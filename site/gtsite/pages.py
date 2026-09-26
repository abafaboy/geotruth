"""The pages of the site: the scoreboard (landing page), one page per library, one per
failure cluster, the findings and the methodology, plus the JSON index."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gtsite import triage
from gtsite.aggregate import CapStats, Cluster, is_exact_but_invalid
from gtsite.examples import Example, legend, markers_table
from gtsite.html import (
    a,
    badge,
    code,
    commit_link,
    dl,
    esc,
    ext,
    pre,
    rel,
    render_page,
    short_sha,
    slug,
    template,
)
from gtsite.load import ScoreSet
from gtsite.words import (
    CAPABILITIES,
    CAPABILITY_NAMES,
    CAPABILITY_SHORT,
    CAPABILITY_TEXT,
    EXACT_CAPABILITIES,
    FAMILY_TEXT,
    HEADLINE_TIERS,
    OVERLAY_CAPABILITIES,
    TIER_NAMES,
    TIER_NUMBER,
    TIER_TEXT,
    TIERS,
    TRIAGE_STATUSES,
    TRIAGE_TEXT,
    VERDICT_NAMES,
    VERDICT_TEXT,
    VERDICTS,
    capability_anchor,
    explain_signature,
    fmt_count,
    fmt_pct,
    sentence,
)

#: Harness controls: shown apart from the libraries under test.
CONTROLS = {
    "engine-control": "Internal control: geotruth's own exact engine behind the adapter "
    "contract. It must score 100%; anything else is a harness bug.",
    "mutant": "Fault-injection control: the engine with deliberate faults. Its failures "
    "show that the scorer catches wrong answers; they are expected.",
}
#: Libraries with a special role that are still libraries under test.
ROLE_NOTES = {
    "cgal": "External exact control (DESIGN §0.2): CGAL's exact kernel should agree with "
    "the engine wherever it answers.",
}
MIXED_TEXT = "the matching registry entries disagree on the status"
CHECK_LABEL = {"ok": "re-checked", "fail": "in doubt", "none": "no second route"}
TIER_ABBR = {"gross": "gross", "topological": "topol.", "exception": "exc."}
PREDICATE_NAMES = (
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
class Page:
    path: str
    html: str


@dataclass
class SiteContext:
    tier: str
    sets: list[ScoreSet]
    registry: list[dict[str, Any]]
    registry_problem: str | None
    registry_rel: str
    generated: str
    repo_url: str
    ref: str
    preview: bool
    max_examples: int
    package_version: str
    engine_version: str
    repro_available: bool
    cluster_path: dict[tuple[str, str], str] = field(default_factory=dict)
    cluster_matches: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    examples: dict[tuple[str, str], list[Example]] = field(default_factory=dict)

    # -------------------------------------------------------------- helpers

    def libraries(self) -> list[ScoreSet]:
        """The libraries under test, in alphabetical order of their names (never by score)."""
        libs = [s for s in self.sets if s.target_id not in CONTROLS]
        return sorted(libs, key=lambda s: (s.library.casefold(), s.target_id))

    def controls(self) -> list[ScoreSet]:
        return [s for s in self.sets if s.target_id in CONTROLS]

    def repo_file(self, path: str) -> str:
        return f"{self.repo_url.rstrip('/')}/blob/{self.ref}/{path}"

    def lib_path(self, target: str) -> str:
        return f"lib/{slug(target)}.html"

    def triage_status(self, target: str, key: str) -> str:
        return triage.status(self.cluster_matches.get((target, key), []))


def cluster_file(cl: Cluster) -> str:
    h = hashlib.sha1(cl.key.encode("utf-8")).hexdigest()[:8]
    return f"cluster/{slug(cl.target)}/{slug(cl.family + '-' + cl.signature, 70)}-{h}.html"


# ============================================================================ shared bits


def banner(ctx: SiteContext) -> str:
    if not ctx.preview:
        return ""
    return (
        '<div class="banner" role="note"><strong>Preview build.</strong> These results are not '
        "published. Library maintainers are notified before their row is published "
        "(DESIGN §6).</div>"
    )


def footer(ctx: SiteContext, path: str) -> str:
    corpus = sorted({str(v.get("corpus")) for s in ctx.sets for v in s.stats.version_sets() if v})
    return (
        "<p>"
        f"geotruth {esc(ctx.package_version)} · engine {esc(ctx.engine_version)}"
        + (f" · corpus {esc(', '.join(corpus))}" if corpus else "")
        + f" · tier {esc(ctx.tier)} · built {esc(ctx.generated)}</p>"
        "<p>A static site: no trackers, no cookies, no requests to other servers. "
        f"{a(rel(path, 'index.json'), 'Machine-readable index')} · "
        f"{ext(ctx.repo_url, 'Source')} · code MIT, corpus CC0.</p>"
    )


def page(ctx: SiteContext, path: str, title: str, desc: str, body: str, nav: str = "") -> Page:
    return Page(
        path,
        render_page(
            path=path,
            title=title,
            description=desc,
            body=body,
            nav_current=nav,
            footer=footer(ctx, path),
            banner=banner(ctx),
        ),
    )


def tierbar(cs: CapStats, label: str) -> str:
    total = sum(cs.tiers.get(t, 0) for t in TIERS)
    if not total:
        return ""
    parts = []
    for t in TIERS:
        n = cs.tiers.get(t, 0)
        if n:
            parts.append(f'<i class="t-{t}" style="width:{100 * n / total:.3f}%"></i>')
    desc = ", ".join(f"{TIER_NAMES[t]} {cs.tiers.get(t, 0)}" for t in TIERS)
    return (
        '<span class="tierbar" role="img" '
        f'aria-label="{esc(label)}: {esc(desc)}">{"".join(parts)}</span>'
    )


def na_text(cs: CapStats) -> str:
    """Why a capability has nothing graded."""
    if cs.total == 0:
        return "not reported"
    v = cs.verdicts
    top = max(
        ("unsupported", "not_reported", "engine_skipped", "engine_error"), key=lambda k: v.get(k, 0)
    )
    return {
        "unsupported": "not supported",
        "not_reported": "not reported",
        "engine_skipped": "engine abstained",
        "engine_error": "engine failed",
    }[top]


def predicates_offered(ss: ScoreSet) -> int | None:
    if ss.target is None:
        return None
    sup, der, _ = ss.target.fields()
    return sum(1 for p in PREDICATE_NAMES if f"predicates.{p}" in sup or f"predicates.{p}" in der)


def matrix_cell(ss: ScoreSet, cap: str, href: str) -> str:
    cs = ss.stats.cap(cap)
    name = CAPABILITY_NAMES[cap]
    if cs.graded == 0:
        return (
            f'<td class="na"><a class="cell" href="{esc(href)}"><span '
            f'class="none">{esc(na_text(cs))}</span></a></td>'
        )
    fails = cs.headline
    sub = f"of {fmt_count(cs.graded)} · {fmt_pct(fails, cs.graded)}"
    lines = []
    if cap in OVERLAY_CAPABILITIES:
        ht = cs.headline_tiers
        bits = [f"{ht[t]} {TIER_ABBR[t]}" for t in HEADLINE_TIERS if ht[t]]
        lines.append(tierbar(cs, f"{ss.library} {name} tiers"))
        if bits:
            lines.append(f'<span class="detail">{esc(" · ".join(bits))}</span>')
    else:
        err = cs.verdicts.get("error", 0)
        if err:
            lines.append(f'<span class="detail">{err} error{"s" if err != 1 else ""}</span>')
        conv = cs.verdicts.get("convention", 0)
        if conv:
            lines.append(f'<span class="detail">{conv} convention</span>')
        if cap == "predicates":
            k = predicates_offered(ss)
            if k is not None and 0 < k < 10:
                lines.append(f'<span class="detail">{k} of 10 predicates</span>')
    if cs.derived:
        lines.append(f'<span class="detail">+{cs.derived} derived</span>')
    cls = "bad" if fails else "ok"
    label = f"{ss.library} {ss.lib}, {name}: {fails} of {fmt_count(cs.graded)} graded answers fail"
    return (
        f'<td class="{cls}"><a class="cell" href="{esc(href)}" aria-label="{esc(label)}">'
        f'<span class="big">{fmt_count(fails)}</span><span class="of">{esc(sub)}</span>'
        f"{''.join(lines)}</a></td>"
    )


def echo_note(ss: ScoreSet) -> str:
    cs = ss.stats.cap("echo")
    if cs.total == 0:
        return ""  # the tier asks for no echo (the canary runs on its own cases)
    bad = cs.verdicts.get("wrong", 0) + cs.verdicts.get("error", 0)
    if cs.graded and not bad:
        return f'<span class="echo">parse-echo: passed ({fmt_count(cs.graded)})</span>'
    if bad:
        return f'<span class="echo warn">parse-echo: {bad} failed</span>'
    return f'<span class="echo">parse-echo: {esc(na_text(cs))}</span>'


def lib_row_head(ctx: SiteContext, ss: ScoreSet, path: str) -> str:
    role = ""
    if ss.target_id in ROLE_NOTES:
        role = ' <span class="tag">exact control</span>'
    return (
        f'<th scope="row">{a(rel(path, ctx.lib_path(ss.target_id)), esc(ss.library))}{role}'
        f'<span class="build">{esc(ss.lib)}</span>{echo_note(ss)}</th>'
    )


def matrix(ctx: SiteContext, path: str) -> str:
    caps = [*EXACT_CAPABILITIES, *OVERLAY_CAPABILITIES]
    head1 = (
        '<tr><th scope="col" rowspan="2" class="lib-col">Library and build</th>'
        '<th scope="colgroup" colspan="3" class="grp">Exact questions: wrong answers and '
        "errors</th>"
        '<th scope="colgroup" colspan="4" class="grp">Overlay: tiers 4-6 (gross, topological, '
        "exception)</th></tr>"
    )
    head2 = (
        "<tr>"
        + "".join(
            '<th scope="col"><abbr '
            f'title="{esc(CAPABILITY_NAMES[c])}">{esc(CAPABILITY_SHORT[c])}</abbr></th>'
            if CAPABILITY_SHORT[c] != CAPABILITY_NAMES[c]
            else f'<th scope="col">{esc(CAPABILITY_SHORT[c])}</th>'
            for c in caps
        )
        + "</tr>"
    )

    def rows(sets: list[ScoreSet]) -> str:
        out = []
        for ss in sets:
            lp = ctx.lib_path(ss.target_id)
            cells = "".join(
                matrix_cell(ss, c, rel(path, f"{lp}#{capability_anchor(c)}")) for c in caps
            )
            out.append(f"<tr>{lib_row_head(ctx, ss, path)}{cells}</tr>")
        return "".join(out)

    body = f"<tbody>{rows(ctx.libraries())}</tbody>"
    if ctx.controls():
        body += (
            '<tbody class="controls"><tr><th scope="rowgroup" colspan="8" class="grp-row">'
            "Harness controls (not libraries under test)</th></tr>"
            f"{rows(ctx.controls())}</tbody>"
        )
    return (
        '<div class="table-wrap" role="region" aria-labelledby="matrix-h" tabindex="0">'
        '<table class="matrix"><caption class="sr">Failures per library and capability on the '
        f"{esc(ctx.tier)} tier; each cell links to the details</caption>"
        f"<thead>{head1}{head2}</thead>{body}</table></div>"
    )


def tier_legend() -> str:
    items = "".join(
        f'<li><span class="sw t-{t}" aria-hidden="true"></span><strong>{TIER_NUMBER[t]}. '
        f"{esc(TIER_NAMES[t])}</strong> — {esc(TIER_TEXT[t])}</li>"
        for t in TIERS
    )
    return f'<ul class="tier-legend">{items}</ul>'


def run_dates(ctx: SiteContext) -> str:
    days = sorted({str(s.run.get("started", ""))[:10] for s in ctx.sets if s.run.get("started")})
    if not days:
        return "unknown dates (no run.json)"
    return days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"


def versions_table(ctx: SiteContext, path: str) -> str:
    rows = []
    for ss in ctx.libraries() + ctx.controls():
        m = ss.manifest
        commit = ss.run.get("library_commit") or m.get("commit") or ""
        started = str(ss.run.get("started", ""))
        rs = ss.run_stats
        cases = (
            f"{fmt_count(rs['cases_run'])} of {fmt_count(rs['cases_total'])}"
            if "cases_run" in rs and "cases_total" in rs
            else fmt_count(len(ss.stats.cases))
        )
        rows.append(
            f'<tr><th scope="row">{a(rel(path, ctx.lib_path(ss.target_id)), esc(ss.library))}</th>'
            f"<td>{code(ss.lib)}</td>"
            f"<td>{esc(m.get('version') or ss.run.get('library_version') or '')}</td>"
            f"<td>{commit_link(m.get('upstream', ''), commit) or '–'}</td>"
            f"<td>{esc(started.replace('T', ' ').replace('Z', ' UTC')) or '–'}</td><td "
            f'class="n">{cases}</td></tr>'
        )
    return (
        '<div class="table-wrap" role="region" aria-label="Versions tested" tabindex="0">'
        '<table class="plain"><thead><tr><th scope="col">Library</th><th scope="col">Build</th>'
        '<th scope="col">Version</th><th scope="col">Commit</th><th scope="col">Run started</th>'
        f'<th scope="col" class="n">Cases</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
        "</div>"
    )


def triage_counts(ctx: SiteContext) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ss in ctx.libraries():
        for cl in ss.stats.clusters.values():
            st = ctx.triage_status(ss.target_id, cl.key)
            counts[st] = counts.get(st, 0) + 1
    return counts


def version_warnings(ctx: SiteContext) -> list[str]:
    """Differences that make rows incomparable: corpus, expected answers, engine."""
    out = []
    for key, what in (
        ("corpus", "corpus versions"),
        ("expected", "expected answers"),
        ("engine", "engine versions"),
    ):
        vals = sorted(
            {str(v.get(key)) for s in ctx.sets for v in s.stats.version_sets() if v.get(key)}
        )
        if len(vals) > 1:
            out.append(
                f"The libraries were scored against different {what} ({', '.join(vals)}): rows "
                "are not directly comparable."
            )
    return out


# ============================================================================ index


def index_page(ctx: SiteContext) -> Page:
    path = "index.html"
    tc = triage_counts(ctx)
    total_clusters = sum(tc.values())
    confirmed = sum(tc.get(s, 0) for s in ("confirmed", "reported", "fixed"))
    tri = (
        ", ".join(f"{fmt_count(tc[s])} {s}" for s in (*TRIAGE_STATUSES, triage.MIXED) if tc.get(s))
        or "none"
    )
    cases = max((len(s.stats.cases) for s in ctx.sets), default=0)
    warn = "".join(f'<p class="warn-box" role="note">{esc(w)}</p>' for w in version_warnings(ctx))
    how = (
        '<ol class="three">'
        "<li>Every coordinate is an IEEE-754 double, and every double is a rational number "
        "m·2<sup>e</sup>, so every question about the input has exactly one right answer.</li>"
        "<li>geotruth scales each case to integers and decides every orientation, "
        "intersection and point location in exact integer arithmetic, with no tolerance "
        "anywhere in a decision.</li>"
        "<li>Answers are checked by independent implementations (two routes for DE-9IM, a "
        "certificate for overlay, CGAL's exact kernel as an outside control), and each "
        "library is graded only against what its own documentation promises.</li></ol>"
    )
    notes = (
        '<ul class="notes">'
        "<li><strong>The corpus is adversarial by design.</strong> Its cases sit on or within "
        "a few ulps of a degeneracy: vertices on edges, nearly collinear edges, parts touching "
        "at a point, coordinates as small as 1e-270 or as large as 1e270. The rates below say "
        "how a library handles such inputs. <strong>They are not real-world failure rates."
        "</strong></li>"
        "<li><strong>There is no single ranking.</strong> Libraries promise different things "
        "(exact predicates, a snapping grid, polygon-only clipping), are graded against their "
        "own documented precision, and many do not offer every capability. Rows are in "
        "alphabetical order; compare one column at a time, and read a library's page before "
        "comparing it with another.</li>"
        f"<li><strong>A disagreement is not a confirmed bug.</strong> Every failure cluster "
        f"takes its triage status from {ext(ctx.repo_file(ctx.registry_rel), ctx.registry_rel)}"
        " (by library, family and field; unreviewed when no entry matches). Of the "
        f"{fmt_count(total_clusters)} clusters of the libraries below ({esc(tri)}), "
        f"{fmt_count(confirmed)} {'matches' if confirmed == 1 else 'match'} an entry that is "
        "confirmed, reported or fixed; the rest are automated disagreements not yet triaged, "
        "or documented behaviour.</li>"
        "<li><strong>Exactly what was tested.</strong> Every row names its build: the version, "
        "and the commit where it was built from source (below). Results from runs on "
        f"{esc(run_dates(ctx))} (UTC), "
        f"{esc(ctx.tier)} tier, {fmt_count(cases)} cases.</li></ul>"
    )
    body = f"""
<section class="hero" aria-labelledby="top-h">
  <h1 id="top-h">geotruth <span class="tagline">exact answers for computational geometry</span></h1>
  <p class="lede">geotruth asks geometry libraries hard, near-degenerate questions (do these
  two polygons touch? what is their intersection? is this polygon valid?) and compares each
  answer with the true one, computed in exact arithmetic on the exact input.</p>
  <div class="cols">
    <div><h2 class="h3">How exactness works</h2>{how}</div>
    <div class="callout" role="note" aria-labelledby="read-h">
<h2 class="h3" id="read-h">Read this first</h2>{notes}</div>
  </div>
</section>
{warn}
<section aria-labelledby="matrix-h">
  <h2 id="matrix-h">Results by library and capability</h2>
  <p>Each cell counts the cases where the library's answer disagrees with the exact one
  (<em>wrong</em>) or where it failed (<em>error</em>), out of the cases it answered. Overlay
  output is graded in six tiers against the library's own documented precision; only tiers
  4-6 count here, and the bar shows all six. A dash means the library does not offer the
  capability or the adapter does not report it. Every cell links to the details.</p>
  {matrix(ctx, path)}
  <details class="legend-box"><summary>What the tiers and verdicts mean</summary>
  {tier_legend()}
  <p>A predicate answer derived from a wrong DE-9IM matrix is counted once, under relate
  (<em>derived</em>); an overlay the library computes from other overlays is likewise
  counted once. Answers that depend on the empty-geometry convention table are shown
  separately (<em>convention</em>) and never counted as wrong. Cases where the exact engine
  abstains are never counted against a library. See the
  {a("methodology.html#scoring", "methodology")}.</p></details>
</section>
<section aria-labelledby="versions-h">
  <h2 id="versions-h">Versions tested</h2>
  {versions_table(ctx, path)}
</section>
{controls_note(ctx)}
"""
    return page(
        ctx,
        path,
        "geotruth: exact answers for computational geometry",
        "How geometry libraries answer near-degenerate questions, compared with answers "
        "computed in exact arithmetic.",
        body,
        nav="index.html",
    )


def controls_note(ctx: SiteContext) -> str:
    items = [
        f"<li><strong>{esc(s.library)}</strong> "
        f"({code(s.target_id)}): {esc(CONTROLS[s.target_id])}</li>"
        for s in ctx.controls()
    ]
    items += [
        f"<li><strong>{esc(s.library)}</strong>: {esc(ROLE_NOTES[s.target_id])}</li>"
        for s in ctx.libraries()
        if s.target_id in ROLE_NOTES
    ]
    if not items:
        return ""
    return (
        '<section aria-labelledby="controls-h"><h2 id="controls-h">Controls</h2>'
        f"<ul>{''.join(items)}</ul></section>"
    )


# ============================================================================ library


def _delta_text(prec: dict[str, Any]) -> str:
    d = prec.get("delta") or {"kind": "undocumented"}
    kind = d.get("kind", "undocumented")
    v = d.get("value")
    if kind == "relative":
        return f"δ = {esc(v)} × M, M the largest absolute input ordinate of the case"
    if kind == "ulp":
        return f"δ = {esc(v)} × ulp(M), M the largest absolute input ordinate of the case"
    if kind == "absolute":
        return f"δ = {esc(v)}"
    if kind == "grid":
        return f"δ = {esc(v)} grid steps; the grid step: {esc(prec.get('grid', ''))}"
    return (
        "none documented: overlay output can be graded only as exact, within rounding, or "
        "failing (tiers 1, 2 and 4-6)"
    )


def library_page(ctx: SiteContext, ss: ScoreSet) -> Page:
    path = ctx.lib_path(ss.target_id)
    m = ss.manifest
    run = ss.run
    rs = ss.run_stats
    prec = m.get("precision") or {}
    coords = m.get("coordinates") or {}
    commit = run.get("library_commit") or m.get("commit") or ""
    opts = m.get("options") or []
    adapter = run.get("adapter") or {}
    vs = ss.stats.version_sets()
    v0 = vs[0] if vs else {}
    warnings = []
    if len(vs) > 1:
        warnings.append(
            f"The score records carry {len(vs)} different version sets; the most common is shown."
        )
    if len(ss.stats.libs) > 1:
        warnings.append(
            "The score records name more than one build: " + ", ".join(sorted(ss.stats.libs))
        )
    if ss.stats.scorer_failures:
        warnings.append(
            f"The scorer failed on {ss.stats.scorer_failures} records (a harness bug; those "
            "records count as engine errors, never against the library)."
        )
    if ss.target is None:
        warnings.append("No adapter manifest was found for this target.")
    if ss.results_path is None:
        warnings.append(
            "The library's result lines were not found, so examples show the score records only."
        )
    role = ""
    if ss.target_id in CONTROLS:
        role = f'<p class="warn-box" role="note">{esc(CONTROLS[ss.target_id])}</p>'
    elif ss.target_id in ROLE_NOTES:
        role = f'<p class="note-box" role="note">{esc(ROLE_NOTES[ss.target_id])}</p>'

    health = []
    for key, label in (
        ("watchdog_timeouts", "watchdog timeouts"),
        ("adapter_restarts", "adapter restarts"),
        ("early_exits", "early exits"),
        ("invalid_lines", "invalid result lines"),
        ("id_mismatches", "id mismatches"),
    ):
        if key in rs:
            health.append(f"{rs[key]} {label}")
    if rs.get("budget_exhausted"):
        health.append("the wall-clock budget ran out")
    build = dl(
        [
            (
                "Library",
                esc(ss.library)
                + (" · " + ext(m["upstream"], "upstream") if m.get("upstream") else ""),
            ),
            ("Build scored", code(ss.lib)),
            ("Version", esc(m.get("version") or run.get("library_version") or "")),
            ("Commit", commit_link(m.get("upstream", ""), commit)),
            ("Toolchain", esc(m.get("toolchain", ""))),
            (
                "Departures from the library's defaults",
                "<ul>" + "".join(f"<li>{esc(o)}</li>" for o in opts) + "</ul>" if opts else "none",
            ),
            (
                "Adapter",
                a(ctx.repo_file(f"adapters/{ss.target.dir}/"), code(f"adapters/{ss.target.dir}/"))
                + f" (contract {esc(ss.target.contract)})"
                if ss.target is not None
                else "",
            ),
            (
                "Adapter commit",
                code(short_sha(str(adapter.get("git_sha", "")), 12))
                if adapter.get("git_sha")
                else "",
            ),
            (
                "Manifest sha256",
                code(str(adapter.get("manifest_sha256", ""))[:16] + "…")
                if adapter.get("manifest_sha256")
                else "",
            ),
            (
                "Run",
                esc(f"{run.get('started', '?')} to {run.get('finished', '?')}")
                if run.get("started")
                else "no run.json",
            ),
            ("Runner", esc(run.get("runner_image", ""))),
            (
                "Cases",
                esc(f"{rs.get('cases_run')} of {rs.get('cases_total')} run")
                if "cases_run" in rs
                else esc(f"{len(ss.stats.cases)} with score records"),
            ),
            ("Run health", esc(", ".join(health)) if health else ""),
            ("Tier", esc(ss.tier)),
            ("Corpus", esc(v0.get("corpus", run.get("corpus_version", "")))),
            ("Exact answers", expected_label(str(v0.get("expected", "")))),
            ("Engine", esc(v0.get("engine", run.get("engine_version", "")))),
        ]
    )
    tol = prec.get("tolerances") or []
    precision = dl(
        [
            ("Precision model", esc(prec.get("model", "not stated in the manifest"))),
            ("Displacement budget δ_lib", _delta_text(prec)),
            (
                "Tolerance-based predicates",
                ("yes" if prec.get("tolerance_predicates") else "no")
                + ("<ul>" + "".join(f"<li>{esc(t)}</li>" for t in tol) + "</ul>" if tol else ""),
            ),
            ("Coordinate range", esc(coords.get("range", ""))),
            ("Beyond the range", esc(coords.get("out_of_range", ""))),
        ]
    )
    manifest_name = code(f"adapters/{ss.target.dir}/adapter.toml") if ss.target else "none"
    cap_sections = "".join(
        capability_section(ctx, ss, path, c)
        for c in CAPABILITIES
        if ss.stats.cap(c).total or c != "echo"
    )
    body = f"""
<nav class="crumbs" aria-label="Breadcrumb">{a(rel(path, "index.html"), "Scoreboard")}
/ {esc(ss.library)}</nav>
<h1>{esc(ss.library)} <span class="build">{esc(ss.lib)}</span></h1>
{role}
{"".join(f'<p class="warn-box" role="note">{esc(w)}</p>' for w in warnings)}
<nav class="toc" aria-label="On this page"><a href="#build">Build and run</a>
<a href="#precision">Precision model</a><a href="#fields">What is graded</a>
<a href="#capabilities">Results by capability</a><a href="#families">Results by family</a>
<a href="#registry">Known behaviours</a></nav>
<section id="build" aria-labelledby="build-h"><h2 id="build-h">Build and run</h2>{build}</section>
<section id="precision" aria-labelledby="precision-h">
<h2 id="precision-h">Precision model and budget</h2>
<p>From the adapter manifest ({manifest_name}).
Overlay output is graded against this budget (tier 3); predicates and relate are exact
questions whatever the model.</p>{precision}</section>
<section id="fields" aria-labelledby="fields-h">
<h2 id="fields-h">What is graded</h2>{fields_table(ss)}</section>
<section id="capabilities" aria-labelledby="caps-h"><h2 id="caps-h">Results by capability</h2>
{cap_sections}
</section>
<section id="families" aria-labelledby="fam-h"><h2 id="fam-h">Results by family</h2>
<p>Failures (tiers 4-6 for overlay) out of the answers graded, per corpus family. A cell with
a single failure cluster links to it.</p>{family_table(ctx, ss, path)}</section>
<section id="registry" aria-labelledby="reg-h"><h2 id="reg-h">Known behaviours and findings</h2>
{registry_for(ctx, ss, path)}</section>
"""
    return page(
        ctx,
        path,
        f"{ss.library} ({ss.lib}) · geotruth",
        f"geotruth results for {ss.library} {ss.lib}: exact questions and overlay tiers.",
        body,
    )


def fields_table(ss: ScoreSet) -> str:
    if ss.target is None:
        return "<p>No manifest: the fields are not documented.</p>"
    sup, der, uns = ss.target.fields()
    groups = [
        ("echo", ["echo"]),
        ("relate", ["relate"]),
        ("predicates", [f"predicates.{p}" for p in PREDICATE_NAMES]),
        ("validity", ["valid_a", "valid_b"]),
        *((c, [c]) for c in OVERLAY_CAPABILITIES),
    ]
    rows = []
    for cap, paths in groups:
        by: dict[str, list[str]] = {}
        hows = []
        for p in paths:
            if p in der:
                st = "derived"
                hows.append(
                    f"{code(p.split('.', 1)[-1] if cap == 'predicates' else p)}: {esc(der[p])}"
                )
            elif p in sup:
                st = "supported"
            elif p in uns:
                st = "unsupported"
            else:
                st = "not listed"
            by.setdefault(st, []).append(p)
        cells = []
        for st in ("supported", "derived", "unsupported", "not listed"):
            ps = by.get(st)
            if not ps:
                continue
            if len(paths) == 1:
                cells.append(badge(st))
            elif len(ps) == len(paths):
                cells.append(f"{badge(st)} all")
            else:
                names = ", ".join(p.split(".", 1)[-1].replace("_", " ") for p in ps)
                cells.append(f"{badge(st)} {esc(names)}")
        how = "<br>".join(hows)
        rows.append(
            f'<tr><th scope="row">{esc(CAPABILITY_NAMES[cap])}</th><td>{"<br>".join(cells)}</td>'
            f'<td class="small">{how}</td></tr>'
        )
    return (
        "<p>From the manifest: a <em>supported</em> field comes from a library call of its own; a "
        "<em>derived</em> one is computed from other calls and never counted twice; an "
        "<em>unsupported</em> one is always null.</p>"
        '<div class="table-wrap" role="region" aria-label="Fields" tabindex="0"><table '
        'class="plain">'
        '<thead><tr><th scope="col">Capability</th><th scope="col">Fields</th><th '
        'scope="col">How derived fields are computed</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def verdict_table(cs: CapStats) -> str:
    head = "".join(
        '<th scope="col" class="n"><abbr '
        f'title="{esc(VERDICT_TEXT[v])}">{esc(VERDICT_NAMES[v])}</abbr></th>'
        for v in VERDICTS
    )
    cells = "".join(f'<td class="n">{fmt_count(cs.verdicts.get(v, 0))}</td>' for v in VERDICTS)
    return (
        '<div class="table-wrap" role="region" aria-label="Verdicts" tabindex="0"><table '
        'class="plain">'
        f"<thead><tr>{head}</tr></thead><tbody><tr>{cells}</tr></tbody></table></div>"
    )


def tier_table(cs: CapStats) -> str:
    head = "".join(
        f'<th scope="col" class="n"><span class="sw t-{t}" aria-hidden="true">'
        f"</span>{TIER_NUMBER[t]}. {esc(TIER_NAMES[t])}</th>"
        for t in TIERS
    )
    cells = "".join(f'<td class="n">{fmt_count(cs.tiers.get(t, 0))}</td>' for t in TIERS)
    return (
        '<div class="table-wrap" role="region" aria-label="Overlay tiers" tabindex="0"><table '
        'class="plain">'
        f"<thead><tr>{head}</tr></thead><tbody><tr>{cells}</tr></tbody></table></div>"
    )


def cluster_list(
    ctx: SiteContext, ss: ScoreSet, path: str, clusters: list[Cluster], first: int = 12
) -> str:
    """A table of clusters, largest first; beyond ``first`` rows the rest is behind a
    disclosure."""
    if not clusters:
        return ""
    if len(clusters) > first + 3:
        rest = clusters[first:]
        return (
            cluster_list(ctx, ss, path, clusters[:first], first)
            + f'<details class="more"><summary>The other {len(rest)} clusters</summary>'
            + cluster_list(ctx, ss, path, rest, len(rest))
            + "</details>"
        )
    rows = []
    for cl in clusters:
        st = ctx.triage_status(ss.target_id, cl.key)
        href = rel(path, ctx.cluster_path[(ss.target_id, cl.key)])
        rows.append(
            f"<tr><td>{esc(cl.family)}</td>"
            f"<td>{a(href, esc(explain_signature(cl.signature, cl.capability)))}</td>"
            f'<td class="n">{fmt_count(cl.count)}</td><td>{badge(st)}</td></tr>'
        )
    return (
        '<div class="table-wrap" role="region" aria-label="Failure clusters" tabindex="0">'
        '<table class="plain clusters"><thead><tr><th scope="col">Family</th><th '
        'scope="col">Failure cluster</th>'
        '<th scope="col" class="n">Cases</th><th scope="col"><abbr title="the status of the '
        "registry entry matched to the cluster by library, family and field; unreviewed when "
        'none matches">Triage</abbr></th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def capability_section(ctx: SiteContext, ss: ScoreSet, path: str, cap: str) -> str:
    cs = ss.stats.cap(cap)
    anchor = capability_anchor(cap)
    name = CAPABILITY_NAMES[cap]
    clusters = [c for c in ss.stats.sorted_clusters() if c.capability == cap]
    if cs.graded:
        lead = (
            f'<p class="stat"><span class="big">{fmt_count(cs.headline)}</span> failures out of '
            f"{fmt_count(cs.graded)} graded ({fmt_pct(cs.headline, cs.graded)})"
            + (
                f"; {cs.derived} more derived from another failing answer of the same case"
                if cs.derived
                else ""
            )
            + ".</p>"
        )
    else:
        lead = f'<p class="stat">Nothing graded: {esc(na_text(cs))}.</p>'
    parts = [
        f'<section id="{anchor}" class="cap" aria-labelledby="{anchor}-h"><h3 '
        f'id="{anchor}-h">{esc(name)}</h3>',
        f"<p>{esc(sentence(CAPABILITY_TEXT[cap]))}.</p>",
        lead,
    ]
    if cs.tiers:
        parts.append(tierbar(cs, f"{name} tiers"))
        parts.append(tier_table(cs))
        if cs.exact_but_invalid:
            parts.append(
                f"<p>Of the {fmt_count(cs.tiers.get('topological', 0))} topological results, "
                f"{fmt_count(cs.exact_but_invalid)} cover exactly the right point set: they fail "
                "only because the output is not valid OGC geometry (for example a ring that "
                "touches itself, or holes that cut the interior apart).</p>"
            )
    if cs.total:
        parts.append(verdict_table(cs))
    if clusters:
        parts.append(f"<h4>Failure clusters ({len(clusters)})</h4>")
        parts.append(cluster_list(ctx, ss, path, clusters))
    parts.append("</section>")
    return "".join(parts)


def family_table(ctx: SiteContext, ss: ScoreSet, path: str) -> str:
    caps = [c for c in (*EXACT_CAPABILITIES, *OVERLAY_CAPABILITIES) if ss.stats.cap(c).graded]
    if not caps:
        return "<p>Nothing graded.</p>"
    head = "".join(f'<th scope="col" class="n">{esc(CAPABILITY_SHORT[c])}</th>' for c in caps)
    rows = []
    by_fc: dict[tuple[str, str], list[Cluster]] = {}
    for cl in ss.stats.clusters.values():
        by_fc.setdefault((cl.family, cl.capability), []).append(cl)
    for fam in sorted(ss.stats.families):
        caps_f = ss.stats.families[fam]
        cells = []
        for c in caps:
            cs = caps_f.get(c)
            if cs is None or not cs.graded:
                cells.append('<td class="n na">–</td>')
                continue
            text = f'{cs.headline}<span class="of"> / {cs.graded}</span>'
            cls = "n bad" if cs.headline else "n"
            cl = by_fc.get((fam, c), [])
            if len(cl) == 1:
                text = a(rel(path, ctx.cluster_path[(ss.target_id, cl[0].key)]), text)
            elif cl:
                text = a(f"#{capability_anchor(c)}", text)
            cells.append(f'<td class="{cls}">{text}</td>')
        desc = FAMILY_TEXT.get(fam, "")
        title = f' title="{esc(desc)}"' if desc else ""
        rows.append(f'<tr><th scope="row"{title}>{esc(fam)}</th>{"".join(cells)}</tr>')
    return (
        '<div class="table-wrap" role="region" aria-label="Results by family" tabindex="0">'
        f'<table class="plain fam"><thead><tr><th scope="col">Family</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def registry_for(ctx: SiteContext, ss: ScoreSet, path: str) -> str:
    if ctx.registry_problem:
        return f"<p>The registry could not be read: {esc(ctx.registry_problem)}.</p>"
    entries = [e for e in ctx.registry if ss.target_id in triage.libraries(e)]
    if not entries:
        return (
            f"<p>{ext(ctx.repo_file(ctx.registry_rel), ctx.registry_rel)} has no entry for this "
            "library, so every failure cluster above is unreviewed: an automated disagreement, "
            "not a confirmed bug.</p>"
        )
    order = {
        s: i for i, s in enumerate(("by-design", "confirmed", "reported", "fixed", "unreviewed"))
    }
    entries.sort(key=lambda e: (order.get(e.get("status", ""), 9), e["id"]))
    items = []
    for e in entries:
        href = rel(path, f"findings.html#{finding_anchor(e['id'])}")
        kind = " (lead)" if e.get("kind") == "lead" else ""
        items.append(
            f"<li>{badge(e.get('status', 'unreviewed'))} {a(href, code(e['id']))}{kind}: "
            f"{esc(e.get('signature', ''))}</li>"
        )
    return (
        "<p>Entries of the triage registry for this library. Documented behaviour is recorded "
        "as <em>by-design</em> and not counted as a bug.</p>"
        f'<ul class="reg">{"".join(items)}</ul>'
    )


# ============================================================================ cluster


def invalid_note(cl: Cluster) -> str:
    """For a topological overlay cluster: how many outputs are invalid geometry, and how many
    of those still cover exactly the right point set."""
    if not cl.capability.startswith("overlay.") or not cl.signature.endswith(":topological"):
        return ""
    invalid = [r for r in cl.records if (r.get("metrics") or {}).get("output_valid") is False]
    if not invalid:
        return "every output is valid; each misses or adds a component or a hole"
    exact = sum(1 for r in cl.records if is_exact_but_invalid(r))
    reasons = Counter((r.get("metrics") or {}).get("output_reason") or "?" for r in invalid)
    why = ", ".join(f"{k.replace('_', ' ')} ({n})" for k, n in reasons.most_common())
    text = (
        f"{fmt_count(len(invalid))} of {fmt_count(cl.count)} outputs are not valid OGC "
        f"geometry ({esc(why)})"
    )
    if exact:
        text += (
            f"; {fmt_count(exact)} of them cover exactly the right point set, so they fail on "
            "the representation, not on the geometry"
        )
    return text


def describe(cl: Cluster) -> str:
    return explain_signature(cl.signature, cl.capability)


def finding_anchor(fid: str) -> str:
    return "f-" + slug(fid, 80)


def cluster_page(ctx: SiteContext, ss: ScoreSet, cl: Cluster) -> Page:
    path = ctx.cluster_path[(ss.target_id, cl.key)]
    found = ctx.cluster_matches.get((ss.target_id, cl.key), [])
    st = triage.status(found)
    lp = ctx.lib_path(ss.target_id)
    name = CAPABILITY_NAMES.get(cl.capability, cl.capability)
    expl = explain_signature(cl.signature, cl.capability)
    examples = ctx.examples.get((ss.target_id, cl.key), [])
    if found:
        tri_items = []
        for e in found:
            href = rel(path, f"findings.html#{finding_anchor(e['id'])}")
            extra = []
            if e.get("upstream_issue"):
                extra.append(ext(e["upstream_issue"], "upstream issue"))
            if e.get("fixed_in"):
                extra.append("fixed in " + esc(e["fixed_in"]))
            if e.get("evidence"):
                extra.append(ext(ctx.repo_file(e["evidence"]), "evidence"))
            tri_items.append(
                f"<li>{badge(e.get('status', 'unreviewed'))} {a(href, code(e['id']))} "
                + (f"(triaged on {code(e['lib'])})" if e.get("lib") else "")
                + f": {esc(e.get('signature', ''))}"
                + (f" · {' · '.join(extra)}" if extra else "")
                + (f'<p class="small">{esc(e["notes"])}</p>' if e.get("notes") else "")
                + "</li>"
            )
        triage_html = (
            f"<p>{badge(st)} The status of the registry "
            f"{'entry' if len(found) == 1 else 'entries'} matched to this cluster: "
            f"{esc(TRIAGE_TEXT.get(st, MIXED_TEXT))}.</p>"
            "<p>The match is by library, family and field, so it names a candidate "
            "explanation: compare the entry's signature with the cluster's examples below.</p>"
            f'<ul class="reg">{"".join(tri_items)}</ul>'
        )
    else:
        triage_html = (
            f"<p>{badge('unreviewed')} No entry of "
            f"{ext(ctx.repo_file(ctx.registry_rel), ctx.registry_rel)} matches this cluster "
            "(by library, family and field). It is an automated disagreement with the exact "
            "answer, not a confirmed bug: it has not been triaged by a person.</p>"
        )
    facts = dl(
        [
            ("Library", a(rel(path, lp), esc(ss.library)) + " " + code(ss.lib)),
            ("Capability", a(rel(path, f"{lp}#{capability_anchor(cl.capability)}"), esc(name))),
            (
                "Family",
                esc(cl.family)
                + (
                    f' <span class="small">({esc(FAMILY_TEXT[cl.family])})</span>'
                    if cl.family in FAMILY_TEXT
                    else ""
                ),
            ),
            ("Signature", code(cl.signature)),
            (
                "Cluster key",
                code(cl.key)
                + (
                    ' <span class="small">(grouped by the site: the scorer gives error records of '
                    "this capability no cluster key)</span>"
                    if cl.key_source == "site"
                    else ""
                ),
            ),
            ("Cases", f"{fmt_count(len(cl.case_ids))} ({fmt_count(cl.count)} score records)"),
            ("Output validity", invalid_note(cl)),
        ]
    )
    ex_html = "".join(example_html(ctx, ss, path, ex, i + 1) for i, ex in enumerate(examples))
    all_ids = cl.case_ids
    shown = all_ids[:400]
    more = (
        f"<li>… and {len(all_ids) - len(shown)} more (see index.json)</li>"
        if len(all_ids) > len(shown)
        else ""
    )
    ids = (
        f'<details class="ids"><summary>All {fmt_count(len(all_ids))} cases of this '
        "cluster</summary>"
        f'<ul class="idlist">{"".join(f"<li>{code(i)}</li>" for i in shown)}{more}</ul></details>'
    )
    title_ex = (
        f"Examples ({len(examples)} of {fmt_count(len(all_ids))}, smallest first)"
        if len(examples) < len(all_ids)
        else f"Examples ({len(examples)})"
    )
    cap_href = f"{lp}#{capability_anchor(cl.capability)}"
    body = f"""
<nav class="crumbs" aria-label="Breadcrumb">{a(rel(path, "index.html"), "Scoreboard")} /
{a(rel(path, lp), esc(ss.library))} / {a(rel(path, cap_href), esc(name))}</nav>
<h1>{esc(ss.library)}: {esc(name)} on {esc(cl.family)}</h1>
<p class="lede">{esc(sentence(expl))}.</p>
{facts}
<section aria-labelledby="triage-h" class="triage">
<h2 id="triage-h">Triage status</h2>{triage_html}</section>
<section aria-labelledby="ex-h"><h2 id="ex-h">{esc(title_ex)}</h2>
<p>Each example shows the exact inputs, the exact answer next to the library's, figures zoomed
to where they differ (with the exact coordinates of the numbered vertices), an independent
re-check of the exact answer, and commands that reproduce both answers.</p>
{ex_html or "<p>No examples could be built.</p>"}
{ids}
</section>
"""
    return page(
        ctx,
        path,
        f"{ss.library}: {name} on {cl.family} · geotruth",
        f"{ss.library} {ss.lib}: {expl} ({cl.count} records, family {cl.family}).",
        body,
    )


def _tags(tags: dict[str, Any]) -> str:
    bits = []
    for k in ("degeneracy", "range"):
        if tags.get(k):
            bits.append(f"{k} {tags[k]}")
    if tags.get("types"):
        bits.append(" / ".join(str(t) for t in tags["types"]))
    if tags.get("n") is not None:
        bits.append(f"{tags['n']} vertices")
    if tags.get("variant"):
        bits.append(f"variant {tags['variant']}")
    if tags.get("flags"):
        bits.append("flags " + ", ".join(tags["flags"]))
    return " · ".join(esc(b) for b in bits)


def example_html(ctx: SiteContext, ss: ScoreSet, path: str, ex: Example, i: int) -> str:
    aid = f"ex-{i}"
    checks = ""
    if ex.checks:
        items = "".join(
            '<li class="chk '
            f'chk-{c.status}">{badge("check-" + c.status, CHECK_LABEL[c.status])} {c.text}</li>'
            for c in ex.checks
        )
        checks = f'<h4>Independent re-check</h4><ul class="checks">{items}</ul>'
    inputs = ""
    if ex.wkt_a is not None:
        long = len(ex.wkt_a) + len(ex.wkt_b or "") > 1200
        inputs = (
            f'<details class="inputs"{"" if long else " open"}><summary>Exact inputs (WKT; every '
            "coordinate is the shortest decimal that reads back as the same double)</summary>"
            f'<p class="small">A</p>{pre(ex.wkt_a)}<p '
            f'class="small">B</p>{pre(ex.wkt_b or "")}</details>'
        )
    outputs = ""
    if ex.wkt_exact is not None or ex.wkt_lib is not None:
        outputs = (
            '<details class="inputs"><summary>Overlay outputs (WKT)</summary>'
            + (
                '<p class="small">Exact result, display only: its vertices are rationals, rounded '
                f"here to doubles (never score against this text)</p>{pre(ex.wkt_exact)}"
                if ex.wkt_exact is not None
                else ""
            )
            + (
                f'<p class="small">Library output</p>{pre(ex.wkt_lib)}'
                if ex.wkt_lib is not None
                else ""
            )
            + "</details>"
        )
    repro = ""
    if ex.repro:
        repro = (
            '<h4>Reproduce</h4><p class="small">From the root of a geotruth checkout.</p>'
            + "".join(
                f'<p class="small">{esc(sentence(c))}:</p>{pre(cmd, "cmd")}' for c, cmd in ex.repro
            )
        )
    notes = "".join(f'<p class="note">{esc(n)}</p>' for n in ex.notes)
    figs = []
    for j, f in enumerate(ex.figures):
        figs.append(
            f'<figure class="figure" id="{aid}-fig{j + 1}"><div class="svgbox">{f.svg}</div>'
            "<figcaption>"
            f"<strong>{esc(f.title)}.</strong> {f.caption}{legend(f.roles)}</figcaption>"
            f"{markers_table(f)}</figure>"
        )
    return f"""
<article class="example" id="{aid}" aria-labelledby="{aid}-h">
<h3 id="{aid}-h"><span class="exn">{i}</span>{code(ex.case_id)}</h3>
<p class="tags">{_tags(ex.rec.get("tags") or {})}</p>
<div class="ex-grid">
<div class="ex-text">
<h4>Exact answer and the library's</h4>
{ex.comparison}
{checks}
{inputs}{outputs}
{repro}
{notes}
</div>
<div class="ex-figs">{"".join(figs)}</div>
</div>
</article>"""


# ============================================================================ findings


def findings_page(ctx: SiteContext) -> Page:
    path = "findings.html"
    known = {s.target_id for s in ctx.sets}
    back: dict[str, list[tuple[str, Cluster]]] = {}
    for (target, key), ents in ctx.cluster_matches.items():
        ss = next(s for s in ctx.sets if s.target_id == target)
        cl = ss.stats.clusters[key]
        for e in ents:
            back.setdefault(e["id"], []).append((ctx.cluster_path[(target, key)], cl))
    findings = [e for e in ctx.registry if e.get("kind") != "lead"]
    leads = [e for e in ctx.registry if e.get("kind") == "lead"]
    if ctx.registry_problem:
        body_items = f"<p>The registry could not be read: {esc(ctx.registry_problem)}.</p>"
    else:
        groups = []
        order = ("confirmed", "reported", "fixed", "by-design", "unreviewed")
        for st in order:
            ents = sorted(
                (e for e in findings if e.get("status", "unreviewed") == st), key=lambda e: e["id"]
            )
            if not ents:
                continue
            cards = "".join(finding_card(ctx, path, e, known, back.get(e["id"], [])) for e in ents)
            groups.append(
                f'<section aria-labelledby="st-{st}"><h2 id="st-{st}">{badge(st)} '
                f'<span class="cnt">{len(ents)}</span></h2>'
                f"<p>{esc(sentence(TRIAGE_TEXT[st]))}.</p>{cards}</section>"
            )
        other = sorted({str(e.get("status")) for e in findings} - set(order))
        if other:
            groups.append(f"<p>Entries with an unknown status: {esc(', '.join(other))}.</p>")
        if leads:
            cards = "".join(
                finding_card(ctx, path, e, known, back.get(e["id"], []))
                for e in sorted(leads, key=lambda e: e["id"])
            )
            groups.append(
                '<section aria-labelledby="leads-h"><h2 id="leads-h">Leads '
                f'<span class="cnt">{len(leads)}</span></h2><p>Documented candidate clusters '
                "that have no findings directory yet. None has been triaged by a person; each is "
                "registered by its signature only, so the site does not match it to clusters "
                f"automatically.</p>{cards}</section>"
            )
        body_items = "".join(groups) or "<p>The registry has no entries yet.</p>"
    counts = {s: sum(1 for e in findings if e.get("status") == s) for s in TRIAGE_STATUSES}
    summary = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "no findings"
    if leads:
        summary += f"; and {len(leads)} unreviewed lead{'s' if len(leads) != 1 else ''}"
    body = f"""
<h1>Findings</h1>
<p class="lede">The triage registry ({ext(ctx.repo_file(ctx.registry_rel), ctx.registry_rel)}):
the failure clusters a person has looked at, with their status: {esc(summary)}.</p>
<p>Before anything is called a bug, it is reproduced on the library's latest development code,
minimised, checked by an independent skeptic, and searched for in the upstream tracker.
Documented behaviour is recorded as <em>by-design</em> and not reported. A failure cluster
with no entry here is <em>unreviewed</em>.</p>
{body_items}
"""
    return page(
        ctx,
        path,
        "Findings · geotruth",
        "Triaged geometry-library findings: confirmed, reported, fixed and by-design.",
        body,
        nav=path,
    )


def finding_card(
    ctx: SiteContext, path: str, e: dict[str, Any], known: set[str], back: list[tuple[str, Cluster]]
) -> str:
    libs = triage.libraries(e)
    lib_html = ", ".join(
        a(rel(path, ctx.lib_path(lib)), code(lib)) if lib in known else code(lib) for lib in libs
    )
    links = e.get("links") or []
    files = []
    for key, label in (
        ("evidence", "write-up"),
        ("cases", "minimal cases"),
        ("repro", "standalone reproducer"),
        ("source", "source of the lead"),
    ):
        if isinstance(e.get(key), str) and e[key]:
            files.append(ext(ctx.repo_file(e[key]), label))
    verified = e.get("verified_on") or []
    facts = dl(
        [
            ("Library", lib_html + (" · triaged on " + code(e["lib"]) if e.get("lib") else "")),
            ("Signature", esc(e.get("signature", ""))),
            ("Fields", ", ".join(code(f) for f in e.get("fields") or [])),
            ("Families", ", ".join(code(f) for f in e.get("families") or [])),
            ("Status since", esc(e.get("status_date", ""))),
            ("Priority", esc(e.get("priority", ""))),
            (
                "Verified on",
                "<ul>" + "".join(f"<li>{esc(v)}</li>" for v in verified) + "</ul>"
                if verified
                else "",
            ),
            (
                "Upstream issue",
                ext(e["upstream_issue"], esc(e["upstream_issue"]))
                if e.get("upstream_issue")
                else "",
            ),
            ("Fixed in", esc(e.get("fixed_in", ""))),
            ("Files", " · ".join(files)),
            (
                "Links",
                "<ul>" + "".join(f"<li>{ext(u, esc(u))}</li>" for u in links) + "</ul>"
                if links
                else "",
            ),
        ]
    )
    notes = f'<p class="note">{esc(e["notes"])}</p>' if e.get("notes") else ""
    bl = ""
    if back:
        items = "".join(
            f"<li>{a(rel(path, p), esc(cl.family + ': ' + describe(cl)))} ({cl.count})</li>"
            for p, cl in sorted(back, key=lambda t: t[1].key)
        )
        bl = (
            "<h4>Clusters on this site matched to it (by library, family and field)</h4>"
            f"<ul>{items}</ul>"
        )
    fid = finding_anchor(e["id"])
    return (
        f'<article class="finding" id="{fid}" aria-labelledby="{fid}-h"><h3 id="{fid}-h">'
        f"{code(e['id'])} {badge(e.get('status', 'unreviewed'))}</h3>{facts}{notes}{bl}</article>"
    )


# ============================================================================ methodology


def methodology_page(ctx: SiteContext) -> Page:
    path = "methodology.html"
    tiers = "".join(
        f'<tr><th scope="row"><span class="sw t-{t}" aria-hidden="true">'
        f"</span>{TIER_NUMBER[t]}</th>"
        f"<td>{esc(TIER_NAMES[t])}</td><td>{esc(TIER_TEXT[t])}</td>"
        f"<td>{'counted' if t in HEADLINE_TIERS else 'correct'}</td></tr>"
        for t in TIERS
    )
    verdicts = "".join(
        f'<tr><th scope="row">{esc(VERDICT_NAMES[v])}</th><td>{esc(VERDICT_TEXT[v])}</td></tr>'
        for v in VERDICTS
    )
    body = template("methodology.html").substitute(
        tiers_rows=tiers,
        verdict_rows=verdicts,
        engine_version=esc(ctx.engine_version),
        design=ext(ctx.repo_file("docs/DESIGN.md"), "docs/DESIGN.md"),
        adapters_readme=ext(ctx.repo_file("adapters/README.md"), "adapters/README.md"),
        registry=ext(ctx.repo_file(ctx.registry_rel), ctx.registry_rel),
        schemas=ext(ctx.repo_file("schemas/"), "schemas/"),
        corpus=ext(ctx.repo_file("corpus/README.md"), "corpus/README.md"),
        expected_note=expected_note(ctx),
    )
    return page(
        ctx,
        path,
        "Methodology · geotruth",
        "How geotruth computes exact answers and grades geometry libraries.",
        body,
        nav=path,
    )


def expected_label(v: str) -> str:
    """HTML naming the exact answers a library was graded against."""
    if not v:
        return ""
    if v.startswith("computed-"):
        engine = esc(v.removeprefix("computed-"))
        return f"computed by the scorer with engine {engine} ({code(v)})"
    return f"release {esc(v)} of the published exact answers ({code('corpus/expected/')})"


def expected_note(ctx: SiteContext) -> str:
    vals = sorted(
        {
            str(v.get("expected"))
            for s in ctx.sets
            for v in s.stats.version_sets()
            if v.get("expected")
        }
    )
    if not vals:
        return "<p>The score records do not say which exact answers they were graded against.</p>"
    text = (
        "<p>The results on this site were graded against these exact answers: "
        f"{'; '.join(expected_label(v) for v in vals)}. "
    )
    if any(v.startswith("computed-") for v in vals):
        text += (
            "Answers computed by the scorer come from the arrangement route with its built-in "
            "assertions; the witness route and the overlay certificate do not run at scoring "
            "time. "
        )
    if any(not v.startswith("computed-") for v in vals):
        text += (
            "In a published release (made by <code>geotruth expect</code>), every matrix was "
            "computed by both routes, which had to agree, and every overlay result passed the "
            "certificate. "
        )
    text += (
        "Either way, each example on a failure page is re-checked by the second route when the "
        "site is built, and the page shows the outcome."
    )
    return text + "</p>"


# ============================================================================ JSON index


def index_json(ctx: SiteContext, report: dict[str, Any]) -> dict[str, Any]:
    libs = []
    for ss in ctx.sets:
        libs.append(
            {
                "target": ss.target_id,
                "library": ss.library,
                "lib": ss.lib,
                "control": ss.target_id in CONTROLS,
                "page": ctx.lib_path(ss.target_id),
                "version": ss.manifest.get("version"),
                "commit": ss.run.get("library_commit") or ss.manifest.get("commit"),
                "upstream": ss.manifest.get("upstream"),
                "run": {
                    k: ss.run.get(k)
                    for k in ("started", "finished", "runner_image")
                    if ss.run.get(k)
                },
                "versions": (ss.stats.version_sets() or [{}])[0],
                "score_file": ss.score_path.name,
                **ss.stats.summary_json(),
            }
        )
    clusters = []
    for ss in ctx.sets:
        for cl in ss.stats.sorted_clusters():
            found = ctx.cluster_matches.get((ss.target_id, cl.key), [])
            exs = ctx.examples.get((ss.target_id, cl.key), [])
            clusters.append(
                {
                    "key": cl.key,
                    "key_source": cl.key_source,
                    "target": ss.target_id,
                    "family": cl.family,
                    "capability": cl.capability,
                    "signature": cl.signature,
                    "records": cl.count,
                    "cases": cl.case_ids,
                    "page": ctx.cluster_path[(ss.target_id, cl.key)],
                    "triage": {
                        "status": triage.status(found),
                        "findings": [e["id"] for e in found],
                    },
                    "examples": [
                        {
                            "id": ex.case_id,
                            "checks": [c.status for c in ex.checks],
                        }
                        for ex in exs
                    ],
                }
            )
    findings = [
        {
            **{
                k: e.get(k)
                for k in ("id", "kind", "lib", "status", "status_date", "signature")
                if k in e
            },
            "libraries": triage.libraries(e),
            **({"upstream_issue": e["upstream_issue"]} if e.get("upstream_issue") else {}),
            **({"fixed_in": e["fixed_in"]} if e.get("fixed_in") else {}),
        }
        for e in ctx.registry
    ]
    return {
        "format": "geotruth-site-index",
        "format_version": 1,
        "generated": ctx.generated,
        "generator": {"geotruth": ctx.package_version, "engine": ctx.engine_version},
        "tier": ctx.tier,
        "notes": [
            "The corpus is adversarial by design: rates are not real-world failure rates.",
            "There is no single ranking; compare one capability at a time.",
            "A failure cluster is a confirmed bug only if its triage status says so.",
        ],
        "pages": {
            "scoreboard": "index.html",
            "findings": "findings.html",
            "methodology": "methodology.html",
        },
        "libraries": libs,
        "clusters": clusters,
        "findings": findings,
        "build": report,
    }


def write_pages(out: Path, pages: list[Page]) -> None:
    for p in pages:
        dest = out / p.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(p.html, encoding="utf-8")
