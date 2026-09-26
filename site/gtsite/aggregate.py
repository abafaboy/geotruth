"""Streaming aggregation of ``score.v2`` records (one library, one tier).

A library's score file holds one record per (case, capability) - tens of thousands of
records, most of them ``correct``. The site needs counts for every record but the full
record only for the failures, so records are folded into :class:`LibraryStats` one at a
time and only the failing ones are kept.

The counting rules are the scorer's own (``geotruth.harness.score.summarize``): a record
counts against the library when its verdict is ``wrong`` or ``error`` and it is not marked
``derived``; overlay records also carry their tier. ``tests/site`` checks that the counts
here equal ``summarize`` on the same records.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from gtsite.words import FAILURE_VERDICTS, GRADED_VERDICTS, HEADLINE_TIERS

#: Prefix of the ``got`` text of a record the scorer failed on (a harness bug).
SCORER_FAILED = "scorer failed: "


def is_exact_but_invalid(rec: dict[str, Any]) -> bool:
    """An overlay record in the topological tier whose output is invalid OGC geometry
    although its point set is exactly the exact result's (Hausdorff distance 0 and
    symmetric-difference area 0, measured by the even-odd rule)."""
    m = rec.get("metrics") or {}
    return (
        rec.get("tier") == "topological"
        and m.get("output_valid") is False
        and m.get("hausdorff2") == "0"
        and m.get("symdiff_area") == "0"
    )


@dataclass
class CapStats:
    """Counts of one capability (of one library, optionally within one family)."""

    verdicts: Counter = field(default_factory=Counter)
    tiers: Counter = field(default_factory=Counter)
    derived: int = 0  # wrong/error records marked derived (counted once, elsewhere)
    headline: int = 0  # wrong/error records not marked derived
    #: topological records whose output has exactly the right point set but is not valid
    #: OGC geometry (a representation problem rather than a wrong point set)
    exact_but_invalid: int = 0

    def add(self, rec: dict[str, Any]) -> None:
        v = rec["verdict"]
        self.verdicts[v] += 1
        if "tier" in rec:
            self.tiers[rec["tier"]] += 1
            if is_exact_but_invalid(rec):
                self.exact_but_invalid += 1
        if v in FAILURE_VERDICTS:
            if rec.get("derived"):
                self.derived += 1
            else:
                self.headline += 1

    @property
    def total(self) -> int:
        return sum(self.verdicts.values())

    @property
    def graded(self) -> int:
        """Records with a gradeable answer: correct, wrong, error or convention."""
        return sum(self.verdicts.get(v, 0) for v in GRADED_VERDICTS)

    @property
    def headline_tiers(self) -> dict[str, int]:
        return {t: self.tiers.get(t, 0) for t in HEADLINE_TIERS}

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "records": self.total,
            "graded": self.graded,
            "failures": self.headline,
            "verdicts": dict(sorted(self.verdicts.items())),
        }
        if self.tiers:
            out["tiers"] = dict(sorted(self.tiers.items()))
        if self.derived:
            out["derived"] = self.derived
        if self.exact_but_invalid:
            out["topological_exact_point_set"] = self.exact_but_invalid
        return out


@dataclass
class Cluster:
    """A failure cluster: library x family x signature (the scorer's ``cluster`` key).

    ``key_source`` is ``"scorer"`` when the key comes from the score records, or ``"site"``
    for failing records the scorer gives no key (``error`` verdicts of relate, predicates
    and validity), which the site groups as ``<target>|<family>|<capability>:error``.
    """

    key: str
    target: str
    family: str
    capability: str
    signature: str
    key_source: str
    records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def case_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for r in self.records:
            seen.setdefault(r["id"], None)
        return list(seen)


@dataclass
class LibraryStats:
    """Everything the site needs from one library's score records."""

    target: str
    caps: dict[str, CapStats] = field(default_factory=lambda: defaultdict(CapStats))
    families: dict[str, dict[str, CapStats]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(CapStats))
    )
    clusters: dict[str, Cluster] = field(default_factory=dict)
    cases: set[str] = field(default_factory=set)
    libs: Counter = field(default_factory=Counter)
    versions: Counter = field(default_factory=Counter)
    scorer_failures: int = 0
    records: int = 0

    def add(self, rec: dict[str, Any]) -> None:
        self.records += 1
        cap = rec["capability"]
        fam = rec.get("family") or "-"
        self.cases.add(rec["id"])
        self.libs[rec.get("lib", "")] += 1
        if rec.get("versions"):
            self.versions[json.dumps(rec["versions"], sort_keys=True)] += 1
        if str(rec.get("got", "")).startswith(SCORER_FAILED):
            self.scorer_failures += 1
        self.caps[cap].add(rec)
        self.families[fam][cap].add(rec)
        if rec["verdict"] in FAILURE_VERDICTS and not rec.get("derived"):
            key = rec.get("cluster")
            source = "scorer"
            if not key:
                key = f"{self.target}|{fam}|{cap}:{rec['verdict']}"
                source = "site"
            cl = self.clusters.get(key)
            if cl is None:
                sig = key.split("|", 2)[2] if key.count("|") >= 2 else key
                cl = Cluster(key, self.target, fam, cap, sig, source)
                self.clusters[key] = cl
            slim = {k: v for k, v in rec.items() if k != "versions"}
            cl.records.append(slim)

    # ------------------------------------------------------------------ views

    @property
    def lib(self) -> str:
        """The most common ``lib`` string of the records."""
        return self.libs.most_common(1)[0][0] if self.libs else ""

    def version_sets(self) -> list[dict[str, str]]:
        """The distinct ``versions`` objects of the records, most common first."""
        return [json.loads(k) for k, _ in self.versions.most_common()]

    def cap(self, name: str) -> CapStats:
        return self.caps.get(name) or CapStats()

    def sorted_clusters(self) -> list[Cluster]:
        """Largest first, then by key (deterministic)."""
        return sorted(self.clusters.values(), key=lambda c: (-c.count, c.key))

    @property
    def headline(self) -> int:
        return sum(c.headline for c in self.caps.values())

    def summary_json(self) -> dict[str, Any]:
        return {
            "cases": len(self.cases),
            "records": self.records,
            "scorer_failures": self.scorer_failures,
            "capabilities": {k: v.to_json() for k, v in sorted(self.caps.items())},
        }
