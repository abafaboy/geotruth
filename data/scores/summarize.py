"""Write the compact score summaries of ``data/scores/`` from the files of ``geotruth score``.

Usage (from the repository root)::

    python3 data/scores/summarize.py --results results [--out data/scores]

``--results`` holds one directory per tier (``core/``, ``curated/``), each laid out as
``geotruth run --out results/<tier>`` and ``geotruth score --results-dir results/<tier>``
leave it: ``<tier>/<target>/<tier>.score.jsonl`` (score.v2 records), ``<tier>.stats.json``
(runner statistics), ``<tier>.summary.json`` (the scorer's own summary) and ``run.json``
(provenance). For every target it writes ``<target>.json``, and ``summary.json`` for all of
them; ``data/README.md`` describes the fields. Everything is counted from the score records
and cross-checked against the scorer's summary (the headline must agree). The output holds
no time stamp of its own, so the same inputs give the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from geotruth.harness.manifest import find_target  # noqa: E402
from geotruth.harness.metrics import Surd  # noqa: E402
from geotruth.numbers import parse_rational  # noqa: E402

FORMAT = "geotruth-score-summary/1"
CAPABILITIES = (
    "echo",
    "relate",
    "predicates",
    "validity",
    "overlay.intersection",
    "overlay.union",
    "overlay.difference",
    "overlay.symdifference",
)
VERDICTS = (
    "correct",
    "wrong",
    "error",
    "convention",
    "unsupported",
    "not_reported",
    "engine_skipped",
    "engine_error",
)
GRADED = ("correct", "wrong", "error", "convention")
OVERLAY_TIERS = ("exact", "rounding", "budget", "gross", "topological", "exception")
TIER_ORDER = ("core", "curated", "full")
#: the largest failure clusters kept per target and tier (the rest are counted)
MAX_CLUSTERS = 40


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _error_kind(rec: dict[str, Any]) -> list[str]:
    """The error kinds of an ``error`` record (timeout, crash, memory, exception), each once
    (a predicates record lists every failing predicate)."""
    kind = (rec.get("metrics") or {}).get("error_kind")
    if kind:
        return [str(kind)]
    got = rec.get("got")
    texts = list(got.values()) if isinstance(got, dict) else [got]
    out = []
    for t in texts:
        head = str(t or "").split(":", 1)[0].strip()
        out.append(head if head in ("timeout", "crash", "memory", "exception") else "exception")
    return sorted(set(out)) or ["exception"]


def _topological_kind(met: dict[str, Any]) -> list[str]:
    """What made an overlay output ``topological``: ``invalid_output`` (the output is not
    OGC-valid), with ``..._exact_point_set`` when its point set is nevertheless the exact one
    (symmetric-difference area 0 and Hausdorff distance 0) and ``..._within_rounding`` when
    its Hausdorff distance to the exact result is at most the rounding floor
    ``delta_rounding`` (exact point sets included; the distance is compared exactly with the
    double ``delta_rounding``); or ``missing_or_extra_parts`` (valid output, a component or
    hole missing or extra)."""
    if met.get("output_valid") is not False:
        return ["missing_or_extra_parts"]
    out = ["invalid_output"]
    h2: Any = None
    if "hausdorff2" in met:
        h2 = Surd(parse_rational(str(met["hausdorff2"])))
    elif "hausdorff2_surd" in met:
        s = met["hausdorff2_surd"]
        h2 = Surd(*(parse_rational(str(s[k])) for k in ("a", "b", "d")))
    if h2 is not None and h2 == 0 and str(met.get("symdiff_area")) == "0":
        # the scorer stops here, without delta_rounding: an exact point set is within it
        return [*out, "invalid_output_exact_point_set", "invalid_output_within_rounding"]
    dr = met.get("delta_rounding")
    if h2 is not None and isinstance(dr, float) and h2 <= Fraction(dr) ** 2:
        out.append("invalid_output_within_rounding")
    return out


def _rate(failures: int, graded: int) -> float | None:
    return round(failures / graded, 6) if graded else None


def summarize_tier(tier: str, tdir: Path, target_id: str) -> dict[str, Any]:
    """The summary of one target on one tier."""
    score_path = tdir / f"{tier}.score.jsonl"
    verdicts: dict[str, Counter] = defaultdict(Counter)
    tiers: dict[str, Counter] = defaultdict(Counter)
    derived: Counter = Counter()
    error_kinds: dict[str, Counter] = defaultdict(Counter)
    topo: dict[str, Counter] = defaultdict(Counter)
    invalid_reasons: dict[str, Counter] = defaultdict(Counter)
    fam: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    rng: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    clusters: Counter = Counter()
    by_case: dict[str, dict[str, str]] = defaultdict(dict)
    headline = 0
    ids = set()
    with open(score_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            cap, v = rec["capability"], rec["verdict"]
            ids.add(rec["id"])
            verdicts[cap][v] += 1
            if "tier" in rec:
                tiers[cap][rec["tier"]] += 1
            is_derived = bool(rec.get("derived"))
            if is_derived:
                derived[cap] += 1
            counted = v in ("wrong", "error") and not is_derived
            family = rec.get("family") or "-"
            crange = str((rec.get("tags") or {}).get("range") or "-")
            if v in GRADED:
                fam[family][cap]["graded"] += 1
                rng[cap][crange]["graded"] += 1
            if counted:
                headline += 1
                fam[family][cap]["failures"] += 1
                rng[cap][crange]["failures"] += 1
                if rec.get("cluster"):
                    clusters[rec["cluster"]] += 1
            if v == "error":
                for k in _error_kind(rec):
                    error_kinds[cap][k] += 1
            if rec.get("tier") == "topological" and counted:
                met = rec.get("metrics") or {}
                for k in _topological_kind(met):
                    topo[cap][k] += 1
                if met.get("output_reason"):
                    invalid_reasons[cap][str(met["output_reason"])] += 1
            if tier == "curated":
                by_case[rec["id"]][cap] = v + (" (derived)" if is_derived else "")
    caps: dict[str, Any] = {}
    for cap in CAPABILITIES:
        v = verdicts.get(cap)
        if not v:
            continue
        graded = sum(v.get(k, 0) for k in GRADED)
        failures = v.get("wrong", 0) + v.get("error", 0) - derived.get(cap, 0)
        entry: dict[str, Any] = {k: v.get(k, 0) for k in VERDICTS}
        entry.update(
            {
                "derived": derived.get(cap, 0),
                "graded": graded,
                "failures": failures,
                "failure_rate": _rate(failures, graded),
            }
        )
        entry["by_range"] = {
            r: {"graded": n["graded"], "failures": n["failures"]}
            for r, n in sorted(rng[cap].items())
        }
        if error_kinds.get(cap):
            entry["error_kinds"] = dict(sorted(error_kinds[cap].items()))
        if cap in tiers:
            entry["overlay_tiers"] = {t: tiers[cap].get(t, 0) for t in OVERLAY_TIERS}
            entry["topological"] = {
                k: topo[cap].get(k, 0)
                for k in (
                    "invalid_output",
                    "invalid_output_exact_point_set",
                    "invalid_output_within_rounding",
                    "missing_or_extra_parts",
                )
            }
            if invalid_reasons.get(cap):
                entry["invalid_output_reasons"] = dict(invalid_reasons[cap].most_common())
        caps[cap] = entry
    unknown = set(verdicts) - set(CAPABILITIES)
    if unknown:
        raise SystemExit(f"{score_path}: unknown capabilities {sorted(unknown)}")
    scorer = _read_json(tdir / f"{tier}.summary.json") or {}
    if scorer and scorer.get("headline_failures") != headline:
        raise SystemExit(
            f"{score_path}: {headline} headline failures counted here, "
            f"{scorer.get('headline_failures')} in the scorer's summary"
        )
    if scorer.get("scorer_failures"):
        raise SystemExit(f"{score_path}: {scorer['scorer_failures']} scorer failures")
    stats = _read_json(tdir / f"{tier}.stats.json") or {}
    run = _read_json(tdir / "run.json") or {}
    if run.get("tier") not in (None, tier):
        raise SystemExit(f"{tdir / 'run.json'} is the provenance of tier {run.get('tier')}")
    families = {
        f: {
            c: {"graded": n["graded"], "failures": n["failures"]}
            for c, n in sorted(caps_.items())
            if n["failures"]
        }
        for f, caps_ in sorted(fam.items())
    }
    top = clusters.most_common()
    out: dict[str, Any] = {
        "date": (run.get("finished") or "")[:10] or None,
        "run": {
            "started": run.get("started"),
            "finished": run.get("finished"),
            "elapsed_s": stats.get("elapsed_s"),
            "host": run.get("host"),
            "runner_image": run.get("runner_image"),
            "op_timeout_s": stats.get("op_timeout_s"),
            "budget_s": stats.get("budget_s"),
            "lib_reported": run.get("lib"),
            "version_command": (run.get("options") or {}).get("version_command"),
            "adapter": run.get("adapter"),
            "compiler": run.get("compiler"),
        },
        "versions": {k: v for k, v in (scorer.get("versions") or {}).items() if k != "lib"},
        "exact_backends": scorer.get("exact_backends"),
        "cases": {
            "total": stats.get("cases_total"),
            "run": stats.get("cases_run"),
            "scored": len(ids),
        },
        "runner": {
            k: stats.get(k)
            for k in (
                "watchdog_timeouts",
                "early_exits",
                "adapter_restarts",
                "invalid_lines",
                "noise_lines",
                "id_mismatches",
                "budget_exhausted",
            )
        },
        "headline_failures": headline,
        "capabilities": caps,
        "families": {f: c for f, c in families.items() if c},
        "clusters": dict(top[:MAX_CLUSTERS]),
        "clusters_total": len(top),
        "clusters_omitted_records": sum(n for _, n in top[MAX_CLUSTERS:]),
    }
    if tier == "curated":
        out["case_verdicts"] = {cid: dict(sorted(v.items())) for cid, v in sorted(by_case.items())}
    return out


def target_meta(target_id: str) -> dict[str, Any]:
    t = find_target(target_id)
    tab = t.table
    prec = tab.get("precision", {})
    return {
        "target": target_id,
        "library": tab.get("library"),
        "lib": tab.get("lib"),
        "version": str(tab.get("version")) if tab.get("version") is not None else None,
        "commit": tab.get("commit"),
        "upstream": tab.get("upstream"),
        "adapter": f"adapters/{t.dir}",
        "toolchain": tab.get("toolchain"),
        "options": list(tab.get("options", [])),
        "precision": {
            "delta": prec.get("delta"),
            "grid": prec.get("grid"),
            "tolerance_predicates": bool(prec.get("tolerance_predicates", False)),
        },
    }


def _git(*args: str) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() if out.returncode == 0 else None


def source_digest() -> str:
    """sha256 over ``src/geotruth/**/*.py`` (path and bytes), the engine and harness code."""
    h = hashlib.sha256()
    for p in sorted((ROOT / "src" / "geotruth").rglob("*.py")):
        h.update(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "scores")
    ap.add_argument("--targets", nargs="*", default=None, help="only these targets")
    args = ap.parse_args(argv)

    found: dict[str, dict[str, Path]] = defaultdict(dict)
    for tdir in sorted(args.results.iterdir()):
        if not tdir.is_dir() or tdir.name.startswith("_"):
            continue
        tier = tdir.name
        for sdir in sorted(tdir.iterdir()):
            if (sdir / f"{tier}.score.jsonl").is_file():
                found[sdir.name][tier] = sdir
    if args.targets:
        found = {k: v for k, v in found.items() if k in args.targets}
    if not found:
        print(f"no score files under {args.results}/<tier>/<target>/", file=sys.stderr)
        return 2

    exp_man = _read_json(ROOT / "corpus" / "expected" / "MANIFEST.json") or {}
    corpus_man = _read_json(ROOT / "corpus" / "MANIFEST.json") or {}
    args.out.mkdir(parents=True, exist_ok=True)
    libraries: dict[str, Any] = {}
    tiers_seen: set[str] = set()
    started: list[str] = []
    finished: list[str] = []
    for target_id in sorted(found):
        meta = target_meta(target_id)
        per_tier = {}
        for tier in sorted(found[target_id], key=lambda t: (*TIER_ORDER, t).index(t)):
            per_tier[tier] = summarize_tier(tier, found[target_id][tier], target_id)
            tiers_seen.add(tier)
        doc = {"format": FORMAT, **meta, "tiers": per_tier}
        path = args.out / f"{target_id}.json"
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        libraries[target_id] = {
            k: meta[k] for k in ("library", "lib", "version", "commit", "upstream")
        } | {
            "tiers": {
                tier: {
                    "date": s["date"],
                    "cases": s["cases"],
                    "headline_failures": s["headline_failures"],
                    "timeouts": sum(
                        c.get("error_kinds", {}).get("timeout", 0)
                        for c in s["capabilities"].values()
                    ),
                    "crashes": sum(
                        c.get("error_kinds", {}).get("crash", 0) for c in s["capabilities"].values()
                    ),
                    "adapter_git_sha": (s["run"].get("adapter") or {}).get("git_sha"),
                    "capabilities": {
                        cap: {
                            k: c[k]
                            for k in (
                                "graded",
                                "failures",
                                "failure_rate",
                                *VERDICTS,
                                "derived",
                                "by_range",
                                "topological",
                            )
                            if k in c
                        }
                        for cap, c in s["capabilities"].items()
                    },
                }
                for tier, s in per_tier.items()
            }
        }
        for s in per_tier.values():
            if s["run"].get("started"):
                started.append(s["run"]["started"])
            if s["run"].get("finished"):
                finished.append(s["run"]["finished"])
    tier_info = {}
    for tier in sorted(tiers_seen, key=lambda t: (*TIER_ORDER, t).index(t)):
        ef = (exp_man.get("files") or {}).get(f"{tier}.jsonl") or {}
        ct = (corpus_man.get("tiers") or {}).get(tier) or {}
        tier_info[tier] = {
            "cases": ct.get("cases"),
            "corpus_version": corpus_man.get("corpus_version"),
            "expected": f"corpus/expected/{tier}.jsonl",
            "expected_version": ef.get("expected_version"),
            "expected_sha256": ef.get("sha256"),
            "expected_status": ef.get("status"),
            "engine_version": ef.get("engine_version"),
        }
    head = _git("rev-parse", "HEAD")
    summary = {
        "format": FORMAT,
        "note": (
            "Counts from `geotruth score` against the committed exact answers. The corpus is "
            "deliberately adversarial (near-degenerate input), so these rates are not "
            "real-world failure rates, and there is no single ranking: compare per "
            "capability. Unreviewed failure clusters are not confirmed bugs "
            "(findings/registry.toml)."
        ),
        # the checkout this summary was written from (the runs' own provenance is in each
        # <target>.json: adapter git hash, "+dirty" when the adapter had local changes)
        "geotruth": {
            "git_head": head,
            "git_worktree_clean": not _git("status", "--porcelain"),
            "src_sha256": source_digest(),
        },
        "runs": {
            "first_started": min(started) if started else None,
            "last_finished": max(finished) if finished else None,
        },
        "tiers": tier_info,
        "libraries": libraries,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    total = sum(p.stat().st_size for p in args.out.glob("*.json"))
    print(f"{len(libraries)} targets, tiers {', '.join(tier_info)}: {total} bytes in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
