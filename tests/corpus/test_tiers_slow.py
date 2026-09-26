"""Every core file regenerates byte for byte from the MANIFEST parameters (all families)."""

from __future__ import annotations

import pytest

from conftest import REPO

pytestmark = pytest.mark.slow

CORPUS = REPO / "corpus"


def test_every_core_file_regenerates(tiers):
    p = tiers.load_manifest()["parameters"]
    for name in tiers.FAMILY_NAMES:
        recs, _ = tiers.generate_family(name, p["n_per_family"], p["seed"])
        text = "".join(tiers.dumps(r) + "\n" for r in tiers.select_core(recs, p["core_per_family"]))
        assert text == (CORPUS / "cases" / "core" / f"{name}.jsonl").read_text(), name
