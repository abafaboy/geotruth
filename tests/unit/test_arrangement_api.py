"""Tests of the frozen Arrangement API: invariants, navigation, and the hand fixtures.

Every fixture label is checked three ways: ``validate(labels=True)`` (internal
consistency), the DE-9IM it implies (against the hand-written matrix), and -- when
Shapely is installed -- GEOS's location of each vertex, edge midpoint and face witness.
"""

from __future__ import annotations

import copy
from fractions import Fraction

import pytest

from geotruth.arrangement_api import Arrangement, ArrangementError, EdgeSource, Location
from geotruth.geom import GEOM_A, GEOM_B, SourceTag

from .fixtures_arrangement import FIXTURES, FixtureSpec, build, fixture, labels_matrix, line, ring

I, B, E = Location.INTERIOR, Location.BOUNDARY, Location.EXTERIOR
NAMES = sorted(FIXTURES)


# ============================================================================ fixtures


@pytest.mark.parametrize("name", NAMES)
def test_fixture_validates(name):
    fixture(name).validate(geometry=True, planarity=True, labels=True)


@pytest.mark.parametrize("name", NAMES)
def test_fixture_labels_imply_relate(name):
    assert labels_matrix(fixture(name)) == FIXTURES[name].relate


@pytest.mark.parametrize("name", NAMES)
def test_fixture_euler_characteristic(name):
    arr = fixture(name)
    parent = list(range(arr.num_vertices))

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for e in range(arr.num_edges):
        parent[find(arr.he_origin[2 * e])] = find(arr.he_origin[2 * e + 1])
    components = len({find(v) for v in range(arr.num_vertices)})
    assert arr.num_vertices - arr.num_edges + arr.num_faces == 1 + components


def test_there_are_at_least_ten_fixtures():
    assert len(FIXTURES) >= 10


def _loc_from_matrix(matrix: str) -> Location:
    """Location of a point P in X from relate(P, X): row I of the matrix."""
    if matrix[0] != "F":
        return I
    if matrix[1] != "F":
        return B
    return E


def _exact_double(q) -> float | None:
    f = float(q)
    return f if Fraction(f) == Fraction(q) else None


@pytest.mark.parametrize("name", NAMES)
def test_fixture_labels_against_geos(name):
    """Each labelled cell, located by GEOS at a representative point."""
    shapely = pytest.importorskip("shapely")
    spec = FIXTURES[name]
    arr = fixture(name)
    ga, gb = shapely.from_wkt(spec.a), shapely.from_wkt(spec.b)
    assert ga.relate(gb) == spec.relate

    def check(point, expected_a, expected_b, what):
        xy = [_exact_double(v) for v in point]
        if None in xy:
            return  # not a double: GEOS cannot be asked about it exactly
        p = shapely.Point(*xy)
        got = (_loc_from_matrix(p.relate(ga)), _loc_from_matrix(p.relate(gb)))
        assert got == (expected_a, expected_b), f"{name}: {what} at {point}"

    for v in range(arr.num_vertices):
        check(arr.vertex_fractions(v), arr.vertex_loc_a[v], arr.vertex_loc_b[v], f"vertex {v}")
    for e in range(arr.num_edges):
        (x0, y0), (x1, y1) = (
            arr.vertex_fractions(arr.he_origin[2 * e]),
            arr.vertex_fractions(arr.he_origin[2 * e + 1]),
        )
        for t in (Fraction(1, 2), Fraction(1, 4)):
            mid = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
            check(mid, arr.edge_loc_a[e], arr.edge_loc_b[e], f"edge {e}")
    for witness, lab in spec.faces:
        check(
            tuple(Fraction(c) for c in witness),
            Location.from_char(lab[0]),
            Location.from_char(lab[1]),
            "face witness",
        )


# ---------------------------------------------------------------- specific shapes


def test_nested_squares_annulus_has_an_inner_component():
    arr = fixture("nested_squares")
    annulus = [f for f in range(arr.num_faces) if (arr.face_loc_a[f], arr.face_loc_b[f]) == (I, E)]
    assert len(annulus) == 1
    f = annulus[0]
    assert arr.face_outer[f] >= 0 and len(arr.face_inner[f]) == 1
    # the classic trap: the centroid of the annulus's OUTER cycle lies in the island
    xs = [arr.vertex_fractions(arr.he_origin[h]) for h in arr.cycle(arr.face_outer[f])]
    cx = sum(p[0] for p in xs) / len(xs)
    cy = sum(p[1] for p in xs) / len(xs)
    assert (cx, cy) == (5, 5)
    island = [g for g in range(arr.num_faces) if (arr.face_loc_a[g], arr.face_loc_b[g]) == (I, I)]
    assert island and island[0] != f


def test_dangling_line_degree_one_vertices_turn_around():
    arr = fixture("dangling_line")
    for v in (5, 6):  # the two free ends of the line
        (g,) = list(arr.outgoing(v))
        assert arr.degree(v) == 1
        assert arr.he_next[arr.he_twin[g]] == g  # next = twin: the walk turns around
    # the inner dangling edge has the same face on both sides (A's interior)
    e = next(
        e
        for e in range(arr.num_edges)
        if arr.tags(e) == {SourceTag.for_line(GEOM_B, 0)} and arr.edge_loc_a[e] == I
    )
    assert arr.he_face[2 * e] == arr.he_face[2 * e + 1] != 0


def test_crossing_lines_has_a_homogeneous_vertex():
    arr = fixture("crossing_lines")
    assert arr.vertex(4) == (6, 2, 5)
    assert arr.vertex_fractions(4) == (Fraction(6, 5), Fraction(2, 5))
    assert arr.degree(4) == 4 and arr.num_faces == 1
    assert len(arr.face_inner[0]) == 1  # one tree component in the unbounded face


def test_points_only_and_empty():
    arr = fixture("points_only")
    assert arr.num_edges == 0 and arr.num_faces == 1
    assert sorted(arr.face_isolated[0]) == [0, 1]
    assert all(arr.is_isolated(v) for v in range(arr.num_vertices))
    assert list(arr.outgoing(0)) == []
    empty = fixture("both_empty")
    assert (empty.num_vertices, empty.num_edges, empty.num_faces) == (0, 0, 1)
    assert [c.dim for c in empty.cells()] == [2]


def test_hole_touching_shell_structure():
    arr = fixture("hole_touching_shell")
    assert arr.degree(4) == 4  # the touch point (0, 2)
    hole_face = next(
        f for f in range(1, arr.num_faces) if (arr.face_loc_a[f], arr.face_loc_b[f]) == (E, E)
    )
    assert arr.face_isolated[hole_face] == [7]  # B's point sits in the hole
    assert arr.face_inner[hole_face] == []


def test_arrangement_new_is_valid():
    arr = Arrangement.new()
    arr.validate()
    assert arr.num_faces == 1 and arr.face_outer == [-1]


# ======================================================================= navigation


def test_outgoing_is_counter_clockwise():
    arr = fixture("overlapping_squares")
    v = 8  # crossing (2, 1): edges to (2, 0) down, (3, 1) right, (2, 2) up, (1, 1) left
    dirs = []
    for g in arr.outgoing(v):
        x0, y0 = arr.vertex_fractions(v)
        x1, y1 = arr.vertex_fractions(arr.dest(g))
        dirs.append((x1 - x0, y1 - y0))
    start = dirs.index((1, 0))
    assert dirs[start:] + dirs[:start] == [(1, 0), (0, 1), (-1, 0), (0, -1)]


def test_cycles_and_faces():
    arr = fixture("two_disjoint_squares")
    for f in range(arr.num_faces):
        hs = list(arr.face_half_edges(f))
        assert all(arr.he_face[h] == f for h in hs)
    assert (
        sum(len(list(arr.face_half_edges(f))) for f in range(arr.num_faces)) == arr.num_half_edges
    )
    assert len(arr.boundary_components(0)) == 2
    for h in range(arr.num_half_edges):
        cyc = list(arr.cycle(h))
        assert cyc[0] == h and len(cyc) == 4


def test_sources_are_flipped_on_the_twin():
    arr = fixture("shared_edge")
    e = next(e for e in range(arr.num_edges) if len(arr.edge_sources[e]) == 2)
    fwd = {s.tag.geom: s.forward for s in arr.sources(2 * e)}
    rev = {s.tag.geom: s.forward for s in arr.sources(2 * e + 1)}
    assert fwd == {GEOM_A: True, GEOM_B: False}
    assert rev == {GEOM_A: False, GEOM_B: True}
    assert arr.tags(e) == {SourceTag.for_ring(GEOM_A, 0, 0), SourceTag.for_ring(GEOM_B, 0, 0)}
    assert Arrangement.edge_of(2 * e + 1) == e


def test_interior_is_left_gives_face_labels_without_sample_points():
    """The DESIGN §2.2 labelling rule, applied to every fixture ring edge."""
    for name in NAMES:
        arr = fixture(name)
        for h in range(arr.num_half_edges):
            for src in arr.sources(h):
                if src.tag.is_line:
                    with pytest.raises(ValueError):
                        arr.interior_is_left(h, src)
                    continue
                locs = arr.face_loc_a if src.tag.geom == GEOM_A else arr.face_loc_b
                left, right = arr.he_face[h], arr.he_face[h ^ 1]
                inside = arr.interior_is_left(h, src)
                # these fixtures have no overlapping elements, so the ring side decides
                assert locs[left] == (I if inside else E), (name, h)
                assert locs[right] == (E if inside else I), (name, h)


def test_cells_and_dump():
    arr = fixture("dangling_line")
    cells = list(arr.cells())
    assert [c.dim for c in cells].count(0) == arr.num_vertices
    assert [c.dim for c in cells].count(1) == arr.num_edges
    assert [c.dim for c in cells].count(2) == arr.num_faces
    assert all(isinstance(c.loc_a, Location) for c in cells)
    text = arr.dump()
    assert "B.e0.line+" in text and "f0 EE" in text


def test_location_chars():
    assert [str(x) for x in Location] == ["I", "B", "E", "-"]
    assert all(Location.from_char(x.char) is x for x in Location)
    with pytest.raises(ValueError):
        Location.from_char("X")


def test_add_vertex_canonicalises():
    arr = Arrangement.new()
    v = arr.add_vertex(4, 6, -2)
    assert arr.vertex(v) == (-2, -3, 1)


def test_vertex_fractions_apply_the_scale():
    arr = Arrangement.new(scale_exp=-2)
    arr.add_vertex(6, 2, 5)
    assert arr.vertex_fractions(0) == (Fraction(6, 20), Fraction(2, 20))
    arr2 = Arrangement.new(scale_exp=3)
    arr2.add_vertex(1, -1)
    assert arr2.vertex_fractions(0) == (8, -8)


# ================================================================ mutation tests


def broken(name: str, mutate) -> Arrangement:
    arr = copy.deepcopy(fixture(name))
    mutate(arr)
    return arr


def expect(arr: Arrangement, code: str, **kw) -> None:
    with pytest.raises(ArrangementError) as info:
        arr.validate(**{"geometry": True, "planarity": True, "labels": True, **kw})
    assert any(p.startswith(code) for p in info.value.problems), info.value.problems


def _swap_next(arr):
    arr.he_next[0], arr.he_next[2] = arr.he_next[2], arr.he_next[0]


def _set(attr, index, value):
    def mutate(arr):
        getattr(arr, attr)[index] = value

    return mutate


@pytest.mark.parametrize(
    ("name", "mutate", "code"),
    [
        ("two_disjoint_squares", lambda a: a.vy.pop(), "T1"),
        ("two_disjoint_squares", _set("he_next", 0, 999), "T1"),
        ("two_disjoint_squares", _set("vx", 1, 0), "T2"),  # duplicates vertex 0
        ("corner_touch", _set("vw", 0, 2), "T2"),  # (0, 0, 2) is not canonical
        ("two_disjoint_squares", _set("he_twin", 0, 2), "T3"),
        ("two_disjoint_squares", _set("he_origin", 1, 0), "T3"),  # loop edge
        ("two_disjoint_squares", _swap_next, "T4"),
        ("two_disjoint_squares", _set("he_face", 0, 2), "T5"),
        ("dangling_line", _set("vertex_edge", 0, 3), "T6"),
        ("points_only", _set("vertex_edge", 0, 0), "T1"),
        ("nested_squares", _set("face_outer", 1, -1), "T7"),
        ("nested_squares", lambda a: a.face_inner[0].append(a.face_inner[0][0]), "T7"),
        ("point_in_polygon", lambda a: a.face_isolated[1].clear(), "T9"),
        ("point_in_polygon", lambda a: a.face_isolated[0].append(4), "T9"),
        ("shared_edge", lambda a: a.ring_orientation.clear(), "T10"),
        (
            "shared_edge",
            lambda a: a.edge_sources.__setitem__(
                0, (EdgeSource(SourceTag.for_ring(GEOM_A, 5, 0), True),)
            ),
            "T10",
        ),
        (
            "dangling_line",
            lambda a: a.edge_sources.__setitem__(
                5, (EdgeSource(SourceTag.for_ring(GEOM_B, 0, 0), True),)
            ),
            "T10",
        ),
        ("point_in_polygon", _set("vx", 4, 10), "G3"),  # isolated vertex left its face
        ("point_in_polygon", _set("vy", 4, 0), "G3"),  # now on the outer boundary
        ("point_in_polygon", _set("vy", 4, 0), "G4"),  # ... inside an edge
        ("corner_touch", _set("face_loc_a", 1, int(B)), "L1"),
        ("corner_touch", _set("edge_loc_b", 0, int(Location.NONE)), "L1"),
        ("corner_touch", _set("face_loc_a", 0, int(I)), "L1"),
        ("nested_squares", _set("edge_loc_a", 4, int(E)), "L2"),  # B edge inside A
        ("dangling_line", _set("edge_loc_b", 0, int(B)), "L2"),
        ("dangling_line", _set("edge_loc_b", 5, int(E)), "L2"),
    ],
)
def test_validate_catches(name, mutate, code):
    expect(broken(name, mutate), code)


def test_validate_catches_swapped_face_components():
    # swap the roles of the annulus's outer boundary and its island's outer cycle
    def mutate(arr):
        f = next(f for f in range(1, arr.num_faces) if arr.face_inner[f])
        outer, inner = arr.face_outer[f], arr.face_inner[f][0]
        arr.face_outer[f], arr.face_inner[f][0] = inner, outer

    expect(broken("nested_squares", mutate), "T8")


def test_validate_catches_mirrored_geometry():
    """Mirroring every vertex keeps the topology but reverses every orientation."""

    def mutate(arr):
        arr.vx[:] = [-x for x in arr.vx]

    arr = broken("overlapping_squares", mutate)
    arr.validate(geometry=False, labels=False)  # topology alone cannot see it
    expect(arr, "G1")  # counter-clockwise outer cycles became clockwise
    expect(arr, "G2")  # rotations at the degree-4 crossings became clockwise


def test_validate_catches_unsorted_rotation():
    """Swapping two leaves of the crossing makes its rotation a reflection."""

    def mutate(arr):
        arr.vx[0], arr.vy[0], arr.vx[2], arr.vy[2] = arr.vx[2], arr.vy[2], arr.vx[0], arr.vy[0]

    arr = broken("crossing_lines", mutate)
    arr.validate(geometry=False, labels=True)
    with pytest.raises(ArrangementError) as info:
        arr.validate(geometry=True, planarity=True, labels=True)
    assert [p[:2] for p in info.value.problems] == ["G2"]


def test_validate_catches_unsplit_edges():
    """A T-junction that was not noded: B's apex on A's edge interior."""
    spec = FixtureSpec(
        name="unsplit",
        description="",
        a="POLYGON ((0 0, 4 0, 4 2, 0 2, 0 0))",
        b="POLYGON ((2 2, 3 4, 1 4, 2 2))",
        relate="FF2F01212",
        vertices=[(0, 0), (4, 0), (4, 2), (0, 2), (2, 2), (3, 4), (1, 4)],
        vertex_labels=["BE", "BE", "BE", "BE", "BB", "EB", "EB"],
        edges=[
            (0, 1, [ring(GEOM_A)], "BE"),
            (1, 2, [ring(GEOM_A)], "BE"),
            (2, 3, [ring(GEOM_A)], "BE"),
            (3, 0, [ring(GEOM_A)], "BE"),
            (4, 5, [ring(GEOM_B)], "EB"),
            (5, 6, [ring(GEOM_B)], "EB"),
            (6, 4, [ring(GEOM_B)], "EB"),
        ],
        faces=[((1, 1), "IE"), ((2, 3), "EI"), ((10, 10), "EE")],
    )
    arr = build(spec)
    arr.validate(geometry=False, labels=True)
    expect(arr, "G4")


def test_validate_catches_crossing_edges():
    spec = FixtureSpec(
        name="uncrossed",
        description="",
        a="LINESTRING (0 0, 2 2)",
        b="LINESTRING (0 2, 2 0)",
        relate="0F1FF0102",
        vertices=[(0, 0), (2, 2), (0, 2), (2, 0)],
        vertex_labels=["BE", "BE", "EB", "EB"],
        edges=[(0, 1, [line(GEOM_A)], "IE"), (2, 3, [line(GEOM_B)], "EI")],
        faces=[((5, 5), "EE")],
    )
    expect(build(spec), "G4")


def test_dump_survives_corruption():
    arr = broken("corner_touch", _set("he_prev", 0, 0))  # rotation at v0 never returns
    arr.edge_loc_a[0] = 7
    text = arr.dump()
    assert "e0 v0->v1 ?E" in text


def test_error_message_lists_problems():
    arr = broken("two_disjoint_squares", _set("he_face", 0, 2))
    with pytest.raises(ArrangementError) as info:
        arr.validate()
    assert "invalid arrangement" in str(info.value) and info.value.problems
