# geotruth: design

geotruth measures whether computational-geometry libraries give the **right** answer, by
comparing them with answers computed in exact arithmetic on the exact input.

It has five parts:

1. an exact reference engine,
2. a corpus of hard cases with exact answers,
3. a harness with one adapter per library,
4. a scoreboard,
5. automation that runs everything against upstream development branches.

## 0. Principles

- **Ground truth is exact.** Every input coordinate is an IEEE-754 double, and every double
  is a rational number. The engine works on those rationals with exact arithmetic
  (`gmpy2.mpq`, falling back to `fractions.Fraction`). It never uses tolerances, epsilons
  or floating point in a decision.
- **Two implementations must agree before a claim is made.** The engine is checked
  against:
  - the audited `geometry-bughunt/oracle.py`;
  - the independent `geometry-bughunt/oracle_review/indep.py`;
  - CGAL with an exact kernel;
  - exact identities: `|A∩B| + |A−B| = |A|`, DE-9IM transpose symmetry, and others.
- **Judge a library only on what it promises.** Predicates on exact input are exact
  questions, so any wrong answer counts. Overlay output is floating point, so it is judged
  by an error bound that rounding can explain, never by bitwise equality. Invalid input is
  used only to test validity checks.
- **Every failure is reproducible.** Each one comes with a minimal case, the exact answer,
  and the library's answer.

## 1. Exact engine (`geotruth/engine/`, Python package `geotruth`)

### Geometry model

- **Types:** Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon, and
  GeometryCollection (for inputs only; outputs never use it).
- **Coordinates:** 2-D `(mpq, mpq)`. Both the input and output formats are WKT and
  GeoJSON-style JSON. Parsing is exact: the decimal text is first parsed as a double, and
  the rational is the double's exact value, which is what libraries see. An option parses
  the exact decimal instead.
- **Emptiness and validity** follow OGC Simple Features 1.2.1 and JTS/GEOS conventions.

### Core: labelled arrangement (`arrangement.py`)

Given geometries A and B, build the planar arrangement of all their segments and isolated
points:

1. Collect segments (zero-length ones dropped) and points.
2. Find every intersection point exactly, with bounding-box sweep pruning. There are
   `O((n + k) log n)` candidate pairs, and each pair is tested exactly.
3. Split the segments at every point that lies on them. Merge coincident sub-segments,
   keeping the set of source geometries for each one.
4. Build a DCEL (a data structure that links each edge to the faces and vertices around
   it), sorting the edges around each vertex by exact angle comparison (quadrant, then
   cross product).
5. Label every cell (vertex, edge and face) with its location relative to A and to B,
   each one of Interior, Boundary or Exterior:
   - **Faces:** use one exact interior sample point per face; the even-odd rule over the
     polygon rings decides whether it is inside each areal geometry.
   - **Edges:** an edge is Boundary of A if it lies on a ring of A. For a linear A it is
     Interior of A, except at the mod-2 boundary endpoints. Otherwise it takes its
     location from the faces on its two sides.
   - **Vertices:** apply the OGC boundary rules for the geometry type. A polygon vertex
     is on its boundary. For line endpoints, the mod-2 rule applies: an endpoint that is
     shared by an even number of lines is in the interior.

### Everything is read off the labelled arrangement

- **DE-9IM (`relate.py`).** For each cell of dimension d with labels (locA, locB), set
  M[locA][locB] = max(M, d). The matrix is complete and exact for every type pair.
  - Named predicates come from the standard patterns: `intersects`, `disjoint`,
    `touches`, `crosses`, `within`, `contains`, `overlaps`, `equals` (topological),
    `covers`, `covered_by`.
  - `relate_pattern(A, B, "T*F**F***")` is also available.
- **Overlay (`overlay.py`).** Select the faces for the operation:
  - Intersection is A∧B, union is A∨B, difference is A∧¬B, and symmetric difference is A⊕B.
  - For linear and point results, also select edges and vertices by the same rule. This
    follows the JTS OverlayNG semantics: the result has the highest dimension available,
    and lower-dimensional parts are kept only where they are not covered.
  
  The result is exact:
  - boundary edges are chained into rings;
  - shells and holes are assigned by containment (exact point-in-ring tests);
  - collinear vertices are removed and adjacent faces merged.
  
  The output is a valid geometry with rational coordinates. It can be rounded to doubles
  for display, and the rounding bound is reported.
- **Validity (`validity.py`).** Implements OGC and GEOS IsValidOp, with a reason for each
  failure: "Self-intersection at (x y)", "Hole lies outside shell", "Interior is
  disconnected", "Nested shells", "Too few points", "Ring self-intersection", "Invalid
  coordinate". The existing `oracle_review/validity.py` rules R0-R6 are the starting point.
- **Measures (`measures.py`).**
  - Area is exact, a rational number.
  - Length and distance involve square roots, so they are returned as exact squared
    values (`mpq`) plus a certified interval of arbitrary precision.
  - Also covered: centroid (exact rational), convex hull (exact monotone chain), and
    point-in-polygon.

### Performance target

Inputs up to about 2,000 vertices per operand should take under a few seconds in pure
Python with gmpy2. A later Rust port (`geotruth-rs`) may reuse the same tests; it is not in
scope for v1.

### Verification of the engine (`engine/tests/`)

- Unit tests for every type-pair relate on hand-made cases, including the published
  JTS/GEOS relate examples, reimplemented rather than copied.
- A cross-check against `oracle.py` (areas and polygon predicates) and `indep.py` on every
  corpus case.
- A cross-check against CGAL, using `Exact_predicates_exact_constructions_kernel` and
  Boolean set operations, for polygon overlay areas and exact output vertices.
- Property tests:
  - DE-9IM(B, A) is the transpose of DE-9IM(A, B);
  - overlay area identities hold;
  - the overlay output is valid, and equals the input when combined with ∅;
  - the results are invariant under exact transformations: translation by dyadics,
    rotation by 90°, reflection, scaling by powers of two.

## 2. Corpus (`geotruth/corpus/`)

A case is `{id, family, tags, a, b}`, with geometries in WKT (all types) or the existing
MultiPolygon JSON. The expected answers are generated by the engine and stored alongside
the cases in `expected/`:

- the DE-9IM matrix;
- all named predicates;
- the overlay results, as exact WKT and as rounded doubles, with exact areas;
- validity and its reasons.

The corpus has three parts:

- **generated:** the ten `geometry-bughunt/gen` families and the review families, extended
  to lines and points (collinear overlaps, endpoint-on-segment, mod-2 boundary cases,
  closed lines, zero-length segments);
- **curated:** the minimal case from every confirmed bug found by this project, each tagged
  with the library, the upstream issue and its status;
- **classic:** hand-written versions of well-known hard configurations, such as the
  degenerate overlay cases described in the literature. They are rewritten, not copied,
  unless the licence allows copying.

The corpus is versioned and immutable once released. Every case's expected answer comes
with the engine version that produced it.

## 3. Harness (`geotruth/harness/`)

- **Contract:** the adapter contract of `geometry-bughunt/FORMAT.md`, extended with
  `relate` (the DE-9IM string), `crosses`, and overlay output geometry as WKT. Adapters
  remain separate processes in any language, and each isolates crashes and hangs per
  operation.
- **Libraries:** GEOS (release and main), JTS (release and master), Shapely, Boost.Geometry
  (release and develop), Clipper2, CGAL (exact kernel, as the control), Turf, JSTS,
  polygon-clipping, polyclip-ts, martinez, geo/i_overlay, and NetTopologySuite if .NET is
  available.
- **Scoring (`score.py`):** for each library, operation and family:
  - predicates: exact agreement rate;
  - relate: exact matrix agreement;
  - overlay: the fraction of results whose symmetric difference with the exact result is
    within the rounding bound (the output-vertex rounding floor from `gen/common.py`),
    plus the counts of gross errors, exceptions, crashes and hangs.

## 4. Scoreboard (`geotruth/site/`)

A static site generated from score files, with:

- a library × operation matrix;
- a page per family;
- a page per failure, showing a minimal case with an SVG picture of both inputs, the exact
  answer and the library's answer;
- version history, to show regressions.

It has no server and no trackers.

## 5. Automation (`.github/workflows/geotruth.yml`, later)

- Nightly: build each library's development branch, run the corpus, and publish the
  scoreboard.
- On a pull request to geotruth: run the engine's own tests and the cross-checks.

## Out of scope for v1

- Buffer, offset, simplification and other operations without exact answers.
- Geodesic geometry and curved or 3-D geometry.

These are candidates for later, using certified-interval ground truth.
