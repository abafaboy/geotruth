# Security policy

geotruth is a testing tool. It reads geometry from files and the command line, runs
library adapters in child processes on your own machine, builds libraries from pinned
upstream sources, and generates a static web site. This page covers two different
things: vulnerabilities in geotruth itself, and security-relevant bugs that geotruth finds
in *other* projects.

## Reporting a vulnerability in geotruth

Please do not open a public issue. Report it privately through GitHub's private
vulnerability reporting: on the repository page, open the **Security** tab and choose
**Report a vulnerability**. If that button is not available, open an issue that asks the
maintainer for a private channel, and leave every detail of the problem out of it.

Useful things to include: the geotruth commit (`geotruth version`), the command you ran,
the input that triggers the problem, and what you expected to happen.

Examples of what counts:

- input (WKT, JSON, a case file or an adapter's output) that makes geotruth run code,
  write outside the output directory it was given, or read files it was not asked to read;
- markup or script from case data, adapter output or the triage registry that reaches the
  generated site without being escaped;
- a build or install script that fetches code without pinning or verifying it.

Resource exhaustion on adversarial input is a known limitation rather than a
vulnerability: the exact engine is written in Python, and its per-case budget (`--max-size`,
`--max-seconds`) is the defence. Reports of a way around the budget are still welcome as
ordinary issues.

Only the latest commit on the default branch is supported. There are no releases with
security backports yet.

## Security-relevant bugs that geotruth finds in other libraries

geotruth runs geometry libraries on adversarial input, so it sometimes makes one crash,
hang, or exhaust its memory. Such a bug can matter beyond wrong answers: GEOS, for
example, runs inside database servers and web services that accept geometry from users.

When a run shows a crash, a hang or a memory failure in a library:

1. **Treat it as potentially security-relevant.** Do not post the reproducer publicly, not
   here and not in the library's public tracker, until you have checked how the library
   wants such reports.
2. **Report it through the library's private channel when it has one** (its security
   policy, usually a `SECURITY.md` in its repository, or its security contact). Only if
   the library has no private channel, or its maintainers say a public issue is fine, file
   it publicly.
3. **Give the maintainers time** to respond and fix it before anything about it is
   published, including in this repository's `findings/`, the corpus's curated tier or
   the results site. The finding stays in the triage registry
   ([`findings/registry.toml`](findings/registry.toml)) with status `confirmed` and
   its note says that it has not been reported yet.

If you are not sure whether a bug is security-relevant, report it to the geotruth
maintainer privately first (as above), and we will work out the right channel together.

Wrong answers (a wrong predicate, a wrong overlay) are ordinary bugs. They go through the
triage policy in [CONTRIBUTING.md](CONTRIBUTING.md#triage-and-reporting-to-library-maintainers)
and are reported upstream in public, once triaged.
