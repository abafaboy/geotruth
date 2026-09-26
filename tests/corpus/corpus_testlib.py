"""Helpers shared by the corpus, minimiser and export tests (tests/corpus/).

The corpus code lives in corpus/generators/ (outside the package); importing this module
puts it on ``sys.path``, the way ``geotruth corpus`` does. (A uniquely named module, so
it never collides with another directory's conftest.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "corpus" / "generators"
DATA = Path(__file__).resolve().parent / "data"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def id_list(name: str) -> list[str]:
    """Ids (first tab-separated field) of a tests/corpus/data list, comments skipped."""
    out = []
    for ln in (DATA / name).read_text().splitlines():
        if ln.strip() and not ln.startswith("#"):
            out.append(ln.split("\t")[0].strip())
    return out


def records_by_id(ids: list[str]) -> list[dict]:
    """The core/curated records with these ids, in the given order."""
    want = set(ids)
    found: dict[str, dict] = {}
    paths = sorted((REPO / "corpus" / "cases" / "core").glob("*.jsonl"))
    for p in [*paths, REPO / "corpus" / "cases" / "curated.jsonl"]:
        for r in read_jsonl(p):
            if r["id"] in want:
                found[r["id"]] = r
    missing = want - set(found)
    assert not missing, f"cases not in the corpus: {sorted(missing)}"
    return [found[i] for i in ids]
