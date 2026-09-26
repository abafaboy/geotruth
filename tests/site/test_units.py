"""Unit tests of the site generator's parts: exact clipping and distances, the zoom
windows, the vocabulary, links, the registry matching and the example selection."""

from __future__ import annotations

from fractions import Fraction as F

import pytest

pytestmark = pytest.mark.unit


# ============================================================================ exact2d


def test_clip_segment_exact():
    from gtsite.exact2d import clip_segment

    box = (F(0), F(0), F(1), F(1))
    assert clip_segment((F(-1), F(F(1, 2))), (F(2), F(1, 2)), box) == ((0, F(1, 2)), (1, F(1, 2)))
    assert clip_segment((F(-1), F(-1)), (F(2), F(2)), box) == ((0, 0), (1, 1))
    assert clip_segment((F(2), F(2)), (F(3), F(5)), box) is None
    # a segment 1e-300 wide, far from the origin, clips exactly
    x = F(10**300)
    e = F(1, 10**300)
    tiny = (x - e, x - e, x + e, x + e)
    got = clip_segment((x - 2 * e, x), (x + 2 * e, x), tiny)
    assert got == ((x - e, x), (x + e, x))


def test_clip_ring_keeps_the_part_inside():
    from gtsite.exact2d import clip_ring

    box = (F(0), F(0), F(1), F(1))
    square = [(F(-1), F(-1)), (F(2), F(-1)), (F(2), F(2)), (F(-1), F(2)), (F(-1), F(-1))]
    assert sorted(clip_ring(square, box)) == sorted([(0, 0), (1, 0), (1, 1), (0, 1)])
    tri = [(F(0), F(0)), (F(2), F(0)), (F(0), F(2)), (F(0), F(0))]
    got = clip_ring(tri, box)
    area2 = sum(got[i][0] * got[i - 1][1] - got[i - 1][0] * got[i][1] for i in range(len(got)))
    assert abs(area2) == 2  # the whole unit square lies under the hypotenuse x + y = 2
    far = [(F(5), F(5)), (F(6), F(5)), (F(6), F(6)), (F(5), F(5))]
    assert clip_ring(far, box) == []


def test_point_in_polygons_and_distances():
    from gtsite.exact2d import Parts, in_polygons, nearest_in, sqrt_frac

    sq = [[(F(0), F(0)), (F(4), F(0)), (F(4), F(4)), (F(0), F(4)), (F(0), F(0))]]
    hole = [(F(1), F(1)), (F(1), F(3)), (F(3), F(3)), (F(3), F(1)), (F(1), F(1))]
    parts = Parts(polygons=[[sq[0], hole]])
    assert in_polygons((F(1, 2), F(1, 2)), parts)
    assert not in_polygons((F(2), F(2)), parts)  # in the hole
    assert in_polygons((F(1), F(2)), parts)  # on the hole's edge
    assert nearest_in((F(2), F(2)), parts) == (1, (F(1), F(2)))
    assert nearest_in((F(1, 2), F(1, 2)), parts)[0] == 0
    assert sqrt_frac(F(9, 4)) == F(3, 2)
    small = sqrt_frac(F(1, 10**600))
    assert abs(small - F(1, 10**300)) < F(1, 10**306)


def test_parts_of_types():
    from gtsite.exact2d import parts_of

    from geotruth.io import read_wkt

    g = read_wkt(
        "GEOMETRYCOLLECTION (POINT (1 2), LINESTRING (0 0, 1 1), LINESTRING (3 3, 3 3), "
        "POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT EMPTY)"
    )
    p = parts_of(g)
    assert p.points == [(1, 2), (3, 3)]  # a zero-length line is drawn as a point
    assert p.lines == [[(0, 0), (1, 1)]]
    assert len(p.polygons) == 1 and p.polygons[0][0][0] == p.polygons[0][0][-1]


# ============================================================================ locus


def test_closest_approach_finds_the_near_miss():
    from gtsite.exact2d import Parts
    from gtsite.locus import closest_approach, contacts

    eps = F(1, 2**60)
    a = Parts(polygons=[[[(F(0), F(0)), (F(4), F(0)), (F(2), F(2)), (F(0), F(0))]]])
    b = Parts(polygons=[[[(F(1), -eps), (F(3), -eps), (F(2), F(-5)), (F(1), -eps)]]])
    d2, p, q = closest_approach(a, b)
    assert d2 == eps * eps
    assert p[1] == 0 and q[1] == -eps
    touch = Parts(polygons=[[[(F(2), F(0)), (F(3), F(-1)), (F(1), F(-1)), (F(2), F(0))]]])
    assert (2, 0) in contacts(a, touch)


def test_deviation_names_the_far_point():
    from gtsite.exact2d import Parts
    from gtsite.locus import deviation

    exact = Parts(
        polygons=[[[(F(0), F(0)), (F(2), F(0)), (F(2), F(2)), (F(0), F(2)), (F(0), F(0))]]]
    )
    lib = Parts(polygons=[[[(F(0), F(0)), (F(3), F(0)), (F(2), F(2)), (F(0), F(2)), (F(0), F(0))]]])
    d2, p, q, who = deviation(exact, lib)
    assert (p, q, who) == ((3, 0), (2, 0), "library") and d2 == 1


def test_self_approach_skips_adjacent_edges():
    from gtsite.exact2d import Parts
    from gtsite.locus import self_approach

    eps = F(1, 2**50)
    # a C shape whose tip nearly touches its own back
    ring = [(F(0), F(0)), (F(4), F(0)), (F(4), F(1)), (F(1), F(1)), (F(1), F(2)), (F(4), F(2)),
            (F(4), F(3)), (F(0), F(3)), (F(0), F(0))]  # fmt: skip
    assert self_approach(Parts(polygons=[[ring]]))[0] == 1
    # a notch whose apex comes within eps of the opposite edge
    ring2 = [(F(0), F(0)), (F(4), F(0)), (F(4), F(4)), (F(2), eps), (F(0), F(4)), (F(0), F(0))]
    d2, p, q = self_approach(Parts(polygons=[[ring2]]))
    assert (d2, p, q) == (eps * eps, (2, eps), (2, 0))


def test_svg_render_is_well_formed_at_extreme_scale():
    import xml.etree.ElementTree as ET

    from gtsite.exact2d import Parts
    from gtsite.locus import View
    from gtsite.svg import Layer, render

    big = F(2) ** 1000
    ulp = F(2) ** (1000 - 52)
    a = Parts(polygons=[[[(big, big), (big + 4 * ulp, big), (big, big + 4 * ulp), (big, big)]]])
    b = Parts(lines=[[(big - ulp, big + ulp), (big + 5 * ulp, big + ulp)]])
    view = View(big + ulp, big + ulp, 3 * ulp, "test", [(big, big)])
    svg, markers = render(view, [Layer(a, "a"), Layer(b, "b")], uid="t", title="T", desc="D & <x>")
    root = ET.fromstring(svg)
    assert root.get("viewBox") == "0 0 400 400"
    assert "inf" not in svg and "nan" not in svg.lower().replace("class", "")
    assert markers and markers[0].point in (
        (big, big),
        (big - ulp, big + ulp),
        (big + 4 * ulp, big),
    )
    assert "D &amp; &lt;x&gt;" in svg


# ============================================================================ words, html


def test_vocabulary_covers_the_scorer():
    from gtsite import words

    from geotruth import schemas
    from geotruth.harness import score

    assert set(score.CAPABILITIES) == set(words.CAPABILITIES)
    assert tuple(score.TIERS) == words.TIERS
    assert tuple(score.HEADLINE_TIERS) == words.HEADLINE_TIERS
    schema = schemas.load_schema("score")
    assert set(schema["properties"]["verdict"]["enum"]) == set(words.VERDICTS)
    assert set(schema["properties"]["tier"]["enum"]) == set(words.TIERS)
    for cap in words.CAPABILITIES:
        assert cap in words.CAPABILITY_NAMES and cap in words.CAPABILITY_TEXT
    for v in words.VERDICTS:
        assert v in words.VERDICT_TEXT


@pytest.mark.parametrize(
    ("sig", "cap", "want"),
    [
        ("relate:BB", "relate", "the DE-9IM entry BB differs from the exact matrix"),
        ("relate:II,IB", "relate", "the DE-9IM entries II, IB differ from the exact matrix"),
        ("predicates:touches,covered_by", "predicates", "wrong predicates: touches, covered by"),
        ("validity:valid_a=false", "validity", "reports A invalid, but A is valid"),
        ("validity:valid_b=true", "validity", "reports B valid, but B is invalid"),
        ("overlay.union:gross", "overlay.union", "union: output beyond"),
        ("overlay.intersection:exception", "overlay.intersection", "(tier 6)"),
        ("echo", "echo", "bit for bit"),
        ("relate:error", "relate", "raised an error"),
        ("predicates:touches|tolerance", "predicates", "tolerance-based predicates"),
    ],
)
def test_explain_signature(sig, cap, want):
    from gtsite.words import explain_signature

    assert want in explain_signature(sig, cap)


def test_fmt_pct_never_hides_a_failure():
    from gtsite.words import fmt_pct

    assert fmt_pct(0, 10) == "0%"
    assert fmt_pct(10, 10) == "100%"
    assert fmt_pct(1, 3200) == "0.03%"
    assert fmt_pct(3199, 3200) == "99.97%"
    assert fmt_pct(162, 3200) == "5.1%"
    assert fmt_pct(1, 0) == "–"


def test_relative_links():
    from gtsite.html import rel

    assert rel("index.html", "lib/a.html#x") == "lib/a.html#x"
    assert rel("lib/a.html", "index.html") == "../index.html"
    assert rel("cluster/t/c.html", "lib/t.html#cap-relate") == "../../lib/t.html#cap-relate"
    assert rel("lib/a.html", "lib/b.html") == "b.html"


def test_coordinates_are_printed_exactly():
    from gtsite.html import approx, coord_cell

    cell = coord_cell(F(0.1))
    assert "0.1<" in cell and (0.1).hex() in cell
    third = coord_cell(F(1, 3))
    assert "1/3" in third
    long = coord_cell(F(10**60 + 1, 3**50))
    assert str(10**60 + 1) in long and "<details" in long  # the full value behind a disclosure
    assert approx(F(10**300, 7)) == "1.4285714285714286e299"


# ============================================================================ triage


def _cluster(target="shapely", family="touch", cap="relate", sig="relate:BB"):
    from gtsite.aggregate import Cluster

    return Cluster(f"{target}|{family}|{sig}", target, family, cap, sig, "scorer")


def test_registry_matching_rules():
    from gtsite.triage import matches, status

    f1 = {
        "id": "f1",
        "library": "shapely",
        "fields": ["relate"],
        "families": ["touch"],
        "status": "confirmed",
    }
    f2 = {
        "id": "f2",
        "library": "shapely",
        "fields": ["area_union"],
        "families": [],
        "status": "by-design",
    }
    lead = {"id": "l", "library": ["shapely", "x"], "status": "unreviewed", "kind": "lead"}
    other = {"id": "o", "library": "clipper2", "fields": ["relate"], "status": "fixed"}
    reg = [f1, f2, lead, other]
    assert matches(_cluster(), reg) == [f1]
    assert matches(_cluster(family="other"), reg) == []
    union = _cluster(cap="overlay.union", sig="overlay.union:gross")
    assert matches(union, reg) == [f2]  # v1 field names are translated
    assert status([]) == "unreviewed"
    assert status([f1]) == "confirmed"
    assert status([f1, f2]) == "mixed"


def test_registry_matching_narrows_predicates_to_the_ones_named():
    from gtsite.triage import matches

    touches = {
        "id": "t",
        "library": "turf",
        "fields": ["predicates.touches"],
        "families": ["shared-edge"],
        "status": "confirmed",
    }
    any_predicate = {"id": "a", "library": "turf", "fields": ["relate"], "status": "confirmed"}
    v1 = {"id": "v", "library": "turf", "fields": ["overlaps"], "status": "by-design"}
    reg = [touches, any_predicate, v1]

    def pred(sig):
        return _cluster("turf", "shared-edge", "predicates", sig)

    assert matches(pred("predicates:touches,overlaps|tolerance"), reg) == [touches, v1]
    assert matches(pred("predicates:overlaps|tolerance"), reg) == [v1]
    assert matches(pred("predicates:within"), reg) == []
    assert matches(pred("predicates:error"), reg) == [touches, v1]  # errors name no predicate


def test_example_selection_prefers_small_and_varied_cases():
    from gtsite import select_examples

    recs = [
        {"id": "c-3", "tags": {"n": 30, "variant": "a.x"}},
        {"id": "c-1", "tags": {"n": 5, "variant": "a.y"}},
        {"id": "c-2", "tags": {"n": 6, "variant": "a.z"}},
        {"id": "c-4", "tags": {"n": 40, "variant": "b"}},
        {"id": "c-1", "tags": {"n": 5, "variant": "a.y"}},  # a second record of one case
    ]
    got = [r["id"] for r in select_examples(recs, 2)]
    assert got == ["c-1", "c-4"]  # the smallest, then a new variant family
    assert [r["id"] for r in select_examples(recs, 10)] == ["c-1", "c-4", "c-2", "c-3"]


def test_aggregate_matches_summarize(synthetic_results):
    from gtsite.aggregate import LibraryStats

    from geotruth.harness.score import summarize

    for target, recs in synthetic_results["records"].items():
        st = LibraryStats(target)
        for r in recs:
            st.add(r)
        s = summarize(recs)
        assert st.headline == s["headline_failures"]
        assert {k: dict(v.verdicts) for k, v in st.caps.items()} == s["verdicts"]
        scorer = {k: c.count for k, c in st.clusters.items() if c.key_source == "scorer"}
        assert scorer == s["clusters"]
        assert len(st.cases) == s["cases"]


def _topo(hausdorff2: str, symdiff: str, valid: bool, **extra) -> dict:
    metrics = {"output_valid": valid, "hausdorff2": hausdorff2, "symdiff_area": symdiff}
    if not valid:
        metrics["output_reason"] = "ring_self_intersection"
    metrics.update(extra)
    return {
        "id": f"c-{hausdorff2}-{valid}",
        "capability": "overlay.union",
        "verdict": "wrong",
        "tier": "topological",
        "metrics": metrics,
    }


def test_exact_point_set_but_invalid_output():
    from gtsite.aggregate import CapStats, Cluster, is_exact_but_invalid
    from gtsite.pages import invalid_note

    exact_invalid = _topo("0", "0", False)
    near_invalid = _topo("1/4", "1/1024", False)
    missing = _topo("4", "2", True, missing_components=1)
    assert is_exact_but_invalid(exact_invalid)
    assert not is_exact_but_invalid(near_invalid) and not is_exact_but_invalid(missing)
    cs = CapStats()
    for r in (exact_invalid, near_invalid, missing):
        cs.add(r)
    assert cs.exact_but_invalid == 1 and cs.headline == 3
    key = "t|f|overlay.union:topological"
    cl = Cluster(key, "t", "f", "overlay.union", "overlay.union:topological", "scorer")
    cl.records = [exact_invalid, near_invalid, missing]
    note = invalid_note(cl)
    assert "2 of 3 outputs are not valid OGC geometry (ring self intersection (2))" in note
    assert "1 of them cover exactly the right point set" in note


def test_overlay_comparison_notes():
    from gtsite.examples import compare_overlay

    exact = compare_overlay(_topo("0", "0", False), "1", F(1))
    assert "covers exactly the right point set" in exact
    within = compare_overlay(
        _topo("1/100", "1/1000", False, delta=0.5, delta_kind="grid"), None, None
    )
    assert "within δ_lib" in within
    beyond = compare_overlay(_topo("1", "1/1000", False, delta=0.5, delta_kind="grid"), None, None)
    assert "within" not in beyond.split("Tier")[0] and "is within" not in beyond
