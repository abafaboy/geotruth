# Adapters

An adapter runs one geometry library on geotruth's cases and reports its answers in a
common format. This page describes the contract (v2), the manifest that says what the
library promises, and how to add a library. Each adapter's own README, under
[`adapters/`](../adapters/), documents how every field is computed for that library.

## The adapters

| directory | targets (`geotruth run --lib ...`) | language |
|---|---|---|
| [`shapely/`](../adapters/shapely/) | `shapely` (GEOS 3.13.1 through Shapely 2.1.2) | Python |
| [`geos_main/`](../adapters/geos_main/) | `geos-main` (git main, pinned), `geos-release` (3.15.0) | C, C++ |
| [`jts_main/`](../adapters/jts_main/) | `jts-main` (git master, pinned), `jts-release` (1.20.0) | Java |
| [`boost_geometry/`](../adapters/boost_geometry/) | `boost-1.83`, `boost-develop` (pinned), `boost-release` (1.92) | C++ |
| [`clipper2/`](../adapters/clipper2/) | `clipper2` (git main, pinned) | C++ |
| [`cgal/`](../adapters/cgal/) | `cgal` (5.6, exact kernel: an external control) | C++ |
| [`rust_geo/`](../adapters/rust_geo/) | `rust-geo` (georust `geo` 0.33.1) | Rust |
| [`js/`](../adapters/js/) | `turf`, `polygon-clipping`, `polyclip-ts`, `martinez`, `jsts` | JavaScript |
| [`engine_control/`](../adapters/engine_control/) | `engine-control`: geotruth's own engine; must score no headline failure | Python |
| [`mutant/`](../adapters/mutant/) | `mutant`: the control with planted faults; every fault must be caught | Python |

`geotruth run --list` prints the targets with their `lib` strings. The exact versions and
commits are pinned in each adapter's build script and recorded in its manifest.

## Running one

```sh
export GEOTRUTH_BUILD_DIR=~/.cache/geotruth     # where builds live (the default)
adapters/clipper2/build.sh                        # build once; nothing is built by `run`
geotruth run   --lib clipper2 --tier core         # results/clipper2/core.jsonl, run.json
geotruth score --lib clipper2 --tier core --expected corpus/expected/core.jsonl
```

To test your own build of a library (a branch, a fix), point the run at its build tree:

```sh
BUILD_ROOT=/path/to/tree adapters/geos_main/build.sh
geotruth run --lib geos-main --prefix /path/to/tree
```

`--prefix` is exported as the adapter's build-root variable (`BUILD_ROOT`, `JTS_BUILD_DIR`
or `CARGO_TARGET_DIR`, named by `build_root_override` in the manifest); for Shapely it is
prepended to `PYTHONPATH`.

The runner enforces a per-operation timeout (`--timeout`, default 3 s, passed to the
adapter as `GEOTRUTH_OP_TIMEOUT`) and a watchdog of its own, restarts an adapter that dies,
stops at a per-library wall budget (`--budget`, default 3600 s), validates every result line
against the schema, and records provenance in `run.json`.

## Contract v2

An adapter is a command:

```sh
RUN CASES.jsonl > RESULTS.jsonl        # RUN is the manifest's `run`
RUN --version                          # prints the lib string, e.g. clipper2@2.0.1-f9c5eb6
```

It reads one case per line and writes **exactly one result line per case, in the same
order**. The formats are JSON Schemas:
[`case.v2`](../schemas/case.v2.schema.json) in,
[`result.v2`](../schemas/result.v2.schema.json) out.

### Input

```json
{"id": "...", "family": "...", "tags": {...}, "provenance": {...},
 "ops": ["relate", "predicates", "validity", "overlay"],
 "a": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
 "b": {"type": "LineString", "coordinates": [[1, 1], [3, 1]]}}
```

- Operands are typed geometries: `Point`, `LineString`, `Polygon`, `MultiPoint`,
  `MultiLineString`, `MultiPolygon`, `GeometryCollection` (with `geometries`), possibly
  empty (`"coordinates": []`) or with empty elements.
- Numbers must be read as IEEE-754 doubles with correct rounding, as Python's `float()`,
  glibc's `strtod` and Java's `Double.parseDouble` do: `9007199254740993` becomes 2^53.
  The literals `NaN`, `Infinity` and `-Infinity` may appear (as Python's `json` writes
  them); they make an operand invalid.
- `ops` selects the groups to answer: `echo`, `relate`, `predicates`, `validity`,
  `overlay`. Absent means every group except `echo`.

### Output

```json
{"id": "int-grid-1-000004-lattice-poly.small-rot", "lib": "clipper2@2.0.1-f9c5eb6",
 "relate": null,
 "predicates": {"intersects": true, "disjoint": false, "touches": null, "crosses": null, ...},
 "valid_a": null, "valid_b": null,
 "overlay": {"intersection": {"type": "Polygon", "coordinates": [[[1.0, 5.0], [0.0, 5.0], ...]]},
             "union": {...}, "difference": {"type": "Polygon", "coordinates": []},
             "symdifference": {...}},
 "errors": {}}
```

(The Clipper2 adapter's answer to a core case, abridged. Clipper2 has no DE-9IM and no
validity check, so those fields are `null`.)

Only the requested groups appear. Every field is one of:

- the library's answer: a DE-9IM string for `relate` (rows A, columns B, in the order
  II IB IE BI BB BE EI EB EE), booleans for the ten predicates (`intersects`, `disjoint`,
  `touches`, `crosses`, `overlaps`, `contains`, `covers`, `within`, `covered_by`,
  `equals`) and for `valid_a` / `valid_b`, and typed geometries for the four overlays
  (`intersection`, `union`, `difference`, `symdifference`);
- `null` when the library does not provide the field at all;
- `"unsupported"` when this input is outside the library's documented contract (the
  scorer then never calls it wrong);
- `null` plus an entry in `errors`, keyed by the field path (`relate`, `valid_a`,
  `predicates.touches`, `overlay.union`, or `*` for the whole case), when it failed:
  `{"kind": "exception" | "crash" | "timeout" | "memory", "message": "..."}`.

`elapsed_ms` (per field path) is optional; the adapters add it with `--timing`.

**Write output coordinates yourself**, in shortest round-trip form (Python `repr` or
`json`, C++ `std::to_chars`, Java `Double.toString` on JDK 19 or later, JavaScript
`String(x)`), never through the library's WKT writer: Shapely's WKT defaults to 6 decimals
and Boost's stream to 6 significant digits, which would make a correct answer look wrong.

**Isolate every operation.** A crash, hang or out-of-memory in one operation must fail
that operation only. The shared runtimes do this by running the library in a forked
worker that streams each result back; an operation over the timeout is killed
(`{"kind": "timeout"}`), a dead worker fails that operation (`{"kind": "crash"}`), and a
fresh worker continues with the next one. The worker's address space is capped (4096 MiB
by default; `GEOTRUTH_ADAPTER_MEM_MB` in the Python runtime), so that running out of memory
is an error of that operation too. Read the per-operation timeout from
`GEOTRUTH_OP_TIMEOUT` (seconds), which the runner sets.

### The parse-echo canary

With `ops: ["echo"]` the adapter writes back the operands exactly as the library read
them, as `"echo": {"a": ..., "b": ...}`. The canary case
([`schemas/examples/case.v2.valid.json`](../schemas/examples/case.v2.valid.json)) contains
2^53+1 written as an integer, subnormals (5e-324, -2.5e-310), -0.0,
0.30000000000000004, the smallest normal double and the largest double. The echo must
reproduce every double bit for bit, including the sign of zero. An adapter that fails it
reads different numbers from the ones the exact answer is about, so nothing else it
reports can be graded. The adapter tests (`tests/harness/test_native_contract.py`,
`test_managed_adapters.py`) run the canary against every built target; the scorer grades
`echo` records wherever a case asks for them.

### Shared runtimes

You rarely need to implement the protocol from scratch:

- **Python:** [`geotruth.harness.pyadapter`](../src/geotruth/harness/pyadapter.py). Provide a
  `Library` (its `lib` string and a `session(case)` that answers each operation, raising
  `Unsupported` for out-of-contract input) and call `pyadapter.main(...)`. The Shapely
  adapter is the reference example; the engine control is the smallest.
- **C/C++:** [`adapters/geos_main/adapter_v2.hpp`](../adapters/geos_main/adapter_v2.hpp), a
  header-only C++17 runtime with a JSON reader (`strtod`), a shortest round-trip writer
  (`std::to_chars`) and the forked-worker isolation. The GEOS, Boost.Geometry, Clipper2
  and CGAL adapters use it.
- JTS, Rust `geo` and the JavaScript libraries have their own implementations in their
  directories.

## The manifest (`adapter.toml`)

Every adapter directory has a manifest that states what each library build promises, so
that it is judged only on that ([`schemas/adapter.v2.schema.json`](../schemas/adapter.v2.schema.json)).
Anything in it that was not checked against the library's source or documentation carries
an `# uncertain:` comment.

```toml
manifest_version = 1

[adapter]
name = "clipper2"                          # the directory under adapters/
language = "C++17"
contract = "v2"
owner = "..."                              # who maintains the adapter
build = "adapters/clipper2/build.sh"       # the build recipe
build_root = "$GEOTRUTH_BUILD_DIR/clipper2"
build_root_override = "BUILD_ROOT"        # what `geotruth run --prefix` sets
isolation = "..."                          # how crashes, hangs and memory are contained

[[target]]                                 # one per library build
id = "clipper2"                            # the name `geotruth run --lib` takes
library = "Clipper2"
upstream = "https://github.com/AngusJohnson/Clipper2"
version = "2.0.1"
commit = "f9c5eb6..."                      # when built from git
lib = "clipper2@2.0.1-f9c5eb6"             # what `run --version` prints
run = "adapters/clipper2/run.sh"
version_command = "adapters/clipper2/run.sh --version"
toolchain = "g++ 13.3 (Ubuntu 24.04), -O2 -g -std=c++17 -Wall"
options = []                               # every departure from the library's defaults

[target.fields]
supported = ["echo", "overlay.intersection", "overlay.union", "overlay.difference",
             "overlay.symdifference"]
unsupported = ["relate", "valid_a", "valid_b", "predicates.touches", ...]   # always null

[target.fields.derived]                    # computed from other calls: a fault counts once
"predicates.intersects" = "Intersect area > 0 (exact shoelace of the result), or the boundaries meet"
"predicates.disjoint" = "not predicates.intersects"

[target.precision]
model = "int64 grid, exact integer arithmetic ..."
delta = { kind = "grid", value = 2 }       # δ_lib, the overlay displacement budget
grid = "2^-k, k the smallest integer in 0..60 that makes every ordinate an integer ..."
tolerance_predicates = false               # does any predicate use a tolerance?
tolerances = ["..."]

[target.coordinates]
range = "..."                              # the supported coordinate range
out_of_range = "unsupported"               # or "not detected"
```

(Abridged from [`adapters/clipper2/adapter.toml`](../adapters/clipper2/adapter.toml).)

The key parts, for the scorer:

- **`fields`** partitions the contract's fields into `supported` (a library call of its
  own), `derived` (computed from other calls: say how) and `unsupported` (always `null`).
  Every field appears exactly once.
- **`precision.delta`** is δ_lib, the displacement the library's documentation allows in
  overlay output: `relative` (× M, the largest absolute input ordinate), `ulp` (× ulp(M)),
  `absolute`, `grid` (grid steps, with the step described in `grid`) or `undocumented`.
  See [SCORING.md](SCORING.md#the-displacement-budget-δ_lib). Take it from the library's
  documentation or source and cite where; if the library documents no bound, say
  `undocumented` rather than guess.
- **`tolerance_predicates`** is true when any predicate compares with a tolerance (Turf,
  Boost's `equals`); such failures are labelled in the results.
- **`options`** lists every non-default setting the adapter uses. Prefer the library's
  defaults: the results should describe the library as its users call it.

## Adding a library

1. **Open an issue first** if the library is large or unusual; it saves work on both
   sides.
2. **Create `adapters/<name>/`** with:
   - `build.sh`: fetches the library at a **pinned** commit or release (never an unpinned
     branch head by default), builds it under `$GEOTRUTH_BUILD_DIR/<name>` (outside the
     repository), with an override variable for the tree; it must be safe to re-run and
     should rebuild only what changed. Use at most `JOBS` (default 2) parallel jobs.
   - a run wrapper that takes `CASES.jsonl` and `--version`;
   - the adapter itself, on a shared runtime if possible;
   - `adapter.toml` (above);
   - `README.md`: a table saying how every field is computed (which library call, which
     options), what is out of contract and why, and any caveat a reader needs.
3. **Report only what the library computes.** If a predicate is derived from another call
   in the adapter (not in the library), declare it in `derived`. If the library has no
   notion of a field, report `null`. If an input is outside what the library documents,
   report `"unsupported"`, citing the documentation in the README.
4. **Test it.** `python -m pytest -m unit tests/harness/test_adapter_manifests.py` checks
   every manifest. The contract tests (`tests/harness/test_native_contract.py` for C/C++
   adapters, `test_managed_adapters.py` for the others) run the canary, every pair of
   geometry kinds, schema validity and the isolation against every built target; add the
   new directory to their target lists (`NATIVE_DIRS` in `test_native_support.py` or
   `MANAGED_DIRS` in `test_managed_adapters.py`).
5. **Run it** on the curated and core tiers and read the failure clusters. Before
   believing a failure, check the adapter: early "bugs" in a new adapter are often the
   adapter's own (a WKT writer rounding, a wrong orientation, a predicate derived the wrong
   way). The engine control passing on the same cases rules out the rest of the harness.
6. **Add it to the nightly matrix** in [`.github/workflows/nightly.yml`](../.github/workflows/nightly.yml).
7. **Before any result is published**, the library's maintainers get notice and a preview
   (see [CONTRIBUTING.md](../CONTRIBUTING.md#triage-and-reporting-to-library-maintainers)).

## The v1 contract

The original bug-hunt harness used a simpler contract for polygon/polygon cases: the
FORMAT-v1 lines of [`harness/FORMAT-v1.md`](../harness/FORMAT-v1.md), run by
`harness/hunt.sh`. The adapters still answer legacy lines with their v1 code, so old
rounds can be reproduced, but new adapters need only v2.
