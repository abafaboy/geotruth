# js: Turf, polygon-clipping, polyclip-ts and martinez (Node.js)

Four adapters that follow the contract in `../../FORMAT.md`. They share one driver.

| run command | `lib` field | npm package (pinned in `package-lock.json`) | fields |
|---|---|---|---|
| `run_turf.sh CASES.jsonl` | `turf@7.4.0` | `@turf/turf` 7.4.0 | validity, 7 predicates, 4 areas |
| `run_polygon_clipping.sh CASES.jsonl` | `polygon-clipping@0.15.7` | `polygon-clipping` 0.15.7 | 4 areas |
| `run_polyclip_ts.sh CASES.jsonl` | `polyclip-ts@0.16.8` | `polyclip-ts` 0.16.8 | 4 areas |
| `run_martinez.sh CASES.jsonl` | `martinez@0.8.1` | `martinez-polygon-clipping` 0.8.1 | 4 areas |

The version in `lib` is read at run time from the installed package's `package.json`.
All four were the latest releases on npm on 2026-09-25. They were tested with Node v22.22.2.

```sh
adapters/js/install.sh        # npm ci into /tmp/claude-0/gb-build/js-libs, then symlink node_modules here
adapters/js/run_turf.sh cases/seed.jsonl > turf.jsonl
python compare.py cases/seed.jsonl results/oracle/seed.jsonl turf.jsonl
```

`install.sh` copies `package.json` and `package-lock.json` to `$BUILD_ROOT` (default
`/tmp/claude-0/gb-build/js-libs`), runs `npm ci` there, and links `adapters/js/node_modules`
to `$BUILD_ROOT/node_modules`. That keeps the roughly 29 MB tree out of the repo, and
`.gitignore` covers the link. Running `npm ci` directly in this directory works too.

## Files

| file | purpose |
|---|---|
| `adapter.mjs` | the driver: reads JSON Lines, runs a worker, applies timeouts, writes results |
| `worker.mjs` | worker thread that loads `lib_<name>.mjs` and runs its operations |
| `lib_turf.mjs`, `lib_polygon_clipping.mjs`, `lib_polyclip_ts.mjs`, `lib_martinez.mjs` | what each library computes for each field |
| `common.mjs` | builds the geometry, computes planar area, formats errors |
| `install.sh`, `run_*.sh` | install script and run wrappers |

## What is computed

Input: a one-part multipolygon becomes a GeoJSON `Polygon`, and anything else becomes a
`MultiPolygon` (FORMAT.md). Each operation gets its own deep copy of the coordinates.

**turf** (`lib_turf.mjs`), with A and B as GeoJSON Features:

| field | call |
|---|---|
| `valid_a`, `valid_b` | `booleanValid` |
| `intersects` `disjoint` `touches` `overlaps` `contains` `within` | `booleanIntersects`, `booleanDisjoint`, `booleanTouches`, `booleanOverlap`, `booleanContains`, `booleanWithin` (A, B), with default options |
| `equals` | `booleanEqual(A, B, {precision})`, exact by default (see below) |
| `covers`, `covered_by` | `null`, because Turf has no covers predicate |
| `area_inter` / `area_union` / `area_diff` | `turf.intersect` / `turf.union` / `turf.difference` of `featureCollection([A, B])` |
| `area_symdiff` | area(`difference([A,B])`) + area(`difference([B,A])`). Turf has no symmetric difference, so this field is derived. A wrong value here can also come from `difference(B, A)`. |

**Turf 7's boolean-op engine.** In Turf 7.2 and later (7.4.0 here), `@turf/intersect`,
`@turf/union` and `@turf/difference` are thin wrappers over **polyclip-ts** (^0.16.8, which
resolves to the same 0.16.8 copy that `run_polyclip_ts.sh` tests). Turf 6.x, 7.0 and 7.1 used
polygon-clipping instead. The adapter prints the engine it resolved to stderr at start-up. As
a result, Turf's `area_inter`, `area_union` and `area_diff` match polyclip-ts bit for bit on
the seed cases. The `boolean*` predicates are Turf's own code (point-in-polygon, line-intersect
and geojson-equality-ts) and do not run an overlay.

**polygon-clipping, polyclip-ts, martinez**: `intersection`, `union`, `difference` (martinez:
`diff`) and `xor` of the coordinate arrays. Only the four areas are filled; every other field
is `null`. polyclip-ts runs at its default precision: no `setPrecision` call and no snapping
epsilon. It does its arithmetic in bignumber.js on the decimal string of each input double,
and divisions round to 20 decimal places.

**Area** (`common.mjs`): planar shoelace, not `turf.area`, which is geodesic. Each ring is
first translated so that its first vertex is at the origin. This matters for the
`tiny-rotation-offset` family, which sits at 1e7. The cross products are then summed with
Neumaier compensation. A polygon's area is |shell| − Σ|holes|, which is the GeoJSON/OGC
reading and does not depend on ring orientation. Unclosed output rings (martinez emits them)
are treated as closed. A `null` or empty result has area 0. The result is measured
faithfully even when the output is invalid, such as a self-intersecting ring or a "hole"
larger than its shell, so the area can come out slightly negative. On polyclip-ts output,
this sum agrees with an exact rational shoelace of the same output to about 1e-16 of the
operands' area.

**booleanEqual precision.** Turf compares vertex by vertex, after `cleanCoords`, with an
absolute tolerance of 10^-precision. The default precision is 6, which would call every
`tiny-rotation` pair equal. The adapter passes `precision = 323.3` by default, because
`10 ** -323.3 === 5e-324`: two coordinates then match only if they are the same double.
`TURF_EQUAL_PRECISION=6` restores Turf's default, and any other number is passed through.
With precision 6, the seed run gains 299 `equals` disagreements.
`booleanEqual` remains a structural test, not topological equality. Two polygons with the
same point set but different vertices are "not equal". Other Turf tolerances are hard-coded
and left as they are: `booleanOverlap` treats inputs that are geojson-equal at 1e-6 as not
overlapping, and `booleanContains` accepts edge midpoints within 1e-6 of the boundary.

## Errors, hangs and crashes

- Each operation runs in its own `try`. A thrown error sets the field to `null` and puts
  `"<Name>: <message>"` (up to 500 characters) in `errors[<field>]`. A non-finite area or a
  non-boolean predicate result counts as an error.
- The library runs in a `worker_threads` worker, which sends back each result as soon as it
  has it. If no result arrives within `JS_ADAPTER_TIMEOUT` seconds (default 10, per
  operation), the worker is terminated. That field then gets `"timeout: ..."`, its key is
  listed in `errors.timeout`, and a new worker continues with the next operation. Fields
  that finished keep their values, which goes beyond the contract's all-null timeout line.
- The worker's heap is capped at `JS_ADAPTER_MEM_MB` (default 2048, 0 means no cap). Running
  out of memory, or any other worker death, gives `"crash: ..."` for that field, and the run
  continues.
- Library `console.*` output goes to stderr, truncated, with at most
  `JS_ADAPTER_LIB_LOG_MAX` messages (default 20) per worker. The worker's stdout is piped to
  stderr, so result lines cannot be corrupted.
- A line that is not valid JSON produces a line where every field is `null` and
  `errors.parse` is set. Blank lines produce no output.
- `JS_ADAPTER_TEST_FAULT=hang:<key>|crash:<key>|oom:<key>` injects a fault. It exists only to
  test the isolation code.

**Speed** on the 1000 seed cases: polygon-clipping 0.6 s, polyclip-ts 2.1 s, turf 2.6 s.
martinez takes 333 s, almost all of it in 33 operations that hit the 10 s timeout.

## Library quirks found while building this

- **martinez 0.8.1: broken CommonJS build.** `require('martinez-polygon-clipping')` loads
  `dist/martinez.cjs`, which calls `require("tinyqueue")`. Its dependency `tinyqueue@3.0.0` is
  ESM-only. On Node 22, `require(esm)` returns the namespace object, so every operation throws
  `TypeError: Y is not a constructor`. Older Node versions fail with `ERR_REQUIRE_ESM`. The
  adapter imports the ESM build (`dist/martinez.js`), which works.
- **martinez hangs.** Some calls loop forever: 100 % CPU, constant memory, and no end after
  90 s. One example is `xor` on seed case `rotated-neighbours-1-000003`.
- **Turf predicates.** For Polygon/Polygon, `booleanTouches` only looks at A's shell
  vertices: some vertex of A lies on B's shell and no vertex of A is strictly inside B. It
  never looks at B's vertices or at edge crossings. `booleanOverlap` returns true as soon as
  any pair of edges intersects, including edges that only touch. Most of the predicate
  disagreements in the seed run come from these two functions.
