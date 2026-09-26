# boost_geometry: Boost.Geometry 1.83, develop and the latest release

This directory has one C++ adapter source, `bg_adapter.cpp`. It is compiled three times by
`build.sh`:

| target | headers | `lib` field | run wrapper |
|---|---|---|---|
| `boost-1.83` | the system Boost 1.83 from apt (`libboost-dev` 1.83.0.1ubuntu2) | `boost-geometry@1.83` | `run_1.83.sh` |
| `boost-develop` | boostorg/geometry `develop` first on the include path; every other Boost library comes from the system 1.83 | `boost-geometry@develop-196d04c` | `run_develop.sh` |
| `boost-release` | boostorg/geometry at tag `boost-1.92.0` (`90c27ef0bf9d1700f553b85f890f43461eced529`, 2026-07-02), the newest release tag, the same way | `boost-geometry@1.92` | `run_release.sh` |

- Pinned develop commit: `196d04c614c12a8d788212b63fa65d25c8b7ea86` (2026-08-17,
  "[doc] Fix \tparam names that do not match the declaration (#1486)"). To move the pin,
  set `BG_COMMIT=<sha>`; the release is `BG_RELEASE_TAG` / `BG_RELEASE_COMMIT` (build.sh
  checks that the tag resolves to the pinned commit).
- The release build is Boost.Geometry 1.92.0 on top of the other Boost 1.83 libraries, as
  the develop build is: it is the Geometry library of the latest release, not a full Boost
  1.92.
- Compiler: g++ 13.3 on Ubuntu 24.04, with `-std=c++17 -O2 -DNDEBUG`. `NDEBUG` gives release
  semantics, so Boost asserts are off. Use `CXXFLAGS_EXTRA=-UNDEBUG` to turn them on; a
  failing assert then aborts the child process, and the adapter reports it as a crash.
- Robustness settings are the library defaults. In 1.83 that is
  `BOOST_GEOMETRY_NO_ROBUSTNESS` (no rescaling). In develop and 1.92.0 the rescaling code has
  been removed altogether, and the overlay traversal is the new graph-based code
  (`algorithms/detail/overlay/graph/`).

The adapter answers both adapter contracts, line by line:

- **v2** ([DESIGN.md §4.1](../../docs/DESIGN.md), `schemas/result.v2.schema.json`): a line
  whose operands are typed geometries or that has `"ops"`; `--v2` answers legacy lines this
  way too. See "Contract v2" below.
- **v1** (`../../harness/FORMAT-v1.md`): a legacy line, answered by the v1 code, unchanged:
  v1 output of the 1.83 and develop builds is byte-identical to the adapter before the v2
  upgrade (checked on 1804 cases, `--reasons` included).

## Files

| file | purpose |
|---|---|
| `bg_adapter.cpp` | the adapter: a small JSON reader, Boost.Geometry calls, fork/timeout isolation (v1), and the v2 session on top of `../geos_main/adapter_v2.hpp` |
| `adapter.toml` | manifest (DESIGN.md §4.2) for the three targets: fields, precision model, tolerances, options |
| `build.sh` | fetches the pinned develop commit and the release tag, builds the three binaries (at most `JOBS`=2 compilers at once, about 90 s and 1.5 GB each) |
| `run_1.83.sh`, `run_develop.sh`, `run_release.sh` | run wrappers: `run_X.sh CASES.jsonl > RESULTS.jsonl` |
| `compat/boost/core/invoke_swap.hpp` | a shim needed by the develop and release builds (see below) |

The build tree stays outside the repo, under `$BUILD_ROOT` (default
`$GEOTRUTH_BUILD_DIR/boost-geometry`, where `GEOTRUTH_BUILD_DIR`, shared by every adapter,
defaults to `~/.cache/geotruth`). It holds `geometry/` (a shallow clone at the pinned
develop commit), `geometry-release/` (the release tag) and `bin/bg_adapter_{1.83,develop,release}`.
`VARIANTS="1.83"` (etc.) builds a subset.

```sh
sudo apt-get install libboost-dev          # Boost 1.83 on Ubuntu 24.04
adapters/boost_geometry/build.sh
adapters/boost_geometry/run_1.83.sh    corpus/cases/seed.jsonl > /tmp/bg183.jsonl
adapters/boost_geometry/run_release.sh --v2 corpus/cases/seed.jsonl > /tmp/bgrel.v2.jsonl
python harness/compare.py corpus/cases/seed.jsonl corpus/expected-v1/seed.jsonl /tmp/bg183.jsonl
```

### Develop and release headers on top of Boost 1.83

The develop and release builds put `-I geometry/include` (or `geometry-release/include`)
first, then `-I compat`, then the system `/usr/include`. After compiling, `build.sh` runs
`g++ -M` and fails if any `boost/geometry` header was resolved from `/usr/include`. The last
build resolved 808 Boost.Geometry headers from develop (and 808 from 1.92.0), 1691 other
Boost headers from the system, and none of Boost.Geometry from the system.

Both include one header that Boost 1.83 does not have: `<boost/core/invoke_swap.hpp>`.
It was added in Boost.Core 1.84, when `boost::swap` was renamed to
`boost::core::invoke_swap`. `compat/` provides it as a thin wrapper over the 1.83
`boost_swap_impl::swap_impl`. It is used only by the geographic Karney formula and the
rtree allocators, and neither is on the planar paths tested here. No other header is
missing.

## Contract v2

Geometry types: `point_xy<double>`, `linestring`, `polygon<point_xy<double>, ClockWise=false,
Closed=true>`, `multi_point`, `multi_linestring`, `multi_polygon`, one per JSON type, held in a
`std::variant` and dispatched pairwise. Polygon rings are re-oriented exactly as in v1 (below).

| field | Boost.Geometry call |
|---|---|
| `relate` | `bg::relation(a, b).str()` |
| `predicates.intersects` `disjoint` `touches` `crosses` `overlaps` `within` `covered_by` `equals` | `bg::intersects(a,b)` … `bg::equals(a,b)` |
| `predicates.contains`, `predicates.covers` | `bg::within(b,a)`, `bg::covered_by(b,a)` (derived: Boost.Geometry has no contains or covers) |
| `valid_a`, `valid_b` | `bg::is_valid` |
| `overlay.<op>` | `bg::intersection` / `bg::union_` / `bg::difference(a,b)` / `bg::sym_difference` into a `multi_polygon`: the **regularized areal** overlay, for Polygon/MultiPolygon pairs only |
| `echo` | the operands as Boost geometries, read back with `bg::get` |

**Which type pairs are supported** is decided at compile time from Boost's own dispatch:
the adapter defines `BOOST_GEOMETRY_IMPLEMENTATION_STATUS_BUILD` (which turns Boost's
`not_implemented<...>` static assertion into a complete tag type; it changes no algorithm)
and asks `std::is_base_of<nyi::not_implemented_tag, dispatch::X<G1, G2>>` for `relate`,
`disjoint` (intersects), `touches`, `crosses`, `overlaps`, `within`, `covered_by` and
`equals`. A pair Boost does not implement is `"unsupported"`, never a compile error or a
guess. With the six types, all 36 pairs support relate and the predicates except
`within`/`covered_by` (and so `contains`/`covers`) where the first operand has the higher
dimension; this holds for all three builds.

**Out of contract** (every field of the pair `"unsupported"`, except `echo` and the other
operand's validity): a GeometryCollection, an empty Point, or an empty point inside a
MultiPoint, which the Boost models cannot represent. Overlay of any pair other than
areal/areal is `"unsupported"` (lines and points are not in this adapter's overlay contract).
Boost ≥ 1.80 has partial GeometryCollection support (relate, within, covered_by, equals,
touches, crosses, overlaps through dynamic geometries); the adapter does not exercise it
yet, so GC cases say `"unsupported"` and are never scored against Boost.

**Output coordinates are written by the adapter** from the Boost result (`bg::get<0>`,
`bg::get<1>`), never through `bg::wkt` (whose stream precision defaults to 6 digits): each
double with `std::to_chars`, the shortest round-trip form. One output polygon is a Polygon,
none is `POLYGON EMPTY`, more are a MultiPolygon.

Isolation, errors and the output line are those of `../geos_main/adapter_v2.hpp`: one forked
child per case that streams each operation's result; a crash or hang fails that one
operation with `{"kind": "crash" | "timeout", ...}` and a fresh child continues;
`std::bad_alloc` is `{"kind": "memory", ...}`; an exception is `"<demangled type>: <what()>"`.
`--timing` adds `elapsed_ms`; `--no-fork` runs in-process.

## Contract v1: what is computed

Types: `bg::model::polygon<bg::model::d2::point_xy<double>, /*ClockWise=*/false, /*Closed=*/true>`
and `bg::model::multi_polygon` of that polygon. Following FORMAT-v1.md, a case with exactly
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
wrongly oriented output ring shows up as a wrong area. Note that `bg::area` is a double
shoelace sum: at large coordinates its own rounding shows (on
`tiny-rotation-offset-1-000001`, coordinates near 1e7, the intersection geometry has exactly
the oracle's area but `bg::area` of it is off by 4.5e-10); v2 reports the geometry instead.

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
data is left untouched; only the Boost geometry built from it is reoriented. v2 does the
same for every polygon.

`BG_ADAPTER_ORIENT=correct` uses `bg::correct()` instead, and `BG_ADAPTER_ORIENT=none`
feeds the rings as they are. Both are for triage only. On `seed.jsonl`, `correct` and
`exact` give identical output in both variants.

`--reasons` adds two fields that are not part of the v1 contract:
`"valid_reasons": {"valid_a": <bg::is_valid message>, ...}` and
`"reversed_rings": {"a": n, "b": m}`.

## Errors and robustness (v1)

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
  only for testing the isolation; `<key>` is a v1 field name or a v2 field path.

Speed: 1000 seed cases take about 0.5 s (v1) and 0.9 s (v2) per build, forks included.

## Seed smoke test (corpus/cases/seed.jsonl, 1000 cases)

| | 1.83 | develop | 1.92.0 |
|---|---|---|---|
| disagreements (v1, compare.py) | 229 over 76 cases | 249 over 82 cases | 249 over 82 cases |
| `error` / `validity` | 0 / 0 | 0 / 0 | 0 / 0 |
| `rotated-neighbours`: intersects/disjoint/touches, with a gap of a few ulps reported as touching | 57 × 3 | 57 × 3 | 57 × 3 |
| `tiny-rotation(-offset)`: overlaps=false, within/covered_by/contains/covers=true when B is A rotated by 1e-16 to 1e-8 rad about a vertex | 54 | 69 | 69 |
| `tiny-rotation`: `equals` true for rings about 2e-16 apart (collected-vectors tolerance) | 4 | 4 | 4 |
| `rotated-neighbours-1-000230`: within/covered_by=true, overlaps=false, and 2 gross `area` errors | 0 | 3 + 2 | 3 + 2 |

For comparison, GEOS/shapely has 0 disagreements on the same file. The 1.92.0 build gives
exactly the develop answers on every seed case (v1) and on all 1804 cases of the broader
check (v2): the develop regression below shipped in 1.92.0.

`--v2` on the seed: predicates and validity are the v1 values, the overlay geometries have
the v1 areas up to `bg::area`'s rounding, and the disagreements with the exact answer are
exactly the v1 ones (`tests/harness/test_native_seed.py`). On 1804 cases (seed + generator
families + `int_cases.jsonl`) v2 has no disagreement v1 lacks and three fewer, all of them
`bg::area` rounding on output geometries that are right (`int-thin-triangle-1-0004`,
`-0009`, `sliver-spike-7-000056`).

Develop regression (not in 1.83; present in 1.92.0): `rotated-neighbours-1-000230`
consists of two unit squares whose overlap is 3.9e-16. Develop returns `within(a,b) =
true` and an intersection of area 0.9999999999999997 (all of A), and `union_` has area 1.0
instead of 2.0. I reproduced this with a standalone program that uses `bg::read_wkt`, the
*default* clockwise polygon type and `bg::correct`, so the adapter plays no part in it.
1.83 gives 0 and 2. The overlay traversal in develop is new graph-based code
(`algorithms/detail/overlay/graph/`, which does not exist in 1.83). When the develop
build compiles `select_edge.hpp:75`, g++ warns `-Wuninitialized`: in
`walk_to_point_after_turn`, `point` is read if `copy_segment_point` does not set it. I
have not checked whether this is connected to the regression. `within` is also wrong in
that case, and it goes through relate, not the overlay traversal. So the cause is more
likely in code the two share (turn and segment-intersection computation) than in the
traversal alone.

## Observations (untriaged, not findings)

- Output structure: on the 1804-case broader check, the typed structure of Boost's overlay
  result (each shell minus its holes) and the even-odd point set of the same rings differ in
  area by more than 1e-6 of the operands in 6 outputs of 1.83
  (`hole-contact-7-000051-fill-ulp-in.n32.projected` union and symdifference,
  `int-thin-triangle-1-0009` union, `multi-touch-7-000029-island-apex.int` symdifference,
  `shared-edge-7-000032-float-mid.origin` symdifference,
  `tiny-transform-7-000041-shift-ulp.parcel.origin` intersection) and 2 of develop and
  1.92.0 (the `hole-contact-7-000051` pair): rings nested or oriented other than the
  multi_polygon says. The v2 output reports the rings as Boost returns them; the scorer
  measures them by even-odd (DESIGN.md §4.3). Not triaged; see `findings/registry.toml`.

## Notes and caveats

- Predicates and overlays are always computed, even when an input is invalid.
  `compare.py` ignores everything except validity for invalid inputs.
- `bg::equals` for Cartesian polygons does not use DE-9IM. It compares the areas and
  then the sorted "collected vectors" (edge directions), and those comparisons use a
  tolerance. `touches` and `overlaps` go through relate. `within` and `covered_by` use
  the relate-based areal/areal implementation.
- Boost's `crosses`, `overlaps` and `touches` apply their DE-9IM masks by the *static*
  dimension of the C++ type (a `linestring` whose points coincide is still linear), where
  DESIGN.md §1 dispatches on the real dimension.
- Empty geometries: `bg::is_valid` reports an empty linestring or polygon invalid (OGC and
  GEOS: valid), and `bg::relation(POINT(1 1), POLYGON EMPTY)` is `FF0FFF212` (GEOS:
  `FF0FFFFF2`). These are Boost's answers, reported as such; the empty-geometry convention
  table decides how they are scored.
- An unclosed input ring is kept as it is, since the type says Closed=true. `bg::is_valid`
  then reports it invalid. FORMAT-v1.md requires closed rings anyway.
- NaN or infinite coordinates are accepted by the parser (`strtod`). `bg::is_valid` reports
  them invalid, and the other fields hold whatever Boost returns.
