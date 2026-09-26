# Adapters

One directory per adapter. An adapter runs one geometry library on case files and writes
one result line per case, following the v1 contract in
[`harness/FORMAT-v1.md`](../harness/FORMAT-v1.md):

```sh
adapters/<lib>/run.sh CASES.jsonl > RESULTS.jsonl
```

| directory | libraries (the name `harness/hunt.sh` uses) | language |
|---|---|---|
| [`shapely/`](shapely/) | GEOS 3.13.1 through Shapely 2.1.2 (`shapely`), the reference adapter | Python |
| [`geos_main/`](geos_main/) | GEOS git main (`geos-main`), C API | C |
| [`jts_main/`](jts_main/) | JTS git master (`jts-main`) | Java |
| [`clipper2/`](clipper2/) | Clipper2 git main (`clipper2`) | C++ |
| [`boost_geometry/`](boost_geometry/) | Boost.Geometry 1.83 and develop (`boost-1.83`, `boost-develop`) | C++ |
| [`rust_geo/`](rust_geo/) | georust `geo` 0.33.1 with i_overlay (`rust-geo`) | Rust |
| [`js/`](js/) | Turf 7.4, polygon-clipping 0.15.7, polyclip-ts 0.16.8, martinez 0.8.1 | JavaScript |

Each directory has a README (what every field is computed with, caveats, smoke-test
results), a build script, run wrappers and an `adapter.toml` manifest.

## Build root

Every build script and run wrapper keeps its build tree outside the repository, under

```
$GEOTRUTH_BUILD_DIR/<name>        GEOTRUTH_BUILD_DIR defaults to ~/.cache/geotruth
```

with `<name>` = `geos-main`, `jts-main`, `clipper2`, `boost-geometry`, `rust-geo/target`
or `js-libs`. One adapter's tree can still be moved on its own with that adapter's override
variable (`BUILD_ROOT`, `JTS_BUILD_DIR` or `CARGO_TARGET_DIR`, see each README);
`harness/hunt.sh` ignores `BUILD_ROOT`, since one exported value would point every
adapter at the same tree. Paths inside the repository are resolved from each script's own
location, so the scripts work from any working directory.

```sh
export GEOTRUTH_BUILD_DIR=~/.cache/geotruth    # the default
adapters/clipper2/build.sh && adapters/clipper2/run.sh corpus/cases/seed.jsonl | head -1
```

## Manifest (`adapter.toml`)

The manifest records what DESIGN.md §4.2 asks for, so the scorer can judge a library only
on what it promises (DESIGN.md §0.3). It is TOML, `manifest_version = 1`:

```toml
manifest_version = 1

[adapter]                  # the adapter itself
name = "clipper2"          # directory under adapters/
language = "C++17"
contract = "v1"            # harness/FORMAT-v1.md; "v2" once DESIGN.md §4.1 is implemented
owner = "..."              # who maintains the adapter
build = "adapters/clipper2/build.sh"
build_root = "$GEOTRUTH_BUILD_DIR/clipper2"
build_root_override = "BUILD_ROOT"
isolation = "..."          # crash / hang / memory isolation per case or operation

[[target]]                 # one per library build the adapter runs
id = "clipper2"            # the name harness/hunt.sh and the results directories use
library = "Clipper2"
upstream = "https://github.com/AngusJohnson/Clipper2"
version = "2.0.1"          # release, or the version the development branch reports
commit = "f9c5eb6..."      # pinned commit, when built from git
lib = "clipper2@2.0.1-f9c5eb6"             # the `lib` field of its result lines
run = "adapters/clipper2/run.sh"
version_command = "adapters/clipper2/run.sh --version"
toolchain = "g++ 13.3, -O2 -std=c++17"
options = ["..."]          # every departure from the library's defaults

[target.fields]            # v1 result fields
supported = ["area_inter", ...]            # computed by a library call of its own
derived = { disjoint = "not intersects" }  # computed from other calls; not counted twice
unsupported = ["valid_a", ...]             # always null

[target.precision]
model = "..."              # the precision model of overlay and predicates
delta = { kind = "grid", value = 2 }       # δ_lib, the overlay displacement budget
grid = "..."               # for kind = "grid": the grid step
tolerance_predicates = false               # does any predicate use a tolerance?
tolerances = ["..."]       # which, and how large

[target.coordinates]
range = "..."              # the supported coordinate range
out_of_range = "unsupported"               # what the adapter reports beyond it
```

`delta.kind` is one of:

- `"relative"`: δ = `value` × M, where M is the largest absolute input ordinate of the case;
- `"grid"`: δ = `value` grid steps, the step being described by `grid`;
- `"undocumented"`: the library documents no bound. Overlay output can then be graded only
  as exact, correctly rounded, gross or topological (DESIGN.md §4.3 tiers 1, 2, 4-6).

Anything a manifest states that was not checked against the library's source or
documentation carries an `# uncertain:` comment.

A cross-check lives in `tests/harness/`: every adapter directory has a manifest that parses,
names only v1 fields, lists each exactly once, and points at scripts that exist.
