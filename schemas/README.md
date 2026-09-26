# geotruth schemas (v2)

JSON Schemas (draft 2020-12) for every record geotruth reads or writes. They are frozen:
a change goes through the Phase 0 owner and bumps the version suffix.

| file | record | where it lives |
|---|---|---|
| `geometry.v2.schema.json` | shared definitions: typed geometries with double ordinates (`#/$defs/Geometry`) or exact rational ordinates (`#/$defs/ExactGeometry`), `Rational`, `Position` | referenced by the others |
| `case.v2.schema.json` | one corpus case: `{id, family, tags, provenance, ops?, a, b}` | `corpus/cases/*.jsonl` |
| `expected.v2.schema.json` | the exact answer for a case: status, relate, predicates, validity with reasons, overlay (rational side-car + display WKT, non-strict and areal variants), measures, engine version | `expected-vY/*.jsonl` |
| `result.v2.schema.json` | what an adapter reports for a case: relate, predicates (incl. `crosses`), validity, overlay output as round-trip doubles, the parse-echo canary, per-field errors | `results/<lib>/*.jsonl` |
| `run.v2.schema.json` | provenance of one adapter run (library commit, adapter hash, compiler, options, engine/corpus versions, runner image) | `results/<lib>/run.json` |
| `score.v2.schema.json` | the grade of one (case, library, capability), with overlay tiers | scorer output |
| `adapter.v2.schema.json` | an adapter manifest (`manifest_version = 1`, documented in `adapters/README.md`): one `[adapter]` table and one `[[target]]` per library build, each with supported/derived/unsupported fields, precision model and displacement budget δ, coordinate range, options, version command | `adapters/<dir>/adapter.toml` |

Conventions shared by all formats:

- Double ordinates are JSON numbers read with `float()` semantics (`9007199254740993` is
  the double 2^53) and written in shortest round-trip form.
- Exact ordinates and measures are strings `"n"` or `"n/d"` in lowest terms.
- In results, a field is `null` when the library does not provide it, `"unsupported"`
  when the input is outside the library's contract, and `null` plus an `errors` entry
  when it failed.
- The engine may abstain (`engine_skipped`, `engine_error`); that is never counted
  against a library.

`examples/` holds valid and invalid instances of each schema (the invalid ones say why);
the unit tests check both. `examples/case.v2.valid.json` starts with the parse-echo
canary case.

Validate from Python (needs `jsonschema`, in the `dev` extra):

```python
from geotruth import schemas
schemas.validate("result", record)   # raises jsonschema.ValidationError
```
