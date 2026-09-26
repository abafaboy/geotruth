"""Exports of corpus cases to each library's own test format (DESIGN §5.6).

========== ============================================================================
format     output
========== ============================================================================
jts-xml    JTS TestRunner / GEOS xmltester ``<run>`` XML (:mod:`.jts_xml`)
boost      Boost.Geometry ``overlay_cases.hpp`` definitions and test lines (:mod:`.boost`)
clipper2   Clipper2 ``Tests/Polygons.txt`` blocks, integer-scaled (:mod:`.clipper2`)
geo-rust   georust/geo ``#[test]`` functions with ``wkt!`` (:mod:`.geo_rust`)
pytest     a pytest module for Shapely/GEOS (:mod:`.pytest_shapely`)
========== ============================================================================

Every expected value is the exact answer (:mod:`.answers`); operands are written with
shortest round-trip doubles, so each library reads exactly the case's doubles. Overlay
expectations are exported as relate and area checks.

    from geotruth.export import export_records
    files = export_records(records, "jts-xml")      # list of ExportFile
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from geotruth.export.common import ExportCase, ExportFile, prepare

__all__ = ["EXTENSIONS", "FORMATS", "ExportCase", "ExportFile", "export_records", "prepare"]


def _jts(cases: list[ExportCase], **kw: Any) -> list[ExportFile]:
    from geotruth.export import jts_xml

    return jts_xml.export(cases, **kw)


def _boost(cases: list[ExportCase], **kw: Any) -> list[ExportFile]:
    from geotruth.export import boost

    kw.pop("rel", None)
    return boost.export(cases, **kw)


def _clipper2(cases: list[ExportCase], **kw: Any) -> list[ExportFile]:
    from geotruth.export import clipper2

    kw.pop("rel", None)
    return clipper2.export(cases, **kw)


def _geo(cases: list[ExportCase], **kw: Any) -> list[ExportFile]:
    from geotruth.export import geo_rust

    return geo_rust.export(cases, **kw)


def _pytest(cases: list[ExportCase], **kw: Any) -> list[ExportFile]:
    from geotruth.export import pytest_shapely

    return pytest_shapely.export(cases, **kw)


#: Format name -> exporter(cases, rel=..., comment=...) -> list of files.
FORMATS: dict[str, Callable[..., list[ExportFile]]] = {
    "jts-xml": _jts,
    "boost": _boost,
    "clipper2": _clipper2,
    "geo-rust": _geo,
    "pytest": _pytest,
}
#: Default file extension per format.
EXTENSIONS = {
    "jts-xml": ".xml",
    "boost": ".hpp",
    "clipper2": ".txt",
    "geo-rust": ".rs",
    "pytest": ".py",
}


def export_records(records: list[dict], fmt: str, **kw: Any) -> list[ExportFile]:
    """Export case records (v2 or FORMAT-v1) to ``fmt``."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
    return FORMATS[fmt](prepare(records), **kw)
