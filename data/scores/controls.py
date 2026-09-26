"""Check the three controls of the scoreboard and write ``data/scores/controls.json``.

Usage (from the repository root, after ``geotruth run`` and ``geotruth score`` of the
targets ``engine-control``, ``mutant`` and ``cgal``)::

    python3 data/scores/controls.py --results results [--run-cgal] [--out data/scores/controls.json]

``--results`` is laid out as for ``summarize.py``: ``<tier>/<target>/<tier>.jsonl`` (the
library's answers), ``<tier>.score.jsonl`` and ``<tier>.stats.json``. For every tier found:

- **engine-control** (the exact engine behind the adapter contract) must have no headline
  failure and no record graded anything but ``correct`` (DESIGN.md §7).
- **mutant** (the same engine with faults planted on purpose): the fields it changed are
  found by comparing its answers with the control's, case by case, and every changed
  (case, capability) must be flagged ``wrong``, or ``convention`` where the flipped value is
  the other empty-geometry convention; no other record may be graded differently from the
  control's.
- **cgal** (CGAL with an exact kernel, the external exact control, DESIGN.md §0.2): its
  exact side-car (``adapters/cgal/run.sh --exact``, one line per case with every overlay
  result in exact rationals) must, for every overlay, have the exact area of the committed
  expected answer (``corpus/expected/<tier>.jsonl``, the regularized areal variant) and the
  same point set (symmetric-difference area 0 and Hausdorff distance 0, both computed
  exactly), and every exact result must be OGC-valid (``geotruth.validity``). Its rounded
  output is also checked to be the output that was scored. With ``--run-cgal`` the side-car
  ``<tier>/cgal/<tier>.exact.jsonl`` is (re)computed from the tier's case files; without it
  an existing side-car is used, and a tier without one is reported as not checked.

The output has no time stamp, so the same inputs give the same bytes. Exit status 1 when a
control fails.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from geotruth import validity  # noqa: E402
from geotruth.harness import metrics  # noqa: E402
from geotruth.harness.runner import load_cases  # noqa: E402
from geotruth.io import geometry_from_json  # noqa: E402
from geotruth.numbers import json_loads  # noqa: E402

FORMAT = "geotruth-controls/1"
TIER_ORDER = ("core", "curated", "full")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json_loads(line) for line in fh if line.strip()]


def _by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in records}


def _scores(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["id"], r["capability"]): r for r in _jsonl(path)}


def engine_control(tdir: Path, tier: str) -> dict[str, Any]:
    scores = _scores(tdir / f"{tier}.score.jsonl")
    verdicts = Counter(r["verdict"] for r in scores.values())
    not_correct = sum(n for v, n in verdicts.items() if v != "correct")
    return {
        "records": len(scores),
        "verdicts": dict(sorted(verdicts.items())),
        "ok": not_correct == 0,
    }


def mutant(ctl_dir: Path, mut_dir: Path, tier: str) -> dict[str, Any]:
    ctl = _by_id(_jsonl(ctl_dir / f"{tier}.jsonl"))
    mut = _by_id(_jsonl(mut_dir / f"{tier}.jsonl"))
    if ctl.keys() != mut.keys():
        return {"ok": False, "problem": "the two runs answered different cases"}
    mutated: set[tuple[str, str]] = set()
    fields: Counter = Counter()
    for cid, c in ctl.items():
        m = mut[cid]
        for k in sorted((set(c) | set(m)) - {"lib", "elapsed_ms"}):
            if k in ("predicates", "overlay"):
                cv, mv = c.get(k) or {}, m.get(k) or {}
                for sub in sorted(set(cv) | set(mv)):
                    if cv.get(sub) != mv.get(sub):
                        mutated.add((cid, "predicates" if k == "predicates" else f"overlay.{sub}"))
                        fields[f"{k}.{sub}"] += 1
            elif c.get(k) != m.get(k):
                cap = "validity" if k in ("valid_a", "valid_b") else k
                mutated.add((cid, cap))
                fields[k] += 1
    sm = _scores(mut_dir / f"{tier}.score.jsonl")
    sc = _scores(ctl_dir / f"{tier}.score.jsonl")
    flagged = Counter(sm[k]["verdict"] for k in mutated if k in sm)
    caught = ("wrong", "convention")
    missed = sorted(k for k in mutated if sm.get(k, {}).get("verdict") not in caught)
    unexpected = sorted(
        k
        for k, r in sm.items()
        if k not in mutated and r["verdict"] != sc.get(k, {}).get("verdict")
    )
    return {
        "cases": len(ctl),
        "mutated_fields": dict(sorted(fields.items())),
        "mutated_records": len(mutated),
        "flagged": dict(sorted(flagged.items())),
        "missed": len(missed),
        "missed_examples": [list(k) for k in missed[:5]],
        "other_records_changed": len(unexpected),
        "other_examples": [list(k) for k in unexpected[:5]],
        "ok": bool(mutated) and not missed and not unexpected,
    }


def _strip(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k != "elapsed_ms"}


def run_cgal_sidecar(tdir: Path, tier: str) -> Path:
    """Run the CGAL adapter with ``--exact`` over the tier's cases (the case files the
    runner recorded in stats.json), and check its v2 output is the one that was scored."""
    stats = json.loads((tdir / f"{tier}.stats.json").read_text(encoding="utf-8"))
    files = [Path(f) for f in stats["case_files"]]
    side = tdir / f"{tier}.exact.jsonl"
    cases = tdir / f"{tier}.exact-cases.jsonl"
    with open(cases, "w", encoding="utf-8") as fh:
        for _, line in load_cases(files):
            fh.write(line + "\n")
    run = subprocess.run(
        [str(ROOT / "adapters" / "cgal" / "run.sh"), "--exact", str(side), str(cases)],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
    )
    cases.unlink()
    direct = [_strip(json_loads(line)) for line in run.stdout.splitlines() if line.strip()]
    scored = [_strip(r) for r in _jsonl(tdir / f"{tier}.jsonl")]
    if direct != scored:
        raise SystemExit(f"{tdir}: the side-car run's answers differ from the scored run's")
    return side


def cgal(tdir: Path, tier: str, expected: Path) -> dict[str, Any]:
    side = tdir / f"{tier}.exact.jsonl"
    if not side.is_file():
        return {"checked": False, "ok": None}
    exp = _by_id(_jsonl(expected))
    st: Counter = Counter()
    bad: list[list[str]] = []
    for s in _jsonl(side):
        e = exp.get(s["id"])
        if e is None or e.get("status") != "ok":
            st["no_expected_answer"] += 1
            continue
        for op, got in sorted((s.get("overlay") or {}).items()):
            want = e["overlay"][op]["areal"]
            g = geometry_from_json(got["exact"], exact=True)
            w = geometry_from_json(want["exact"], exact=True)
            sg, sw = metrics.shape_of(g), metrics.shape_of(w)
            sd = metrics.even_odd_area(sg.rings() + sw.rings())
            h2 = metrics.hausdorff2(sg, sw)[0]
            area_ok = str(got["area"]) == str(want["area"])
            same = sd == 0 and h2 is not None and h2 == 0
            valid = validity.validate(g).valid
            st["overlays"] += 1
            st["area_exact"] += area_ok
            st["same_point_set"] += same
            st["ogc_valid"] += valid
            if not (area_ok and same and valid):
                bad.append([s["id"], op])
    n = st["overlays"]
    return {
        "checked": True,
        "sidecar": side.name,
        **{k: st[k] for k in ("overlays", "area_exact", "same_point_set", "ogc_valid")},
        "no_expected_answer": st["no_expected_answer"],
        "failures": bad[:10],
        "ok": n > 0 and st["area_exact"] == st["same_point_set"] == st["ogc_valid"] == n,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "scores" / "controls.json")
    ap.add_argument("--run-cgal", action="store_true", help="(re)compute the CGAL side-car")
    args = ap.parse_args(argv)

    tiers = sorted(
        (d.name for d in args.results.iterdir() if d.is_dir() and not d.name.startswith("_")),
        key=lambda t: (*TIER_ORDER, t).index(t),
    )
    out: dict[str, Any] = {"format": FORMAT, "tiers": {}}
    ok = True
    for tier in tiers:
        base = args.results / tier
        ctl, mut, cg = base / "engine-control", base / "mutant", base / "cgal"
        entry: dict[str, Any] = {}
        if (ctl / f"{tier}.score.jsonl").is_file():
            entry["engine-control"] = engine_control(ctl, tier)
            if (mut / f"{tier}.score.jsonl").is_file():
                entry["mutant"] = mutant(ctl, mut, tier)
        if (cg / f"{tier}.score.jsonl").is_file():
            if args.run_cgal:
                run_cgal_sidecar(cg, tier)
            entry["cgal"] = cgal(cg, tier, ROOT / "corpus" / "expected" / f"{tier}.jsonl")
        if entry:
            out["tiers"][tier] = entry
            ok = ok and all(v.get("ok") is not False for v in entry.values())
    out["ok"] = ok
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for tier, entry in out["tiers"].items():
        print(tier, {k: v.get("ok") for k, v in entry.items()})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
