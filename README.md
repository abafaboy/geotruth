# geotruth

**Exact ground truth for computational geometry.**

geotruth checks whether geometry libraries give the *right* answer. It poses hard,
near-degenerate questions: do these two polygons touch? What is the area of their
intersection? Is this polygon valid? It compares each library's answer with the true
answer, which it computes in exact rational arithmetic on the exact input.

Every IEEE-754 double is a rational number, so for any input there is one correct answer
and it can be computed exactly. Nothing is left to tolerances or opinion.

> Status: under active construction. The repository currently holds the working
> bug-hunting harness that geotruth grows out of: an audited exact oracle, a suite of
> near-degenerate case generators, and adapters for 11 builds of 9 libraries. The full
> exact engine, the corpus and the scoreboard described in [docs/DESIGN.md](docs/DESIGN.md)
> are being built.

## What already works

- **Exact oracle** ([tests/reference/oracle.py](tests/reference/oracle.py)). It computes
  polygon/polygon predicates and overlay areas in rational arithmetic on the exact binary
  values of the input doubles. An adversarial review
  ([tools/oracle_review/](tools/oracle_review/)) checked it against an independent exact
  implementation on 36,000+ cases and found no wrong answer on valid input.
- **Engine foundation** ([src/geotruth/](src/geotruth/)). Exact integer primitives with
  per-case dyadic scaling, a typed OGC geometry model, hand-written WKT/JSON I/O, and the
  frozen arrangement (DCEL) interface. It has 380+ unit tests, and its fixtures are
  cross-checked against GEOS.
- **Adapters** ([adapters/](adapters/)) share one JSON-lines contract
  ([harness/FORMAT-v1.md](harness/FORMAT-v1.md)), each with a manifest (`adapter.toml`),
  and each isolates crashes and hangs per operation:

  | library | versions tested |
  |---|---|
  | GEOS | 3.13.1 and main |
  | JTS | master |
  | Boost.Geometry | 1.83 and develop |
  | Clipper2 | main |
  | Rust `geo` | 0.33.1 |
  | Turf | 7.4 |
  | polygon-clipping | 0.15.7 |
  | polyclip-ts | 0.16.8 |
  | martinez | 0.8.1 |

- **Generators** ([corpus/generators/](corpus/generators/)) produce ten families of near-degenerate, exactly valid
  inputs: near-collinear edges, vertices exactly on edges, shared edges, tiny
  rotations, slivers, hole contacts, touching multipolygon parts, dense tilings,
  integer grids, and extreme scales.
- **Findings** ([findings/](findings/)): each candidate bug is reproduced on the
  library's latest development code, minimised, checked by an independent skeptic,
  and searched for in the upstream tracker before anything is reported.

## Reproduce a round

```sh
pip install -e '.[dev]'
python -m pytest -m unit                      # engine and harness tests
export GEOTRUTH_BUILD_DIR=~/.cache/geotruth   # where library builds live
adapters/<lib>/build.sh                       # build the libraries you want
harness/hunt.sh 1000 3                        # generate, compute exact answers, run, compare
```

## Licence

Code: MIT, see [LICENSE](LICENSE). Corpus: CC0, see [corpus/LICENSE](corpus/LICENSE), so
any library can copy cases into its own test suite.

By Abdulfayyod Mukhamedov, built with [Claude Code](https://claude.com/claude-code).
