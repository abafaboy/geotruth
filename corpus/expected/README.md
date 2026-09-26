# Expected answers (`expected.v2`)

The exact answer to every case of the corpus tiers, computed by the geotruth engine in
exact arithmetic on the exact input doubles. Like the cases, the answers are dedicated to
the public domain under CC0 1.0 ([../LICENSE](../LICENSE)).

| file | answers the cases of | in git |
|---|---|---|
| `core.jsonl` | `cases/core/*.jsonl`, files in name order, cases in file order | yes |
| `curated.jsonl` | `cases/curated.jsonl` | yes |
| `full.jsonl` | `cases/full/*.jsonl` | no: a release asset, like the full tier's cases |
| `MANIFEST.json` | for each file: sha256, size, record count, counts per status, engine version, the sha256 of every case file it answers, and where it was computed (git commit, digest of the engine sources, Python, gmpy2) | yes |

[`../expected-v1/`](../expected-v1/) holds the legacy answers of the bug hunt's oracle for the
v1 seed corpus (polygon predicates, validity and overlay areas only).

## Records

One JSON object per line, in the order of the cases, valid against
[`schemas/expected.v2.schema.json`](../../schemas/expected.v2.schema.json):

- `id`, `case_sha256` (of the canonical case, `geotruth.io.case_sha256`), `engine`
  (`version` = `geotruth.ENGINE_VERSION`, `expected_version` = `"2"`), `status`;
- `dimensions` of both operands (type dimension and RelateNG real dimension);
- `validity` of both operands: the boolean (the scored field), every defect kind, the reason
  GEOS reports first and its message;
- for two valid operands: `relate` (the DE-9IM matrix), `predicates`, `conventions` (fields
  decided by the empty-geometry convention table, scored as `convention`), and `overlay`:
  intersection, union, difference and symmetric difference, each `non_strict` (OverlayNG's
  default) and `areal` (regularized), as the exact rational side-car (`exact`, ordinates as
  `"n/d"` strings, canonical order), a display-only `wkt`, the exact `area` and
  `num_vertices`;
- `measures` of operands with finite coordinates: exact areas, certified lengths and
  centroids (intervals with the correctly rounded double), and the exact squared distance
  when both operands are valid.

Relate, predicates and overlay are not defined for invalid operands, so those records have
validity and measures only (the `invalid-zero-length-line` family, for example).

`status` is `ok`, `engine_skipped` (over the engine's size budget) or `engine_error` (the
engine failed or one of the checks below disagreed), with a `reason`; the scorer never counts
either against a library. An abstaining record keeps its validity and measures.

## How each answer is checked

Every record passes these checks before it is written (`src/geotruth/expect.py`):

- relate is computed twice, from the labelled arrangement (which also checks that relate(B, A)
  from a second arrangement is the transpose) and from witness points located directly in the
  input geometries; the two routes share only the arithmetic primitives and must agree;
- every overlay result passes the independent certificate (`geotruth.overlay_certify`), which
  re-nodes A, B and the result from scratch, and its area equals its shoelace area;
- relate and overlay, computed from different arrangements, must agree: the dimension of each
  non-strict result is the largest matrix entry over the location pairs the operation
  selects, each areal result is non-empty exactly when one of those entries away from the
  boundaries is 2, the two variants have equal areas, |A u B| = |A n B| + |A xor B|, and for
  polygonal operands |A| = |A n B| + |A - B| and |A u B| = |A| + |B| - |A n B|;
- the record validates against the schema.

## Regenerating

```sh
geotruth expect --tier core --tier curated --jobs 2   # the files in git
geotruth expect --tier full --jobs 2                  # needs cases/full (geotruth corpus build)
geotruth expect --tier core --check --no-cache        # recompute and compare; writes nothing
```

With two worker processes the core tier takes under a minute and the full tier about three
minutes on the development machine. Answers are cached by (case sha256, engine version) under
`~/.cache/geotruth/expected/` (`--cache`, `$GEOTRUTH_CACHE_DIR`); the cache directory is also
keyed by a digest of the engine sources, so an edited engine never reuses old answers. The
output does not depend on the number of jobs, the cache or the rational backend (gmpy2 or
fractions): the records carry no timestamp, commit or backend.

## Versioning

For one engine version and one set of case files the answers are fixed. `geotruth expect`
refuses to write a file whose content changed while the engine version and the case files
are the ones `MANIFEST.json` records; answers that change need a new
`geotruth.ENGINE_VERSION`. The golden tests (`tests/golden/`) check the same from the other
side: the files match the manifest, a sample recomputed from scratch matches the files (all of
them in the `slow` tests), and no file changed since git `HEAD` without a version bump. A new
case file (for example a rebuilt curated tier) needs a regeneration but no bump.

Cite answers as (corpus version, expected v2, engine version), with the commit from
`MANIFEST.json` when it matters.
