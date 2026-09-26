# Case generators (`gen/`)

A suite of case generators (Python 3, stdlib only) that write cases in the `FORMAT.md` format.
They target inputs that floating-point geometry code is known to get wrong. Every emitted
operand is a valid OGC geometry, checked exactly (see below), so any predicate disagreement
with `oracle.py` is a wrong answer from the library.

## Usage

```sh
python gen/run_all.py 300 1                  # cases/<family>.jsonl, 300 cases per family, seed 1
python gen/run_all.py 50 7 --families int-grid,multi-touch --outdir /tmp/x --stats
python gen/validate.py cases/hole-contact.jsonl ...   # re-check format, validity, contact stats
gen/pipeline.sh                              # oracle + shapely adapter + compare.py + summary
ADAPTER="adapters/clipper2/run.sh" LIB=clipper2 gen/pipeline.sh   # any other adapter
```

`pipeline.sh` writes to `RESULTS_DIR` (default `/tmp/claude-0/gb-build/generators/results`,
outside the repo). The layout is `oracle/<family>.jsonl`, `<LIB>/<family>.jsonl` and
`compare-<LIB>/<family>.jsonl` (the `compare.py --json` output). It runs `JOBS=2` families
in parallel and reuses oracle results that are newer than the case file. The whole
3000-case set takes about 3 s.

| file | what |
|---|---|
| `run_all.py` | driver: `run_all.py N SEED` writes every family (validity filter, dedup, stats) |
| `families.py` | the ten family generators |
| `common.py` | frames, ulp nudges, integer-lattice helpers, exact validity checker, rounding floor |
| `validate.py` | re-checks case files: format, validity, exact boundary-contact statistics |
| `summarize.py` | per-family / per-kind summary of `compare.py --json` output, with example ids |
| `pipeline.sh` | oracle + adapter + compare + summary for every family |

## Guarantees

- **Validity.** A single ring passes `oracle.valid_single_polygon`, which is exact. Anything with
  holes or several parts must pass both `common.exact_valid` and `shapely.is_valid`.
  `exact_valid` is an exact rational check: rings simple; each hole strictly inside its
  shell apart from at most one touch point per ring pair; no nested holes; the ring-touch
  graph is a forest, so the interior is connected; parts share no boundary segment and have
  zero-area intersection (via `oracle.overlay_areas`). It is conservative: three rings
  through one point are rejected. Over about 40k candidate geometries it agreed with GEOS
  3.13.1 on every one.
- **Exactness.** The exact families build everything on an integer lattice (`ExactFrame`),
  so points on edges, shared sub-edges and touch points are exact. The lattice maps to
  doubles by `x = (X + ox) * 2^e` with `|X + ox| < 2^53`, and `ExactFrame.pt` checks every
  coordinate with `fractions`. Designated on-edge vertices are also re-verified with the
  oracle's `orient`/`on_segment` on the final doubles. `validate.py` confirms it: every
  `vertex-on-edge` case has an exact vertex-on-boundary contact.
- **Determinism.** The same `N SEED` gives byte-identical files. Each family has its own
  random stream seeded with `"<family>:<SEED>"`.
- **Ids.** Ids take the form `<family>-<SEED>-<nnnnnn>-<variant>`. The variant says how the
  case was built, e.g. `hole-contact-1-000042-touch-in.n16.projected`: the `touch-in`
  variant, edge parameters m/16, projected frame. `scaled` ids embed the source family, its
  variant and the scale (`p2e-13` = 2^-13, `dec+3.6` = 10^3.6).
- **Normalisation.** Ring start vertex and orientation are randomised, as are part and hole
  order. Rings are closed, repeated consecutive points are removed, and coordinates are
  JSON floats. There are at most 300 vertices per case.
- **Area checks are meaningful** except where noted. `common.rounding_floor(a, b)` is
  `ulp(max|coord|) * (perimeter A + perimeter B)`, which bounds the area change from
  rounding every output vertex to the nearest double. `validate.py` counts cases where
  this floor exceeds compare.py's tolerance (`1e-6 * max(area A, area B)`). This happens
  only for `sliver-spike/sliver-pair`, where both operands are ulp-thin slivers (about 22
  of 300). Their predicates are still exact questions, but their areas are not evidence.
  `summarize.py` reports how many area disagreements are "beyond floor".

## Frames

- `FloatFrame` is used for floating-point constructions (rotations, lerps, ulp nudges):
  - `origin`: size about 1 at (0, 0).
  - `moderate`: centre in ±1000, size 1e-2..1e2.
  - `projected`: centre 1e5..1e7, size 1..1000 (metres).
  - `lonlat`: centre lon ±180 / lat ±85, size 1e-4..1. Coordinates are rounded to 12
    decimals, and nudges there are in units of 1e-12 instead of ulps.

  "Tiny" distances are 10^U(-15.6, -9) times the coordinate magnitude, so they run from
  about 1 ulp to 1e-9 relative and never vanish by rounding.
- `ExactFrame` is used for lattice constructions:
  - `unit`: 2^-b grid, b = 8..50, coordinates in ±1.
  - `int`: integers, local extent 2^6..2^30, offset at most 2^20 extents.
  - `projected` and `lonlat`: as above, on a 2^e grid 30..51 bits below the magnitude.

  All lattice coordinates have at most about 52 fractional bits. So Clipper-style scaling
  by 2^k, k <= 60, is exact for the lattice families (`vertex-on-edge`, most of
  `shared-edge`, `hole-contact`, `multi-touch` and `int-grid`). The float families often
  need more bits.

## Families

| family | what | variants (id) |
|---|---|---|
| `near-collinear` | a vertex a few ulps (or 1e-12 in lon/lat) off another polygon's edge; an edge bent by ulps; nearly collinear edges | `offedge-out`/`offedge-in` (B's apex at lerp(P,Q,t) ± k ulps, B outside/inside A), `bent-edge`/`bent-both` (P–M–Q with M ulps off PQ, B shares P and Q), `near-parallel` (B's edge endpoints ulps off A's edge line, overhanging), `zigzag` (chain of ulp-perturbed points along the edge), `extension` (B continues A's edge line beyond a vertex) |
| `vertex-on-edge` | vertices exactly on another polygon's sloped edge, at t = m/2^j (dyadic) or m/n on a lattice | `apex-out`, `apex-in`, `star-apex` (non-convex A), `cross` (B on both sides), `two-edges`, `inscribed` (all B vertices on A's edges or vertices), `on-vertex` |
| `shared-edge` | fully / partially shared collinear edges, sloped and exact, plus float variants | `full-opp`/`full-same`, `sub-opp`/`sub-same` (sub-segment), `overhang-*` (collinear partial overlap), `split` (different collinear split vertices), `chain` (convex lattice polygon cut by a lattice polyline), `chain-ulp` (B's chain 1 ulp off), `float-full` (shared edge between arbitrary doubles), `float-mid` (float-computed split point), `float-sub` (float-computed sub-segment) |
| `tiny-transform` | the same polygon moved by 1 ulp .. 1e-9 of the coordinate magnitude, at the origin, projected (1e5..1e7) and lon/lat (12 decimals) | `rot-vertex`, `rot-centroid`, `rot-far`, `shift-ulp`, `shift-abs`, `scale`, `rot-shift`, `same` (identical, different start/orientation); shapes `star`/`convex`/`rect`/`rotrect`/`parcel` |
| `sliver-spike` | near-zero-area parts of valid polygons, nearly coincident parallel edges | `spike-out`/`spike-in` (spike or crack of ulp..1e-8 width; B crosses it, sits at the tip, has a vertex at the tip, covers it, or lies beside it), `sliver-in`/`sliver-out`/`sliver-straddle` (thin B along A's edge), `parallel-gap`/`parallel-overlap` (B's edge parallel at a tiny offset), `needle-cross`, `sliver-pair` (two slivers crossing at 1e-12..1e-5 rad) |
| `hole-contact` | A has 1–2 holes; B fills, touches or nearly touches a hole boundary (A and B randomly swapped) | `fill` (B = hole), `fill-ulp-in`/`fill-ulp-out`/`fill-scaled`, `touch-in`/`touch-solid` (B's vertex exactly on a hole edge, inside the hole / in the solid), `share-in`/`share-solid` (shared sub-segment of a hole edge), `cross-near` (vertex ulps off a hole edge/vertex), `cover-hole-edge`, `hole-touch-shell-*` (hole touches its shell at one point, B at the pinch), `two-holes-touch-*`, `both-holed` (both operands have the same hole) |
| `multi-touch` | multipolygons whose parts touch at a point, with B at or around the touch point | `checker-*` / `chain-*` (tilted lattice squares touching at corners; B = a white cell, all white cells, a cell-sized square centred on the touch point, a band along the diagonal, one part, or a triangle with apex at the touch), `fan<k>-*` (k triangles around one apex; B in a gap, sharing edges, a box around the apex, one part, a band through the apex), `t-touch-*` (a part's vertex exactly on another part's edge), `island-*` (a part inside another part's hole touching it); `-rot` = the whole case rotated in floating point (exact touches become near) |
| `tiling-contact` | tiles of a rotated square / equilateral-triangle tiling, each computed by one of three formulas (`direct` O+iu+jv, `center`, `accum`), so shared edges agree only up to rounding | `sq-*`/`tri-*` × `edge`, `corner`, `same` (same tile, two formulas), `gap`/`overlap` (neighbour moved by ulps or a tiny distance), `multi` (A = tiles meeting at corners, B = the tile between), `strip` (A = 2–4 squares as one polygon with all tile corners, B = the square below) |
| `int-grid` | integer lattice families with many exact collinearities | `polyomino` (random cell sets traced into rings with every unit vertex; holes and parts touching at points come out as separate rings), `polyomino-merged` (collinear vertices removed), `lattice-poly` (simple polygons on a 2..32 grid, extra collinear lattice vertices, B sometimes a vertex subset of A), `lattice-tri-*` (triangles sharing an edge / vertex / vertex-on-edge); mapped by identity, a rotated integer lattice `[[a,-b],[b,a]]` or a shear; `small` (up to about 1e3), `big` (units 2^20..2^40, offsets up to 2^45) or `dyadic` (times 2^-k) |
| `scaled` | a case from any other family with all coordinates multiplied by 2^k (k in -27..27, exact) or 10^U(-8,8) (rounded: exact contacts become near) | id = `<source family>.<variant>.<p2eK or decX>` |

## Results: GEOS 3.13.1 (shapely 2.1.2), N = 300, seed 1

`gen/pipeline.sh` (compare.py kinds; the numbers are cases, not records). Nothing here is
triaged. "beyond floor" is explained under Guarantees.

| family | cases | cases with disagreement | predicate | area (beyond floor) | validity | error |
|---|---:|---:|---:|---:|---:|---:|
| near-collinear | 300 | 1 | 1 | 0 (0) | 0 | 0 |
| vertex-on-edge | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| shared-edge | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| tiny-transform | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| sliver-spike | 300 | 11 | 0 | 11 (0) | 0 | 0 |
| hole-contact | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| multi-touch | 300 | 3 | 3 | 0 (0) | 0 | 0 |
| tiling-contact | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| int-grid | 300 | 0 | 0 | 0 (0) | 0 | 0 |
| scaled | 300 | 5 | 4 | 1 (0) | 0 | 0 |
| total | 3000 | 20 | | | | |

A larger run outside the repo (`run_all.py 2000 2`) found 158 of 20000 cases with a
disagreement:

- 55 `multi-touch` predicate cases. Most are `t-touch-part`: B is exactly one part of a
  multipolygon whose parts touch vertex-to-edge. The oracle says within/contains; GEOS says
  overlaps.
- 12 `near-collinear` predicate cases.
- 5 `sliver-spike` predicate cases.
- 2 `tiling-contact` predicate cases, plus 1 area case beyond the rounding floor:
  `tiling-contact-2-001988-sq-multi.center-direct.origin`, where GEOS returns a union of
  area 3 for an exact 4 and B disappears from the overlay.
- 10 `scaled` predicate cases.
- The rest are ulp-thin `sliver-pair` area records, all within the rounding floor.
