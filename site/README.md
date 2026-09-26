# The geotruth site (`site/`)

The static site of results (DESIGN.md §6), built from score files:

```sh
geotruth run   --lib <target> --tier core                  # a library's answers
geotruth score --lib <target> --tier core \
               --expected corpus/expected/core.jsonl       # graded against the exact answers
geotruth site  --scores results --out site/_build          # this site
```

Open `site/_build/index.html` from disk, or publish the directory as it is (it has a
`.nojekyll` for GitHub Pages). The site is plain HTML with its CSS, a few lines of
JavaScript (the theme switch and copy buttons) and its SVG figures inline in every page. It
uses system fonts, makes no request to any other server, sets no cookies and has no
trackers. It works offline, in light and dark themes, and at phone width.

## What it shows

| page | what |
|---|---|
| `index.html` | what geotruth is, how exactness works, the notes a reader must see first (adversarial corpus, no single ranking, triage status, versions), the library × capability matrix (exact questions and overlay tiers apart; every cell links to its details) and the versions tested |
| `lib/<target>.html` | the build (version, commit, toolchain, options that depart from the library's defaults, adapter commit and manifest hash, run dates and health), the precision model and displacement budget δ_lib from the manifest, the fields graded, results per capability (verdicts, overlay tiers, failure clusters) and per corpus family, and the library's entries in the triage registry |
| `cluster/<target>/<family>-<signature>-<hash>.html` | one failure cluster (library × family × signature): what the signature means, its triage status, and up to `--max-examples` examples (smallest cases first, one per generator variant before repeats), each with the exact inputs, the exact answer next to the library's, figures zoomed to the discrepancy with the exact coordinates of the numbered vertices, an independent re-check of the exact answer, and the commands that reproduce both answers |
| `findings.html` | the triage registry (`findings/registry.toml`): confirmed, reported, fixed and by-design findings, then the unreviewed leads |
| `methodology.html` | exact arithmetic, the two routes, the overlay certificate, the controls, scoring and the overlay tiers, the fairness rules, triage, the corpus, how to read the figures, how to reproduce a result, how to add an adapter |
| `index.json` | the same data for machines: every library's counts, every cluster with its cases, page and triage status, the registry entries, and a build report |

## Inputs

`--scores DIR` (one or more) names results directories laid out as `geotruth run` and
`geotruth score` write them:

```
DIR/<target>/<tier>.score.jsonl   score.v2 records (required)
DIR/<target>/<tier>.jsonl         the library's result.v2 lines (its answers, for the examples)
DIR/<target>/<tier>.stats.json    runner statistics and the case files
DIR/<target>/run.json             provenance (run.v2): versions, commits, dates
DIR/_expected/*.jsonl             exact answers cached by the scorer
```

Only the score files are required. The generator also reads the adapter manifests
(`adapters/*/adapter.toml`), the registry, the case files and the published exact answers
(`corpus/expected/*.jsonl`). An exact answer that is in none of them is computed by the
engine for the examples shown (`--no-compute` turns that off), and the page says so.

## Honesty rules the generator enforces

- Every number comes from the score records; the counting rules are the scorer's own
  (`tests/site` checks them against `geotruth.harness.score.summarize`).
- There is no total per library and no ranking: rows are alphabetical, and rates are per
  capability, out of the answers graded.
- A failure cluster is `unreviewed` unless a registry entry matches it by library, family
  and field; a match is shown as a candidate explanation, with the entry's own signature.
  Leads (registered by signature only) are never matched automatically.
- The exact answer of every example is re-checked when the site is built, by an
  independent route: the witness-point relate (DESIGN §2.4), the overlay certificate
  (§2.6), or the audited reference validity rules. A failed re-check is shown on the page
  as "in doubt", listed in `index.json`, and makes `geotruth site` exit with status 1.
- The figures are drawn in exact arithmetic (a window a few ulps wide at 1e300 is drawn
  correctly); where the zoomed window comes from a heuristic, the caption says so.
- `--preview` stamps every page as unpublished, for showing maintainers their row before
  it is published.

## Code

`gtsite/` is the generator (it is not called `site`, which is Python's start-up module):
`load.py` reads the inputs, `aggregate.py` folds the score records, `triage.py` matches
clusters to the registry, `examples.py` builds the examples, `locus.py` chooses the zoomed
windows, `exact2d.py` holds the exact clipping and distances, `svg.py` draws the figures,
`pages.py` writes the pages, `words.py` holds the vocabulary. `templates/` holds the page
layout and the methodology text, `static/` the stylesheet and scripts that are inlined in
every page. The tests are in `tests/site/`.
