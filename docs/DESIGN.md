# geotruth design (v2)

geotruth measures whether computational-geometry libraries give the **right** answer. It
compares them with answers computed in exact arithmetic on the exact input.

v2 incorporates two independent design reviews: one on semantics and correctness, one
on engineering and scope. Every claim below that a library "does X" was checked against
GEOS 3.13.1 / JTS during review.

## 0. Principles

1. **Ground truth is exact.** Every coordinate is an IEEE-754 double, and every double is
   a rational number m·2^e.
   - The engine decides everything in exact integer or rational arithmetic, with no
     tolerance anywhere in a decision.
   - Inputs are read the way libraries read them: a JSON number becomes a double first,
     so integers above 2^53 round.
2. **Two independent implementations must agree before a claim is made.**
   - For relate: the arrangement route (§2.3) and the witness-point route (§2.4). They
     share only the primitives in §2.1.
   - For polygon areas and predicates: also the audited `tests/reference/oracle.py` and
     `indep.py`.
   - For overlay: an independent certificate checker (§2.6).
   - CGAL, with an exact kernel, is an external control.
3. **Judge a library only on what it promises.**
   - Predicates and relate on exact input are exact questions, so any wrong answer counts.
   - Overlay output is graded against the library's own documented precision model, in
     tiers (§4.3).
   - Behaviour outside a library's contract is reported as `unsupported`, never as `wrong`.
     Examples: coordinates above Clipper2's MAX_COORD; geometry collections in the old JTS
     RelateOp; line output from a polygon-only clipper.
4. **No automated disagreement is presented as a confirmed bug.** Every failure cluster
   has a triage status in the registry (§5.4): unreviewed, confirmed, by-design, reported
   or fixed.
5. **The engine can abstain.** A case over the engine's budget is `engine_skipped`, and an
   engine exception is `engine_error`. Neither is ever counted against a library.
6. **Everything is reproducible.** Each failure has:
   - a minimised case;
   - one command that shows the exact answer next to the library's;
   - a standalone program that uses only the library's public API.

## 1. Semantics (what "exact answer" means)

geotruth models the OGC Simple Features semantics as implemented by JTS/GEOS **RelateNG**
and **OverlayNG**. It uses the default Mod-2 boundary node rule and the default validity
(isInvertedRingValid = false).

### Types and conventions

- **Types:** Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon and
  GeometryCollection (GC). Z and M values are ignored.
- **Empty geometries:** empty elements are ignored for dimension.
- **Real dimension:** a LineString whose points all coincide has real dimension 0, as in
  RelateNG. Cases like this are tagged, because GEOS calls them invalid.

### Point location

The same rules apply to one geometry and to a GC:

1. **Polygonal part** (the union of all polygonal elements):
   - *Interior* if the point is in any element's interior, or on an edge or vertex whose
     incident sectors are all interior (as in AdjacentEdgeLocator).
   - *Boundary* if it is on the union's boundary.
2. **Linear part:**
   - *Boundary* if the point occurs an odd number of times among the first and last
     coordinates of all line elements. A closed line contributes 2.
   - Otherwise *Interior* if it lies on a line.
   - The boundary test comes first, as in `RelatePointLocator.locateOnLines`.
3. **Points:** *Interior* if the point equals a point element.
4. Otherwise *Exterior*.

The dimension precedence is polygonal first, then linear, then points.

### DE-9IM

The matrix entry M[a][b] is the maximum dimension of any point set whose location
relative to A is a and relative to B is b. EE is always 2.

Named predicates are dispatched on dimension:

| predicate | pattern | applies to |
|---|---|---|
| crosses | T*T****** | P/L, P/A, L/A |
| crosses | T*****T** | L/P, A/P, A/L |
| crosses | 0******** | L/L |
| crosses | false | every other pair |
| overlaps | T*T***T** | P/P, A/A |
| overlaps | 1*T***T** | L/L |
| overlaps | false | every other pair |
| touches | false | P/P |
| equals | requires equal dimensions | all |

Empty/empty conventions (for example, equals(EMPTY, EMPTY) is true in GEOS 3.13) come
from a convention table. Cases that depend on a convention are tagged, and they are
scored as `convention` disagreements, not as wrong answers.

### Overlay

Overlay follows OverlayNG. "In X" means Interior or Boundary of X, as in `isResultOfOp`.
The selection rule for each operation:

| operation | selected where |
|---|---|
| intersection | A∧B |
| union | A∨B |
| difference | A∧¬B |
| symmetric difference | A⊕B |

The result is the closure of the selected cells:
- faces are merged across every edge whose two sides are both selected;
- lower-dimensional parts are kept only where they are not covered.

There are two variants:
- **non-strict:** the default. It keeps boundary-touch lines and points, as in GEOS's
  default, and can produce a GC.
- **regularized areal:** the polygon part only, for polygon-only clippers.

An empty result is typed as in `OverlayUtil.resultDimension`:
- intersection: min(dimA, dimB);
- union and symmetric difference: max(dimA, dimB);
- difference: dimA.

### Validity

Validity follows GEOS IsValidOp for every type:

- **GC:** validity is checked per element.
- **LineString:** valid if it has at least 2 distinct points.
- **Empty geometries:** always valid.
- **Polygons and multipolygons:** rules R0-R6 from `tests/reference/validity.py`:
  - invalid coordinate;
  - ring closure;
  - too few points;
  - self-intersection vs ring self-intersection (a non-crossing self-touch of a single
    ring);
  - holes in the shell;
  - nested holes;
  - nested shells;
  - disconnected interior.

The engine computes the full exact set of defects. Scoring is on the boolean result
alone. The first reason by GEOS precedence is reported for information.

### Measures

- **Area** is an exact rational.
- **Distance²** is an exact rational.
- **Length** and **line centroid** involve square roots, so they are certified intervals,
  refined until the correctly rounded double is decided.
- **Convex hull** is exact.

## 2. Engine (`src/geotruth/`)

### 2.1 Primitives (`numbers.py`, `exact.py`, `geom.py`, `io.py`)

- **Per-case dyadic scaling.** All coordinates are m·2^e, so each case is scaled by
  2^-e_min to Python integers. Orientation and intersection tests are then pure integer
  arithmetic, measured at 2.3M orient/s against 1.0M for mpq.
- **Intersection points** are homogeneous integer triples (X, Y, W), reduced only for
  hashing and merging.
- **Segment-segment intersection** returns nothing, a single point, or the (up to two)
  endpoints of a collinear overlap. It includes T-junctions.
- **Non-finite coordinates** are carried as flags (validity code "Invalid Coordinate");
  they never raise.
- **I/O:**
  - a JSON typed-geometry reader using float semantics;
  - a hand-written WKT reader and writer; neither goes through a library under test;
  - a rational side-car writer (`"n/d"` strings, canonical order);
  - a shortest-round-trip double writer.

### 2.2 Arrangement (`arrangement.py`)

- **Candidate pairs** are pruned with monotone chains. The cost is O(n log n + number of
  chain-envelope overlaps); that is the honest bound, and a Θ(n²) worst case with no
  intersections is possible.
- Segments are split at every point on them, and coincident sub-segments are merged.
  Each sub-edge keeps its source tags: which geometry, element, ring and shell or hole.
- **DCEL in parallel integer arrays.** It supports:
  - degree-1 vertices (next = twin);
  - isolated vertices;
  - several connected components;
  - an unbounded face that always exists.
- **Edge order around a vertex** comes from each source segment's direction vector. A
  sub-edge is collinear with its source, so this needs no arithmetic on intersection
  points. A proper degree-4 crossing needs a single orient test.
- **Face labelling, with no sample points:**
  - A half-edge lying on a ring of an areal geometry X gives X's location for its left
    face directly, from the ring's exact orientation and role: interior lies on the left
    of a CCW shell or a CW hole.
  - Otherwise the location is found by a breadth-first parity walk from the unbounded
    face.
  - There is one exact point location per nested component (islands, holes that touch
    nothing, isolated points).
  - The labels of all half-edges of a face must agree.
- **Budget:** each case has limits on n + k (default about 200k), wall-clock time and
  memory. Over budget gives `engine_skipped`.

### 2.3 Relate from the arrangement (`relate.py`)

- Each cell (vertex, edge or face) is located in A and in B with the §1 rules. The matrix
  is the maximum dimension over the cells in each (locA, locB) entry.
- Named predicates are dispatched on dimension, as in §1.
- **Assertions** run on every matrix:
  - EE = 2;
  - relate(B, A) is the transpose of relate(A, B);
  - a non-empty areal A has II, IB or IE non-F.

### 2.4 Relate from witnesses (`relate_witness.py`), the independent second opinion

- **Witnesses:**
  - all input vertices;
  - all pairwise intersection points;
  - the midpoints between consecutive split points on every segment;
  - one point strictly inside each face, from a horizontal ray cast from a half-edge
    midpoint to the nearest crossing.
- Each witness is located directly against the **original** A and B by a standalone
  RelateNG-style point locator (`locate.py`). The DCEL is not used.
- It shares only §2.1 with §2.3. Every expected matrix must match between the two routes.

### 2.5 Overlay (`overlay.py`)

- Cells are selected by §1, then the closure is taken.
- **Ring building:** at a result vertex of degree above 2, rings are closed minimally
  using the angularly adjacent edge, so a pinch becomes a shell plus a touching hole. Faces
  that touch only at a vertex stay separate polygons.
- **Hole assignment** comes from face adjacency. Collinear vertices are removed, except at
  nodes and at mod-2 boundary points.
- **Output:**
  - exact rational rings in canonical order: each ring starts at its lexicographically
    smallest vertex, shells are CCW and holes CW, and parts are sorted;
  - the typed-empty rules;
  - both variants (non-strict and regularized areal);
  - a display-only WKT rounded to doubles. It is never scored against, because rounding
    can make the result invalid.

### 2.6 Overlay certificate (`overlay_certify.py`), the independent check

An arrangement of (A, B, R) is built from scratch. Every cell's witness is located in A,
B and R, and the check asserts that the R label equals op(A label, B label) under the
closure semantics. The same checker grades library output (§4.3).

### 2.7 Validity (`validity.py`) and measures (`measures.py`)

These implement §1.

## 3. Corpus (`corpus/`)

- **Case format:** `{id, family, tags, provenance, a, b}`, with typed JSON geometries. The
  tags cover:
  - the degeneracy class: exact lattice degeneracy, ulp-level near-degeneracy, or generic;
  - the coordinate range: normal, or extreme (below about 1e-150 or above 1e150);
  - n, k and the geometry types.
- **Tiers:**
  - `core`: a stratified 200 per family, run by every library for the headline matrix;
  - `full`: every case, as release assets with a sha256 MANIFEST; only the small tiers
    are kept in git;
  - `curated`: the minimal case of every triaged finding, with its upstream issue URL and
    status.
- **Families:**
  - the ten existing generator families and the review families;
  - new line, point and GC families: collinear overlaps, endpoint-on-segment, mod-2
    configurations, closed lines, zero-length lines (tagged), point-on-boundary;
  - an empty-geometry convention family.
- **Versioning:** cases are immutable. Expected answers are versioned separately, with
  errata releases, and every claim cites (corpus vX, expected vY, engine sha).
- **Licence:** the corpus is CC0, so that GEOS (LGPL), JTS (EPL/EDL), Boost (BSL) and
  Clipper2 (BSL) can copy cases freely. The code is MIT.

## 4. Harness (`adapters/`, `src/geotruth/harness/`)

### 4.1 Adapter contract v2

Adapter input and output:
- **Input:** typed JSON geometries.
- **Output:** relate (DE-9IM), every named predicate, validity, and overlay output. Output
  coordinates are written by the adapter itself in shortest round-trip form, never through
  the library's WKT writer (Shapely defaults to 6 decimals, Boost's stream to 6).

Before anything is scored, every adapter must pass a **parse-echo canary**. It echoes
back:
- 2^53+1 written as an integer;
- subnormals;
- -0.0;
- 0.30000000000000004;
- the largest double.

Fields are reported as `null` when unsupported, and `unsupported` for out-of-contract
input. Every adapter keeps its per-operation crash, hang and memory isolation.

### 4.2 Adapter manifest (`adapters/<lib>/adapter.toml`)

Each manifest records:
- the supported and derived fields (for example, Boost contains = within(B, A), Turf
  symdiff = two differences);
- the precision model and the displacement budget δ_lib;
- the supported coordinate range;
- any options that depart from the library's defaults;
- the version command, the build recipe (build root `$GEOTRUTH_BUILD_DIR`, default
  `~/.cache/geotruth`), and the owner.

It also records whether the library uses tolerance-based predicates (Turf's 1e-6, Boost's
equals).

### 4.3 Scoring (`score.py`)

- **Relate and predicates** are scored exactly, **per case**. A derived field is not
  counted twice. Disagreements that depend on a convention are shown separately.
- **Validity** is scored on the boolean.
- **Overlay** is graded against the exact result using δ_lib, into these tiers:
  1. exact;
  2. within the correctly rounded floor;
  3. within the library's documented budget, where both must hold:
     - Hausdorff distance ≤ δ_lib;
     - symmetric-difference area ≤ 2δ(P_exact + P_lib) + πδ²·n_vertices;
     - exact components thinner than δ may vanish or collapse;
  4. gross;
  5. topological: a missing or extra component, or invalid output (the point set is
     defined by even-odd);
  6. exception, crash or hang.

  The headline is tiers 4-6. GEOS is scored against its loosest documented fallback, and
  an optional floating-noder-only mode separates precise-path failures.
- **Every result records** the library version or commit, the adapter hash, the compiler
  and flags, non-default options, the engine version, the corpus version and the runner
  image.

## 5. Maintainer tools

1. **`geotruth relate A B` / `geotruth overlay A B OP` / `geotruth valid A`** print the
   exact answer for any WKT or JSON input.
2. **`geotruth repro CASE --lib geos`** shows the exact answer next to the library's, and
   emits a standalone program that uses only the library's public API.
3. **`geotruth run --lib geos --prefix /path/to/build`** runs against a maintainer's own
   branch.
4. **Triage registry (`findings/registry.toml`).** For each cluster: the library, a
   signature, the status (unreviewed, confirmed, by-design, reported or fixed), and links.
   Documented behaviour (Clipper2's small-triangle removal, Turf's 1e-6 tolerances,
   i_overlay's grid) is recorded as by-design.
5. **Minimiser.** Delta debugging over parts, holes and vertices, and shortening
   decimals. After every step it re-checks validity and the exact answer, and it batches
   candidates per adapter call.
6. **Exports to each library's own test format:**
   - JTS/GEOS XML (TestRunner and xmltester);
   - Boost overlay test cases;
   - Clipper2 `Tests/Polygons.txt`;
   - Rust `#[test]` with `wkt!`;
   - pytest.

   Overlay expectations are exported as relate and area checks. CI verifies that the
   exports load and pass on known-good cases.

## 6. Site (`site/`)

A static site with:
- a library × capability matrix, with the tiers separated;
- a page per failure cluster (library × family × signature), with capped examples;
- SVGs zoomed to where the discrepancy is, with the exact coordinates printed.

It shows no single aggregate ranking, and it says prominently that the corpus is
deliberately adversarial, so the rates are not real-world failure rates. Maintainers get
notice before their row is published. The site uses no trackers.

## 7. Packaging, tests, CI

- **Packaging:** `pyproject.toml` with a src layout and Python ≥ 3.10. gmpy2 is required
  for producing expected answers. `fractions` is kept as a cross-check backend, and is
  about 9× slower. The console script is `geotruth`. Ruff for linting.
- **Tests** live in `tests/`, with pytest markers `unit` (under 1 minute), `crosscheck`
  and `slow`. They include:
  - golden and determinism tests: expected/ may not change without an engine version bump;
  - mutation tests of the engine;
  - a control adapter (the engine) that must score 100%;
  - a mutant adapter that must be caught.
- **CI:**
  - on each PR: lint, unit tests and a small crosscheck on Python 3.10-3.13, under 10
    minutes;
  - nightly: one matrix job per library in pinned images, with results on a `data` branch
    and a Pages deploy. It is written but stays disabled until the triage registry is
    complete.

## 8. Build order

1. **Phase 0** (blocks the rest):
   - the skeleton, the primitives (§2.1), the schemas, and a frozen Arrangement API with
     fixtures;
   - moving the existing bug-hunt harness into the new layout with `$GEOTRUTH_BUILD_DIR`;
   - vendoring the references into `tests/reference/`.
2. **Phase 1** (parallel):
   - E1: the arrangement and labelling (the critical path);
   - E2: the point locator and the witness relate;
   - E3: validity and measures;
   - E4: adapters v2, the manifests, the runner and the scorer;
   - E5: the corpus, the new families, the tiers, the minimiser, the exports and the CLI.
3. **Phase 2:**
   - relate from the arrangement, cross-checked against the witness route, oracle, indep
     and GEOS on integer lattices;
   - overlay and its certificate;
   - property tests.
4. **Phase 3:**
   - expected answers v1 for the core tier;
   - all adapters scored;
   - the site;
   - the README and documentation;
   - CI.

## Out of scope for v1

- Buffer, offset and simplification.
- Geodesic, curved and 3-D geometry.
- Rust and C ports of the engine.
