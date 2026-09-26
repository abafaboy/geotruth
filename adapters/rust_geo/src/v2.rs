//! Adapter contract v2 (docs/DESIGN.md §4.1, schemas/result.v2.schema.json) for geo.
//!
//! A line is a v2 case when an operand is a typed geometry (a JSON object) or `"ops"` is
//! present (`--v2`: every line). One field path per operation, in this order (`"ops"` selects
//! the groups; absent means everything but `echo`):
//!
//! | path | geo call |
//! |---|---|
//! | `echo` | the operands as built, written back by this module |
//! | `relate` | `a.relate(&b)` (`Relate`, the GeometryGraph port of JTS RelateOp) |
//! | `predicates.<name>` | `IntersectionMatrix::is_<name>()` of that same matrix (derived) |
//! | `valid_a`, `valid_b` | `Validation::is_valid` |
//! | `overlay.<op>` | `BooleanOps::intersection / union / difference / xor` (i_overlay) |
//!
//! Out of geo's contract, reported `"unsupported"`: empty points (geo has no empty Point),
//! unclosed polygon rings (`Polygon::new` would close them, so geo cannot hold the input),
//! non-finite coordinates for relate (geo's documented precondition), and overlays of
//! operands that are not Polygon / MultiPolygon (`BooleanOps` exists for those only).
//! Output coordinates are written by this module: finite doubles with serde_json (ryu, the
//! shortest round-trip form), NaN / Infinity as Python's json module writes them.

use std::io::{self, Write};
use std::time::{Duration, Instant};

use geo::coordinate_position::CoordPos;
use geo::dimensions::Dimensions;
use geo::relate::IntersectionMatrix;
use geo::{
    BooleanOps, Coord, Geometry, GeometryCollection, LineString, MultiLineString, MultiPoint,
    MultiPolygon, Point, Polygon, Relate, Validation,
};
use serde_json::Value;

pub const PREDICATES: [&str; 10] = [
    "intersects", "disjoint", "touches", "crosses", "overlaps", "contains", "covers", "within",
    "covered_by", "equals",
];
pub const OVERLAYS: [&str; 4] = ["intersection", "union", "difference", "symdifference"];

/// Why an operand cannot be held by geo, or why it is malformed.
#[derive(Clone, Debug)]
pub enum BuildError {
    /// outside geo's contract; the reason is kept for debugging
    Unsupported(#[allow(dead_code)] String),
    Malformed(String),
}

pub fn is_v2(case: &Value) -> bool {
    case.get("ops").is_some()
        || case.get("a").is_some_and(Value::is_object)
        || case.get("b").is_some_and(Value::is_object)
}

fn group_of(path: &str) -> &str {
    if path == "valid_a" || path == "valid_b" {
        return "validity";
    }
    path.split('.').next().unwrap_or(path)
}

pub fn all_paths() -> Vec<String> {
    let mut p = vec!["echo".to_string(), "relate".to_string()];
    p.extend(PREDICATES.iter().map(|s| format!("predicates.{s}")));
    p.push("valid_a".into());
    p.push("valid_b".into());
    p.extend(OVERLAYS.iter().map(|s| format!("overlay.{s}")));
    p
}

/// The field paths a case asks for.
pub fn requested(case: &Value) -> Result<Vec<String>, String> {
    let groups: Vec<String> = match case.get("ops") {
        None => ["relate", "predicates", "validity", "overlay"].iter().map(|s| s.to_string()).collect(),
        Some(Value::Array(ops)) => {
            let mut g = Vec::new();
            for o in ops {
                match o.as_str() {
                    Some(s @ ("echo" | "relate" | "predicates" | "validity" | "overlay")) => g.push(s.to_string()),
                    _ => return Err(format!("unknown op {o}")),
                }
            }
            g
        }
        Some(_) => return Err("\"ops\" must be an array".into()),
    };
    Ok(all_paths().into_iter().filter(|p| groups.iter().any(|g| g == group_of(p))).collect())
}

// ------------------------------------------------------------------------------ building

fn num(v: &Value) -> Result<f64, BuildError> {
    v.as_f64().ok_or_else(|| BuildError::Malformed(format!("not a number: {v}")))
}

fn coord(v: &Value) -> Result<Coord<f64>, BuildError> {
    let p = v.as_array().ok_or_else(|| BuildError::Malformed("a position must be an array".into()))?;
    if p.len() < 2 {
        return Err(BuildError::Malformed("a position needs at least 2 numbers".into()));
    }
    Ok(Coord { x: num(&p[0])?, y: num(&p[1])? })
}

fn coords(v: &Value) -> Result<Vec<Coord<f64>>, BuildError> {
    let a = v.as_array().ok_or_else(|| BuildError::Malformed("expected a list of positions".into()))?;
    a.iter().map(coord).collect()
}

fn point(v: &Value) -> Result<Point<f64>, BuildError> {
    if v.as_array().is_some_and(Vec::is_empty) {
        return Err(BuildError::Unsupported("geo has no empty Point".into()));
    }
    Ok(Point(coord(v)?))
}

fn same(a: &Coord<f64>, b: &Coord<f64>) -> bool {
    a.x == b.x && a.y == b.y
}

fn polygon(v: &Value) -> Result<Polygon<f64>, BuildError> {
    let rings = v.as_array().ok_or_else(|| BuildError::Malformed("expected a list of rings".into()))?;
    let mut rs = Vec::with_capacity(rings.len());
    for r in rings {
        let cs = coords(r)?;
        if !cs.is_empty() && !same(&cs[0], &cs[cs.len() - 1]) {
            return Err(BuildError::Unsupported(
                "an unclosed ring: geo's Polygon::new would close it".into(),
            ));
        }
        rs.push(LineString(cs));
    }
    let mut it = rs.into_iter();
    let shell = it.next().unwrap_or_else(|| LineString(vec![]));
    Ok(Polygon::new(shell, it.collect()))
}

/// A geo geometry from typed JSON (or a legacy FORMAT-v1 multipolygon array).
pub fn build(v: Option<&Value>) -> Result<Geometry<f64>, BuildError> {
    let v = v.ok_or_else(|| BuildError::Malformed("missing operand".into()))?;
    if let Some(parts) = v.as_array() {
        let polys = parts.iter().map(polygon).collect::<Result<Vec<_>, _>>()?;
        return Ok(if polys.len() == 1 {
            Geometry::Polygon(polys.into_iter().next().unwrap())
        } else {
            Geometry::MultiPolygon(MultiPolygon(polys))
        });
    }
    let t = v.get("type").and_then(Value::as_str).ok_or_else(|| BuildError::Malformed("geometry without a type".into()))?;
    if t == "GeometryCollection" {
        let gs = v.get("geometries").and_then(Value::as_array).ok_or_else(|| BuildError::Malformed("GeometryCollection needs 'geometries'".into()))?;
        let parts = gs.iter().map(|g| build(Some(g))).collect::<Result<Vec<_>, _>>()?;
        return Ok(Geometry::GeometryCollection(GeometryCollection(parts)));
    }
    let c = v.get("coordinates").ok_or_else(|| BuildError::Malformed(format!("{t} needs 'coordinates'")))?;
    let list = c.as_array().ok_or_else(|| BuildError::Malformed("coordinates must be a list".into()))?;
    Ok(match t {
        "Point" => Geometry::Point(point(c)?),
        "LineString" => Geometry::LineString(LineString(coords(c)?)),
        "Polygon" => Geometry::Polygon(polygon(c)?),
        "MultiPoint" => Geometry::MultiPoint(MultiPoint(list.iter().map(point).collect::<Result<_, _>>()?)),
        "MultiLineString" => Geometry::MultiLineString(MultiLineString(
            list.iter().map(|l| coords(l).map(LineString)).collect::<Result<_, _>>()?,
        )),
        "MultiPolygon" => Geometry::MultiPolygon(MultiPolygon(list.iter().map(polygon).collect::<Result<_, _>>()?)),
        other => return Err(BuildError::Malformed(format!("unknown geometry type {other:?}"))),
    })
}

// ------------------------------------------------------------------------------ writing

/// A double as JSON: shortest round-trip for finite values (serde_json uses ryu), NaN and
/// Infinity as Python's json module writes them.
pub fn fmt(x: f64) -> String {
    if x.is_nan() {
        "NaN".into()
    } else if x.is_infinite() {
        if x > 0.0 { "Infinity".into() } else { "-Infinity".into() }
    } else {
        serde_json::to_string(&x).unwrap_or_else(|_| "null".into())
    }
}

fn pos(out: &mut String, c: &Coord<f64>) {
    out.push('[');
    out.push_str(&fmt(c.x));
    out.push_str(", ");
    out.push_str(&fmt(c.y));
    out.push(']');
}

fn seq(out: &mut String, ls: &LineString<f64>) {
    out.push('[');
    for (i, c) in ls.0.iter().enumerate() {
        if i > 0 {
            out.push_str(", ");
        }
        pos(out, c);
    }
    out.push(']');
}

fn poly(out: &mut String, p: &Polygon<f64>) {
    if p.exterior().0.is_empty() {
        out.push_str("[]");
        return;
    }
    out.push('[');
    seq(out, p.exterior());
    for h in p.interiors() {
        out.push_str(", ");
        seq(out, h);
    }
    out.push(']');
}

/// Typed JSON of a geo geometry (Line, Rect and Triangle as LineString / Polygon).
pub fn geom_json(g: &Geometry<f64>) -> String {
    let mut o = String::new();
    write_geom(&mut o, g);
    o
}

fn write_geom(o: &mut String, g: &Geometry<f64>) {
    match g {
        Geometry::Point(p) => {
            o.push_str("{\"type\": \"Point\", \"coordinates\": ");
            pos(o, &p.0);
        }
        Geometry::Line(l) => {
            o.push_str("{\"type\": \"LineString\", \"coordinates\": ");
            seq(o, &LineString(vec![l.start, l.end]));
        }
        Geometry::LineString(ls) => {
            o.push_str("{\"type\": \"LineString\", \"coordinates\": ");
            seq(o, ls);
        }
        Geometry::Polygon(p) => {
            o.push_str("{\"type\": \"Polygon\", \"coordinates\": ");
            poly(o, p);
        }
        Geometry::Rect(r) => {
            o.push_str("{\"type\": \"Polygon\", \"coordinates\": ");
            poly(o, &r.to_polygon());
        }
        Geometry::Triangle(t) => {
            o.push_str("{\"type\": \"Polygon\", \"coordinates\": ");
            poly(o, &t.to_polygon());
        }
        Geometry::MultiPoint(mp) => {
            o.push_str("{\"type\": \"MultiPoint\", \"coordinates\": [");
            for (i, p) in mp.0.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                pos(o, &p.0);
            }
            o.push(']');
        }
        Geometry::MultiLineString(ml) => {
            o.push_str("{\"type\": \"MultiLineString\", \"coordinates\": [");
            for (i, l) in ml.0.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                seq(o, l);
            }
            o.push(']');
        }
        Geometry::MultiPolygon(mp) => {
            o.push_str("{\"type\": \"MultiPolygon\", \"coordinates\": [");
            for (i, p) in mp.0.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                poly(o, p);
            }
            o.push(']');
        }
        Geometry::GeometryCollection(gc) => {
            o.push_str("{\"type\": \"GeometryCollection\", \"geometries\": [");
            for (i, e) in gc.0.iter().enumerate() {
                if i > 0 {
                    o.push_str(", ");
                }
                write_geom(o, e);
            }
            o.push(']');
        }
    }
    o.push('}');
}

pub fn quote(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"?\"".into())
}

// ------------------------------------------------------------------------------ operations

pub fn de9im(m: &IntersectionMatrix) -> String {
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

fn finite(g: &Geometry<f64>) -> bool {
    use geo::CoordsIter;
    g.coords_iter().all(|c| c.x.is_finite() && c.y.is_finite())
}

fn polygonal(g: &Geometry<f64>) -> Option<MultiPolygon<f64>> {
    match g {
        Geometry::Polygon(p) => Some(MultiPolygon(vec![p.clone()])),
        Geometry::MultiPolygon(mp) => Some(mp.clone()),
        _ => None,
    }
}

/// One case on the library side: both operands built once; the relate matrix is computed
/// once and shared by the predicates (they are derived from it).
pub struct Session {
    a: Result<Geometry<f64>, BuildError>,
    b: Result<Geometry<f64>, BuildError>,
    matrix: Option<IntersectionMatrix>,
}

/// An operation's outcome: a JSON value, or an error message (JSON text).
pub enum Outcome {
    Value(String),
    Unsupported,
    Error(String),
}

impl Session {
    pub fn new(case: &Value) -> Session {
        Session { a: build(case.get("a")), b: build(case.get("b")), matrix: None }
    }

    fn operands(&self, need_a: bool, need_b: bool) -> Result<(), Outcome> {
        for (need, g, tag) in [(need_a, &self.a, "A"), (need_b, &self.b, "B")] {
            if !need {
                continue;
            }
            match g {
                Err(BuildError::Unsupported(_)) => return Err(Outcome::Unsupported),
                Err(BuildError::Malformed(m)) => return Err(Outcome::Error(quote(&format!("building {tag}: {m}")))),
                Ok(_) => {}
            }
        }
        Ok(())
    }

    /// Computes one field path (the caller catches panics).
    pub fn run(&mut self, path: &str) -> Outcome {
        let need_a = path != "valid_b";
        let need_b = path != "valid_a";
        if let Err(o) = self.operands(need_a, need_b) {
            return o;
        }
        match path {
            "echo" => {
                let (a, b) = (self.a.as_ref().unwrap(), self.b.as_ref().unwrap());
                Outcome::Value(format!("{{\"a\": {}, \"b\": {}}}", geom_json(a), geom_json(b)))
            }
            "valid_a" => Outcome::Value(self.a.as_ref().unwrap().is_valid().to_string()),
            "valid_b" => Outcome::Value(self.b.as_ref().unwrap().is_valid().to_string()),
            "relate" => match self.matrix() {
                Some(m) => Outcome::Value(quote(&de9im(&m))),
                None => Outcome::Unsupported,
            },
            p if p.starts_with("predicates.") => {
                let Some(m) = self.matrix() else { return Outcome::Unsupported };
                let v = match &p["predicates.".len()..] {
                    "intersects" => m.is_intersects(),
                    "disjoint" => m.is_disjoint(),
                    "touches" => m.is_touches(),
                    "crosses" => m.is_crosses(),
                    "overlaps" => m.is_overlaps(),
                    "contains" => m.is_contains(),
                    "covers" => m.is_covers(),
                    "within" => m.is_within(),
                    "covered_by" => m.is_coveredby(),
                    "equals" => m.is_equal_topo(),
                    other => return Outcome::Error(quote(&format!("unknown predicate {other}"))),
                };
                Outcome::Value(v.to_string())
            }
            p if p.starts_with("overlay.") => {
                let (a, b) = (self.a.as_ref().unwrap(), self.b.as_ref().unwrap());
                let (Some(x), Some(y)) = (polygonal(a), polygonal(b)) else { return Outcome::Unsupported };
                let r = match &p["overlay.".len()..] {
                    "intersection" => x.intersection(&y),
                    "union" => x.union(&y),
                    "difference" => x.difference(&y),
                    _ => x.xor(&y),
                };
                Outcome::Value(geom_json(&Geometry::MultiPolygon(r)))
            }
            other => Outcome::Error(quote(&format!("unknown field path {other}"))),
        }
    }

    fn matrix(&mut self) -> Option<IntersectionMatrix> {
        if self.matrix.is_none() {
            let (a, b) = (self.a.as_ref().unwrap(), self.b.as_ref().unwrap());
            if !(finite(a) && finite(b)) {
                return None; // Relate must not be called on NaN coordinates (geo's docs)
            }
            self.matrix = Some(a.relate(b));
        }
        self.matrix.clone()
    }
}

// ------------------------------------------------------------------------------ records

/// One operation's result as sent by the worker and assembled by the supervisor.
#[derive(Clone)]
pub struct OpResult {
    pub value: String,
    pub error: Option<String>,
    pub ms: f64,
}

impl OpResult {
    pub fn failed(error: String) -> OpResult {
        OpResult { value: "null".into(), error: Some(error), ms: -1.0 }
    }
}

pub fn outcome_result(o: Outcome, ms: f64) -> OpResult {
    match o {
        Outcome::Value(v) => OpResult { value: v, error: None, ms },
        Outcome::Unsupported => OpResult { value: "\"unsupported\"".into(), error: None, ms },
        Outcome::Error(e) => OpResult { value: "null".into(), error: Some(e), ms },
    }
}

/// The result line of a case.
pub fn render(lib: &str, id: &Value, paths: &[String], res: &[OpResult], timing: bool) -> String {
    let get = |p: &str| paths.iter().position(|x| x == p).map(|i| &res[i]);
    let mut o = format!("{{\"id\": {}, \"lib\": {}", serde_json::to_string(id).unwrap_or("null".into()), quote(lib));
    if let Some(r) = get("relate") {
        o.push_str(&format!(", \"relate\": {}", r.value));
    }
    if get("predicates.intersects").is_some() {
        o.push_str(", \"predicates\": {");
        for (i, p) in PREDICATES.iter().enumerate() {
            if i > 0 {
                o.push_str(", ");
            }
            o.push_str(&format!("\"{p}\": {}", get(&format!("predicates.{p}")).unwrap().value));
        }
        o.push('}');
    }
    if let Some(r) = get("valid_a") {
        o.push_str(&format!(", \"valid_a\": {}, \"valid_b\": {}", r.value, get("valid_b").unwrap().value));
    }
    if get("overlay.intersection").is_some() {
        o.push_str(", \"overlay\": {");
        for (i, p) in OVERLAYS.iter().enumerate() {
            if i > 0 {
                o.push_str(", ");
            }
            o.push_str(&format!("\"{p}\": {}", get(&format!("overlay.{p}")).unwrap().value));
        }
        o.push('}');
    }
    if let Some(r) = get("echo") {
        if r.value != "null" {
            o.push_str(&format!(", \"echo\": {}", r.value));
        }
    }
    o.push_str(", \"errors\": {");
    let mut first = true;
    for (p, r) in paths.iter().zip(res) {
        if let Some(e) = &r.error {
            if !first {
                o.push_str(", ");
            }
            first = false;
            o.push_str(&format!("\"{p}\": {e}"));
        }
    }
    o.push('}');
    if timing {
        o.push_str(", \"elapsed_ms\": {");
        let mut first = true;
        for (p, r) in paths.iter().zip(res) {
            if r.ms >= 0.0 {
                if !first {
                    o.push_str(", ");
                }
                first = false;
                o.push_str(&format!("\"{p}\": {:.3}", r.ms));
            }
        }
        o.push('}');
    }
    o.push('}');
    o
}

/// The failure record of a line that cannot be read.
pub fn render_failed(lib: &str, id: &Value, msg: &str) -> String {
    format!(
        "{{\"id\": {}, \"lib\": {}, \"errors\": {{\"*\": {}}}}}",
        serde_json::to_string(id).unwrap_or("null".into()),
        quote(lib),
        quote(msg)
    )
}

// ------------------------------------------------------------------------------ worker side

/// Worker: answers `v2:<start>\t<case>`; one line `<k>\t<value>\t<error>\t<ms>` per path.
pub fn worker_answer(
    out: &mut impl Write,
    start: usize,
    case_json: &str,
    guarded: &dyn Fn(&mut dyn FnMut() -> Outcome) -> Outcome,
    fault: &dyn Fn(&str),
) -> io::Result<()> {
    let case: Value = serde_json::from_str(case_json).unwrap_or(Value::Null);
    let paths = requested(&case).unwrap_or_default();
    let mut session = Session::new(&case);
    for (k, p) in paths.iter().enumerate().skip(start) {
        let t0 = Instant::now();
        let o = guarded(&mut || {
            fault(p);
            session.run(p)
        });
        let r = outcome_result(o, t0.elapsed().as_secs_f64() * 1000.0);
        writeln!(out, "{k}\t{}\t{}\t{}", r.value, r.error.unwrap_or_default(), r.ms)?;
        out.flush()?;
    }
    Ok(())
}

/// Parse a worker line into (k, OpResult).
pub fn parse_worker_line(line: &str) -> Option<(usize, OpResult)> {
    let f: Vec<&str> = line.splitn(4, '\t').collect();
    if f.len() != 4 {
        return None;
    }
    let k = f[0].parse().ok()?;
    let error = if f[2].is_empty() { None } else { Some(f[2].to_string()) };
    Some((k, OpResult { value: f[1].to_string(), error, ms: f[3].trim().parse().unwrap_or(-1.0) }))
}

pub fn timeout_error(t: Duration) -> String {
    format!("{{\"kind\": \"timeout\", \"message\": {}}}", quote(&format!("no result after {} s (worker killed)", t.as_secs_f64())))
}

pub fn crash_error(how: &str) -> String {
    format!("{{\"kind\": \"crash\", \"message\": {}}}", quote(how))
}
