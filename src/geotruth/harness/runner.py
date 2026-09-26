"""The runner (DESIGN §4, §5.3): one adapter target over one corpus tier.

``geotruth run --lib <target> [--tier core|full|curated] [--prefix PATH]`` builds nothing.
It

1. finds the target in the adapter manifests (``adapters/*/adapter.toml``) and checks that
   it is built by running its ``version_command`` (a missing build fails with the build
   recipe);
2. resolves the tier's case files from ``corpus/MANIFEST.json`` (``--cases`` names files
   directly) and feeds the cases, as v2 typed JSON (legacy FORMAT-v1 operands converted),
   to the adapter's ``run`` command;
3. enforces the per-operation timeout (default 3 s, passed to the adapter through
   ``GEOTRUTH_OP_TIMEOUT`` and the adapters' own variables; each adapter isolates its
   operations) and a watchdog of its own: when no result line arrives within
   ``(ops + 1) * timeout + slack`` the adapter's process group is killed, that case is
   recorded as a timeout and the adapter restarts on the next case; an adapter that exits
   early is restarted the same way (the case gets a crash);
4. stops at the per-library wall budget (the cases not run are counted in ``stats.json``);
5. validates every result line against ``schemas/result.v2.schema.json``; a line that
   violates it (or answers another case) is replaced by an error record and kept verbatim
   in ``invalid.jsonl``;
6. writes ``<out>/<target>/<tier>.jsonl``, the provenance record ``run.json``
   (``schemas/run.v2``: library version and commit, adapter git hash and manifest hash,
   compiler and flags, non-default options, engine and corpus versions, runner image) and
   ``stats.json`` (counts, timing, the case files).

``--prefix PATH`` runs a maintainer's own build: PATH is exported as the adapter's
``build_root_override`` variable (for example ``BUILD_ROOT`` of ``adapters/geos_main``), so
a tree built with ``BUILD_ROOT=PATH adapters/geos_main/build.sh`` is used; for an adapter
without one (Shapely) PATH is prepended to ``PYTHONPATH``.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import platform
import select
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.harness.manifest import Target, repo_root
from geotruth.io import case_from_json, case_to_json
from geotruth.numbers import json_loads

__all__ = [
    "TIERS",
    "TIMEOUT_ENV_VARS",
    "RunOptions",
    "RunReport",
    "corpus_dir",
    "corpus_version",
    "load_cases",
    "resolve_tier",
    "run_target",
]

TIERS = ("core", "full", "curated", "seed")

#: Per-operation timeout variables of the adapters (all set to the runner's timeout).
TIMEOUT_ENV_VARS = (
    "GEOTRUTH_OP_TIMEOUT",
    "GEOS_ADAPTER_TIMEOUT",
    "BG_ADAPTER_TIMEOUT",
    "CGAL_ADAPTER_TIMEOUT",
    "CLIPPER2_ADAPTER_TIMEOUT",
    "JS_ADAPTER_TIMEOUT",
    "GEO_ADAPTER_TIMEOUT",
    "JTS_ADAPTER_TIMEOUT",
    "SHAPELY_ADAPTER_TIMEOUT",
    "CONTROL_ADAPTER_TIMEOUT",
    "MUTANT_ADAPTER_TIMEOUT",
)

#: Operations per case for the default groups (relate, 10 predicates, 2 validity, 4 overlay).
_OPS_PER_CASE = 17
#: Seconds allowed on top of the adapter's own timeouts (start-up of a JVM or Node).
_STARTUP_SLACK = 60.0
_LINE_SLACK = 10.0


def corpus_dir() -> Path:
    env = os.environ.get("GEOTRUTH_CORPUS_DIR")
    return Path(env) if env else repo_root() / "corpus"


def _corpus_manifest(base: Path) -> dict[str, Any] | None:
    path = base / "MANIFEST.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def resolve_tier(tier: str, base: Path | None = None) -> list[Path]:
    """The case files of a tier, from ``corpus/MANIFEST.json`` (files missing locally,
    such as an unreleased ``full`` tier, raise FileNotFoundError)."""
    base = base or corpus_dir()
    man = _corpus_manifest(base)
    if man is None or tier not in man.get("tiers", {}):
        known = sorted((man or {}).get("tiers", {}))
        raise FileNotFoundError(
            f"tier {tier!r} is not in {base / 'MANIFEST.json'} (tiers: {', '.join(known) or '-'})"
        )
    files = [base / rel for rel in man["tiers"][tier]["files"]]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise FileNotFoundError(
            f"tier {tier!r}: {len(missing)} case files are missing locally, e.g. {missing[0]} "
            "(the full tier is a release asset; `geotruth corpus build` regenerates it)"
        )
    return files


def corpus_version(files: list[Path], base: Path | None = None) -> str:
    """The corpus version of MANIFEST.json, or a digest of the case files."""
    man = _corpus_manifest(base or corpus_dir())
    if man and man.get("corpus_version"):
        rels = {str(p) for t in man.get("tiers", {}).values() for p in t.get("files", {})}
        root = (base or corpus_dir()).resolve()
        inside = all(
            str(f.resolve().relative_to(root)) in rels
            for f in files
            if f.resolve().is_relative_to(root)
        )
        if inside and all(f.resolve().is_relative_to(root) for f in files):
            return str(man["corpus_version"])
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    return "sha256:" + h.hexdigest()[:16]


def load_cases(files: list[Path]) -> Iterator[tuple[str, str]]:
    """``(id, v2 JSON line)`` for every case of the files, legacy operands converted to
    typed geometries (the case's other keys are kept)."""
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                obj = json_loads(line)
                if isinstance(obj.get("a"), list) or isinstance(obj.get("b"), list):
                    c = case_from_json(obj)
                    obj = case_to_json(c)
                    if not obj.get("family"):
                        obj.pop("family", None)
                yield str(obj["id"]), json.dumps(obj)


# ============================================================================ options


@dataclass
class RunOptions:
    target: Target
    files: list[Path]
    tier: str | None = None
    out_dir: Path = Path("results")
    prefix: str | None = None
    op_timeout: float = 3.0
    budget_s: float | None = 3600.0
    limit: int | None = None
    validate: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class RunReport:
    results_path: Path
    run_path: Path
    stats_path: Path
    stats: dict[str, Any]
    run: dict[str, Any]


def adapter_env(opts: RunOptions) -> dict[str, str]:
    env = dict(os.environ)
    t = f"{opts.op_timeout:g}"
    for var in TIMEOUT_ENV_VARS:
        env[var] = t
    if opts.prefix:
        var = opts.target.adapter.get("build_root_override")
        if var:
            env[var] = opts.prefix
        else:
            env["PYTHONPATH"] = opts.prefix + os.pathsep + env.get("PYTHONPATH", "")
        env["GEOTRUTH_PREFIX"] = opts.prefix
    env.update(opts.extra_env)
    return env


def _command(cmd: str) -> list[str]:
    words = shlex.split(cmd)
    root = repo_root()
    return [str(root / w) if "/" in w and (root / w).exists() else w for w in words]


def check_available(target: Target, env: dict[str, str], timeout: float = 180.0) -> str:
    """Run the target's version command; returns its output (the lib string). Raises
    RuntimeError, with the build recipe, when the adapter is not built."""
    try:
        out = subprocess.run(
            _command(target.version_command),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=repo_root(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{target.id}: version command failed: {exc}") from None
    text = out.stdout.strip().splitlines()
    if out.returncode != 0 or not text:
        build = target.adapter.get("build", "?")
        raise RuntimeError(
            f"{target.id} is not available (version command exited {out.returncode}: "
            f"{out.stderr.strip()[-300:]}); build it first: {build}"
        )
    return text[-1].strip()


# ============================================================================ provenance


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root()), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def adapter_git_sha(target: Target) -> str | None:
    """The last commit touching the adapter directory, ``+dirty`` with local changes."""
    rel = f"adapters/{target.dir}"
    sha = _git("log", "-1", "--format=%H", "--", rel)
    if not sha:
        return None
    dirty = _git("status", "--porcelain", "--", rel)
    return sha + ("+dirty" if dirty else "")


def _compiler(toolchain: str) -> dict[str, str]:
    """``{"name", "version", "flags"}`` from a manifest toolchain string."""
    if not toolchain:
        return {}
    head, _, rest = toolchain.partition(",")
    words = head.split()
    out = {"name": head.strip()}
    if len(words) >= 2 and any(ch.isdigit() for ch in words[-1]):
        out = {"name": " ".join(words[:-1]), "version": words[-1]}
    if rest.strip():
        out["flags"] = rest.strip()
    return out


def _runner_image() -> str:
    img = os.environ.get("GEOTRUTH_RUNNER_IMAGE")
    if img:
        return img
    osname = platform.platform()
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return f"host: {osname}, python {platform.python_version()}"


def _now() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def provenance(
    opts: RunOptions, lib: str, version_out: str, started: str, finished: str, corpus_ver: str
) -> dict[str, Any]:
    """The ``run.v2`` record."""
    t = opts.target
    rec: dict[str, Any] = {"lib": lib}
    if t.table.get("version"):
        rec["library_version"] = str(t.table["version"])
    if t.table.get("commit"):
        rec["library_commit"] = str(t.table["commit"])
    adapter: dict[str, Any] = {"name": t.dir, "manifest_sha256": t.manifest_sha256}
    sha = adapter_git_sha(t)
    if sha:
        adapter["git_sha"] = sha
    rec["adapter"] = adapter
    comp = _compiler(t.table.get("toolchain", ""))
    if comp:
        rec["compiler"] = comp
    options: dict[str, Any] = {"manifest": list(t.table.get("options", []))}
    if version_out and version_out != lib:
        options["version_command"] = version_out
    if opts.prefix:
        options["prefix"] = opts.prefix
    options["runner"] = {"op_timeout_s": opts.op_timeout, "budget_s": opts.budget_s}
    rec["options"] = options
    rec["engine_version"] = ENGINE_VERSION
    rec["corpus_version"] = corpus_ver
    if opts.tier in ("core", "full", "curated"):
        rec["tier"] = opts.tier
    rec["runner_image"] = _runner_image()
    rec["started"] = started
    rec["finished"] = finished
    rec["host"] = platform.node()
    return rec


# ============================================================================ running


class _Adapter:
    """One adapter process reading a case file, with a line reader and a watchdog."""

    def __init__(self, cmd: list[str], cases_file: Path, env: dict[str, str], err) -> None:
        self.proc = subprocess.Popen(
            [*cmd, str(cases_file)],
            stdout=subprocess.PIPE,
            stderr=err,
            env=env,
            cwd=repo_root(),
            start_new_session=True,
        )
        assert self.proc.stdout is not None
        self.fd = self.proc.stdout.fileno()
        self.buf = b""

    def readline(self, timeout: float) -> bytes | str:
        """A line, or ``"timeout"`` / ``"eof"``."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return "timeout"
            ready, _, _ = select.select([self.fd], [], [], left)
            if not ready:
                return "timeout"
            chunk = os.read(self.fd, 1 << 16)
            if not chunk:
                if self.buf:
                    line, self.buf = self.buf, b""
                    return line
                return "eof"
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.proc.wait()
        if self.proc.stdout:
            self.proc.stdout.close()

    def close(self) -> int:
        try:
            rc = self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.kill()
            rc = -9
        if self.proc.stdout:
            self.proc.stdout.close()
        return rc


def _ops_of(line: str) -> int:
    try:
        obj = json.loads(line)
    except ValueError:
        return _OPS_PER_CASE
    ops = obj.get("ops")
    if not ops:
        return _OPS_PER_CASE
    per = {"echo": 1, "relate": 1, "predicates": 10, "validity": 2, "overlay": 4}
    return sum(per.get(o, 1) for o in ops)


def _failure(case_id: str, lib: str, kind: str, message: str) -> dict[str, Any]:
    return {"id": case_id, "lib": lib, "errors": {"*": {"kind": kind, "message": message}}}


def run_target(opts: RunOptions, *, log=None) -> RunReport:
    """Run the target over the cases; see the module docstring."""
    from geotruth import schemas

    t = opts.target
    if t.contract != "v2":
        raise RuntimeError(
            f"{t.id}: adapter {t.dir} speaks contract {t.contract}; the runner needs v2 "
            "(run it with harness/hunt.sh instead)"
        )
    env = adapter_env(opts)
    version_out = check_available(t, env)
    out_dir = Path(opts.out_dir) / t.id
    out_dir.mkdir(parents=True, exist_ok=True)
    name = opts.tier or "cases"
    results_path = out_dir / f"{name}.jsonl"
    invalid_path = out_dir / f"{name}.invalid.jsonl"
    stderr_path = out_dir / f"{name}.stderr.log"
    cases = list(load_cases(opts.files))
    if opts.limit is not None:
        cases = cases[: opts.limit]
    validator = None
    if opts.validate:
        try:
            validator = schemas.validator("result")
        except ImportError:  # jsonschema is optional
            validator = None
    stats: dict[str, Any] = {
        "target": t.id,
        "tier": opts.tier,
        "case_files": [str(f) for f in opts.files],
        "cases_total": len(cases),
        "cases_run": 0,
        "watchdog_timeouts": 0,
        "adapter_restarts": 0,
        "early_exits": 0,
        "invalid_lines": 0,
        "id_mismatches": 0,
        "lib_strings": {},
        "budget_exhausted": False,
        "op_timeout_s": opts.op_timeout,
        "budget_s": opts.budget_s,
        "schema_validation": validator is not None,
    }
    started = _now()
    t0 = time.monotonic()
    cmd = _command(t.run)
    lib_seen = t.lib
    with (
        open(results_path, "w", encoding="utf-8") as out,
        open(invalid_path, "w", encoding="utf-8") as bad,
        open(stderr_path, "wb") as err,
        tempfile.TemporaryDirectory(prefix="geotruth-run-") as tmp,
    ):
        k = 0
        silent_exits = 0
        k_stop = False
        while k < len(cases) and not k_stop:
            if opts.budget_s is not None and time.monotonic() - t0 > opts.budget_s:
                stats["budget_exhausted"] = True
                break
            feed = Path(tmp) / f"cases-{k}.jsonl"
            feed.write_text("".join(line + "\n" for _, line in cases[k:]), encoding="utf-8")
            proc = _Adapter(cmd, feed, env, err)
            first = True
            first_line = True
            while k < len(cases):
                if opts.budget_s is not None and time.monotonic() - t0 > opts.budget_s:
                    stats["budget_exhausted"] = True
                    proc.kill()
                    break
                cid, cline = cases[k]
                wait = (_ops_of(cline) + 1) * opts.op_timeout + _LINE_SLACK
                if first:
                    wait += _STARTUP_SLACK
                got = proc.readline(wait)
                first = False
                if got == "timeout":
                    proc.kill()
                    stats["watchdog_timeouts"] += 1
                    rec = _failure(
                        cid, lib_seen, "timeout", f"no result within {wait:g} s (runner watchdog)"
                    )
                    out.write(json.dumps(rec) + "\n")
                    k += 1
                    break
                if got == "eof":
                    rc = proc.close()
                    stats["early_exits"] += 1
                    silent_exits = silent_exits + 1 if first_line else 0
                    rec = _failure(
                        cid, lib_seen, "crash", f"adapter exited (status {rc}) before answering"
                    )
                    out.write(json.dumps(rec) + "\n")
                    k += 1
                    if silent_exits >= 3:
                        stats["aborted"] = (
                            f"the adapter exited {silent_exits} times without answering a case; "
                            f"see {stderr_path}"
                        )
                        k_stop = True
                    break
                assert isinstance(got, bytes)
                first_line = False
                text = got.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                rec, problem = _check_line(text, cid, lib_seen, validator)
                if problem:
                    stats["invalid_lines"] += 1
                    if problem.startswith("id"):
                        stats["id_mismatches"] += 1
                    bad.write(json.dumps({"id": cid, "problem": problem, "line": text}) + "\n")
                lib_seen = rec.get("lib") or lib_seen
                stats["lib_strings"][lib_seen] = stats["lib_strings"].get(lib_seen, 0) + 1
                out.write(json.dumps(rec) + "\n")
                k += 1
                stats["cases_run"] = k
            else:
                proc.close()
                continue
            stats["adapter_restarts"] += 1 if k < len(cases) else 0
            if log:
                log(f"{t.id}: adapter restarted at case {k}/{len(cases)}")
        stats["cases_run"] = k
    stats["elapsed_s"] = round(time.monotonic() - t0, 3)
    finished = _now()
    corpus_ver = corpus_version(opts.files)
    run_rec = provenance(opts, lib_seen, version_out, started, finished, corpus_ver)
    run_path = out_dir / "run.json"
    run_path.write_text(json.dumps(run_rec, indent=1) + "\n", encoding="utf-8")
    stats_path = out_dir / f"{name}.stats.json"
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    if invalid_path.stat().st_size == 0:
        invalid_path.unlink()
    return RunReport(results_path, run_path, stats_path, stats, run_rec)


def _check_line(text: str, cid: str, lib: str, validator: Any) -> tuple[dict[str, Any], str]:
    """The record to keep for an adapter output line, and what was wrong with it."""
    try:
        rec = json_loads(text)
    except ValueError as exc:
        return _failure(cid, lib, "exception", f"adapter output is not JSON: {exc}"), "json"
    if not isinstance(rec, dict):
        return _failure(cid, lib, "exception", "adapter output is not an object"), "json"
    if rec.get("id") != cid:
        msg = f"adapter answered id {rec.get('id')!r} for case {cid!r}"
        return _failure(cid, lib, "exception", msg), "id mismatch"
    if validator is not None:
        errs = sorted(validator.iter_errors(rec), key=lambda e: list(e.absolute_path))
        if errs:
            e = errs[0]
            where = "/".join(str(p) for p in e.absolute_path) or "(root)"
            msg = f"adapter output violates result.v2 at {where}: {e.message[:300]}"
            return _failure(cid, rec.get("lib") or lib, "exception", msg), msg
    return rec, ""
