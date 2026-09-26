"""Fixtures for the site generator tests (``site/gtsite``, ``geotruth site``).

``synthetic_results`` builds a small results directory the way ``geotruth run`` and
``geotruth score`` lay it out, from hand-written cases: the exact answers come from the
engine (cached where the scorer caches them), two fake libraries answer with deliberate
faults, and the real scorer (``geotruth.harness.score``) grades them. The site is then built
from these files exactly as from a real run.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "site"
if str(SITE) not in sys.path:
    sys.path.insert(0, str(SITE))

SQ_A = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
SQ_B = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
TINY = 2.0**-600


def _poly(ring: list) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [ring]}


def _case(cid: str, family: str, a: dict, b: dict, **tags: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "family": family,
        "tags": {"degeneracy": "lattice", "range": "normal", **tags},
        "provenance": {"source": "manual"},
        "a": a,
        "b": b,
    }


CASES = [
    _case("squares-1", "squares", _poly(SQ_A), _poly(SQ_B), n=8, variant="overlap"),
    _case(
        "touch-1",
        "touch",
        _poly([[0, 0], [4, 0], [4, 4], [0, 0]]),
        _poly([[2, 2], [2, 5], [0, 5], [2, 2]]),
        n=6,
        variant="apex-on-edge",
    ),
    _case(
        "line-1",
        "line",
        {"type": "LineString", "coordinates": [[-1, 1], [3, 1]]},
        _poly(SQ_A),
        n=7,
        variant="chord",
    ),
    _case(
        "extreme-1",
        "extreme",
        _poly([[x * TINY, y * TINY] for x, y in SQ_A]),
        _poly([[x * TINY, y * TINY] for x, y in SQ_B]),
        n=8,
        variant="overlap.extreme",
        range="extreme",
    ),
    _case(
        "invalid-1",
        "invalid",
        _poly([[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]),
        _poly(SQ_B),
        n=8,
        variant="bowtie",
    ),
    _case(
        "empty-1",
        "empty",
        {"type": "Point", "coordinates": []},
        _poly(SQ_A),
        n=4,
        variant="empty-point",
    ),
]

LIB1, LIB2 = "shapely", "fakelib"  # a target with a real manifest, and one without


def good_result(case: dict, exp: dict, lib: str) -> dict[str, Any]:
    """A result that agrees with the exact answer (overlays: the exact result rounded)."""
    from geotruth.harness.control import rounded_json
    from geotruth.io import geometry_from_json

    res: dict[str, Any] = {"id": case["id"], "lib": lib, "errors": {}}
    res["echo"] = {"a": case["a"], "b": case["b"]}
    val = exp.get("validity") or {}
    res["valid_a"] = val.get("a", {}).get("valid")
    res["valid_b"] = val.get("b", {}).get("valid")
    if "relate" in exp:
        res["relate"] = exp["relate"]
        res["predicates"] = dict(exp["predicates"])
    if "overlay" in exp:
        res["overlay"] = {
            op: rounded_json(geometry_from_json(v["non_strict"]["exact"], exact=True))
            for op, v in exp["overlay"].items()
        }
    return res


def faulty_lib1(case: dict, exp: dict) -> dict[str, Any]:
    """LIB1: right except for one deliberate fault per case."""
    res = good_result(case, exp, "fake@1")
    cid = case["id"]
    if cid == "squares-1":
        # union output moved by 0.5 at one vertex: far beyond any budget (gross or worse)
        ring = res["overlay"]["union"]["coordinates"][0]
        ring[0] = [ring[0][0] + 0.5, ring[0][1]]
        ring[-1] = list(ring[0])
        # the echo of A loses the sign of nothing but changes one ordinate
        res["echo"] = copy.deepcopy(res["echo"])
        res["echo"]["a"]["coordinates"][0][1] = [2.0000000000000004, 0]
    elif cid == "touch-1":
        m = list(res["relate"])
        m[4] = "F"  # BB: the library misses the touch
        res["relate"] = "".join(m)
        res["predicates"]["intersects"] = not res["predicates"]["intersects"]
        res["predicates"]["disjoint"] = not res["predicates"]["disjoint"]
    elif cid == "line-1":
        res["overlay"]["intersection"] = None
        res["errors"] = {
            "overlay.intersection": {"kind": "exception", "message": "TopologyException: boom"}
        }
    elif cid == "invalid-1":
        res["valid_a"] = True
    return res


def faulty_lib2(case: dict, exp: dict) -> dict[str, Any]:
    """LIB2 (no manifest): no relate, no validity; a wrong predicate on the extreme case."""
    res = good_result(case, exp, "fake2@0.1")
    res.pop("echo", None)
    res["relate"] = "unsupported"
    res["valid_a"] = res["valid_b"] = None
    if case["id"] == "extreme-1" and "predicates" in res:
        res["predicates"]["overlaps"] = False
        res["predicates"]["intersects"] = False
        res["predicates"]["disjoint"] = True
    return res


REGISTRY = """
registry_version = 1

[[finding]]
id = "fake-touch-missed"
library = "shapely"
lib = "fake@1"
signature = "relate misses a vertex that lies exactly on an edge"
fields = ["relate"]
families = ["touch"]
status = "confirmed"
status_date = "2026-09-26"
links = ["https://example.org/issue/1"]
upstream_issue = ""
evidence = "findings/README.md"

[[finding]]
id = "fake-other-library"
library = "fakelib"
signature = "something about another library"
fields = ["area_inter"]
families = ["squares"]
status = "by-design"
status_date = "2026-09-26"
links = []
upstream_issue = ""

[[lead]]
id = "fake-lead"
library = ["shapely", "fakelib"]
status = "unreviewed"
source = "corpus/curated/leads.toml"
signature = "a lead registered by its signature only"
"""


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


@pytest.fixture(scope="session")
def synthetic_results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A results directory with two scored fake libraries; returns the paths and the score
    records of each library."""
    from geotruth import ENGINE_VERSION
    from geotruth.harness import expected as E
    from geotruth.harness import score
    from geotruth.harness.manifest import find_target
    from geotruth.io import case_from_json

    base = tmp_path_factory.mktemp("site-results")
    root = base / "results"
    root.mkdir()
    case_file = base / "cases.jsonl"
    _write_jsonl(case_file, CASES)
    lines = case_file.read_text(encoding="utf-8").splitlines()
    expected = E.compute_expected(lines, jobs=1, cache_dir=root / "_expected")
    records: dict[str, list[dict]] = {}
    for target, make, lib in ((LIB1, faulty_lib1, "fake@1"), (LIB2, faulty_lib2, "fake2@0.1")):
        d = root / target
        d.mkdir()
        results = [make(c, expected[c["id"]]) for c in CASES]
        _write_jsonl(d / "core.jsonl", results)
        versions = {
            "corpus": "test",
            "expected": f"computed-{ENGINE_VERSION}",
            "engine": ENGINE_VERSION,
            "lib": lib,
        }
        try:
            tgt = find_target(target)
        except KeyError:
            tgt = None
        ctx = score.ScoreContext(target=tgt, lib_id=target, versions=versions)
        recs = []
        for c, r in zip(CASES, results, strict=True):
            recs += score.score_case(case_from_json(c), expected[c["id"]], r, ctx)
        _write_jsonl(d / "core.score.jsonl", recs)
        records[target] = recs
        (d / "run.json").write_text(
            json.dumps(
                {
                    "lib": lib,
                    "library_version": "1",
                    "adapter": {"name": target, "git_sha": "0123456789abcdef"},
                    "engine_version": ENGINE_VERSION,
                    "corpus_version": "test",
                    "tier": "core",
                    "started": "2026-09-26T01:02:03Z",
                    "finished": "2026-09-26T01:02:04Z",
                }
            ),
            encoding="utf-8",
        )
        (d / "core.stats.json").write_text(
            json.dumps(
                {
                    "target": target,
                    "tier": "core",
                    "case_files": [str(case_file)],
                    "cases_total": len(CASES),
                    "cases_run": len(CASES),
                    "watchdog_timeouts": 0,
                    "adapter_restarts": 0,
                    "early_exits": 0,
                    "invalid_lines": 0,
                }
            ),
            encoding="utf-8",
        )
    registry = base / "registry.toml"
    registry.write_text(REGISTRY, encoding="utf-8")
    return {
        "root": root,
        "case_file": case_file,
        "registry": registry,
        "records": records,
        "expected": expected,
    }


@pytest.fixture(scope="session")
def built_site(synthetic_results: dict[str, Any], tmp_path_factory: pytest.TempPathFactory):
    """The site built from ``synthetic_results``: ``(out dir, BuildReport)``."""
    from gtsite import SiteOptions, build_site

    out = tmp_path_factory.mktemp("site") / "_build"
    report = build_site(
        SiteOptions(
            scores=[synthetic_results["root"]],
            out=out,
            registry=synthetic_results["registry"],
            generated="2026-09-26 00:00 UTC",
        ),
        log=lambda msg: None,
    )
    return out, report
