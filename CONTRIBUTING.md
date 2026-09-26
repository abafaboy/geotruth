# Contributing to geotruth

Thank you for helping. geotruth makes claims about other people's software, so correctness
and fairness come before everything else here: a wrong exact answer, or a library judged on
something it never promised, does real harm. Contributions of every size are welcome,
and these are especially valuable:

- **a case where the exact engine is wrong** (the most important bug report this project
  can get; there is an issue template for it);
- **corrections from library maintainers**: an adapter that calls your library in a way you
  would not recommend, a manifest that misstates its precision model or its supported
  input, behaviour that is documented and should be `by-design`;
- new adapters, new corpus families, exports to more test formats, documentation.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues, including crashes
that geotruth finds in other libraries, follow [SECURITY.md](SECURITY.md), not the public
tracker.

## Development setup

```sh
git clone https://github.com/abafaboy/geotruth
cd geotruth
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'            # add 'shapely==2.1.2' for the GEOS cross-checks
pre-commit install                 # optional: ruff and file checks on commit
```

Python 3.10 to 3.13 are supported. gmpy2 is a dependency; the pure-Python `fractions`
backend is kept as an independent cross-check (`GEOTRUTH_RATIONAL=fractions`), and CI runs
the engine tests without gmpy2 installed.

The [Makefile](Makefile) has the common commands; `make ci` runs what a pull request runs
(lint, unit tests and the cross-check subset) on one Python version.

## Tests

Tests live in `tests/` and are selected by marker:

| marker | what | how to run | time on the development machine |
|---|---|---|---|
| `unit` | engine, harness, corpus and export tests | `make unit` (`pytest -m unit`) | 1 to 2 minutes |
| `crosscheck` | independent implementations against each other: the two relate routes, the overlay certificate, the references, GEOS through Shapely | `make crosscheck-ci` (the CI subset) or `make crosscheck` (all) | about 5 and 9 minutes |
| `slow` | large arrangements and full corpora | `make slow` | longer |

Tests under `tests/unit/`, `tests/crosscheck/` and `tests/slow/` get their marker from the
directory; tests elsewhere carry it explicitly. `HYPOTHESIS_PROFILE=ci` (what CI uses) or
`thorough` runs more property-test examples.

Adapter tests run against every library build they find under `$GEOTRUTH_BUILD_DIR`
(default `~/.cache/geotruth`) and skip the ones that are not built. Build a library with its
adapter's script, for example `adapters/clipper2/build.sh`; see
[docs/ADAPTERS.md](docs/ADAPTERS.md). Builds use `JOBS` parallel jobs (default 2).

## Code style

- `ruff check .` must be clean with the version pinned in
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (`RUFF_VERSION`); the rules are in
  `pyproject.toml`. Lines are at most 100 characters.
- Modules start with a docstring that says what they do and, where one applies, the section
  of [docs/DESIGN.md](docs/DESIGN.md) they implement.
- Some files are kept byte for byte for provenance, and are neither linted nor edited: the
  audited references in `tests/reference/`, `tools/oracle_review/`, and the evidence in
  each `findings/<id>/` directory (the registry itself is updated as triage goes on).
  `corpus/generators/` is not linted either (much of it predates geotruth); its generators
  must keep producing exactly the published cases, which the tier tests check. The corpus
  case files and the expected answers are never edited by hand.

## Changing the engine

The engine (`src/geotruth/`) produces the answers every score depends on, so:

- **No tolerance** in any decision. Everything is decided with integers or rationals; square
  roots only in certified intervals.
- **Abstain rather than guess.** Over budget is `engine_skipped`; an internal
  inconsistency is `engine_error`.
- **Both routes.** A change to relate must keep the arrangement route and the witness route
  independent (they share only the primitives of DESIGN §2.1), and both must agree on every
  test. Overlay results must pass the independent certificate.
- **Version the answers.** If any expected answer could change (a semantic fix, a new
  canonical form), bump `geotruth.ENGINE_VERSION` in `src/geotruth/__init__.py` and regenerate
  the answers with `geotruth expect --tier core --tier curated --jobs 2`. The golden tests in
  `tests/golden/` refuse a changed `corpus/expected/` without a version bump, and
  `geotruth expect --check` tells you whether anything changed.
- **Test both backends.** `make fractions-ci` in an environment without gmpy2 runs the
  engine tests on `fractions`.
- Add a regression test for every bug fixed, with the minimal case.

## Adding a corpus family

1. Write the generator in `corpus/generators/families_v2.py` (or a new module there). It
   must be deterministic for a given seed and build exact contacts on an integer lattice,
   so that the degeneracy it targets is real, not approximate.
2. Every operand must be valid by the exact engine, unless the family is named
   `invalid-*`. Tags are computed by `corpus/generators/casev2.py`; do not set them by hand.
3. Add it to `FAMILIES_V2` at the end of `families_v2.py`, which the tier builder
   (`corpus/generators/tiers.py`) reads; rebuild with `geotruth corpus build`, check with
   `geotruth corpus verify`, and compute the answers with `geotruth expect`.
4. Published cases are immutable. A generator change that could change existing cases bumps
   the generator version and the corpus version in `corpus/MANIFEST.json`.
5. Describe the family in [docs/CORPUS.md](docs/CORPUS.md) and in
   `corpus/generators/README.md`.

By contributing cases you dedicate them to the public domain under CC0 1.0, like the rest
of the corpus ([corpus/LICENSE](corpus/LICENSE)). Code contributions are under the MIT
licence ([LICENSE](LICENSE)).

## Adding a library

See [docs/ADAPTERS.md](docs/ADAPTERS.md#adding-a-library). In short: a pinned build
script, an adapter on one of the shared runtimes, a manifest that states what the library
promises (with sources), a README, and the adapter tests. Report only what the library
itself computes, and use `"unsupported"` for input outside its documented contract.

## Triage and reporting to library maintainers

geotruth finds disagreements automatically; it never presents one as a confirmed bug
automatically. Every failure cluster (library × family × signature) has a triage status in
[`findings/registry.toml`](findings/registry.toml):

| status | meaning |
|---|---|
| `unreviewed` | found by the harness, not yet triaged by a person |
| `confirmed` | triaged: a wrong answer within the library's documented contract |
| `by-design` | triaged: documented or intended behaviour; not reported as a bug |
| `reported` | confirmed and reported upstream (`upstream_issue` is set) |
| `fixed` | fixed upstream (`fixed_in` names the release or commit) |

### From a disagreement to a finding

1. **Reproduce it** on the library's latest development code and its latest release.
2. **Rule out the adapter.** Check the parse-echo canary, compare with another adapter of
   the same library where there is one (Shapely and `geos-main` both run GEOS), and write a
   standalone program that uses only the library's public API. Most early "bugs" are
   adapter bugs.
3. **Confirm the exact answer independently**: `geotruth relate --dual`,
   `geotruth overlay --certify`, the references in `tests/reference/`, and CGAL where its
   semantics apply.
4. **Minimise it**: `geotruth minimize CASE --lib TARGET --field FIELD` delta-debugs the case
   (parts, holes, vertices, decimals) while the library keeps disagreeing with the exact
   answer.
5. **Read the library's documentation** for the behaviour. Documented behaviour, such as a
   precision grid or a tolerance, is `by-design`, and the manifest should describe it.
6. **Search the upstream tracker**, closed issues included, for the same root cause.
7. **Have someone else review the evidence** before the status becomes `confirmed`.
8. **Record it**: a directory `findings/<id>/` with the minimal cases, both exact answers,
   the standalone reproduction and a write-up, an entry in `registry.toml`, and the curated
   corpus tier rebuilt (`geotruth corpus build --tier curated`).

### Reporting upstream

- **Crashes, hangs and memory errors** follow [SECURITY.md](SECURITY.md): the library's
  private channel first.
- **Wrong answers** are reported in the library's own tracker, following its contribution
  guidelines: one issue per root cause, not one per case; the minimal case, the exact
  answer and how it was established, the standalone program, the versions tested, and an
  offer of the exported test ([docs/EXPORTS.md](docs/EXPORTS.md)). Keep it short and
  check it twice; maintainers' time is the scarcest resource involved.
- **Never file reports automatically or in bulk.**
- Update the registry entry (`reported`, `upstream_issue`) once the report is filed, and
  (`fixed`, `fixed_in`) once it is fixed.

### Publishing results

Before a library's results are first published on the results site, its maintainers are
told and shown a preview (`geotruth site --preview`), and their corrections are taken into
account. The nightly workflow that publishes the site stays disabled until the triage
registry is complete (DESIGN.md §6-§7).

## Pull requests

- Keep a pull request to one topic, with tests for new behaviour and a regression test for
  every fix.
- Run `make ci` before pushing. CI runs lint, the unit tests on Python 3.10 to 3.13, the
  engine without gmpy2, the cross-check subset and a package build.
- Update the documentation and [CHANGELOG.md](CHANGELOG.md) where users would notice the
  change.
- Commit messages: an imperative summary line, then what and why.
