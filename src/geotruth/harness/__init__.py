"""The v2 harness (DESIGN §4): manifests, the runner, the scorer and the exact metrics.

Module map:

- :mod:`geotruth.harness.manifest` -- adapter manifests (``adapters/*/adapter.toml``):
  discovery, targets, derived fields, the displacement budget δ_lib of a case.
- :mod:`geotruth.harness.engine` -- the exact answers, behind an import shim: the engine's
  documented API (DESIGN §2: ``relate(a, b)``, ``overlay(a, b, op, variant)``) as soon as
  it exists, the audited references in ``tests/reference`` (and the witness relate) until
  then. Builds ``expected.v2`` records.
- :mod:`geotruth.harness.fallback_overlay` -- the exact areal overlay of valid polygonal
  operands from the boundary pieces of ``tests/reference/indep.py`` (the shim's fallback).
- :mod:`geotruth.harness.metrics` -- exact grading metrics of a library's overlay output:
  even-odd areas, the symmetric-difference area, the exact squared Hausdorff distance, the
  tube area bound.
- :mod:`geotruth.harness.pyadapter` -- the contract-v2 runtime of the Python adapters
  (Shapely, the engine control and the mutant): reading cases, per-operation process
  isolation with a timeout and a memory cap, writing result lines.
- :mod:`geotruth.harness.control` -- the ``engine_control`` and ``mutant`` adapters.
- :mod:`geotruth.harness.runner` -- ``geotruth run``: runs one adapter target over a tier.
- :mod:`geotruth.harness.score` -- ``geotruth score``: grades results against expected
  answers (DESIGN §4.3) into ``score.v2`` records and a summary.
"""
