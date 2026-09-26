# Changelog

All notable changes to geotruth are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Three versions are tracked separately and cited
together: the package version (below), the engine version (`geotruth.ENGINE_VERSION`, which
changes whenever an expected answer could change) and the corpus version
(`corpus/MANIFEST.json`).

## [0.1.0] - 2026-09-26

The first release: the exact engine, the corpus with its exact answers, the harness that
runs and grades libraries, and the tools around them. Engine 0.1.0, corpus 2.0.0, expected
answers version 2.

### Exact engine

- Exact primitives: doubles read with `float()` semantics and converted to rationals
  exactly, per-case dyadic scaling to integers, integer orientation and segment
  intersection, homogeneous intersection points; non-finite coordinates carried and
  reported as invalid, never raised on.
- A typed OGC Simple Features model (Point to GeometryCollection, empty geometries,
  RelateNG real dimensions) with hand-written WKT and typed-JSON readers and writers, a
  rational side-car format and shortest round-trip double output.
- An arrangement of both operands as a DCEL with face labelling by ring orientation and
  parity, within a size and time budget.
- DE-9IM relate by two independent routes, from the arrangement and from witness points
  located directly in the inputs, required to agree; named predicates dispatched on
  dimension as in JTS/GEOS RelateNG, with a convention table for empty geometries.
- Overlay (intersection, union, difference, symmetric difference) with OverlayNG's
  non-strict semantics and a regularized areal variant, exact rational output in canonical
  order, and an independent certificate that re-nodes A, B and the result.
- Validity by the GEOS IsValidOp rules, reporting every defect with its exact location.
- Measures: exact areas and squared distances, certified lengths and centroids, exact
  convex hulls.
- Rational backends gmpy2 (default) and `fractions` (independent cross-check).

### Corpus and expected answers (CC0)

- Case format v2 with typed operands, exact tags (degeneracy, coordinate range, sizes,
  types, flags) and provenance; JSON Schemas for every record in `schemas/`.
- 17 families: the ten polygon families of the original bug hunt (near-collinear edges,
  vertices on edges, shared edges, tiny transformations, slivers and spikes, hole contacts,
  touching multipolygon parts, tilings, integer grids, scaled cases) and seven new ones for
  lines, the Mod-2 boundary rule, points, line/polygon pairs, GeometryCollections, empty
  geometries and zero-length lines.
- Tiers: `core` (3400 cases, a stratified 200 per family), `curated` (the minimal cases of
  every triaged finding and documented lead) and `full` (17000 cases, not in git, to be published as a
  release asset), with a manifest of checksums.
- Exact expected answers for the core and curated tiers, each checked by the two relate
  routes, the overlay certificate and relate/overlay consistency checks before it is
  written, and golden tests that refuse a changed answer without an engine version bump.

### Harness

- Adapter contract v2 (typed JSON in, relate, predicates, validity and overlay geometry
  out, written in shortest round-trip form), with per-operation isolation of crashes,
  hangs and memory failures, and a parse-echo canary.
- Adapter manifests stating what each library promises: supported, derived and
  unsupported fields, precision model and overlay displacement budget, coordinate range,
  non-default options, build recipe.
- Adapters for 16 library targets: GEOS (through Shapely, git main and the latest release),
  JTS (master and the latest release), Boost.Geometry (1.83, develop and the latest
  release), Clipper2, CGAL with an exact kernel (an external control), georust `geo`, Turf,
  polygon-clipping, polyclip-ts, martinez and JSTS; plus two harness controls, the engine
  itself and a mutant with planted faults.
- `geotruth run`: runs a target over a tier with timeouts, a watchdog, a wall budget,
  schema validation of every result and provenance records.
- `geotruth score`: grades relate and predicates exactly, validity on the boolean, and
  overlay output in six tiers against the library's own documented budget, with
  convention, unsupported and derived fields handled so that no library is charged twice
  or for what it does not promise.
- The triage registry (`findings/registry.toml`) with the findings triaged so far, each with
  minimal cases, exact answers, standalone reproductions and status.

### Tools

- `geotruth relate`, `overlay` and `valid`: the exact answer for any WKT or JSON input,
  with `--dual`, `--certify` and `--explain`.
- `geotruth minimize`: delta debugging of a failing case against a library.
- `geotruth export`: cases with exact answers as JTS/GEOS XML, Boost.Geometry, Clipper2,
  georust `geo` and pytest tests; the XML can be run with the JTS TestRunner and GEOS
  `xmltester` directly.
- `geotruth corpus` and `geotruth expect`: build, list, summarise and verify the tiers and
  their answers.
- `geotruth site`: a static results site (library × capability matrix, failure clusters
  with zoomed exact figures, findings, methodology), with no trackers and no external
  requests, and a preview mode for maintainers.

### Project

- Continuous integration: ruff and actionlint, unit tests on Python 3.10 to 3.13, the engine
  without gmpy2, a cross-check against GEOS through Shapely, and a package build that is
  installed and run in a clean environment. A nightly workflow that builds every library
  from upstream, scores it and publishes the site is included but disabled until the
  triage registry is complete.
- Documentation: quickstart, adapters, scoring, corpus, exports, FAQ, contributing guide,
  security policy, code of conduct and citation metadata.
- Licences: code MIT; corpus and expected answers CC0 1.0.

[0.1.0]: https://github.com/abafaboy/geotruth
