
## must_fix

1. Overlay tolerance will report false failures. The 'output-vertex rounding floor' from gen/common.py assumes every output vertex lies within about 1 ulp of an exact vertex. Several libraries go beyond that by design: GEOS/JTS OverlayNG use snapping and snap-rounding fallbacks; geo/i_overlay snaps to an i32 grid of about 2^-30 of the extent (adapters/rust_geo/README.md reports relative area error up to 5e-9 on the seed); Clipper64 uses an integer grid and deliberately removes triangles with an edge under 2 units (findings/clipper2-thin-triangle-dropped/ISSUE.md); polyclip-ts rounds divisions to 20 decimals. FIX: score each overlay result in bands: exact, within the double-rounding floor, within the library's declared precision bound (from an adapter manifest), gross (above max(C x declared bound, 1e-6 relative); keep compare.py's 1e-6 for continuity), topological (missing or extra component, invalid output), and exception/crash/hang. The headline number is gross + topological + exception; the other bands are shown but not counted as failures.

2. Overlay output geometry loses precision on its way out of the adapter. Verified here with Shapely 2.1.2 / GEOS 3.13.1: Point(0.1+0.2, 1/3).wkt gives 'POINT (0.3 0.3333333333333333)', which drops the last ulp of 0.30000000000000004. shapely.to_wkt defaults to rounding_precision=6 ('0.333333'). rounding_precision=-1 also prints 0.3. Only 17 round-trips. Boost's bg::wkt uses the stream precision, which defaults to 6. If the contract says 'overlay output as WKT' and adapters use the library writers, the scores will measure the writers, not the overlay. FIX: the contract requires output coordinates to be written by the adapter itself, in shortest-round-trip decimal or hex floats (reuse the adapters' existing %.17g / to_chars / Double.toString code). Add a parse-echo canary operation: the adapter returns the doubles it parsed and wrote back for 2^53+1 as an integer literal, subnormals, -0.0, 0.30000000000000004 and 1.7976931348623157e308. Run it in CI for every adapter before any scoring.

3. The arrangement complexity claim is wrong, and face labelling is a performance cliff. (a) A bounding-box sweep gives O(n log n + c), where c is the number of bbox-overlapping pairs. c can be Θ(n²) with k = 0, for example with the long near-parallel edges of the sliver-spike, near-collinear and shared-edge families. It is not O((n + k) log n). (b) 'One exact interior sample point per face, even-odd over the rings' costs O(F·E). For two random 2000-vertex stars (measured: about 50k crossings, so about 52k faces and 4000 edges) that is about 2×10^8 exact edge tests, several minutes at the measured ~1M mpq orient/s. Building a strictly interior point of a non-convex face with rational vertices is also error-prone. FIX: label faces by propagation. Walk the face-adjacency graph breadth-first from the unbounded face (Exterior/Exterior), toggling A's or B's parity when crossing an edge whose source set contains a ring of A or B. For valid input each merged edge lies on at most one ring per operand. Do one exact point location per nested connected component (holes or islands that touch nothing, isolated points), which makes labelling O(E). Prune candidates with JTS-style monotone chains, not raw segment bounding boxes, and restate the bound honestly.

4. 'Up to about 2,000 vertices in a few seconds' is not achievable as stated, and nothing enforces a limit. Measured in this sandbox (Python 3.11, gmpy2 2.3.1). The arrangement skeleton alone (detection, construction, splitting, vertex sort, face walk; no labelling, rings or output):
- two random 2000-vertex stars, 50k crossings: 1.5 s, 144 MB;
- 1000-vertex combs, 250k crossings: 4.3 s, 554 MB;
- 2000-vertex combs, 1M crossings: 22 s, 2.1 GB.
The fractions.Fraction fallback is about 9x slower than mpq (107k vs 978k orient/s). FIX: state the target in terms of n + k, for example '≤ 5 s for n + k ≤ 50k with gmpy2'. Give the engine a budget (n + k cap of about 200k, wall-clock and RSS limits) that returns status engine_skipped, which the scorer must never count against a library. Make gmpy2 a hard dependency of 'expect' and corpus release, and keep Fraction only as a test-time cross-check. Have generators record k per case.

5. 'Cross-check against oracle.py and indep.py on every corpus case' cannot be done for large cases. oracle.py's slab method is cubic (oracle_review F5: 242 edges with 20k crossings takes 22 s). A 2000-vertex star pair has about 54k slabs x 4000 edges, minutes per case. indep.py splits every edge at every contact, which is O(E²). FIX: limit these cross-checks to cases of about 300 vertices or fewer and k ≤ 5k, or apply the F5 fix (incremental active lists) first. Check the large tier with exact identities (and with CGAL later), and label those claims 'single engine + identities' on the site.

6. The rule 'two implementations must agree before a claim' cannot be met outside polygon/polygon in v1. oracle.py and indep.py cover only areal predicates, areas and validity, and CGAL has no DE-9IM and no OGC line/point semantics. Line/point relate claims would rest on the new engine alone. FIX: either limit v1 scoreboard claims to areal/areal, or write a second relate for P/L/A that uses a different algorithm and no DCEL: extend indep.py's split-every-segment-at-every-contact approach and classify each sub-segment midpoint and each vertex against the other geometry by exact point location. Until that exists, show P/L results as 'unconfirmed' and keep them out of the headline.

7. Mixed-dimension overlay scoring would measure semantic choices, not bugs. 'Outputs never use GeometryCollection' contradicts JTS/GEOS OverlayNG: the union of a polygon and a line outside it is a GC. Libraries also differ on lower-dimensional output (OverlayNG strict vs non-strict mode), and Boost, Clipper2, i_overlay and the JS clippers return only polygons. FIX for v1: score only the areal part of polygon/polygon overlays, which every library returns. Defer line/point overlay until each library's documented semantics are encoded per adapter.

8. The design as written cannot be split into its own repository. The engine cross-checks and the harness reach into ../geometry-bughunt (oracle.py, oracle_review/indep.py, validity.py, gen/, adapters/, compare.py). The adapters default to /tmp/claude-0/gb-build. The workflow is planned at the monorepo root .github/. `git filter-repo --subdirectory-filter geotruth` would produce a broken repo. FIX:
- Move adapters/ and gen/ into geotruth/, so that geometry-bughunt depends on geotruth and not the other way round.
- Vendor oracle.py, indep.py and validity.py under geotruth/tests/reference/, with a provenance header (source commit) and the F1-F4 fixes applied.
- Take the build root from $GEOTRUTH_BUILD_DIR, defaulting to ~/.cache/geotruth.
- Put the CI workflows in geotruth/.github/workflows/ and add a thin root-level shim while it lives in the monorepo.


## should_change

1. Cut from v1:
- GeometryCollection inputs: JTS's old RelateOp rejects GC arguments and RelateNG unions them, so results diverge by design.
- Line/point overlay.
- Measures other than exact area (length/distance intervals, centroid, hull). None of them are in the adapter contract, so nothing would be scored.
- The 'parse the exact decimal' option: it answers a question no library is asked, and it risks a second 'ground truth'.
- CGAL: the build needs CGAL, GMP, MPFR and Boost; its polygon validity and representation differ from OGC (holes touching the shell, relatively simple boundaries). Move it to a nightly job in v1.1.
- JSTS and NetTopologySuite: ports of JTS, so little extra signal for the setup cost.
- The 'classic' literature family, which needs licence research.
- Version-history pages.
- Enabled nightly automation: write the workflow but leave it off.
Keep for v1: areal/areal DE-9IM and named predicates, areal overlay with exact rational rings and exact area, OGC polygon validity (port oracle_review/validity.py), plus P/L relate as a stretch goal labelled 'unconfirmed'.

2. Exact output format: 'exact WKT' does not exist, because WKT cannot carry rationals. Specify expected-answer JSON with rationals as 'n/d' strings in a canonical form: each ring starts at its lexicographically smallest vertex, shells are CCW and holes CW, and polygons are sorted. Add a separate WKT rounded to doubles, with its bound. Document that the rounded geometry can be invalid (thin slivers collapse), so it must never serve as an 'expected valid output' in exported tests.

3. Cheap arithmetic speed-ups:
- Every double is m·2^e, so scale each case to Python ints by 2^-emin. Measured 2.29M orient/s against 0.98M for mpq, with no gcd per operation.
- Keep intersection points as homogeneous integer triples (X, Y, W), reduced only for hashing and vertex merging.
- Sort edges around a vertex using the source segment's direction (b - a). Sub-edges are collinear with their source, so no arithmetic on intersection points is needed.
- At a proper degree-4 crossing, one orient call gives the cyclic order, so no sort is needed. In the prototype, cmp_to_key sorting was 15 of the 22 s.
- Store the DCEL in parallel int arrays or __slots__ objects. The tuple prototype used 2.1 GB for 2M edges.
- A certified float filter (Shewchuk static bound) can sit behind a flag, off for released expected answers.

4. Build one arrangement per case and read relate, all four overlays and every predicate off it. Parallelise across cases (expect --jobs N). Cache expected answers keyed by (sha256 of the canonical case, engine version). Small cases (mean 10-23 vertices, max 126 in the current cases/) should take a few ms each, so a 50k-case expected run takes minutes on 4 cores. Only the large tier is expensive.

5. Overlay scoring cost: symmetric difference for every library x operation x case is about 13 x 4 x 50k = 2.6M exact overlays. Mitigations:
- Exact shoelace area of the library output first, O(n).
- Canonicalise, and pass immediately when the output matches the rounded exact result vertex for vertex.
- Deduplicate identical outputs across libraries by hash (Turf's overlay is polyclip-ts, bit for bit).
- Compare against the exact result rounded to doubles, adding its rounding bound, rather than the rational result. Arithmetic on intersection-point coordinates measured about 9x slower (109k orient/s), and comparing against the rational result would need second-level constructions.
- Define the point set of an invalid library output by even-odd and report output validity as its own metric.

6. Score per case and per capability, not per field. geo derives all nine predicates from one relate call. Boost's contains is within(b, a). Clipper2's intersects is derived. Turf's symdiff is two differences. Counting nine predicates per case inflates and double-counts. Score the relate matrix once, and score predicates as 'any wrong' only for libraries with independent predicate code. Mark derived fields in the adapter manifest and on the site.

7. Tag every case with its degeneracy class (exact lattice degeneracy / ulp-level near-degeneracy / generic) and its coordinate range (normal / extreme, below about 1e-150 or above 1e150 / outside the library's documented range, e.g. Clipper2 MAX_COORD = 2^61 - 1). Report each class separately. Maintainers treat 'wrong on an exactly representable touching input' very differently from 'wrong two ulps away from a touch'. The generator families already encode the distinction, so carry it through to scoring.

8. Timeouts and denominators. martinez hit the 10 s timeout on 33 of 1000 seed cases (333 s per 1000), which is about 4.6 h for a 50k-case run. hunt.sh already runs Turf and martinez on a 150-per-family subset, which makes denominators unequal. Use one fixed, stratified core tier (for example 200 per family) run by every library for the headline matrix, with the full corpus as an extra. Use per-operation timeouts of 2-3 s with hangs counted, plus a per-library wall budget.

9. Library versions and provenance. 'Release' must mean the latest upstream release, not a distro package. Boost 1.83 from Ubuntu apt is several releases behind. The Shapely 2.1.2 wheel bundles GEOS 3.13.1 while GEOS main reports 3.16.0dev, so label Shapely rows as GEOS 3.13.1 and add the current GEOS release as its own row. Every result file should record:
- the library commit or version;
- the adapter's git hash;
- compiler and flags;
- every option that departs from library defaults (Turf booleanEqual precision 323.3; Clipper --scale-bits; JTS old relate vs RelateNG; GEOS non-Prec overlay; Boost NDEBUG);
- engine version, corpus version, and runner image digest.

10. Version cases and expected answers separately. Cases are immutable. Expected answers get errata releases when an engine bug is found, since an immutable corpus with a wrong expected answer would accuse every library at once. Every claim on the site cites (corpus vX, expected vY, engine sha).

11. Keep adapter input as typed JSON coordinates ({type, coordinates}). All six languages' hand-written readers already parse them exactly. Do not switch adapter input to WKT, because library WKT readers are unverified for exactness. Only the Python side needs a WKT reader and writer; hand-write them rather than go through Shapely/GEOS, the library under test.

12. Site: build pages per failure cluster (library x family x variant x difference signature) with capped examples and a JSON index, instead of one page per failure; tens of thousands of pages is unusable. Zoom each SVG to where the discrepancy is: ulp-level failures are invisible at full extent. Print exact coordinates. Do not publish a single aggregate league-table ranking. Say prominently that the corpus is deliberately adversarial, so the rates are not real-world failure rates.

13. Tests: use a top-level tests/ (not engine/tests) with pytest markers (unit under 1 min, crosscheck, slow). Use hypothesis only for the exact-transform invariances; valid-polygon strategies are hard, so reuse the seeded generators instead. Mutation-test the engine the way oracle_review/mutants.py did. Add an end-to-end control adapter (engine/indep wrapped in the adapter contract) that must score 100%, and a mutant adapter that flips answers and must be caught.

14. Validity scoring: score only the boolean against OGC/GEOS IsValidOp. Show reason strings as information, because vocabularies differ, geo does not check interior connectivity, and Turf's booleanValid has its own rules.


## missing

1. A test-case minimizer. The design promises 'a minimal case' for every failure but has no component that makes one. It needs delta debugging: drop parts, holes and vertices; shorten decimals; re-check validity and the engine answer after each step; batch the candidates into one adapter call per round, because adapters are JSONL batch processes.

2. Export to each library's own test format:
- JTS/GEOS XML: <run><precisionModel type="FLOATING"/><case><a>WKT</a><b>WKT</b><test><op name="relate" arg1="A" arg2="B" arg3="212101212">true</op></test></case></run>. JTS TestRunner and GEOS's tests/xmltester run it unchanged, which is the single biggest adoption lever for those two projects.
- Boost.Geometry: overlay_cases.hpp-style `static std::string case_x[2]` plus a test_one call with count and area.
- Clipper2: a Tests/Polygons.txt block (CAPTION / CLIPTYPE / FILLRULE / SOL_AREA / SOL_COUNT / SUBJECTS / CLIPS) with integer-scaled coordinates.
- geo: a #[test] using wkt!.
- Shapely: a pytest function.
Export overlay expectations as relate/area checks rather than exact result WKT, because runners compare with normalized equalsExact and collinear vertices differ. CI should verify that the exports load and pass on known-good cases.

3. Single-command tools for maintainers:
- `geotruth relate WKT_A WKT_B` (and `overlay`) prints the exact answer for any pair. It is probably the most-used feature for their own triage.
- `geotruth repro CASE_ID --lib geos` prints the exact answer against the library's, and emits a standalone program that uses only the library's public API, like findings/*/repro.cpp.
- `geotruth run --lib geos --prefix /path/to/local/build` (or JTS_JAR=...) runs against the maintainer's own branch, not just pinned commits.

4. An adapter manifest (adapter.toml) for each library: supported fields, derived fields, precision model and declared error bound, supported coordinate range, options that differ from defaults, version command, build recipe, owner. The scorer and the site read it.

5. A known-issues / triage registry per library: documented or by-design behaviour (Clipper2's removal of triangles with an edge under 2 units, Turf's hard-coded 1e-6 tolerances, i_overlay's grid), reported upstream (#n), fixed in version X. Every failure cluster carries a status (unreviewed / confirmed / by-design / fixed), so automated disagreements are never presented as confirmed bugs. The Clipper2 triage shows why this matters: that 'finding' turned out to be documented behaviour.

6. Engine outcome statuses in expected/ and in the harness (ok / engine_skipped / engine_error), so that a budget overrun or an engine exception can never turn into a library failure.

7. A corpus licence and per-case provenance. Use CC0 or BSL-1.0-compatible terms so that LGPL GEOS, EPL/EDL JTS and BSL Boost/Clipper2 can copy cases into their own suites without friction. Each case records its generator, seed and version, or for curated cases the upstream issue URL.

8. A storage plan for the corpus. The current 1000-case files are 0.48-0.85 MB each, so 50k cases is about 35 MB of JSONL before exact rational outputs, which multiply that. Keep only small tiers in git. Publish full tiers as release assets with a sha256 MANIFEST. The wheel ships only the engine.

9. Packaging and CI detail. pyproject.toml with src layout, requires-python >= 3.10, gmpy2 >= 2.2 required, extras [dev] and [shapely], and a `geotruth` console script. Ruff. GitHub Actions:
- PR: lint, unit and a small crosscheck under 10 min on Python 3.10-3.13, plus a no-gmpy2 job on a tiny subset.
- Nightly: one matrix job per library in pinned container images, build caches keyed on the upstream sha, results committed to a `data` branch, and a Pages deploy. One broken upstream build must not block the others.

10. Determinism and golden tests: canonical ordering and byte-identical output, plus a test that fails when expected/ changes without an engine version bump.

11. A small empty-geometry relate family (POLYGON EMPTY against a point, and so on). Libraries disagree widely there, and the design says nothing about it beyond 'OGC conventions'.

12. A disclosure and governance policy. Give maintainers notice and a chance to correct their adapter before their row is published. Welcome adapter PRs from upstream. Add CODEOWNERS per adapter. Adapters build upstream code, so run them in sandboxed CI jobs.


## build_order
 The engine is the one risky piece. Plan so nothing else waits on it: the harness, scoring, site, corpus and exports can all run first on polygon/polygon expected answers derived from oracle.py (with F1-F4 applied) and indep.py. DE-9IM is added once the engine lands. v1 is realistic for 4-5 people in a few hours only if it is scoped to areal/areal: DE-9IM, predicates, areal overlay, OGC polygon validity and area, with P/L relate as a stretch goal marked 'unconfirmed'.

PHASE 0 (one person, about 45 min, blocks everyone else):
- the geotruth/ skeleton: pyproject.toml and src/geotruth/;
- numbers.py: Q, per-case dyadic integer scaling, rational JSON;
- geom.py: typed geometry;
- io.py: JSON coordinate reader using float() semantics per F4, a hand-written WKT reader and round-trip writer;
- schemas/ for case, expected, result v2 (relate, output rings, parse-echo), score and adapter manifest;
- a frozen Arrangement interface (vertex, edge and face arrays; per-edge source-ring sets; cell labels) with about 10 hand-built fixture arrangements;
- a CLI dispatcher where each subcommand lives in its own module and is registered through a table, so nobody edits a shared file.
Schemas are frozen after this phase; changes go through this owner.

PHASE 1 (parallel, about 2-3 h, one owner per directory):
- E1, the critical path: engine/arrangement.py and label.py. Monotone-chain candidate pruning; exact intersections and collinear overlaps on dyadic integers; splitting; the DCEL in arrays; direction-vector vertex sort; parity-propagation labelling with one point location per nested component; the resource budget. Test it with the Euler characteristic, face areas summing to the bbox area, and random-point labels checked against oracle.point_in.
- E2: engine/relate.py, the predicates and engine/overlay.py (ring chaining, hole assignment, collinear merge, canonical output). Built against the Phase 0 fixtures first, then switched to E1's arrangement.
- E3: engine/validity.py (a port of oracle_review/validity.py) and the area measure; tests/reference/ with oracle.py, indep.py and validity.py vendored (with provenance and fixes); crosscheck and property tests (transpose, area identities, exact transforms, the size gate). If time allows, the split-and-classify second relate for P/L.
- E4: harness/. Move the adapters into geotruth/adapters/ with manifests and $GEOTRUTH_BUILD_DIR. Add `relate` to GEOS, JTS, Boost (bg::relation), geo and Shapely, and add round-trip output rings to every adapter; the parse-echo canary goes in first. Write the runner (timeouts, the stratified core tier) and score.py (bands, per-case scoring, derived fields), plus the control and mutant adapters.
- E5: move gen/ into corpus/generators/, build the curated tier from findings/, the tiers and MANIFEST with degeneracy and range tags. Exports, JTS XML first, checked against JTS TestRunner and GEOS xmltester. site/ built from fixture score files, and `geotruth repro` / `geotruth relate`.

PHASE 2 (integration, about 1 h):
1. Run the engine on the core tier.
2. Diff its areal fields against the oracle/indep expected answers; they must be identical.
3. Swap the engine in as the source of expected answers.
4. Run all adapters, score, and build the site.
5. Publish nothing until the triage registry is filled in.
Integration branch rebased hourly; E1 and E2 pair at the arrangement API boundary.


=================== NEXT CRITIC ===================


## must_fix

1. GeometryCollection inputs get wrong 'exact' answers. The design accepts GCs as input, but its labelling rules (even-odd over all rings, 'Boundary if it lies on a ring of A', mod-2 over the line endpoints) do not give the GC semantics any library implements. GEOS 3.13 RelateNG (JTS RelateNG too) uses union semantics with a dimension precedence. Checked with Shapely 2.1.2 / GEOS 3.13.1: (a) GC(two unit squares sharing x=1) vs the 2x1 rectangle gives 2FFF1FFF2, but the design marks the shared edge as Boundary, so BI=1; (b) GC(overlapping squares) vs a point in the overlap gives 0F2FF1FF2, but even-odd makes the overlap Exterior; (c) GC(POLYGON((0 0,2 0,2 2,0 2,0 0)), LINESTRING(1 1,3 1)) vs POINT(1 1) gives 0F2FF1FF2 (Interior), but mod-2 says Boundary. These GCs are VALID (GEOS is_valid=True, since GC validity is per element), so under the design's own rule they will be scored. Fix: implement RelatePointLocator precedence per cell. First the polygonal union: Interior if in any element's interior, or on an edge or vertex whose incident face sectors are all interior (AdjacentEdgeLocator); Boundary if on the union's boundary. Next the lines: Boundary if the mod-2 endpoint count over all line elements is odd, else Interior. Next the points: Interior. Otherwise Exterior. Faces get the union of per-element in/out, not even-odd. Or drop GC from relate and overlay in v1. Either way, mark old JTS RelateOp (the jts_main default; GeometryRelate.relate calls checkNotGeometryCollection) as 'unsupported', not wrong.

2. The face sample point is unspecified, and the obvious constructions give wrong labels. A face of a disconnected arrangement has inner components. For A=[0,10]^2 and B=[4,6]^2, a sample point for the annulus face taken from its outer cycle alone (ear, vertex-average, centroid (5,5)) falls inside B. The face is then labelled (I,I) instead of (I,E), so IE=F where it should be 2. The same happens for points inside dangling or isolated components. Fix: label faces through half-edges, with no sample point. If a half-edge lies on a ring of areal X, the X-location of its left face comes from the ring's exact orientation and its shell/hole role (interior on the left of a CCW shell or a CW hole). Otherwise it is PIP(midpoint of the half-edge), which is never on X's boundary, so it is strictly I or E. Assert that all half-edges of a face agree. If a point is still needed, use a horizontal ray from the midpoint of a non-horizontal half-edge to the nearest edge or vertex crossing on the face side, and take the midpoint. The DCEL must also support degree-1 vertices (next = twin), isolated vertices, multiple components, and an unbounded face even when there are no edges, so that EE=2 always.

3. Overlay output types contradict both the stated OverlayNG semantics and GEOS. The design says 'outputs never use [GeometryCollection]', but GEOS's default intersection is non-strict. GEOS 3.13.1 returns GEOMETRYCOLLECTION (POLYGON ((2 2, 2 1, 1 1, 1 2, 2 2)), LINESTRING (0 1.5, 0 0.5), POINT (2 0), POINT (0 0)) for a square intersected with a valid multipolygon that overlaps it, touches it along an edge and touches it at points. Union or symdifference of a polygon with a line or point outside it is also a GC. Fix: (1) Allow GC output. Define a non-strict expected result (JTS STRICT_MODE_DEFAULT=false: include boundary-touch lines and touch points) and a regularized, polygon-only result for libraries that only promise areas (Clipper2, i_overlay, martinez, polygon-clipping, polyclip-ts, CGAL). (2) State that 'in X' means Interior or Boundary (OverlayNG.isResultOfOp maps Boundary to Interior). Otherwise line∩polygon along the boundary, and polygon touch lines and points, are lost. (3) The output is the closure of the selected cells. 'Covered' means in the closure of the selected higher-dimension cells, and faces are merged across every edge whose two sides are both selected, even if that edge is not selected itself. GEOS: difference(LINESTRING(0 0,2 0), LINESTRING(1 -1,1 1)) = MULTILINESTRING((0 0,1 0),(1 0,2 0)), and symdifference(polygon, interior point) = the polygon. (4) Type empty results per OverlayUtil.resultDimension: intersection min(dimA,dimB), union and symdifference max, difference dimA. GEOS returns POLYGON EMPTY / LINESTRING EMPTY / POINT EMPTY.

4. The overlay error bound is not justified for any real library, and the symmetric-difference area criterion is blind to part of the output. gen/common.rounding_floor = ulp(max|c|)*(perA+perB) assumes each output vertex is the correctly rounded exact vertex. No tested library works that way. GEOS/JTS compute intersection points in double: I measured GEOS 3.13.1 line-line intersection points up to 35 ulps from exact at crossing angles near 1e-15 rad. OverlayNGRobust falls back to a SnappingNoder with tolerance max|ordinate|*1e-12, multiplied by 10 over 5 tries (up to 1e-8*M, which is 0.1 absolute for projected data at 1e7), then to snap-rounding at 10^(digits-14). Clipper2 snaps to the 2^-k grid, i_overlay to about 2^-30 of the half-extent (seed errors ~5e-9 relative), and polyclip-ts rounds divisions to 20 decimals. With this floor, those libraries would be scored wrong while doing exactly what they document. Also, symmetric-difference area is 0 for any line or point result, and for zero-width spikes. And Shapely's to_wkt defaults to 6 decimals (checked: POINT (0.123457 1)), so harness printing can add error. Fix: give each library a displacement budget δ_lib taken from its precision model: ½ulp·√2 for correctly rounded, the snap tolerance or grid step otherwise. Then require: (a) exact (squared-distance) Hausdorff distance between the library output and the exact output ≤ δ_lib, for every dimension; (b) exact area of the symmetric difference ≤ 2δ(P_exact+P_lib) + πδ²·n_vertices. This is the tube bound that snap rounding guarantees; the current floor has no second-order term. (c) Exact components or holes that fit inside the δ-tube of their own boundary may vanish or collapse to a lower dimension, and spurious lower-dimension pieces are allowed only within δ of the exact boundary. (d) Report three tiers: within the correctly-rounded floor, within the library budget, gross. Require adapters to print round-trip doubles.

5. The named predicates must be dispatched on dimension, and empties need an explicit convention; 'standard patterns' alone gives wrong answers. crosses is T*T****** only for P/L, P/A and L/A. It is T*****T** for L/P, A/P and A/L, 0******** for L/L, and false otherwise. A polygon with a line inside it matches T*T****** but does not cross. overlaps is T*T***T** for P/P and A/A, 1*T***T** for L/L (lines crossing at a point do not overlap), and false otherwise. touches is false for P/P, and equals requires equal dimensions. Use RelateNG's 'real' dimension: empty elements ignored, a line whose points all coincide counts as P. EMPTY equals EMPTY is true in RelateNG/GEOS 3.13 for any types (checked: POINT EMPTY equals LINESTRING EMPTY → True), while T*F**FFF* gives false. Tag such cases as convention-dependent rather than 'wrong answer'.

6. The mod-2 rule is stated wrongly. 'An endpoint shared by an even number of lines is interior' must be 'a point that occurs an even number of times among the start and end points of all line elements'. A closed LineString contributes 2, and a point that is an endpoint of one element and interior to another is still Boundary. GEOS: MULTILINESTRING((0 0,2 0),(1 0,1 1)) vs POINT(1 0) = FF10F0FF2, and LINESTRING(0 0,1 0,0 0) vs LINESTRING(0 0,1 0) = 10FFFFFF2. Also, vertex labels need a full point location for BOTH operands, not only for the geometry the vertex came from. This applies to intersection points and to isolated points inside the other operand's faces. The boundary-endpoint test comes before line-interior, as in RelatePointLocator.locateOnLines. Take endpoints from the first and last coordinates before dropping zero-length segments.

7. 'Exact WKT' / JSON output of overlay results is impossible. Intersection points are generally non-dyadic rationals: (0,0)-(1,1) meets (0,1)-(2,0) at x=2/3, which has no finite decimal and no JSON number. Fix: store exact coordinates as integer p/q pairs, or as a rational side-car next to the rounded WKT. Mark rounded WKT as display-only. Never score against it, because rounding a valid exact result can make it invalid or change its topology.

8. Validity: the rule set does not match GEOS IsValidOp beyond polygons, and the reasons cannot be compared as strings. GC validity is per element only: overlapping polygons in a GC are VALID (GEOS is_valid=True). Applying R6 to GCs would call them invalid. LineString validity is only 'at least 2 distinct points', so self-crossing or self-overlapping lines are valid. Empties are always valid. Codes missing from the list: 'Holes are nested', 'Ring is not closed'. Classification: a crossing or collinear overlap, including a fold-back inside one ring, is 'Self-intersection'. Only a non-crossing self-touch of one ring is 'Ring Self-intersection'. GEOS reports only the FIRST error, in a fixed order (coordinates, closure, too few points, area intersections, holes in shell, nested holes, nested shells, interior connected), at a floating-point location. Fix: extend R0-R6 to every type. Compute the full exact set of defects. Score the boolean exactly, and score the reason as the first code by GEOS precedence, with the location within δ of some exact defect.

9. Measures: the claims are false for lines. The centroid of a (Multi)LineString is length-weighted, so it involves square roots and is not rational. JTS/GEOS also take the centroid from the highest-dimension components only. The length of a polyline is a sum of square roots, so it has no rational 'exact squared value'; that works only for a single segment, and for distance, which is a min of rational squared distances. Fix: use certified intervals, refined until the correctly rounded double is decided. Detect exactly the case where every segment length is rational (perfect squares), where the value can be a double or a tie.


## should_change

1. The complexity claim is false. Bounding-box sweep pruning does not give O((n+k) log n) candidate pairs: n parallel diagonal segments with pairwise-overlapping boxes give Θ(n²) pairs with k=0. Either use Bentley-Ottmann or state the cost as O(n log n + #bbox-overlaps). The target of 2,000 vertices in a few seconds is unrealistic when k is large: oracle.py took 22 s at 242 edges and 20k crossings, and face labelling by PIP is O(F·E). State the target in terms of n+k and give the engine its own per-case timeout.

2. The pairwise intersection routine used for splitting must return the up-to-2 endpoints of a collinear overlap, and T-junction endpoints. Do not reuse oracle.py crossing_x, which returns nothing when denom=0 (correct only for slab events). Deduplicate points by exact mpq equality, since three segments can meet at one rational point.

3. Overlay ring building: at result-boundary vertices of degree > 2, link minimal rings, taking the angularly adjacent edge on the result side. A pinch then becomes a shell plus a hole touching it at a point, not an inverted self-touching ring, which GEOS calls 'Ring Self-intersection'. Faces touching only at a vertex become separate polygons. Never merge faces across a vertex. Assign holes from DCEL face adjacency, or by PIP of a hole vertex that is not on the candidate shell, choosing the smallest enclosing shell (islands in holes). Collinear-vertex removal must keep nodes, and the line endpoints that are mod-2 boundary points.

4. CGAL cross-check: compare exact point sets (the engine's exact symmetric difference is empty), not vertex lists. CGAL's regularized set operations drop lower-dimension parts, may output relatively simple outer boundaries (pinched) instead of a shell plus touching hole, and keep degree-2 vertices. Have the CGAL adapter print exact rationals. CGAL::to_double / mpq_get_d truncates and is not round-to-nearest, so it is not a ½-ulp control.

5. The scoreboard needs an 'unsupported / out of contract' category separate from 'wrong': old JTS RelateOp throws on GCs, JTS OverlayNG rejects mixed GCs (GEOS 3.13 accepts them with union semantics), polygon-only clippers have no line or point outputs, and Clipper2 cannot take non-dyadic input or input above 2^62. Judge Turf predicates (hard-coded 1e-6 tolerances) and Boost.Geometry equals (tolerant collected vectors) against their documented tolerances, or flag them as tolerance-based, in line with 'judge only on what it promises'.

6. Library output geometry may be invalid: self-intersecting rings, holes outside shells, martinez's unclosed rings. Define the measured point set (even-odd over the output rings) and report invalid output as a separate failure class, rather than letting the symmetric difference silently absorb it.

7. Identity tests: |A∩B|+|A−B|=|A| needs |A| to be the area of the point set. The JTS/GEOS area of a GC is the sum of its elements' areas even when they overlap, so name which one the measure returns. The check 'A ∪ ∅ = A' must use topological equality, because the engine normalizes (collinear-vertex removal, merged faces).

8. Zero-length geometry: dropping zero-length segments makes a LineString whose points all coincide vanish, so it is treated as empty. RelateNG treats it as a Point (GEOS: LINESTRING(1 1,1 1) vs POINT(1 1) = 0FFFFFFF2). It is also GEOS-invalid ('Too few distinct points'), so either keep it out of relate and overlay cases or follow RelateNG explicitly.

9. Parsing: the 'exact decimal' option describes a geometry no library sees, so it must never feed library scoring. Specify how Z/M is handled (ignored, as the adapters do). Keep NaN and Inf as flagged coordinates for validity ('Invalid Coordinate'); do not let them raise at mpq() (lesson F2). Feed indep.py doubles, not raw JSON integers (F4).

10. State that only the OGC Mod-2 Boundary Node Rule and GEOS-default validity (isInvertedRingValid=false) are modelled, and make adapters use those defaults (GEOSRelate, not GEOSRelateBoundaryNodeRule; no ALLOW_SELFTOUCHING flag). Add sanity assertions on every matrix: EE=2, transpose symmetry, and for non-empty areal A, II or IE or IB is non-F.


## missing

1. A second, independent implementation for everything that is not polygon/polygon. oracle.py and indep.py cover only polygon predicates and areas, and neither yields a DE-9IM matrix (BB, IB, BI entries). So the 'two implementations must agree' principle is unmet for the full matrix, for lines, points and GCs, and for mod-2. Proposal: a witness-point relate. Witnesses are all input vertices, all pairwise intersection points, midpoints between consecutive split points on every segment, and the horizontal-ray face points. Each is located directly against the original A and B with a standalone RelateNG-style point locator. M = max dimension over witnesses of each label pair. It shares only the segment-intersection primitive with the DCEL route. Use GEOS RelateNG on small-integer lattice cases as a third opinion.

2. An overlay certificate checker that does not depend on the overlay builder. Build the arrangement of (A, B, R_exact), locate every cell's witness in A, B and R, and assert R-label = op(A-label, B-label) under the closure and non-strict semantics. The same checker can grade library output with a δ-tolerant variant.

3. Semantics for collapses in library output. Valid inputs never collapse in exact arithmetic, but GEOS non-strict output can contain 'collapse lines' after snapping. The scoring rule must say they are allowed within δ of the exact boundary.

4. A written convention table for empties across relate, predicates, overlay and measures: typed empty results, equals(EMPTY, EMPTY), POLYGON EMPTY elements inside Multi* and GC, and the OverlayUtil.isEmptyResult short-cuts (intersection of envelope-disjoint inputs, difference with empty A).

5. Line-output comparison semantics. JTS/GEOS output fully noded, unmerged line pieces, so line results must be compared as point sets (Hausdorff plus length of the symmetric difference, or exact equality after merging), never structurally.

6. Rational bit growth and cost at extremes: subnormal inputs give denominators around 2^1074, and huge exponents are possible. The engine needs a budget or timeout, and the corpus needs to record when a case was too expensive, instead of stalling the nightly run.

7. How GEOS's fallback path can be told apart. The harness cannot tell whether GEOS used the floating noder, snapping or snap-rounding. Either score against the loosest documented budget, or add an adapter mode that runs OverlayNG with the floating noder only, so precise-path failures can be separated from documented snapping loss.


## build_order
 1) Primitives first, by one implementer, then freeze their API: geotruth/geom.py (types, empties, GC flattening), exact.py (double→mpq parse with non-finite flags, orient, segment-segment intersection returning a point or overlap endpoints, exact squared distances), and io.py (WKT/JSON reader, rational p/q writer, round-trip-double writer). 2) In parallel on top of the primitives, one module and one test file per implementer so there are no shared edits: (a) arrangement.py: candidate pairs, splitting, merging with per-element source tags, DCEL with dangling and isolated vertices, half-edge side labelling; (b) locate.py: standalone RelateNG-style point locator with mod-2 and GC union semantics; (c) validity.py: R0-R6 extended to all types, GEOS codes and precedence; (d) measures.py: exact area, certified length and line centroid, distance², hull; (e) the CGAL adapter (C++, prints exact rationals); (f) generator extensions for lines, points and GCs, using only primitives and validity. 3) relate.py (matrix from the labelled arrangement, dimension-dispatched predicates, empties table) after 2a, and relate_witness.py after 2b. Cross-check them against each other, oracle.py, indep.py and GEOS on integer lattices before generating any expected answers. 4) overlay.py (closed-set selection, closure, minimal rings, hole assignment, typed empties, GC output, strict and non-strict variants) after 2a, plus overlay_certify.py after 2b. Add property tests (transpose, area identities, exact transformations). 5) Harness adapter extensions in parallel, one owner per language directory (C: geos_main; C++: boost_geometry and clipper2; Java: jts_main; JS: adapters/js; Rust: rust_geo; Python: shapely): relate string, crosses, overlay WKT at round-trip precision, explicit 'unsupported'. 6) score.py once the overlay API and the per-library δ table are fixed (Hausdorff plus tube-area tiers, validity by precedence). 7) Freeze corpus v1 with engine-version stamps. 8) Static site. 9) Nightly CI. Critical path: 1 → 2a/2b → 3 → 4 → 6. Validity (2c), measures (2d), CGAL (2e), generators (2f) and adapters (5) run off the critical path.


=================== NEXT CRITIC ===================

