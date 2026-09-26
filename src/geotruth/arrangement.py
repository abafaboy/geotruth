"""The planar arrangement of two geometries: noding, DCEL and cell labels (DESIGN §2.2).

:func:`build_arrangement` takes two operands A and B of any type (points, lines, polygons,
their multi-types and GeometryCollections, empty or not), nodes all their segments against
each other, and returns a labelled :class:`~geotruth.arrangement_api.Arrangement` that
satisfies every invariant of the frozen API (``validate()``). Every decision is exact
integer or rational arithmetic; there is no tolerance anywhere.

Pipeline
--------
1. **Input.** All coordinates of both operands are scaled by one power of two
   ``2**-scale_exp`` (the minimum 2-adic valuation, as :class:`geotruth.numbers.DyadicScale`)
   to Python ints. Exact non-dyadic rationals (``Fraction``/``mpq`` coordinates, e.g. an
   engine output fed back in) are also accepted: they are multiplied by the lcm ``L`` of
   the odd parts of their denominators, and the stored vertices carry ``L`` in their
   homogeneous weight, so the API's ``real = (vx / vw) * 2**scale_exp`` still holds. Rings
   must be closed and have non-zero area (:class:`InvalidInputError` otherwise); their exact
   orientation goes into ``ring_orientation``. Zero-length segments are dropped (a line
   whose points all coincide becomes a point that lies on that line).
2. **Candidate pairs.** Every ring and line is cut into maximal monotone chains (all
   segment directions in one closed quadrant). A sweep over the chain envelopes sorted by
   ``xmin`` reports every pair of chains (and chain/input point) whose envelopes overlap;
   each such pair is refined by recursive bisection of the chains (a sub-chain's envelope
   is the box of its two end points), down to segment pairs tested with
   :func:`geotruth.exact.intersect_segments`. Two segments of one chain never meet except
   at their shared vertex, so a chain is never tested against itself.
3. **Splitting and merging.** Every segment is split at every intersection point and input
   point on it (points sorted along the segment by an exact projection key); coincident
   sub-segments are merged into one edge that keeps one :class:`EdgeSource` per covering
   input segment (``forward`` relative to the edge's primary half-edge).
4. **Rotation system.** The outgoing half-edges of a vertex are sorted counter-clockwise
   by the direction vector of their *source segment* (a sub-edge is collinear with it), so
   no arithmetic touches intersection points. Degree <= 2 needs no sort, and a proper
   crossing (two straight-through edges) needs a single cross product.
5. **Faces.** Boundary cycles are walked with ``next``. In each connected component, the
   cycle through the wedge that contains direction ``-x`` at the component's
   lexicographically smallest vertex is the component's outer cycle; every other cycle is
   the outer boundary of a new bounded face. Each component (and each isolated vertex) is
   then located by exact horizontal ray shooting: a sweep in ``y`` answers, for the
   component's leftmost vertex ``p``, which edge or vertex the ray from ``p`` towards
   ``-x`` hits first; the face on ``p``'s side of that hit is its containing face
   (possibly through the outer cycle of another component, whose leftmost vertex lies
   further left and is resolved first). This is the one exact point location per nested
   component of DESIGN §2.2; no point is ever constructed.
6. **Labels, with no sample point.** For each operand X, crossing edge ``e`` from the right
   of half-edge ``2e`` to its left changes the *coverage count* (the number of polygonal
   elements of X containing the face) by ``+1`` for every ring source of X whose interior
   lies on the left of ``2e`` (exact ring orientation and shell/hole role, see
   :meth:`Arrangement.interior_is_left`) and ``-1`` for every other ring source. A
   breadth-first walk from the unbounded face (count 0) assigns every face its count; the
   equation is then re-checked on *every* edge, and every half-edge lying on a ring of X
   with the interior on its left must see a face with count >= 1 (and, for a Polygon or
   MultiPolygon operand, every other ring half-edge a face with count 0). A face is
   X-Interior when its count is positive: this is the parity rule for a single valid
   polygonal geometry and the *union* semantics of RelateNG for GeometryCollections.
   Edges and vertices are located by DESIGN §1: the polygonal part first (Interior when
   every incident face sector is interior, as AdjacentEdgeLocator; Boundary when some
   are), then lines (Boundary when the point occurs an odd number of times among the
   first/last coordinates of all line elements, else Interior on a line), then points.

Cost (honest bounds)
--------------------
With ``n`` input segments and points, ``c`` monotone chains and ``k`` split points:
``O(n log n)`` for chains and sorting, plus one envelope test per pair of chains whose
x-ranges overlap (``O(c^2)`` in the worst case, e.g. long near-parallel edges, even when
``k == 0``), plus the bisection work of each overlapping chain pair (up to the product of
their lengths), plus ``O((n + k) log(n + k))`` for splitting, sorting and the rotation
system, ``O(n + k)`` for cycles and labels, and for the ray shooting ``O(E log E)`` plus,
per nested component, the number of edges crossing its horizontal line. The
:class:`Budget` bounds ``n + k``, wall-clock time and (optionally) resident memory.

Errors
------
- :class:`BudgetExceeded`: over budget. The caller reports ``engine_skipped``.
- :class:`InvalidInputError` (a ``ValueError``): the input is outside the arrangement's
  contract: a non-finite coordinate, an unclosed or zero-area ring, or polygonal elements
  whose coverage is inconsistent with valid polygons (a hole outside its shell, a
  self-crossing ring, overlapping parts of a MultiPolygon, ...). Check validity first.
- :class:`~geotruth.arrangement_api.ArrangementError`: an internal invariant failed
  (an engine bug). The caller reports ``engine_error``.
"""

from __future__ import annotations

import math
import os
import time
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cmp_to_key
from math import gcd
from typing import Any

from geotruth.arrangement_api import Arrangement, ArrangementError, EdgeSource, Location
from geotruth.exact import angle_cmp, hp_orient, hpoint, intersect_segments, on_segment
from geotruth.geom import (
    GEOM_A,
    GEOM_B,
    Geometry,
    MultiPolygon,
    Polygon,
    SourceTag,
)
from geotruth.numbers import NonFiniteError, rational

__all__ = [
    "DEFAULT_BUDGET",
    "Budget",
    "BudgetExceeded",
    "InvalidInputError",
    "build_arrangement",
]

_I, _B, _E = int(Location.INTERIOR), int(Location.BOUNDARY), int(Location.EXTERIOR)


# ============================================================================ errors


class InvalidInputError(ValueError):
    """The operands are outside the arrangement's contract (see the module docstring)."""


class BudgetExceeded(RuntimeError):
    """The case exceeds the engine's resource budget; report it as ``engine_skipped``.

    ``resource`` is ``"size"`` (``n + k``), ``"time"`` (seconds) or ``"memory"`` (MB);
    ``limit`` and ``used`` are in that unit, and ``phase`` names the pipeline step.
    """

    def __init__(self, resource: str, limit: float, used: float, phase: str) -> None:
        self.resource = resource
        self.limit = limit
        self.used = used
        self.phase = phase
        super().__init__(f"arrangement over budget: {resource} {used} > {limit} (during {phase})")


@dataclass(frozen=True)
class Budget:
    """Per-case resource limits; ``None`` disables a limit.

    ``max_size`` caps ``n + k``: input segments and points plus the split points found
    (DESIGN §2.2, default 200k). ``max_seconds`` caps the wall-clock time of the build and
    ``max_memory_mb`` the process's resident set size (read from ``/proc``; ignored where
    that is unavailable).
    """

    max_size: int | None = 200_000
    max_seconds: float | None = 120.0
    max_memory_mb: float | None = None


#: The default budget of :func:`build_arrangement`.
DEFAULT_BUDGET = Budget()

_UNLIMITED = Budget(None, None, None)


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            pages = int(fh.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * os.sysconf("SC_PAGE_SIZE") / 2**20


# ===================================================================== exact scaling


def _parts(v: Any) -> tuple[int, int]:
    """``(numerator, denominator > 0)`` of a finite coordinate value, exactly."""
    if isinstance(v, float):
        if not math.isfinite(v):
            raise NonFiniteError(f"non-finite coordinate {v!r}")
        return v.as_integer_ratio()
    if isinstance(v, bool):
        raise TypeError("a boolean is not a coordinate")
    if isinstance(v, int):
        return v, 1
    try:
        n, d = int(v.numerator), int(v.denominator)
    except AttributeError:
        raise TypeError(f"not an exact coordinate value: {v!r}") from None
    if d < 0:
        n, d = -n, -d
    return n, d


def _v2(n: int) -> int:
    """2-adic valuation of a non-zero int."""
    return (n & -n).bit_length() - 1


class _Scale:
    """Maps coordinates to ints: ``v * odd_lcm * 2**-exp``."""

    def __init__(self, values: Iterable[Any]) -> None:
        best: int | None = None
        lcm = 1
        for v in values:
            n, d = _parts(v)
            if n == 0:
                continue
            a = _v2(d)
            e = _v2(n) - a
            if best is None or e < best:
                best = e
            odd = d >> a
            if odd != 1:
                lcm = lcm * odd // gcd(lcm, odd)
        self.exp = 0 if best is None else best
        self.lcm = lcm

    def to_int(self, v: Any) -> int:
        n, d = _parts(v)
        if n == 0:
            return 0
        a = _v2(d)
        n *= self.lcm // (d >> a)
        shift = -self.exp - a
        return n << shift if shift >= 0 else n >> -shift

    def point(self, c: tuple[Any, Any]) -> tuple[int, int]:
        return self.to_int(c[0]), self.to_int(c[1])


# ============================================================================ builder


def build_arrangement(
    a: Geometry,
    b: Geometry,
    *,
    budget: Budget | None = DEFAULT_BUDGET,
    check: bool = True,
    stats: dict[str, Any] | None = None,
) -> Arrangement:
    """The labelled arrangement of operands ``a`` (A) and ``b`` (B).

    ``budget`` bounds the work (``None``: unlimited) and raises :class:`BudgetExceeded`.
    ``check`` runs the O(V + E) topology and label invariants of
    :meth:`Arrangement.validate` before returning (the exact geometric checks are left to
    the caller: ``arr.validate()``). If ``stats`` is a dict, it receives sizes (``n``,
    ``k``, ``chains``, ``chain_pairs``, ``segment_tests``, ``V``, ``E``, ``F``,
    ``components``) and per-phase timings in seconds.
    """
    builder = _Builder(a, b, budget or _UNLIMITED)
    arr = builder.run()
    if check:
        arr.validate(geometry=False, planarity=False, labels=True)
    if stats is not None:
        stats.update(builder.stats)
    return arr


class _Builder:
    """One arrangement build; the phases are methods called in order by :meth:`run`."""

    def __init__(self, a: Geometry, b: Geometry, budget: Budget) -> None:
        self.a, self.b = a, b
        self.budget = budget
        self.t0 = time.perf_counter()
        self.deadline = None if budget.max_seconds is None else self.t0 + budget.max_seconds
        self.phase = "input"
        self.ops = 0
        self.stats: dict[str, Any] = {}

    # ------------------------------------------------------------------ budget

    def tick(self) -> None:
        """Called from hot loops: checks time and memory every 1024 calls."""
        self.ops += 1
        if self.ops & 1023 == 0:
            self.check_clock()

    def check_clock(self) -> None:
        if self.deadline is not None:
            now = time.perf_counter()
            if now > self.deadline:
                raise BudgetExceeded(
                    "time", self.budget.max_seconds, round(now - self.t0, 3), self.phase
                )
        if self.budget.max_memory_mb is not None:
            rss = _rss_mb()
            if rss is not None and rss > self.budget.max_memory_mb:
                raise BudgetExceeded("memory", self.budget.max_memory_mb, round(rss), self.phase)

    def check_size(self) -> None:
        cap = self.budget.max_size
        if cap is not None and self.n + self.k > cap:
            raise BudgetExceeded("size", cap, self.n + self.k, self.phase)

    def enter(self, phase: str) -> None:
        now = time.perf_counter()
        self.stats[f"t_{self.phase}"] = round(now - self.t_phase, 6)
        self.phase = phase
        self.t_phase = now
        self.check_clock()

    # --------------------------------------------------------------------- run

    def run(self) -> Arrangement:
        self.t_phase = self.t0
        self.read_input()
        self.enter("intersect")
        self.find_intersections()
        self.enter("split")
        self.build_edges()
        self.enter("rotate")
        self.link_rotations()
        self.enter("faces")
        self.make_faces()
        self.enter("label")
        self.label()
        self.enter("emit")
        arr = self.emit()
        self.enter("done")
        self.stats.update(
            n=self.n,
            k=self.k,
            chains=len(self.chain_lo),
            chain_pairs=self.n_chain_pairs,
            segment_tests=self.n_tests,
            V=len(self.VX),
            E=len(self.EU),
            F=self.num_faces,
            components=self.num_components,
            t_total=round(time.perf_counter() - self.t0, 6),
        )
        return arr

    # ================================================================== 1. input

    def read_input(self) -> None:
        a, b = self.a, self.b
        try:
            self.scale = sc = _Scale(v for g in (a, b) for v in g.iter_values())
        except NonFiniteError as exc:
            raise InvalidInputError(f"invalid coordinate: {exc}") from exc
        # segments (parallel lists; segments of one polyline are contiguous)
        self.P: list[tuple[int, int]] = []
        self.Q: list[tuple[int, int]] = []
        self.stag: list[SourceTag] = []
        # monotone chains: segment index range [lo, hi) and envelope
        self.chain_lo: list[int] = []
        self.chain_hi: list[int] = []
        self.chain_env: list[tuple[int, int, int, int]] = []
        # isolated input points: (x, y), with flags per operand
        self.points: dict[tuple[int, int], int] = {}  # point -> bitmask
        self.orientation: dict[SourceTag, int] = {}
        self.endpoints = (Counter(), Counter())  # mod-2 rule input, per operand
        self.simple_polygonal = (
            isinstance(a, (Polygon, MultiPolygon)),
            isinstance(b, (Polygon, MultiPolygon)),
        )
        for gid, g in ((GEOM_A, a), (GEOM_B, b)):
            for ring in g.iter_rings(gid):
                if not ring.coords:
                    continue
                pts = [sc.point(c) for c in ring.coords]
                if pts[0] != pts[-1]:
                    raise InvalidInputError(f"ring {ring.tag} is not closed")
                area2 = 0
                for i in range(len(pts) - 1):
                    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
                    area2 += x0 * y1 - x1 * y0
                if area2 == 0:
                    raise InvalidInputError(f"ring {ring.tag} has zero area")
                self.orientation[ring.tag] = 1 if area2 > 0 else -1
                self.add_polyline(pts, ring.tag)
            for tag, coords in g.iter_lines(gid):
                pts = [sc.point(c) for c in coords]
                ends = self.endpoints[gid]
                ends[pts[0]] += 1
                ends[pts[-1]] += 1
                if not self.add_polyline(pts, tag):
                    # all points coincide: a point lying on this line (RelateNG treats the
                    # line as having real dimension 0)
                    self.points[pts[0]] = self.points.get(pts[0], 0) | (4 << gid)
            for _, c in g.iter_points():
                p = sc.point(c)
                self.points[p] = self.points.get(p, 0) | (1 << gid)
        self.n = len(self.P) + len(self.points)
        self.k = 0
        self.check_size()

    def add_polyline(self, pts: list[tuple[int, int]], tag: SourceTag) -> bool:
        """Append the non-degenerate segments of ``pts`` and their monotone chains.

        Returns False if the polyline has no segment of positive length.
        """
        clean = [pts[0]]
        for p in pts[1:]:
            if p != clean[-1]:
                clean.append(p)
        m = len(clean) - 1
        if m == 0:
            return False
        P, Q = self.P, self.Q
        base = len(P)
        P.extend(clean[:-1])
        Q.extend(clean[1:])
        self.stag.extend([tag] * m)
        start, sx, sy = 0, 0, 0
        for i in range(m):
            (x0, y0), (x1, y1) = clean[i], clean[i + 1]
            dx = (x1 > x0) - (x1 < x0)
            dy = (y1 > y0) - (y1 < y0)
            if (sx and dx and dx != sx) or (sy and dy and dy != sy):
                self.add_chain(base + start, base + i, clean[start], clean[i])
                start, sx, sy = i, dx, dy
            else:
                sx = sx or dx
                sy = sy or dy
        self.add_chain(base + start, base + m, clean[start], clean[m])
        return True

    def add_chain(self, lo: int, hi: int, p: tuple[int, int], q: tuple[int, int]) -> None:
        self.chain_lo.append(lo)
        self.chain_hi.append(hi)
        self.chain_env.append((min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1])))

    # ======================================================= 2. candidate pairs

    def find_intersections(self) -> None:
        nseg = len(self.P)
        self.splits: list[list[tuple[int, int, int]] | None] = [None] * nseg
        self.n_tests = 0
        self.n_chain_pairs = 0
        env = list(self.chain_env)
        nchains = len(env)
        point_list = list(self.points)
        for x, y in point_list:
            env.append((x, x, y, y))
        order = sorted(range(len(env)), key=lambda i: env[i][0])
        active: list[int] = []
        for i in order:
            x0, _, y0, y1 = env[i]
            keep = []
            for j in active:
                ej = env[j]
                if ej[1] < x0:
                    continue
                keep.append(j)
                if ej[3] < y0 or y1 < ej[2]:
                    continue
                if i < nchains:
                    if j < nchains:
                        self.n_chain_pairs += 1
                        self.overlap_chains(i, j)
                    else:
                        self.overlap_point(i, point_list[j - nchains])
                elif j < nchains:
                    self.overlap_point(j, point_list[i - nchains])
            keep.append(i)
            active = keep
            self.tick()

    def overlap_chains(self, c0: int, c1: int) -> None:
        """Test every segment pair of two chains whose envelopes overlap (bisection)."""
        P, Q = self.P, self.Q
        stack = [(self.chain_lo[c0], self.chain_hi[c0], self.chain_lo[c1], self.chain_hi[c1])]
        pop, push = stack.pop, stack.append
        steps = 0
        while stack:
            a0, a1, b0, b1 = pop()
            if a1 - a0 == 1 and b1 - b0 == 1:
                self.test_pair(a0, b0)
                continue
            steps += 1
            if steps & 4095 == 0:
                self.check_clock()
            p, q, r, s = P[a0], Q[a1 - 1], P[b0], Q[b1 - 1]
            if p[0] <= q[0]:
                ax0, ax1 = p[0], q[0]
            else:
                ax0, ax1 = q[0], p[0]
            if r[0] <= s[0]:
                bx0, bx1 = r[0], s[0]
            else:
                bx0, bx1 = s[0], r[0]
            if ax1 < bx0 or bx1 < ax0:
                continue
            if p[1] <= q[1]:
                ay0, ay1 = p[1], q[1]
            else:
                ay0, ay1 = q[1], p[1]
            if r[1] <= s[1]:
                by0, by1 = r[1], s[1]
            else:
                by0, by1 = s[1], r[1]
            if ay1 < by0 or by1 < ay0:
                continue
            if a1 - a0 >= b1 - b0:
                m = (a0 + a1) >> 1
                push((a0, m, b0, b1))
                push((m, a1, b0, b1))
            else:
                m = (b0 + b1) >> 1
                push((a0, a1, b0, m))
                push((a0, a1, m, b1))

    def test_pair(self, i: int, j: int) -> None:
        self.n_tests += 1
        r = intersect_segments(self.P[i], self.Q[i], self.P[j], self.Q[j])
        if r.kind:
            for pt in r.points:
                self.add_split(i, pt)
                self.add_split(j, pt)
        self.tick()

    def add_split(self, i: int, pt: tuple[int, int, int]) -> None:
        if pt[2] == 1:
            xy = (pt[0], pt[1])
            if xy == self.P[i] or xy == self.Q[i]:
                return
        lst = self.splits[i]
        if lst is None:
            self.splits[i] = [pt]
        else:
            lst.append(pt)
        self.k += 1
        cap = self.budget.max_size
        if cap is not None and self.n + self.k > cap:
            self.check_size()

    def overlap_point(self, c: int, pt: tuple[int, int]) -> None:
        """Split the segments of chain ``c`` that contain input point ``pt``."""
        P, Q = self.P, self.Q
        x, y = pt
        stack = [(self.chain_lo[c], self.chain_hi[c])]
        while stack:
            s0, s1 = stack.pop()
            p, q = P[s0], Q[s1 - 1]
            if not (min(p[0], q[0]) <= x <= max(p[0], q[0])) or not (
                min(p[1], q[1]) <= y <= max(p[1], q[1])
            ):
                continue
            if s1 - s0 == 1:
                self.n_tests += 1
                if pt != p and pt != q and on_segment(pt, p, q):
                    self.add_split(s0, (x, y, 1))
                continue
            m = (s0 + s1) >> 1
            stack.append((s0, m))
            stack.append((m, s1))

    # ============================================ 3. splitting and merging

    def build_edges(self) -> None:
        vid: dict[tuple[int, int, int], int] = {}
        VX: list[int] = []
        VY: list[int] = []
        VW: list[int] = []
        EU: list[int] = []
        EV: list[int] = []
        EDX: list[int] = []
        EDY: list[int] = []
        ESRC: list[list[EdgeSource]] = []
        eline: list[int] = []  # bit g: the edge lies on a line of operand g
        edge_of: dict[tuple[int, int], int] = {}
        online: dict[int, int] = {}  # vertex -> bit g: on a line of operand g

        def vertex(t: tuple[int, int, int]) -> int:
            v = vid.get(t)
            if v is None:
                v = vid[t] = len(VX)
                VX.append(t[0])
                VY.append(t[1])
                VW.append(t[2])
            return v

        P, Q, stag, splits = self.P, self.Q, self.stag, self.splits
        tick = self.tick
        for i in range(len(P)):
            (x0, y0), (x1, y1) = P[i], Q[i]
            dx, dy = x1 - x0, y1 - y0
            tag = stag[i]
            chain = [vertex((x0, y0, 1))]
            extra = splits[i]
            if extra:

                def key(t: tuple[int, int, int], dx: int = dx, dy: int = dy) -> Any:
                    s = dx * t[0] + dy * t[1]
                    return s if t[2] == 1 else rational(s, t[2])

                for t in sorted(set(extra), key=key):
                    chain.append(vertex(t))
            chain.append(vertex((x1, y1, 1)))
            line_bit = (1 << tag.geom) if tag.ring < 0 else 0
            for k in range(len(chain) - 1):
                u, v = chain[k], chain[k + 1]
                ekey = (u, v) if u < v else (v, u)
                e = edge_of.get(ekey)
                if e is None:
                    e = edge_of[ekey] = len(EU)
                    EU.append(u)
                    EV.append(v)
                    EDX.append(dx)
                    EDY.append(dy)
                    ESRC.append([EdgeSource(tag, True)])
                    eline.append(line_bit)
                else:
                    ESRC[e].append(EdgeSource(tag, EU[e] == u))
                    eline[e] |= line_bit
                if line_bit:
                    online[u] = online.get(u, 0) | line_bit
                    online[v] = online.get(v, 0) | line_bit
                tick()
        # input points: isolated vertices unless they coincide with a vertex
        self.point_flags: dict[int, int] = {}
        for (x, y), flags in self.points.items():
            v = vertex((x, y, 1))
            self.point_flags[v] = self.point_flags.get(v, 0) | flags
            if flags & 12:  # a zero-length line lies here
                online[v] = online.get(v, 0) | (flags >> 2)
        self.VX, self.VY, self.VW = VX, VY, VW
        self.EU, self.EV, self.EDX, self.EDY, self.ESRC = EU, EV, EDX, EDY, ESRC
        self.eline, self.online = eline, online
        del self.splits, self.P, self.Q

    # =============================================== 4. rotation system

    def direction(self, h: int) -> tuple[int, int]:
        """Direction of half-edge ``h`` (a positive multiple of dest - origin), taken
        from its source segment."""
        e = h >> 1
        if h & 1:
            return -self.EDX[e], -self.EDY[e]
        return self.EDX[e], self.EDY[e]

    def link_rotations(self) -> None:
        V, E = len(self.VX), len(self.EU)
        H = 2 * E
        out: list[list[int]] = [[] for _ in range(V)]
        EU, EV = self.EU, self.EV
        for e in range(E):
            out[EU[e]].append(2 * e)
            out[EV[e]].append(2 * e + 1)
        nxt = [-1] * H
        prv = [-1] * H
        direction = self.direction
        dir_key = cmp_to_key(lambda g, h: angle_cmp(direction(g), direction(h)))
        for v in range(V):
            hs = out[v]
            n = len(hs)
            if n >= 3:
                order = _crossing_order(hs, direction) if n == 4 else None
                if order is None:
                    order = sorted(hs, key=dir_key)
                hs = out[v] = order
            for i in range(n):
                g = hs[i - 1]
                nxt[hs[i] ^ 1] = g
                prv[g] = hs[i] ^ 1
            self.tick()
        self.out, self.nxt, self.prv = out, nxt, prv

    # ====================================================================== 5. faces

    def wedge(self, v: int, d: tuple[int, int]) -> int:
        """The outgoing half-edge of ``v`` whose left wedge contains direction ``d``
        (``d`` must differ from every outgoing direction)."""
        direction = self.direction
        below = top = -1
        dbelow = dtop = None
        for g in self.out[v]:
            dg = direction(g)
            c = angle_cmp(dg, d)
            if c == 0:
                raise ArrangementError([f"ray direction {d} runs along an edge at vertex {v}"])
            if dtop is None or angle_cmp(dg, dtop) > 0:
                top, dtop = g, dg
            if c < 0 and (dbelow is None or angle_cmp(dg, dbelow) > 0):
                below, dbelow = g, dg
        return below if below >= 0 else top

    def make_faces(self) -> None:
        V, H = len(self.VX), 2 * len(self.EU)
        nxt, out = self.nxt, self.out
        VX, VY, VW = self.VX, self.VY, self.VW
        # boundary cycles
        cyc = [-1] * H
        cycle_rep: list[int] = []
        for h in range(H):
            if cyc[h] >= 0:
                continue
            c = len(cycle_rep)
            cycle_rep.append(h)
            g = h
            while cyc[g] < 0:
                cyc[g] = c
                g = nxt[g]
            self.tick()
        # connected components (union-find over vertices with edges)
        parent = list(range(V))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        EU, EV = self.EU, self.EV
        for e in range(len(EU)):
            ru, rv = find(EU[e]), find(EV[e])
            if ru != rv:
                parent[ru] = rv
        # lexicographically smallest vertex of each component: always an input vertex
        # (W == 1): an intersection point is interior to a non-vertical source segment,
        # whose left end is further left
        low: dict[int, int] = {}
        for v in range(V):
            if out[v] and VW[v] == 1:
                r = find(v)
                w = low.get(r)
                if w is None or (VX[v], VY[v]) < (VX[w], VY[w]):
                    low[r] = v
        comps = sorted(low.values(), key=lambda v: (VX[v], VY[v]))  # leftmost vertices
        comp_of_root = {find(v): i for i, v in enumerate(comps)}
        if len(comp_of_root) != sum(1 for v in range(V) if out[v] and find(v) == v):
            raise ArrangementError(["a component has no vertex with integer coordinates"])
        # the outer cycle of each component passes through the wedge containing -x at
        # its leftmost vertex; every other cycle bounds a new bounded face
        outer_comp: dict[int, int] = {}  # cycle id -> component index
        for i, v in enumerate(comps):
            outer_comp[cyc[self.wedge(v, (-1, 0))]] = i
        face_of_cycle = [0] * len(cycle_rep)
        face_outer = [-1]
        for c, h in enumerate(cycle_rep):
            if c not in outer_comp:
                face_of_cycle[c] = len(face_outer)
                face_outer.append(h)
        F = len(face_outer)
        # containing face of every component and isolated vertex: ray shooting
        isolated = [v for v in range(V) if not out[v]]
        queries = list(comps) + isolated
        hits = self.shoot_rays(queries) if len(queries) > 1 and len(EU) > 0 else {}
        face_inner: list[list[int]] = [[] for _ in range(F)]
        face_isolated: list[list[int]] = [[] for _ in range(F)]
        comp_face = [0] * len(comps)

        def resolve(h: int, owner: str) -> int:
            if h < 0:
                return 0
            c = cyc[h]
            j = outer_comp.get(c)
            if j is None:
                return face_of_cycle[c]
            if j >= done:
                raise ArrangementError([f"ray from {owner} hit an unresolved component {j}"])
            return comp_face[j]

        done = 0
        for i, v in enumerate(comps):  # in increasing (x, y): dependencies come first
            f = resolve(hits.get(v, -1), f"component {i}")
            comp_face[i] = f
            done = i + 1
        for c, i in outer_comp.items():
            f = comp_face[i]
            face_of_cycle[c] = f
            face_inner[f].append(cycle_rep[c])
        for v in isolated:
            face_isolated[resolve(hits.get(v, -1), f"isolated vertex {v}")].append(v)
        for f in range(F):
            face_inner[f].sort()
        he_face = [face_of_cycle[cyc[h]] for h in range(H)]
        self.he_face, self.face_outer = he_face, face_outer
        self.face_inner, self.face_isolated = face_inner, face_isolated
        self.iso_face = {v: f for f in range(F) for v in face_isolated[f]}
        self.num_faces = F
        self.num_components = len(comps) + len(isolated)

    def shoot_rays(self, queries: list[int]) -> dict[int, int]:
        """For each query vertex (the leftmost vertex of a component, or an isolated
        vertex; both have integer coordinates), the half-edge whose left face contains
        the points just left of it, or -1 for the unbounded face.

        A sweep over ``y`` keeps the edges whose closed y-range contains the sweep line;
        at a query ``p`` every such edge is intersected exactly with the horizontal line
        through ``p``, and the nearest hit strictly left of ``p`` decides.
        """
        VX, VY, VW, EU, EV = self.VX, self.VY, self.VW, self.EU, self.EV

        def ykey(v: int) -> Any:
            w = VW[v]
            return VY[v] if w == 1 else rational(VY[v], w)

        events: list[tuple[Any, int, int]] = []
        yk = [ykey(v) for v in range(len(VX))]
        for e in range(len(EU)):
            ya, yb = yk[EU[e]], yk[EV[e]]
            if yb < ya:
                ya, yb = yb, ya
            events.append((ya, 0, e))
            events.append((yb, 2, e))
        for v in queries:
            events.append((yk[v], 1, v))
        events.sort(key=lambda t: (t[0], t[1]))
        active: dict[int, None] = {}
        hits: dict[int, int] = {}
        for _, kind, x in events:
            if kind == 0:
                active[x] = None
            elif kind == 2:
                del active[x]
            else:
                hits[x] = self.first_hit(x, active)
            self.tick()
        return hits

    def first_hit(self, q: int, active: Iterable[int]) -> int:
        VX, VY, VW, EU, EV = self.VX, self.VY, self.VW, self.EU, self.EV
        px, py = VX[q], VY[q]
        if VW[q] != 1:
            raise ArrangementError([f"query vertex {q} is not an integer point"])
        best = None  # rational x of the nearest hit
        best_vertex = -1  # the hit vertex, or -1 for an edge interior
        best_edge = -1
        tie = False
        for e in active:
            u, v = EU[e], EV[e]
            ax, ay, aw = VX[u], VY[u], VW[u]
            bx, by, bw = VX[v], VY[v], VW[v]
            a_on = ay == py * aw
            b_on = by == py * bw
            if a_on or b_on:
                # the hit, if any, is an endpoint on the line (the nearer one for a
                # horizontal edge)
                cands = []
                if a_on and ax < px * aw:
                    cands.append(u)
                if b_on and bx < px * bw:
                    cands.append(v)
                for w in cands:
                    x = VX[w] if VW[w] == 1 else rational(VX[w], VW[w])
                    if best is None or x > best:
                        best, best_vertex, best_edge, tie = x, w, -1, False
                    elif x == best and best_vertex != w:
                        tie = True
                continue
            # the edge crosses the line in its interior: x* = N / (aw * D)
            d = by * aw - ay * bw
            n = ax * d + (py * aw - ay) * (bx * aw - ax * bw)
            den = aw * d
            if (n - px * den > 0) == (den > 0) or n == px * den:
                continue  # at or right of p
            x = rational(n, den)
            if best is None or x > best:
                best, best_vertex, best_edge, tie = x, -1, e, False
            elif x == best:
                tie = True
        if best is None:
            return -1
        if tie:
            raise ArrangementError([f"ray from vertex {q} hits two edges at one non-vertex point"])
        if best_vertex >= 0:
            return self.wedge(best_vertex, (1, 0))
        e = best_edge
        u, v = EU[e], EV[e]
        o = hp_orient((VX[u], VY[u], VW[u]), (VX[v], VY[v], VW[v]), (px, py, 1))
        if o == 0:
            raise ArrangementError([f"vertex {q} lies on edge {e}"])
        return 2 * e if o > 0 else 2 * e + 1

    # ===================================================================== 6. labels

    def label(self) -> None:
        E, F = len(self.EU), self.num_faces
        he_face, ESRC, orientation = self.he_face, self.ESRC, self.orientation
        # coverage-count jump across each edge, from the right of 2e to its left
        jump = ([0] * E, [0] * E)
        left_in = ([False] * (2 * E), [False] * (2 * E))  # some ring has interior left
        has_ring = ([False] * E, [False] * E)
        for e in range(E):
            ring_elements: set[tuple[int, int]] = set()
            for s in ESRC[e]:
                t = s.tag
                if t.ring < 0:
                    continue
                g = t.geom
                # The rings of a valid polygon meet only at points, so no edge lies twice
                # on the rings of one polygon element. Such an edge (a ring folding back on
                # itself, a hole sharing a segment with its shell) has no defined sides:
                # coverage counting and even-odd location would disagree there.
                if (g, t.element) in ring_elements:
                    raise InvalidInputError(
                        f"edge {e} lies twice on the rings of polygon element {t.element} "
                        f"of {'AB'[g]}: a ring overlaps itself or another ring of the same "
                        f"polygon (the polygonal input is not valid)"
                    )
                ring_elements.add((g, t.element))
                has_ring[g][e] = True
                # interior left of the traversal: CCW shell or CW hole
                if ((orientation[t] > 0) != t.is_hole) == s.forward:
                    jump[g][e] += 1
                    left_in[g][2 * e] = True
                else:
                    jump[g][e] -= 1
                    left_in[g][2 * e + 1] = True
        # breadth-first walk of the face adjacency graph from the unbounded face
        adj: list[list[int]] = [[] for _ in range(F)]
        for e in range(E):
            fl, fr = he_face[2 * e], he_face[2 * e + 1]
            if fl != fr:
                adj[fl].append(2 * e)
                adj[fr].append(2 * e + 1)
        count: tuple[list[int | None], list[int | None]] = ([None] * F, [None] * F)
        ca, cb = count
        ja, jb = jump
        ca[0] = cb[0] = 0
        todo = deque([0])
        while todo:
            f = todo.popleft()
            for h in adj[f]:  # f is the left face of h; cross to its right face
                g = he_face[h ^ 1]
                if ca[g] is None:
                    e = h >> 1
                    sign = 1 if h & 1 == 0 else -1
                    ca[g] = ca[f] - sign * ja[e]
                    cb[g] = cb[f] - sign * jb[e]
                    todo.append(g)
            self.tick()
        problems = []
        for f in range(F):
            if ca[f] is None:
                problems.append(f"face {f} is not reachable from the unbounded face")
        if problems:
            raise ArrangementError(problems)
        for e in range(E):
            fl, fr = he_face[2 * e], he_face[2 * e + 1]
            for g in (GEOM_A, GEOM_B):
                c = count[g]
                if c[fl] - c[fr] != jump[g][e]:
                    raise ArrangementError(
                        [
                            f"edge {e}: coverage of {'AB'[g]} jumps by {c[fl] - c[fr]} "
                            f"between faces {fl} and {fr}, but its rings say {jump[g][e]}"
                        ]
                    )
        # validity of the polygonal coverage (the half-edge-on-ring rule)
        for g in (GEOM_A, GEOM_B):
            c, name, simple = count[g], "AB"[g], self.simple_polygonal[g]
            for f in range(F):
                if c[f] < 0 or (simple and c[f] > 1):
                    raise InvalidInputError(
                        f"face {f} is covered {c[f]} times by the polygons of {name}: "
                        f"the polygonal input is not valid"
                    )
            li, hr = left_in[g], has_ring[g]
            for h in range(2 * E):
                if li[h]:
                    if c[he_face[h]] < 1:
                        raise InvalidInputError(
                            f"half-edge {h} has the interior of a polygon of {name} on its "
                            f"left, but its face is not covered: invalid polygonal input"
                        )
                elif simple and hr[h >> 1] and c[he_face[h]] != 0:
                    raise InvalidInputError(
                        f"half-edge {h} has the exterior of {name} on its left, but its "
                        f"face is covered: invalid polygonal input"
                    )
        # faces
        self.face_loc = ([_I if x > 0 else _E for x in ca], [_I if x > 0 else _E for x in cb])
        fa, fb = self.face_loc
        # edges: polygonal part first, then lines
        eline = self.eline
        edge_loc: tuple[list[int], list[int]] = ([_E] * E, [_E] * E)
        for g, floc in ((GEOM_A, fa), (GEOM_B, fb)):
            el, bit = edge_loc[g], 1 << g
            for e in range(E):
                il = floc[he_face[2 * e]] == _I
                ir = floc[he_face[2 * e + 1]] == _I
                if il and ir:
                    el[e] = _I
                elif il or ir:
                    el[e] = _B
                elif eline[e] & bit:
                    el[e] = _I
        self.edge_loc = edge_loc
        # vertices: incident face sectors, then the mod-2 rule and lines, then points
        V = len(self.VX)
        VX, VY, VW, out, iso = self.VX, self.VY, self.VW, self.out, self.iso_face
        online, pflags = self.online, self.point_flags
        vertex_loc: tuple[list[int], list[int]] = ([_E] * V, [_E] * V)
        for v in range(V):
            hs = out[v]
            sectors = [he_face[h] for h in hs] if hs else [iso[v]]
            for g, floc in ((GEOM_A, fa), (GEOM_B, fb)):
                n_in = 0
                for f in sectors:
                    if floc[f] == _I:
                        n_in += 1
                if n_in:
                    loc = _I if n_in == len(sectors) else _B
                else:
                    cnt = self.endpoints[g].get((VX[v], VY[v]), 0) if VW[v] == 1 else 0
                    if cnt & 1:
                        loc = _B
                    elif cnt or online.get(v, 0) >> g & 1 or pflags.get(v, 0) >> g & 1:
                        loc = _I
                    else:
                        loc = _E
                vertex_loc[g][v] = loc
            self.tick()
        self.vertex_loc = vertex_loc

    # ====================================================================== output

    def emit(self) -> Arrangement:
        sc = self.scale
        arr = Arrangement.new(scale_exp=sc.exp, a=self.a, b=self.b)
        V, E = len(self.VX), len(self.EU)
        if sc.lcm == 1:
            arr.vx, arr.vy, arr.vw = self.VX, self.VY, self.VW
        else:
            vx, vy, vw = [], [], []
            for x, y, w in zip(self.VX, self.VY, self.VW, strict=True):
                x, y, w = hpoint(x, y, w * sc.lcm)
                vx.append(x)
                vy.append(y)
                vw.append(w)
            arr.vx, arr.vy, arr.vw = vx, vy, vw
        arr.vertex_edge = [hs[0] if hs else -1 for hs in self.out]
        arr.vertex_loc_a, arr.vertex_loc_b = self.vertex_loc
        he_origin = [0] * (2 * E)
        he_origin[0::2] = self.EU
        he_origin[1::2] = self.EV
        arr.he_origin = he_origin
        arr.he_twin = [h ^ 1 for h in range(2 * E)]
        arr.he_next, arr.he_prev, arr.he_face = self.nxt, self.prv, self.he_face
        arr.edge_sources = [tuple(s) for s in self.ESRC]
        arr.edge_loc_a, arr.edge_loc_b = self.edge_loc
        arr.face_outer = self.face_outer
        arr.face_inner = self.face_inner
        arr.face_isolated = self.face_isolated
        arr.face_loc_a, arr.face_loc_b = self.face_loc
        arr.ring_orientation = dict(self.orientation)
        if len(arr.vx) != V:
            raise ArrangementError(["vertex arrays out of step"])
        return arr


# ================================================================== rotation helpers


def _crossing_order(hs: list[int], direction: Any) -> list[int] | None:
    """Counter-clockwise order of four outgoing half-edges that form two straight lines
    through the vertex (a proper crossing) from one cross product; None otherwise."""
    h0 = hs[0]
    d0x, d0y = direction(h0)
    partner = -1
    for j in (1, 2, 3):
        djx, djy = direction(hs[j])
        if d0x * djy == d0y * djx and d0x * djx + d0y * djy < 0:
            partner = j
            break
    if partner < 0:
        return None
    k, l = (j for j in (1, 2, 3) if j != partner)
    dkx, dky = direction(hs[k])
    dlx, dly = direction(hs[l])
    if dkx * dly != dky * dlx or dkx * dlx + dky * dly >= 0:
        return None
    c = d0x * dky - d0y * dkx
    if c == 0:
        return None
    if c > 0:
        return [h0, hs[k], hs[partner], hs[l]]
    return [h0, hs[l], hs[partner], hs[k]]
