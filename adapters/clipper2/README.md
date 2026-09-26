# Clipper2 adapter (`clipper2`)

Adapter for [AngusJohnson/Clipper2](https://github.com/AngusJohnson/Clipper2) (C++, int64
boolean operations), built from git `main` at a pinned commit. It follows the contract in
`../../FORMAT.md`.

`lib` is `clipper2@<version>-<short commit>`, currently `clipper2@2.0.1-f9c5eb6`. Variants
append a suffix: `+nonzero`, `+pathsd8`, `+strict`, `+scale<B>`.

## Files

| file | what |
|---|---|
| `clipper2_adapter.cpp` | the adapter (built-in JSON reader, exact scaling and areas, forked worker) |
| `build.sh` | clones Clipper2 at the pinned commit and compiles with `g++ -O2` (`JOBS`, default 2) |
| `run.sh` | runs the adapter: `run.sh [options] CASES.jsonl > RESULTS.jsonl` |
| `gen_int_cases.py` | generator for `int_cases.jsonl` (`python gen_int_cases.py [N_PER_FAMILY] [SEED]`, defaults 12 and 1) |
| `int_cases.jsonl` | 204 integer-coordinate near-degenerate cases, 17 families of 12 |
| `repro_small_triangle.cpp` | stand-alone repro of the small-triangle finding below, calling only the Clipper2 API |

The build tree is `$BUILD_ROOT` (default `/tmp/claude-0/gb-build/clipper2`), outside the repo:
`src/` (the clone), `obj/` (library objects), and `bin/clipper2_adapter` plus
`bin/repro_small_triangle`. `CLIPPER2_COMMIT=main build.sh` builds whatever `main` is now,
and the `lib` string records the commit.

## What each field is

**Scaling.** Clipper64 works on int64, so each case is scaled by 2^k: the smallest k
(0 <= k <= 60) that makes every coordinate of both operands an integer. That is exact for
doubles. If there is no such k, or a scaled coordinate has magnitude >= 2^62, the case gets
every field `null` and `errors.unsupported = "non-dyadic or out of range"`. Clipper2's
documented `MAX_COORD` is `INT64_MAX >> 2` = 2^61 - 1. The adapter accepts [2^61, 2^62) as
asked, marks such cases with the extra field `"over_max_coord": true`, and `--strict-range`
makes them unsupported instead. Coordinate differences still fit in int64 below 2^62.

**Geometry.** Every ring of every polygon (shells and holes) becomes one `Path64`, with the
closing point dropped. A is the subject and B is the clip, with `FillRule::EvenOdd` (correct
for valid OGC input). `--fill nonzero` first orients shells CCW and holes CW, using an exact
orientation test, then uses `FillRule::NonZero`.

**Areas.** `area_inter/union/diff/symdiff` come from `Clipper64::Execute` with
`Intersection/Union/Difference/Xor` and `Paths64` output. The area is the signed shoelace sum
over all result paths (holes come out negative), accumulated exactly (int128 products in a
192-bit accumulator), rounded once, then divided by 4^k. So the area adds no error of its own
beyond one final rounding. If `Execute` returns `false` or throws, the field is `null` and the
message goes in `errors`.

**Predicates.** `valid_a` and `valid_b` are `null`, since Clipper2 has no validity check.
`touches` through `equals` are `null`. `intersects` = (Clipper's intersection area > 0) OR
(the boundaries meet), and `disjoint` = not `intersects`. "The boundaries meet" is tested
exactly with Clipper2's own exact primitives:

- `PointInPolygon(...) == IsOn` for every vertex of each operand against every ring of the
  other;
- a proper crossing of an edge pair, from `CrossProductSign`, which uses int128 and is exact
  below 2^62.

Every contact that adds no area produces one of these. So `intersects` is exact whenever
Clipper's intersection area is right, and a disagreement means Clipper produced a spurious or
missing intersection where the boundaries do not meet. The contact result is also in the
extra field `boundaries_meet`.

**Extra fields** (compare.py ignores them): `scale_log2` (k), `min_scale_log2` (only with
`--scale-bits`), `over_max_coord`, `boundaries_meet`. With `--dump-paths` it also adds
`paths_inter/union/diff/symdiff`, the result paths in scaled integer coordinates.

## Options

- `--fill nonzero`: NonZero fill rule with oriented rings (default EvenOdd).
- `--pathsd8`: runs `ClipperD(8)` on `PathsD` instead of Clipper64. Note that ClipperD does not
  scale by 10^8: it scales by `2^(ilogb(10^8)+1)` = 2^27 (Clipper2 issue #25). The run is exact
  only when every coordinate times 2^27 is an integer below 2^53, which also makes the way back
  to double exact. Other cases get `errors.unsupported = "not exact in ClipperD precision 8"`.
  Result coordinates are multiplied back by 2^27, exactly, and measured the same way as above.
- `--scale-bits B` (1..62): scale by the largest 2^k (at least the smallest valid k) that keeps
  every scaled coordinate below 2^B. This gives a finer snapping grid. See the caveat below.
- `--strict-range`: unsupported beyond `MAX_COORD` (2^61 - 1).
- `--timeout S` (default 10), `--no-fork`, `--dump-paths`, `--version`.

**Isolation.** The adapter reads all cases, then a forked worker runs them in order and pipes
each line back. If the worker crashes, that case gets `errors.crash` (the signal), and a new
worker continues with the next case. A case running over the budget is killed and gets
`errors.timeout`. `--no-fork` runs in-process and gives identical output. Two self-test hooks
exist: `CLIPPER2_ADAPTER_TEST_CRASH_ID=<id>` makes the worker segfault on that case, and
`CLIPPER2_ADAPTER_TEST_HANG_ID=<id>` makes it hang there.

## Caveat: snapping to the integer grid

Clipper64 rounds every new intersection point to an integer. Under the smallest-k scaling, the
grid is therefore the input's own finest dyadic unit. For typical double input (seed:
k = 53..57) that is ~1e-16 of the shape. For integer input with small coordinates (k = 0)
it is a whole unit. For example, two random lattice polygons of size ~5 come out with areas
off by ~10%. That is Clipper's design, not a bug, but compare.py reports it as `area`.

So:

- cases for this adapter should either span >= ~2^30 units, or have exact results whose
  vertices are all input-grid points;
- or run with `--scale-bits 53` (or 61), which removes this effect. On 60 random lattice
  polygon pairs of size 6, k = 0 gives 214 `area` disagreements and `--scale-bits 53` gives 0.

## `int_cases.jsonl`

These cases are integer and exactly representable, so they run at k = 0. They stay fair under
the 1e-6 tolerance: every shape is fat and >= 2^33 units across (except in
`int-thin-triangle`, where every exact result vertex is a lattice point), and the degeneracies
are at unit scale. The families:

- **shared edges and vertices:** shared sloped edges (touch or overlap), vertex exactly on an
  edge, vertex-to-vertex touch, collinear vertex chains, identical inputs (same, rotated
  start, reversed, collinear points inserted);
- **near misses:** a vertex one unit off an edge, lattice polygons with one vertex jittered by
  one unit;
- **thin angles:** edges crossing at slopes of 1..9 units over 2^36..2^52, nearly parallel
  long edges;
- **holes and multipolygons:** a hole equal to B, a hole shifted by one unit, a hole touching
  its shell at a point, multipolygon parts touching at a corner;
- **large coordinates:** coordinates near 2^60 (inside `MAX_COORD`), and in [2^61, 2^62)
  (`int-beyond-maxcoord`, outside the documented range);
- **thin triangles:** long triangles whose short side is 1 unit (`int-thin-triangle`).

Validity is checked with shapely. Exact answers come from `python oracle.py int_cases.jsonl`.

Results at `clipper2@2.0.1-f9c5eb6` (compare.py, all 204 cases):

| run | disagreements |
|---|---|
| default (EvenOdd, smallest k) | 25, all `area`, all 12 `int-thin-triangle` cases |
| `--fill nonzero` | the same 25 |
| `--strict-range` | the same 25, plus 12 `unsupported` (`int-beyond-maxcoord`) |
| `--scale-bits 53`, `--scale-bits 61` | 0 |
| `--pathsd8` | 196 `unsupported`; the 8 eligible (small thin triangles) agree |
| shapely (GEOS 3.13.1), for reference | 0 |

There are no `intersects`/`disjoint` disagreements in any run.

## Finding: triangles with two vertices one unit apart are deleted, whatever their size

`clipper.engine.cpp` defines `IsVerySmallTriangle` (line ~441). It is true for any 3-vertex
output ring in which some two vertices are within 1 unit in both x and y (`PtsReallyClose`:
`|dx| < 2 && |dy| < 2`). The area is never checked. Such rings are discarded:

- in `CleanCollinear`, through `IsValidClosedPath` (lines 1529 and 1548);
- in `BuildPath64` and `BuildPathD` (lines 2914 and 3088).

A long thin triangle of any area therefore vanishes from every result. `repro_small_triangle`
shows this with the plain API:

- `Union({(0,0), (1,0), (0,2^40)})` (a valid triangle of area 2^39) returns nothing.
- `Intersect(tri, tri)` returns nothing too.
- With A = [(0,1), (2^44,1), (2^44,-2^44-1), (0,-2^44+1)] and B = [(0,0), (2^44,2), (2^44,2^44),
  (0,2^44)], the exact A∩B is the lattice triangle (0,0), (0,1), (2^43,1), of area 2^42.
  `Intersect` returns nothing, while `Difference(A,B)` correctly removes exactly that triangle.
  So |A∩B| + |A−B| != |A|.

It is a gross error when the thin triangle is most of the input: the 12 `int-thin-triangle`
cases. It is sub-tolerance but still inconsistent when the triangle is a sliver of fat
operands. Snapping turns the exact intersection into such a triangle, which is then deleted
whole: this happens in `int-thin-crossing-1-0003` (area 2^34), five `int-near-parallel-large`
cases (up to ~1.1e15) and two `int-near-miss` cases.

Root cause check: a copy of the library patched so that `IsVerySmallTriangle` returns `false`
(built by hand, not by build.sh) gives 0 disagreements on `int_cases.jsonl`. It also gives
exact thin-triangle areas and no result with exact area > 0 where Clipper returned 0. The
unpatched library has 35 of those. The seed is unchanged. Under smallest-k scaling, a double-coordinate triangle whose short
side is one unit of 2^-k is affected as well. `--scale-bits` and ClipperD (which scales by
2^27) avoid it, because the short side becomes >= 2 units. It is not reported upstream from
here.

## Seed smoke test

`run.sh cases/seed.jsonl` gives 1000 lines. compare.py reports 15 disagreements, all
`error unsupported`: `tiny-rotation` cases whose coordinates need k > 60. There are 0 `area`
and 0 predicate disagreements. The same holds for `--fill nonzero`, `--strict-range`,
`--no-fork` and `--scale-bits 61`. With `--pathsd8`, the 250 `shared-sloped-edge` cases are
eligible and agree, and the other 750 are `unsupported`. The largest relative area error is
~4e-16 on the unit-size families. On `tiny-rotation-offset` it is ~1.5e-9, which is snapping
to the 2^-29 grid of coordinates near 1e7.
