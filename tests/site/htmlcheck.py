"""Basic HTML checks for the generated site (no external validator needed).

:func:`check_page` parses one page with the standard library's HTML parser and reports:
structure (doctype, ``lang``, ``<title>``, ``charset``, ``viewport``), balanced tags,
block elements inside ``<p>``, nested links, duplicate ids, ``aria-labelledby`` targets,
``scope`` values, and anything that would load a resource from elsewhere. It also returns
the links and ids so the caller can resolve links across pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
    "track", "wbr",
}  # fmt: skip
BLOCK_IN_P = {
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "main", "nav", "ol", "p", "pre", "section", "table", "ul",
}  # fmt: skip
SCOPES = {"row", "col", "rowgroup", "colgroup"}


@dataclass
class PageReport:
    errors: list[str] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)
    links: list[str] = field(default_factory=list)
    title: str = ""
    lang: str = ""


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.r = PageReport()
        self.stack: list[str] = []
        self.labelledby: list[str] = []
        self.in_title = False
        self.charset = False
        self.viewport = False
        self.doctype = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower() == "doctype html":
            self.doctype = True

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if "id" in a and a["id"] is not None:
            if a["id"] in self.r.ids:
                self.r.errors.append(f"duplicate id {a['id']!r}")
            self.r.ids.add(a["id"])
        if tag == "a":
            href = a.get("href")
            if href is None:
                self.r.errors.append("<a> without href")
            else:
                self.r.links.append(href)
        if "src" in a:
            self.r.errors.append(f"<{tag} src=...>: the site must not load resources")
        if tag == "link":
            href = a.get("href") or ""
            if not href.startswith("data:"):
                self.r.errors.append(f"<link href={href!r}>: only data: URIs are allowed")
        if tag == "script" and "src" in a:
            self.r.errors.append("external script")
        if tag == "html":
            self.r.lang = a.get("lang") or ""
        if tag == "meta":
            if "charset" in a:
                self.charset = True
            if a.get("name") == "viewport":
                self.viewport = True
        if tag in ("th", "td") and "scope" in a and a["scope"] not in SCOPES:
            self.r.errors.append(f"bad scope {a['scope']!r}")
        if a.get("aria-labelledby"):
            self.labelledby += (a["aria-labelledby"] or "").split()
        style = a.get("style") or ""
        if "url(" in style:
            self.r.errors.append("style with url(): the site must not load resources")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._attrs(tag, attrs)
        if tag in BLOCK_IN_P and "p" in self.stack and "svg" not in self.stack:
            self.r.errors.append(f"<{tag}> inside <p>")
        if tag == "a" and "a" in self.stack:
            self.r.errors.append("nested <a>")
        if tag == "title" and "svg" not in self.stack:
            self.in_title = True
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._attrs(tag, attrs)
        if "svg" not in self.stack and tag not in VOID:
            self.r.errors.append(f"self-closing <{tag}/> outside SVG")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack:
            self.r.errors.append(f"</{tag}> without an open tag")
            return
        if self.stack[-1] != tag:
            self.r.errors.append(f"</{tag}> closes <{self.stack[-1]}> (open: {self.stack[-4:]})")
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                self.stack.pop()
            return
        self.stack.pop()
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.r.title += data


def check_page(text: str) -> PageReport:
    c = _Checker()
    c.feed(text)
    c.close()
    r = c.r
    if not c.doctype:
        r.errors.append("no <!doctype html>")
    if r.lang != "en":
        r.errors.append("<html> without lang")
    if not r.title.strip():
        r.errors.append("empty <title>")
    if not c.charset:
        r.errors.append("no <meta charset>")
    if not c.viewport:
        r.errors.append("no viewport meta")
    if c.stack:
        r.errors.append(f"unclosed tags: {c.stack}")
    for ref in c.labelledby:
        if ref not in r.ids:
            r.errors.append(f"aria-labelledby names a missing id {ref!r}")
    return r


SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL)


def svgs(text: str) -> list[str]:
    return SVG_RE.findall(text)
