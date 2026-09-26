"""The failure examples of a cluster page: for one score record, the exact inputs, the
exact answer next to the library's, the figures zoomed to the discrepancy, an independent
re-check of the exact answer, and the commands that reproduce both answers.

The exact answer shown is the one the scorer graded against (the ``expected`` field of the
score record, or the scorer's cached ``expected.v2`` record for the case). It is re-checked
here by a second, independent route where one exists: the witness-point relate
(DESIGN §2.4) for relate and predicates, the overlay certificate (§2.6) for overlay, the
audited reference rules (``tests/reference/validity.py``) for polygon validity. A failed
re-check is shown on the page and counted in the build report; it is never hidden.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from gtsite import locus as L
from gtsite.aggregate import is_exact_but_invalid
from gtsite.exact2d import P, Parts, parts_of, sqrt_frac
from gtsite.html import (
    approx,
    code,
    coord_cell,
    esc,
    fmt_float,
    fmt_rational_str,
    fmt_sqrt_of,
    pre,
)
from gtsite.load import _ID_RE, CaseLine
from gtsite.svg import ROLES, Layer, Marker, render
from gtsite.words import ENTRY_NAMES, TIER_NAMES, TIER_NUMBER

PREDICATE_ORDER = (
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


@dataclass
class Figure:
    title: str
    svg: str
    caption: str  # HTML
    markers: list[Marker]
    roles: list[str]


@dataclass
class Check:
    status: str  # "ok", "fail" or "none"
    text: str  # HTML


@dataclass
class Example:
    rec: dict[str, Any]
    case_id: str
    anchor: str
    case: CaseLine | None = None
    wkt_a: str | None = None
    wkt_b: str | None = None
    comparison: str = ""
    figures: list[Figure] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    repro: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    wkt_exact: str | None = None  # display WKT of the exact overlay result (rounded)
    wkt_lib: str | None = None  # WKT of the library's overlay output (its doubles)


@dataclass
class ExampleContext:
    """What building an example needs besides the record."""

    target_id: str
    lib: str
    run_command: str  # the adapter's run command from the manifest ("" if unknown)
    repro_available: bool  # does `geotruth repro` exist?
    repo_root: Any  # Path of the repository (for relative case-file paths)
    verify: bool = True  # run the second exact route
    compute_missing: bool = True  # compute an exact answer the caches lack
    uid: str = "x"


# ============================================================================ helpers


def _dim(ch: str) -> int:
    return int(ch) if ch in "012" else -1


def _display_path(ctx: ExampleContext, path: Any) -> str:
    try:
        return str(path.resolve().relative_to(ctx.repo_root.resolve()))
    except (ValueError, OSError):
        return str(path)


def _pt_text(p: P) -> str:
    return f"({approx(p[0], 6)}, {approx(p[1], 6)})"


def _dist_text(d2: Fraction) -> str:
    return fmt_sqrt_of(d2)


def _geom(obj: Any, exact: bool = False) -> Any:
    from geotruth.io import geometry_from_json

    return geometry_from_json(obj, exact=exact)


def _wkt(g: Any) -> str:
    from geotruth.io import to_wkt

    return to_wkt(g)


# ============================================================================ comparisons


def _matrix_table(m: str, other: str, caption: str) -> str:
    rows = []
    for r, rl in enumerate("IBE"):
        cells = []
        for c in range(3):
            k = 3 * r + c
            ch = m[k] if k < len(m) else "?"
            diff = k >= len(other) or other[k] != ch
            cls = ' class="diff"' if diff else ""
            mark = '<span class="sr"> (differs)</span>' if diff else ""
            cells.append(f"<td{cls}>{esc(ch)}{mark}</td>")
        rows.append(f'<tr><th scope="row">{rl}</th>{"".join(cells)}</tr>')
    head = '<tr><th scope="col"><span class="sr">A \\ B</span></th>' + "".join(
        f'<th scope="col">{x}</th>' for x in "IBE"
    )
    return (
        f'<figure class="de9im"><figcaption>{caption} {code(m)}</figcaption>'
        f"<table><thead>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></figure>"
    )


def compare_relate(exp: str, got: str) -> str:
    diff = [ENTRY_NAMES[i] for i in range(9) if i >= len(got) or got[i] != exp[i]]
    return (
        '<div class="compare">'
        + _matrix_table(exp, got, "Exact")
        + _matrix_table(got, exp, "Library")
        + "</div>"
        + f'<p class="small">Rows: interior, boundary, exterior of A; columns: of B. '
        f"Entries that differ: {esc(', '.join(diff))}.</p>"
    )


def _bool(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "–"
    return esc(v)


def compare_predicates(exp: dict[str, Any], got: dict[str, Any], wrong: set[str]) -> str:
    rows = []
    for name in PREDICATE_ORDER:
        if name not in exp and name not in got:
            continue
        e, g = exp.get(name), got.get(name)
        bad = name in wrong
        cls = ' class="diff"' if bad else ""
        mark = ' <span class="neq" aria-label="differs">≠</span>' if bad else ""
        rows.append(
            f'<tr{cls}><th scope="row">{esc(name.replace("_", " "))}</th>'
            f"<td>{_bool(e)}</td><td>{_bool(g)}{mark}</td></tr>"
        )
    return (
        '<table class="cmp"><thead><tr><th scope="col">Predicate</th><th scope="col">Exact</th>'
        f'<th scope="col">Library</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def compare_validity(exp_v: dict[str, Any], got: dict[str, Any], wrong: set[str]) -> str:
    rows = []
    for k in ("a", "b"):
        e = (exp_v or {}).get(k) or {}
        g = got.get(k, got.get(f"valid_{k}"))
        bad = f"valid_{k}" in wrong
        cls = ' class="diff"' if bad else ""
        reason = ""
        if e and not e.get("valid", True):
            reason = (
                " <span "
                f'class="small">({esc(e.get("message") or e.get("first_reason") or "")})</span>'
            )
        mark = ' <span class="neq" aria-label="differs">≠</span>' if bad else ""
        ev = e.get("valid") if e else None
        rows.append(
            f'<tr{cls}><th scope="row">{k.upper()}</th>'
            f"<td>{'valid' if ev else ('invalid' if ev is False else '–')}{reason}</td>"
            f"<td>{'valid' if g is True else ('invalid' if g is False else esc(g))}{mark}</td></tr>"
        )
    return (
        '<table class="cmp"><thead><tr><th scope="col">Operand</th><th scope="col">Exact</th>'
        f'<th scope="col">Library</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def compare_overlay(rec: dict[str, Any], exact_area: str | None, lib_area: Fraction | None) -> str:
    m = rec.get("metrics") or {}
    tier = rec.get("tier", "")
    rows: list[tuple[str, str]] = []
    if tier:
        rows.append(("Tier", f"{TIER_NUMBER.get(tier, '?')} · {esc(TIER_NAMES.get(tier, tier))}"))
    if m.get("variant"):
        v = m["variant"]
        rows.append(
            (
                "Graded against",
                "the regularized areal result (the output has only polygons)"
                if v == "areal"
                else "the non-strict result (lines and points of boundary touches kept)",
            )
        )
    h = None
    if "hausdorff2" in m:
        try:
            h2 = Fraction(m["hausdorff2"])
            h = float(sqrt_frac(h2, 40)) if h2 else 0.0
            rows.append(("Hausdorff distance", f"≈ {esc(fmt_sqrt_of(h2))}"))
        except (ValueError, ZeroDivisionError, OverflowError):
            rows.append(("Hausdorff distance²", esc(m["hausdorff2"])))
    elif "hausdorff2_approx" in m:
        try:
            h = float(m["hausdorff2_approx"]) ** 0.5
            rows.append(("Hausdorff distance", f"≈ {esc(fmt_float(h))} (an exact surd)"))
        except (TypeError, ValueError):
            pass
    elif m.get("hausdorff2_infinite"):
        rows.append(("Hausdorff distance", "infinite: one of the two is empty"))
    if "delta" in m:
        kind = m.get("delta_kind", "")
        rows.append(
            ("δ_lib (the library's budget)", f"{esc(fmt_float(float(m['delta'])))} ({esc(kind)})")
        )
        if h is not None and m["delta"]:
            rows.append(("Hausdorff / δ_lib", f"≈ {esc(fmt_float(h / float(m['delta'])))}"))
    elif m.get("delta_kind"):
        note = m.get("delta_note") or "none documented"
        rows.append(("δ_lib (the library's budget)", f"none ({esc(note)})"))
    if "delta_rounding" in m:
        rows.append(("Rounding floor δ", esc(fmt_float(float(m["delta_rounding"])))))
    if "symdiff_area" in m:
        rows.append(("Area of exact ⊕ library", fmt_rational_str(str(m["symdiff_area"]))))
    if "area_budget" in m:
        rows.append(("Area allowance at the tier's δ", esc(fmt_float(float(m["area_budget"])))))
    if exact_area is not None:
        rows.append(("Exact area", fmt_rational_str(exact_area)))
    if lib_area is not None:
        rows.append(("Library area (even-odd, exact)", fmt_rational_str(str(lib_area))))
    if "output_valid" in m:
        ok = m["output_valid"]
        why = f" ({esc(m['output_reason'])})" if m.get("output_reason") else ""
        rows.append(("Library output valid", ("yes" if ok else "no") + why))
    for key, label in (
        ("missing_components", "Missing components"),
        ("extra_components", "Extra components"),
        ("missing_holes", "Missing holes"),
        ("extra_holes", "Extra holes"),
        ("excused_thin", "Thin exact parts excused"),
    ):
        if m.get(key):
            rows.append((label, esc(m[key])))
    if m.get("nonfinite_output"):
        rows.append(("Output", "has non-finite coordinates"))
    if m.get("unreadable"):
        rows.append(("Output", f"unreadable: {esc(m['unreadable'])}"))
    body = "".join(f'<tr><th scope="row">{esc(k)}</th><td>{v}</td></tr>' for k, v in rows)
    note = ""
    reason = esc(str(m.get("output_reason", "")).replace("_", " "))
    structural = any(
        m.get(k) for k in ("missing_components", "extra_components", "missing_holes", "extra_holes")
    )
    if is_exact_but_invalid(rec):
        note = (
            '<p class="note">The output covers exactly the right point set (Hausdorff distance 0, '
            "symmetric-difference area 0); it is graded topological only because it is not valid "
            f"OGC geometry ({reason}).</p>"
        )
    elif tier == "topological" and m.get("output_valid") is False and not structural:
        budget = m.get("delta") if m.get("delta") is not None else m.get("delta_rounding")
        within = False
        if budget is not None and "hausdorff2" in m:
            try:  # exact: h² <= δ² (δ as the scorer printed it)
                within = Fraction(m["hausdorff2"]) <= Fraction(float(budget)) ** 2
            except (ValueError, ZeroDivisionError, TypeError):
                within = False
        elif budget is not None and h is not None:
            within = h <= 0.99 * float(budget)  # an approximated surd: keep a margin
        if within:
            which = "δ_lib" if m.get("delta") is not None else "the rounding floor"
            note = (
                f'<p class="note">By Hausdorff distance the output is within {which} of the exact '
                "result (the area allowance is not evaluated for topological results); it is "
                f"graded topological because it is not valid OGC geometry ({reason}).</p>"
            )
    return f'<table class="cmp kv"><tbody>{body}</tbody></table>{note}'


def compare_error(rec: dict[str, Any]) -> str:
    got = rec.get("got")
    if isinstance(got, dict):
        text = "\n".join(f"{k}: {v}" for k, v in got.items())
    else:
        text = str(got or "")
    kind = (rec.get("metrics") or {}).get("error_kind")
    head = (
        f"<p>The library failed ({esc(kind)}); the exact engine answered.</p>"
        if kind
        else ("<p>The library failed; the exact engine answered.</p>")
    )
    return head + pre(text or "(no message)", "err")


def compare_echo(case: Any, result: dict[str, Any] | None) -> str:
    from geotruth.geom import Geometry

    echo = (result or {}).get("echo")
    if not isinstance(echo, dict):
        return "<p>The echoed operands are not available (no result line).</p>"
    rows = []
    for k in ("a", "b"):
        want: Geometry = getattr(case, k)
        try:
            got = _geom(echo.get(k))
        except Exception as exc:  # the echo itself is malformed
            rows.append(f'<tr><th>{k.upper()}</th><td colspan="2">unreadable: {esc(exc)}</td></tr>')
            continue
        wv = [float(v) for v in want.iter_values()]
        gv = [float(v) for v in got.iter_values()]
        shown = 0
        for i in range(max(len(wv), len(gv))):
            w = wv[i] if i < len(wv) else None
            g = gv[i] if i < len(gv) else None
            same = w is not None and g is not None and (w == g or (w != w and g != g))
            if same and w == 0:
                same = str(w)[0] == str(g)[0]  # -0.0 keeps its sign
            if not same:
                rows.append(
                    f'<tr class="diff"><th scope="row">{k.upper()} ordinate {i}</th>'
                    f"<td>{esc(repr(w)) if w is not None else '–'}</td>"
                    f"<td>{esc(repr(g)) if g is not None else '–'}</td></tr>"
                )
                shown += 1
                if shown >= 10:
                    break
    if not rows:
        return "<p>No ordinate differs; the type tree differs.</p>"
    return (
        '<table class="cmp"><thead><tr><th scope="col">Where</th><th scope="col">Input double</th>'
        f'<th scope="col">Echoed</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# ============================================================================ views


def _relate_view(case: Any, pa: Parts, pb: Parts, exp: str, got: str) -> L.View | None:
    """The zoom window for a relate disagreement (see :mod:`gtsite.locus`)."""
    views: list[L.View] = []
    missed = [i for i in range(9) if i < len(got) and _dim(exp[i]) > _dim(got[i])]
    extra = [i for i in range(9) if i < len(got) and _dim(got[i]) > _dim(exp[i])]
    if missed:
        try:
            from geotruth.relate import relate

            res = relate(case.a, case.b, keep_arrangement=True)
            cells = res.realizers() if res.ok else {}
            arr = res.arrangement
        except Exception:  # an engine failure only costs the figure its zoom
            cells, arr = {}, None
        for i in missed:
            name = ENTRY_NAMES[i]
            cell = cells.get(name)
            if cell is None or arr is None:
                continue
            what = (
                f"the {('vertex', 'edge', 'face')[cell.dim]} of the exact arrangement that "
                f"realises {name} = {exp[i]}; the library reports {name} = {got[i]}"
            )
            if cell.dim == 0:
                views.append(L.around_point(arr.vertex_fractions(cell.index), [pa, pb], what))
            elif cell.dim == 1:
                h = 2 * cell.index
                ends = [
                    arr.vertex_fractions(arr.he_origin[h]),
                    arr.vertex_fractions(arr.he_origin[h + 1]),
                ]
                views.append(L.around_points(ends, [pa, pb], what))
            elif cell.index > 0 and arr.face_outer[cell.index] >= 0:
                pts = [
                    arr.vertex_fractions(arr.he_origin[g])
                    for g in arr.cycle(arr.face_outer[cell.index])
                ]
                views.append(L.around_points(pts, [pa, pb], what))
    ca = L.closest_approach(pa, pb)
    if ca is not None and views:
        # the realising cell is exact; when the closest approach between A and B lies inside
        # its window and is much smaller, that near-degenerate spot is where to look
        d2, p, q = ca
        best = min(views, key=lambda v: v.half)
        gap = L.around_gap(p, q, d2, "", heuristic=True)
        bx0, by0, bx1, by1 = best.box
        if bx0 <= gap.cx <= bx1 and by0 <= gap.cy <= by1 and gap.half * 4 < best.half:
            gap.what = (
                f"the closest approach between A and B (distance ≈ {_dist_text(d2)}), inside "
                f"the window of {best.what}"
            )
            return gap
    if (extra or not views) and ca is not None:
        d2, p, q = ca
        names = ", ".join(ENTRY_NAMES[i] for i in extra) or "the differing entries"
        views.append(
            L.around_gap(
                p,
                q,
                d2,
                f"the closest approach between A and B (distance ≈ {_dist_text(d2)}), the "
                f"likeliest source of the library's {names}",
                heuristic=True,
            )
        )
    views = [v for v in views if v.half > 0]
    return min(views, key=lambda v: v.half) if views else None


def _near_view(pa: Parts, pb: Parts, why: str) -> L.View | None:
    ca = L.closest_approach(pa, pb)
    if ca is not None:
        d2, p, q = ca
        return L.around_gap(
            p,
            q,
            d2,
            f"the closest approach between A and B (distance ≈ {_dist_text(d2)}); {why}",
            heuristic=True,
        )
    touch = L.contacts(pa, pb)
    if touch:
        v = L.around_point(
            touch[0],
            [pa, pb],
            f"a point where a vertex of one operand lies exactly on the other; {why}",
        )
        v.heuristic = True
        return v
    return None


def _defect_view(geom: Any, parts: Parts, whose: str) -> L.View | None:
    from geotruth.validity import validate

    try:
        report = validate(geom)
    except Exception:
        return None
    for d in report.defects:
        if d.location:
            pts = [(_fr(x), _fr(y)) for x, y in d.location]
            return L.around_points(pts, [parts], f"the exact defect of {whose}: {d.message}")
    return None


def _fr(v: Any) -> Fraction:
    from gtsite.exact2d import frac

    f = frac(v)
    return f if f is not None else Fraction(0)


def _overlay_view(
    exact_p: Parts, lib_p: Parts, lib_geom: Any, rec: dict[str, Any]
) -> L.View | None:
    m = rec.get("metrics") or {}
    if m.get("output_valid") is False:
        v = _defect_view(lib_geom, lib_p, "the library's output")
        if v is not None:
            return v
    dev = L.deviation(exact_p, lib_p)
    if dev is not None and dev[0] > 0:
        d2, p, q, name = dev
        other = "exact result" if name == "library" else "library's output"
        whose = "library's output" if name == "library" else "exact result"
        return L.around_gap(
            p,
            q,
            d2,
            f"the point of the {whose} farthest from the {other} (distance ≈ {_dist_text(d2)})",
            Fraction(3, 2),
        )
    return None


# ============================================================================ figures


def _caption(view: L.View, ov: L.View | None) -> str:
    width = fmt_sqrt_of((2 * view.half) ** 2)
    zoom = ""
    if ov is not None and view.half > 0 and view is not ov:
        ratio = ov.half / view.half
        times = fmt_float(float(ratio), 2) if ratio < 10**300 else "more than 1e300"
        zoom = f"; magnified {esc(times)} times relative to the whole case"
    return (
        f"Window centred at ≈ ({esc(approx(view.cx, 8))}, {esc(approx(view.cy, 8))}), "
        f"{esc(width)} wide{zoom}."
    )


def build_figures(
    uid: str,
    ov: L.View,
    zoom: L.View | None,
    pa: Parts,
    pb: Parts,
    result_layers: list[Layer] | None,
) -> list[Figure]:
    figs: list[Figure] = []
    if zoom is not None and zoom.half * 2 >= ov.half:
        if zoom.heuristic:
            # no near-degenerate spot: the heuristic has nothing to point at
            zoom = None
        else:
            # the discrepancy spans the case: show it on the overview
            ov = L.View(ov.cx, ov.cy, ov.half, zoom.what, zoom.focus)
            zoom = None
    has_zoom = zoom is not None
    layers = [Layer(pa, "a", number=not has_zoom), Layer(pb, "b", number=not has_zoom)]
    svg, markers = render(
        ov,
        layers,
        uid=f"{uid}-o",
        title="Both operands, the whole case",
        desc="A drawn in blue with solid edges and round vertex marks, B in orange with "
        "dashed edges and square marks"
        + ("; the ring marks the zoomed window" if has_zoom else ""),
        inset=zoom,
    )
    cap = "The ring (or rectangle) marks the zoomed window." if has_zoom else _caption(ov, None)
    if not has_zoom and ov.what != "the whole case":
        cap = f"Marked: {esc(ov.what)}. " + cap
    figs.append(Figure("Whole case", svg, cap, markers, ["a", "b"]))
    view = zoom or ov
    if zoom is not None:
        svg, markers = render(
            zoom,
            [Layer(pa, "a"), Layer(pb, "b")],
            uid=f"{uid}-z",
            title="Both operands, zoomed to the discrepancy",
            desc=f"Zoomed to {zoom.what}",
        )
        figs.append(
            Figure(
                "Zoomed to the discrepancy",
                svg,
                f"Zoomed to {esc(zoom.what)}. {_caption(zoom, ov)}",
                markers,
                ["a", "b"],
            )
        )
    if result_layers:
        roles = [ly.role for ly in result_layers]
        svg, markers = render(
            view,
            result_layers,
            uid=f"{uid}-r",
            title="Exact result and library output",
            desc="The exact result filled in green with solid edges and diamond marks; the "
            "library output in violet with dashed edges and cross marks; the operands as "
            "grey outlines",
        )
        figs.append(
            Figure(
                "Exact result and library output" + (", same window" if zoom else ""),
                svg,
                "The exact result against the library's output"
                + (" in the zoomed window." if zoom else ", whole case. " + _caption(view, None)),
                markers,
                roles,
            )
        )
    return figs


def markers_table(fig: Figure) -> str:
    if not fig.markers:
        return ""
    rows = []
    for m in fig.markers:
        who = ", ".join(ROLES.get(r, r) for r in m.roles)
        rows.append(
            f'<tr><th scope="row">{m.n}</th><td>{esc(who)}</td>'
            f'<td class="c">{coord_cell(m.point[0])}</td><td '
            f'class="c">{coord_cell(m.point[1])}</td></tr>'
        )
    return (
        '<table class="coords"><caption>Numbered vertices, exact coordinates (a double as its '
        "shortest round-trip decimal and its exact binary value; another rational as n/d)"
        '</caption><thead><tr><th scope="col">#</th><th scope="col">Of</th><th scope="col">x</th>'
        f'<th scope="col">y</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# ============================================================================ checks


def _check_relate(case: Any, exp_matrix: str | None) -> Check:
    if not exp_matrix:
        return Check("none", "No exact matrix to re-check.")
    try:
        from geotruth.relate_witness import relate_witness

        m = relate_witness(case.a, case.b).matrix
    except Exception as exc:
        return Check(
            "fail", f"The witness-point route failed: {esc(type(exc).__name__)}: {esc(exc)}"
        )
    if m == exp_matrix:
        return Check(
            "ok",
            f"The independent witness-point route (DESIGN §2.4) gives the same matrix {code(m)}.",
        )
    return Check(
        "fail",
        f"The witness-point route gives {code(m)}, not {code(exp_matrix)}: the exact answer of "
        "this case is in doubt, and this example must not be cited until that is resolved.",
    )


def _check_overlay(case: Any, op: str, variant: str, exact_geom: Any) -> Check:
    try:
        from geotruth.overlay_certify import certify

        cert = certify(case.a, case.b, op, exact_geom, variant)
    except Exception as exc:
        return Check(
            "fail", f"The certificate could not run: {esc(type(exc).__name__)}: {esc(exc)}"
        )
    if cert.ok:
        return Check(
            "ok",
            f"The independent overlay certificate (DESIGN §2.6) confirms the exact result "
            f"({cert.witnesses} witness points located in A, B and the result).",
        )
    return Check(
        "fail",
        f"The overlay certificate rejects the exact result: {esc(cert.summary())}. This "
        "example must not be cited until that is resolved.",
    )


def _check_validity(geom: Any, exact_valid: bool | None, which: str) -> Check:
    from geotruth.geom import MultiPolygon, Polygon

    if exact_valid is None:
        return Check("none", f"No exact validity of {which} to re-check.")
    if not isinstance(geom, (Polygon, MultiPolygon)):
        return Check(
            "none",
            f"{which} is not polygonal; the audited reference rules cover polygons only, so the "
            "engine's answer (geotruth.validity) stands alone here.",
        )
    try:
        from geotruth.harness.fallback_overlay import _v1, reference_module

        ref = reference_module("validity").valid_geometry(_v1(geom))
    except Exception as exc:
        return Check("none", f"The reference rules could not run: {esc(type(exc).__name__)}")
    if bool(ref) == bool(exact_valid):
        return Check(
            "ok",
            f"The audited reference rules (tests/reference/validity.py) agree: {which} is "
            f"{'valid' if ref else 'invalid'}.",
        )
    return Check(
        "fail",
        f"The reference rules say {which} is {'valid' if ref else 'invalid'}; the engine says "
        f"{'valid' if exact_valid else 'invalid'}. This example must not be cited until that is "
        "resolved.",
    )


# ============================================================================ repro


def repro_commands(
    ctx: ExampleContext,
    cl: CaseLine,
    cap: str,
    variant: str | None,
    wkts: dict[str, str],
    wrong: list[str],
) -> list[tuple[str, str]]:
    path = shlex.quote(_display_path(ctx, cl.path))
    cid = cl.id
    out: list[tuple[str, str]] = []
    if cap in ("relate", "predicates", "echo"):
        out.append(
            (
                "the exact DE-9IM matrix and predicates, by both exact routes",
                f"geotruth relate @{path} --id {cid} --dual",
            )
        )
    elif cap.startswith("overlay."):
        op = cap.split(".", 1)[1]
        areal = " --areal" if variant == "areal" else ""
        out.append(
            (
                "the exact result, with its certificate",
                f"geotruth overlay @{path} {op} --id {cid}{areal} --certify",
            )
        )
    elif cap == "validity":
        for k in ("a", "b"):
            if f"valid_{k}" in wrong and k in wkts:
                out.append(
                    (f"the exact validity of {k.upper()}", f"geotruth valid {shlex.quote(wkts[k])}")
                )
    if ctx.repro_available:
        out.append(
            (
                "the library's answer next to the exact one",
                f"geotruth repro {cid} --lib {ctx.target_id}",
            )
        )
    elif ctx.run_command:
        m = _ID_RE.search(cl.line)
        if m:
            pat = shlex.quote(cl.line[m.start() : m.end()])
            out.append(
                (
                    f"the library's own answer, from the adapter the scores come from "
                    f"(with {ctx.target_id} built)",
                    f"grep -F {pat} {path} > case.jsonl && {ctx.run_command} case.jsonl",
                )
            )
    return out


# ============================================================================ an example


def build_example(
    ctx: ExampleContext,
    rec: dict[str, Any],
    cl: CaseLine | None,
    result: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    anchor: str,
) -> Example:
    ex = Example(rec=rec, case_id=rec["id"], anchor=anchor, case=cl)
    cap = rec["capability"]
    verdict = rec["verdict"]
    wrong = set(rec.get("fields") or [])
    if cl is None:
        ex.notes.append("The case file was not found, so the inputs and figures are missing.")
        ex.comparison = _comparison_from_record(rec)
        return ex
    try:
        from geotruth.io import case_from_json

        case = case_from_json(cl.obj)
    except Exception as exc:
        ex.notes.append(f"The case could not be read: {type(exc).__name__}: {exc}")
        ex.comparison = _comparison_from_record(rec)
        return ex
    ex.wkt_a, ex.wkt_b = _wkt(case.a), _wkt(case.b)
    pa, pb = parts_of(case.a), parts_of(case.b)
    if pa.dropped or pb.dropped:
        ex.notes.append("Non-finite coordinates are not drawn.")
    if expected is None and ctx.compute_missing and cap != "echo":
        try:
            from geotruth.harness.engine import expected_record

            expected = expected_record(case)
            ex.notes.append(
                "The scorer's cached exact answer was not found; the exact answer shown in the "
                "figures was recomputed by the engine this site was built with."
            )
        except Exception as exc:
            ex.notes.append(f"The exact answer could not be recomputed: {type(exc).__name__}")
    zoom: L.View | None = None
    result_layers: list[Layer] | None = None
    variant = None

    if verdict == "error":
        ex.comparison = compare_error(rec)
        zoom = _near_view(
            pa, pb, "where a near-degenerate case usually has its difficulty (a heuristic)"
        )
    elif cap == "echo":
        ex.comparison = compare_echo(case, result)
    elif cap == "relate":
        exp, got = str(rec.get("expected", "")), str(rec.get("got", ""))
        ex.comparison = compare_relate(exp, got)
        zoom = _relate_view(case, pa, pb, exp, got)
    elif cap == "predicates":
        exp_p = dict((expected or {}).get("predicates") or rec.get("expected") or {})
        got_p = dict((result or {}).get("predicates") or rec.get("got") or {})
        names = {f.split(".", 1)[1] for f in wrong if f.startswith("predicates.")}
        ex.comparison = compare_predicates(exp_p, got_p, names)
        exp_m = (expected or {}).get("relate")
        got_m = (result or {}).get("relate")
        if isinstance(exp_m, str) and isinstance(got_m, str) and len(got_m) == 9 and exp_m != got_m:
            zoom = _relate_view(case, pa, pb, exp_m, got_m)
            ex.notes.append(
                f"The library's own DE-9IM matrix for this case is {got_m}; the exact one "
                f"is {exp_m}."
            )
        else:
            zoom = _near_view(
                pa, pb, "the likeliest place for a predicate to go wrong (a heuristic)"
            )
    elif cap == "validity":
        exp_v = (expected or {}).get("validity") or {
            k: {"valid": v} for k, v in (rec.get("expected") or {}).items()
        }
        got_v = {k: (result or {}).get(f"valid_{k}", (rec.get("got") or {}).get(k)) for k in "ab"}
        ex.comparison = compare_validity(exp_v, got_v, wrong)
        for k in ("a", "b"):
            if f"valid_{k}" not in wrong:
                continue
            geom, parts = (case.a, pa) if k == "a" else (case.b, pb)
            ev = (exp_v.get(k) or {}).get("valid")
            if ev is False:
                zoom = _defect_view(geom, parts, k.upper())
            else:
                sa = L.self_approach(parts)
                if sa is not None:
                    d2, p, q = sa
                    zoom = L.around_gap(
                        p,
                        q,
                        d2,
                        f"the closest approach between non-adjacent parts of {k.upper()} (distance "
                        f"≈ {_dist_text(d2)}), where the library probably sees a defect (a "
                        "heuristic)",
                        heuristic=True,
                    )
            break
    elif cap.startswith("overlay."):
        op = cap.split(".", 1)[1]
        variant = (rec.get("metrics") or {}).get("variant") or "non_strict"
        exp_op = ((expected or {}).get("overlay") or {}).get(op) or {}
        exact_json = (exp_op.get(variant) or {}).get("exact")
        lib_json = ((result or {}).get("overlay") or {}).get(op)
        exact_geom = lib_geom = None
        try:
            exact_geom = _geom(exact_json, exact=True) if exact_json is not None else None
        except Exception:
            exact_geom = None
        try:
            lib_geom = _geom(lib_json) if isinstance(lib_json, dict) else None
        except Exception:
            lib_geom = None
        lib_area = None
        if lib_geom is not None:
            try:
                from geotruth.harness import metrics as M

                lib_area = _fr(M.even_odd_area(M.shape_of(lib_geom).rings()))
            except Exception:
                lib_area = None
        ex.comparison = compare_overlay(rec, (exp_op.get(variant) or {}).get("area"), lib_area)
        if exact_geom is not None or lib_geom is not None:
            ex_p = parts_of(exact_geom) if exact_geom is not None else Parts()
            lib_p = parts_of(lib_geom) if lib_geom is not None else Parts()
            result_layers = [
                Layer(pa, "ghost-a", number=False),
                Layer(pb, "ghost-b", number=False),
                Layer(ex_p, "exact"),
                Layer(lib_p, "lib"),
            ]
            zoom = _overlay_view(ex_p, lib_p, lib_geom, rec)
            ex.wkt_exact = _wkt(exact_geom) if exact_geom is not None else None
            ex.wkt_lib = _wkt(lib_geom) if lib_geom is not None else None
            if lib_geom is None:
                ex.notes.append("The library's output is not available (no result line).")
        if ctx.verify and exact_geom is not None:
            ex.checks.append(_check_overlay(case, op, variant, exact_geom))

    ov = L.overview([pa, pb] + ([ly.parts for ly in result_layers] if result_layers else []))
    if ov is not None:
        ex.figures = build_figures(ctx.uid, ov, zoom, pa, pb, result_layers)
    else:
        ex.notes.append("Both operands are empty: there is nothing to draw.")

    if ctx.verify:
        if cap in ("relate", "predicates"):
            exp_m = (expected or {}).get("relate")
            if exp_m is None and cap == "relate" and verdict != "error":
                exp_m = rec.get("expected")
            ex.checks.append(_check_relate(case, exp_m))
        elif cap == "validity":
            exp_v = (expected or {}).get("validity") or {}
            for k in ("a", "b"):
                if f"valid_{k}" in wrong or verdict == "error":
                    geom = case.a if k == "a" else case.b
                    ex.checks.append(
                        _check_validity(geom, (exp_v.get(k) or {}).get("valid"), k.upper())
                    )
    ex.repro = repro_commands(ctx, cl, cap, variant, {"a": ex.wkt_a, "b": ex.wkt_b}, sorted(wrong))
    return ex


def _comparison_from_record(rec: dict[str, Any]) -> str:
    """What the score record alone says (no case file)."""
    cap = rec["capability"]
    if rec["verdict"] == "error":
        return compare_error(rec)
    if cap == "relate":
        return compare_relate(str(rec.get("expected", "")), str(rec.get("got", "")))
    if cap.startswith("overlay."):
        return compare_overlay(rec, None, None)
    exp, got = rec.get("expected"), rec.get("got")
    return (
        '<table class="cmp kv"><tbody>'
        f'<tr><th scope="row">Exact</th><td>{code(exp)}</td></tr>'
        f'<tr><th scope="row">Library</th><td>{code(got)}</td></tr></tbody></table>'
    )


def legend(roles: list[str]) -> str:
    items = "".join(
        f'<li><span class="sw sw-{r}" aria-hidden="true"></span>{esc(ROLES.get(r, r))}</li>'
        for r in roles
    )
    return f'<ul class="legend">{items}</ul>'
