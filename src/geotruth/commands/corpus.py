"""Build, list and summarise the corpus tiers (DESIGN §3)."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

HELP = "build, list, summarise or verify the corpus tiers (core, curated, full)"

TIERS = ("core", "curated", "full", "seed")


def corpus_dir() -> Path:
    """The repository's corpus/ directory (the generators live there, not in the package)."""
    return Path(__file__).resolve().parents[3] / "corpus"


def tiers_module() -> ModuleType:
    """``corpus/generators/tiers.py`` (imported from the source tree)."""
    gen = corpus_dir() / "generators"
    if not (gen / "tiers.py").is_file():
        raise RuntimeError(f"corpus generators not found in {gen} (a source checkout is needed)")
    if str(gen) not in sys.path:
        sys.path.insert(0, str(gen))
    return importlib.import_module("tiers")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", metavar="ACTION", required=True)
    b = sub.add_parser(
        "build",
        help="generate the full tier, select core, collect curated; write MANIFEST.json",
        description="Generate the corpus tiers. full: N cases per family (not in git); "
        "core: a stratified, deterministic sample per family; curated: findings/ and "
        "corpus/curated/leads.toml. The legacy FORMAT-v1 writer for the old harness is "
        "corpus/generators/run_all.py.",
    )
    b.add_argument("--tier", choices=("all", "core", "curated", "full"), default="all")
    b.add_argument("--n", type=int, default=None, help="cases per family in full (1000)")
    b.add_argument("--seed", type=int, default=None, help="generator seed (1)")
    b.add_argument("--per-family", type=int, default=None, help="core cases per family (200)")
    b.add_argument("--families", default="", help="comma-separated subset of families")
    b.add_argument("--jobs", type=int, default=2, help="families generated in parallel (2)")
    b.add_argument("--corpus", type=Path, default=None, help="corpus directory (repo corpus/)")
    b.add_argument("--quiet", action="store_true")

    ls = sub.add_parser("list", help="list tiers, families and files, or case ids")
    ls.add_argument("--tier", choices=TIERS, default=None)
    ls.add_argument("--family", default=None)
    ls.add_argument("--ids", action="store_true", help="print case ids (one per line)")
    ls.add_argument(
        "--families",
        dest="list_families",
        action="store_true",
        help="print the known generator families",
    )
    ls.add_argument("--corpus", type=Path, default=None)

    st = sub.add_parser("stats", help="case counts per family and tag")
    st.add_argument("--tier", choices=TIERS, default="core")
    st.add_argument("--family", default=None)
    st.add_argument(
        "--by",
        default="degeneracy,range",
        help="tags to tabulate (degeneracy, range, types, flags, variant)",
    )
    st.add_argument("--json", action="store_true")
    st.add_argument("--corpus", type=Path, default=None)

    ve = sub.add_parser("verify", help="check every present tier file against MANIFEST.json")
    ve.add_argument("--corpus", type=Path, default=None)


def _build(args: argparse.Namespace, t: ModuleType, corpus: Path) -> int:
    tiers = {"core", "curated", "full"} if args.tier == "all" else {args.tier}
    old = t.load_manifest(corpus) or {}
    p = old.get("parameters", {})
    n = args.n or p.get("n_per_family", t.DEFAULT_N)
    seed = args.seed if args.seed is not None else p.get("seed", t.DEFAULT_SEED)
    per = args.per_family or p.get("core_per_family", t.CORE_PER_FAMILY)
    fams = [f for f in args.families.split(",") if f] or None
    log = None if args.quiet else (lambda s: print(s, file=sys.stderr))
    m = t.build(
        tiers, n=n, seed=seed, per_family=per, families=fams, jobs=args.jobs, corpus=corpus, log=log
    )
    if not args.quiet:
        for tier, info in m["tiers"].items():
            print(
                f"{tier:8s} {info['cases']:7d} cases in {len(info['files'])} files"
                f"{'' if info['in_git'] else '  (not in git)'}"
            )
    return 0


def _list(args: argparse.Namespace, t: ModuleType, corpus: Path) -> int:
    if args.list_families:
        for name, _, legacy in t.ALL_FAMILIES:
            print(f"{name:28s} {'legacy polygon family' if legacy else 'v2 family'}")
        return 0
    if args.ids:
        for tier in [args.tier] if args.tier else ["curated", "core"]:
            for rec in t.iter_tier(tier, corpus, args.family):
                print(rec["id"])
        return 0
    m = t.load_manifest(corpus)
    if m is None:
        print("no MANIFEST.json; run `geotruth corpus build`", file=sys.stderr)
        return 1
    for tier, info in m["tiers"].items():
        if args.tier and tier != args.tier:
            continue
        where = "git" if info["in_git"] else "release asset"
        print(f"{tier}: {info['cases']} cases, format {info['format']}, {where}")
        for path, e in info["files"].items():
            fam = Path(path).stem
            if args.family and fam != args.family:
                continue
            present = "" if e.get("present", True) and (corpus / path).exists() else "  (absent)"
            print(f"  {path:48s} {e['cases']:6d} {e['sha256'][:12]}{present}")
    return 0


def _stats(args: argparse.Namespace, t: ModuleType, corpus: Path) -> int:
    by = [b for b in args.by.split(",") if b]
    table = t.stats(args.tier, by, corpus, args.family)
    if args.json:
        print(json.dumps(table, indent=1, sort_keys=True))
        return 0
    if not table:
        print(f"no cases in tier {args.tier}", file=sys.stderr)
        return 1
    cols = sorted({k for row in table.values() for k in row if k != "cases"})
    width = max(len(f) for f in table) + 2
    print(f"{'family':{width}s}{'cases':>7s}  " + "  ".join(cols))
    total: dict[str, int] = {}
    for fam in sorted(table):
        row = table[fam]
        print(
            f"{fam:{width}s}{row['cases']:7d}  "
            + "  ".join(f"{row.get(c, 0):{len(c)}d}" for c in cols)
        )
        for k, v in row.items():
            total[k] = total.get(k, 0) + v
    print(
        f"{'total':{width}s}{total['cases']:7d}  "
        + "  ".join(f"{total.get(c, 0):{len(c)}d}" for c in cols)
    )
    return 0


def _verify(args: argparse.Namespace, t: ModuleType, corpus: Path) -> int:
    m = t.load_manifest(corpus)
    if m is None:
        print("no MANIFEST.json", file=sys.stderr)
        return 1
    bad = checked = 0
    for info in m["tiers"].values():
        for path, e in info["files"].items():
            p = corpus / path
            if not p.exists():
                if info["in_git"]:
                    print(f"MISSING {path}")
                    bad += 1
                continue
            checked += 1
            if t.sha256_file(p) != e["sha256"] or t.count_lines(p) != e["cases"]:
                print(f"CHANGED {path}")
                bad += 1
    print(f"{checked} files checked, {bad} problems")
    return 1 if bad else 0


def run(args: argparse.Namespace) -> int:
    try:
        t = tiers_module()
    except RuntimeError as exc:
        print(f"geotruth corpus: {exc}", file=sys.stderr)
        return 2
    corpus = getattr(args, "corpus", None) or t.CORPUS
    action = {"build": _build, "list": _list, "stats": _stats, "verify": _verify}[args.action]
    return action(args, t, corpus)
