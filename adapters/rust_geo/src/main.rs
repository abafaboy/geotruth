//! Adapter for the georust `geo` crate (see ../../FORMAT.md and README.md).
//!
//! usage: geo_adapter [--in-process] CASES.jsonl > RESULTS.jsonl
//!        geo_adapter --version
//!
//! By default the process is a supervisor: it feeds each case to a worker child (this same
//! binary, `--worker`) and reads back one JSON line per operation ("unit"). Every unit runs
//! under `catch_unwind`, so panics become `errors` entries; a unit that hangs past the
//! timeout, or kills the worker (abort, stack overflow, out of memory), is reported for
//! that unit only and a fresh worker carries on with the next unit.

use std::collections::VecDeque;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::panic::{self, AssertUnwindSafe};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use geo::coordinate_position::CoordPos;
use geo::dimensions::Dimensions;
use geo::relate::IntersectionMatrix;
use geo::{
    Area, BooleanOps, Contains, ContainsProperly, Coord, Covers, Intersects, LineString,
    MultiPolygon, Polygon, PreparedGeometry, Relate, Validation, Within,
};
use serde_json::{json, Map, Value};

const LIB: &str = concat!("geo@", env!("GEO_VERSION"));
const LIB_DETAIL: &str = concat!("geo@", env!("GEO_VERSION"), " (i_overlay@", env!("I_OVERLAY_VERSION"), ")");

const PREDICATES: [&str; 9] = [
    "intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within", "covered_by",
    "equals",
];
const STANDARD: [&str; 15] = [
    "valid_a", "valid_b", "intersects", "disjoint", "touches", "overlaps", "contains", "covers",
    "within", "covered_by", "equals", "area_inter", "area_union", "area_diff", "area_symdiff",
];

/// One isolated operation. `keys` are the standard result fields it fills; an empty `keys`
/// marks an "alt" unit whose answer only goes into the extra `alt` object.
struct Unit {
    name: &'static str,
    keys: &'static [&'static str],
}

const UNITS: &[Unit] = &[
    Unit { name: "valid_a", keys: &["valid_a"] },
    Unit { name: "valid_b", keys: &["valid_b"] },
    Unit { name: "relate", keys: &PREDICATES },
    Unit { name: "area_inter", keys: &["area_inter"] },
    Unit { name: "area_union", keys: &["area_union"] },
    Unit { name: "area_diff", keys: &["area_diff"] },
    Unit { name: "area_symdiff", keys: &["area_symdiff"] },
    // alt units: trait-based answers, compared with the Relate-based ones by the supervisor
    Unit { name: "Intersects", keys: &[] },
    Unit { name: "Contains", keys: &[] },
    Unit { name: "Within", keys: &[] },
    Unit { name: "Covers", keys: &[] },
    Unit { name: "CoveredBy", keys: &[] },
    Unit { name: "ContainsProperly", keys: &[] },
    Unit { name: "relate_ba", keys: &[] },
    Unit { name: "relate_prepared", keys: &[] },
];

/// Which Relate-based answer each alt unit is compared with.
fn alt_baseline(name: &str) -> &'static str {
    match name {
        "Intersects" => "intersects",
        "Contains" => "contains",
        "Within" => "within",
        "Covers" => "covers",
        "CoveredBy" => "covered_by",
        "ContainsProperly" => "_contains_properly",
        _ => "de9im", // relate_ba, relate_prepared
    }
}

// ---------------------------------------------------------------------------------------
// geometry
// ---------------------------------------------------------------------------------------

enum G {
    P(Polygon<f64>),
    M(MultiPolygon<f64>),
}

/// Runs `$body` with `$x`, `$y` bound to the concrete geometry types of `$a`, `$b`.
macro_rules! d2 {
    ($a:expr, $b:expr, |$x:ident, $y:ident| $body:expr) => {
        match ($a, $b) {
            (G::P($x), G::P($y)) => $body,
            (G::P($x), G::M($y)) => $body,
            (G::M($x), G::P($y)) => $body,
            (G::M($x), G::M($y)) => $body,
        }
    };
}
macro_rules! d1 {
    ($a:expr, |$x:ident| $body:expr) => {
        match $a {
            G::P($x) => $body,
            G::M($x) => $body,
        }
    };
}

fn build_ring(v: &Value) -> Result<LineString<f64>, String> {
    let pts = v.as_array().ok_or("ring is not an array")?;
    let mut coords = Vec::with_capacity(pts.len());
    for p in pts {
        let xy = p.as_array().ok_or("point is not an array")?;
        if xy.len() < 2 {
            return Err("point has fewer than 2 ordinates".into());
        }
        let x = xy[0].as_f64().ok_or("x is not a number")?;
        let y = xy[1].as_f64().ok_or("y is not a number")?;
        coords.push(Coord { x, y });
    }
    Ok(LineString(coords))
}

fn build(v: Option<&Value>) -> Result<G, String> {
    let parts = v.and_then(Value::as_array).ok_or("not a list of polygons")?;
    let mut polys = Vec::with_capacity(parts.len());
    for p in parts {
        let rings = p.as_array().ok_or("polygon is not a list of rings")?;
        let mut it = rings.iter();
        let shell = match it.next() {
            Some(r) => build_ring(r)?,
            None => LineString(vec![]),
        };
        let holes = it.map(build_ring).collect::<Result<Vec<_>, _>>()?;
        polys.push(Polygon::new(shell, holes));
    }
    Ok(if polys.len() == 1 {
        G::P(polys.pop().unwrap())
    } else {
        G::M(MultiPolygon(polys))
    })
}

fn de9im(m: &IntersectionMatrix) -> String {
    let pos = [CoordPos::Inside, CoordPos::OnBoundary, CoordPos::Outside];
    let mut s = String::with_capacity(9);
    for r in pos {
        for c in pos {
            s.push(match m.get(r, c) {
                Dimensions::Empty => 'F',
                Dimensions::ZeroDimensional => '0',
                Dimensions::OneDimensional => '1',
                Dimensions::TwoDimensional => '2',
            });
        }
    }
    s
}

fn transpose(s: &str) -> String {
    let c: Vec<char> = s.chars().collect();
    if c.len() != 9 {
        return s.to_string();
    }
    (0..9).map(|k| c[(k % 3) * 3 + k / 3]).collect()
}

/// `T**FF*FF*`, the IntersectionMatrix::is_contains_properly pattern.
fn contains_properly_from_de9im(s: &str) -> Option<bool> {
    let c: Vec<char> = s.chars().collect();
    (c.len() == 9).then(|| c[0] != 'F' && c[3] == 'F' && c[4] == 'F' && c[6] == 'F' && c[7] == 'F')
}

// ---------------------------------------------------------------------------------------
// panics
// ---------------------------------------------------------------------------------------

static LAST_PANIC: Mutex<Option<String>> = Mutex::new(None);

fn payload_str(p: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = p.downcast_ref::<&str>() {
        s.to_string()
    } else if let Some(s) = p.downcast_ref::<String>() {
        s.clone()
    } else {
        "<non-string panic payload>".to_string()
    }
}

fn short_path(file: &str) -> &str {
    // ".../registry/src/index.crates.io-xxxx/geo-0.33.1/src/x.rs" -> "geo-0.33.1/src/x.rs"
    if let Some(i) = file.find("/registry/src/") {
        let rest = &file[i + "/registry/src/".len()..];
        if let Some(j) = rest.find('/') {
            return &rest[j + 1..];
        }
    }
    file
}

fn install_panic_hook() {
    panic::set_hook(Box::new(|info| {
        let msg = payload_str(info.payload());
        let loc = info
            .location()
            .map(|l| format!(" at {}:{}:{}", short_path(l.file()), l.line(), l.column()))
            .unwrap_or_default();
        // GEO_ADAPTER_BACKTRACE=1 appends the geo / i_overlay frames of the panic backtrace
        let bt = if std::env::var_os("GEO_ADAPTER_BACKTRACE").is_some_and(|v| v != "0") {
            let full = std::backtrace::Backtrace::force_capture().to_string();
            let frames: Vec<&str> = full
                .lines()
                .map(str::trim)
                .filter(|l| l.contains(": geo::") || l.contains(": i_overlay::") || l.contains(": i_float::"))
                .map(|l| l.split_once(": ").map_or(l, |(_, f)| f))
                .collect();
            format!(" [backtrace: {}]", frames.join(" <- "))
        } else {
            String::new()
        };
        let mut g = LAST_PANIC.lock().unwrap_or_else(|e| e.into_inner());
        *g = Some(format!("{msg}{loc}{bt}"));
    }));
}

fn guarded<T>(f: impl FnOnce() -> T) -> Result<T, String> {
    *LAST_PANIC.lock().unwrap_or_else(|e| e.into_inner()) = None;
    match panic::catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => Ok(v),
        Err(p) => {
            let hooked = LAST_PANIC.lock().unwrap_or_else(|e| e.into_inner()).take();
            Err(format!("panic: {}", hooked.unwrap_or_else(|| payload_str(&*p))))
        }
    }
}

// ---------------------------------------------------------------------------------------
// operations
// ---------------------------------------------------------------------------------------

/// Test hook: GEO_ADAPTER_TEST_FAULT=<panic|abort|hang|overflow>:<unit name>
fn inject_fault(unit: &str) {
    let Ok(spec) = std::env::var("GEO_ADAPTER_TEST_FAULT") else { return };
    let Some((kind, name)) = spec.split_once(':') else { return };
    if name != unit {
        return;
    }
    match kind {
        "panic" => panic!("injected test panic"),
        "abort" => std::process::abort(),
        "hang" => loop {
            thread::sleep(Duration::from_secs(3600))
        },
        "overflow" => {
            #[allow(unconditional_recursion)]
            fn rec(n: u64) -> u64 {
                let buf = [n; 64];
                std::hint::black_box(&buf);
                rec(n + 1) + buf[3]
            }
            std::hint::black_box(rec(0));
        }
        _ => {}
    }
}

fn finite_area(x: f64) -> Result<Value, String> {
    if x.is_finite() {
        Ok(json!(x))
    } else {
        Err(format!("non-finite area: {x}"))
    }
}

/// Computes one unit. Returns (fields, errors). Standard units fill their `keys`; alt units
/// fill `fields[name]`. Extra fields (de9im, invalid_reason_*) ride along in `fields`.
fn run_unit(u: usize, a: &Result<G, String>, b: &Result<G, String>) -> (Map<String, Value>, Map<String, Value>) {
    let unit = &UNITS[u];
    let mut f = Map::new();
    let mut e = Map::new();
    let err_all = |e: &mut Map<String, Value>, msg: String| {
        if unit.keys.is_empty() {
            e.insert(unit.name.into(), json!(msg));
        }
        for k in unit.keys {
            e.insert((*k).into(), json!(msg));
        }
    };
    // validity needs only its own operand
    if unit.name == "valid_a" || unit.name == "valid_b" {
        let (g, tag) = if unit.name == "valid_a" { (a, "a") } else { (b, "b") };
        match g {
            Err(m) => err_all(&mut e, format!("building {}: {m}", tag.to_uppercase())),
            Ok(g) => match guarded(|| {
                inject_fault(unit.name);
                d1!(g, |x| x.check_validation().err().map(|err| err.to_string()))
            }) {
                Ok(None) => {
                    f.insert(unit.name.into(), json!(true));
                }
                Ok(Some(why)) => {
                    f.insert(unit.name.into(), json!(false));
                    f.insert(format!("invalid_reason_{tag}"), json!(why));
                }
                Err(m) => err_all(&mut e, m),
            },
        }
        return (f, e);
    }
    let (a, b) = match (a, b) {
        (Ok(a), Ok(b)) => (a, b),
        (Err(m), _) => {
            err_all(&mut e, format!("building A: {m}"));
            return (f, e);
        }
        (_, Err(m)) => {
            err_all(&mut e, format!("building B: {m}"));
            return (f, e);
        }
    };
    let r: Result<Map<String, Value>, String> = guarded(|| {
        inject_fault(unit.name);
        let mut o = Map::new();
        match unit.name {
            "relate" => {
                let m = d2!(a, b, |x, y| x.relate(y));
                o.insert("intersects".into(), json!(m.is_intersects()));
                o.insert("disjoint".into(), json!(m.is_disjoint()));
                o.insert("touches".into(), json!(m.is_touches()));
                o.insert("overlaps".into(), json!(m.is_overlaps()));
                o.insert("contains".into(), json!(m.is_contains()));
                o.insert("covers".into(), json!(m.is_covers()));
                o.insert("within".into(), json!(m.is_within()));
                o.insert("covered_by".into(), json!(m.is_coveredby()));
                o.insert("equals".into(), json!(m.is_equal_topo()));
                o.insert("de9im".into(), json!(de9im(&m)));
            }
            "area_inter" | "area_union" | "area_diff" | "area_symdiff" => {
                let area = d2!(a, b, |x, y| match unit.name {
                    "area_inter" => x.intersection(y),
                    "area_union" => x.union(y),
                    "area_diff" => x.difference(y),
                    _ => x.xor(y),
                }
                .unsigned_area());
                match finite_area(area) {
                    Ok(v) => {
                        o.insert(unit.name.into(), v);
                    }
                    Err(m) => {
                        o.insert("_error".into(), json!(m));
                    }
                }
            }
            "Intersects" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| x.intersects(y))));
            }
            "Contains" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| x.contains(y))));
            }
            "Within" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| x.is_within(y))));
            }
            "Covers" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| x.covers(y))));
            }
            "CoveredBy" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| y.covers(x))));
            }
            "ContainsProperly" => {
                o.insert(unit.name.into(), json!(d2!(a, b, |x, y| x.contains_properly(y))));
            }
            "relate_ba" => {
                let m = d2!(a, b, |x, y| y.relate(x));
                o.insert(unit.name.into(), json!(transpose(&de9im(&m))));
            }
            "relate_prepared" => {
                let m = d2!(a, b, |x, y| {
                    let pa = PreparedGeometry::from(x);
                    let pb = PreparedGeometry::from(y);
                    pa.relate(&pb)
                });
                o.insert(unit.name.into(), json!(de9im(&m)));
            }
            other => unreachable!("unknown unit {other}"),
        }
        o
    });
    match r {
        Ok(mut o) => {
            if let Some(Value::String(m)) = o.remove("_error") {
                err_all(&mut e, m);
            }
            f = o;
        }
        Err(m) => err_all(&mut e, m),
    }
    (f, e)
}

// ---------------------------------------------------------------------------------------
// worker
// ---------------------------------------------------------------------------------------

fn limit_memory() {
    let mb: u64 = std::env::var("GEO_ADAPTER_MEM_MB")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(4096);
    if mb == 0 {
        return;
    }
    let lim = libc::rlimit { rlim_cur: mb << 20, rlim_max: mb << 20 };
    unsafe {
        libc::setrlimit(libc::RLIMIT_AS, &lim);
    }
}

/// Protocol: stdin lines `<first unit>\t<case json>`; for every unit from `first` on, one
/// stdout line `{"u": index, "f": {fields}, "e": {errors}}`.
fn worker_main() -> io::Result<()> {
    limit_memory();
    install_panic_hook();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line?;
        let Some((start, js)) = line.split_once('\t') else { continue };
        let start: usize = start.parse().unwrap_or(0);
        let case: Value = serde_json::from_str(js).unwrap_or(Value::Null);
        let a = build(case.get("a"));
        let b = build(case.get("b"));
        for u in start..UNITS.len() {
            let (f, e) = run_unit(u, &a, &b);
            writeln!(out, "{}", json!({"u": u, "f": f, "e": e}))?;
            out.flush()?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------
// supervisor
// ---------------------------------------------------------------------------------------

struct Worker {
    child: Child,
    stdin: ChildStdin,
    rx: Receiver<String>,
    stderr_tail: Arc<Mutex<VecDeque<String>>>,
    stderr_thread: Option<JoinHandle<()>>,
}

impl Worker {
    fn spawn() -> io::Result<Worker> {
        let exe = std::env::current_exe()?;
        let mut child = Command::new(exe)
            .arg("--worker")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        let stderr_tail = Arc::new(Mutex::new(VecDeque::new()));
        let tail = stderr_tail.clone();
        let stderr_thread = thread::spawn(move || {
            for line in BufReader::new(stderr).lines() {
                let Ok(line) = line else { break };
                if line.trim().is_empty() {
                    continue;
                }
                let mut t = tail.lock().unwrap();
                t.push_back(line);
                if t.len() > 6 {
                    t.pop_front();
                }
            }
        });
        Ok(Worker { child, stdin, rx, stderr_tail, stderr_thread: Some(stderr_thread) })
    }

    /// Kills (if needed) and reaps the worker; returns a description of how it ended.
    fn finish(mut self, kill: bool) -> String {
        if kill {
            let _ = self.child.kill();
        }
        let status = self.child.wait();
        if let Some(t) = self.stderr_thread.take() {
            let _ = t.join();
        }
        let tail: Vec<String> = self.stderr_tail.lock().unwrap().drain(..).collect();
        let how = match status {
            Ok(s) => {
                use std::os::unix::process::ExitStatusExt;
                match (s.code(), s.signal()) {
                    (_, Some(sig)) => format!("signal {sig} ({})", signal_name(sig)),
                    (Some(c), _) => format!("exit status {c}"),
                    _ => "unknown status".into(),
                }
            }
            Err(e) => format!("wait failed: {e}"),
        };
        if tail.is_empty() {
            how
        } else {
            format!("{how}; stderr: {}", tail.join(" | "))
        }
    }
}

fn signal_name(sig: i32) -> &'static str {
    match sig {
        libc::SIGSEGV => "SIGSEGV",
        libc::SIGABRT => "SIGABRT",
        libc::SIGKILL => "SIGKILL",
        libc::SIGBUS => "SIGBUS",
        libc::SIGILL => "SIGILL",
        libc::SIGFPE => "SIGFPE",
        _ => "?",
    }
}

fn record_failure(unit: &Unit, msg: &str, fields: &mut Map<String, Value>, errors: &mut Map<String, Value>) {
    if unit.keys.is_empty() {
        errors.insert(unit.name.into(), json!(msg));
    }
    for k in unit.keys {
        fields.remove(*k);
        errors.insert((*k).into(), json!(msg));
    }
}

/// Runs all units of one case, isolating each in the worker. Returns merged (fields, errors),
/// where errors of alt units are keyed by the unit name.
fn run_case_isolated(
    worker: &mut Option<Worker>,
    line: &str,
    timeout: Duration,
    timeouts: &mut Vec<&'static str>,
) -> (Map<String, Value>, Map<String, Value>) {
    let mut fields = Map::new();
    let mut errors = Map::new();
    let mut start = 0;
    let mut write_failures = 0;
    while start < UNITS.len() {
        if worker.is_none() {
            match Worker::spawn() {
                Ok(w) => *worker = Some(w),
                Err(e) => {
                    for u in &UNITS[start..] {
                        record_failure(u, &format!("cannot start worker: {e}"), &mut fields, &mut errors);
                    }
                    break;
                }
            }
        }
        let w = worker.as_mut().unwrap();
        if writeln!(w.stdin, "{start}\t{line}").and_then(|_| w.stdin.flush()).is_err() {
            let how = worker.take().unwrap().finish(true);
            write_failures += 1;
            if write_failures >= 2 {
                for u in &UNITS[start..] {
                    record_failure(u, &format!("crash: worker unusable: {how}"), &mut fields, &mut errors);
                }
                break;
            }
            continue;
        }
        let mut u = start;
        while u < UNITS.len() {
            match worker.as_ref().unwrap().rx.recv_timeout(timeout) {
                Ok(msg) => {
                    let v: Value = serde_json::from_str(&msg).unwrap_or(Value::Null);
                    if v.get("u").and_then(Value::as_u64) != Some(u as u64) {
                        // protocol confusion: treat as a crash of this unit
                        let how = worker.take().unwrap().finish(true);
                        record_failure(&UNITS[u], &format!("crash: bad worker output ({how}): {msg}"), &mut fields, &mut errors);
                        u += 1;
                        break;
                    }
                    if let Some(Value::Object(f)) = v.get("f") {
                        fields.extend(f.clone());
                    }
                    if let Some(Value::Object(e)) = v.get("e") {
                        errors.extend(e.clone());
                    }
                    u += 1;
                }
                Err(RecvTimeoutError::Timeout) => {
                    let _ = worker.take().unwrap().finish(true);
                    record_failure(
                        &UNITS[u],
                        &format!("timeout: no result after {} s", timeout.as_secs_f64()),
                        &mut fields,
                        &mut errors,
                    );
                    timeouts.push(UNITS[u].name);
                    u += 1;
                    break;
                }
                Err(RecvTimeoutError::Disconnected) => {
                    let how = worker.take().unwrap().finish(false);
                    record_failure(&UNITS[u], &format!("crash: worker died: {how}"), &mut fields, &mut errors);
                    u += 1;
                    break;
                }
            }
        }
        start = u;
    }
    (fields, errors)
}

fn run_case_in_process(line: &str) -> (Map<String, Value>, Map<String, Value>) {
    let case: Value = serde_json::from_str(line).unwrap_or(Value::Null);
    let a = build(case.get("a"));
    let b = build(case.get("b"));
    let mut fields = Map::new();
    let mut errors = Map::new();
    for u in 0..UNITS.len() {
        let (f, e) = run_unit(u, &a, &b);
        fields.extend(f);
        errors.extend(e);
    }
    (fields, errors)
}

/// Assembles the output record from the merged unit results.
fn assemble(id: Value, mut fields: Map<String, Value>, mut errors: Map<String, Value>, timeouts: &[&str]) -> Value {
    let mut out = Map::new();
    out.insert("id".into(), id);
    out.insert("lib".into(), json!(LIB));
    for k in STANDARD {
        out.insert(k.into(), fields.remove(k).unwrap_or(Value::Null));
    }
    // alt: trait-based answers that differ from the Relate-based ones (or stand alone
    // because the Relate-based one is missing), and alt-unit errors.
    let de9im = fields.get("de9im").cloned();
    let cp = de9im
        .as_ref()
        .and_then(Value::as_str)
        .and_then(contains_properly_from_de9im)
        .map(|b| json!(b));
    let mut alt = Map::new();
    for unit in UNITS.iter().filter(|u| u.keys.is_empty()) {
        if let Some(msg) = errors.remove(unit.name) {
            alt.insert(unit.name.into(), msg);
            continue;
        }
        let Some(val) = fields.remove(unit.name) else { continue };
        let base = alt_baseline(unit.name);
        let base_val = match base {
            "_contains_properly" => cp.clone(),
            "de9im" => de9im.clone(),
            k => out.get(k).cloned().filter(|v| !v.is_null()),
        };
        if base_val.as_ref() != Some(&val) {
            alt.insert(unit.name.into(), val);
        }
    }
    let mut errs = Map::new();
    for (k, v) in errors {
        errs.insert(k, v);
    }
    if !timeouts.is_empty() {
        errs.insert("timeout".into(), json!(timeouts.join(",")));
    }
    out.insert("errors".into(), Value::Object(errs));
    for k in ["de9im", "invalid_reason_a", "invalid_reason_b"] {
        if let Some(v) = fields.remove(k) {
            out.insert(k.into(), v);
        }
    }
    if !alt.is_empty() {
        out.insert("alt".into(), Value::Object(alt));
    }
    Value::Object(out)
}

fn supervisor_main(path: &str, in_process: bool) -> io::Result<()> {
    let timeout = Duration::from_secs_f64(
        std::env::var("GEO_ADAPTER_TIMEOUT")
            .ok()
            .and_then(|s| s.parse::<f64>().ok())
            .filter(|t| *t > 0.0)
            .unwrap_or(10.0),
    );
    if in_process {
        install_panic_hook();
    }
    let input = BufReader::new(std::fs::File::open(path)?);
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    let mut worker: Option<Worker> = None;
    for line in input.lines() {
        let line = line?;
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let rec = match serde_json::from_str::<Value>(line) {
            Err(e) => {
                let mut r = Map::new();
                r.insert("id".into(), Value::Null);
                r.insert("lib".into(), json!(LIB));
                for k in STANDARD {
                    r.insert(k.into(), Value::Null);
                }
                r.insert("errors".into(), json!({"parse": e.to_string()}));
                Value::Object(r)
            }
            Ok(case) => {
                let id = case.get("id").cloned().unwrap_or(Value::Null);
                let mut timeouts = Vec::new();
                let (f, e) = if in_process {
                    run_case_in_process(line)
                } else {
                    run_case_isolated(&mut worker, line, timeout, &mut timeouts)
                };
                assemble(id, f, e, &timeouts)
            }
        };
        writeln!(out, "{rec}")?;
        out.flush()?;
    }
    if let Some(w) = worker {
        drop(w.stdin);
        let mut child = w.child;
        let _ = child.wait();
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--worker") {
        if let Err(e) = worker_main() {
            eprintln!("worker: {e}");
            std::process::exit(1);
        }
        return;
    }
    if args.iter().any(|a| a == "--version") {
        println!("{LIB_DETAIL}");
        return;
    }
    let in_process = args.iter().any(|a| a == "--in-process");
    let files: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();
    if files.len() != 1 {
        eprintln!("usage: geo_adapter [--in-process] CASES.jsonl > RESULTS.jsonl");
        std::process::exit(2);
    }
    if let Err(e) = supervisor_main(files[0], in_process) {
        eprintln!("geo_adapter: {e}");
        std::process::exit(1);
    }
}
