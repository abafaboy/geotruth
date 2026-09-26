# tools

Maintainer tools that are not part of the engine or the harness.

| directory | what |
|---|---|
| [`oracle_review/`](oracle_review/) | the adversarial review of the exact oracle: its record ([README](oracle_review/README.md)), the review case generators, the check, mutation and timing scripts, and an adapter around the independent implementation. The audited modules themselves (`oracle.py`, `indep.py`, `validity.py`) are vendored in [`tests/reference/`](../tests/reference/) |

Run the scripts from anywhere; they find the references from their own location, for example
`python tools/oracle_review/check.py CASES.jsonl --jobs 2`.
