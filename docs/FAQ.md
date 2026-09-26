# Frequently asked questions

## What is geotruth, in one paragraph?

A conformance suite for computational-geometry libraries. It asks libraries questions
such as "how do these two geometries relate (DE-9IM)?", "what is their intersection?" and
"is this polygon valid?", on inputs chosen to be hard: vertices a few ulps from an edge,
edges shared up to rounding, touching parts, extreme scales. It computes the true answer
in exact arithmetic and grades each library's answer against it, within the precision the
library itself documents.

## Why exact arithmetic?

Because on near-degenerate input nothing else gives a reliable reference. Two
floating-point libraries can disagree, and a third floating-point implementation cannot
tell which is right: a tolerance only moves the problem to the threshold. With exact
arithmetic there is exactly one answer for the input, so every disagreement has a definite
explanation (a library bug, a documented limitation, or a bug in geotruth itself) and is
never a matter of opinion.

geotruth decides every geometric question with integers and rationals: orientation tests,
segment intersections, point location, areas. There is no tolerance anywhere in a
decision. Lengths and centroids involve square roots; they are computed as certified
intervals, refined until the correctly rounded double is known.

## Why treat doubles as rational numbers?

Because that is what a library is actually given. Every finite IEEE-754 double is exactly
m·2^e for integers m and e. When you write `0.1` in WKT, the library receives the double
nearest to 0.1, which is exactly 3602879701896397/2^55, not 1/10. The geometric question
the library answers is about those rationals, so the exact answer must be too.

This has visible consequences. The segment from (0, 0) to (0.3, 0.9) does **not** pass
through the point (0.1, 0.3): the three doubles are not collinear, as rationals.
`geotruth relate "POINT (0.1 0.3)" "LINESTRING (0 0, 0.3 0.9)"` prints `FF0FFF102`
(disjoint), and so does GEOS 3.13.1 (through Shapely 2.1.2). In the same way, geotruth reads JSON numbers the way
libraries do (as `float()` or `strtod` would), so the integer literal `9007199254740993`
is the double 2^53.

Exact results are reported as rationals (`"n/d"` strings); the WKT shown next to them is
rounded to doubles for display only and is never used for grading.

## Isn't it unfair to hold floating-point libraries to exact answers?

For predicates and relate, no. The question itself is exact: for given input there is one
right DE-9IM matrix, and libraries document their predicates as answering it, apart from
those with an explicit tolerance (Turf, Boost's `equals`), which are labelled as such in
the results. Many libraries use robust orientation tests; where they also construct
intersection points in floating point, near-degenerate input can still lead them to a
wrong matrix, and that is what geotruth measures.

For overlay, yes, it would be unfair, so geotruth does not do it. A library's overlay
output is graded against its own documented precision model: exact, within the correctly
rounded floor, within the library's displacement budget δ_lib (from its documentation),
and only beyond that as a failure. Libraries that document no bound get no budget, and
their output that is merely off by rounding still grades correct. Input a library does not
support is `unsupported`, not wrong. See [SCORING.md](SCORING.md).

## How do you know the exact engine is right?

It is checked in several independent ways, and it may abstain rather than guess:

- **Relate is computed twice**, from a labelled arrangement (a DCEL) and from witness
  points located directly in the input geometries. The two routes share only the
  arithmetic primitives, and every expected answer requires them to agree.
- **Every overlay result is certified** by an independent checker that re-nodes A, B and
  the result from scratch and checks each cell's label.
- **Relate and overlay are cross-checked** against each other, and areas against the
  inclusion-exclusion identities.
- **Audited references** (`tests/reference/`) and two rational backends (gmpy2 and
  Python's `fractions`) give further second opinions.
- **CGAL with an exact kernel** runs as an external control where its semantics match.
- **The test suite compares the engine with GEOS** (through Shapely) on small integer
  lattices, where GEOS's point location is exact. A disagreement must be explained, as a
  known GEOS defect with a minimal case whose witnesses GEOS's own point locator confirms;
  anything else fails the test.
- **The harness is tested too**: the engine behind the adapter contract (the control)
  must score no failure, and a mutant with planted faults must have every fault caught.

Over budget, the engine reports `engine_skipped`; on an internal failure or a
disagreement between its routes, `engine_error`. Neither is ever counted against a
library.

None of this makes the engine infallible. If you find a case where it is wrong, that is
the most valuable bug report this project can get: see [CONTRIBUTING.md](../CONTRIBUTING.md).

## What semantics does geotruth use?

The OGC Simple Features semantics as implemented by JTS and GEOS **RelateNG** and
**OverlayNG**: the Mod-2 boundary node rule, GEOS IsValidOp validity, non-strict overlay
results by default (lines and points of boundary touches are kept) and a regularized
polygonal variant for polygon-only clippers. The details, including how
GeometryCollections and empty geometries are handled, are in
[DESIGN.md §1](DESIGN.md#1-semantics-what-exact-answer-means). Where libraries
legitimately differ (conventions for empty geometries), the disagreement is reported as a
`convention`, not as a wrong answer.

## What are the limitations?

- **Speed.** The engine is written in Python (with gmpy2) for auditability. It is fast
  enough for the corpus, but it is not a production geometry library, and each case has a
  size and time budget.
- **Scope.** DE-9IM relate, the named predicates, overlay (intersection, union,
  difference, symmetric difference), validity and a few measures, in 2-D. Buffer, offset,
  simplification, geodesic, curved and 3-D geometry are out of scope for now; Z and M
  values are ignored.
- **One semantics.** Libraries with other documented semantics are graded only where
  they promise the same thing, which leaves some of their behaviour ungraded.
- **The corpus is adversarial.** Failure rates measure behaviour on near-degenerate
  input, deliberately constructed. They are not real-world failure rates, and they are not
  a ranking.
- **Budgets are readings of documentation.** δ_lib and the out-of-contract rules come from
  each library's documentation and source; several are marked uncertain until their
  maintainers confirm them.
- **Adapters can be wrong.** An adapter bug looks like a library bug. The parse-echo
  canary, the adapter tests, the control runs and the triage policy exist to catch that
  before anything is claimed.

## How does this relate to prior work?

- **The JTS and GEOS test suites.** JTS has a large suite of XML test cases run by its
  TestRunner, and GEOS runs the same kind of XML files with its `xmltester`, along with its
  own unit tests. Their expected results are curated by the developers. geotruth is
  complementary: its cases are generated in bulk around near-degenerate configurations,
  each comes with an exact answer, and `geotruth export --format jts-xml` writes them in
  exactly that XML format, so they can be added to those suites directly
  ([EXPORTS.md](EXPORTS.md)).
- **Spatter** (Wenjing Deng, Qiuyang Mang, Chengyu Zhang and Manuel Rigger, "Finding
  Logic Bugs in Spatial Database Engines via Affine Equivalent Inputs", SIGMOD 2025;
  [arXiv:2410.12496](https://arxiv.org/abs/2410.12496)) tests spatial database systems
  (PostGIS, DuckDB Spatial, MySQL and SQL Server) with metamorphic testing: it checks that
  the topological relationship of a pair of geometries is unchanged when both are mapped
  by the same affine transformation, which needs no ground truth. The authors report 34
  previously unknown bugs, 30 of them confirmed and 18 fixed at the time of writing.
  geotruth takes the other route to the oracle problem: it computes the ground truth, so a
  single query can be graded on its own and overlay output can be graded geometrically.
  It tests geometry libraries directly, not SQL engines, so it cannot find bugs in a
  database's own layers. The two approaches are complementary.
- **CGAL** is built on the exact computation paradigm: exact predicates, and with the
  `Epeck` kernel exact constructions. It is a library, not a test suite. It has no DE-9IM
  relate, and its polygon Boolean operations are regularized operations on polygons,
  without the rest of the OGC semantics above (the Mod-2 rule, GeometryCollections,
  non-strict overlay). geotruth therefore has its own engine, and runs CGAL as an
  independent external control where the semantics coincide.
- **Robustness research.** The failures geotruth looks for are the ones described in the
  literature on geometric robustness, for example Shewchuk's adaptive-precision predicates
  (1997) and Kettner, Mehlhorn, Pion, Schirra and Yap's "Classroom examples of robustness
  problems in geometric computations" (2008).

## Can I use the cases in my own project?

Yes. The cases and expected answers are CC0 (public domain dedication): copy them into
any test suite, under any licence, without asking or attributing. The code is MIT.

## Why is there no overall ranking?

Because the corpus is adversarial and the libraries promise different things: a polygon
clipper with an integer grid and a DE-9IM engine are not doing the same job. The results
are reported per capability and per corpus family, with the precision model of each
library next to them, and every failure cluster with its triage status.

## Are the failures reported to the libraries?

Only after triage. An automated disagreement is `unreviewed` until a person has
reproduced it on the library's latest development code, minimised it, checked the exact
answer by independent routes, checked the library's documentation for intended behaviour
and searched the upstream tracker for duplicates. The status of every cluster is in
[`findings/registry.toml`](../findings/registry.toml), and the policy is in
[CONTRIBUTING.md](../CONTRIBUTING.md#triage-and-reporting-to-library-maintainers).

## I maintain a library and I think a result is wrong. What now?

Please open an issue (there is a template for it). Possible causes: the adapter calls the
library in a way you do not recommend; the manifest misstates what the library promises (its
precision, its supported input); the behaviour is documented and should be `by-design`;
or the engine is wrong. `geotruth relate` / `overlay` / `valid` print the exact answer for
any input, with `--dual`, `--certify` and `--explain` to show how it was reached.
