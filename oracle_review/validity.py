"""Proposed fix for finding F3: exact OGC / GEOS-default validity for ANY input shape
(single ring, polygon with holes, multipolygon), so that compare.py never treats an
invalid multi-ring input as valid.

    valid_geometry(geom) -> bool         geom = FORMAT.md MultiPolygon coordinate lists

Rules (GEOS IsValidOp with isInvertedRingValid = false, which is what Shapely's is_valid
and every adapter in this repo use):
  R0 every coordinate finite                                  (GEOS: Invalid Coordinate)
  R1 every ring closed, >= 3 distinct consecutive vertices, simple: no self-crossing,
     no self-touch, no fold-back                              (Too few points / Ring
                                                               self-intersection)
  R2 two rings of the same polygon or of different parts never share a segment
     (they may meet in finitely many points)                  (Self-intersection)
  R3 every hole lies inside its shell                         (Hole lies outside shell)
  R4 holes of one polygon have disjoint interiors (no nesting, no overlap)
                                                              (Holes are nested /
                                                               Self-intersection)
  R5 the interior of each polygon is connected: in the bipartite graph
     rings <-> touch points (points where two different rings of the polygon meet)
     there is no cycle                                        (Interior is disconnected)
  R6 parts of a multipolygon have disjoint interiors          (Nested shells /
                                                               Self-intersection)
Everything is decided in exact rational arithmetic on the input doubles (via indep.py).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indep  # noqa: E402
from fractions import Fraction as F  # noqa: E402


def _ring_pts(ring):
    return indep.dedup([(F(x), F(y)) for x, y in ring])


def _edges(pts):
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i] != pts[i + 1]]


def _contacts(ea, eb):
    """Set of contact points between two edge lists, or None if they share a segment."""
    pts = set()
    for p0, p1 in ea:
        for q0, q1 in eb:
            if max(p0[0], p1[0]) < min(q0[0], q1[0]) or max(q0[0], q1[0]) < min(p0[0], p1[0]):
                continue
            if max(p0[1], p1[1]) < min(q0[1], q1[1]) or max(q0[1], q1[1]) < min(p0[1], p1[1]):
                continue
            c = indep.contact_params(p0, p1, q0, q1)
            if len(c) == 2:
                return None
            if c:
                t = c[0]
                pts.add((p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])))
    return pts


def _interiors_meet(ga, gb):
    return indep.evaluate_geoms(ga, gb)["inter"] > 0


def valid_geometry(geom):
    # R0, R1
    for poly in geom:
        if not poly:
            return False
        for ring in poly:
            if not ring or any(not math.isfinite(c) for p in ring for c in p):
                return False
            if not indep.ring_is_simple(ring):
                return False
    rings = [[_ring_pts(r) for r in poly] for poly in geom]
    edges = [[_edges(r) for r in poly] for poly in rings]
    for pi, poly in enumerate(geom):
        shell = [poly[0]]
        # R3: each hole inside the shell (closed containment, exact)
        for h in poly[1:]:
            if not indep.evaluate_geoms([shell], [[h]])["contains"]:
                return False
        # R2 + R4 inside the polygon; collect (ring, touch point) incidences for R5
        incidences = set()
        for i in range(len(poly)):
            for j in range(i + 1, len(poly)):
                c = _contacts(edges[pi][i], edges[pi][j])
                if c is None:
                    return False
                if i > 0 and _interiors_meet([[poly[i]]], [[poly[j]]]):
                    return False
                for p in c:
                    incidences.add((i, p))
                    incidences.add((j, p))
        # R5: a cycle in the bipartite graph rings <-> touch points disconnects the interior
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for r, p in incidences:
            a, b = find(("ring", r)), find(("pt", p))
            if a == b:
                return False
            parent[a] = b
    # R2 + R6 between parts
    for i in range(len(geom)):
        for j in range(i + 1, len(geom)):
            for ei in edges[i]:
                for ej in edges[j]:
                    if _contacts(ei, ej) is None:
                        return False
            if _interiors_meet([geom[i]], [geom[j]]):
                return False
    return True

