"""Unit tests for geotruth.io: WKT, typed JSON, the rational side-car, canonical order."""

from __future__ import annotations

import json
import math
import random
import struct
from fractions import Fraction

import pytest

from geotruth import numbers as N
from geotruth.geom import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import (
    Case,
    GeometryFormatError,
    WKTError,
    canonical_line,
    canonical_ring,
    canonicalize,
    case_from_json,
    case_sha256,
    case_to_json,
    dumps_canonical,
    format_double,
    geometry_from_json,
    geometry_to_json,
    read_cases,
    read_wkt,
    to_wkt,
    write_jsonl,
)

TWO53 = 2**53


def bits(x: float) -> int:
    return struct.unpack("<q", struct.pack("<d", x))[0]


def same_doubles(g1, g2) -> bool:
    """Structural equality with bit-exact ordinates (distinguishes -0.0, NaN-safe)."""
    if type(g1) is not type(g2):
        return False
    c1, c2 = list(g1.iter_coords()), list(g2.iter_coords())
    return len(c1) == len(c2) and all(
        bits(float(a)) == bits(float(b))
        for p, q in zip(c1, c2, strict=True)
        for a, b in zip(p, q, strict=True)
    )


# ============================================================================== doubles


@pytest.mark.parametrize(
    ("x", "text", "trimmed"),
    [
        (1.0, "1.0", "1"),
        (-0.0, "-0.0", "-0"),
        (0.1, "0.1", "0.1"),
        (0.30000000000000004, "0.30000000000000004", "0.30000000000000004"),
        (1e16, "1e+16", "1e+16"),
        (5e-324, "5e-324", "5e-324"),
        (1.7976931348623157e308, "1.7976931348623157e+308", "1.7976931348623157e+308"),
        (math.nan, "NaN", "NaN"),
        (math.inf, "Inf", "Inf"),
        (-math.inf, "-Inf", "-Inf"),
    ],
)
def test_format_double(x, text, trimmed):
    assert format_double(x) == text
    assert format_double(x, trim=True) == trimmed


def test_format_double_round_trips():
    rng = random.Random(30)
    for _ in range(5000):
        (x,) = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))
        if math.isnan(x):
            continue
        for trim in (False, True):
            assert bits(float(format_double(x, trim=trim))) == bits(x)


# ================================================================================= WKT

WKT_ROUND_TRIP = [
    "POINT EMPTY",
    "POINT (1 2)",
    "POINT (-0 0.30000000000000004)",
    "LINESTRING EMPTY",
    "LINESTRING (0 0, 1 1, 2 0)",
    "POLYGON EMPTY",
    "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 2, 2 2, 1 1))",
    "MULTIPOINT EMPTY",
    "MULTIPOINT ((0 0), EMPTY, (1 1))",
    "MULTILINESTRING EMPTY",
    "MULTILINESTRING ((0 0, 1 1), EMPTY)",
    "MULTIPOLYGON EMPTY",
    "MULTIPOLYGON (((0 0, 1 0, 0 1, 0 0)), EMPTY)",
    "GEOMETRYCOLLECTION EMPTY",
    "GEOMETRYCOLLECTION (POINT (1 2), GEOMETRYCOLLECTION (LINESTRING (0 0, 1 1)), POLYGON EMPTY)",
    "POINT (NaN Inf)",
    "POINT (5e-324 1.7976931348623157e+308)",
]


@pytest.mark.parametrize("wkt", WKT_ROUND_TRIP)
def test_wkt_round_trip_text(wkt):
    assert to_wkt(read_wkt(wkt)) == wkt


@pytest.mark.parametrize(
    ("variant", "canonical"),
    [
        ("point(1 2)", "POINT (1 2)"),
        ("  Point  ( 1   2 ) ", "POINT (1 2)"),
        ("POINT Z (1 2 3)", "POINT (1 2)"),
        ("POINTZ(1 2 3)", "POINT (1 2)"),
        ("POINT M (1 2 3)", "POINT (1 2)"),
        ("POINT ZM (1 2 3 4)", "POINT (1 2)"),
        ("POINT (1 2 3 4)", "POINT (1 2)"),
        ("SRID=4326;POINT(1 2)", "POINT (1 2)"),
        ("POINT (+1.5e0 .5)", "POINT (1.5 0.5)"),
        ("POINT (1. -2E-1)", "POINT (1 -0.2)"),
        ("MULTIPOINT (1 2, 3 4)", "MULTIPOINT ((1 2), (3 4))"),
        ("MULTIPOINT ((1 2), 3 4)", "MULTIPOINT ((1 2), (3 4))"),
        ("MULTIPOINT Z ((1 2 9))", "MULTIPOINT ((1 2))"),
        ("LINEARRING (0 0, 1 0, 1 1, 0 0)", "LINESTRING (0 0, 1 0, 1 1, 0 0)"),
        ("POINT EMPTY", "POINT EMPTY"),
        ("point empty", "POINT EMPTY"),
        ("POINT Z EMPTY", "POINT EMPTY"),
        ("POINT (nan -infinity)", "POINT (NaN -Inf)"),
        ("POLYGON (EMPTY)", "POLYGON (EMPTY)"),
        (
            "GEOMETRYCOLLECTION(POINT(1 2),POINT EMPTY)",
            "GEOMETRYCOLLECTION (POINT (1 2), POINT EMPTY)",
        ),
    ],
)
def test_wkt_variants(variant, canonical):
    assert to_wkt(read_wkt(variant)) == canonical


def test_wkt_numbers_have_float_semantics():
    p = read_wkt("POINT (9007199254740993 0.1)")
    assert p.coord == (float(TWO53), 0.1)
    assert read_wkt("POINT (1e400 -1e400)").coord == (math.inf, -math.inf)
    assert read_wkt("POINT (1e-400 2)").coord == (0.0, 2.0)
    assert math.copysign(1, read_wkt("POINT (-0 0)").coord[0]) == -1


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "POINT",
        "POINT (1)",
        "POINT (1 2",
        "POINT (1 2))",
        "POINT (1 2 3 4 5)",
        "CIRCLE (1 2)",
        "POINT (a b)",
        "LINESTRING (0 0,)",
        "POLYGON ((0 0, 1 1)",
        "POINT (1 2) POINT (3 4)",
        "GEOMETRYCOLLECTION ()",
        "POINT (1 2) x",
        "POINT (1 # 2)",
        "SRID=x;POINT (1 2)",
        "MULTIPOINT ()",
        "POINT (1,2)",
    ],
)
def test_wkt_errors(bad):
    with pytest.raises(WKTError):
        read_wkt(bad)


def random_geometry(rng: random.Random, depth: int = 0):
    def num():
        r = rng.random()
        if r < 0.2:
            return rng.choice(
                [0.0, -0.0, 5e-324, 1.7976931348623157e308, 0.1, 1 / 3, -2.5e-310, float(TWO53)]
            )
        if r < 0.5:
            (x,) = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))
            return x if math.isfinite(x) else 1.0
        return rng.uniform(-1e6, 1e6)

    def coords(k):
        return tuple((num(), num()) for _ in range(k))

    def ring(k):
        c = coords(k - 1)
        return (*c, c[0])

    kind = rng.randrange(7 if depth < 2 else 6)
    if kind == 0:
        return Point(None if rng.random() < 0.2 else coords(1)[0])
    if kind == 1:
        return LineString(() if rng.random() < 0.2 else coords(rng.randint(2, 5)))
    if kind == 2:
        return Polygon(tuple(ring(rng.randint(4, 6)) for _ in range(rng.randint(0, 3))))
    if kind == 3:
        return MultiPoint(
            tuple(
                Point(None if rng.random() < 0.2 else coords(1)[0])
                for _ in range(rng.randint(0, 3))
            )
        )
    if kind == 4:
        return MultiLineString(
            tuple(LineString(coords(rng.randint(2, 4))) for _ in range(rng.randint(0, 3)))
        )
    if kind == 5:
        return MultiPolygon(tuple(Polygon((ring(4),)) for _ in range(rng.randint(0, 3))))
    return GeometryCollection(
        tuple(random_geometry(rng, depth + 1) for _ in range(rng.randint(0, 3)))
    )


def test_wkt_round_trip_random_geometries_bit_exact():
    rng = random.Random(31)
    for _ in range(1500):
        g = random_geometry(rng)
        for trim in (True, False):
            back = read_wkt(to_wkt(g, trim=trim))
            assert same_doubles(back, g), to_wkt(g)
            if not isinstance(g, Polygon) or g.rings:
                assert back == g or g.has_nonfinite


def test_wkt_writes_rationals_rounded():
    g = Point((Fraction(2, 3), Fraction(-1, 7)))
    assert to_wkt(g) == "POINT (0.6666666666666666 -0.14285714285714285)"
    if N.HAVE_GMPY2:
        import gmpy2

        assert to_wkt(Point((gmpy2.mpq(1, 3), 5))) == "POINT (0.3333333333333333 5)"


def test_wkt_against_shapely():
    shapely = pytest.importorskip("shapely")
    rng = random.Random(32)
    for _ in range(300):
        g = random_geometry(rng)
        if g.has_nonfinite:
            continue
        ours = to_wkt(g)
        theirs = shapely.from_wkt(ours)
        # GEOS reads our WKT to the same doubles (checked through its WKB-free
        # coordinate array, not through its WKT writer, which rounds)
        coords = shapely.get_coordinates(theirs)
        expected = list(g.iter_coords())
        assert len(coords) == len(expected)
        for (x, y), (ex, ey) in zip(coords, expected, strict=True):
            assert bits(float(x)) == bits(float(ex)) and bits(float(y)) == bits(float(ey))
    # and we read GEOS's own WKT of simple lattice geometries identically
    for wkt in [
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 2, 2 2, 1 1))",
        "MULTIPOINT ((0 0), (1 1))",
        "GEOMETRYCOLLECTION (POINT (1 2), LINESTRING (0 0, 3 4))",
        "MULTIPOLYGON (((0 0, 1 0, 0 1, 0 0)))",
    ]:
        assert to_wkt(read_wkt(shapely.from_wkt(wkt).wkt)) == wkt


# ========================================================================== typed JSON


def test_typed_json_round_trip():
    rng = random.Random(33)
    for _ in range(1000):
        g = random_geometry(rng)
        obj = json.loads(json.dumps(geometry_to_json(g)))
        back = geometry_from_json(obj)
        assert same_doubles(back, g)
        assert type(back) is type(g)


def test_typed_json_examples():
    assert geometry_to_json(Point()) == {"type": "Point", "coordinates": []}
    assert geometry_from_json({"type": "Point", "coordinates": []}) == Point()
    mp = geometry_from_json({"type": "MultiPoint", "coordinates": [[1, 2], []]})
    assert mp == MultiPoint([Point((1.0, 2.0)), Point()])
    gc = geometry_from_json(
        {
            "type": "GeometryCollection",
            "geometries": [{"type": "LineString", "coordinates": [[0, 0, 5], [1, 1, 6, 7]]}],
        }
    )
    assert gc == GeometryCollection([LineString([(0.0, 0.0), (1.0, 1.0)])])
    # JSON integers get float semantics
    p = geometry_from_json(N.json_loads('{"type": "Point", "coordinates": [9007199254740993, 1]}'))
    assert p.coord == (float(TWO53), 1.0) and isinstance(p.coord[0], float)


def test_legacy_multipolygon_coordinates():
    ring = [[0, 0], [1, 0], [1, 1], [0, 0]]
    assert isinstance(geometry_from_json([[ring]]), Polygon)
    mp = geometry_from_json([[ring], [ring]])
    assert isinstance(mp, MultiPolygon) and len(mp.polygons) == 2
    assert geometry_from_json([]) == MultiPolygon()


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "Point"},
        {"coordinates": [1, 2]},
        {"type": "Circle", "coordinates": []},
        {"type": "Point", "coordinates": [1]},
        {"type": "Point", "coordinates": ["1", "2"]},
        {"type": "Point", "coordinates": [True, 2]},
        {"type": "LineString", "coordinates": 5},
        {"type": "GeometryCollection"},
        "POINT (1 2)",
        5,
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], "x"]]},
    ],
)
def test_typed_json_errors(bad):
    with pytest.raises(GeometryFormatError):
        geometry_from_json(bad)


# ================================================================== rational side-car


def test_exact_side_car_round_trip():
    tri = Polygon(
        [
            [
                (Fraction(0), Fraction(0)),
                (Fraction(2, 3), Fraction(1, 3)),
                (Fraction(-1, 7), Fraction(5)),
                (Fraction(0), Fraction(0)),
            ]
        ]
    )
    obj = geometry_to_json(tri, exact=True)
    assert obj["coordinates"][0][1] == ["2/3", "1/3"]
    assert obj["coordinates"][0][2] == ["-1/7", "5"]
    for backend in ("fractions", "gmpy2") if N.HAVE_GMPY2 else ("fractions",):
        with N.use_backend(backend):
            back = geometry_from_json(json.loads(json.dumps(obj)), exact=True)
            assert back == tri
            assert isinstance(back.shell[1][0], N.rational_type())


def test_exact_side_car_of_doubles_is_exact():
    g = Point((0.1, -2.5))
    obj = geometry_to_json(g, exact=True)
    assert obj["coordinates"] == ["3602879701896397/36028797018963968", "-5/2"]
    back = geometry_from_json(obj, exact=True)
    assert Fraction(back.coord[0]) == Fraction(0.1)


def test_exact_reader_rejects_numbers():
    with pytest.raises(GeometryFormatError):
        geometry_from_json({"type": "Point", "coordinates": [1, 2]}, exact=True)
    with pytest.raises(GeometryFormatError):
        geometry_from_json({"type": "Point", "coordinates": ["1.5", "2"]}, exact=True)


def test_display_json_rounds_rationals():
    obj = geometry_to_json(Point((Fraction(1, 3), Fraction(2))))
    assert obj == {"type": "Point", "coordinates": [1 / 3, 2.0]}


# ==================================================================== canonical order


def as_exact(c):
    return (Fraction(c[0]), Fraction(c[1]))


def test_canonical_ring_orientation_and_start():
    cw = [(2, 2), (2, 0), (0, 0), (0, 2), (2, 2)]
    assert canonical_ring(cw) == ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0))
    assert canonical_ring(cw, ccw=False) == ((0, 0), (0, 2), (2, 2), (2, 0), (0, 0))
    # works on an open ring too, and keeps coordinate objects (floats stay floats)
    r = canonical_ring([(1.5, 0.0), (0.0, 0.0), (0.0, 1.0)])
    assert r == ((0.0, 0.0), (1.5, 0.0), (0.0, 1.0), (0.0, 0.0))
    assert all(isinstance(v, float) for c in r for v in c)
    assert canonical_ring([]) == ()


def test_canonical_ring_properties():
    rng = random.Random(34)
    for _ in range(500):
        n = rng.randint(3, 8)
        pts = [
            (Fraction(rng.randint(-5, 5), rng.randint(1, 3)), rng.randint(-5, 5) / 4)
            for _ in range(n)
        ]
        ring = [*pts, pts[0]]
        for ccw in (True, False):
            c = canonical_ring(ring, ccw=ccw)
            assert c[0] == c[-1]
            keys = [as_exact(p) for p in c[:-1]]
            assert keys[0] == min(keys)
            area = sum(
                keys[i - 1][0] * keys[i][1] - keys[i][0] * keys[i - 1][1] for i in range(len(keys))
            )
            if area != 0:
                assert (area > 0) == ccw
            # the same cyclic sequence up to direction
            orig = [as_exact(p) for p in pts]
            fwd = keys
            doubled = orig + orig
            rev = orig[::-1] + orig[::-1]
            k = len(orig)
            assert any(doubled[i : i + k] == fwd for i in range(k)) or any(
                rev[i : i + k] == fwd for i in range(k)
            )
            assert canonical_ring(c, ccw=ccw) == c  # idempotent


def test_canonical_line():
    assert canonical_line([(2, 0), (1, 1), (0, 0)]) == ((0, 0), (1, 1), (2, 0))
    assert canonical_line([(0, 0), (1, 1)]) == ((0, 0), (1, 1))
    closed = canonical_line([(1, 1), (0, 1), (0, 0), (1, 1)])
    assert closed[0] == (0, 0) and closed[0] == closed[-1]
    assert canonical_line([(3, 3)]) == ((3, 3),)


def test_canonicalize_geometries():
    mp = read_wkt(
        "MULTIPOLYGON (((5 5, 5 6, 6 6, 5 5)), "
        "((0 0, 0 4, 4 4, 4 0, 0 0), (3 1, 2 2, 3 2, 3 1), (1 1, 2 1, 2 2, 1 1)), "
        "EMPTY)"
    )
    c = canonicalize(mp)
    assert to_wkt(c) == (
        "MULTIPOLYGON (((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 2, 2 1, 1 1), "
        "(2 2, 3 2, 3 1, 2 2)), ((5 5, 6 6, 5 6, 5 5)))"
    )
    assert canonicalize(c) == c
    gc = read_wkt(
        "GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (3 3, 0 0), POINT EMPTY, "
        "POLYGON ((0 0, 0 1, 1 0, 0 0)), MULTIPOINT ((2 2), (1 1)))"
    )
    assert to_wkt(canonicalize(gc)) == (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), LINESTRING (0 0, 3 3), "
        "POINT (1 1), MULTIPOINT ((1 1), (2 2)))"
    )
    assert canonicalize(Point()) == Point()
    assert canonicalize(read_wkt("MULTILINESTRING ((1 1, 0 0), (0 0, 0 1))")) == read_wkt(
        "MULTILINESTRING ((0 0, 0 1), (0 0, 1 1))"
    )


def test_canonical_side_car_is_byte_identical():
    """Two different spellings of the same exact polygon give identical side-car text."""
    a = Polygon(
        [
            [
                (Fraction(0), Fraction(0)),
                (Fraction(0), Fraction(1)),
                (Fraction(2, 3), Fraction(0)),
                (Fraction(0), Fraction(0)),
            ]
        ]
    )
    b = Polygon(
        [
            [
                (Fraction(2, 3), Fraction(0)),
                (Fraction(0), Fraction(0)),
                (Fraction(0), Fraction(1)),
                (Fraction(2, 3), Fraction(0)),
            ]
        ]
    )
    ta = dumps_canonical(geometry_to_json(canonicalize(a), exact=True))
    tb = dumps_canonical(geometry_to_json(canonicalize(b), exact=True))
    assert ta == tb


# ============================================================================== cases


def test_case_round_trip_and_legacy(tmp_path):
    legacy = {
        "id": "f-1",
        "family": "f",
        "a": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
        "b": [[[[0, 0], [1, 0], [1, 1], [0, 0]]], [[[5, 5], [6, 5], [6, 6], [5, 5]]]],
        "note": "kept",
    }
    c = case_from_json(legacy)
    assert c.legacy and isinstance(c.a, Polygon) and isinstance(c.b, MultiPolygon)
    assert c.extra == {"note": "kept"}
    v2 = case_to_json(c)
    assert v2["a"]["type"] == "Polygon" and v2["note"] == "kept"
    c2 = case_from_json(v2)
    assert not c2.legacy and c2.a == c.a and c2.b == c.b
    path = tmp_path / "cases.jsonl"
    write_jsonl([legacy, v2], path)
    got = list(read_cases(path))
    assert [x.id for x in got] == ["f-1", "f-1"]
    assert case_sha256(got[0]) == case_sha256(got[1])


def test_case_hash_ignores_number_spelling():
    a = case_from_json(
        N.json_loads(
            '{"id": "x", "family": "f",'
            ' "a": {"type": "Point", "coordinates": [9007199254740993, 1]},'
            ' "b": {"type": "Point", "coordinates": [0, 0]}}'
        )
    )
    b = case_from_json(
        N.json_loads(
            '{"id": "x", "family": "f",'
            ' "a": {"type": "Point", "coordinates": [9007199254740992.0, 1.0]},'
            ' "b": {"type": "Point", "coordinates": [0.0, 0e5]}}'
        )
    )
    assert case_sha256(a) == case_sha256(b)
    c = Case(id="x", a=Point((1.0, 1.0)), b=Point((0.0, 0.0)), family="f")
    assert case_sha256(c) != case_sha256(a)


def test_case_errors_and_ops():
    with pytest.raises(GeometryFormatError):
        case_from_json({"id": "x", "a": {"type": "Point", "coordinates": []}})
    with pytest.raises(GeometryFormatError):
        case_from_json([1, 2])
    c = case_from_json(
        {
            "id": 7,
            "ops": ["echo"],
            "a": {"type": "Point", "coordinates": []},
            "b": {"type": "Point", "coordinates": []},
        }
    )
    assert c.id == "7" and c.ops == ("echo",)
    assert case_to_json(c)["ops"] == ["echo"]


def test_canary_case_parses_with_float_semantics(repo_root):
    path = repo_root / "schemas" / "examples" / "case.v2.valid.json"
    text = path.read_text()
    assert "9007199254740993" in text  # the literal really is written as an integer
    canary = case_from_json(N.json_loads(text)[0])
    xs = [c for p in canary.a.points for c in p.coord]
    assert xs[0] == float(TWO53)
    assert xs[1] == 5e-324
    assert math.copysign(1, xs[2]) == -1 and xs[2] == 0
    assert xs[3] == 0.30000000000000004
    assert xs[4] == 1.7976931348623157e308
