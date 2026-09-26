"""Tally a hunt round: disagreements per library and kind, from `compare.py --json` output.

usage: python harness/tally.py OUT_DIR [--json]

OUT_DIR is a directory written by harness/hunt.sh (or any directory laid out the same way).
Every `results-*/compare-<lib>/<family>.jsonl` file below it is read, together with the
`<family>.log` file next to it, whose last line compare.py writes as
`# N disagreements over M cases`. For each library the table gives:

- cases:     cases compared (M summed over the case files);
- records:   disagreement records (N summed; one case can give several records);
- cases_hit: cases with at least one disagreement;
- one column per compare.py kind (predicate, area, validity, error), counting records;
- error_keys: for `error` records, how many there are per key (for example `unsupported`
  when an adapter declines out-of-contract input, `timeout`, or an operation name).
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

KINDS = ("predicate", "area", "validity", "error")
LOG_LINE = re.compile(r"#\s*(\d+) disagreements over (\d+) cases")


@dataclass
class LibTally:
    """Counts for one library over every case file of a round."""

    cases: int = 0
    records: int = 0
    ids: set = field(default_factory=set)
    kinds: Counter = field(default_factory=Counter)
    error_keys: Counter = field(default_factory=Counter)

    @property
    def cases_hit(self):
        return len(self.ids)

    def as_dict(self):
        return {
            "cases": self.cases,
            "records": self.records,
            "cases_hit": self.cases_hit,
            "kinds": {k: self.kinds.get(k, 0) for k in KINDS},
            "error_keys": dict(sorted(self.error_keys.items())),
        }


def read_log(path):
    """(disagreements, cases) from a compare.py log, or None if it has no summary line."""
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        return None
    found = LOG_LINE.findall(text)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def tally(out_dir):
    """Map library name -> LibTally (sorted by name), for every compare-<lib> directory."""
    libs = {}
    pattern = os.path.join(out_dir, "results-*", "compare-*", "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        lib = os.path.basename(os.path.dirname(path))[len("compare-"):]
        t = libs.setdefault(lib, LibTally())
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                t.records += 1
                t.ids.add(rec["id"])
                t.kinds[rec["kind"]] += 1
                if rec["kind"] == "error":
                    t.error_keys[rec["key"]] += 1
        summary = read_log(path[: -len(".jsonl")] + ".log")
        if summary is not None:
            t.cases += summary[1]
    return dict(sorted(libs.items()))


def format_table(libs):
    """A fixed-width text table, one row per library."""
    head = f"{'library':18s} {'cases':>7s} {'records':>8s} {'cases_hit':>9s} " + " ".join(
        f"{k:>9s}" for k in KINDS) + "  error_keys"
    rows = [head]
    for lib, t in libs.items():
        keys = ", ".join(f"{k} {n}" for k, n in sorted(t.error_keys.items()))
        rows.append(f"{lib:18s} {t.cases:7d} {t.records:8d} {t.cases_hit:9d} " + " ".join(
            f"{t.kinds.get(k, 0):9d}" for k in KINDS) + (f"  {keys}" if keys else ""))
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--json", action="store_true", help="print a JSON object instead of a table")
    args = ap.parse_args(argv)
    libs = tally(args.out_dir)
    if not libs:
        print(f"tally.py: no compare-<lib> output under {args.out_dir}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({lib: t.as_dict() for lib, t in libs.items()}, indent=1))
    else:
        print(format_table(libs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
