"""findings/registry.toml: one well-formed entry per finding directory (DESIGN.md §5.4)."""

import pytest

STATUSES = {"unreviewed", "confirmed", "by-design", "reported", "fixed"}
KEYS = {"id", "library", "lib", "signature", "status", "status_date", "links",
        "upstream_issue", "evidence"}


@pytest.fixture(scope="module")
def registry(repo, toml):
    with open(repo / "findings" / "registry.toml", "rb") as f:
        return toml.load(f)


@pytest.mark.unit
def test_one_entry_per_finding_directory(repo, registry):
    dirs = sorted(p.name for p in (repo / "findings").iterdir() if p.is_dir())
    ids = [f["id"] for f in registry["finding"]]
    assert sorted(ids) == dirs
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_entries_are_well_formed(repo, registry, manifests):
    target_ids = {t["id"] for m in manifests.values() for t in m["target"]}
    assert registry["registry_version"] == 1
    for f in registry["finding"]:
        assert set(f) >= KEYS, f["id"]
        assert f["status"] in STATUSES, f["id"]
        assert f["library"] in target_ids, f["id"]
        assert f["signature"], f["id"]
        assert all(link.startswith("https://") for link in f["links"]), f["id"]
        if f["status"] in ("reported", "fixed"):
            assert f["upstream_issue"].startswith("https://"), f["id"]
        if f["status"] == "fixed":
            assert f.get("fixed_in"), f["id"]
        for key in ("cases", "repro", "evidence"):
            if key in f:
                assert f[key].startswith(f"findings/{f['id']}/"), (f["id"], key)
                assert (repo / f[key]).is_file(), (f["id"], key)
