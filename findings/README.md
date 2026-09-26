# Findings

Each candidate bug found by the harness gets a directory here with the evidence for it:
the minimal cases (`cases.jsonl`), the exact answers from both references (`oracle.jsonl`,
`indep.jsonl`), the library's answers, a standalone program that uses only the library's
public API (`repro.*`, with `run.sh`), its output on the latest development code and the
latest release, and the triage write-up (`ISSUE.md`).

[`registry.toml`](registry.toml) is the triage registry (DESIGN.md §5.4): one entry per
cluster, with the library, a signature, the status and links. No automated disagreement is
presented as a confirmed bug; the status says how far triage has got:

| status | meaning |
|---|---|
| `unreviewed` | found by the harness, not yet triaged by a person |
| `confirmed` | a wrong answer within the library's documented contract |
| `by-design` | documented or intended behaviour, not reported as a bug |
| `reported` | confirmed and reported upstream |
| `fixed` | fixed upstream |

| finding | library | status |
|---|---|---|
| [`clipper2-thin-triangle-dropped`](clipper2-thin-triangle-dropped/ISSUE.md) | Clipper2 | by-design |
