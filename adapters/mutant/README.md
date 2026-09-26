# mutant: the engine control with deliberate faults

The mutant of DESIGN.md §7: the [engine control](../engine_control/README.md) with faults
planted on purpose. The scorer **must catch every one**; a mutation that grades correct is
a blind spot in the scorer. `lib` is `geotruth-mutant@<engine version>`, currently
`geotruth-mutant@0.1.0`.

```sh
python3 -m geotruth run --lib mutant --tier core
python3 -m geotruth score --lib mutant --tier core   # many headline failures, by design
```

| file | what |
|---|---|
| `mutant_adapter.py` | entry point: `pyadapter.main(MutantLibrary())` |
| `run.sh` | run wrapper (as the control's; `MUTANT_ADAPTER_TIMEOUT` instead of `CONTROL_ADAPTER_TIMEOUT`) |
| `adapter.toml` | manifest: the control's fields and δ, and the mutations listed in `options` |

The implementation is `MutantLibrary` in
[`src/geotruth/harness/control.py`](../../src/geotruth/harness/control.py). It answers
exactly as the control does, then rewrites the record before it is written (a
post-processing hook of the adapter runtime, so the exact answers themselves are
untouched). The faults are applied in input order, counted over the whole run:

- **predicates**: every 17th reported named predicate (the 1st, 18th, 35th, ..., counted
  in the contract's field order over every case) is negated;
- **overlay**: every 17th non-empty polygonal overlay output (the 1st, 18th, ...) has the
  second vertex of its first ring moved perpendicular to the chord between its two
  neighbours (so the point set changes even where that vertex is collinear), by the larger
  of 1/256 of the ring's extent and 2^-20 of its largest ordinate: beyond every library's
  δ (the loosest is 1e-8 of the largest ordinate), so it grades `gross` or `topological`.

Relate, validity and the echo canary are not mutated; they are the control's, so those
records must stay correct. `MutantLibrary.mutations` lists every `(case id, field)` it
changed, which the unit test `tests/harness/test_score.py::test_mutant_is_caught` checks
against the scorer's records one by one.

## Results

Core tier (3400 cases), 2026-09-26: 1883 predicates negated and 513 overlays perturbed,
2396 mutated (case, capability) records in all. Every one is flagged: 2368 `wrong` and 28
`convention` (negations of predicates the expected answer decides by the empty-geometry
convention table, which the scorer reports separately by design). No record the mutant
left alone is flagged, and relate, validity and echo stay 100% correct.
