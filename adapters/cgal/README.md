# cgal: CGAL with an exact kernel, the exact control

This adapter runs [CGAL](https://www.cgal.org/) 5.6 (Ubuntu 24.04 `libcgal-dev`
5.6-1build3, header-only, with GMP 6.3 and MPFR 4.2) with the
**Exact_predicates_exact_constructions_kernel** (`CGAL::Epeck`). Every double of the input is
an exact rational, and every point CGAL constructs (edge intersections) is exact, so its
regularized overlay is the exact regularized overlay. It is geotruth's external control
(DESIGN.md §0.2): it shares no code with the engine or the reference oracle, and it must
agree with them exactly.

`lib` is `cgal@5.6`. It answers both adapter contracts, line by line:

- **v2** ([DESIGN.md §4.1](../../docs/DESIGN.md), `schemas/result.v2.schema.json`): a line
  whose operands are typed geometries or that has `"ops"`; `--v2` answers legacy lines this
  way too. `--exact FILE` also writes the exact results to a side-car (below).
- **v1** (`../../harness/FORMAT-v1.md`): a legacy line. The same computations under the v1
  field names, plus an extra field `"exact": {"inter", "union", "diff", "symdiff"}` with the
  exact areas as `"n/d"` (compare.py ignores it).

## Files

| file | purpose |
|---|---|
| `cgal_adapter.cpp` | the adapter, on top of `../geos_main/adapter_v2.hpp` (the contract-v2 runtime shared by the native adapters: JSON reader, typed geometries, round-trip double writer, per-operation fork isolation) |
| `build.sh` | checks the CGAL headers and compiles `bin/cgal_adapter` (about 45 s, one compiler) |
| `run.sh` | run wrapper: `run.sh [--v2] [--exact SIDECAR.jsonl] CASES.jsonl > RESULTS.jsonl` |
| `adapter.toml` | manifest (DESIGN.md §4.2) |

```sh
sudo apt-get install libcgal-dev              # CGAL 5.6 (+ libgmp-dev, libmpfr-dev)
adapters/cgal/build.sh                        # -> $GEOTRUTH_BUILD_DIR/cgal/bin/cgal_adapter
adapters/cgal/run.sh corpus/cases/seed.jsonl > /tmp/cgal.v1.jsonl
adapters/cgal/run.sh --v2 --exact /tmp/cgal.exact.jsonl corpus/cases/seed.jsonl > /tmp/cgal.v2.jsonl
```

The build tree is `$GEOTRUTH_BUILD_DIR/cgal` (`BUILD_ROOT` overrides it). CGAL's own
checks stay on (no `NDEBUG` / `CGAL_NDEBUG`), so a failed CGAL precondition throws and is
reported as that operation's error instead of running on; `-frounding-math` as CGAL requires.

## What is computed (v2)

Only Polygon and MultiPolygon operands are in CGAL's contract here: every field but `echo` is
`"unsupported"` for any other type (Boolean_set_operations_2 works on polygons).

| field | how |
|---|---|
| `overlay.intersection` … `overlay.symdifference` | `CGAL::Polygon_set_2<Epeck>`: `intersection`, `join`, `difference` (A − B), `symmetric_difference`. The **regularized areal** overlay (no lines, no points; faces merged); a result is a Polygon, a MultiPolygon, or `POLYGON EMPTY`, shells counter-clockwise and holes clockwise as CGAL returns them |
| `valid_a`, `valid_b` | see "Validity" |
| `predicates.*` | derived, exactly, for Polygon/MultiPolygon pairs (see below) |
| `relate` | `null`: CGAL has no DE-9IM |
| `echo` | each position as an exact CGAL point, back through the exact-rational-to-double conversion below |

**Building the operands.** Each ring becomes a `Polygon_2`: the closing point and repeated
consecutive points are dropped (they do not change the point set) and the ring is turned
counter-clockwise (shell) or clockwise (hole) by the sign of its exact area, since CGAL
requires that orientation and OGC does not care. A polygon CGAL accepts as a
`Polygon_with_holes_2` enters the set as one; a polygon whose holes touch its shell or each
other at a point inside an edge (OGC-valid, but a precondition violation for CGAL's polygon
with holes) enters as its shell minus its holes, the same point set, built from simple
polygons only. A shell or hole that is not a simple polygon is outside CGAL's documented
preconditions, and the overlays and predicates of that case are `"unsupported"`. A
MultiPolygon is the `join` of its polygons. Non-finite ordinates: `valid_*` is `false`
(OGC: invalid coordinate) and every other field `"unsupported"`.

**Output doubles are computed by the adapter, correctly rounded.** Each exact coordinate is
read from the kernel's exact number type (`CGAL::exact(FT)`, printed and read back into a
GMP `mpq_t`, canonical) and rounded to the nearest double with ties to even, subnormals and
overflow included (integer division on `mpz_t` after scaling to a 53-bit integer part, or to
the subnormal grid 2^-1074). `CGAL::to_double` is not used: it does not promise
round-to-nearest (`mpq_get_d` truncates). Every double is written with `std::to_chars`
(shortest round-trip).

**Derived predicates.** For valid inputs (regular closed sets) these are exact:
II = A ∩* B ≠ ∅, AB = A −* B ≠ ∅, BA = B −* A ≠ ∅ (regularized, from the same polygon sets),
and *contact* = some boundary segment of A meets some boundary segment of B
(`K::Do_intersect_2` on exact segments, filtered by exact double bounding boxes). Then
`intersects` = II or contact, `disjoint` = not intersects, `touches` = contact and not II,
`overlaps` = II and AB and BA, `contains` = `covers` = not BA, `within` = `covered_by` = not
AB, `equals` = not AB and not BA, and `crosses` = false (areal/areal, DESIGN.md §1). They are
`null` when an operand is empty (the empty-geometry conventions are not CGAL's to decide).
They are listed as derived in `adapter.toml`.

## The exact side-car (`--exact FILE`)

One JSON line per v2 case, in input order:

```json
{"id": "...", "lib": "cgal@5.6",
 "overlay": {"intersection": {"exact": ExactGeometry, "area": "n/d", "num_vertices": 7}, ...},
 "echo": {"a": ExactGeometry, "b": ExactGeometry}}
```

`exact` is a typed geometry whose ordinates are canonical rationals (`"n"` or `"n/d"`,
lowest terms, `schemas/geometry.v2.schema.json#/$defs/ExactGeometry`), in the vertex order
of the v2 output line; `area` is the exact area (Σ of the exact signed ring areas);
`num_vertices` counts distinct vertices (rings are closed in `exact` as in the output).
This is the `areal` OverlayResult of `schemas/expected.v2.schema.json` minus its display WKT.
Only the operations that ran appear; a failed or unsupported one is absent.

## Validity

For a Polygon, after the adapter's own OGC pre-checks (finite ordinates; every ring closed
and of at least 4 positions), on the rings as built above:

- `CGAL::is_valid_polygon` of the shell: strictly simple (and counter-clockwise, which the
  adapter ensured). CGAL's polygon-with-holes rule alone would accept a "relatively simple"
  shell that touches itself at a vertex, which OGC calls invalid;
- with holes, also `CGAL::is_valid_polygon_with_holes` (holes simple and clockwise, inside
  the shell, not crossing the shell or each other).

An empty Polygon is valid. A MultiPolygon is `null`: CGAL has no multipolygon rule that
matches OGC's (parts may touch only at points, interiors disjoint). Known differences from
OGC/GEOS validity, so compare CGAL's `valid_*` only where they cannot arise:

- a hole touching the shell or another hole at a point inside an edge: CGAL invalid, OGC
  valid (the 20 validity differences of the broader check below, families `hole-contact`
  and `int-hole-touches-shell`);
- an interior disconnected by holes that touch each other or the shell at two or more
  points: not checked by CGAL (CGAL valid, OGC invalid).

## Errors and robustness

Those of `../geos_main/adapter_v2.hpp`: each case runs in a forked child that streams each
operation's result; a crash or a hang (`CGAL_ADAPTER_TIMEOUT`, default 10 s per operation)
fails that one operation with `{"kind": "crash" | "timeout", ...}` and a fresh child continues;
the child's address space is capped at `CGAL_ADAPTER_MEM_MB` (default 4096 MiB) and
`std::bad_alloc` is `{"kind": "memory", ...}`; a CGAL exception (a failed precondition) is its
message. Within one child the polygon sets and the regularized overlays of the predicates are
computed once. `--no-fork` runs in-process; `--timing` adds `elapsed_ms`;
`CGAL_ADAPTER_TEST_FAULT=crash:<path>|hang_:<path>|throw:<path>` injects a fault (self-test).
CGAL's validity warnings are silenced (the answer is the boolean).

## Parse-echo canary

The canary (`schemas/examples/case.v2.valid.json`) comes back exactly, with one documented
difference: `-0.0` comes back as `0.0`, because an exact rational has no signed zero (the
echo goes through CGAL's exact points on purpose, to exercise the rounding path).
`9007199254740993` → 2^53, `5e-324`, `2.2250738585072014e-308`, `-2.5e-310`,
`0.30000000000000004` and `±1.7976931348623157e+308` are exact; the side-car echo carries
them as rationals (`5e-324` is `"1/2^1074"` written out).

## Verification

- **Seed (1000 cases, `tests/harness/test_native_seed.py`):** for every case and every
  operation the exact area equals the oracle's exact area (`corpus/expected-v1/seed.jsonl`,
  `exact.inter/diff_ab/diff_ba`) as a rational, and equals the exact shoelace of the
  side-car geometry; every output double is the correctly rounded side-car rational (checked
  against Python's `float(Fraction)`); the nine v1 predicates and validity equal the
  oracle's; `harness/compare.py` on the v1 output reports 0 disagreements.
- **Broader check (1804 cases: seed + 60 cases of each generator family +
  `adapters/clipper2/int_cases.jsonl`, oracle by `tests/reference/oracle.py`):** exact
  areas equal on all 1804 cases, predicates equal on all, validity equal on 3482 of 3502
  comparable operands (the 20 others: holes touching at a point, above; 106 MultiPolygon
  operands are `null`).
- One case shows the rounding floor, not an error: `sliver-spike-7-000033-sliver-pair
  .projected` (coordinates near 1e7, operands of area ~1e-4) has exact areas equal to the
  oracle's, but the area of the correctly rounded output geometry differs by 1.6e-5 of the
  operands' area, over compare.py's 1e-6. Rounding the exact result is exactly what
  DESIGN.md §4.3 grades as "within the correctly rounded floor".

Speed: about 2.6 ms per case in v2 (1000 seed cases: 2.6 s), forks included.
