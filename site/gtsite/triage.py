"""Matching failure clusters to entries of the triage registry (``findings/registry.toml``).

A registry entry names a library target, the result fields affected and the corpus
families where its cluster shows up. A cluster (library x family x signature) matches an
entry when

- the entry's ``library`` names the cluster's target,
- the entry lists no ``families``, or lists the cluster's family, and
- the entry lists no ``fields``, or one of them belongs to the cluster's capability
  (v1 field names such as ``area_inter`` are translated to v2 paths).

An entry that lists neither families nor fields (the ``[[lead]]`` entries, which only
register a documented candidate by its signature) is never matched automatically: it would
match every cluster of its library. ``library`` may be one target id or a list of them.

A match says that the triaged behaviour is a candidate explanation of the cluster, found by
library, family and field; the site says so and shows the entry's own signature next to the
cluster's. A cluster that matches nothing is ``unreviewed`` (DESIGN §0.4): an automated
disagreement, not a confirmed bug.
"""

from __future__ import annotations

from typing import Any

from gtsite.aggregate import Cluster

UNREVIEWED = "unreviewed"
MIXED = "mixed"


def _v1_to_v2() -> dict[str, str]:
    try:
        from geotruth.harness.manifest import V1_TO_V2
    except ImportError:  # pragma: no cover
        return {}
    return dict(V1_TO_V2)


def capability_of_field(path: str) -> str:
    """The capability a result field belongs to."""
    path = _v1_to_v2().get(path, path)
    if path.startswith("predicates."):
        return "predicates"
    if path in ("valid_a", "valid_b") or path.startswith("validity"):
        return "validity"
    if path.startswith("echo"):
        return "echo"
    return path


def libraries(entry: dict[str, Any]) -> list[str]:
    """The target ids an entry names (``library`` is a string or a list)."""
    lib = entry.get("library")
    if isinstance(lib, str):
        return [lib]
    if isinstance(lib, list):
        return [str(x) for x in lib]
    return []


def matches(cluster: Cluster, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        if cluster.target not in libraries(e):
            continue
        fams = e.get("families") or []
        fields = e.get("fields") or []
        if not fams and not fields:
            continue
        if fams and cluster.family not in fams:
            continue
        if fields and cluster.capability not in {capability_of_field(f) for f in fields}:
            continue
        out.append(e)
    return out


def status(found: list[dict[str, Any]]) -> str:
    """The triage status of a cluster from its matching entries."""
    statuses = {str(e.get("status") or UNREVIEWED) for e in found}
    if not statuses:
        return UNREVIEWED
    if len(statuses) == 1:
        return statuses.pop()
    return MIXED
