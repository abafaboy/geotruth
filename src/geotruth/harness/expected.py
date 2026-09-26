"""Expected answers for scoring: read an ``expected.v2`` file, or compute them with the
shim of :mod:`geotruth.harness.engine` (in parallel, cached).

The cache lives in ``<results>/_expected/<key>.jsonl``; the key digests the case lines,
the engine version, the rational backend and the routes the shim takes (engine or
fallbacks), so a changed engine or a newly landed engine module never reuses stale
answers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.numbers import get_backend, json_loads

__all__ = ["cache_key", "compute_expected", "load_expected"]


def load_expected(path: Path) -> dict[str, dict[str, Any]]:
    """id -> expected record, from a JSON-lines file."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json_loads(line)
                out[rec["id"]] = rec
    return out


def cache_key(case_lines: Iterable[str]) -> str:
    from geotruth.harness.engine import backends

    h = hashlib.sha256()
    h.update(f"{ENGINE_VERSION}|{get_backend()}|{json.dumps(backends(), sort_keys=True)}".encode())
    for line in case_lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:24]


def _one(line: str) -> str:
    from geotruth.harness.engine import expected_record
    from geotruth.io import case_from_json

    case = case_from_json(json_loads(line))
    try:
        rec = expected_record(case)
    except Exception as exc:  # the engine may fail; never a library failure
        rec = {
            "id": case.id,
            "engine": {"version": ENGINE_VERSION},
            "status": "engine_error",
            "reason": f"{type(exc).__name__}: {exc}"[:2000],
        }
    return json.dumps(rec, separators=(",", ":"))


def compute_expected(
    case_lines: list[str], *, jobs: int = 1, cache_dir: Path | None = None, log=None
) -> dict[str, dict[str, Any]]:
    """id -> expected record for the cases (v2 JSON lines), computed with the shim."""
    path = None
    if cache_dir is not None:
        path = Path(cache_dir) / f"{cache_key(case_lines)}.jsonl"
        if path.is_file():
            if log:
                log(f"expected answers from the cache {path}")
            return load_expected(path)
    if log:
        log(f"computing expected answers for {len(case_lines)} cases ({jobs} jobs)")
    if jobs > 1 and len(case_lines) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            lines = list(ex.map(_one, case_lines, chunksize=8))
    else:
        lines = [_one(x) for x in case_lines]
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        tmp.replace(path)
    return {r["id"]: r for r in (json_loads(x) for x in lines)}
