"""Crosscheck of the scorer's two exact overlay routes (src/geotruth/harness/engine.py):
the engine's ``geotruth.overlay`` against the harness fallback overlay (assembled from the
audited reference arrangement of tests/reference/indep.py). Both must give the same point
set, in both variants, on every valid polygonal core case sampled. (On the full core tier,
2026-09-26: 7952 of 7952 (case, op, variant) answers identical.)"""

from __future__ import annotations

import json
from itertools import islice

import pytest

from geotruth.harness import engine
from geotruth.harness import metrics as M
from geotruth.harness.fallback_overlay import is_polygonal
from geotruth.harness.runner import load_cases, resolve_tier
from geotruth.io import case_from_json

pytestmark = pytest.mark.crosscheck

FAMILIES = ("shared-edge", "hole-contact", "vertex-on-edge", "tiling-contact", "int-grid")
PER_FAMILY = 6


def _sample() -> list:
    out = []
    for path in resolve_tier("core"):
        if path.stem not in FAMILIES:
            continue
        cases = (case_from_json(json.loads(line)) for _, line in load_cases([path]))
        polygonal = (
            c
            for c in cases
            if is_polygonal(c.a)
            and is_polygonal(c.b)
            and engine.validity_answer(c.a)["valid"]
            and engine.validity_answer(c.b)["valid"]
        )
        out += islice(polygonal, PER_FAMILY)
    return out


def _answers(monkeypatch, route: str, a, b) -> dict:
    monkeypatch.setenv("GEOTRUTH_EXACT_BACKEND", route)
    return engine.overlay_answers(a, b)


def test_engine_overlay_matches_the_fallback(monkeypatch):
    if engine._engine_fn("overlay", "overlay") is None:
        pytest.skip("geotruth.overlay is not there yet")
    cases = _sample()
    assert len(cases) >= 20
    compared = 0
    for c in cases:
        ref = _answers(monkeypatch, "reference", c.a, c.b)
        eng = _answers(monkeypatch, "engine", c.a, c.b)
        for op in engine.OVERLAY_OPS:
            for v in engine.VARIANTS:
                r, e = ref[op][v], eng[op][v]
                assert r.status == engine.STATUS_OK, (c.id, op, v, r.reason)
                assert e.status == engine.STATUS_OK, (c.id, op, v, e.reason)
                sr, se = M.shape_of(r.geometry), M.shape_of(e.geometry)
                assert M.even_odd_area(sr.rings() + se.rings()) == 0, (c.id, op, v)
                assert M.hausdorff2(sr, se)[0] == 0, (c.id, op, v)
                compared += 1
    assert compared == len(cases) * 8
