# boost_geometry: Boost.Geometry 1.83 and develop

This directory has one C++ adapter source, `bg_adapter.cpp`. It is compiled twice by
`build.sh` and implements the adapter contract in `../../FORMAT.md`.

| variant | headers | `lib` field | run wrapper |
|---|---|---|---|
| 1.83 | the system Boost 1.83 from apt (`libboost-dev` 1.83.0.1ubuntu2) | `boost-geometry@1.83` | `run_1.83.sh` |
| develop | boostorg/geometry `develop` first on the include path; every other Boost library comes from the system 1.83 | `boost-geometry@develop-196d04c` | `run_develop.sh` |

- Pinned develop commit: `196d04c614c12a8d788212b63fa65d25c8b7ea86` (2026-08-17,
  "[doc] Fix \tparam names that do not match the declaration (#1486)"). To move the pin,
  set `BG_COMMIT=<sha>`.
- Compiler: g++ 13.3 on Ubuntu 24.04, with `-std=c++17 -O2 -DNDEBUG`. `NDEBUG` gives release
  semantics, so Boost asserts are off. Use `CXXFLAGS_EXTRA=-UNDEBUG` to turn them on; a
  failing assert then aborts the child process, and the adapter reports it as a crash.
- Robustness settings are the library defaults. In 1.83 that is
  `BOOST_GEOMETRY_NO_ROBUSTNESS` (no rescaling). In develop the rescaling code has been
  removed altogether.

## Files

| file | purpose |
|---|---|
| `bg_adapter.cpp` | the adapter: a small JSON reader, Boost.Geometry calls, and fork/timeout isolation |
| `build.sh` | fetches the pinned develop commit and builds both binaries (2 compilers at once, about 40 s) |
| `run_1.83.sh`, `run_develop.sh` | run wrappers: `run_X.sh CASES.jsonl > RESULTS.jsonl` |
| `compat/boost/core/invoke_swap.hpp` | a shim needed only by the develop build (see below) |

The build tree stays outside the repo, under `$BUILD_ROOT`
(default `/tmp/claude-0/gb-build/boost-geometry`). It holds `geometry/` (a shallow clone
at the pinned commit) and `bin/bg_adapter_{1.83,develop}`.

```sh
sudo apt-get install libboost-dev          # Boost 1.83 on Ubuntu 24.04
adapters/boost_geometry/build.sh
adapters/boost_geometry/run_1.83.sh    cases/seed.jsonl > /tmp/bg183.jsonl
adapters/boost_geometry/run_develop.sh cases/seed.jsonl > /tmp/bgdev.jsonl
python compare.py cases/seed.jsonl results/oracle/seed.jsonl /tmp/bgdev.jsonl
```

### Develop headers on top of Boost 1.83

The develop build puts `-I geometry/include` first, then `-I compat`, then the system
`/usr/include`. After compiling, `build.sh` runs `g++ -M` and fails if any
`boost/geometry` header was resolved from `/usr/include`. The last build resolved 808
Boost.Geometry headers from develop and none from the system.

Develop includes one header that Boost 1.83 does not have: `<boost/core/invoke_swap.hpp>`.
It was added in Boost.Core 1.84, when `boost::swap` was renamed to
`boost::core::invoke_swap`. `compat/` provides it as a thin wrapper over the 1.83
`boost_swap_impl::swap_impl`. It is used only by the geographic Karney formula and the
rtree allocators, and neither is on the planar polygon paths tested here. No other
header is missing.

## What is computed

Types: `bg::model::polygon<bg::model::d2::point_xy<double>, /*ClockWise=*/false, /*Closed=*/true>`
and `bg::model::multi_polygon` of that polygon. Following FORMAT.md, a case with exactly
one part becomes a `polygon`, and anything else becomes a `multi_polygon`. The four
type combinations are dispatched through `std::variant`.

| field | Boost.Geometry call |
|---|---|
| `valid_a`, `valid_b` | `bg::is_valid(g, message)`. The message appears with `--reasons` |
| `intersects` `disjoint` `touches` `overlaps` | `bg::intersects(a,b)` … `bg::overlaps(a,b)` |
| `within`, `covered_by` | `bg::within(a,b)`, `bg::covered_by(a,b)` |
| `contains`, `covers` | `bg::within(b,a)`, `bg::covered_by(b,a)`. Boost.Geometry has no contains or covers |
| `equals` | `bg::equals(a,b)` |
| `area_inter` `area_union` `area_diff` `area_symdiff` | `bg::area` of the `multi_polygon` output of `bg::intersection` / `bg::union_` / `bg::difference(a,b)` / `bg::sym_difference` |

Coordinates are parsed with glibc `strtod`, which rounds correctly, and are passed
straight to the point constructors. No WKT round trip is involved. A third ordinate,
if present, is ignored. Output areas are printed with `std::to_chars` in the shortest
form that round-trips. The area is reported as returned, without `abs()`, so a
wrongly oriented output ring shows up as a wrong area.

### Orientation (instead of `bg::correct`)

Boost.Geometry needs every ring to have the orientation declared by the polygon type.
The type here is counter-clockwise, as for GeoJSON (RFC 7946) shells. It is closed,
because the case rings are closed. The case files do contain rings of both
orientations; for example, B in `shared-sloped-edge` is clockwise. The adapter
determines each ring's orientation **exactly**: it takes the turn at the
lowest-then-leftmost vertex and computes it with `boost::multiprecision::cpp_rational`,
falling back to the exact signed area when that turn is degenerate. It then reverses
any ring that disagrees with the type (a CCW shell or a CW hole is required). This is
what `bg::correct()` does to a closed ring. The difference is that `bg::correct()`
decides with the floating-point area, which could misjudge a sliver ring. The case
data is left untouched; only the Boost geometry built from it is reoriented.

`BG_ADAPTER_ORIENT=correct` uses `bg::correct()` instead, and `BG_ADAPTER_ORIENT=none`
feeds the rings as they are. Both are for triage only. On `seed.jsonl`, `correct` and
`exact` give identical output in both variants.

`--reasons` adds two fields that are not part of the contract:
`"valid_reasons": {"valid_a": <bg::is_valid message>, ...}` and
`"reversed_rings": {"a": n, "b": m}`.

## Errors and robustness

The design is the same as in `../geos_main`:

- Exceptions are caught per operation. The field is `null`, and
  `errors[key] = "<demangled exception type>: <what()>"`, for example
  `boost::geometry::overlay_invalid_input_exception: ...`. A non-finite area is reported
  the same way (`std::range_error`).
- Each case runs in a forked child, which streams each operation's result to the parent.
  If the child dies from a signal, that one operation gets
  `"crash: process killed by signal 11 (Segmentation fault)"`, and a new child continues
  with the next operation. If an operation gives no result within `BG_ADAPTER_TIMEOUT`
  seconds (default 10), the child is killed, and the field gets `"timeout: ..."` and is
  listed in `errors.timeout`. Each child's address space is limited to
  `BG_ADAPTER_MEM_MB` MiB (default 4096, 0 turns the limit off).
- A line that cannot be parsed produces a line with every field `null` and
  `errors.parse`. Blank lines produce no output.
- `--no-fork` runs everything in-process. It gives byte-identical output on the seed file.
  `BG_ADAPTER_TEST_FAULT=crash:<key>|hang_:<key>|throw:<key>` injects a fault, which is
  only for testing the isolation. All three were tested.

Speed: 1000 seed cases take about 0.5 s per variant, including one fork per case.

## Seed smoke test (cases/seed.jsonl, 1000 cases)

| | 1.83 | develop |
|---|---|---|
| disagreements | 229 over 76 cases | 249 over 82 cases |
| `error` / `validity` | 0 / 0 | 0 / 0 |
| `rotated-neighbours`: intersects/disjoint/touches, with a gap of a few ulps reported as touching | 57 × 3 | 57 × 3 |
| `tiny-rotation(-offset)`: overlaps=false, within/covered_by/contains/covers=true when B is A rotated by 1e-16 to 1e-8 rad about a vertex | 54 | 69 |
| `tiny-rotation`: `equals` true for rings about 2e-16 apart (collected-vectors tolerance) | 4 | 4 |
| `rotated-neighbours-1-000230`: within/covered_by=true, overlaps=false, and 2 gross `area` errors | 0 | 3 + 2 |

For comparison, GEOS/shapely has 0 disagreements on the same file.

Develop regression (not in 1.83): `rotated-neighbours-1-000230` consists of two unit
squares whose overlap is 3.9e-16. Develop returns `within(a,b) = true` and an
intersection of area 0.9999999999999997 (all of A), and `union_` has area 1.0 instead of
2.0. I reproduced this with a standalone program that uses `bg::read_wkt`, the
*default* clockwise polygon type and `bg::correct`, so the adapter plays no part in it.
1.83 gives 0 and 2. The overlay traversal in develop is new graph-based code
(`algorithms/detail/overlay/graph/`, which does not exist in 1.83). When the develop
build compiles `select_edge.hpp:75`, g++ warns `-Wuninitialized`: in
`walk_to_point_after_turn`, `point` is read if `copy_segment_point` does not set it. I
have not checked whether this is connected to the regression. `within` is also wrong in
that case, and it goes through relate, not the overlay traversal. So the cause is more
likely in code the two share (turn and segment-intersection computation) than in the
traversal alone.

## Notes and caveats

- Predicates and overlays are always computed, even when an input is invalid.
  `compare.py` ignores everything except validity for invalid inputs.
- `bg::equals` for Cartesian polygons does not use DE-9IM. It compares the areas and
  then the sorted "collected vectors" (edge directions), and those comparisons use a
  tolerance. `touches` and `overlaps` go through relate. `within` and `covered_by` use
  the relate-based areal/areal implementation.
- An unclosed input ring is kept as it is, since the type says Closed=true. `bg::is_valid`
  then reports it invalid. FORMAT.md requires closed rings anyway.
- NaN or infinite coordinates are accepted by the parser (`strtod`). `bg::is_valid` reports
  them invalid, and the other fields hold whatever Boost returns.
