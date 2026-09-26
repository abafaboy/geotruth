# shapely: GEOS through Shapely

The GEOS that ships inside the installed Shapely wheel, through Shapely's vectorized
functions: `lib` is `geos@<GEOS version>+shapely@<Shapely version>`, currently
`geos@3.13.1+shapely@2.1.2`. Target id `shapely`. It answers adapter contract v2
(DESIGN.md §4.1, `schemas/result.v2.schema.json`) for typed lines and the legacy v1
contract ([`../../harness/FORMAT-v1.md`](../../harness/FORMAT-v1.md)) for legacy lines,
unchanged, so it is still the default adapter of
[`corpus/generators/pipeline.sh`](../../corpus/generators/pipeline.sh).

```sh
pip install 'shapely==2.1.2'
python3 -m geotruth run --lib shapely --tier core    # results/shapely/core.jsonl
python3 -m geotruth score --lib shapely --tier core
python3 adapters/shapely/shapely_adapter.py corpus/cases/curated.jsonl   # the bare adapter
python3 adapters/shapely/shapely_adapter.py --version
```

Nothing is built, so there is no build tree.

| file | what |
|---|---|
| `shapely_adapter.py` | the adapter: WKB writer and reader, the v2 and v1 sessions |
| `adapter.toml` | manifest (DESIGN.md §4.2): fields, precision model and δ, isolation |

The contract-v2 runtime (reading lines, `ops`, per-operation isolation, error kinds) is
shared with the engine control:
[`src/geotruth/harness/pyadapter.py`](../../src/geotruth/harness/pyadapter.py).

## Coordinates in and out

Operands go into GEOS as little-endian WKB written by the adapter from the exact doubles
(JSON numbers read with `float()` semantics), and results come back as WKB read by the
adapter (`shapely.to_wkb(..., output_dimension=2)`): no coordinate passes through a WKT or
GeoJSON writer or reader, so the output doubles are GEOS's own, and Python's `json` writes
them in shortest round-trip form. Empty elements and non-finite coordinates go through
unchanged. The parse-echo canary (`echo`) writes the operands back the same way.

## What each field is (contract v2)

| field | Shapely call |
|---|---|
| `echo` | the operands as built (`shapely.from_wkb`), written back through WKB |
| `valid_a`, `valid_b` | `shapely.is_valid` (GEOS IsValidOp) |
| `relate` | `shapely.relate` (GEOS 3.13: RelateNG) |
| `predicates.<name>` | `shapely.intersects`, `disjoint`, `touches`, `crosses`, `overlaps`, `contains`, `covers`, `within`, `covered_by`, `equals` (RelateNG; `equals` is topological equality) |
| `overlay.<op>` | `shapely.intersection`, `union`, `difference`, `symmetric_difference` (OverlayNG through OverlayNGRobust, `grid_size=None`) |

A geometry GEOS refuses to build (an unclosed ring, a ring with too few points) fails
every field that needs it, with GEOS's message.

**Precision (manifest).** Floating PrecisionModel. OverlayNGRobust tries the floating
noder, then snapping with a tolerance of M/10¹² growing ×10 per try for 5 tries, then snap
rounding; δ is the loosest documented fallback, `{kind = "relative", value = 1e-8}` of the
largest input ordinate M.

## Isolation

Every operation runs in a forked worker process that streams each result back as soon as
it has it. An operation over `GEOTRUTH_OP_TIMEOUT` / `SHAPELY_ADAPTER_TIMEOUT` seconds
(default 10) is killed and gets `{"kind": "timeout"}`; a worker that dies (a GEOS crash)
fails that operation with `{"kind": "crash"}`, and a fresh worker carries on with the next
one. The worker's address space is capped at `GEOTRUTH_ADAPTER_MEM_MB` (default 4096); a
`MemoryError` is `{"kind": "memory"}`. `--no-fork` runs in-process (debugging only).
`GEOTRUTH_PYADAPTER_TEST_FAULT=crash:<path>|hang:<path>|throw:<path>|oom:<path>` injects a
fault into one field path, to test the isolation.

## Legacy v1 fields

A legacy line (multipolygon coordinate arrays, FORMAT-v1) gets the v1 fields exactly as
before: `valid_a`, `valid_b`, nine predicates, and the four `area_*` values (`.area` of the
OverlayNG results). A one-part case becomes a `Polygon`, anything else a `MultiPolygon`.
`corpus/cases/seed.jsonl` (1000 cases): 0 disagreements with
`corpus/expected-v1/seed.jsonl`.

## Results

Core tier (3400 cases), 2026-09-26, `geotruth run` + `geotruth score`: **558 headline
failures**, 0 scorer failures. relate wrong on 162 cases (mostly line and point inputs),
predicates 103, validity 43; overlays: 152 gross, 34 topological, 62 exceptions (tier
counts over the four operations). Notable:

- 43 overlay exceptions in the `empty` family, `AssertionFailedException: Should never
  reach here`, on operands with empty elements;
- at the extreme coordinate range GEOS overflows: the union of two crossing
  MultiLineStrings near 1e212 (`line-line-1-000030-proper-cross.ba.unit.extreme`) comes
  back rerouted through a far vertex (Hausdorff distance about 8% of the largest ordinate),
  with NumPy warning "overflow encountered in union";
- GeometryCollection operands that are not simple (mixed dimensions or overlapping
  polygons, see above) make the overlays `"unsupported"`: 210 cases per operation, most
  of the `gc` family.
