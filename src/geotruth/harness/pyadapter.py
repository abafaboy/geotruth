"""The adapter-contract-v2 runtime of the Python adapters (DESIGN §4.1).

Used by ``adapters/shapely``, ``adapters/engine_control`` and ``adapters/mutant``. It
mirrors the native runtime (``adapters/geos_main/adapter_v2.hpp``):

- **Input**: one case per line. A line is a v2 case when an operand is a typed geometry
  (a JSON object) or ``"ops"`` is present; ``ops`` selects the groups (``echo``,
  ``relate``, ``predicates``, ``validity``, ``overlay``; absent means everything but
  ``echo``). Other lines are legacy FORMAT-v1 cases, answered by the adapter's v1 code if
  it has one, else as v2 (``--v2`` forces v2 for every line).
- **Output**: ``{"id", "lib", "relate"?, "predicates"?, "valid_a"?, "valid_b"?,
  "overlay"?, "echo"?, "errors", "elapsed_ms"?}`` with only the requested groups. A
  field is ``null`` when the library does not provide it, ``"unsupported"`` when the
  input is outside the library's contract (the session raises :class:`Unsupported`) and
  ``null`` plus an ``errors`` entry when it failed. Output geometries are typed JSON whose
  doubles ``json.dumps`` writes in shortest round-trip form; nothing goes through a
  library's WKT writer.
- **Isolation**: the library runs in a forked worker process that streams each
  operation's result as soon as it has it. An operation with no result within the
  per-operation timeout (``GEOTRUTH_OP_TIMEOUT`` or the adapter's own variable, default
  10 s) is killed (``{"kind": "timeout"}``); a worker that dies (a crash, a signal) fails
  that one operation (``{"kind": "crash"}``); either way a fresh worker continues with
  the next operation. The worker's address space is capped at ``GEOTRUTH_ADAPTER_MEM_MB``
  MiB (default 4096, 0 = no cap); a ``MemoryError`` is ``{"kind": "memory"}``.
  ``--no-fork`` runs everything in-process (same output when nothing crashes).
- ``--timing`` adds ``elapsed_ms`` per field path; ``--version`` prints the ``lib``
  string. ``GEOTRUTH_PYADAPTER_TEST_FAULT=crash:<path>|hang:<path>|throw:<path>|oom:<path>``
  injects a fault in front of one operation, only to test the isolation.

An adapter provides a :class:`Library` (``lib``, ``session(case)``, optionally
``session_v1(case)`` and ``postprocess(record)``) and calls :func:`main`.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import signal
import sys
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "GROUPS",
    "PREDICATES",
    "V1_FIELDS",
    "V2_PATHS",
    "Config",
    "Library",
    "Session",
    "Unsupported",
    "answer_line",
    "is_v2_case",
    "main",
]

PREDICATES = (
    "intersects",
    "disjoint",
    "touches",
    "crosses",
    "overlaps",
    "contains",
    "covers",
    "within",
    "covered_by",
    "equals",
)
OVERLAY_OPS = ("intersection", "union", "difference", "symdifference")
GROUPS = ("echo", "relate", "predicates", "validity", "overlay")
DEFAULT_GROUPS = ("relate", "predicates", "validity", "overlay")
V2_PATHS = (
    "echo",
    "relate",
    *(f"predicates.{p}" for p in PREDICATES),
    "valid_a",
    "valid_b",
    *(f"overlay.{op}" for op in OVERLAY_OPS),
)
#: FORMAT-v1 result fields, in the order the v1 Shapely adapter wrote them.
V1_FIELDS = (
    "valid_a",
    "valid_b",
    "intersects",
    "disjoint",
    "touches",
    "overlaps",
    "contains",
    "covers",
    "within",
    "equals",
    "covered_by",
    "area_inter",
    "area_union",
    "area_diff",
    "area_symdiff",
)


def group_of(path: str) -> str:
    if path in ("valid_a", "valid_b"):
        return "validity"
    return path.split(".", 1)[0]


class Unsupported(Exception):
    """The input is outside the library's contract: the field is ``"unsupported"``."""


class Session:
    """One case on the library side. ``run(path)`` returns the JSON value of one field
    path (None when the library does not provide it), or raises :class:`Unsupported` or
    any exception (an error)."""

    def run(self, path: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


class Library:
    """What an adapter provides to :func:`main`."""

    lib: str = "unknown@0"
    #: environment variable of the adapter's own per-operation timeout (besides
    #: GEOTRUTH_OP_TIMEOUT)
    timeout_env: str | None = None
    #: True if :meth:`session_v1` answers legacy FORMAT-v1 lines
    supports_v1: bool = False

    def session(self, case: dict[str, Any]) -> Session:  # pragma: no cover - interface
        raise NotImplementedError

    def session_v1(self, case: dict[str, Any]) -> Session | None:
        """A session for a legacy FORMAT-v1 line (paths are v1 field names), or None to
        answer legacy lines with the v2 contract."""
        return None

    def postprocess(self, record: dict[str, Any], case: dict[str, Any] | None) -> dict[str, Any]:
        """Called in the parent process on every output record, in input order."""
        return record

    def version(self) -> str:
        return self.lib


@dataclass
class Config:
    timeout_s: float = 10.0
    mem_mb: int = 4096
    fork: bool = True
    timing: bool = False
    force_v2: bool = False
    fault: str = ""

    @classmethod
    def from_env(cls, library: Library) -> Config:
        cfg = cls()
        for var in ("GEOTRUTH_OP_TIMEOUT", library.timeout_env):
            if var and os.environ.get(var):
                try:
                    t = float(os.environ[var])
                except ValueError:
                    continue
                if t > 0:
                    cfg.timeout_s = t
                    break
        mem = os.environ.get("GEOTRUTH_ADAPTER_MEM_MB")
        if mem:
            cfg.mem_mb = int(mem)
        cfg.fault = os.environ.get("GEOTRUTH_PYADAPTER_TEST_FAULT", "")
        return cfg


# ============================================================================ cases


def is_v2_case(obj: Any) -> bool:
    """A v2 case: an operand is a typed geometry (an object) or ``ops`` is present."""
    if not isinstance(obj, dict):
        return False
    return "ops" in obj or isinstance(obj.get("a"), dict) or isinstance(obj.get("b"), dict)


def _loads(line: str) -> Any:
    from geotruth.numbers import json_loads

    return json_loads(line)


def requested_paths(case: dict[str, Any]) -> list[str]:
    ops = case.get("ops")
    if ops is None:
        groups = set(DEFAULT_GROUPS)
    else:
        if not isinstance(ops, list):
            raise ValueError('"ops" must be an array')
        groups = set()
        for o in ops:
            if o not in GROUPS:
                raise ValueError(f"unknown op {o!r}")
            groups.add(o)
    return [p for p in V2_PATHS if group_of(p) in groups]


def _error_value(exc: BaseException) -> Any:
    if isinstance(exc, MemoryError):
        return {"kind": "memory", "message": f"MemoryError: {exc}"[:500]}
    msg = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return msg[:1000]


def _error_v1(exc: BaseException) -> str:
    return repr(exc)


# ============================================================================ one case


def _inject(cfg: Config, path: str) -> None:
    if not cfg.fault or ":" not in cfg.fault:
        return
    kind, _, where = cfg.fault.partition(":")
    if where != path:
        return
    if kind == "crash":
        os.kill(os.getpid(), signal.SIGSEGV)
    if kind == "hang":
        while True:
            time.sleep(3600)
    if kind == "throw":
        raise RuntimeError("injected test fault")
    if kind == "oom":
        hog = []
        while True:
            hog.append(bytearray(1 << 26))


def _run_ops(
    session_factory: Callable[[], Session], paths: Sequence[str], start: int, cfg: Config, v1: bool
) -> Iterator[dict[str, Any]]:
    """Yield ``{"k", "v" | "e", "ms"}`` for every path from ``start`` on."""
    try:
        session: Session | None = session_factory()
        build_error = None
    except Exception as exc:
        session, build_error = None, exc
    for k in range(start, len(paths)):
        path = paths[k]
        t0 = time.perf_counter()
        out: dict[str, Any] = {"k": k}
        try:
            _inject(cfg, path)
            if session is None:
                assert build_error is not None
                raise build_error
            out["v"] = session.run(path)
        except Unsupported:
            out["v"] = "unsupported"
        except Exception as exc:
            out["e"] = _error_v1(exc) if v1 else _error_value(exc)
        except MemoryError as exc:  # pragma: no cover - listed for clarity
            out["e"] = _error_value(exc)
        out["ms"] = (time.perf_counter() - t0) * 1000.0
        yield out


class _Worker:
    """A forked worker process: request lines in, one result line per operation out."""

    def __init__(self, library: Library, cfg: Config) -> None:
        r_req, w_req = os.pipe()
        r_res, w_res = os.pipe()
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:  # the worker
            os.close(w_req)
            os.close(r_res)
            try:
                _worker_loop(library, cfg, r_req, w_res)
            finally:
                os._exit(0)
        os.close(r_req)
        os.close(w_res)
        self.pid = pid
        self.req = os.fdopen(w_req, "w", encoding="utf-8")
        self.res_fd = r_res
        self.buf = b""

    def send(self, request: dict[str, Any]) -> bool:
        try:
            self.req.write(json.dumps(request) + "\n")
            self.req.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def read(self, timeout: float) -> dict[str, Any] | str:
        """The next result, ``"timeout"`` or ``"eof"``."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return "timeout"
            ready, _, _ = select.select([self.res_fd], [], [], left)
            if not ready:
                return "timeout"
            chunk = os.read(self.res_fd, 1 << 16)
            if not chunk:
                return "eof"
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line)

    def finish(self, kill: bool) -> str:
        """Stop the worker; returns how it ended."""
        if kill:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            self.req.close()
        try:
            _, status = os.waitpid(self.pid, 0)
        except ChildProcessError:
            status = 0
        os.close(self.res_fd)
        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            try:
                name = signal.Signals(sig).name
            except ValueError:
                name = "?"
            return f"process killed by signal {sig} ({name})"
        return f"process exited with status {os.WEXITSTATUS(status)}"


def _worker_loop(library: Library, cfg: Config, r_req: int, w_res: int) -> None:
    if cfg.mem_mb > 0:
        try:
            import resource

            lim = cfg.mem_mb << 20
            resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
        except (ValueError, OSError):
            pass
    out = os.fdopen(w_res, "w", encoding="utf-8")
    with os.fdopen(r_req, "r", encoding="utf-8") as inp:
        for line in inp:
            req = json.loads(line)
            case = _loads(req["case"])
            v1 = bool(req.get("v1"))

            def factory(case: dict[str, Any] = case, v1: bool = v1) -> Session:
                s = library.session_v1(case) if v1 else library.session(case)
                assert s is not None
                return s

            for res in _run_ops(factory, req["paths"], req["start"], cfg, v1):
                out.write(json.dumps(res) + "\n")
                out.flush()


class Runner:
    """Runs cases through a persistent (re-forked on failure) worker."""

    def __init__(self, library: Library, cfg: Config) -> None:
        self.library = library
        self.cfg = cfg
        self.worker: _Worker | None = None

    def close(self) -> None:
        if self.worker is not None:
            self.worker.finish(kill=False)
            self.worker = None

    def run(
        self, line: str, case: dict[str, Any], paths: list[str], v1: bool
    ) -> list[dict[str, Any]]:
        """One result per path: ``{"v": value}`` or ``{"e": error}``, with ``ms``."""
        if not self.cfg.fork:

            def factory() -> Session:
                s = self.library.session_v1(case) if v1 else self.library.session(case)
                assert s is not None
                return s

            return list(_run_ops(factory, paths, 0, self.cfg, v1))
        res: list[dict[str, Any] | None] = [None] * len(paths)
        nxt = 0
        restarts = 0
        while nxt < len(paths):
            if self.worker is None:
                self.worker = _Worker(self.library, self.cfg)
            w = self.worker
            if not w.send({"case": line, "paths": paths, "start": nxt, "v1": v1}):
                how = w.finish(kill=True)
                self.worker = None
                restarts += 1
                if restarts > 2:
                    for k in range(nxt, len(paths)):
                        res[k] = {"e": self._crash(f"worker unusable: {how}", v1)}
                    break
                continue
            while nxt < len(paths):
                msg = w.read(self.cfg.timeout_s)
                if msg == "timeout":
                    w.finish(kill=True)
                    self.worker = None
                    res[nxt] = {"e": self._timeout(v1)}
                    nxt += 1
                    break
                if msg == "eof":
                    how = w.finish(kill=False)
                    self.worker = None
                    res[nxt] = {"e": self._crash(how, v1)}
                    nxt += 1
                    break
                assert isinstance(msg, dict)
                res[msg["k"]] = msg
                nxt = msg["k"] + 1
        return [r if r is not None else {"v": None} for r in res]

    def _timeout(self, v1: bool) -> Any:
        msg = f"no result after {self.cfg.timeout_s:g} s (killed)"
        return f"timeout: {msg}" if v1 else {"kind": "timeout", "message": msg}

    @staticmethod
    def _crash(how: str, v1: bool) -> Any:
        return f"crash: {how}" if v1 else {"kind": "crash", "message": how}


# ============================================================================ records


def _render_v2(
    lib: str, case: dict[str, Any], paths: list[str], res: list[dict[str, Any]], cfg: Config
) -> dict[str, Any]:
    got = dict(zip(paths, res, strict=True))
    groups = {group_of(p) for p in paths}
    out: dict[str, Any] = {"id": case.get("id"), "lib": lib}

    def val(p: str) -> Any:
        r = got.get(p, {})
        return r.get("v") if "e" not in r else None

    if "relate" in groups:
        out["relate"] = val("relate")
    if "predicates" in groups:
        out["predicates"] = {p: val(f"predicates.{p}") for p in PREDICATES}
    if "validity" in groups:
        out["valid_a"] = val("valid_a")
        out["valid_b"] = val("valid_b")
    if "overlay" in groups:
        out["overlay"] = {op: val(f"overlay.{op}") for op in OVERLAY_OPS}
    if "echo" in groups and val("echo") is not None:
        out["echo"] = val("echo")
    out["errors"] = {p: r["e"] for p, r in got.items() if "e" in r}
    if cfg.timing:
        out["elapsed_ms"] = {p: round(r["ms"], 3) for p, r in got.items() if "ms" in r}
    return out


def _render_v1(lib: str, case: dict[str, Any], res: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": case.get("id"), "lib": lib, "errors": {}}
    timeouts = []
    for f, r in zip(V1_FIELDS, res, strict=True):
        if "e" in r:
            out[f] = None
            out["errors"][f] = r["e"]
            if isinstance(r["e"], str) and r["e"].startswith("timeout:"):
                timeouts.append(f)
        else:
            out[f] = r.get("v")
    if timeouts:
        out["errors"]["timeout"] = timeouts
    return out


def _id_of(line: str) -> Any:
    try:
        obj = _loads(line)
    except ValueError:
        return None
    return obj.get("id") if isinstance(obj, dict) else None


def answer_line(library: Library, runner: Runner, line: str) -> tuple[dict[str, Any], Any]:
    """The result record of one input line, and the parsed case (None if unreadable)."""
    cfg = runner.cfg
    try:
        case = _loads(line)
        if not isinstance(case, dict):
            raise ValueError("a case must be a JSON object")
        v1 = not cfg.force_v2 and not is_v2_case(case) and library.supports_v1
        paths = list(V1_FIELDS) if v1 else requested_paths(case)
        if not v1 and ("a" not in case or "b" not in case):
            raise ValueError('missing "a" or "b"')
    except (ValueError, TypeError) as exc:
        rec = {"id": _id_of(line), "lib": library.lib, "errors": {"*": f"input parse error: {exc}"}}
        return rec, None
    res = runner.run(line, case, paths, v1)
    if v1:
        return _render_v1(library.lib, case, res), case
    return _render_v2(library.lib, case, paths, res, cfg), case


def _lines(path: str) -> Iterator[str]:
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")  # noqa: SIM115
    try:
        for line in fh:
            if line.strip():
                yield line.strip()
    finally:
        if fh is not sys.stdin:
            fh.close()


USAGE = (
    "usage: {prog} [--v2] [--timing] [--no-fork] CASES.jsonl|- > RESULTS.jsonl\n"
    "       {prog} --version"
)


def main(library: Library, argv: Sequence[str] | None = None, prog: str = "adapter") -> int:
    """Run an adapter over a case file; returns the exit status."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args:
        print(library.version())
        return 0
    cfg = Config.from_env(library)
    files = []
    for a in args:
        if a == "--v2":
            cfg.force_v2 = True
        elif a == "--timing":
            cfg.timing = True
        elif a == "--no-fork":
            cfg.fork = False
        elif a.startswith("--"):
            print(f"{prog}: unknown option {a}\n" + USAGE.format(prog=prog), file=sys.stderr)
            return 2
        else:
            files.append(a)
    if len(files) != 1:
        print(USAGE.format(prog=prog), file=sys.stderr)
        return 2
    runner = Runner(library, cfg)
    try:
        for line in _lines(files[0]):
            rec, case = answer_line(library, runner, line)
            rec = library.postprocess(rec, case)
            sys.stdout.write(json.dumps(rec) + "\n")
            sys.stdout.flush()
    except BrokenPipeError:
        return 0
    finally:
        runner.close()
    return 0
