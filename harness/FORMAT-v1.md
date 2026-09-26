# Case and result format, v1

This is the contract of the bug-hunt harness that geotruth grows out of. Every v1 tool
speaks it: the adapters in [`adapters/`](../adapters/), the generators in
[`corpus/generators/`](../corpus/generators/), the reference oracle
[`tests/reference/oracle.py`](../tests/reference/oracle.py), and
[`compare.py`](compare.py) and [`hunt.sh`](hunt.sh) here. It is JSON Lines: one object
per line. Adapter contract v2 ([DESIGN.md §4.1](../docs/DESIGN.md)), with typed geometries,
relate matrices and overlay output, will supersede it; until then this file is normative.

## Cases (`corpus/cases/*.jsonl`)

```json
{"id": "family-000123", "family": "near-collinear", "a": MULTIPOLYGON, "b": MULTIPOLYGON}
```

`MULTIPOLYGON` is GeoJSON MultiPolygon coordinates: a list of polygons; each polygon is a
list of rings (shell first, then holes); each ring is a list of `[x, y]` pairs, **closed**
(the last point repeats the first). Coordinates are JSON numbers that round-trip exactly
to IEEE-754 doubles (Python `json.dumps` of a float, JavaScript `JSON.stringify`, C
`%.17g`, all qualify). When a multipolygon has exactly one polygon, adapters must build a
plain Polygon, not a one-part MultiPolygon.

Generators should only emit inputs that are valid OGC geometries (simple rings, holes
inside shells, parts with disjoint interiors), unless the family name starts with
`invalid-`, which is for testing validity checks only.

## Results (`<results dir>/<lib>/*.jsonl`)

One line per case, same `id`:

```json
{"id": "...", "lib": "geos@3.13.1",
 "valid_a": true, "valid_b": true,
 "intersects": true, "disjoint": false, "touches": false, "overlaps": true,
 "contains": false, "covers": false, "within": false, "covered_by": false, "equals": false,
 "area_inter": 1.0, "area_union": 7.0, "area_diff": 3.0, "area_symdiff": 6.0,
 "errors": {"area_union": "TopologyException: ..."}}
```

- Predicates are about the ordered pair: `contains` means A contains B, `within` means A
  is within B, `area_diff` is the area of A minus B.
- A field the library does not support is `null`. A field whose computation threw is
  `null` and the message goes in `errors` under the same key.
- `lib` is `<name>@<version or commit>`, for example `geos@3.14.0dev-1a2b3c4`.

## Adapter contract

`<adapter> CASES.jsonl > RESULTS.jsonl`, one output line per input line, in order,
never crashing on a single bad case (catch per operation, put it in `errors`). A case
that takes over 10 s may be reported with every field null and `errors.timeout`.

## Comparison

`python harness/compare.py CASES.jsonl ORACLE.jsonl RESULTS.jsonl` lists every disagreement.
The exact answers for the tracked seed corpus are in
[`corpus/expected-v1/seed.jsonl`](../corpus/expected-v1/seed.jsonl):

- `predicate`: a predicate differs from the exact oracle (inputs valid). Predicates are
  exact questions about exact inputs, so any difference is a wrong answer.
- `area`: an overlay area differs from the exact value by more than 1e-6 relative to
  the operands' area (gross error; rounding of output vertices explains ~1e-15).
- `validity`: `valid_a`/`valid_b` differs from the exact oracle (single-ring polygons).
- `error`: the library threw on valid input.
