# JTS master adapter (`jts-main`)

Adapter for [locationtech/jts](https://github.com/locationtech/jts) `jts-core`, built from
current git master. It follows the contract in `../../FORMAT.md`.

## Files

- `JtsAdapter.java`: the adapter, with a small built-in JSON reader and writer (no dependencies
  except jts-core).
- `build.sh`: shallow-clones JTS master and builds jts-core and the adapter.
- `run.sh`: runs the adapter.

## Build

    adapters/jts_main/build.sh            # clone if needed, then build
    adapters/jts_main/build.sh --update   # fetch the latest master first

The build tree is `$JTS_BUILD_DIR` (default `/tmp/claude-0/gb-build/jts-main`), outside the
repo:

- `src/`: the clone.
- `m2/`: a private Maven repository.
- `out/jts-core.jar`, `out/classes/`: the built jar and adapter classes.
- `out/lib.txt`: the `lib` string.

Maven builds `modules/core` with `-DskipTests -Dcheckstyle.skip=true`. Checkstyle is skipped
because it downloads its config from checkstyle.org, and the proxy blocks that host. If Maven
fails, the script compiles `modules/core/src/main/java` directly with `javac`. Set
`FORCE_JAVAC=1` to force that path. Both paths give byte-identical results on the seed set.
Requires JDK 11 or later (tested with OpenJDK 21).

## Run

    adapters/jts_main/run.sh CASES.jsonl > RESULTS.jsonl
    adapters/jts_main/run.sh --relate ng CASES.jsonl > RESULTS.jsonl   # RelateNG predicates
    adapters/jts_main/run.sh --timeout 30 CASES.jsonl > RESULTS.jsonl  # per-case budget in s

The `lib` field is `jts@<pom version>-<short commit>`, for example
`jts@1.21.0-SNAPSHOT-3ea61f8`. With `--relate ng` it gets a `+relateng` suffix.

## What each field calls

| field | JTS call |
|---|---|
| geometry | One part becomes `Polygon`; otherwise `MultiPolygon`. Built with the default `GeometryFactory` (floating precision). Coordinates go through `Double.parseDouble`, which is exact for round-trip decimals. |
| `valid_a`, `valid_b` | `new IsValidOp(g).isValid()` (OGC rules, so self-touching rings are invalid) |
| `intersects` … `covered_by` | `Geometry.intersects/disjoint/touches/overlaps/contains/covers/within/coveredBy` |
| `equals` | `Geometry.equalsTopo` |
| `area_*` | `OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION/UNION/DIFFERENCE/SYMDIFFERENCE).getArea()` |

Predicates use the JTS default engine, which is the old `RelateOp`/`GeometryGraph` code
(`GeometryRelate.RELATE_NG_DEFAULT = false` on master). `--relate ng` sets the system property
`jts.relate=ng` before JTS loads, which routes the same `Geometry` methods through the newer
`RelateNG`. Running both modes compares two predicate engines in the same build.

## Caveats

- Each operation catches `Throwable`. The message goes to `errors[field]` as
  `ExceptionClass: message`. A non-finite area is reported as `null`, with an error.
- JTS refuses to build some rings: unclosed rings, and rings with 1 or 2 points
  (`IllegalArgumentException`). Those only occur in `invalid-*` families. In that case every
  field that depends on the unbuildable geometry is `null`, with the construction message in
  `errors`. A closed 3-point ring (`A,B,A`) is accepted and reported invalid by `IsValidOp`.
- Timeouts: each case runs on its own worker thread with a 256 MB stack. The default budget is
  10 s. JTS ignores thread interrupts, so a case that runs over is abandoned, not killed: the
  thread becomes a low-priority daemon, and the case gets every field `null` plus
  `errors.timeout`. Each abandoned thread keeps using a core until the run ends, and a warning
  goes to stderr. `--timeout 0` turns the budget off.
- `JAVA_TOOL_OPTIONS` on this machine makes the JVM print a banner on stderr. Stdout carries
  only JSON lines.
