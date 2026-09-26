"""The site built from synthetic score files (``conftest.synthetic_results``): it builds,
every link resolves, the HTML and SVG are well formed, nothing is loaded from elsewhere, and
the pages show the numbers of the score files."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from htmlcheck import check_page, svgs

pytestmark = pytest.mark.unit


def _pages(out: Path) -> dict[str, str]:
    return {
        p.relative_to(out).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(out.rglob("*.html"))
    }


def _failures_by_cap(records: list[dict]) -> Counter:
    """Failures per capability, counted from the score records directly (wrong or error,
    not derived): the scorer's own rule."""
    out: Counter = Counter()
    for r in records:
        if r["verdict"] in ("wrong", "error") and not r.get("derived"):
            out[r["capability"]] += 1
    return out


def _graded_by_cap(records: list[dict]) -> Counter:
    out: Counter = Counter()
    for r in records:
        if r["verdict"] in ("correct", "wrong", "error", "convention"):
            out[r["capability"]] += 1
    return out


def test_builds_every_page(built_site, synthetic_results):
    out, report = built_site
    pages = _pages(out)
    for p in (
        "index.html",
        "findings.html",
        "methodology.html",
        "lib/shapely.html",
        "lib/fakelib.html",
    ):
        assert p in pages, p
    assert (out / "index.json").is_file()
    assert report.libraries == 2
    n_clusters = len(json.loads((out / "index.json").read_text())["clusters"])
    assert report.clusters == n_clusters > 0
    assert len([p for p in pages if p.startswith("cluster/")]) == n_clusters
    assert report.pages == len(pages)
    assert report.missing_cases == 0
    assert report.checks.get("fail", 0) == 0, report.failed_checks
    assert report.checks.get("ok", 0) > 0


def test_html_is_well_formed(built_site):
    out, _ = built_site
    for path, text in _pages(out).items():
        rep = check_page(text)
        assert not rep.errors, (path, rep.errors[:10])


def test_every_link_resolves(built_site):
    out, _ = built_site
    pages = _pages(out)
    ids = {p: check_page(t).ids for p, t in pages.items()}
    checked = 0
    for path, text in pages.items():
        for href in check_page(text).links:
            parts = urlsplit(href)
            if parts.scheme in ("http", "https"):
                assert parts.scheme == "https", (path, href)
                continue
            assert not parts.scheme and not parts.netloc, (path, href)
            dest = (
                (out / Path(path).parent / unquote(parts.path)).resolve()
                if parts.path
                else out / path
            )
            assert dest.is_file(), (path, href)
            assert out.resolve() in dest.resolve().parents or dest.resolve().parent == out.resolve()
            if parts.fragment:
                rel = dest.resolve().relative_to(out.resolve()).as_posix()
                if rel.endswith(".html"):
                    assert parts.fragment in ids[rel], (path, href)
            checked += 1
    assert checked > 50


def test_svgs_are_well_formed_and_finite(built_site):
    out, _ = built_site
    n = 0
    for path, text in _pages(out).items():
        for svg in svgs(text):
            root = ET.fromstring(svg)  # raises on malformed XML
            n += 1
            if "fig" not in (root.get("class") or ""):
                continue  # the logo
            assert root.get("viewBox") == "0 0 400 400", path
            tags = [el.tag.split("}")[-1] for el in root]
            assert tags[:2] == ["title", "desc"], (path, tags[:3])
            assert root.get("role") == "img"
            for el in root.iter():
                for attr in ("d", "x", "y", "cx", "cy", "r", "width", "height"):
                    v = (el.get(attr) or "").lower()
                    assert "nan" not in v and "inf" not in v, (path, attr, v[:80])
    assert n > 10


def test_no_external_resources(built_site):
    out, _ = built_site
    for path, text in _pages(out).items():
        assert "<script src" not in text, path
        assert not re.search(r'<link[^>]+rel="stylesheet"', text), path
        assert "@import" not in text and "url(http" not in text, path
        assert "fonts.googleapis" not in text, path


def test_index_shows_the_score_numbers(built_site, synthetic_results):
    out, _ = built_site
    text = (out / "index.html").read_text(encoding="utf-8")
    names = {
        "relate": "Relate (DE-9IM)",
        "predicates": "Named predicates",
        "validity": "Validity",
        "overlay.intersection": "Intersection",
        "overlay.union": "Union",
    }
    for target, recs in synthetic_results["records"].items():
        fails, graded = _failures_by_cap(recs), _graded_by_cap(recs)
        for cap, name in names.items():
            if not graded[cap]:
                continue
            want = f"{name}: {fails[cap]} of {graded[cap]:,} graded answers fail"
            assert want in text, (target, cap, want)
    # the deliberate faults are visible
    assert "Relate (DE-9IM): 1 of 5 graded answers fail" in text
    assert "Read this first" in text and "not real-world failure rates" in text
    assert "no single ranking" in text.lower()
    assert "2026-09-26" in text


def test_library_page_numbers(built_site, synthetic_results):
    out, _ = built_site
    recs = synthetic_results["records"]["shapely"]
    text = (out / "lib/shapely.html").read_text(encoding="utf-8")
    fails, graded = _failures_by_cap(recs), _graded_by_cap(recs)
    for cap in ("relate", "validity", "overlay.union", "overlay.intersection"):
        anchor = "cap-" + cap.replace(".", "-")
        sec = text[text.index(f'id="{anchor}"') :]
        sec = sec[: sec.index("</section>")]
        assert (
            f'<span class="big">{fails[cap]}</span> failures out of {graded[cap]} graded' in sec
        ), cap
        counts = Counter(r["verdict"] for r in recs if r["capability"] == cap)
        for v, n in counts.items():
            assert f'<td class="n">{n}</td>' in sec, (cap, v, n)
    assert "Precision model" in text and "δ = 1e-08 × M" in text  # from the shapely manifest
    assert "fake@1" in text


def test_index_json_matches_the_scorer(built_site, synthetic_results):
    from geotruth.harness.score import summarize

    out, _ = built_site
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["format"] == "geotruth-site-index" and index["tier"] == "core"
    libs = {lib["target"]: lib for lib in index["libraries"]}
    for target, recs in synthetic_results["records"].items():
        summary = summarize(recs)
        caps = libs[target]["capabilities"]
        for cap, verdicts in summary["verdicts"].items():
            assert caps[cap]["verdicts"] == verdicts, (target, cap)
        for cap, tiers in summary["overlay_tiers"].items():
            assert caps[cap]["tiers"] == tiers, (target, cap)
        site_clusters = {
            c["key"]: c["records"]
            for c in index["clusters"]
            if c["target"] == target and c["key_source"] == "scorer"
        }
        assert site_clusters == summary["clusters"], target
        assert sum(c["failures"] for c in caps.values()) == summary["headline_failures"]
    for c in index["clusters"]:
        assert (out / c["page"]).is_file()


def test_cluster_page_contents(built_site):
    out, _ = built_site
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    by_key = {c["key"]: c for c in index["clusters"]}

    relate = by_key["shapely|touch|relate:BB"]
    text = (out / relate["page"]).read_text(encoding="utf-8")
    assert "the DE-9IM entry BB differs from the exact matrix" in text.replace(
        "The DE-9IM", "the DE-9IM"
    )
    assert "geotruth relate @" in text and "--id touch-1 --dual" in text
    assert "witness-point route" in text and "re-checked" in text
    assert relate["triage"] == {"status": "confirmed", "findings": ["fake-touch-missed"]}
    assert 'class="badge b-confirmed"' in text
    assert "Zoomed to" in text  # the vertex on the edge is far smaller than the case
    assert '<table class="coords">' in text and "0x" in text  # exact coordinates printed

    union = next(c for k, c in by_key.items() if k.startswith("shapely|squares|overlay.union:"))
    text = (out / union["page"]).read_text(encoding="utf-8")
    assert "geotruth overlay @" in text and "union --id squares-1" in text and "--certify" in text
    assert "overlay certificate" in text and "re-checked" in text
    assert "Exact result and library output" in text
    assert union["triage"]["status"] == "unreviewed"  # the by-design entry is for another library

    err = by_key["shapely|line|overlay.intersection:exception"]
    text = (out / err["page"]).read_text(encoding="utf-8")
    assert "TopologyException: boom" in text

    val = by_key["shapely|invalid|validity:valid_a=true"]
    text = (out / val["page"]).read_text(encoding="utf-8")
    assert "reports A valid, but A is invalid" in text.replace("Reports", "reports")
    assert "geotruth valid " in text and "exact defect" in text

    echo = by_key["shapely|squares|echo"]
    text = (out / echo["page"]).read_text(encoding="utf-8")
    assert "2.0000000000000004" in text

    extreme = next(
        c for c in index["clusters"] if c["target"] == "fakelib" and c["family"] == "extreme"
    )
    text = (out / extreme["page"]).read_text(encoding="utf-8")
    assert "e-181" in text  # coordinates near 2^-600 print exactly
    for svg in svgs(text):
        ET.fromstring(svg)


def test_findings_page_lists_registry(built_site):
    out, _ = built_site
    text = (out / "findings.html").read_text(encoding="utf-8")
    for fid in ("fake-touch-missed", "fake-other-library", "fake-lead"):
        assert f'id="f-{fid}"' in text
    idx = text.index('id="leads-h"')
    assert text.index('id="f-fake-lead"') > idx  # the lead is in its own section
    assert "Clusters on this site matched to it" in text


def test_lead_is_not_matched_automatically(built_site):
    out, _ = built_site
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    for c in index["clusters"]:
        assert "fake-lead" not in c["triage"]["findings"]


def test_methodology_page(built_site):
    out, _ = built_site
    text = (out / "methodology.html").read_text(encoding="utf-8")
    for anchor in ("exact", "routes", "certificate", "controls", "scoring", "fairness", "adapters"):
        assert f'id="{anchor}"' in text
    assert "computed-" in text  # which exact answers the scores were graded against
    assert "$" not in text.replace("$GEOTRUTH_BUILD_DIR", "")


def test_deterministic(synthetic_results, tmp_path):
    from gtsite import SiteOptions, build_site

    outs = []
    for name in ("a", "b"):
        out = tmp_path / name
        build_site(
            SiteOptions(
                scores=[synthetic_results["root"]],
                out=out,
                registry=synthetic_results["registry"],
                generated="2026-01-01 00:00 UTC",
                verify=False,
            ),
            log=lambda msg: None,
        )
        outs.append(out)
    fa = sorted(p.relative_to(outs[0]) for p in outs[0].rglob("*") if p.is_file())
    fb = sorted(p.relative_to(outs[1]) for p in outs[1].rglob("*") if p.is_file())
    assert fa == fb
    for rel in fa:
        assert (outs[0] / rel).read_bytes() == (outs[1] / rel).read_bytes(), rel


def test_refuses_a_foreign_output_directory(synthetic_results, tmp_path):
    from gtsite import SiteOptions, build_site

    out = tmp_path / "somewhere"
    out.mkdir()
    (out / "precious.txt").write_text("keep me")
    with pytest.raises(RuntimeError, match="not empty"):
        build_site(SiteOptions(scores=[synthetic_results["root"]], out=out), log=lambda m: None)
    assert (out / "precious.txt").read_text() == "keep me"


def test_rebuild_replaces_a_previous_site(synthetic_results, tmp_path):
    from gtsite import SiteOptions, build_site

    out = tmp_path / "site"
    opts = SiteOptions(scores=[synthetic_results["root"]], out=out, verify=False, max_examples=1)
    build_site(opts, log=lambda m: None)
    (out / "stale.html").write_text("old")
    build_site(opts, log=lambda m: None)
    assert not (out / "stale.html").exists()
    assert (out / "index.html").is_file()


def test_cli(synthetic_results, tmp_path, capsys):
    from geotruth.cli import main

    out = tmp_path / "cli-site"
    status = main(
        [
            "site",
            "--scores",
            str(synthetic_results["root"]),
            "--out",
            str(out),
            "--registry",
            str(synthetic_results["registry"]),
            "--date",
            "2026-09-26",
            "--max-examples",
            "2",
            "--preview",
        ]
    )
    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert "pages in" in captured.out
    text = (out / "index.html").read_text(encoding="utf-8")
    assert "Preview build" in text


def test_cli_errors(tmp_path, capsys):
    from geotruth.cli import main

    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["site", "--scores", str(empty), "--out", str(tmp_path / "o")]) == 2
    assert "no score files" in capsys.readouterr().err
    assert main(["site", "--scores", str(tmp_path / "missing"), "--out", str(tmp_path / "o")]) == 2
