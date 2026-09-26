"""Inline SVG figures of a case in a view window.

The window and the clipping are exact (:mod:`gtsite.exact2d`); each canvas position is
the exact value ``(x - x0) * scale`` rounded once to a float, so a window a few ulps wide at
coordinates of 1e300 draws correctly. Colours come from CSS classes of the page (light and
dark themes); every role also has its own dash pattern and vertex mark, so identity never
rests on colour alone. Vertices near the centre get numbers, and the page lists their exact
coordinates in a table under the figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from html import escape

from gtsite.exact2d import P, Parts, clip_ring, clip_segment, in_box
from gtsite.locus import View

SIZE = 400

#: Role -> legend label; the order is the drawing order.
ROLES = {
    "ghost-a": "A (outline)",
    "ghost-b": "B (outline)",
    "a": "A",
    "b": "B",
    "exact": "exact result",
    "lib": "library output",
}


@dataclass
class Layer:
    parts: Parts
    role: str
    number: bool = True  # give its vertices numbered marks


@dataclass
class Marker:
    """A numbered vertex: its number, the roles it belongs to and its exact point."""

    n: int
    roles: list[str]
    point: P


def _f(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class _Canvas:
    def __init__(self, view: View, size: int = SIZE) -> None:
        self.view = view
        self.size = size
        self.box = view.box
        self.scale = Fraction(size) / (2 * view.half)

    def xy(self, p: P) -> tuple[float, float]:
        x0, _, _, y1 = self.box
        return float((p[0] - x0) * self.scale), float((y1 - p[1]) * self.scale)

    def fxy(self, p: P) -> str:
        x, y = self.xy(p)
        return f"{_f(x)} {_f(y)}"


def _mark(role: str, x: float, y: float, r: float = 2.6) -> str:
    """A vertex mark whose shape depends on the role."""
    if role in ("b", "ghost-b"):
        return (
            f'<rect class="v v-{role}" x="{_f(x - r)}" y="{_f(y - r)}" width="{_f(2 * r)}" '
            f'height="{_f(2 * r)}"/>'
        )
    if role == "exact":
        d = r * 1.35
        return (
            f'<path class="v v-exact" d="M{_f(x)} {_f(y - d)}L{_f(x + d)} {_f(y)}'
            f'L{_f(x)} {_f(y + d)}L{_f(x - d)} {_f(y)}Z"/>'
        )
    if role == "lib":
        d = r * 1.2
        return (
            f'<path class="v v-lib" d="M{_f(x - d)} {_f(y - d)}L{_f(x + d)} {_f(y + d)}'
            f'M{_f(x - d)} {_f(y + d)}L{_f(x + d)} {_f(y - d)}"/>'
        )
    return f'<circle class="v v-{role}" cx="{_f(x)}" cy="{_f(y)}" r="{_f(r)}"/>'


def _nice_length(width: float) -> float:
    """A 1, 2 or 5 x 10^k length close to a quarter of the width."""
    target = width / 4
    if not (target > 0 and math.isfinite(target)):
        return 0.0
    k = math.floor(math.log10(target))
    best = 10.0**k
    for m in (1, 2, 5, 10):
        v = m * 10.0**k
        if v <= target * 1.25:
            best = v
    return best


def _fmt_len(v: float) -> str:
    if v == 0:
        return "0"
    if 1e-3 <= abs(v) < 1e5:
        return f"{v:g}"
    return f"{v:.0e}".replace("e-0", "e-").replace("e+0", "e").replace("e+", "e")


def render(
    view: View,
    layers: list[Layer],
    *,
    uid: str,
    title: str,
    desc: str,
    max_numbers: int = 12,
    inset: View | None = None,
    size: int = SIZE,
) -> tuple[str, list[Marker]]:
    """An ``<svg>`` element (well-formed XML) of the layers in the view, and the numbered
    markers it shows. ``inset`` marks another (smaller) window on this one."""
    cv = _Canvas(view, size)
    box = cv.box
    fills: list[str] = []
    edges: list[str] = []
    points: list[str] = []
    candidates: dict[P, list[str]] = {}

    for layer in layers:
        role = layer.role
        parts = layer.parts
        for poly in parts.polygons:
            d = []
            for ring in poly:
                clipped = clip_ring(ring, box)
                if len(clipped) >= 3:
                    d.append("M" + "L".join(cv.fxy(p) for p in clipped) + "Z")
            if d:
                fills.append(f'<path class="fill fill-{role}" d="{"".join(d)}"/>')
        segs = []
        for ln in parts.lines:
            segs += [(ln[i], ln[i + 1]) for i in range(len(ln) - 1)]
        line_segs = len(segs)
        for poly in parts.polygons:
            for ring in poly:
                segs += [(ring[i], ring[i + 1]) for i in range(len(ring) - 1)]
        d_edge, d_line = [], []
        for i, (a, b) in enumerate(segs):
            if a == b:
                continue
            c = clip_segment(a, b, box)
            if c is None:
                continue
            (d_line if i < line_segs else d_edge).append(f"M{cv.fxy(c[0])}L{cv.fxy(c[1])}")
        if d_edge:
            edges.append(f'<path class="edge edge-{role}" d="{"".join(d_edge)}"/>')
        if d_line:
            edges.append(f'<path class="edge line line-{role}" d="{"".join(d_line)}"/>')
        for p in parts.points:
            if in_box(p, box):
                x, y = cv.xy(p)
                points.append(_mark(role, x, y, 4.2))
        if layer.number:
            for v in parts.vertices():
                if in_box(v, box):
                    roles = candidates.setdefault(v, [])
                    if role not in roles:
                        roles.append(role)

    marks: list[str] = []
    for v, roles in candidates.items():
        x, y = cv.xy(v)
        marks.append(_mark(roles[0], x, y))

    def dist_c(p: P) -> Fraction:
        return (p[0] - view.cx) ** 2 + (p[1] - view.cy) ** 2

    ordered = sorted(candidates.items(), key=lambda kv: (dist_c(kv[0]), kv[0]))
    markers = [Marker(i + 1, roles, p) for i, (p, roles) in enumerate(ordered[:max_numbers])]
    labels = []
    placed: list[tuple[float, float]] = []
    for m in markers:
        x, y = cv.xy(m.point)
        lx, ly = x + 6, y - 6
        for _ in range(4):  # nudge labels that would sit on top of each other
            if all(abs(lx - px) > 16 or abs(ly - py) > 11 for px, py in placed):
                break
            ly += 12
        placed.append((lx, ly))
        labels.append(f'<text class="num" x="{_f(lx)}" y="{_f(ly)}">{m.n}</text>')

    focus = []
    for p in view.focus:
        if in_box(p, box):
            x, y = cv.xy(p)
            focus.append(f'<circle class="focus" cx="{_f(x)}" cy="{_f(y)}" r="11"/>')

    extra = []
    if inset is not None:
        ib = inset.box
        (ax, ay), (bx, by) = cv.xy((ib[0], ib[3])), cv.xy((ib[2], ib[1]))
        w = bx - ax
        if w >= 10:
            extra.append(
                f'<rect class="inset" x="{_f(ax)}" y="{_f(ay)}" width="{_f(w)}" '
                f'height="{_f(by - ay)}"/>'
            )
        else:
            cx, cy = cv.xy((inset.cx, inset.cy))
            extra.append(f'<circle class="inset" cx="{_f(cx)}" cy="{_f(cy)}" r="14"/>')
            extra.append(
                f'<path class="inset" d="M{_f(cx - 22)} {_f(cy)}H{_f(cx - 14)}'
                f"M{_f(cx + 14)} {_f(cy)}H{_f(cx + 22)}M{_f(cx)} {_f(cy - 22)}V{_f(cy - 14)}"
                f'M{_f(cx)} {_f(cy + 14)}V{_f(cy + 22)}"/>'
            )

    width = float(2 * view.half)
    bar = _nice_length(width)
    scale_bar = ""
    if bar > 0:
        px = bar / width * size
        y = size - 14
        scale_bar = (
            f'<g class="scale"><path d="M12 {y}h{_f(px)}M12 {y - 4}v8M{_f(12 + px)} {y - 4}v8"/>'
            f'<text x="12" y="{y - 7}">{escape(_fmt_len(bar))}</text></g>'
        )

    tid, did = f"{uid}-t", f"{uid}-d"
    body = "".join(fills + edges + points + marks + focus + extra + labels)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="fig" viewBox="0 0 {size} {size}" '
        f'role="img" aria-labelledby="{tid} {did}">'
        f'<title id="{tid}">{escape(title)}</title><desc id="{did}">{escape(desc)}</desc>'
        f'<rect class="frame" x="0.5" y="0.5" width="{size - 1}" height="{size - 1}"/>'
        f"{body}{scale_bar}</svg>"
    )
    return svg, markers
