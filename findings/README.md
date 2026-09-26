# Findings

Each candidate bug found by the harness gets a directory here with the evidence for it:
the minimal cases (`cases.jsonl`), the exact answers from both references (`oracle.jsonl`,
`indep.jsonl`), the library's answers, a standalone program that uses only the library's
public API (`repro.*`, with `run.sh`), its output on the latest development code and the
latest release, and the triage write-up (`ISSUE.md`).

[`registry.toml`](registry.toml) is the triage registry (DESIGN.md §5.4): one entry per
directory, with the library, a signature, the status and links. No automated disagreement is
presented as a confirmed bug; the status says how far triage has got:

| status | meaning |
|---|---|
| `unreviewed` | found by the harness, not yet triaged by a person |
| `confirmed` | a wrong answer within the library's documented contract |
| `by-design` | documented or intended behaviour, not reported as a bug |
| `reported` | confirmed and reported upstream |
| `fixed` | fixed upstream |

The findings so far, from the registry. Nothing marked `confirmed` has been reported
upstream yet: each directory holds the drafted report (`FINAL.md`, and `JTS_FINAL.md` where
JTS shares the code), to be filed by a person.

| finding | library | status |
|---|---|---|
| [`boost-geometry-develop-regression`](boost-geometry-develop-regression/FINAL.md) | Boost.Geometry | confirmed |
| [`clipper2-polytree-nesting`](clipper2-polytree-nesting/FINAL.md) | Clipper2 | confirmed |
| [`clipper2-thin-triangle-dropped`](clipper2-thin-triangle-dropped/ISSUE.md) | Clipper2 | by-design |
| [`geo-i-overlay-thin-polygon-collapse`](geo-i-overlay-thin-polygon-collapse/ISSUE.md) | georust geo | by-design |
| [`geos-multipolygon-touching-parts-predicates`](geos-multipolygon-touching-parts-predicates/FINAL.md) | GEOS | confirmed |
| [`geos-near-collinear-predicates`](geos-near-collinear-predicates/FINAL.md) | GEOS | confirmed |
| [`geos-overlay-geometrycollection`](geos-overlay-geometrycollection/ISSUE.md) | GEOS | confirmed |
| [`geos-relateng-geometrycollection-semantics`](geos-relateng-geometrycollection-semantics/ISSUE.md) | GEOS | confirmed |
| [`geos-relateng-line-end-skip`](geos-relateng-line-end-skip/ISSUE.md) | GEOS | confirmed |
| [`geos-relateng-segfault`](geos-relateng-segfault/ISSUE.md) | GEOS | confirmed, high priority |
| [`geos-tiny-coordinates-underflow`](geos-tiny-coordinates-underflow/FINAL.md) | GEOS | confirmed, low priority |
| [`geos-union-drops-polygon`](geos-union-drops-polygon/ISSUE.md) | GEOS (through Shapely) | fixed in GEOS 3.15.0 |
| [`jts-master-union-extreme-regression`](jts-master-union-extreme-regression/FINAL.md) | JTS | confirmed, low priority |
| [`turf-boolean-predicates`](turf-boolean-predicates/FINAL.md) | Turf | confirmed |

A crash or a hang is reported through the library's private channel first when it has one
([`../SECURITY.md`](../SECURITY.md)); GEOS has none, and takes crash reports in its public
tracker.
