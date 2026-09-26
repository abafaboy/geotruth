# rust_geo: the georust `geo` crate

Adapter for [georust/geo](https://github.com/georust/geo), the Rust crate, built from
crates.io. It follows the contract in `../../FORMAT.md`.

- `lib` is `geo@<version>`, currently `geo@0.33.1` (the latest on crates.io on 2026-09-26).
  `build.rs` reads the version from `Cargo.lock`, so the string always matches the build.
- `Cargo.lock` pins the whole dependency tree. The one that matters is `i_overlay 4.5.2`
  (with `i_float 1.16.0`), which geo's `BooleanOps` calls into. `geo_adapter --version` prints
  `geo@0.33.1 (i_overlay@4.5.2)`.
- geo is built with its default features (`earcut`, `spade`, `multithreading`). Serde_json
  1.0.151 is built with `float_roundtrip`, so every coordinate parses to the exact double
  in the case file (the default fast path can be 1 ulp off), and with `preserve_order`.
- Built with rustc/cargo 1.94.1 in the release profile (`panic = "unwind"`, `debug = 1`).

## Files

| file | what |
|---|---|
| `Cargo.toml`, `Cargo.lock` | the crate, with pinned dependencies |
| `build.rs` | puts the locked geo and i_overlay versions into the binary |
| `src/main.rs` | the adapter: a supervisor process plus a worker process (the same binary) |
| `build.sh` | `cargo build --release --locked -j2`. `UPDATE=1` runs `cargo update` first |
| `run.sh` | run wrapper: `run.sh [--in-process] CASES.jsonl > RESULTS.jsonl` |
| `examples/repro_thin_triangle.rs` | stand-alone repro of the thin-triangle collapse described below |

The build tree is `$CARGO_TARGET_DIR`, which defaults to `/tmp/claude-0/gb-build/rust-geo/target`
and sits outside the repo. The binary is `$CARGO_TARGET_DIR/release/geo_adapter`.

```sh
adapters/rust_geo/build.sh
adapters/rust_geo/run.sh cases/seed.jsonl > results/rust-geo/seed.jsonl
python compare.py cases/seed.jsonl results/oracle/seed.jsonl results/rust-geo/seed.jsonl
# the repro:
(cd adapters/rust_geo && CARGO_TARGET_DIR=/tmp/claude-0/gb-build/rust-geo/target \
   cargo run --release --locked --example repro_thin_triangle)
```

## What each field is

Geometry: a one-part multipolygon becomes `geo::Polygon`, and any other count becomes
`geo::MultiPolygon` (zero parts gives an empty MultiPolygon). Each ring becomes a
`LineString` of the exact input doubles. A third ordinate, if present, is ignored.
`Polygon::new` closes a ring that is not closed. Case rings are already closed, so this
changes nothing for valid input.

| field | geo call |
|---|---|
| `valid_a`, `valid_b` | `Validation::check_validation` (`is_valid`). When the answer is false, the message goes in the extra field `invalid_reason_a` / `invalid_reason_b` |
| `intersects` `disjoint` `touches` `overlaps` `contains` `covers` `within` `covered_by` `equals` | a single `a.relate(&b)` (`Relate`, the GeometryGraph port of JTS RelateOp), then `IntersectionMatrix::is_intersects`, `is_disjoint`, `is_touches`, `is_overlaps`, `is_contains`, `is_covers`, `is_within`, `is_coveredby`, `is_equal_topo` |
| `area_inter` `area_union` `area_diff` `area_symdiff` | `Area::unsigned_area` of `BooleanOps::intersection` / `union` / `difference` (A − B) / `xor`. These are the default even-odd `boolean_op` calls, which use i_overlay's `FloatOverlay` with `OverlayOptions::ogc()` |

### Extra fields

- `de9im`: the matrix from `a.relate(&b)` as 9 characters, for example `212101212`.
- `invalid_reason_a`, `invalid_reason_b`: geo's validation message, present only when the
  geometry is invalid.
- `alt`: present only when non-empty. Its keys are the trait-based answers that differ
  from the Relate-based answers:

| `alt` key | computed as | compared with |
|---|---|---|
| `Intersects` | `a.intersects(&b)` (`Intersects` trait: an independent implementation using robust orientation tests) | `intersects` |
| `Contains` | `a.contains(&b)` (`Contains` trait) | `contains` |
| `Within` | `a.is_within(&b)`, which is `b.contains(&a)` | `within` |
| `Covers` | `a.covers(&b)` (`Covers` trait) | `covers` |
| `CoveredBy` | `b.covers(&a)` | `covered_by` |
| `ContainsProperly` | `a.contains_properly(&b)` (`ContainsProperly` trait: an independent monotone-chain implementation) | Relate's `is_contains_properly` (pattern `T**FF*FF*`) |
| `relate_ba` | `b.relate(&a)`, transposed | `de9im` |
| `relate_prepared` | `PreparedGeometry::from(&a).relate(&PreparedGeometry::from(&b))` | `de9im` |

For polygon and multipolygon pairs in geo 0.33.1, `Contains`, `Covers` and `Within` are
thin wrappers over `Relate`. For `MultiPolygon.contains(x)` and for `Within`, the wrapper
relates the operands in the *reverse* order. So a difference in those keys, or in
`relate_ba`, points to an asymmetry in Relate. If an alt computation panics or fails, its
key holds the error string instead of a boolean. If the Relate-based answer is missing,
because relate itself failed, the alt value is reported unconditionally.

## Errors and robustness

- Every operation ("unit") runs under `std::panic::catch_unwind`. A panic makes the
  unit's fields `null`, and `errors[key]` holds `panic: <message> at <file>:<line>:<col>`,
  where the path is relative to the crate, for example `geo-0.33.1/src/...`. One `relate` call
  fills all nine predicates, so a panic in relate puts the same message under all nine
  keys. With `GEO_ADAPTER_BACKTRACE=1`, the message also carries the geo, i_overlay and
  i_float frames of the backtrace.
- Process isolation: the binary runs as a supervisor and feeds cases to a worker child
  (`geo_adapter --worker`). The worker sends back one line per unit as soon as it has it.
  If a unit gives no result within `GEO_ADAPTER_TIMEOUT` seconds (default 10), the
  worker is killed. The unit's fields become `null` with `errors[key] = "timeout: ..."`,
  its name is added to `errors.timeout`, and a new worker continues with the next unit
  of the same case. If the worker dies (an abort, a stack overflow, an allocation failure),
  the unit gets `crash: worker died: signal 6 (SIGABRT); stderr: <last lines>`.
- The worker limits its own address space to `GEO_ADAPTER_MEM_MB` MiB (default 4096,
  `0` = no limit), so a runaway allocation shows up as a crash of that unit.
- `--in-process` runs everything in a single process (catch_unwind but no timeout). Its
  output is identical when nothing crashes. It is useful under a debugger.
- An input line that cannot be parsed gives a record with every field `null` and
  `errors.parse`. If a geometry cannot be built (for example a non-numeric
  coordinate), the fields that need it are `null` with `building A: ...`. Blank lines
  produce no output.
- A non-finite overlay area is reported as an error (`non-finite area: ...`).
- `GEO_ADAPTER_TEST_FAULT=<panic|abort|hang|overflow>:<unit>` injects a fault in front of
  one unit, and exists only to test the isolation. Unit names are `valid_a`, `valid_b`,
  `relate`, `area_inter`, `area_union`, `area_diff`, `area_symdiff`, and the alt keys above.
  All four kinds were checked.
- `run.sh` sets `RAYON_NUM_THREADS=1` unless it is already set. i_overlay only goes
  parallel on large inputs, and this keeps it off the shared cores.

Speed: the 1000 seed cases take about 0.2 s.

## Semantics caveats (read before triaging disagreements)

- **Overlay precision.** geo's `BooleanOps` is not a floating-point overlay. i_overlay
  maps every input point to an `i32` grid centred on the joint bounding box of A and B:
  `scale = 2^(29 - round(log2(max half-extent)))`, rounding half away from zero. The
  overlay runs exactly on those integers, and the output vertices are grid points mapped
  back. The grid step is therefore about 2^-29 to 2^-30 of the half-extent. On the seed
  cases the area error relative to the operands goes up to about 5e-9 (GEOS gets about
  1e-16). That is below compare.py's 1e-6 threshold, but a tighter threshold would flag
  ordinary rounding.
- **Thin features vanish.** A consequence of the grid: a valid polygon, or a part of a
  result, that is narrower than one grid step collapses to nothing. In
  `../clipper2/int_cases.jsonl` (204 integer cases), the adapter gets 10 `area`
  disagreements, all in the `int-thin-triangle` family (cases 0004, 0009, 0010, 0011).
  For example, in `int-thin-triangle-1-0010` A and B are the same triangle, about
  1.1e12 long and 1.4 units wide, and both `A ∩ B` and `A ∪ B` come back empty (exact area
  1099511627777, grid step 1024). `examples/repro_thin_triangle.rs` reproduces this with
  the public geo API: `a.intersection(&a)` and `a.union(&a)` of a valid triangle are
  `MULTIPOLYGON EMPTY`. The same inputs gave no predicate, validity or alt disagreements.
- **Relate** uses floating-point intersection points within an exact-orientation
  framework: the pre-RelateNG JTS design. Wrong answers are possible on near-degenerate
  inputs. Relate never snaps to a grid, so the predicates and the overlay areas can
  disagree with each other on the same case.
- **Validation** checks too few points, ring self-intersection, non-finite coordinates,
  holes inside the shell, rings that meet along a line or overlap, and multipolygon
  elements that overlap or meet along a line. It does **not** check that the interior is
  connected (for example, holes that cut the shell's interior in two). The oracle only
  rules on validity for a single polygon without holes (`valid_single_polygon`), and
  reports `null` otherwise.

## Smoke test (seed.jsonl)

`run.sh cases/seed.jsonl`, then `compare.py` against `results/oracle/seed.jsonl`:
**1000 cases, 0 disagreements** of any kind (predicate, area, validity or error), no
`alt` entries, and no errors. The 13 hand-made hole and multipolygon cases (holes,
filled holes, a polygon inside a hole, multi against poly both ways, equal multipolygons in
a different order, clockwise and rotated-start equal rings, and corner, edge and
containment touches) also gave 0 disagreements against `oracle.py`.
