# Exports: exact cases in each library's own test format

`geotruth export` writes corpus cases, with their exact answers, in the test format of a
library, so that its maintainers can add them to their own suite without depending on
geotruth. The cases are CC0: no permission or attribution is needed.

| `--format` | writes | for |
|---|---|---|
| `jts-xml` | a `<run>` XML file | JTS TestRunner and GEOS `xmltester` |
| `boost` | definitions for `test/algorithms/overlay/overlay_cases.hpp` and `TEST_INTERSECTION` / `TEST_UNION` / `TEST_DIFFERENCE` / relate test lines | Boost.Geometry's test suite |
| `clipper2` | blocks for `Tests/Polygons.txt` | Clipper2's `TestPolygons.cpp` |
| `geo-rust` | `#[test]` functions using `wkt!` | georust `geo` |
| `pytest` | a pytest module | Shapely (GEOS) |

Every expected value is the exact answer. Operands are written with shortest round-trip
doubles, so every library reads exactly the case's doubles. Overlay results are exported as
checks the formats can express: the relate matrix and the predicates, validity, and the
areas of the four overlays (a library's overlay output is not bit-exact, so it cannot be
compared vertex by vertex).

## Usage

```sh
geotruth export --format FORMAT CASES.jsonl [CASES.jsonl ...] [-o OUT]
    [--id ID ...] [--family FAMILY] [--limit N]    # which cases (FILE#ID selects one case)
    [--rel 1e-6]                                   # relative area tolerance of area checks
    [--comment TEXT]                               # an extra line for the file header
```

Without `-o` the export goes to standard output. `-o` names the file; when an export needs
several files, they get `.part1`, `.part2`, ... before the extension. Case files can be
corpus v2 (`corpus/cases/...`) or the legacy FORMAT-v1.

## JTS and GEOS (`jts-xml`)

```console
$ geotruth export --format jts-xml corpus/cases/core/vertex-on-edge.jsonl --limit 20 \
      -o vertex-on-edge.xml --run geos,jts
wrote vertex-on-edge.part1.xml
wrote vertex-on-edge.part2.xml
wrote vertex-on-edge.part3.xml
vertex-on-edge.part1.xml: geos xmltester: 224 tests, 224 passed, 0 failed, 0 exceptions
vertex-on-edge.part1.xml: jts (ng): 224 tests, 224 passed, 0 failed, 0 exceptions
vertex-on-edge.part2.xml: geos xmltester: 48 tests, 48 passed, 0 failed, 0 exceptions
vertex-on-edge.part2.xml: jts (ng): 48 tests, 48 passed, 0 failed, 0 exceptions
vertex-on-edge.part3.xml: geos xmltester: 48 tests, 48 passed, 0 failed, 0 exceptions
vertex-on-edge.part3.xml: jts (ng): 48 tests, 48 passed, 0 failed, 0 exceptions
```

(GEOS main at the commit pinned in `adapters/geos_main/build.sh` and JTS master at the
commit pinned in `adapters/jts_main/build.sh`, 2026-09-26. These 20 cases happen to pass
everywhere; other cases may not, which is the point of exporting them.)

Each case becomes a `<case>` with `relate`, the named predicates (`coveredBy` and
`equalsTopo` in JTS's names), `isValid` for both operands, and area checks:

```xml
  <case>
    <desc>vertex-on-edge-1-000036-apex-in.n7.projected; family vertex-on-edge; degeneracy lattice; range normal</desc>
    <a>
    POLYGON ((3299433.59765625 1357645.234375, 3299435.78125 1357647.0703125, 3299436.109375 1357646.83984375, 3299433.59765625 1357645.234375))
  </a>
    <b>
    POLYGON ((3299481.390625 1357608.4375, 3299490.16796875 1357618.9921875, 3299438.1875 1357653.14453125, 3299431.76171875 1357642.0703125, 3299481.390625 1357608.4375))
  </b>
    <test><op name="relate" arg3="2FF10F212" arg1="A" arg2="B">true</op></test>
    <test><op name="intersects" arg1="A" arg2="B">true</op></test>
    ...
    <test><op name="within" arg1="A" arg2="B">true</op></test>
    <test><op name="coveredBy" arg1="A" arg2="B">true</op></test>
    <test><op name="equalsTopo" arg1="A" arg2="B">false</op></test>
    <test><op name="isValid" arg1="A">true</op></test>
    <test><op name="isValid" arg1="B">true</op></test>
    <test><op name="unionArea" arg1="A">0.5528335571289062</op></test>
    <test><op name="unionArea" arg1="B">807.0614624023438</op></test>
  </case>
```

Predicates whose value depends on the empty-geometry convention table are left out. The
overlay areas are checked through `unionArea`, which both runners provide: `unionArea` of A
and of B, and a companion case whose A is `GEOMETRYCOLLECTION (A, B)`, whose `unionArea` is
area(A ∪ B). Together these fix all four overlay areas (area(A ∩ B) = area(A) + area(B) -
area(A ∪ B), and so on). JTS compares areas within one absolute `<tolerance>` per file
(GEOS's `xmltester` within 1e-3 relative), and the tolerance of a case must be at least 4
times its double-rounding floor and at most the `--rel` share (default 1e-6) of its larger
operand's area. Cases whose ranges cannot share one tolerance go to separate files, which
is why the example wrote three, and a case whose tolerance would reach half its area gets
no area checks.

`--run jts,jts-old,geos` runs the written files with the libraries' own runners and exits
with 1 if any test fails; `jts` uses RelateNG (`-Djts.relate=ng`) and `jts-old` JTS's
original RelateOp. The runners are built under `$GEOTRUTH_BUILD_DIR` from the same source
trees the adapters use: `adapters/jts_main/build.sh` and `adapters/geos_main/build.sh` first,
then `geotruth export --build-runners` (the JTS TestRunner is compiled with `javac`; GEOS is
configured with `-DBUILD_TESTING=ON` in a separate tree and only `test_xmltester` is built).

To use a file upstream, copy it into JTS's `modules/tests/src/test/resources/testxml/` or
GEOS's `tests/xmltester/tests/` tree and register it the way those projects register new
files.

## Boost.Geometry (`boost`)

```sh
geotruth export --format boost corpus/cases/core/int-grid.jsonl --limit 3 -o int-grid.hpp
```

```cpp
// ---- test/algorithms/overlay/overlay_cases.hpp

// int-grid-1-000004-lattice-poly.small-rot; family int-grid; degeneracy lattice; range normal
static std::string geotruth_int_grid_1_000004_lattice_poly_small_rot[2] = {
        "POLYGON((2 4,0 4,1 7,2 4))",
        "POLYGON((1 3,0 2,-1 1,0 6,3 5,1 3))" };
...
// ---- test/algorithms/set_operations/intersection/intersection.cpp
    TEST_INTERSECTION(geotruth_int_grid_1_000004_lattice_poly_small_rot, -1, -1, 2.4);
...
// ---- test/algorithms/relate/relate_*.cpp (inside test_all<P>())
    // int-grid-1-000004-lattice-poly.small-rot
    test_geometry<poly, poly>(
        "POLYGON((2 4,0 4,1 7,2 4))",
        "POLYGON((1 3,0 2,-1 1,0 6,3 5,1 3))",
        "212101212");
```

The file is a set of snippets to paste, each under a comment naming its destination file.
Rings are written for Boost's default `model::polygon<point_xy<double>>`: shells clockwise,
holes counter-clockwise, closed. Expected areas are the exact areas rounded to doubles;
counts are not checked (`-1`). Cases with other operand types get the relate line only, and
GeometryCollections and empty operands are skipped.

## Clipper2 (`clipper2`)

```sh
geotruth export --format clipper2 corpus/cases/core/int-grid.jsonl --limit 3 -o int-grid.txt
```

```
CAPTION: 1. geotruth int-grid-1-000004-lattice-poly.small-rot intersection (scale 2^0; grid rounding of the output may exceed the 1 % area tolerance)
CLIPTYPE: INTERSECTION
FILLRULE: EVENODD
SOL_AREA: 2
SOL_COUNT: 0
SUBJECTS
2,4, 1,7, 0,4
CLIPS
1,3, 0,2, -1,1, 0,6, 3,5
```

Clipper2 works on int64 coordinates, so each case is scaled by 2^k, the smallest k in
0..60 that makes every coordinate an integer; this is exact for doubles, and it is what the
Clipper2 adapter does. Cases outside that range are skipped. `SOL_AREA` is the exact area in
scaled units rounded to an integer and `SOL_COUNT` is not checked. Clipper2's test compares
areas within 1%; the caption says when the output's grid rounding could exceed that on a
small area, as here, where the exact intersection area is 2.4. `Polygons.txt` has no comment
syntax, so delete the header lines before appending, and renumber the captions.

## georust `geo` (`geo-rust`)

```sh
geotruth export --format geo-rust corpus/cases/core/int-grid.jsonl --limit 3 -o geotruth_int_grid.rs
```

```rust
use geo::{wkt, Area, BooleanOps, Relate, Validation};

/// int-grid-1-000004-lattice-poly.small-rot; family int-grid; degeneracy lattice; range normal
#[test]
fn geotruth_int_grid_1_000004_lattice_poly_small_rot() {
    let a = wkt! { POLYGON((2.0 4.0, 1.0 7.0, 0.0 4.0, 2.0 4.0)) };
    let b = wkt! { POLYGON((1.0 3.0, 0.0 2.0, -1.0 1.0, 0.0 6.0, 3.0 5.0, 1.0 3.0)) };
    assert_eq!(a.is_valid(), true, "valid_a");
    assert_eq!(b.is_valid(), true, "valid_b");
    let im = a.relate(&b);
    assert!(im.matches("212101212").unwrap(), "relate: expected 212101212, got {:?}", im);
    ...
    let got: f64 = a.intersection(&b).unsigned_area();
    assert!((got - 2.4).abs() <= tol, "intersection area: expected 2.4, got {}", got);
    ...
}
```

Placed in the `tests/` directory of a crate that depends on `geo = "0.33.1"`, this file
compiled, and its 3 tests passed, with `cargo test` (Rust 1.94.1, the lock file of
`adapters/rust_geo`).

## Shapely (`pytest`)

```console
$ geotruth export --format pytest corpus/cases/core/int-grid.jsonl --limit 3 -o test_int_grid.py
wrote test_int_grid.py
$ python -m pytest -q test_int_grid.py
...................................................                      [100%]
51 passed in 0.32s
```

(Shapely 2.1.2 with GEOS 3.13.1.) The module holds the cases and their exact answers as
data, with one parametrized test per relate matrix, predicate, validity and overlay area.
It skips itself when Shapely is not installed.

## What is verified

The test suite (`tests/corpus/test_export.py`, `test_export_runners.py`) checks the
structure of every format, and, when the runners are built, that a list of known-good cases
passes in GEOS `xmltester` and in JTS with RelateNG, that a list of known-failing cases
fails exactly on the listed operations, and that the pytest export passes against the
installed Shapely. The Boost.Geometry and Clipper2 snippets are not compiled by the test
suite; the georust example above was compiled by hand.
