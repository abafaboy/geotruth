# JTS adapter (`jts-main`, `jts-release`)

Adapter for [locationtech/jts](https://github.com/locationtech/jts) `jts-core`. One source,
`JtsAdapter.java`, is built twice: against JTS git master at a pinned commit and against
the latest JTS release, 1.20.0, from its git tag. It answers adapter contract v2
(DESIGN.md §4.1, `schemas/result.v2.schema.json`) for typed lines, and the legacy v1
contract (`../../harness/FORMAT-v1.md`) for legacy lines, unchanged.

| target | `lib` | JTS | run |
|---|---|---|---|
| `jts-main` | `jts@1.21.0-SNAPSHOT-3ea61f8` | master, commit `3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd` | `run.sh` |
| `jts-release` | `jts@1.20.0` | tag `1.20.0`, commit `6e95fe82feb986a7aa657f4ffa406d8c290af509` | `run_release.sh` |

```sh
adapters/jts_main/build.sh              # master at the pinned commit
adapters/jts_main/build.sh release      # the 1.20.0 release
adapters/jts_main/build.sh main --update   # move master to the newest upstream commit
python3 -m geotruth run --lib jts-main --tier core
python3 -m geotruth score --lib jts-main --tier core
```

## Files

- `JtsAdapter.java`: the adapter, with a small built-in JSON reader and writer (no
  dependencies except jts-core).
- `build.sh`: shallow-fetches the pinned commit and builds jts-core and the adapter.
- `run.sh`, `run_release.sh`: run the master and release builds.
- `adapter.toml`: the manifest (DESIGN.md §4.2) of both targets.

## Build

The build trees are outside the repo: `$GEOTRUTH_BUILD_DIR/jts-main` (override
`JTS_BUILD_DIR`) and `$GEOTRUTH_BUILD_DIR/jts-release` (override `JTS_RELEASE_BUILD_DIR`),
where `GEOTRUTH_BUILD_DIR`, shared by every adapter, defaults to `~/.cache/geotruth`:

- `src/`: the shallow clone at the pinned commit.
- `m2/`: a private Maven repository (master only).
- `out/jts-core.jar`, `out/jts-core.commit`: the built jar and the commit it was built from;
  jts-core is built once per commit, later runs only recompile the adapter.
- `out/classes/`: the adapter classes. `out/lib.txt`: the `lib` string.

Maven builds `modules/core` of master with `-DskipTests -Dcheckstyle.skip=true`
(checkstyle downloads its config from checkstyle.org, which the proxy blocks). If Maven
fails, and always for the release, the script compiles `modules/core/src/main/java` with
`javac`; `FORCE_JAVAC=1` forces that path. Both paths give byte-identical results.
Requires JDK 11 or later (tested with OpenJDK 21); output doubles are written with
`Double.toString`, the shortest round-trip decimal on JDK 19 and later.

## Run

    adapters/jts_main/run.sh CASES.jsonl > RESULTS.jsonl
    adapters/jts_main/run.sh --relate old CASES.jsonl > RESULTS.jsonl   # v2 through RelateOp
    adapters/jts_main/run.sh --timeout 30 CASES.jsonl > RESULTS.jsonl   # s per operation
    adapters/jts_main/run.sh --version

`run_release.sh` takes the same arguments. `--v2` answers legacy lines with v2 output too;
`--timing` adds per-operation milliseconds; `-` reads cases from stdin.

## What each field calls (contract v2)

Every geometry type is built with the default `GeometryFactory` (floating
PrecisionModel), empty geometries and empty elements included. Coordinates go through
`Double.parseDouble`, which is exact for round-trip decimals. A geometry JTS refuses to
build (an unclosed ring, a one-point line) fails every field that needs it with
`building A: ...`.

| field | JTS call |
|---|---|
| `echo` | the operands as built, written back from their CoordinateSequences |
| `valid_a`, `valid_b` | `new IsValidOp(g).isValid()` |
| `relate` | `RelateNG.relate(a, b)` (`--relate old`: `Geometry.relate`, the old RelateOp) |
| `predicates.<name>` | `RelateNG.relate(a, b, RelatePredicate.<name>())`; `covered_by` = coveredBy, `equals` = equalsTopo (`--relate old`: the `Geometry` methods) |
| `overlay.<op>` | `OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION / UNION / DIFFERENCE / SYMDIFFERENCE)`: non-strict OverlayNG with its snapping and snap-rounding fallbacks |

Out of JTS's contract, and so `"unsupported"`:

- GeometryCollection operands of the old RelateOp (`--relate old` only);
- GeometryCollection operands of OverlayNG that are not *simple*. OverlayNG's javadoc: "A
  GeometryCollection is simple if it can be flattened into a valid Multi-geometry; i.e. it
  is homogeneous and does not contain any overlapping Polygons." The adapter checks this
  before the call (same dimension for every non-empty element; polygonal elements valid
  as one MultiPolygon). A GeometryCollection that OverlayNG rejects with an
  `IllegalArgumentException` is also unsupported.

Output coordinates are written by the adapter, never by a WKT writer.

**Precision (manifest).** OverlayNGRobust tries the floating noder, then snapping with a
tolerance of M/10¹² growing ×10 per try for 5 tries, then snap rounding; δ is the loosest
documented fallback, `{kind = "relative", value = 1e-8}`.

## Isolation (contract v2)

The operations run in a worker JVM (this class with `--worker`) that sends each result as
soon as it has it. An operation with no result within the timeout (`--timeout`, else
`JTS_ADAPTER_TIMEOUT` or `GEOTRUTH_OP_TIMEOUT`, default 10 s) kills the worker
(`{"kind": "timeout"}`); a worker that dies fails that operation (`{"kind": "crash"}`); a
new worker continues with the next operation. The worker heap is capped at
`JTS_ADAPTER_MEM_MB` MiB (default 2048; `OutOfMemoryError` is `{"kind": "memory"}`).
`--no-fork` runs in-process. `JTS_ADAPTER_TEST_FAULT=crash:<path>|hang_:<path>|throw:<path>`
injects a fault (self-test only).

JTS prints some diagnostics on `System.out` (for example "Found zero-length section
segment" from RelateNG). The worker keeps the real stdout for the protocol and points
`System.out` at stderr, and the supervisor ignores lines that are not protocol lines, so
library output cannot corrupt results.

## Legacy v1 fields

Legacy lines keep the v1 behaviour: a one-part multipolygon becomes a `Polygon`, otherwise
a `MultiPolygon`; `valid_a`/`valid_b` from IsValidOp; predicates through the `Geometry`
methods, which default to the old RelateOp (`--relate ng` sets `jts.relate=ng`, lib suffix
`+relateng`); areas from `OverlayNGRobust.overlay(a, b, op).getArea()`; a per-case
`--timeout` on a thread (JTS ignores interrupts, so a case that runs over is abandoned, not
killed). The v1 code path is unchanged from the v1 adapter.

## Results

Core tier (3400 cases), 2026-09-26, `geotruth run` + `geotruth score`, 0 scorer failures:

| target | headline | relate wrong | predicates wrong | validity wrong | overlay gross / topological / exception |
|---|---|---|---|---|---|
| `jts-main` | 483 | 160 | 102 | 42 | 118 / 51 / 8 |
| `jts-release` | 518 | 165 | 100 | 42 | 164 / 27 / 13 |

Notable:

- **master regression.** `union(MultiLineString, Polygon)` near 1e220
  (`line-polygon-1-000090-along-edge-full.ba.int.extreme`): master returns `POLYGON EMPTY`,
  with no exception; 1.20.0 returns the correct GeometryCollection. Master has 51
  topological overlay grades against 27 for the release.
- **ClassCastException** (`LineString cannot be cast to Polygon`) in the union and
  symmetric difference of a MultiPolygon and a Point near 1e-162
  (`point-geometry-1-000016-in-hole.ba.int.extreme`), in both builds.
- Line overlays at the extreme range go gross in both builds, like GEOS (overflow in the
  noding of coordinates near 1e212).
