"""Corpus v2 tiers (DESIGN §3): generate, select, curate, checksum.

usage (normally through the CLI, ``geotruth corpus build|list|stats|verify``)::

    python corpus/generators/tiers.py build [--tier all] [--n 1000] [--seed 1] [--jobs 2]

Tiers
-----
``full``
    every family (the ten legacy polygon families and the v2 families of
    ``families_v2.py``), ``N`` cases each (default 1000, seed 1), in
    ``corpus/cases/full/<family>.jsonl``. Released as assets with the MANIFEST; not in git.
``core``
    a stratified, deterministic 200 per family, drawn from ``full``, in
    ``corpus/cases/core/<family>.jsonl`` (tracked). Strata are (variant class, degeneracy,
    range, geometry types); every stratum gets a case before any gets two (largest strata
    first), the rest is proportional (largest remainder), and within a stratum cases are
    taken in order of sha256(id).
``curated``
    the minimal case of every finding in ``findings/registry.toml`` plus the documented
    leads of ``corpus/curated/leads.toml`` (adapter READMEs), each with its provenance
    and upstream status, in ``corpus/cases/curated.jsonl`` (tracked).

``corpus/MANIFEST.json`` records every tier file with its sha256, byte size and case
count, and the parameters that produced it; ``corpus/SHA256SUMS`` gains the tracked files.

Validity: every operand of a family not named ``invalid-*`` is valid by the exact engine
(``geotruth.validity``). Legacy families additionally pass their own exact checks
(``common.check_valid`` with the engine as the second opinion instead of Shapely, so the
output does not depend on the installed GEOS). Generation is deterministic: each family
has its own random stream seeded with ``"<family>:<seed>"``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent
ROOT = CORPUS.parent
for _p in (str(HERE), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import casev2  # noqa: E402
import common  # noqa: E402
from families import FAMILIES as LEGACY_FAMILIES  # noqa: E402
from families_v2 import FAMILIES_V2  # noqa: E402

CORPUS_VERSION = "2.0.0"
MANIFEST_VERSION = 1
DEFAULT_N = 1000
DEFAULT_SEED = 1
CORE_PER_FAMILY = 200
MAX_COORDS = 300  # both operands together (keeps the exact engine fast)

LEGACY_GENERATOR = "corpus/generators/families.py"
V2_GENERATOR = "corpus/generators/families_v2.py"

#: (name, generator function, legacy?) for every family, in corpus order.
ALL_FAMILIES: list[tuple[str, Any, bool]] = [(n, f, True) for n, f in LEGACY_FAMILIES] + [
    (n, f, False) for n, f in FAMILIES_V2
]
FAMILY_NAMES = [n for n, _, _ in ALL_FAMILIES]


# ============================================================================ validity


def _engine_is_valid():
    try:
        from geotruth.validity import is_valid
    except ImportError:  # pragma: no cover - the engine validity is part of the package
        return None
    return is_valid


def valid_json(g: dict) -> bool:
    """Exact validity of a typed JSON geometry (GEOS IsValidOp semantics)."""
    fn = _engine_is_valid()
    geom = casev2.as_geometry(g)
    if fn is not None:
        return bool(fn(geom))
    ref = ROOT / "tests" / "reference"
    if str(ref) not in sys.path:
        sys.path.insert(0, str(ref))
    import validity  # tests/reference/validity.py (polygonal input only)

    if g["type"] == "Polygon":
        return validity.valid_geometry([g["coordinates"]])
    if g["type"] == "MultiPolygon":
        return validity.valid_geometry(g["coordinates"])
    raise RuntimeError("no validity check for non-polygonal input without the engine")


def legacy_valid(mp: list) -> tuple[bool, str]:
    """The legacy families' exact check, with the engine instead of Shapely."""
    for poly in mp:
        for r in poly:
            for x, y in r:
                if not (x == x and y == y) or abs(x) == float("inf") or abs(y) == float("inf"):
                    return False, "non-finite"
    if len(mp) == 1 and len(mp[0]) == 1:
        if not common.oracle.valid_single_polygon(mp):
            return False, "exact: ring not simple"
    else:
        ok, why = common.exact_valid(mp)
        if not ok:
            return False, "exact: " + why
    if not valid_json(casev2.legacy_to_typed(mp)):
        return False, "engine: invalid"
    return True, ""


# ============================================================================ generate


def generate_family(name: str, n: int, seed: int) -> tuple[list[dict], Counter]:
    """``n`` v2 case records of one family (deterministic for a given (n, seed))."""
    fn, legacy = next((f, lg) for nm, f, lg in ALL_FAMILIES if nm == name)
    rng = random.Random(f"{name}:{seed}")
    out: list[dict] = []
    seen: set[str] = set()
    stats: Counter = Counter()
    attempts = 0
    gen = LEGACY_GENERATOR if legacy else V2_GENERATOR
    prov = casev2.provenance(gen, seed, n)
    invalid_family = name.startswith("invalid-")
    while len(out) < n:
        attempts += 1
        if attempts > 500 * n + 2000:
            raise RuntimeError(f"{name}: too many rejected attempts ({stats.most_common(5)})")
        try:
            if legacy:
                variant, a, b = fn(rng)
                a, b = common.finalize(rng, a), common.finalize(rng, b)
                flags: tuple[str, ...] = ()
            else:
                variant, a, b, flags = fn(rng)
        except common.Reject as e:
            stats["reject: " + str(e)] += 1
            continue
        except (ZeroDivisionError, ValueError, OverflowError) as e:
            stats["construction error: " + type(e).__name__] += 1
            continue
        if legacy:
            if common.n_edges(a) + common.n_edges(b) > MAX_COORDS:
                stats["too many coordinates"] += 1
                continue
            bad = next((why for g in (a, b) for ok, why in [legacy_valid(g)] if not ok), None)
            if bad:
                stats["invalid: " + bad] += 1
                continue
        else:
            if casev2.as_geometry(a).num_coords + casev2.as_geometry(b).num_coords > MAX_COORDS:
                stats["too many coordinates"] += 1
                continue
            va, vb = valid_json(a), valid_json(b)
            if invalid_family and va and vb:
                stats["invalid family: both operands valid"] += 1
                continue
            if not invalid_family and not (va and vb):
                stats["invalid operand"] += 1
                continue
        key = json.dumps([a, b], sort_keys=True)
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        stats["kept"] += 1
        cid = f"{name}-{seed}-{len(out) + 1:06d}-{variant}"
        out.append(casev2.make_case(cid, name, a, b, variant=variant, prov=prov, flags=flags))
    stats["attempts"] = attempts
    return out, stats


def _gen_worker(args: tuple[str, int, int]) -> tuple[str, list[dict], dict]:
    name, n, seed = args
    recs, stats = generate_family(name, n, seed)
    return name, recs, dict(stats)


def generate_all(names: list[str], n: int, seed: int, jobs: int = 2, log=None):
    """{family: records} for the given families (in parallel over families)."""
    work = [(nm, n, seed) for nm in names]
    results: dict[str, list[dict]] = {}
    stats: dict[str, dict] = {}
    if jobs > 1 and len(work) > 1:
        import multiprocessing as mp

        with mp.get_context("fork").Pool(min(jobs, len(work))) as pool:
            for name, recs, st in pool.imap_unordered(_gen_worker, work):
                results[name], stats[name] = recs, st
                if log:
                    log(f"{name:26s} {len(recs):5d} cases {st.get('attempts', 0):7d} attempts")
    else:
        for w in work:
            name, recs, st = _gen_worker(w)
            results[name], stats[name] = recs, st
            if log:
                log(f"{name:26s} {len(recs):5d} cases {st.get('attempts', 0):7d} attempts")
    return {nm: results[nm] for nm in names}, stats


# ============================================================================ core


def stratum(rec: dict) -> tuple:
    t = rec.get("tags", {})
    vclass = str(t.get("variant", "")).split(".")[0]
    return (vclass, t.get("degeneracy", ""), t.get("range", ""), tuple(t.get("types", ())))


def _hkey(case_id: str) -> str:
    return hashlib.sha256(case_id.encode()).hexdigest()


def select_core(records: list[dict], k: int = CORE_PER_FAMILY) -> list[dict]:
    """A deterministic stratified sample of ``k`` records (all of them if fewer)."""
    if len(records) <= k:
        return list(records)
    strata: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        strata[stratum(r)].append(i)
    for idx in strata.values():
        idx.sort(key=lambda i: _hkey(records[i]["id"]))
    keys = sorted(strata, key=lambda s: (-len(strata[s]), s))
    alloc = dict.fromkeys(keys, 0)
    for s in keys[:k]:
        alloc[s] = 1
    left = k - sum(alloc.values())
    total = len(records)
    while left > 0:
        cap = {s: len(strata[s]) - alloc[s] for s in keys if len(strata[s]) > alloc[s]}
        weight = sum(len(strata[s]) for s in cap)
        quotas = {s: left * len(strata[s]) / weight for s in cap}
        base = {s: min(cap[s], int(q)) for s, q in quotas.items()}
        given = sum(base.values())
        for s, q in base.items():
            alloc[s] += q
        rest = left - given
        order = sorted(cap, key=lambda s: (-(quotas[s] - int(quotas[s])), -len(strata[s]), s))
        for s in order:
            if rest <= 0:
                break
            if alloc[s] < len(strata[s]):
                alloc[s] += 1
                rest -= 1
        left = k - sum(alloc.values())
        if total <= sum(alloc.values()):
            break
    chosen = sorted(i for s in keys for i in strata[s][: alloc[s]])
    return [records[i] for i in chosen]


# ============================================================================ curated


def _toml():
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    return tomllib


def _read_lines(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def _case_from_source(spec: dict, cache: dict) -> dict:
    """The (a, b, family) of a lead case: from a file (``from`` + ``id``) or inline WKT."""
    from geotruth.io import geometry_to_json, read_wkt

    if "from" in spec:
        path = ROOT / spec["from"]
        if path not in cache:
            cache[path] = {r["id"]: r for r in _read_lines(path)}
        src = cache[path][spec.get("source_id", spec["id"])]
        a, b = src["a"], src["b"]
        a = casev2.legacy_to_typed(a) if isinstance(a, list) else a
        b = casev2.legacy_to_typed(b) if isinstance(b, list) else b
        return {"a": a, "b": b, "family": src.get("family")}
    return {
        "a": geometry_to_json(read_wkt(spec["a"])),
        "b": geometry_to_json(read_wkt(spec["b"])),
        "family": spec.get("family"),
    }


_PROV_KEYS = (
    "library",
    "lib",
    "status",
    "status_date",
    "signature",
    "fields",
    "verified_on",
    "links",
    "evidence",
    "documented_in",
    "notes",
)


def _curated_prov(entry: dict, kind: str, case_spec: dict | None = None) -> dict:
    prov: dict[str, Any] = {"source": "curated", kind: entry["id"]}
    for k in _PROV_KEYS:
        if entry.get(k) not in (None, "", []):
            prov[k] = entry[k]
    up = entry.get("upstream_issue", "")
    prov["upstream_issue"] = up
    if up:
        prov["issue_url"] = up
    prov["upstream_status"] = entry.get("upstream_status") or ("reported" if up else "not reported")
    if case_spec:
        for k in ("parent", "minimised_with", "case_notes", "from"):
            if case_spec.get(k):
                prov["original_source" if k == "from" else k] = case_spec[k]
        if case_spec.get("parent"):
            prov["source"] = "minimised"
    return prov


def build_curated() -> list[dict]:
    """Curated records: every finding's cases (registry), then every documented lead."""
    tl = _toml()
    out: list[dict] = []
    with open(ROOT / "findings" / "registry.toml", "rb") as fh:
        registry = tl.load(fh)
    for f in registry.get("finding", []):
        for src in _read_lines(ROOT / f["cases"]):
            a, b = src["a"], src["b"]
            prov = _curated_prov(f, "finding")
            prov["original_source"] = f["cases"]
            out.append(
                casev2.make_case(
                    f"{f['id']}:{src['id']}",
                    src.get("family") or "curated",
                    a,
                    b,
                    variant=None,
                    prov=prov,
                    flags=("curated",),
                )
            )
    leads_path = CORPUS / "curated" / "leads.toml"
    if leads_path.exists():
        with open(leads_path, "rb") as fh:
            leads = tl.load(fh)
        cache: dict = {}
        for lead in leads.get("lead", []):
            for spec in lead.get("case", []):
                src = _case_from_source(spec, cache)
                prov = _curated_prov(lead, "lead", spec)
                ops = spec.get("ops")
                out.append(
                    casev2.make_case(
                        f"{lead['id']}:{spec['id']}",
                        src["family"] or spec.get("family") or "curated",
                        src["a"],
                        src["b"],
                        variant=None,
                        prov=prov,
                        flags=("curated", "lead"),
                        ops=ops,
                    )
                )
    ids = [r["id"] for r in out]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    if dup:
        raise ValueError(f"duplicate curated ids: {dup}")
    return out


# ============================================================================ files


def dumps(rec: dict) -> str:
    return json.dumps(rec, separators=(",", ":"))


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(dumps(r) + "\n")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    with open(path, "rb") as fh:
        return sum(1 for ln in fh if ln.strip())


def file_entry(path: Path, corpus: Path) -> dict:
    return {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "cases": count_lines(path),
    }


def tier_files(corpus: Path) -> dict[str, list[Path]]:
    cases = corpus / "cases"
    return {
        "seed": [cases / "seed.jsonl"] if (cases / "seed.jsonl").exists() else [],
        "core": sorted((cases / "core").glob("*.jsonl")),
        "curated": [cases / "curated.jsonl"] if (cases / "curated.jsonl").exists() else [],
        "full": sorted((cases / "full").glob("*.jsonl")),
    }


def write_manifest(corpus: Path, params: dict, old: dict | None = None) -> dict:
    """Write corpus/MANIFEST.json for every tier file present (a missing full tier keeps
    the entries of the previous manifest, marked ``present: false``)."""
    files = tier_files(corpus)
    tiers: dict[str, Any] = {}
    in_git = {"seed": True, "core": True, "curated": True, "full": False}
    fmt = {"seed": "v1", "core": "v2", "curated": "v2", "full": "v2"}
    for tier, paths in files.items():
        entries = {str(p.relative_to(corpus)): file_entry(p, corpus) for p in paths}
        if not entries and old and tier in old.get("tiers", {}):
            entries = {
                k: {**v, "present": False} for k, v in old["tiers"][tier].get("files", {}).items()
            }
        tiers[tier] = {
            "format": fmt[tier],
            "in_git": in_git[tier],
            "cases": sum(e["cases"] for e in entries.values()),
            "files": entries,
        }
    families: dict[str, Any] = {}
    for name, _, legacy in ALL_FAMILIES:
        fam: dict[str, Any] = {"generator": LEGACY_GENERATOR if legacy else V2_GENERATOR}
        for tier in ("core", "full"):
            e = tiers[tier]["files"].get(f"cases/{tier}/{name}.jsonl")
            if e:
                fam[tier] = e["cases"]
        families[name] = fam
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "corpus_version": CORPUS_VERSION,
        "case_format": "https://github.com/abafaboy/geotruth/schemas/case.v2.schema.json",
        "generator_version": casev2.GENERATOR_VERSION,
        "licence": "CC0-1.0",
        "parameters": params,
        "tiers": tiers,
        "families": families,
    }
    with open(corpus / "MANIFEST.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=False)
        fh.write("\n")
    return manifest


def update_sha256sums(corpus: Path) -> None:
    """Rewrite corpus/SHA256SUMS: every tracked case and expected-answer file."""
    files = tier_files(corpus)
    tracked = files["seed"] + files["core"] + files["curated"]
    tracked += sorted(corpus.glob("expected-*/*.jsonl"))
    lines = [f"{sha256_file(p)}  {p.relative_to(corpus)}" for p in tracked]
    (corpus / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def load_manifest(corpus: Path = CORPUS) -> dict | None:
    path = corpus / "MANIFEST.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ============================================================================ build


def build(
    tiers: set[str],
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    per_family: int = CORE_PER_FAMILY,
    families: list[str] | None = None,
    jobs: int = 2,
    corpus: Path = CORPUS,
    log=None,
) -> dict:
    """Build the requested tiers; returns the new manifest."""
    names = families or FAMILY_NAMES
    unknown = set(names) - set(FAMILY_NAMES)
    if unknown:
        raise ValueError(f"unknown families: {sorted(unknown)}")
    old = load_manifest(corpus)
    params = dict((old or {}).get("parameters", {}))
    if tiers & {"full", "core"}:
        recs, _stats = generate_all(names, n, seed, jobs, log)
        params.update({"seed": seed, "n_per_family": n, "core_per_family": per_family})
        for name, rs in recs.items():
            if "full" in tiers:
                write_records(corpus / "cases" / "full" / f"{name}.jsonl", rs)
            if "core" in tiers:
                write_records(
                    corpus / "cases" / "core" / f"{name}.jsonl", select_core(rs, per_family)
                )
    if "curated" in tiers:
        cur = build_curated()
        write_records(corpus / "cases" / "curated.jsonl", cur)
        if log:
            log(f"{'curated':26s} {len(cur):5d} cases")
    manifest = write_manifest(corpus, params, old)
    update_sha256sums(corpus)
    return manifest


# ============================================================================ stats


def iter_tier(tier: str, corpus: Path = CORPUS, family: str | None = None):
    for p in tier_files(corpus)[tier]:
        for rec in _read_lines(p):
            if family is None or rec.get("family") == family:
                yield rec


def stats(tier: str, by: list[str], corpus: Path = CORPUS, family: str | None = None) -> dict:
    """Counts per family and per tag value (``by`` tag names; ``flags`` counts each flag)."""
    table: dict[str, Counter] = defaultdict(Counter)
    for rec in iter_tier(tier, corpus, family):
        fam = rec.get("family", "?")
        tags = rec.get("tags", {})
        table[fam]["cases"] += 1
        for key in by:
            val = tags.get(key)
            if key == "flags":
                for fl in val or ():
                    table[fam][f"flags={fl}"] += 1
            elif key == "types":
                table[fam][f"types={'/'.join(val or ())}"] += 1
            else:
                table[fam][f"{key}={val}"] += 1
    return {k: dict(v) for k, v in table.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--tier", default="all", choices=("all", "core", "curated", "full"))
    b.add_argument("--n", type=int, default=DEFAULT_N)
    b.add_argument("--seed", type=int, default=DEFAULT_SEED)
    b.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args(argv)
    tiers = {"core", "curated", "full"} if args.tier == "all" else {args.tier}
    build(tiers, n=args.n, seed=args.seed, jobs=args.jobs, log=lambda s: print(s, file=sys.stderr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
