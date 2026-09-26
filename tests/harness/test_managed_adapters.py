"""Adapter contract v2 of the adapters E4b manages (DESIGN.md §4.1): Shapely, JTS (master and
the 1.20.0 release), georust geo, the JavaScript libraries (Turf, polygon-clipping,
polyclip-ts, martinez, JSTS), the engine control and the mutant.

Manifests are checked always; the adapters themselves only when built (each test is
skipped for a target whose version command does not answer; builds live under
$GEOTRUTH_BUILD_DIR): the parse-echo canary bit for bit, schema-valid output for every pair
of geometry kinds, predicates consistent with the adapter's own relate matrix, "unsupported"
for out-of-contract input, per-operation isolation (hang and crash), and legacy v1 lines
still answered with the v1 contract."""

from __future__ import annotations

import json
import math
import os
import shlex
import struct
import subprocess
from functools import cache
from pathlib import Path

import pytest

from geotruth import schemas
from geotruth.harness import manifest

pytestmark = pytest.mark.unit
pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parents[2]
MANAGED_DIRS = ("shapely", "jts_main", "rust_geo", "js", "engine_control", "mutant")
V1_FIELDS = {
    "valid_a",
    "valid_b",
    "intersects",
    "disjoint",
    "touches",
    "overlaps",
    "contains",
    "covers",
    "within",
    "covered_by",
    "equals",
    "area_inter",
    "area_union",
    "area_diff",
    "area_symdiff",
}
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
V2_PATHS = {
    "echo",
    "relate",
    *(f"predicates.{p}" for p in PREDICATES),
    "valid_a",
    "valid_b",
    *(f"overlay.{op}" for op in ("intersection", "union", "difference", "symdifference")),
}
TARGETS = [t for t in manifest.targets() if t.dir in MANAGED_DIRS]
IDS = [t.id for t in TARGETS]

#: fault injection: (environment variable, hang spec, crash spec) per adapter directory
FAULTS = {
    "shapely": ("GEOTRUTH_PYADAPTER_TEST_FAULT", "hang:overlay.union", "crash:relate"),
    "engine_control": ("GEOTRUTH_PYADAPTER_TEST_FAULT", "hang:overlay.union", "crash:relate"),
    "jts_main": ("JTS_ADAPTER_TEST_FAULT", "hang_:overlay.union", "crash:relate"),
    "rust_geo": ("GEO_ADAPTER_TEST_FAULT", "hang:overlay.union", "abort:relate"),
    "js": ("JS_ADAPTER_TEST_FAULT", "hang:overlay.union", "crash:overlay.intersection"),
}


def command(cmd: str) -> list[str]:
    return [str(REPO / w) if "/" in w and (REPO / w).exists() else w for w in shlex.split(cmd)]


@cache
def built(tid: str) -> bool:
    t = manifest.find_target(tid)
    try:
        out = subprocess.run(
            command(t.version_command),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (
        out.returncode == 0
        and out.stdout.strip().splitlines()[-1:] != []
        and (out.stdout.strip().splitlines()[-1].startswith(t.lib))
    )


@pytest.fixture(params=TARGETS, ids=IDS)
def tgt(request):
    if not built(request.param.id):
        pytest.skip(f"{request.param.id} is not built ({request.param.adapter.get('build')})")
    return request.param


def run(
    t, cases: list[dict], tmp: Path, *flags: str, env: dict | None = None, timeout: float = 600
) -> list[dict]:
    path = tmp / f"cases-{t.id}.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    full_env = {**os.environ, **(env or {})}
    out = subprocess.run(
        [*command(t.run), *flags, str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
        cwd=REPO,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    from geotruth.numbers import json_loads

    return [json_loads(line) for line in out.stdout.splitlines() if line.strip()]


# ============================================================================ manifests


@pytest.mark.parametrize("d", MANAGED_DIRS)
def test_manifest_is_v2_and_lists_every_field_once(d):
    m = manifest.load_manifests()[d]
    schemas.validate("adapter", m)
    assert m["adapter"]["contract"] == "v2"
    for t in m["target"]:
        f = t["fields"]
        listed = [*f["supported"], *f.get("derived", {}), *f.get("unsupported", [])]
        assert len(listed) == len(set(listed)), (t["id"], "a field is listed twice")
        want = V2_PATHS if d in ("engine_control", "mutant") else V1_FIELDS | V2_PATHS
        assert set(listed) == want, (t["id"], want ^ set(listed))
        for w in shlex.split(t["run"]) + shlex.split(t["version_command"]):
            if "/" in w:
                assert (REPO / w).is_file(), (t["id"], w)


def test_managed_target_ids():
    assert IDS == [
        "engine-control",
        "turf",
        "polygon-clipping",
        "polyclip-ts",
        "martinez",
        "jsts",
        "jts-main",
        "jts-release",
        "mutant",
        "rust-geo",
        "shapely",
    ]
    assert len({t.lib for t in TARGETS}) == len(TARGETS)


def test_deltas_are_computable():
    """Every managed target with a documented budget gets a numeric delta for a case."""
    for t in TARGETS:
        d = manifest.delta_for(t, 8.0, [0.0, 0.0, 8.0, 4.0, 0.5, 0.25])
        if t.precision["delta"]["kind"] != "undocumented":
            assert d.delta2 is not None and d.delta2 > 0, (t.id, d.note)


# ============================================================================ canary


def _canary() -> dict:
    cases = json.loads((REPO / "schemas" / "examples" / "case.v2.valid.json").read_text())
    (c,) = [c for c in cases if c.get("ops") == ["echo"]]
    return c


def _bits(x) -> bytes:
    return struct.pack("<d", float(x))


def test_parse_echo_canary(tgt, tmp_path):
    """The echo returns exactly the doubles float() reads from the case (2^53+1 -> 2^53,
    subnormals, -0.0, 0.30000000000000004, the largest double), written by the adapter."""
    from geotruth.harness.score import _same_geometry
    from geotruth.io import geometry_from_json

    c = _canary()
    (r,) = run(tgt, [c], tmp_path)
    schemas.validator("result").validate(r)
    assert r["id"] == c["id"] and r["lib"] == tgt.lib and r["errors"] == {}
    for k in ("a", "b"):
        assert _same_geometry(geometry_from_json(c[k]), geometry_from_json(r["echo"][k])), k
    xs = r["echo"]["a"]["coordinates"]
    assert _bits(xs[1][0]) == _bits(-0.0)
    assert float(xs[0][0]) == 2.0**53 and float(xs[1][1]) == 0.30000000000000004


# ============================================================================ all pairs

SQ = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
GEOMS = {
    "P": {"type": "Point", "coordinates": [1, 1]},
    "Pe": {"type": "Point", "coordinates": []},
    "L": {"type": "LineString", "coordinates": [[0, 0], [2, 2]]},
    "Le": {"type": "LineString", "coordinates": []},
    "A": {"type": "Polygon", "coordinates": [SQ]},
    "Ah": {
        "type": "Polygon",
        "coordinates": [
            [[-1, -1], [4, -1], [4, 4], [-1, 4], [-1, -1]],
            [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5], [0.5, 0.5]],
        ],
    },
    "Ae": {"type": "Polygon", "coordinates": []},
    "MP": {"type": "MultiPoint", "coordinates": [[1, 1], [3, 3]]},
    "ML": {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[1, 1], [3, 1]]]},
    "MA": {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],
        ],
    },
    "GC": {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [5, 5]},
            {
                "type": "GeometryCollection",
                "geometries": [
                    {"type": "Polygon", "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
                ],
            },
        ],
    },
}
EMPTY = {"Pe", "Le", "Ae"}
POLYGONAL = {"A", "Ah", "Ae", "MA"}


def pair_cases() -> list[dict]:
    return [
        {
            "id": f"pair-{ka}-{kb}",
            "family": "pairs",
            "tags": {},
            "provenance": {"source": "manual"},
            "a": a,
            "b": b,
        }
        for ka, a in GEOMS.items()
        for kb, b in GEOMS.items()
    ]


def test_every_pair_gives_a_schema_valid_line(tgt, tmp_path):
    cases = pair_cases()
    if tgt.id == "martinez":
        cases = [c for c in cases if c["a"]["type"] in ("Polygon", "MultiPolygon")]
    recs = run(tgt, cases, tmp_path, env={"GEOTRUTH_OP_TIMEOUT": "5"})
    assert [r["id"] for r in recs] == [c["id"] for c in cases]
    v = schemas.validator("result")
    for r in recs:
        v.validate(r)
        assert r["lib"] == tgt.lib
        assert set(r) >= {"relate", "predicates", "valid_a", "valid_b", "overlay", "errors"}
        assert "echo" not in r  # not requested
    by = {r["id"]: r for r in recs}
    # polygon clippers: only polygonal pairs get overlays; everything else is out of contract
    if tgt.dir == "js" and tgt.id in ("polygon-clipping", "polyclip-ts", "martinez"):
        r = by.get("pair-L-A")
        if r is not None:
            assert r["overlay"]["union"] == "unsupported"
        assert by["pair-A-MA"]["overlay"]["intersection"]["type"] == "MultiPolygon"
        assert by["pair-A-MA"]["relate"] is None
    if tgt.id in ("jts-main", "jts-release"):
        # OverlayNG rejects a mixed GeometryCollection: out of contract
        assert by["pair-GC-A"]["overlay"]["union"] == "unsupported"
        assert by["pair-GC-A"]["relate"] not in (None, "unsupported")  # RelateNG takes GCs
    if tgt.id == "rust-geo":
        assert by["pair-Pe-A"]["relate"] == "unsupported"  # geo has no empty point
        assert by["pair-L-A"]["overlay"]["union"] == "unsupported"


def test_overlayng_takes_only_simple_collections(tgt, tmp_path):
    """OverlayNG's documented input (JTS javadoc, GEOS OverlayNG.h): a GeometryCollection
    must flatten into a valid multi-geometry. A non-simple one (overlapping polygons) is
    "unsupported"; a simple one is overlaid."""
    if tgt.id not in ("shapely", "jts-main", "jts-release"):
        pytest.skip("OverlayNG adapters only")

    def sq(x0: float, y0: float, s: float) -> dict:
        ring = [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s], [x0, y0]]
        return {"type": "Polygon", "coordinates": [ring]}

    def gc(*parts: dict) -> dict:
        return {"type": "GeometryCollection", "geometries": list(parts)}

    b = sq(0.5, 0.5, 2)
    cases = [
        {"id": "overlapping", "a": gc(sq(0, 0, 2), sq(1, 1, 2)), "b": b, "ops": ["overlay"]},
        {"id": "simple", "a": gc(sq(0, 0, 1), sq(2, 2, 1)), "b": b, "ops": ["overlay"]},
    ]
    over, simple = run(tgt, cases, tmp_path)
    assert set(over["overlay"].values()) == {"unsupported"} and not over["errors"]
    assert all(isinstance(g, dict) for g in simple["overlay"].values()), simple


def test_predicates_agree_with_the_same_runs_relate(tgt, tmp_path):
    """For adapters with RelateNG-semantics predicates (the dispatch of DESIGN §1), every
    reported predicate follows from the adapter's own matrix on non-empty pairs."""
    if tgt.id not in ("shapely", "jts-main", "jts-release", "engine-control"):
        pytest.skip("predicates with other semantics or no relate")
    from geotruth.io import geometry_from_json
    from geotruth.predicates import predicates

    cases = [
        c for c in pair_cases() if not ({c["id"].split("-")[1], c["id"].split("-")[2]} & EMPTY)
    ]
    for r, c in zip(run(tgt, cases, tmp_path), cases, strict=True):
        if not isinstance(r["relate"], str):
            continue
        da = geometry_from_json(c["a"]).real_dimension
        db = geometry_from_json(c["b"]).real_dimension
        want = predicates(r["relate"], da, db)
        got = {k: v for k, v in r["predicates"].items() if isinstance(v, bool)}
        assert got == {k: want[k] for k in got}, (c["id"], r["relate"])


def test_overlay_output_is_the_exact_area(tgt, tmp_path):
    """On a lattice pair every managed library's overlay has the exact area (measured
    exactly by even-odd on its output)."""
    if tgt.id == "mutant":
        pytest.skip("the mutant perturbs overlays on purpose")
    from fractions import Fraction

    from geotruth.harness import metrics as M
    from geotruth.io import geometry_from_json

    c = {
        "id": "sq",
        "a": GEOMS["A"],
        "b": {"type": "Polygon", "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]},
    }
    (r,) = run(tgt, [c], tmp_path)
    want = {"intersection": 1, "union": 7, "difference": 3, "symdifference": 6}
    for op, area in want.items():
        g = r["overlay"][op]
        if g is None:
            continue
        got = M.even_odd_area(M.shape_of(geometry_from_json(g)).rings())
        assert Fraction(got) == area, (op, g)


# ============================================================================ isolation


def test_hang_and_crash_fail_one_operation(tgt, tmp_path):
    if tgt.dir not in FAULTS or tgt.id == "martinez":
        pytest.skip("no fault injection for this adapter")
    var, hang, crash = FAULTS[tgt.dir]
    c = {"id": "sq", "a": GEOMS["A"], "b": GEOMS["MA"]}
    env = {
        var: hang,
        "GEOTRUTH_OP_TIMEOUT": "2",
        "JS_ADAPTER_TIMEOUT": "2",
        "GEO_ADAPTER_TIMEOUT": "2",
        "JTS_ADAPTER_TIMEOUT": "2",
    }
    (r,) = run(tgt, [c], tmp_path, env=env)
    schemas.validator("result").validate(r)
    assert r["errors"]["overlay.union"]["kind"] == "timeout"
    assert r["overlay"]["union"] is None
    assert r["overlay"]["difference"] is not None  # the next operation ran in a fresh worker
    (r,) = run(tgt, [c], tmp_path, env={**env, var: crash})
    path = crash.split(":", 1)[1]
    assert r["errors"][path]["kind"] == "crash", r["errors"]
    others = [p for p in ("overlay.union", "overlay.difference") if p != path]
    assert all(r["overlay"][p.split(".")[1]] is not None for p in others)


def test_legacy_lines_keep_the_v1_contract(tgt, tmp_path):
    if tgt.dir in ("engine_control", "mutant"):
        pytest.skip("contract v2 only")
    line = json.loads((REPO / "corpus" / "cases" / "seed.jsonl").read_text().splitlines()[0])
    (r,) = run(tgt, [line], tmp_path)
    assert set(r) >= V1_FIELDS and "relate" not in r and "overlay" not in r
    area = r["area_inter"]
    assert area is None or (isinstance(area, float) and math.isfinite(area))
