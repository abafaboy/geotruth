"""geotruth.export: the five formats, the exact-answer shim, and running the exports."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from conftest import DATA, id_list, records_by_id
from geotruth.export import EXTENSIONS, FORMATS, export_records, prepare
from geotruth.export.answers import exact_answer
from geotruth.export.boost import boost_wkt
from geotruth.export.clipper2 import scale_bits
from geotruth.export.common import area_bounds, signed_ring_area
from geotruth.io import geometry_to_json, read_wkt

pytestmark = pytest.mark.unit

TOUCH = "relateng-multipolygon-touching-parts:t-touch-part-min"
GC_LEAD = "relateng-gc-polygon-with-exterior-point:gc-poly-exterior-point"


def case(cid, a, b, family="t"):
    return {
        "id": cid,
        "family": family,
        "a": geometry_to_json(read_wkt(a)),
        "b": geometry_to_json(read_wkt(b)),
    }


SMALL = [
    case("sq", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))"),
    case("lp", "LINESTRING (0 0, 4 4)", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"),
    case("gc", "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (5 5))", "POINT (5 5)"),
    case("em", "POINT EMPTY", "LINESTRING (0 0, 1 1)"),
    case("bad", "POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))", "POINT (1 1)"),
]


# ============================================================================ shim


def test_exact_answer_polygons_engine_and_oracle_agree():
    a = read_wkt("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))")
    b = read_wkt("POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))")
    ans = exact_answer(a, b)
    assert ans.relate == "212101212"
    assert ans.areas == {
        "a": 16,
        "b": 16,
        "intersection": 4,
        "union": 28,
        "difference": 12,
        "symdifference": 24,
    }
    assert ans.field("area_union") == 28 == ans.field("overlay.union")
    assert ans.field("within") is False and ans.field("predicates.overlaps") is True


def test_exact_answer_other_types_and_invalid():
    ans = exact_answer(read_wkt("LINESTRING (0 0, 4 4)"), read_wkt("POINT (2 2)"))
    assert ans.relate == "0F1FF0FF2" and ans.areas["union"] == 0
    bad = exact_answer(read_wkt("POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"), read_wkt("POINT (1 1)"))
    assert bad.valid_a is False and bad.relate is None and bad.areas is None


def test_every_format_is_registered():
    assert set(FORMATS) == set(EXTENSIONS) == {"jts-xml", "boost", "clipper2", "geo-rust", "pytest"}
    for fmt in FORMATS:
        files = export_records(SMALL, fmt)
        assert files and all(f.text.endswith("\n") for f in files)


# ============================================================================ JTS XML


def test_jts_xml_structure():
    [f] = export_records(SMALL, "jts-xml")
    run = ET.fromstring(f.text)
    assert run.tag == "run"
    assert run.find("precisionModel").get("type") == "FLOATING"
    assert float(run.find("tolerance").text) > 0
    cases = run.findall("case")
    descs = [c.find("desc").text for c in cases]
    assert descs[0].startswith("sq;") and "area(A union B) = 28" in descs[1]
    ops = {(o.get("name"), o.get("arg1"), o.get("arg3"), o.text) for o in cases[0].iter("op")}
    assert ("relate", "A", "212101212", "true") in ops
    assert ("coveredBy", "A", None, "false") in ops and ("equalsTopo", "A", None, "false") in ops
    assert ("unionArea", "A", None, "16.0") in ops
    assert (
        cases[1].find("a").text.strip() == "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, "
        "0 0)), POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2)))"
    )
    bad = next(c for c in cases if c.find("desc").text.startswith("bad"))
    assert {o.get("name") for o in bad.iter("op")} == {"isValid"}
    empty = next(c for c in cases if c.find("desc").text.startswith("em"))
    names = [o.get("name") for o in empty.iter("op")]
    # within/covered_by(EMPTY, X) come from the convention table: left out
    assert "relate" in names and "within" not in names and "coveredBy" not in names
    assert "contains" in names


def test_jts_xml_splits_scales_that_cannot_share_a_tolerance():
    recs = [
        case("big", "POLYGON ((0 0, 1e6 0, 1e6 1e6, 0 0))", "POLYGON ((0 0, 1 0, 1 1, 0 0))"),
        case(
            "tiny",
            "POLYGON ((0 0, 1e-6 0, 1e-6 1e-6, 0 0))",
            "POLYGON ((0 0, 1e-7 0, 1e-7 1e-7, 0 0))",
        ),
    ]
    files = export_records(recs, "jts-xml")
    assert [f.suffix for f in files] == [".part1", ".part2"]
    tols = [float(ET.fromstring(f.text).find("tolerance").text) for f in files]
    assert tols[0] < tols[1]


def test_area_bounds_follow_the_rounding_floor():
    [thin] = prepare(
        records_by_id(["geo-i-overlay-thin-triangle-collapse:int-thin-triangle-1-0010"])
    )
    lo, hi = area_bounds(thin, 1e-6)
    assert lo > 1e-6 * float(thin.area_scale())  # rounding dominates: 2 x the floor
    assert hi == 2 * lo and hi < float(thin.area_scale()) / 2
    [sq] = prepare(SMALL[:1])
    assert area_bounds(sq, 1e-6)[1] == pytest.approx(1e-6 * 16)


# ============================================================================ others


def test_boost_orientation_and_skips():
    [f] = export_records(SMALL, "boost")
    assert "static std::string geotruth_sq[2]" in f.text
    assert "TEST_INTERSECTION(geotruth_sq, -1, -1, 4.0);" in f.text
    assert "TEST_UNION(geotruth_sq, -1, -1, -1, 28.0);" in f.text
    assert "TEST_DIFFERENCE(geotruth_sq, -1, 12.0, -1, 12.0, -1);" in f.text
    assert "test_geometry<ls, poly>(" in f.text
    assert f.skipped == ["gc", "em", "bad"]
    w = boost_wkt(read_wkt("POLYGON ((0 0, 4 0, 4 4, 0 0), (1 0.5, 3 2.5, 3 0.5, 1 0.5))"))
    shell, hole = re.findall(r"\(([^()]+)\)", w)

    def ring(t):
        return tuple(tuple(float(v) for v in p.split()) for p in t.split(","))

    assert signed_ring_area(ring(shell)) < 0 < signed_ring_area(ring(hole))  # CW shell, CCW hole


def test_clipper2_blocks_are_integer_scaled():
    assert scale_bits([1, 2.5, -0.125]) == 3
    assert scale_bits([0.1]) == 55
    assert scale_bits([2.0**-61]) is None
    assert scale_bits([2.0**62]) is None
    recs = [case("h", "POLYGON ((0 0, 1.5 0, 1.5 1.5, 0 0))", "POLYGON ((0 0, 1 0, 1 1, 0 0))")]
    [f] = export_records(recs, "clipper2")
    blocks = f.text.split("CAPTION:")[1:]
    assert [re.search(r"CLIPTYPE: (\w+)", b).group(1) for b in blocks] == [
        "INTERSECTION",
        "UNION",
        "DIFFERENCE",
        "XOR",
    ]
    first = blocks[0]
    assert "(scale 2^1" in first and "SOL_AREA: 2\n" in first  # area 0.5 x 4
    assert "SUBJECTS\n0,0, 3,0, 3,3\nCLIPS\n0,0, 2,0, 2,2\n" in first


def test_geo_rust_uses_float_literals():
    [f] = export_records(SMALL, "geo-rust")
    for lit in re.findall(r"wkt! \{ ([^}]*) \}", f.text):
        nums = re.findall(r"-?[0-9][0-9.e+-]*", lit)
        assert nums and all("." in n or "e" in n for n in nums), lit
    assert 'assert!(im.matches("212101212").unwrap()' in f.text
    assert "let got: f64 = a.xor(&b).unsigned_area();" in f.text
    assert f.skipped == ["em"]


# ============================================================================ running


def test_known_lists_exist_and_resolve():
    good = id_list("xml_known_good.txt")
    assert len(good) >= 20
    records_by_id(good)
    failing = [
        ln.split("\t")
        for ln in (DATA / "xml_known_failing.txt").read_text().splitlines()
        if ln and not ln.startswith("#")
    ]
    assert len(records_by_id([f[0] for f in failing])) == len(failing) == 3
