"""HTML building blocks: escaping, the page template, links and number formatting."""

from __future__ import annotations

import math
import re
from decimal import Context, Decimal
from fractions import Fraction
from html import escape
from pathlib import Path
from string import Template
from typing import Any

SITE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = SITE_DIR / "templates"
STATIC = SITE_DIR / "static"


def esc(s: Any) -> str:
    """Text escaped for HTML content and attribute values."""
    return escape(str(s), quote=True)


def slug(text: str, limit: int = 60) -> str:
    """A lower-case file-name-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-") or "x"


def template(name: str) -> Template:
    return Template((TEMPLATES / name).read_text(encoding="utf-8"))


def static(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def rel(from_page: str, to_page: str) -> str:
    """A relative URL from one site path (``lib/x.html``) to another (``index.html#a``)."""
    target, _, frag = to_page.partition("#")
    src_dir = from_page.split("/")[:-1]
    dst = target.split("/")
    i = 0
    while i < len(src_dir) and i < len(dst) - 1 and src_dir[i] == dst[i]:
        i += 1
    parts = [".."] * (len(src_dir) - i) + dst[i:]
    url = "/".join(parts) if target else ""
    return url + ("#" + frag if frag else "")


def a(href: str, text: str, cls: str = "", **attrs: str) -> str:
    extra = "".join(f' {k.rstrip("_").replace("_", "-")}="{esc(v)}"' for k, v in attrs.items())
    c = f' class="{cls}"' if cls else ""
    return f'<a href="{esc(href)}"{c}{extra}>{text}</a>'


def ext(href: str, text: str) -> str:
    """A link to another site."""
    return f'<a href="{esc(href)}" rel="noopener">{text}</a>'


def code(s: Any) -> str:
    return f"<code>{esc(s)}</code>"


def pre(s: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<pre{c}><code>{esc(s)}</code></pre>"


def dl(items: list[tuple[str, str]], cls: str = "facts") -> str:
    """A definition list; values are HTML."""
    rows = "".join(f"<div><dt>{esc(k)}</dt><dd>{v}</dd></div>" for k, v in items if v)
    return f'<dl class="{cls}">{rows}</dl>'


def badge(status: str, text: str | None = None) -> str:
    return f'<span class="badge b-{esc(slug(status))}">{esc(text or status)}</span>'


def short_sha(s: str, n: int = 9) -> str:
    return s[:n] if re.fullmatch(r"[0-9a-f]{12,40}", s or "") else s


def commit_link(upstream: str, commit: str) -> str:
    """The commit as a link when the upstream is a GitHub repository."""
    if not commit:
        return ""
    if upstream.startswith("https://github.com/"):
        return ext(f"{upstream.rstrip('/')}/commit/{commit}", code(short_sha(commit)))
    return code(commit)


# ============================================================================ numbers


def is_double(q: Fraction) -> bool:
    try:
        f = float(q)
    except OverflowError:
        return False
    return math.isfinite(f) and Fraction(f) == q


def fmt_double(x: float) -> str:
    """Shortest round-trip decimal (``geotruth.io.format_double`` with trim)."""
    if x != x:
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    s = repr(x)
    return s[:-2] if s.endswith(".0") else s


def approx(q: Fraction, digits: int = 17) -> str:
    """A decimal approximation of an exact rational, correctly rounded to ``digits``
    significant digits (display only)."""
    if q == 0:
        return "0"
    ctx = Context(prec=digits)
    d = ctx.divide(Decimal(q.numerator), Decimal(q.denominator))
    mant, _, exp = f"{d:e}".partition("e")
    if "." in mant:
        mant = mant.rstrip("0").rstrip(".")
    e = int(exp)
    if -5 <= e < 16:
        s = format(d, "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    return f"{mant}e{e}"


def rational_text(q: Fraction) -> str:
    return str(q.numerator) if q.denominator == 1 else f"{q.numerator}/{q.denominator}"


def coord_cell(q: Fraction) -> str:
    """HTML for one exact coordinate: a double as its shortest round-trip decimal plus its
    exact binary value (hex float); another rational as ``n/d``, or a 17-digit
    approximation with the full value behind a disclosure when ``n/d`` is long."""
    if is_double(q):
        x = float(q)
        return (
            f'<span class="cv">{esc(fmt_double(x))}</span><span class="hex">{esc(x.hex())}</span>'
        )
    text = rational_text(q)
    if len(text) <= 44:
        return f'<span class="cv">{esc(text)}</span><span class="hex">≈ {esc(approx(q))}</span>'
    return (
        f'<span class="cv">≈ {esc(approx(q))}</span><details class="rat"><summary>exact '
        f"({len(text)} characters)</summary><code>{esc(text)}</code></details>"
    )


def fmt_rational_str(s: str) -> str:
    """HTML for an exact rational given as ``"n/d"`` text (score metrics): the value when
    short, else an approximation with the exact text behind a disclosure."""
    try:
        q = Fraction(s)
    except (ValueError, ZeroDivisionError):
        return esc(s)
    if len(s) <= 32:
        return f"<code>{esc(s)}</code>" + (
            f" (≈ {esc(approx(q, 4))})" if q.denominator != 1 else ""
        )
    return (
        f'≈ {esc(approx(q, 4))} <details class="rat"><summary>exact</summary>'
        f"<code>{esc(s)}</code></details>"
    )


def fmt_float(v: float, sig: int = 3) -> str:
    if v == 0:
        return "0"
    if not math.isfinite(v):
        return str(v)
    if 1e-3 <= abs(v) < 1e6:
        return f"{v:.{sig}g}"
    s = f"{v:.{sig - 1}e}"
    mant, _, exp = s.partition("e")
    mant = mant.rstrip("0").rstrip(".") if "." in mant else mant
    return f"{mant}e{int(exp)}"


def fmt_sqrt_of(q: Fraction, sig: int = 3) -> str:
    """sqrt(q) to a few significant digits (display)."""
    if q <= 0:
        return "0"
    n, d = q.numerator, q.denominator
    # scale so the float conversion neither overflows nor underflows
    e = (n.bit_length() - d.bit_length()) // 2
    scaled = Fraction(n, d) / Fraction(4) ** e if e >= 0 else Fraction(n, d) * Fraction(4) ** (-e)
    m = math.sqrt(float(scaled))
    exp10 = e * math.log10(2) + math.log10(m)
    k = math.floor(exp10)
    mant = 10 ** (exp10 - k)
    if mant >= 9.995:
        mant, k = mant / 10, k + 1
    if -3 <= k < 6:
        return f"{mant * 10.0**k:.{sig}g}"
    return f"{mant:.{sig - 1}f}".rstrip("0").rstrip(".") + f"e{k}"


def render_page(
    *,
    path: str,
    title: str,
    description: str,
    body: str,
    nav_current: str,
    footer: str,
    banner: str = "",
) -> str:
    """A complete HTML document from ``templates/page.html``."""
    root = rel(path, "index.html")[: -len("index.html")]
    nav = []
    for href, label in (
        ("index.html", "Scoreboard"),
        ("findings.html", "Findings"),
        ("methodology.html", "Methodology"),
    ):
        cur = ' aria-current="page"' if href == nav_current else ""
        nav.append(f'<a href="{esc(rel(path, href))}"{cur}>{label}</a>')
    return template("page.html").substitute(
        title=esc(title),
        description=esc(description),
        css=static("site.css"),
        js=static("site.js"),
        head_js=static("theme.js"),
        home=esc(rel(path, "index.html")),
        nav="".join(nav),
        banner=banner,
        body=body,
        footer=footer,
        root=esc(root),
    )
