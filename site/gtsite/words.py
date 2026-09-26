"""The site's vocabulary: names and one-line explanations of capabilities, verdicts, overlay
tiers, triage statuses, corpus families and failure-cluster signatures.

Every definition here restates DESIGN.md and ``src/geotruth/harness/score.py``; when the
scorer changes, this file must follow it (``tests/site`` checks that every capability,
verdict and tier the scorer can emit has an entry).
"""

from __future__ import annotations

import re

#: Capabilities in display order (``geotruth.harness.score.CAPABILITIES``).
CAPABILITIES = (
    "echo",
    "relate",
    "predicates",
    "validity",
    "overlay.intersection",
    "overlay.union",
    "overlay.difference",
    "overlay.symdifference",
)
#: Capabilities graded exactly (one right answer, no tolerance).
EXACT_CAPABILITIES = ("relate", "predicates", "validity")
OVERLAY_CAPABILITIES = (
    "overlay.intersection",
    "overlay.union",
    "overlay.difference",
    "overlay.symdifference",
)

CAPABILITY_NAMES = {
    "echo": "Parse-echo canary",
    "relate": "Relate (DE-9IM)",
    "predicates": "Named predicates",
    "validity": "Validity",
    "overlay.intersection": "Intersection",
    "overlay.union": "Union",
    "overlay.difference": "Difference",
    "overlay.symdifference": "Symmetric difference",
}
CAPABILITY_SHORT = {
    "echo": "Echo",
    "relate": "Relate",
    "predicates": "Predicates",
    "validity": "Validity",
    "overlay.intersection": "Intersection",
    "overlay.union": "Union",
    "overlay.difference": "Difference",
    "overlay.symdifference": "Sym. diff.",
}
CAPABILITY_TEXT = {
    "echo": "the operands read back by the adapter must be the input doubles, bit for bit "
    "(-0.0 keeps its sign); a check of the adapter's input path, not of geometry",
    "relate": "the DE-9IM intersection matrix, compared exactly with the exact matrix",
    "predicates": "the named predicates (intersects, touches, crosses, overlaps, contains, "
    "covers, within, covered by, equals, disjoint) of a case, graded together: one record "
    "per case",
    "validity": "the OGC validity of each operand (GEOS IsValidOp rules), graded on the "
    "boolean; the reason is informational",
    "overlay.intersection": "the intersection A ∩ B, graded in tiers against the exact result",
    "overlay.union": "the union A ∪ B, graded in tiers against the exact result",
    "overlay.difference": "the difference A − B, graded in tiers against the exact result",
    "overlay.symdifference": "the symmetric difference A ⊕ B, graded in tiers against the "
    "exact result",
}

#: Verdicts in display order (``schemas/score.v2.schema.json``).
VERDICTS = (
    "correct",
    "wrong",
    "error",
    "convention",
    "unsupported",
    "not_reported",
    "engine_skipped",
    "engine_error",
)
#: Verdicts that are graded (the denominator of a rate).
GRADED_VERDICTS = ("correct", "wrong", "error", "convention")
#: Verdicts counted against a library (unless the record is marked derived).
FAILURE_VERDICTS = ("wrong", "error")

VERDICT_NAMES = {
    "correct": "correct",
    "wrong": "wrong",
    "error": "error",
    "convention": "convention",
    "unsupported": "unsupported",
    "not_reported": "not reported",
    "engine_skipped": "engine skipped",
    "engine_error": "engine error",
}
VERDICT_TEXT = {
    "correct": "agrees with the exact answer (overlay: tiers 1-3)",
    "wrong": "disagrees with the exact answer (overlay: tier 4 gross or 5 topological)",
    "error": "the library raised an exception, crashed or hung (overlay: tier 6)",
    "convention": "disagrees only on a field that the empty-geometry convention table "
    "decides; shown separately, never counted as wrong",
    "unsupported": "outside the library's documented contract (for example coordinates "
    "beyond its range, or a geometry type it does not take); never counted as wrong",
    "not_reported": "the adapter reports no answer (null): the library has no such "
    "operation or the adapter does not call it",
    "engine_skipped": "the exact engine abstained (over its size or time budget); never "
    "counted against the library",
    "engine_error": "the exact engine failed on this case; never counted against the library",
}

#: Overlay tiers 1-6 (DESIGN §4.3).
TIERS = ("exact", "rounding", "budget", "gross", "topological", "exception")
HEADLINE_TIERS = ("gross", "topological", "exception")
TIER_NUMBER = {t: i + 1 for i, t in enumerate(TIERS)}
TIER_NAMES = {
    "exact": "exact",
    "rounding": "within rounding",
    "budget": "within budget",
    "gross": "gross",
    "topological": "topological",
    "exception": "exception",
}
TIER_TEXT = {
    "exact": "the output's point set is exactly the exact result (Hausdorff distance 0 and "
    "symmetric-difference area 0)",
    "rounding": "within the correctly rounded floor δ = ulp(M)/√2, M the largest input "
    "ordinate: Hausdorff distance ≤ δ and |E ⊕ L| ≤ 2δ(P_E + P_L) + πδ²n",
    "budget": "within the library's own documented displacement budget δ_lib (the same two "
    "conditions); exact components thinner than δ may vanish or collapse",
    "gross": "beyond the library's documented budget (or beyond rounding, when the library "
    "documents none)",
    "topological": "invalid output, or a missing or extra component or hole",
    "exception": "an exception, crash, hang or memory failure",
}

TRIAGE_STATUSES = ("unreviewed", "confirmed", "reported", "fixed", "by-design")
TRIAGE_TEXT = {
    "unreviewed": "found by the harness, not yet triaged by a person: an automated "
    "disagreement, not a confirmed bug",
    "confirmed": "triaged: a wrong answer within the library's documented contract",
    "reported": "confirmed and reported upstream",
    "fixed": "fixed upstream",
    "by-design": "triaged: documented or intended behaviour, not reported as a bug",
}

#: DE-9IM entry names in matrix order.
ENTRY_NAMES = ("II", "IB", "IE", "BI", "BB", "BE", "EI", "EB", "EE")
ENTRY_TEXT = {
    "I": "interior",
    "B": "boundary",
    "E": "exterior",
}

#: Short descriptions of the corpus families (corpus/README.md, corpus/generators/README.md).
FAMILY_TEXT = {
    "near-collinear": "a vertex a few ulps off another polygon's edge, an edge bent by "
    "ulps, nearly collinear edges",
    "vertex-on-edge": "vertices exactly on another polygon's sloped edge",
    "shared-edge": "fully or partially shared collinear edges, sloped and exact, plus "
    "floating-point variants",
    "tiny-transform": "the same polygon moved by 1 ulp to 1e-9 of the coordinate magnitude",
    "sliver-spike": "near-zero-area parts of valid polygons, nearly coincident parallel edges",
    "hole-contact": "B fills, touches or nearly touches a hole boundary of A",
    "multi-touch": "multipolygons whose parts touch at a point, with B at or around the touch",
    "tiling-contact": "tiles computed by different formulas, so shared edges agree only up "
    "to rounding",
    "int-grid": "integer-lattice polygons with many exact collinearities",
    "scaled": "a case from another family scaled by 2^k (exact) or 10^x (rounded)",
    "line-line": "collinear overlaps, T-junctions, endpoints on vertices and segments, "
    "proper crossings",
    "line-mod2": "the Mod-2 boundary rule: closed lines, endpoints shared by several lines",
    "point-geometry": "points on vertices, segments, endpoints, polygon edges and holes, "
    "inside and outside",
    "line-polygon": "lines along edges, through vertices, tangent, inside touching the "
    "boundary, chords, in holes",
    "gc": "geometry collections: overlapping polygons, mixed dimensions, nested collections",
    "empty": "empty geometries of every type and collections of empties (convention cases)",
    "invalid-zero-length-line": "lines whose points all coincide (invalid for GEOS; real "
    "dimension 0 in RelateNG)",
}

_TIER_SIG = {
    "gross": "output beyond the library's documented displacement budget (tier 4, gross)",
    "topological": "invalid output, or a missing or extra component or hole (tier 5, topological)",
    "exception": "an exception, crash, hang or memory failure (tier 6)",
}


def sentence(text: str) -> str:
    """``text`` with its first letter in upper case (the rest untouched)."""
    return text[:1].upper() + text[1:]


def capability_name(cap: str) -> str:
    return CAPABILITY_NAMES.get(cap, cap)


def capability_anchor(cap: str) -> str:
    """The fragment id of a capability's section on a library page."""
    return "cap-" + cap.replace(".", "-")


def split_cluster_key(key: str) -> tuple[str, str, str]:
    """``(target, family, signature)`` of a cluster key ``target|family|signature``; the
    signature keeps any ``|tolerance`` suffix."""
    parts = key.split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


def explain_signature(signature: str, capability: str) -> str:
    """A sentence (no final period) saying what a cluster signature means."""
    sig = signature
    tolerance = sig.endswith("|tolerance")
    if tolerance:
        sig = sig[: -len("|tolerance")]
    head, _, rest = sig.partition(":")
    out: str
    if head == "echo" or sig == "echo":
        out = "the echoed operands are not the input doubles, bit for bit"
    elif head == "relate" and rest and rest != "error":
        entries = rest.split(",")
        if len(entries) == 1:
            out = f"the DE-9IM entry {entries[0]} differs from the exact matrix"
        else:
            out = "the DE-9IM entries " + ", ".join(entries) + " differ from the exact matrix"
    elif head == "predicates" and rest and rest != "error":
        names = [n.replace("_", " ") for n in rest.split(",")]
        out = "wrong " + ("predicate: " if len(names) == 1 else "predicates: ") + ", ".join(names)
    elif head == "validity" and rest and rest != "error":
        parts = []
        for item in rest.split(","):
            m = re.fullmatch(r"valid_([ab])=(true|false)", item)
            if not m:
                parts.append(item)
                continue
            op = m.group(1).upper()
            if m.group(2) == "false":
                parts.append(f"reports {op} invalid, but {op} is valid")
            else:
                parts.append(f"reports {op} valid, but {op} is invalid")
        out = "; ".join(parts)
    elif head.startswith("overlay.") and rest in _TIER_SIG:
        out = f"{capability_name(head).lower()}: {_TIER_SIG[rest]}"
    elif rest == "error":
        out = f"{capability_name(capability).lower()}: the library raised an error"
    else:
        out = sig
    if tolerance:
        out += " (the library documents tolerance-based predicates)"
    return out


def fmt_count(n: int) -> str:
    """An integer with thousands separators."""
    return f"{n:,}"


def fmt_pct(k: int, n: int) -> str:
    """k/n as a percentage, with enough digits that a non-zero count never shows as 0%."""
    if n <= 0:
        return "–"
    if k == 0:
        return "0%"
    if k == n:
        return "100%"
    p = 100.0 * k / n
    first = 0 if p >= 10 else (1 if p >= 1 else 2)
    s = f"{p:.{first}f}"
    for decimals in range(first, 16):
        s = f"{p:.{decimals}f}"
        if 0.0 < float(s) < 100.0:
            break
    return s + "%"
