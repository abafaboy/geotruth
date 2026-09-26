# geos_main: GEOS git main, via the C API

This adapter runs GEOS built from the `main` branch. It is a small C program that uses
the reentrant GEOS C API (`geos_c.h`, `*_r` functions, `GEOS_USE_ONLY_R_API`), and it
implements the adapter contract in `../../FORMAT.md`.

- Pinned commit: `ae9cdd98be4e0bae552b918d4d14c94a9ce99c58` (libgeos/geos main, 2026-09-21,
  "Update NEWS.md"). Its `Version.txt` says 3.16.0dev, C API 1.22.0.
- `lib` field: `geos@3.16.0dev-ae9cdd9`. The adapter builds this at run time from
  `GEOSversion()` and `GEOSrevision()`, so it always matches the linked library.
- Build: CMake Release, `-DBUILD_TESTING=OFF`, `-j2`. It was built with gcc 13.3 and
  cmake 3.28 on Ubuntu 24.04.

## Files

| file | purpose |
|---|---|
| `geos_adapter.c` | the adapter: a small JSON reader plus GEOS calls, with no other dependencies |
| `build.sh` | fetches the pinned commit, builds and installs GEOS, then compiles the adapter |
| `run.sh` | run wrapper: `run.sh CASES.jsonl > RESULTS.jsonl` |

The build tree stays outside the repo, under `$BUILD_ROOT`
(default `/tmp/claude-0/gb-build/geos-main`):
`src/` (a shallow clone at the pinned commit), `build/`, `install/`, and
`bin/geos_adapter`. The adapter is linked with an rpath to `install/lib`.

```sh
adapters/geos_main/build.sh                       # JOBS=2 by default; GEOS_COMMIT=<sha> to move the pin
adapters/geos_main/run.sh cases/seed.jsonl > results/geos-main/seed.jsonl
python compare.py cases/seed.jsonl results/oracle/seed.jsonl results/geos-main/seed.jsonl
```

## What is computed

| field | GEOS call |
|---|---|
| `valid_a`, `valid_b` | `GEOSisValid_r` |
| `intersects` `disjoint` `touches` `overlaps` `contains` `covers` `within` `covered_by` `equals` | `GEOSIntersects_r` … `GEOSCoveredBy_r`, `GEOSEquals_r` (A, B order) |
| `area_inter` `area_union` `area_diff` `area_symdiff` | `GEOSArea_r` of `GEOSIntersection_r` / `GEOSUnion_r` / `GEOSDifference_r` (A − B) / `GEOSSymDifference_r` |

The predicates are the plain (unprepared) calls. In GEOS 3.13 and later they go through
RelateNG. The overlays are the default `GEOSIntersection_r` and so on, which means
OverlayNG with floating precision and its snapping and snap-rounding fallbacks. They are
not the `*Prec_r` variants.

How geometries are built: a one-part multipolygon becomes a `Polygon`, and anything else
becomes a `MultiPolygon`. Coordinates go into `GEOSCoordSeq_copyFromBuffer_r` with no
Z or M. Numbers are parsed with glibc `strtod`, which rounds correctly, so they are the
exact doubles in the case file. A third ordinate, if present, is ignored.

Output areas are printed in the shortest form that round-trips (tries `%.15g`, `%.16g`,
then `%.17g`).

## Errors and robustness

- An error handler is installed with `GEOSContext_setErrorMessageHandler_r`. Each
  operation checks its own failure signal: a predicate or `isValid` returning 2, an
  overlay returning NULL, or `GEOSArea_r` returning 0. On failure the field is `null`
  and the GEOS message (for example `TopologyException: side location conflict ...`)
  goes into `errors` under that field's key. A non-finite area is reported the same way.
- If GEOS will not build A or B (for example an unclosed ring), every field that needs
  that geometry is `null` with `"building A: IllegalArgumentException: ..."`.
- An input line that cannot be parsed gives a line with every field `null` and
  `errors.parse`. Blank lines produce no output, as in the reference adapter.
- Crash and hang isolation: each case runs in a forked child. The child sends each
  operation's result to the parent over a pipe as soon as it has it. If the child dies
  from a signal, that one operation gets `errors[key] = "crash: process killed by
  signal 11 (Segmentation fault)"`, and a new child carries on with the next operation.
  If one operation gives no result within `GEOS_ADAPTER_TIMEOUT` seconds (default 10),
  the child is SIGKILLed, the field is `null` with a `timeout: ...` message, the key is
  listed in `errors.timeout`, and the run continues. This is a superset of the contract,
  which allows an all-null line with `errors.timeout`: fields that finished keep their
  values. Each child is also limited to `GEOS_ADAPTER_MEM_MB` MiB of address space
  (default 4096, 0 turns it off), so a runaway allocation shows up as a `std::bad_alloc`
  error instead of exhausting the shared machine.
- `--no-fork` runs everything in-process, which is handy under gdb. The output is
  identical when nothing crashes.
- `GEOS_ADAPTER_TEST_FAULT=crash:<key>` or `hang_:<key>` injects a fault in front of an
  operation. It exists only to test the isolation code.

Speed: about 1 ms per case including the fork (1000 seed cases take 0.9 s; 4000
generated cases take 4.3 s).

## Notes and caveats

- GEOS main accepts a closed 3-point ring (`[[0,0],[1,1],[0,0]]`) when constructing,
  and `GEOSisValid_r` then reports it as invalid. Older releases refused to construct it.
- Predicates and overlays are always computed, even when an input is invalid. For
  invalid inputs, overlays usually throw `TopologyException`. `compare.py` ignores
  everything except validity when the oracle says an input is invalid.
- `equals` is topological equality (`GEOSEquals_r`), not `GEOSEqualsExact_r` or
  `GEOSEqualsIdentical_r`.
