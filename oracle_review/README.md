# Oracle review (`oracle-review`)

Adversarial review of `../oracle.py`. oracle.py itself was **not** modified; the fixes
below are described, not applied.

## Verdict

**No wrong answer was found on valid, in-format input.** The oracle's predicates and
exact areas (`exact.inter`, `exact.diff_ab`, `exact.diff_ba`) matched an independent
exact implementation *as rationals* on every one of 36,342 valid cases. Many of those
cases are deliberately degenerate. `ring_simple` matched GEOS and an independent test on
126,339 rings, including every ring of 3 to 5 vertices on a 3x3 grid.

The problems found are crashes and scope gaps:

| # | Severity | What | Where |
|---|----------|------|-------|
| F1 | **bug on valid input** | `OverflowError` crash when an area exceeds DBL_MAX (coordinates of magnitude ~1.34e154 or more). The run then aborts, and every later case is lost | oracle.py L226-231, L239-242 |
| F2 | bug for `invalid-*` families | `AssertionError` on most invalid inputs (bowtie, hole outside shell, overlapping or nested parts), and `ValueError` on NaN. The run aborts | L235, L36, L239-242 |
| F3 | false-positive risk | validity is only decided for single-ring polygons. An invalid multi-ring input that passes the L235 assert is silently treated as valid, and compare.py then reports library "bugs" on it | L190-194 |
| F4 | input hardening | JSON integer literals above 2^53 are taken exactly, while every adapter rounds them to a double. The oracle then answers a different question | L36, L194 |
| F5 | performance | worst case is cubic: 242 edges per operand with 20k crossings takes 22 s, over FORMAT.md's 10 s | L101-144 |

There are also two dead or redundant code paths, both harmless (see "Mutation testing"):
- `point_in`'s `return 0` branch (L92-93) is unreachable from `intersects()`.
- `ring_simple`'s `n < 3` test (L171) is subsumed by the fold-back test.

All minimal cases are in `findings_cases.jsonl`. `python ../oracle.py findings_cases.jsonl`
prints 1 line out of 9 and then dies with a traceback.

### F1: area overflow crashes the oracle (valid input)

```json
{"id": "F1-area-overflow", "a": [[[[0.0,0.0],[2e154,0.0],[2e154,2e154],[0.0,2e154],[0.0,0.0]]]],
 "b": [[[[0.0,0.0],[1.0,0.0],[1.0,1.0],[0.0,1.0],[0.0,0.0]]]]}
```

The exact area 4e308 is fine as an `mpq`. `float(both + da)` at L226 raises
`OverflowError: 'mpq' too large to convert to float` (gmpy2; `Fraction` raises too).
`main()` (L239-242) has no per-case guard, so the whole run stops. Any case with
coordinates of 1e300 hits this, and so does any case whose area is over about 1.8e308.

**Fix:** convert with a saturating helper, `def fl(q): try: return float(q) except OverflowError: return math.inf`
(areas are non-negative), and use it at L226-231. With that change, all 947 overflow
cases in my corpus passed every check (verified on an in-memory patched copy). Python
writes `Infinity` in JSON and `compare.py` reads it back. With `scale = inf`, area
comparisons are then skipped, which is right because every double library overflows
there too, while the predicates, which are exact, are still compared.

### F2: invalid inputs crash the oracle

```json
{"id": "F2-invalid-bowtie", "a": [[[[0,0],[2,2],[2,0],[0,2],[0,0]]]], "b": [[[[0,0],[1,0],[1,1],[0,1],[0,0]]]]}
```

The even-odd slab area of A (2) differs from its shoelace value (|1 - 1| = 0), so the
`assert` at L235 fires. The same happens for:
- a hole outside the shell,
- overlapping multipolygon parts,
- nested shells.

NaN or Infinity coordinates (non-standard JSON that Python's `json` accepts) raise at
`Q(x)` on L36. FORMAT.md explicitly reserves `invalid-*` families for validity tests, so
such a family cannot currently go through the oracle.

**Fix:**
1. Compute `valid_a` and `valid_b` first. If either is `False`, return only
   `id/lib/valid_a/valid_b`; compare.py reads nothing else in that case (compare.py L25-26).
2. In `valid_single_polygon`, return `False` for non-finite coordinates (GEOS: "Invalid Coordinate").
3. In `main()`, catch per case and emit `{"id", "lib", "errors": {"oracle": repr(e)}}`
   instead of dying. compare.py would then also need to skip oracle lines that carry errors.

### F3: multi-ring validity is not checked, so invalid inputs are compared as if valid

`valid_single_polygon` returns `None` for polygons with holes and for multipolygons.
compare.py treats `None` as valid. The L235 assert rejects some invalid shapes (see F2),
but these pass silently:
- a hole sharing a segment with the shell,
- parts sharing an edge,
- a hole touching the shell at two points (disconnected interior),
- nested holes that happen to satisfy the shoelace identity, and so on.

Example (`F3-invalid-hole-shares-shell-edge`): shell [0,4]², hole [0,2]x[1,3] on the
shell's left edge, B = [-1,1]x[1,3]. The oracle says `touches=True`; GEOS says
`valid=False`, `overlaps=True`. compare.py would file this as a GEOS predicate bug.

**Fix:** `validity.py` here is a drop-in exact `valid_geometry(geom)` for every shape. It
checks:
- per-ring simplicity,
- no shared segments between rings,
- holes inside the shell,
- holes and parts with disjoint interiors,
- a connected interior, using GEOS's rule: no cycle in the ring/touch-point graph.

It agreed with GEOS `is_valid` on 30,000 random small-integer multi-ring geometries
(`validity_check.py`), including every invalidity class GEOS reports (Self-intersection,
Too few points, Interior is disconnected, Hole lies outside shell, Holes are nested,
Nested shells) and ~5,000 valid ones. It also agreed on all 45 hand-made edge cases.

To apply: use it for `valid_a`/`valid_b` at L215-216 and extend compare.py's validity
comparison beyond single rings. Its cost is O(E²) exact operations.

### F4: integer literals above 2^53

```json
{"id": "F4", "a": [[[[0,0],[9007199254740993,0],[9007199254740993,1],[0,1],[0,0]]]],
 "b": [[[[9007199254740992.0,0.0],[9007199254740994.0,0.0],[9007199254740994.0,1.0],[9007199254740992.0,1.0],[9007199254740992.0,0.0]]]]}
```

`json.loads` returns the Python int 2^53+1 and `Q(x)` keeps it exactly. Shapely/numpy,
`strtod` and `JSON.parse` all round it to 2^53. The oracle says `overlaps`; every library
sees `touches`, which is correct for the doubles they actually receive. FORMAT.md forbids
such literals, but nothing enforces the rule.

**Fix:** use `Q(float(x))` at L36 and L194. This is exact for every double and
reproduces what every adapter parses.

### F5: run time

For two random stars (few crossings), the oracle takes 0.3 s at 200 vertices per operand
and 1.5 s at 400.

For combs with about n² edge crossings:

| edges per operand | crossings | time |
|-------------------|-----------|------|
| 62 | 1,252 | 0.36 s |
| 122 | 5,100 | 2.5 s |
| 242 | 20,596 | 22 s |

The cause is that every slab rescans all edges and there are O(crossings) slabs. Keep
oracle cases small, or build each slab's active list incrementally from the previous
slab. `timing.py` reproduces the star numbers.

## `ring_simple` against OGC / GEOS validity for a single-ring polygon

GEOS `IsValidOp` (3.13, `isInvertedRingValid=false`, which is what Shapely's `is_valid`
uses):

| GEOS / OGC rule | ring_simple | Match? |
|---|---|---|
| coordinates finite ("Invalid Coordinate") | crashes: `Q(nan)` raises ValueError, `Q(inf)` raises OverflowError | **mismatch** (crash instead of False; F2) |
| ring closed | returns False if not closed. GEOS's C API refuses to build the ring; **Shapely silently closes it and reports it valid** | **mismatch against Shapely-based adapters** (out-of-format input only) |
| at least 4 non-repeated coordinates ("Too few points") | `n < 3` after dropping consecutive repeats; a 2-vertex ring is also caught by the fold-back test | yes |
| consecutive repeated points ignored | yes (L163-166) | yes |
| collinear 180° vertex allowed | yes (adjacent collinear edges without fold-back pass) | yes |
| spike / fold-back / zero-area ring invalid | yes (L178-183) | yes |
| proper self-crossing invalid | yes (L185) | yes |
| self-touch at a vertex (inverted ring, "ESRI-valid") invalid | yes, via `seg_intersect` on non-adjacent edges | yes |
| vertex on a non-adjacent edge invalid | yes | yes |
| orientation irrelevant | yes | yes |

Tested with `ring_check.py`: every vertex sequence of length 3, 4 and 5 on the 3x3 grid
(66,339 rings, repeats included) plus 60,000 random rings on 5x5 and dyadic grids, under
exact maps. The result: 0 disagreements among `ring_simple`, an independent test built
on intersection *sets*, and GEOS. For fewer than 4 coordinates, Shapely raises at
construction, so an adapter reports `valid=null` plus an error. compare.py does not flag
that, which is consistent.

## Method

1. **Line-by-line read.** Each step's correctness argument was checked:
   - the slab invariant (all crossings are events, so edge order inside an open slab is
     fixed and the midpoint-sum sort key is exact);
   - the even-odd parity;
   - the `seg_intersect` general case with zero orientations;
   - the claim in `intersects()` that with no boundary contact one vertex per ring decides;
   - predicate definitions from exact areas (for regular closed sets, interiors meet iff
     the intersection area is > 0, and B ⊆ A iff area(B-A) = 0).

   The gmpy2 conversions were checked separately: `mpq(float)` was exact on 200k random
   bit patterns including subnormals, and `float(mpq)` was correctly rounded (it matched
   `Fraction` on 200k values).

2. **Independent implementation, `indep.py`.** It shares no code or algorithm with the
   oracle:
   - `Fraction` instead of gmpy2;
   - winding number on re-oriented rings instead of even-odd;
   - line-equation (Cramer) intersection instead of the parametric formula;
   - areas by Green's theorem on boundary pieces: every edge is split at every contact
     and classified in/out/same-direction/opposite-direction by its midpoint;
   - predicates from that classification, without using any area.

   For convex pairs, a third route uses exact Sutherland-Hodgman clipping and a
   separating-axis test.

3. **Properties** checked on every case:
   - identities: `inter + diff_ab` equals the independent shoelace area; disjoint/touches/interiors-meet partition; equals = contains ∧ within; overlaps ⇒ ¬contains ∧ ¬within; and so on;
   - swap symmetry (contains↔within, diff_ab↔diff_ba);
   - invariance under exact maps (swap x/y, negation, scaling by 2^k, which scales areas by 4^k);
   - invariance under representation changes (ring start, orientation, inserted repeated points, part and hole order).

4. **Corpus** (`gen_review.py`, 36,045 cases), checked with `check.py`:

| family | cases | what it stresses | result |
|---|---|---|---|
| convex-grid | 8000 | shared full and partial edges, vertex on edge, identical copies (rotated start, reversed, repeated points), adjacent translates, nested dyadic hulls: 2404 touches, 2158 equals, 1340 contains/within | 0 failures |
| convex-grid-rot | 8000 | the same pairs pushed through one float rotation, scale and offset, so degeneracy becomes ulp-level near-degeneracy | 0 |
| convex-ulp | 3000 | squares and rotated squares ±1-2 ulps apart; a vertex nudged by ulps; a triangle apex ulps across an edge | 0 |
| convex-float | 3000 | generic convex pairs, **also against Shapely** | 0 (Shapely: 0) |
| general-grid | 8000 | unions of grid cells and half-cells: holes touching the shell at a point, parts touching at a point, vertical, horizontal and collinear edges everywhere; B = copy, shift, filled hole, superset, subset, mirror (7711 multipolygons) | 0 |
| general-float | 3000 | generic stars with holes, multipolygons, **also against Shapely** (predicates exact, areas within 1e-9 relative) | 0 (Shapely: 0) |
| extreme | 3000 | exact 2^k scalings from 2^-1074 (subnormal) to 2^600 | 0 disagreements; 691 cases at 2^510 and above hit F1 (all pass with the F1 fix) |
| edge | 45 | hand-made cases: identical, shared edge, corner touch, hole filled, hole touching shell, holes touching each other, island in hole, vertical/horizontal/sloped collinear overlaps, repeated points, ulp gap/overlap, 1e-300, subnormals, 1e150-1e300, 1e15 offset, -0.0, CW shell | 0; 5 are F1 crashes |
| seed.jsonl | 1000 | the shared smoke test | 0 |

5. **Mutation testing** (`mutants.py`) makes sure the checks above can actually fail.
   Nineteen single-line defects were planted in an in-memory copy of oracle.py, and the
   real oracle's baseline failures (the F1 crashes) were subtracted:
   - **Killed (all 13 that are not equivalent):** wrong sort keys, no sort, missing
     crossing events, strict slab membership, one-way `intersects`, a wrong `touches`,
     `overlaps` or `equals` formula, a wrong trapezoid factor, a missing fold-back test,
     a missing non-adjacent test.
   - **Survived, as predicted equivalent:** strict `crossing_x` bounds, the other
     half-open ray rule, a strict vertex test in `intersects`, a strict bbox prefilter.
   - **Survived, and equivalent on analysis:**
     - dropping `seg_intersect`'s collinear special cases (with closed rings, a
       collinear-only contact always comes with a non-collinear one at the end of the overlap);
     - the `point_in` boundary branch (unreachable);
     - `n < 2` instead of `n < 3` in `ring_simple` (the fold-back test catches n = 2).

## Leads for the library hunt (not oracle bugs)

These came up while testing. They are reproducible with Shapely 2.1.2 / GEOS 3.13.1.

- **GEOS predicates underflow.** `box(0,0,s,s)` vs `box(s/2,s/2,2s,2s)`:
  - s = 1e-150 is correct (`212101212`);
  - s = 1e-170, 1e-200 and 1e-300 give `relate = FF2FF1212` (disjoint);
  - edge case `tiny-1e-300` gives `touches=True`.

  The exact answer is `overlaps` (area s²/4 > 0).
- **GEOS `is_valid` underflow.** The valid polygon `[(0,0),(4,0),(4,4),(0,4)]` with hole
  `[(0,2),(2,1),(2,3)]`, which touches the shell at one point, is valid down to a scale of
  2^-520. Scaled *exactly* by 2^-540 it becomes "Hole lies outside shell". Valid grid
  multipolygons scaled by 2^-600 are reported "Self-intersection".

  compare.py flags this for single-ring inputs only; with F3's fix it would flag it for all.

## Files

- `indep.py`: independent exact implementation (general polygons, convex SH and SAT, ring simplicity).
- `indep_adapter.py`: FORMAT.md adapter around `indep.py` (`lib = indep-exact@oracle_review`).
- `check.py`: all oracle checks on a case file (`--shapely` for generic families, `--jobs`, `--out`).
- `gen_review.py`: case families above (`python gen_review.py all N SEED`).
- `ring_check.py`: ring_simple vs independent vs GEOS.
- `validity.py`, `validity_check.py`: proposed exact multi-ring validity (F3 fix) and its test against GEOS.
- `mutants.py`: mutation test of the harness.
- `timing.py`: run-time scaling (F5).
- `findings_cases.jsonl`: minimal cases for F1-F4 plus controls.

Large case files and outputs live in `/tmp/claude-0/gb-build/oracle-review/`.

Reproduce:

```sh
python gen_review.py all 2000 1 > /tmp/review.jsonl
python check.py /tmp/review.jsonl --jobs 2 --shapely --out /tmp/fail.json
python ring_check.py 60000 3
python validity_check.py 15000 1
python mutants.py /tmp/review.jsonl 25
python indep_adapter.py ../cases/seed.jsonl > /tmp/indep_seed.jsonl
python ../compare.py ../cases/seed.jsonl ../results/oracle/seed.jsonl /tmp/indep_seed.jsonl
```
