"""The scorer (DESIGN §4.3): grades adapter results against exact answers.

One ``score.v2`` record per (case, library, capability):

- **echo** (the parse-echo canary): the echoed operands must be the case's doubles, bit for
  bit (``-0.0`` keeps its sign).
- **relate**: the DE-9IM string, exactly.
- **predicates**: all reported named predicates of the case together, exactly (one record
  per case, so a library that derives several predicates from one call is not counted
  several times). A disagreement only on a field the expected answer decides by the
  empty-geometry convention table is ``convention``, not ``wrong``. A wrong predicate that
  the manifest declares derived from relate is marked ``derived`` when the case's relate is
  wrong too: it is the same fault, counted once (under relate).
- **validity**: ``valid_a`` and ``valid_b``, on the boolean (reasons are informational).
- **overlay.<op>**: graded into tiers against the exact result, with δ_lib from the
  target's manifest (:func:`geotruth.harness.manifest.delta_for`):

  1. ``exact``: the output's point set is the exact one (squared Hausdorff distance 0 and
     symmetric-difference area 0);
  2. ``rounding``: within the correctly rounded floor, δ² = ulp(M)²/2 (M the largest
     |input ordinate|): Hausdorff ≤ δ and ``|E xor L| <= 2δ(P_E + P_L) + πδ²n``;
  3. ``budget``: the same two conditions with the library's δ_lib;
  4. ``gross``: beyond;
  5. ``topological``: invalid output (its point set measured by even-odd), or a missing or
     extra component or hole;
  6. ``exception``: an exception, crash, hang or memory failure.

  In tiers 2 and 3, exact components and holes that fit inside the δ-tube of their own
  boundary (:func:`geotruth.harness.metrics.is_thin`) may vanish or collapse: they are left
  out of the exact-to-library Hausdorff direction. The exact result is the non-strict one
  (OverlayNG's default, lines and points of boundary touches kept) when the output has
  lower-dimensional parts, and the regularized areal one otherwise, so polygon-only
  clippers are judged on what they promise. Verdicts: tiers 1-3 ``correct``, 4-5
  ``wrong``, 6 ``error``; the headline counts tiers 4-6.

Engine abstentions (``engine_skipped`` / ``engine_error``) are never counted against a
library. Capabilities undefined for the case (relate, predicates and overlay of invalid
input) get no record.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from geotruth.geom import Geometry, LineString, Point, Polygon
from geotruth.harness import metrics as M
from geotruth.harness.manifest import Delta, Target, delta_for
from geotruth.io import Case, GeometryFormatError, geometry_from_json
from geotruth.numbers import format_rational

__all__ = [
    "CAPABILITIES",
    "HEADLINE_TIERS",
    "OverlayGrade",
    "ScoreContext",
    "grade_overlay",
    "score_case",
    "summarize",
    "summary_table",
]

OVERLAY_OPS = ("intersection", "union", "difference", "symdifference")
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
CAPABILITIES = (
    "echo",
    "relate",
    "predicates",
    "validity",
    *(f"overlay.{op}" for op in OVERLAY_OPS),
)
TIERS = ("exact", "rounding", "budget", "gross", "topological", "exception")
HEADLINE_TIERS = ("gross", "topological", "exception")
ENTRY_NAMES = ("II", "IB", "IE", "BI", "BB", "BE", "EI", "EB", "EE")


@dataclass
class ScoreContext:
    """What the scorer knows besides the case: the target (manifest) and versions."""

    target: Target | None = None
    lib_id: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    #: grade the overlay capability (it is the expensive part)
    overlay: bool = True


# ============================================================================ helpers


def _err_kind(e: Any) -> str:
    if isinstance(e, dict):
        return str(e.get("kind", "exception"))
    return "exception"


def _err_text(e: Any) -> str:
    if isinstance(e, dict):
        return f"{e.get('kind', 'exception')}: {e.get('message', '')}"
    return str(e)


def _is_value(v: Any) -> bool:
    return v is not None and v != "unsupported"


def _same_double(x: Any, y: Any) -> bool:
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        return False
    if math.isnan(fx) or math.isnan(fy):
        return math.isnan(fx) and math.isnan(fy)
    return fx == fy and math.copysign(1.0, fx) == math.copysign(1.0, fy)


def _same_geometry(g: Geometry, h: Geometry) -> bool:
    """Same type tree and bit-identical doubles (the parse-echo comparison)."""
    if type(g) is not type(h):
        return False
    if isinstance(g, Point):
        assert isinstance(h, Point)
        if (g.coord is None) != (h.coord is None):
            return False
        return g.coord is None or all(
            _same_double(a, b) for a, b in zip(g.coord, h.coord, strict=True)
        )
    if isinstance(g, LineString):
        assert isinstance(h, LineString)
        return len(g.coords) == len(h.coords) and all(
            _same_double(a[0], b[0]) and _same_double(a[1], b[1])
            for a, b in zip(g.coords, h.coords, strict=True)
        )
    if isinstance(g, Polygon):
        assert isinstance(h, Polygon)
        return len(g.rings) == len(h.rings) and all(
            _same_geometry(LineString(r), LineString(s))
            for r, s in zip(g.rings, h.rings, strict=True)
        )
    kids_g, kids_h = g.children(), h.children()
    return len(kids_g) == len(kids_h) and all(
        _same_geometry(a, b) for a, b in zip(kids_g, kids_h, strict=True)
    )


def _record(
    case_id: str,
    lib: str,
    cap: str,
    verdict: str,
    ctx: ScoreContext,
    case: Case | None,
    **extra: Any,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"id": case_id, "lib": lib}
    if case is not None and case.family:
        rec["family"] = case.family
    rec["capability"] = cap
    rec["verdict"] = verdict
    rec.update({k: v for k, v in extra.items() if v is not None})
    if case is not None and case.tags:
        rec["tags"] = dict(case.tags)
    if ctx.versions:
        rec["versions"] = dict(ctx.versions)
    return rec


def _cluster(ctx: ScoreContext, case: Case | None, signature: str) -> str:
    fam = case.family if case is not None and case.family else "-"
    tol = "|tolerance" if ctx.target is not None and ctx.target.tolerance_predicates else ""
    return f"{ctx.lib_id or '-'}|{fam}|{signature}" + (tol if signature.startswith("pred") else "")


# ============================================================================ capabilities


def _score_echo(result: dict, case: Case, ctx: ScoreContext, case_json: dict | None) -> dict | None:
    errors = result.get("errors") or {}
    wanted = case.ops is not None and "echo" in case.ops
    if "echo" not in result and "echo" not in errors and not wanted:
        return None
    lib, cid = result.get("lib", ""), case.id
    if "*" in errors or "echo" in errors:
        e = errors.get("echo", errors.get("*"))
        return _record(cid, lib, "echo", "error", ctx, case, got=_err_text(e))
    echo = result.get("echo")
    if echo == "unsupported":
        return _record(cid, lib, "echo", "unsupported", ctx, case)
    if not isinstance(echo, dict):
        return _record(cid, lib, "echo", "not_reported", ctx, case)
    bad = []
    for k, want in (("a", case.a), ("b", case.b)):
        try:
            got = geometry_from_json(echo.get(k))
        except (GeometryFormatError, TypeError, ValueError):
            bad.append(f"echo.{k}")
            continue
        if not _same_geometry(want, got):
            bad.append(f"echo.{k}")
    if not bad:
        return _record(cid, lib, "echo", "correct", ctx, case)
    return _record(
        cid, lib, "echo", "wrong", ctx, case, fields=bad, cluster=_cluster(ctx, case, "echo")
    )


def _engine_verdict(expected: dict | None) -> str | None:
    if expected is None:
        return "engine_skipped"
    st = expected.get("status", "ok")
    return None if st == "ok" else st


def _defined(expected: dict | None) -> bool:
    """Relate, predicates and overlay are defined only for valid operands."""
    if expected is None or expected.get("status", "ok") != "ok":
        return True  # the abstention is reported
    v = expected.get("validity") or {}
    return all((v.get(k) or {}).get("valid", True) for k in ("a", "b"))


def _score_relate(
    result: dict, expected: dict | None, case: Case, ctx: ScoreContext
) -> dict | None:
    if "relate" not in result:
        return None
    if not _defined(expected):
        return None
    lib, cid = result.get("lib", ""), case.id
    ev = _engine_verdict(expected)
    if ev:
        return _record(cid, lib, "relate", ev, ctx, case)
    assert expected is not None
    errors = result.get("errors") or {}
    got = result.get("relate")
    if got == "unsupported":
        return _record(cid, lib, "relate", "unsupported", ctx, case)
    if got is None:
        e = errors.get("relate", errors.get("*"))
        if e is not None:
            return _record(cid, lib, "relate", "error", ctx, case, got=_err_text(e))
        return _record(cid, lib, "relate", "not_reported", ctx, case)
    want = expected.get("relate")
    if want is None:
        return _record(cid, lib, "relate", "engine_skipped", ctx, case)
    if got == want:
        return _record(cid, lib, "relate", "correct", ctx, case)
    diff = [ENTRY_NAMES[i] for i in range(9) if i >= len(got) or got[i] != want[i]]
    verdict = "convention" if "relate" in (expected.get("conventions") or []) else "wrong"
    return _record(
        cid,
        lib,
        "relate",
        verdict,
        ctx,
        case,
        fields=["relate"],
        expected=want,
        got=got,
        cluster=_cluster(ctx, case, "relate:" + ",".join(diff)),
    )


def _derived_from_relate(ctx: ScoreContext, path: str) -> bool:
    if ctx.target is None:
        return False
    how = ctx.target.derived_fields().get(path)
    return how is not None and "relate" in how.lower()


def _score_predicates(
    result: dict, expected: dict | None, case: Case, ctx: ScoreContext, relate_verdict: str | None
) -> dict | None:
    preds = result.get("predicates")
    if preds is None and not any(k.startswith("predicates.") for k in result.get("errors") or {}):
        return None
    if not _defined(expected):
        return None
    lib, cid = result.get("lib", ""), case.id
    ev = _engine_verdict(expected)
    if ev:
        return _record(cid, lib, "predicates", ev, ctx, case)
    assert expected is not None
    want = expected.get("predicates") or {}
    conv = set(expected.get("conventions") or [])
    errors = result.get("errors") or {}
    preds = preds if isinstance(preds, dict) else {}
    wrong, convention, errored, graded, unsupported = [], [], [], 0, 0
    for name in PREDICATES:
        if name not in want:
            continue
        path = f"predicates.{name}"
        got = preds.get(name)
        if got == "unsupported":
            unsupported += 1
            continue
        if not isinstance(got, bool):
            if path in errors or "*" in errors:
                errored.append(path)
            continue
        graded += 1
        if got != want[name]:
            (convention if path in conv else wrong).append(path)
    exp_sub = {p.split(".", 1)[1]: want[p.split(".", 1)[1]] for p in wrong + convention}
    got_sub = {p.split(".", 1)[1]: preds.get(p.split(".", 1)[1]) for p in wrong + convention}
    if wrong:
        derived = relate_verdict == "wrong" and all(_derived_from_relate(ctx, p) for p in wrong)
        sig = "predicates:" + ",".join(p.split(".", 1)[1] for p in wrong)
        return _record(
            cid,
            lib,
            "predicates",
            "wrong",
            ctx,
            case,
            fields=wrong + convention,
            derived=derived,
            expected=exp_sub,
            got=got_sub,
            cluster=_cluster(ctx, case, sig),
        )
    if errored:
        msgs = {p: _err_text(errors.get(p, errors.get("*"))) for p in errored}
        return _record(cid, lib, "predicates", "error", ctx, case, fields=errored, got=msgs)
    if convention:
        return _record(
            cid,
            lib,
            "predicates",
            "convention",
            ctx,
            case,
            fields=convention,
            expected=exp_sub,
            got=got_sub,
        )
    if graded:
        return _record(cid, lib, "predicates", "correct", ctx, case)
    if unsupported:
        return _record(cid, lib, "predicates", "unsupported", ctx, case)
    return _record(cid, lib, "predicates", "not_reported", ctx, case)


def _score_validity(
    result: dict, expected: dict | None, case: Case, ctx: ScoreContext
) -> dict | None:
    if "valid_a" not in result and "valid_b" not in result:
        return None
    lib, cid = result.get("lib", ""), case.id
    exp_v = (expected or {}).get("validity")
    if not exp_v:
        return _record(
            cid, lib, "validity", _engine_verdict(expected) or "engine_skipped", ctx, case
        )
    errors = result.get("errors") or {}
    wrong, errored, graded, unsupported = [], [], 0, 0
    got_all, want_all = {}, {}
    for k in ("a", "b"):
        got = result.get(f"valid_{k}")
        want = exp_v[k]["valid"]
        if got == "unsupported":
            unsupported += 1
            continue
        if not isinstance(got, bool):
            if f"valid_{k}" in errors or "*" in errors:
                errored.append(f"valid_{k}")
            continue
        graded += 1
        got_all[k], want_all[k] = got, want
        if got != want:
            wrong.append(f"valid_{k}")
    if wrong:
        sig = "validity:" + ",".join(f"{w}={str(got_all[w[-1]]).lower()}" for w in wrong)
        return _record(
            cid,
            lib,
            "validity",
            "wrong",
            ctx,
            case,
            fields=wrong,
            expected=want_all,
            got=got_all,
            cluster=_cluster(ctx, case, sig),
        )
    if errored:
        msgs = {p: _err_text(errors.get(p, errors.get("*"))) for p in errored}
        return _record(cid, lib, "validity", "error", ctx, case, fields=errored, got=msgs)
    if graded:
        return _record(cid, lib, "validity", "correct", ctx, case)
    if unsupported:
        return _record(cid, lib, "validity", "unsupported", ctx, case)
    return _record(cid, lib, "validity", "not_reported", ctx, case)


# ============================================================================ overlay


@dataclass
class OverlayGrade:
    """The grade of one overlay output: its tier and metrics."""

    tier: str
    metrics: dict[str, Any]
    variant: str


def _fmt_surd(s: M.Surd | None, out: dict[str, Any], key: str) -> None:
    if s is None:
        out[f"{key}_infinite"] = True
    elif s.is_rational:
        out[key] = format_rational(s.a)
    else:
        out[f"{key}_surd"] = s.to_json()
        out[f"{key}_approx"] = float(s)


def _has_lower_dim(g: Geometry) -> bool:
    return any(not isinstance(e, Polygon) for e in g.elements() if not e.is_empty)


def grade_overlay(
    expected_op: dict[str, Any], lib_json: Any, case: Case, delta: Delta
) -> OverlayGrade:
    """Grade one library overlay output (typed JSON with doubles) against the exact
    result (``expected.v2`` ``OverlayOp``: ``non_strict`` and ``areal``)."""
    from geotruth.validity import validate

    lib_geom = geometry_from_json(lib_json)
    variant = "non_strict" if _has_lower_dim(lib_geom) else "areal"
    exact = geometry_from_json(expected_op[variant]["exact"], exact=True)
    met: dict[str, Any] = {"variant": variant}
    report = validate(lib_geom)
    met["output_valid"] = report.valid
    if not report.valid and report.first_reason:
        met["output_reason"] = report.first_reason
    if lib_geom.has_nonfinite:
        met["nonfinite_output"] = True
        return OverlayGrade("topological", met, variant)
    se, sl = M.shape_of(exact), M.shape_of(lib_geom)
    area_e = M.even_odd_area(se.rings())
    area_l = M.even_odd_area(sl.rings())
    symdiff = M.even_odd_area(se.rings() + sl.rings())
    h2, h_el0, h_le0 = M.hausdorff2(se, sl)
    met["symdiff_area"] = format_rational(symdiff)
    _fmt_surd(h2, met, "hausdorff2")
    if h2 is not None and h2 == 0 and symdiff == 0:
        return OverlayGrade("exact" if report.valid else "topological", met, variant)

    m = M.max_abs_ordinate(case.a, case.b)
    dr2 = M.rounding_delta2(m)
    met["delta_rounding"] = float(M.sqrt_upper(dr2))
    if delta.delta2 is not None:
        met["delta"] = delta.delta
    met["delta_kind"] = delta.kind
    if delta.note:
        met["delta_note"] = delta.note
    pe, he = M.components(se)
    pl, hl = M.components(sl)
    perim = M.perimeter_upper(se.rings(), se.lines) + M.perimeter_upper(sl.rings(), sl.lines)
    n = se.num_vertices + sl.num_vertices

    def thin_exact(d2: Any) -> set[tuple]:
        out: set[tuple] = set()
        for c in pe + he:
            if M.is_thin(c.area, c.perimeter_up, c.n_vertices, d2):
                out |= c.excuse
        return out

    def within(d2: Any) -> tuple[bool, int]:
        budget = M.tube_bound(d2, perim, n)
        if symdiff > budget:
            return False, 0
        thin = thin_exact(d2)
        excused = sum(1 for c in pe + he if c.excuse <= thin)
        if h2 is not None and h2 <= d2:
            return True, 0
        _, h_el, h_le = M.hausdorff2(se, sl, excuse=thin) if thin else (h2, h_el0, h_le0)
        if h_le is None or not h_le <= d2:
            return False, excused
        if h_el is not None and h_el <= d2:
            return True, excused
        # boundaries of exact rings within 2 delta of another exact ring may collapse
        fe = M.features_of(se)
        if thin:
            fe = M.excuse_features(fe, thin)
        h_c = M.directed_hausdorff2_collapse(fe, M.features_of(sl), d2, 4 * M.q(d2))
        return h_c is not None and h_c <= d2, excused

    # topological: a missing or extra component or hole (thin ones excused)
    dt2 = delta.delta2 if delta.delta2 is not None else dr2
    thin_t = thin_exact(dt2)
    missing = [
        c
        for c in pe
        if c.key not in thin_t and M.overlap_area(c.rings, c.area, sl.rings(), area_l) == 0
    ]
    extra = [
        c
        for c in pl
        if c.area > 0
        and not M.is_thin(c.area, c.perimeter_up, c.n_vertices, dt2)
        and M.overlap_area(c.rings, c.area, se.rings(), area_e) == 0
    ]
    missing_h = [
        c
        for c in he
        if c.key not in thin_t and M.overlap_area(c.rings, c.area, sl.rings(), area_l) == c.area
    ]
    extra_h = [
        c
        for c in hl
        if c.area > 0
        and not M.is_thin(c.area, c.perimeter_up, c.n_vertices, dt2)
        and M.overlap_area(c.rings, c.area, se.rings(), area_e) == c.area
    ]
    for key, lst in (
        ("missing_components", missing),
        ("extra_components", extra),
        ("missing_holes", missing_h),
        ("extra_holes", extra_h),
    ):
        if lst:
            met[key] = len(lst)
    if not report.valid or missing or extra or missing_h or extra_h:
        return OverlayGrade("topological", met, variant)
    ok, excused = within(dr2)
    if ok:
        met["area_budget"] = float(M.tube_bound(dr2, perim, n))
        if excused:
            met["excused_thin"] = excused
        return OverlayGrade("rounding", met, variant)
    if delta.delta2 is not None:
        budget = M.tube_bound(delta.delta2, perim, n)
        met["area_budget"] = float(budget)
        ok, excused = within(delta.delta2)
        if ok:
            if excused:
                met["excused_thin"] = excused
            return OverlayGrade("budget", met, variant)
    return OverlayGrade("gross", met, variant)


def _score_overlay(
    result: dict, expected: dict | None, case: Case, ctx: ScoreContext, op: str
) -> dict | None:
    ovl = result.get("overlay")
    path = f"overlay.{op}"
    errors = result.get("errors") or {}
    if not isinstance(ovl, dict) or op not in ovl:
        if path not in errors:
            return None
        ovl = ovl if isinstance(ovl, dict) else {}
    if not _defined(expected):
        return None
    lib, cid = result.get("lib", ""), case.id
    ev = _engine_verdict(expected)
    if ev:
        return _record(cid, lib, path, ev, ctx, case)
    assert expected is not None
    got = ovl.get(op)
    if got == "unsupported":
        return _record(cid, lib, path, "unsupported", ctx, case)
    if got is None:
        e = errors.get(path, errors.get("*"))
        if e is not None:
            return _record(
                cid,
                lib,
                path,
                "error",
                ctx,
                case,
                tier="exception",
                metrics={"error_kind": _err_kind(e)},
                got=_err_text(e),
                cluster=_cluster(ctx, case, f"{path}:exception"),
            )
        return _record(cid, lib, path, "not_reported", ctx, case)
    exp_op = (expected.get("overlay") or {}).get(op)
    if exp_op is None:
        return _record(cid, lib, path, "engine_skipped", ctx, case)
    m = M.max_abs_ordinate(case.a, case.b)
    values = [float(v) for g in (case.a, case.b) for v in g.iter_values()]
    delta = (
        delta_for(ctx.target, m, values)
        if ctx.target is not None
        else Delta("undocumented", None, None, "no manifest")
    )
    try:
        grade = grade_overlay(exp_op, got, case, delta)
    except (GeometryFormatError, TypeError, ValueError) as exc:
        return _record(
            cid,
            lib,
            path,
            "wrong",
            ctx,
            case,
            tier="topological",
            metrics={"output_valid": False, "unreadable": str(exc)[:300]},
            cluster=_cluster(ctx, case, f"{path}:topological"),
        )
    verdict = "correct" if grade.tier in ("exact", "rounding", "budget") else "wrong"
    rec = _record(cid, lib, path, verdict, ctx, case, tier=grade.tier, metrics=grade.metrics)
    if verdict == "wrong":
        rec["fields"] = [path]
        rec["cluster"] = _cluster(ctx, case, f"{path}:{grade.tier}")
    return rec


# ============================================================================ a case


def score_case(
    case: Case, expected: dict | None, result: dict, ctx: ScoreContext
) -> list[dict[str, Any]]:
    """Every ``score.v2`` record of one case."""
    out: list[dict[str, Any]] = []
    r = _score_echo(result, case, ctx, None)
    if r:
        out.append(r)
    rel = _score_relate(result, expected, case, ctx)
    if rel:
        out.append(rel)
    pr = _score_predicates(result, expected, case, ctx, rel["verdict"] if rel else None)
    if pr:
        out.append(pr)
    va = _score_validity(result, expected, case, ctx)
    if va:
        out.append(va)
    if ctx.overlay:
        for op in OVERLAY_OPS:
            o = _score_overlay(result, expected, case, ctx, op)
            if o:
                out.append(o)
    return out


# ============================================================================ summary


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts per capability and verdict, overlay tiers, headline failures, conventions
    and the failure clusters."""
    verdicts: dict[str, Counter] = defaultdict(Counter)
    tiers: dict[str, Counter] = defaultdict(Counter)
    clusters: Counter = Counter()
    derived = Counter()
    cases = set()
    headline = 0
    lib = None
    for rec in records:
        lib = lib or rec.get("lib")
        cap = rec["capability"]
        cases.add(rec["id"])
        verdicts[cap][rec["verdict"]] += 1
        if "tier" in rec:
            tiers[cap][rec["tier"]] += 1
        if rec.get("derived"):
            derived[cap] += 1
        counted = rec["verdict"] in ("wrong", "error") and not rec.get("derived")
        if counted:
            headline += 1
            if rec.get("cluster"):
                clusters[rec["cluster"]] += 1
    return {
        "lib": lib,
        "cases": len(cases),
        "verdicts": {k: dict(v) for k, v in sorted(verdicts.items())},
        "overlay_tiers": {k: dict(v) for k, v in sorted(tiers.items())},
        "derived": dict(derived),
        "headline_failures": headline,
        "clusters": dict(clusters.most_common()),
    }


def summary_table(summary: dict[str, Any]) -> str:
    """A plain-text table of a :func:`summarize` result."""
    lines = [
        f"library {summary.get('lib')}: {summary['cases']} cases, "
        f"{summary['headline_failures']} headline failures "
        f"(wrong or error, derived counted once; overlay tiers {', '.join(HEADLINE_TIERS)})",
        "",
    ]
    cols = (
        "correct",
        "wrong",
        "error",
        "convention",
        "unsupported",
        "not_reported",
        "engine_skipped",
        "engine_error",
    )
    head = f"{'capability':24s}" + "".join(f"{c:>15s}" for c in cols)
    lines += [head, "-" * len(head)]
    for cap in CAPABILITIES:
        v = summary["verdicts"].get(cap)
        if not v:
            continue
        row = f"{cap:24s}" + "".join(f"{v.get(c, 0):>15d}" for c in cols)
        d = summary["derived"].get(cap)
        if d:
            row += f"   ({d} wrong derived from relate)"
        lines.append(row)
    if summary["overlay_tiers"]:
        lines += ["", f"{'overlay tiers':24s}" + "".join(f"{t:>13s}" for t in TIERS)]
        for cap, t in summary["overlay_tiers"].items():
            lines.append(f"{cap:24s}" + "".join(f"{t.get(x, 0):>13d}" for x in TIERS))
    if summary["clusters"]:
        lines += ["", "failure clusters (library|family|signature: records):"]
        for k, n in list(summary["clusters"].items())[:40]:
            lines.append(f"  {k}: {n}")
        if len(summary["clusters"]) > 40:
            lines.append(f"  ... {len(summary['clusters']) - 40} more")
    return "\n".join(lines) + "\n"


# ============================================================================ files


def _score_chunk(args: tuple[ScoreContext, list[tuple[str, Any, Any]]]) -> list[dict[str, Any]]:
    from geotruth.io import case_from_json
    from geotruth.numbers import json_loads

    ctx, items = args
    out: list[dict[str, Any]] = []
    for case_line, expected, result in items:
        case = case_from_json(json_loads(case_line))
        try:
            out += score_case(case, expected, result, ctx)
        except Exception as exc:  # a scorer failure must be visible, never silent
            out.append(
                _record(
                    case.id,
                    result.get("lib", ""),
                    "relate",
                    "engine_error",
                    ctx,
                    case,
                    got=f"scorer failed: {type(exc).__name__}: {exc}"[:500],
                )
            )
    return out


def score_results(
    cases: list[tuple[str, str]],
    expected: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    ctx: ScoreContext,
    *,
    jobs: int = 1,
) -> list[dict[str, Any]]:
    """Score records for every case that has a result, in case order.

    ``cases``: ``(id, v2 JSON line)``; ``expected`` and ``results``: records by id.
    """
    items = [(line, expected.get(cid), results[cid]) for cid, line in cases if cid in results]
    if jobs <= 1 or len(items) < 16:
        return _score_chunk((ctx, items))
    from concurrent.futures import ProcessPoolExecutor

    size = max(4, len(items) // (jobs * 8))
    chunks = [(ctx, items[i : i + size]) for i in range(0, len(items), size)]
    out: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for part in ex.map(_score_chunk, chunks):
            out += part
    return out
