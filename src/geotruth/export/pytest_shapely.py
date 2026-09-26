"""pytest functions (Shapely/GEOS) with the exact answers.

The export is a self-contained test module: a table of cases (WKT with shortest
round-trip doubles, exact matrix, predicates, validity and overlay areas as correctly
rounded doubles plus the exact rational in a comment) and four parametrized test
functions, one test id per (case, field): ``test_relate``, ``test_predicate``,
``test_validity`` and ``test_overlay_area`` (within ``rel``, default 1e-6, of the larger
operand area; no area checks where that is below 4 x the double-rounding floor).
Predicates that depend on the empty-geometry convention table are left out. It needs
only ``pytest`` and ``shapely``.
"""

from __future__ import annotations

from geotruth.export.common import (
    ExportCase,
    ExportFile,
    area_double,
    area_tolerance,
    header,
    wkt,
)

__all__ = ["export"]


def export(cases: list[ExportCase], *, rel: float = 1e-6, comment: str = "") -> list[ExportFile]:
    doc = header("pytest / Shapely", cases, comment)
    lines = ['"""' + doc[0], *doc[1:], "", "Run with: python -m pytest THIS_FILE", '"""', ""]
    lines += [
        "import pytest",
        "",
        'shapely = pytest.importorskip("shapely")',
        "",
        "# id, A (WKT), B (WKT), exact answers",
        "CASES = {",
    ]
    rel_rows, pred_rows, valid_rows, area_rows = [], [], [], []
    for c in cases:
        ans = c.answer
        lines.append(f"    {c.id!r}: ({wkt(c.a)!r}, {wkt(c.b)!r}),  # {c.describe()}")
        if ans.valid_a is not None:
            valid_rows.append((c.id, "a", ans.valid_a))
        if ans.valid_b is not None:
            valid_rows.append((c.id, "b", ans.valid_b))
        if not ans.valid:
            continue
        if ans.relate:
            rel_rows.append((c.id, ans.relate))
        for name, value in c.predicates().items():
            pred_rows.append((c.id, name, value))
        tol = area_tolerance(c, rel) if ans.areas is not None else None
        if tol is not None:
            for op in ("intersection", "union", "difference", "symdifference"):
                q = ans.areas[op]
                area_rows.append((c.id, op, area_double(q), repr(tol), f"{q}"))
    lines += ["}", ""]
    lines.append("RELATE = [")
    lines += [f"    ({i!r}, {m!r})," for i, m in rel_rows]
    lines += ["]", "", "PREDICATES = ["]
    lines += [f"    ({i!r}, {n!r}, {v!r})," for i, n, v in pred_rows]
    lines += ["]", "", "VALIDITY = ["]
    lines += [f"    ({i!r}, {o!r}, {v!r})," for i, o, v in valid_rows]
    lines += [
        "]",
        "",
        "# id, operation, exact area as the nearest double, absolute tolerance; exact",
    ]
    lines.append("AREAS = [")
    lines += [f"    ({i!r}, {op!r}, {a}, {s}),  # {q}" for i, op, a, s, q in area_rows]
    lines += [
        "]",
        "",
        "",
        "def _load(case_id):",
        "    a, b = CASES[case_id]",
        "    return shapely.from_wkt(a), shapely.from_wkt(b)",
        "",
        "",
        '@pytest.mark.parametrize(("case_id", "matrix"), RELATE, ids=[r[0] for r in RELATE])',
        "def test_relate(case_id, matrix):",
        "    a, b = _load(case_id)",
        "    assert shapely.relate(a, b) == matrix",
        "",
        "",
        "@pytest.mark.parametrize(",
        '    ("case_id", "name", "expected"),',
        "    PREDICATES,",
        '    ids=[f"{r[0]}:{r[1]}" for r in PREDICATES],',
        ")",
        "def test_predicate(case_id, name, expected):",
        "    a, b = _load(case_id)",
        "    assert bool(getattr(shapely, name)(a, b)) is expected",
        "",
        "",
        "@pytest.mark.parametrize(",
        '    ("case_id", "operand", "expected"),',
        "    VALIDITY,",
        '    ids=[f"{r[0]}:{r[1]}" for r in VALIDITY],',
        ")",
        "def test_validity(case_id, operand, expected):",
        "    a, b = _load(case_id)",
        '    assert bool(shapely.is_valid(a if operand == "a" else b)) is expected',
        "",
        "",
        "@pytest.mark.parametrize(",
        '    ("case_id", "op", "expected", "tol"), AREAS, ids=[f"{r[0]}:{r[1]}" for r in AREAS]',
        ")",
        "def test_overlay_area(case_id, op, expected, tol):",
        "    a, b = _load(case_id)",
        '    fn = {"symdifference": "symmetric_difference"}.get(op, op)',
        "    got = getattr(shapely, fn)(a, b).area",
        "    assert abs(got - expected) <= tol",
    ]
    return [ExportFile("\n".join(lines) + "\n")]
