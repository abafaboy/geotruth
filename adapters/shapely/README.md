# shapely: GEOS through Shapely (the reference adapter)

The first and simplest adapter of the bug hunt, and the reference implementation of the v1
contract in [`../../harness/FORMAT-v1.md`](../../harness/FORMAT-v1.md). It runs the GEOS
that ships inside the installed Shapely wheel: `lib` is `geos@<GEOS version>+shapely@<Shapely
version>`, currently `geos@3.13.1+shapely@2.1.2`.

```sh
pip install 'shapely==2.1.2'
python3 adapters/shapely/shapely_adapter.py corpus/cases/seed.jsonl > /tmp/shapely.jsonl
python3 harness/compare.py corpus/cases/seed.jsonl corpus/expected-v1/seed.jsonl /tmp/shapely.jsonl
```

Nothing is built, so there is no build tree. It is also the default adapter of
[`corpus/generators/pipeline.sh`](../../corpus/generators/pipeline.sh).

| file | what |
|---|---|
| `shapely_adapter.py` | the adapter |
| `adapter.toml` | manifest (DESIGN.md §4.2): fields, precision model and δ, options |

## What each field is

A one-part case becomes a `Polygon`, anything else a `MultiPolygon`.

| field | Shapely call |
|---|---|
| `valid_a`, `valid_b` | `is_valid` (GEOS IsValidOp) |
| `intersects` `disjoint` `touches` `overlaps` `contains` `covers` `within` `covered_by` `equals` | the Shapely predicate of the same name, `a.<pred>(b)`. GEOS 3.13 evaluates them with RelateNG; `equals` is topological equality |
| `area_inter` `area_union` `area_diff` `area_symdiff` | `.area` of `a.intersection(b)`, `a.union(b)`, `a.difference(b)`, `a.symmetric_difference(b)` (OverlayNG) |

Exceptions are caught per operation (the field is `null`, `repr(e)` goes in `errors`). There
is no process isolation and no timeout: a GEOS crash or hang stops the run. Contract v2
(DESIGN.md §4.1) requires isolation, so this adapter needs it before it is scored.

## Seed smoke test

`corpus/cases/seed.jsonl` (1000 cases): 0 disagreements with `corpus/expected-v1/seed.jsonl`.
