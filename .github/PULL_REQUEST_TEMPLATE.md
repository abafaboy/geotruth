## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `make lint` and `make unit` pass (`make crosscheck-ci` too for engine or harness changes).
- [ ] New behaviour has tests; a fixed bug has a regression test.
- [ ] If any expected answer could change, `geotruth.ENGINE_VERSION` is bumped and
      `corpus/expected/` is regenerated (`geotruth expect`); the golden tests say so otherwise.
- [ ] No published case file is edited (cases are immutable; add a new file or tier).
- [ ] Docs and `CHANGELOG.md` are updated where users would notice the change.
- [ ] Nothing here discloses an unreported crash in another library (see `SECURITY.md`).
