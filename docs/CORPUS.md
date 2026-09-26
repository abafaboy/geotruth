# The corpus

The corpus is the set of questions geotruth asks every library: pairs of geometries,
mostly near-degenerate, whose exact answers are known. It lives in
[`corpus/`](../corpus/), and [`corpus/README.md`](../corpus/README.md) is its reference
(layout, tag definitions, generator details). This page is the overview.

## What a case is

One JSON object per line ([`schemas/case.v2.schema.json`](../schemas/case.v2.schema.json)):

```json
{"id": "line-line-1-000008-t-junction.unit.rot", "family": "line-line",
 "tags": {"degeneracy": "ulp", "range": "normal", "n": 5, "k": 1,
          "types": ["LineString", "LineString"], "variant": "t-junction.unit.rot"},
 "provenance": {"source": "generator", "generator": "corpus/generators/families_v2.py",
                "generator_version": "2", "seed": 1, "n_per_family": 1000},
 "a": {"type": "LineString", "coordinates": [...]}, "b": {...}}
```

`a` and `b` are typed geometries: Point, LineString, Polygon, their Multi- forms and
GeometryCollection, possibly empty. Coordinates are JSON numbers, and **a JSON number
means the IEEE-754 double that `float()` (or C's `strtod`) makes of it**. The literal
`9007199254740993` is therefore the double 2^53, and `0.1` is the double nearest to 0.1,
which is exactly 3602879701896397/2^55. The exact answer is the answer for those doubles,
taken as rational numbers. If you load cases in your own code, parse numbers as doubles,
not as decimals.

A case may carry `"ops"` to restrict what is asked (`["echo"]` is the parse-echo canary,
see [ADAPTERS.md](ADAPTERS.md#the-parse-echo-canary)).

## Families

17 families, from the ten polygon families of the original bug hunt and seven families
added for lines, points, collections and empty geometries:

| family | what it probes |
|---|---|
| `near-collinear` | a vertex a few ulps off another polygon's edge; edges bent or offset by ulps |
| `vertex-on-edge` | vertices exactly on another polygon's sloped edge (exact lattice points) |
| `shared-edge` | edges shared fully or partially, exactly or up to rounding |
| `tiny-transform` | the same polygon moved, rotated or scaled by 1 ulp to 1e-9 of its size |
| `sliver-spike` | near-zero-area spikes, cracks and slivers; nearly coincident parallel edges |
| `hole-contact` | holes filled, touched or nearly touched by the other operand |
| `multi-touch` | multipolygon parts touching at a point, with the other operand at the touch |
| `tiling-contact` | neighbouring tiles computed by different formulas, so shared edges agree only up to rounding |
| `int-grid` | integer-lattice polygons with many exact collinearities, at small and very large scales |
| `scaled` | cases of the other families scaled by 2^k (exact) or 10^x (rounded) |
| `line-line` | collinear overlaps, T-junctions, endpoints on vertices and segments |
| `line-mod2` | the Mod-2 boundary rule: closed lines, endpoints shared by 2, 3 or 4 lines |
| `point-geometry` | points on vertices, segments, endpoints, hole edges, inside, outside |
| `line-polygon` | lines along edges, through vertices, tangent, inside touching the boundary |
| `gc` | GeometryCollections: overlapping polygons, mixed dimensions, nesting |
| `empty` | every empty type against empty and non-empty geometries (the convention cases) |
| `invalid-zero-length-line` | lines whose points all coincide: invalid for GEOS, dimension 0 in RelateNG |

Every operand of a family whose name does not start with `invalid-` is valid by the exact
engine (GEOS IsValidOp semantics). The seven newer families are built on exact integer
lattices; about 10% of their cases are scaled by 2^±(500..900) (range tag `extreme`) and
about 15% are rotated in floating point, which turns exact contacts into ulp-level ones.
The variants of each family are listed in
[`corpus/generators/README.md`](../corpus/generators/README.md#families) and
[`corpus/README.md`](../corpus/README.md#tiers).

## Tags

Tags are computed exactly from the geometry
([`corpus/generators/casev2.py`](../corpus/generators/casev2.py)), so results can be
broken down by them:

- `degeneracy`: `lattice` when the operands (or two rings or elements of one operand)
  meet in an exact degenerate contact (a vertex on a segment or on a vertex, a collinear
  overlap); else `ulp` when a vertex lies within 4096 ulps of a segment it does not
  touch; else `generic`;
- `range`: `extreme` when a coordinate is below 1e-150 or above 1e150 in magnitude, else
  `normal`;
- `n` (coordinates), `k` (distinct points where `a` meets `b`), `types`, `variant`, and
  `flags` such as `convention`, `empty`, `gc`, `zero-length-line`, `invalid-input`,
  `mod2`, `curated`, `lead`.

The core tier by family and tag (`geotruth corpus stats --tier core`, corpus 2.0.0):

```
family                      cases  degeneracy=generic  degeneracy=lattice  degeneracy=ulp  range=extreme  range=normal
empty                         200                 150                  50               0              0           200
gc                            200                   7                 191               2             39           161
hole-contact                  200                  12                 132              56              0           200
int-grid                      200                  36                 164               0              0           200
invalid-zero-length-line      200                  27                 153              20             35           165
line-line                     200                  20                 166              14             45           155
line-mod2                     200                   0                 200               0             48           152
line-polygon                  200                  27                 145              28             48           152
multi-touch                   200                   5                 192               3              0           200
near-collinear                200                  32                  60             108              0           200
point-geometry                200                  39                 135              26             50           150
scaled                        200                  30                 110              60              0           200
shared-edge                   200                   2                 183              15              0           200
sliver-spike                  200                 105                  13              82              0           200
tiling-contact                200                  10                 114              76              3           197
tiny-transform                200                  42                  58             100              0           200
vertex-on-edge                200                   0                 200               0              0           200
total                        3400                 544                2266             590            268          3132
```

## Tiers

| tier | size | in git | what |
|---|---:|---|---|
| `core` | 3400 cases (200 per family) | yes | the tier every library runs for the results matrix |
| `curated` | one or more minimal cases per finding and lead | yes | the minimal case of every entry in the triage registry, with its provenance and upstream status |
| `full` | 17000 cases (1000 per family, seed 1) | no | every generated case; its checksums are in `corpus/MANIFEST.json` |
| `seed` | 1000 cases | yes | the v1 smoke-test corpus of the original bug hunt (FORMAT-v1, polygons only) |

**core** is a deterministic stratified sample of **full**. The strata are (variant class,
degeneracy, range, geometry types); every stratum gets one case before any gets two, the
rest is allocated in proportion, and within a stratum cases are taken in order of
sha256(id). The same parameters give byte-identical files, which the tests check.

**curated** grows as findings are triaged: each entry of
[`findings/registry.toml`](../findings/registry.toml) contributes its minimal cases, and
each documented lead in [`corpus/curated/leads.toml`](../corpus/curated/leads.toml) its
original and minimised cases. Provenance records the library, the triage status and the
upstream issue, if any.

**full** is meant to be published as a release asset. Until then, rebuild it; the
generators are deterministic, and `geotruth corpus verify` checks the result against the
checksums in the manifest:

```sh
geotruth corpus build --tier full          # 1000 per family, seed 1
geotruth corpus verify                     # every present tier file against MANIFEST.json
```

On the machine this page was written on, `geotruth corpus verify` reported
`36 files checked, 0 problems` with all four tiers present.

## Expected answers

The exact answer to every case of the core and curated tiers is in
[`corpus/expected/`](../corpus/expected/) (format
[`expected.v2`](../schemas/expected.v2.schema.json)); its
[README](../corpus/expected/README.md) lists what a record holds and the checks each
answer passes before it is written: relate computed by two independent routes, every
overlay certified independently, relate and overlay cross-checked against each other, and
a schema check. To recompute them and compare with the files, writing nothing:

```sh
geotruth expect --tier core --check --no-cache --jobs 2
```

## Versioning

- **Cases are immutable.** A published case file is never edited; a fix is a new file or
  a new tier. `corpus/SHA256SUMS` and `corpus/MANIFEST.json` make any edit visible.
- **The corpus version** (`2.0.0` for the first v2 tiers) is bumped whenever a case could
  change: a generator change bumps the generator version and the corpus version, and the
  curated tier gets a new corpus version each time it grows.
- **Expected answers are versioned separately** from the cases (`expected_version` 2), and
  each record names the engine version that produced it. Answers may change only with a
  new `geotruth.ENGINE_VERSION`; the golden tests refuse a changed answer file without a
  version bump.
- **Cite all three**: corpus version, expected version and engine version, plus the commit
  recorded in `corpus/expected/MANIFEST.json` when it matters.

## Licence

The case data and the expected answers are dedicated to the public domain under
**CC0 1.0** ([`corpus/LICENSE`](../corpus/LICENSE)). GEOS (LGPL), JTS (EPL/EDL),
Boost (BSL), Clipper2 (BSL) and any other project can copy cases into their own test
suites without asking and without attribution. [EXPORTS.md](EXPORTS.md) writes them in
each library's own test format. The generator code is code, and like the rest of the
repository it is MIT-licensed.

By contributing cases you agree to dedicate them under CC0 1.0 as well.

## Commands

```sh
geotruth corpus list [--tier core] [--family gc] [--ids]    # tiers, files, case ids
geotruth corpus list --families                             # the generator families
geotruth corpus stats --tier core --by degeneracy,range,types,flags
geotruth corpus build [--tier all|core|curated|full]        # regenerate tiers
geotruth corpus verify                                      # check against MANIFEST.json
geotruth expect --tier core [--check]                       # exact answers
```

These commands read the generators and the manifest from the repository, so they need a
source checkout (see [QUICKSTART.md](QUICKSTART.md)).
