# Quickstart

geotruth needs Python 3.10 or later and [gmpy2](https://pypi.org/project/gmpy2/) (installed
automatically; wheels exist for the common platforms). It is developed and tested on Linux.

## Install

geotruth is not on PyPI yet. Install it from a clone of the repository:

```sh
git clone https://github.com/abafaboy/geotruth
cd geotruth
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'          # the engine, the CLI and the development tools
```

`pip install .` (without `-e`) installs the engine and the `geotruth` command as an ordinary
package; `relate`, `overlay`, `valid` and `export` then work from any directory. The
commands that work on the corpus, the adapters or the site (`corpus`, `expect`, `run`,
`score`, `site`, `minimize`) read those directories from the repository, so run them from an
editable install of a clone.

```console
$ geotruth version
geotruth 0.1.0 (engine 0.1.0)
python 3.10.20, gmpy2 2.3.1, rational backend gmpy2
```

All outputs on this page are real runs of that version (engine 0.1.0, 2026-09-26): the
single-geometry commands from a fresh virtual environment with the package installed, the
corpus and scoring examples from a clone.

## The exact answer for two geometries

`geotruth relate A B` prints the exact DE-9IM matrix and the named predicates. Operands are
WKT or typed JSON, inline, as `@FILE`, or `-` for standard input.

```console
$ geotruth relate "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (1 1, 3 1)"
A: Polygon (5 coordinates; real dimension 2)
B: LineString (2 coordinates; real dimension 1)
relate: 1020F1102
      I  B  E
   I  1  0  2
   B  0  F  1
   E  1  0  2
predicates:
  intersects  true
  disjoint    false
  touches     false
  crosses     true
  overlaps    false
  contains    false
  covers      false
  within      false
  covered_by  false
  equals      false
```

The answer is for the input **doubles**, taken as exact rationals, which is what a library
receives. `0.1`, `0.3` and `0.9` are not the decimals but the nearest doubles, and those
three points are not collinear:

```console
$ geotruth relate "POINT (0.1 0.3)" "LINESTRING (0 0, 0.3 0.9)"
A: Point (1 coordinate; real dimension 0)
B: LineString (2 coordinates; real dimension 1)
relate: FF0FFF102
      I  B  E
   I  F  F  0
   B  F  F  F
   E  1  0  2
predicates:
  intersects  false
  disjoint    true
  ...
```

`--explain` names a cell (vertex, edge or face, with exact coordinates) that realises each
matrix entry, and `--dual` recomputes the matrix by the independent witness-point route and
compares:

```console
$ geotruth relate "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (1 1, 3 1)" --explain --dual
...
relate: 1020F1102
      I  B  E
   I  1  0  2
   B  0  F  1
   E  1  0  2
   II = 1: edge (1 1)-(2 1)
   IB = 0: vertex (1 1)
   IE = 2: face left of (0 0)->(2 0)
   BI = 0: vertex (2 1)
   BE = 1: edge (0 0)-(2 0)
   EI = 1: edge (2 1)-(3 1)
   EB = 0: vertex (3 1)
   EE = 2: the unbounded face
...
witness route: 1020F1102 agrees
```

Other options: `--pattern T********` tests the matrix against a DE-9IM pattern, and
`--json` prints the answer as an expected-answer record
([`schemas/expected.v2.schema.json`](../schemas/expected.v2.schema.json)).

## The exact overlay

`geotruth overlay A B OP`, with OP one of `intersection`, `union`, `difference`,
`symdifference` or `all`. The result is printed three ways: a WKT rounded to doubles, for
display only; the exact result with rational coordinates (`"n/d"` strings); and the exact
area.

```console
$ geotruth overlay "LINESTRING (0 0, 1 1)" "LINESTRING (0 1, 2 0)" intersection
A: LineString (2 coordinates; dimension 1)
B: LineString (2 coordinates; dimension 1)
intersection (non-strict): Point, 1 vertex
  wkt:   POINT (0.6666666666666666 0.6666666666666666)
  exact: {"type": "Point", "coordinates": ["2/3", "2/3"]}
  area:  0
```

With inputs that are not exact decimals in binary, the exact coordinates show it. Here B's
vertex `3 0.1` is really (3, 3602879701896397/2^55), and `--certify` runs the independent
overlay certificate on the result:

```console
$ geotruth overlay "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "POLYGON ((1 -1, 3 0.1, 1 3, 1 -1))" intersection --certify
A: Polygon (5 coordinates; dimension 2)
B: Polygon (4 coordinates; dimension 2)
intersection (non-strict): Polygon, 5 vertices
  wkt:   POLYGON ((1 0, 2 0, 2 1.55, 1.6896551724137931 2, 1 2, 1 0))
  exact: {"type": "Polygon", "coordinates": [[["1", "0"], ["2", "0"], ["2", "111689270758788301/72057594037927936"], ["176541105392923443/104483511354995507", "2"], ["1", "2"], ["1", "0"]]]}
  area:  29063881665648697606023744899294167/15057660889751000093915401739567104 (~1.9301724137931036)
  certificate: ok (57 witnesses)
```

By default the result follows OverlayNG's non-strict semantics, which keeps the lines and
points of boundary contact and can produce a GeometryCollection. `--areal` gives the
regularized polygonal result that polygon-only clippers compute:

```console
$ geotruth overlay "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (-1 1, 3 1)" union
A: Polygon (5 coordinates; dimension 2)
B: LineString (2 coordinates; dimension 1)
union (non-strict): GeometryCollection, 10 vertices
  wkt:   GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0)), LINESTRING (-1 1, 0 1), LINESTRING (2 1, 3 1))
  ...
$ geotruth overlay "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (-1 1, 3 1)" union --areal
A: Polygon (5 coordinates; dimension 2)
B: LineString (2 coordinates; dimension 1)
union (areal): Polygon, 6 vertices
  wkt:   POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0))
  exact: {"type": "Polygon", "coordinates": [[["0", "0"], ["2", "0"], ["2", "1"], ["2", "2"], ["0", "2"], ["0", "1"], ["0", "0"]]]}
  area:  4
```

## Exact validity

`geotruth valid A` applies the GEOS IsValidOp rules exactly and lists every defect, not
only the first. A hole that touches its shell at one point is valid in OGC; two holes that
cross are not:

```console
$ geotruth valid "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 0, 2 1, 1 2, 0 0))"
Polygon: valid

$ geotruth valid "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1), (1 1, 2 0.5, 2 1.5, 1 1))"
Polygon: INVALID
first reason (GEOS precedence and noding order): Self-intersection at (1, 1) [/ hole 1; / hole 2] (rings cross at a vertex)
defects (2):
  self_intersection        Self-intersection at (1, 1) [/ hole 1; / hole 2] (rings cross at a vertex)
  self_intersection        Self-intersection at (2, 1) [/ hole 1; / hole 2] (proper crossing)
```

`--json` prints the same with each defect's exact location.

## Exit status

`relate` and `overlay` exit with 0 on success, 1 when the engine failed or (with `--dual` or
`--certify`) its independent checks disagreed, 2 for unreadable input or input outside the
engine's contract, and 3 when the case is over the engine's budget (`--max-size`,
`--max-seconds`, `--no-budget`). `valid` exits with 0 whether or not the geometry is valid,
and with 2 for unreadable input:

```console
$ geotruth relate "LINESTRING (0 0, 1" "POINT (0 0)"
geotruth relate: bad WKT in the command line: expected more input at end of input
```

## Corpus cases

From a clone, any corpus case can be given by file and id. This one is a closed line and a
point at its start; under the Mod-2 boundary rule a closed line has no boundary, so the
point is in the line's interior:

```console
$ geotruth relate @corpus/cases/core/line-mod2.jsonl --id line-mod2-1-000005-closed.point.unit --dual
A: LineString (4 coordinates; real dimension 1)
B: Point (1 coordinate; real dimension 0)
relate: 0F1FFFFF2
      I  B  E
   I  0  F  1
   B  F  F  F
   E  F  F  2
predicates:
  intersects  true
  disjoint    false
  touches     false
  crosses     false
  overlaps    false
  contains    true
  covers      true
  within      false
  covered_by  false
  equals      false
witness route: 0F1FFFFF2 agrees
```

## Grading a library

Every library runs behind an adapter ([ADAPTERS.md](ADAPTERS.md)). The engine control needs
no build, which makes it the quickest end-to-end check of an installation:

```console
$ geotruth run --lib engine-control --tier core --out results
engine-control: 3400/3400 cases in 20.914 s (0 watchdog timeouts, 0 early exits, 0 invalid lines)
results: results/engine-control/core.jsonl
provenance: results/engine-control/run.json
$ geotruth score --lib engine-control --tier core --results-dir results --expected corpus/expected/core.jsonl
library geotruth-control@0.1.0: 3400 cases, 0 headline failures (wrong or error, derived counted once; overlay tiers gross, topological, exception)
...
```

For a real library, build its adapter first. Shapely is the simplest, as it is a wheel:

```sh
pip install 'shapely==2.1.2'
geotruth run   --lib shapely --tier core --out results
geotruth score --lib shapely --tier core --results-dir results --expected corpus/expected/core.jsonl
```

The others are built from pinned upstream sources under `$GEOTRUTH_BUILD_DIR` (default
`~/.cache/geotruth`), for example `adapters/geos_main/build.sh` or
`adapters/clipper2/build.sh`; `geotruth run --list` lists every target. [SCORING.md](SCORING.md)
explains the summary, and `geotruth site --scores results` builds the static results site
from any number of scored libraries.

Remember that the corpus is adversarial: a failure count describes behaviour on deliberately
near-degenerate input, not on typical data, and a failure is not a confirmed bug until it has
been triaged ([CONTRIBUTING.md](../CONTRIBUTING.md#triage-and-reporting-to-library-maintainers)).

## Where next

- [CORPUS.md](CORPUS.md): the families, tiers and licence of the cases.
- [SCORING.md](SCORING.md): verdicts, overlay tiers and fairness rules.
- [EXPORTS.md](EXPORTS.md): cases with exact answers in each library's own test format.
- [ADAPTERS.md](ADAPTERS.md): the adapter contract and how to add a library.
- [FAQ.md](FAQ.md): why exact, why doubles are rationals, limitations, prior work.
- [DESIGN.md](DESIGN.md): the design in full.
