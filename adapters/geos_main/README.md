# geos_main: GEOS git main and the latest GEOS release, via the C API

This adapter runs GEOS through the reentrant GEOS C API (`geos_c.h`, `*_r` functions,
`GEOS_USE_ONLY_R_API`). One source is built twice by `build.sh`:

| target | GEOS | `lib` field | build | run wrapper |
|---|---|---|---|---|
| `geos-main` | git `main` at `ae9cdd98be4e0bae552b918d4d14c94a9ce99c58` (2026-09-21, "Update NEWS.md"), `Version.txt` 3.16.0dev, C API 1.22.0 | `geos@3.16.0dev-ae9cdd9` | `build.sh main` (the default) | `run.sh` |
| `geos-release` | tag `3.15.0` = `d0228513abb0c29c185443cf2bfb06c9281024b5` (2026-09-01), the newest release tag (`git ls-remote --tags`), C API 1.21.0 | `geos@3.15.0` | `build.sh release` | `run_release.sh` |

The `lib` string is built at run time from `GEOSversion()` and, where it exists (C API
1.22, i.e. 3.16dev, and later), `GEOSrevision()`; a release without `GEOSrevision()` is
named by its version alone. Build: CMake Release, `-DBUILD_TESTING=OFF`, `-j2`, gcc 13.3 and
cmake 3.28 on Ubuntu 24.04. The library is built once per commit; later runs of `build.sh`
only recompile the adapter (a few seconds).

The adapter answers both adapter contracts, line by line:

- **v2** ([DESIGN.md §4.1](../../docs/DESIGN.md), `schemas/result.v2.schema.json`): a line
  whose operands are typed geometries (`{"type": ..., "coordinates" | "geometries": ...}`)
  or that has `"ops"`. `--v2` answers legacy lines this way too.
- **v1** (`../../harness/FORMAT-v1.md`): a legacy line (multipolygon arrays). Answered by the
  v1 code, unchanged: v1 output is byte-identical to the adapter before the v2 upgrade
  (checked on 1804 cases: the seed, 60 cases of each generator family, `int_cases.jsonl`).

## Files

| file | purpose |
|---|---|
| `geos_adapter.c` | driver (C11): reads lines, sends v2 lines to `geos_adapter_v2.cpp`, answers v1 lines itself |
| `geos_adapter_v2.cpp` | contract v2 (C++17 over the same C API): builds every type, runs the operations, writes the geometries back |
| `adapter_v2.hpp` | the contract-v2 runtime shared by the four native adapters (`geos_main`, `boost_geometry`, `clipper2`, `cgal`): JSON reader, typed geometry model, shortest round-trip double writer, per-operation fork isolation, result line |
| `build.sh` | `build.sh [main\|release]`: fetches the pinned commit, builds and installs GEOS, compiles the adapter |
| `run.sh`, `run_release.sh` | run wrappers: `run.sh CASES.jsonl > RESULTS.jsonl` |
| `adapter.toml` | manifest (DESIGN.md §4.2): both targets, their fields, precision model and δ |

Each build tree stays outside the repo: `$GEOTRUTH_BUILD_DIR/geos-main` or
`$GEOTRUTH_BUILD_DIR/geos-release` (`GEOTRUTH_BUILD_DIR` defaults to `~/.cache/geotruth`;
`BUILD_ROOT` overrides it for one build). Each holds `src/` (a shallow clone at the pinned
commit), `build/`, `install/`, `obj/` and `bin/geos_adapter`, linked with an rpath to
`install/lib`.

```sh
adapters/geos_main/build.sh && adapters/geos_main/build.sh release      # JOBS=2 by default
adapters/geos_main/run.sh corpus/cases/seed.jsonl > results/geos-main/seed.jsonl         # v1
adapters/geos_main/run_release.sh --v2 corpus/cases/seed.jsonl > /tmp/geos-release.v2.jsonl
python harness/compare.py corpus/cases/seed.jsonl corpus/expected-v1/seed.jsonl results/geos-main/seed.jsonl
```

## Contract v2: what is computed

| field | GEOS call |
|---|---|
| `relate` | `GEOSRelate_r` (Mod-2 boundary node rule; not `GEOSRelateBoundaryNodeRule_r`) |
| `predicates.<name>` | `GEOSIntersects_r`, `GEOSDisjoint_r`, `GEOSTouches_r`, `GEOSCrosses_r`, `GEOSOverlaps_r`, `GEOSContains_r`, `GEOSCovers_r`, `GEOSWithin_r`, `GEOSCoveredBy_r`, `GEOSEquals_r`, in (A, B) order; plain, unprepared calls |
| `valid_a`, `valid_b` | `GEOSisValid_r` (IsValidOp, `isInvertedRingValid = false`) |
| `overlay.intersection` … `overlay.symdifference` | `GEOSIntersection_r`, `GEOSUnion_r`, `GEOSDifference_r` (A − B), `GEOSSymDifference_r`: OverlayNG with floating precision and its snapping / snap-rounding fallbacks, **non-strict** (lines and points of boundary touches are kept, so a result can be a GeometryCollection). Not the `*Prec_r` variants |
| `echo` | the operands built as GEOS geometries and read back (the parse-echo canary) |

Every geometry type is accepted: Point, LineString, Polygon, MultiPoint, MultiLineString,
MultiPolygon and GeometryCollection (nested too), with empty geometries and empty elements
(`Point []`, `LineString []`, `Polygon []`, an empty point inside a MultiPoint). They are
built with `GEOSGeom_createPointFromXY_r`, `GEOSCoordSeq_copyFromBuffer_r` +
`GEOSGeom_createLineString_r` / `GEOSGeom_createLinearRing_r` + `GEOSGeom_createPolygon_r`,
`GEOSGeom_createCollection_r` and the `GEOSGeom_createEmpty*_r` calls, i.e. the way GEOS
itself builds what it reads. Z and M ordinates are dropped. Nothing is ever reported
`unsupported`: GEOS takes every type.

**Output coordinates are written by the adapter**, never by `GEOSWKTWriter`: a result is
walked with `GEOSGeomTypeId_r`, `GEOSGetExteriorRing_r`, `GEOSGetInteriorRingN_r`,
`GEOSGetGeometryN_r` and `GEOSCoordSeq_copyToBuffer_r`, and every double is printed with
`std::to_chars`, the shortest decimal that reads back as the same double ("2.0", "-0.0",
"5e-324", "1.7976931348623157e+308"; `NaN` / `Infinity` as Python's json module writes
them). Rings and parts are in GEOS's order and orientation; a `LinearRing` would be written
as a LineString. The `id` of the input line is echoed verbatim.

**Numbers are read with glibc `strtod`**, which rounds correctly (ties to even), so each
JSON number becomes exactly the double `float()` gives, including `9007199254740993` → 2^53,
subnormals and `-0.0`.

**Output line**: `{"id", "lib", "relate", "predicates": {...}, "valid_a", "valid_b",
"overlay": {...}, "errors": {...}}`, with only the groups the case asks for (`"ops"`;
absent means everything but `echo`); `--timing` adds `elapsed_ms` per field path. The
canary case (`"ops": ["echo"]`) gets `{"id", "lib", "echo": {"a", "b"}, "errors"}`.

## Errors and robustness

- An error handler is installed with `GEOSContext_setErrorMessageHandler_r`. Each
  operation checks its own failure signal (a predicate or `isValid` returning 2, relate or
  an overlay returning NULL). The field is then `null` and the GEOS message (for example
  `TopologyException: side location conflict ...`) goes into `errors` under the field's key
  (v1: `area_inter`; v2: `overlay.intersection`). In v2 a `std::bad_alloc` message becomes
  `{"kind": "memory", "message": ...}`.
- If GEOS will not build A or B (for example an unclosed ring), every field that needs
  that geometry is `null` with `"building A: IllegalArgumentException: ..."`.
- A line that cannot be read gives, in v1, a line with every field `null` and
  `errors.parse`; in v2, `{"id", "lib", "errors": {"*": "input parse error: ..."}}` (an
  unknown geometry type is such an error). Blank lines produce no output.
- Crash and hang isolation: each case runs in a forked child. The child sends each
  operation's result to the parent over a pipe as soon as it has it. If the child dies
  from a signal, that one operation gets v1 `errors[key] = "crash: process killed by
  signal 11 (Segmentation fault)"` / v2 `{"kind": "crash", "message": "process killed by
  signal 11 (Segmentation fault)"}`, and a new child carries on with the next operation.
  If one operation gives no result within `GEOS_ADAPTER_TIMEOUT` seconds (default 10), the
  child is SIGKILLed and the field fails with a timeout (v1: a `timeout: ...` message and
  the key listed in `errors.timeout`; v2: `{"kind": "timeout", ...}`); the run continues.
  Each child is limited to `GEOS_ADAPTER_MEM_MB` MiB of address space (default 4096, 0
  turns it off).
- `--no-fork` runs everything in-process, which is handy under gdb. The output is
  identical when nothing crashes (tested).
- `GEOS_ADAPTER_TEST_FAULT=crash:<key>` or `hang_:<key>` (v2 also `throw:<key>`) injects a
  fault in front of one operation; `<key>` is a v1 field name or a v2 field path such as
  `overlay.union`. It exists only to test the isolation (`tests/harness/test_native_contract.py`).

Speed: about 1 ms per v1 case and 1.5 ms per v2 case including the forks (1000 seed cases:
0.9 s v1, 1.5 s v2).

## Verification

`tests/harness/test_native_*.py` (skipped when a build is absent):

- the parse-echo canary (`schemas/examples/case.v2.valid.json`) comes back bit for bit,
  `-0.0` included, on both targets;
- all 121 pairs of 11 geometry kinds (every type, empties, a hole, a nested GC) give
  schema-valid lines, and on every pair without an empty operand the named predicates agree
  with the same run's relate matrix;
- seed (1000 cases): `harness/compare.py` on the v1 output gives 0 disagreements for both
  targets (unchanged); the `--v2` output has the same predicates and validity as v1, overlay
  geometries whose exact area is the v1 area up to GEOS's double area computation, and the
  same (zero) disagreements with the exact answer.

On 1804 cases (seed + generator families + `int_cases.jsonl`), v2 has no disagreement with
the exact oracle that v1 lacks. It has one fewer: in `int-thin-triangle-1-0009`
(coordinates near 2^52) the output geometry is exact but `GEOSArea_r` of it is off by more
than 1e-6, so v1, which compared `GEOSArea_r`, reported it.

## Observations (untriaged, not findings)

- `GEOSIntersection_r(POINT EMPTY, GEOMETRYCOLLECTION (POINT (5 5), POLYGON ((1 1, 3 1, 3 3,
  1 3, 1 1))))` and the same with `LINESTRING EMPTY` or `POLYGON EMPTY`, and
  `GEOSDifference_r` of those pairs, throw `AssertionFailedException: Should never reach
  here: Unable to determine overlay result geometry dimension`, in main and in 3.15.0
  (`pair-Pe-GC`, `pair-Le-GC`, `pair-Ae-GC` and their mirrors in the contract test's
  pairs). Not yet triaged; see `findings/registry.toml` before reporting anything.

## Notes and caveats

- GEOS main accepts a closed 3-point ring (`[[0,0],[1,1],[0,0]]`) when constructing,
  and `GEOSisValid_r` then reports it as invalid. Older releases refused to construct it.
- Predicates and overlays are always computed, even when an input is invalid. For
  invalid inputs, overlays usually throw `TopologyException`. `compare.py` ignores
  everything except validity when the oracle says an input is invalid.
- `equals` is topological equality (`GEOSEquals_r`), not `GEOSEqualsExact_r` or
  `GEOSEqualsIdentical_r`.
- DESIGN.md §4.3 mentions an optional floating-noder-only mode (to separate failures of
  the precise path from documented snapping); it is not implemented yet.

## Manifest and build root

`adapter.toml` is this adapter's manifest (DESIGN.md §4.2): both targets, the fields of both
contracts, the precision model and its δ (the loosest OverlayNGRobust snapping tolerance,
1e-8 of the largest ordinate; the same constants in 3.15.0), the coordinate range and the
build recipe.
