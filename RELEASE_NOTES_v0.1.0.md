# geotruth 0.1.0

The first release of geotruth: an exact-answer conformance suite for
computational-geometry libraries. It computes the one correct answer to DE-9IM relate,
overlay and validity questions in exact arithmetic on the input doubles, and grades
geometry libraries against it, each on what its own documentation promises.

Versions in this release, cited together: package 0.1.0, engine 0.1.0
(`geotruth.ENGINE_VERSION`), corpus 2.0.0, expected answers version 2. The full list of
changes is in [CHANGELOG.md](CHANGELOG.md).

## What is in it

- **The exact engine** (`src/geotruth/`, MIT). DE-9IM relate by two independent routes (a
  labelled arrangement, and witness points located directly in the inputs), named
  predicates dispatched as in JTS/GEOS RelateNG, overlay with OverlayNG's non-strict
  semantics and a regularized variant, an independent certificate for every overlay
  result, GEOS-compatible validity with every defect located exactly, and exact or
  certified measures. Every geometry type, including GeometryCollections and empty
  geometries. Rational backends: gmpy2, and Python's `fractions` as a cross-check.
- **The corpus and its exact answers** (`corpus/`, CC0). 17 families of near-degenerate
  cases; the `core` tier (3,400 cases, 200 per family) and the `curated` tier (the minimal
  cases of every finding and lead) are in git with their answers; the `full` tier (17,000
  cases) is generated deterministically by `geotruth corpus build --tier full` and its
  answers are recorded in `corpus/expected/MANIFEST.json`.
- **The harness.** Adapter contract v2 with per-operation crash and hang isolation and a
  parse-echo canary; manifests stating each library's promises (fields, precision model,
  overlay displacement budget, coordinate range, non-default options); `geotruth run` and
  `geotruth score`, with overlay graded in six tiers.
- **Adapters for 16 library builds**: GEOS (main, 3.15.0, and 3.13.1 through Shapely
  2.1.2), JTS (master and 1.20.0), Boost.Geometry (1.83, 1.92.0 and develop), Clipper2,
  CGAL 5.6 with an exact kernel (an external control), georust `geo` 0.33.1, Turf 7.4.0,
  JSTS 2.12.1, polygon-clipping 0.15.7, polyclip-ts 0.16.8 and martinez 0.8.1; plus two
  controls of the harness itself, the engine (`engine-control`) and a mutant with planted
  faults (`mutant`).
- **The scoreboard.** `data/scores/` (per-target and summary JSON for the `core` and
  `curated` tiers, and the checks of the three controls) and `geotruth site`, a static site
  with no trackers and no external requests: a library × capability matrix, a page per
  failure cluster with zoomed exact figures, the findings, and the methodology.
- **The triage registry** (`findings/registry.toml`): 14 findings, each with a directory of
  evidence (minimal cases, a standalone reproduction against the library's public API, its
  output on every version tested, and a drafted report), and 4 unreviewed leads.
- **Tools**: `geotruth relate`, `overlay` and `valid` for any WKT or JSON input;
  `geotruth minimize` (delta debugging against a library); `geotruth export` to JTS/GEOS
  XML, Boost.Geometry, Clipper2, georust and pytest tests, with `--run` to execute the XML
  in the JTS TestRunner and GEOS `xmltester`.

## Checked for this release

Every number here comes from a run on 2026-09-26 (Ubuntu 24.04 VM, 4 cores, Python 3.11.15,
gmpy2 2.3.1).

| check | result |
|---|---|
| `full` tier recomputed from scratch, 2 worker processes | 17,000 cases in 171.5 s wall (339.8 s in the engine): 16,000 with both operands valid, both relate routes agreeing on all of them; 128,000 overlay results (4 operations × 2 variants), every one passing the certificate; 0 `engine_skipped`, 0 `engine_error`; byte-identical to the answers recorded in the manifest |
| `engine-control`, core tier | 22,600 of 22,600 score records correct |
| `mutant`, core tier | 2,396 planted faults: 2,368 graded wrong, 28 graded as the other empty-geometry convention, 0 missed, 0 other records changed |
| CGAL exact kernel, core tier | 8,048 overlays with the same exact area, the same point set and OGC-valid results |
| the three controls, curated tier (131 cases) | `engine-control` 899 of 899 score records correct; `mutant` 93 planted faults, none missed; CGAL 232 overlays with the same exact area and point set, all OGC-valid |
| results site, core tier | 3,151 pages, 3,130 failure clusters, 9,486 examples; the exact answers of the examples re-checked by a second route when the site was built: 8,915 checks agree, 0 disagree, and 283 checks (in 235 examples, all validity of non-polygonal operands) have no second route; all 39,131 internal links resolve and all 23,497 inline SVG figures parse |
| test suite | `pytest -m unit`: 1,706 passed, 22 skipped, 0 failed; `tests/golden` with its slow tests: 35 passed; the CI cross-check subset (`make crosscheck-ci`): 359 passed, 27 skipped (native adapters not built in that run); `ruff check` clean with the pinned ruff 0.16.9 |

## Findings

The registry holds 14 findings: 11 confirmed, 1 fixed upstream, 2 by design. **None of the
confirmed findings has been reported upstream yet**; the reports are drafted in each
`findings/<id>/` directory and will be filed one at a time by a person. Among them:

- **Boost.Geometry 1.87 to 1.92 and develop**: for two overlapping triangles with a vertex
  1 to 2 ulps from the other's, `within` is true and the intersection is all of A (bisected
  to commit 0edb673).
- **GEOS RelateNG (3.13 to main)**: wrong matrices for MultiPolygons with touching parts,
  for near-collinear crossings, for GeometryCollections (three separate defects), a
  shortcut that makes the matrix depend on element order, and a crash on valid input
  (high priority; to be reported through a private channel first, per SECURITY.md).
- **GEOS overlay with GeometryCollections (3.13.0 to main)**, **Clipper2 PolyTree nesting
  (1.5.3 to 2.0.1)**, **Turf `booleanTouches` on polygons**, **two JTS overlay defects** (an
  empty result for coordinates above about 1.3e162 in unreleased master, and a
  `ClassCastException` in mixed polygon/point overlays in 1.20.0 and master), and a
  low-priority coordinate-range defect in GEOS and JTS segment intersection and orientation.
- **Fixed upstream**: the GEOS OverlayNG union that drops a polygon (libgeos/geos#1405,
  fixed in GEOS 3.15.0; still present in the GEOS 3.13.1 that Shapely 2.1.2 wheels bundle).
- **By design**: Clipper2's removal of thin result triangles and i_overlay's snapping grid
  in georust `geo`, both documented.

## Known limitations

- The corpus is adversarial by design; the failure counts are not real-world failure rates,
  and there is no ranking.
- The engine is written in Python for auditability (about 20 ms per case); it is not a
  production geometry library, and each case has a size budget.
- Scope: 2-D relate, predicates, overlay, validity and a few measures. No buffer, offset,
  simplification, geodesic, curved or 3-D geometry; Z and M are ignored.
- The results site is not published yet, and the nightly workflow that rebuilds and rescores
  every library stays disabled until maintainers have seen their rows (DESIGN.md §6).
- Not on PyPI yet; install from a clone (`pip install -e .`).
- `geotruth repro` (a generated standalone program per case, DESIGN.md §5) is not in this
  release; each finding directory has a hand-written one, and each cluster page of the site
  gives the commands that reproduce both answers.
- One cluster found during triage, a GEOS 3.13.1 regression in RelateNG's self-noding
  (`findings/geos-relateng-line-end-skip/covered-ring/`), is registered only in the notes of
  the finding whose directory holds its evidence, and so is not in the curated tier, until
  it gets a directory of its own.

## Thanks

By Abdulfayyod Mukhamedov, built with [Claude Code](https://claude.com/claude-code). The
libraries tested here are the work of their maintainers and contributors; geotruth exists to
help them, and every report will be filed with that in mind.
