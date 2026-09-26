"""adapters/*/adapter.toml: every adapter has a well-formed manifest (DESIGN.md §4.2)."""

import shlex

import pytest

V1_FIELDS = {
    "valid_a", "valid_b",
    "intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
    "covered_by", "equals",
    "area_inter", "area_union", "area_diff", "area_symdiff",
}
ADAPTER_KEYS = {"name", "language", "contract", "owner", "build", "isolation"}
TARGET_KEYS = {"id", "library", "upstream", "version", "lib", "run", "version_command",
               "toolchain", "options", "fields", "precision", "coordinates"}
DELTA_KINDS = {"relative", "grid", "ulp", "undocumented"}
# contract v2 fields beyond v1 (DESIGN.md §4.1)
V2_EXTRA = {"echo", "relate",
            *(f"predicates.{p}" for p in ("intersects", "disjoint", "touches", "crosses", "overlaps",
                                          "contains", "covers", "within", "covered_by", "equals")),
            *(f"overlay.{op}" for op in ("intersection", "union", "difference", "symdifference"))}
# harness self-checks, not libraries: the engine itself and a deliberately broken copy
CONTROL_IDS = {"engine-control", "mutant"}
# the libraries harness/hunt.sh runs
HUNT_IDS = {"shapely", "geos-main", "geos-release", "jts-main", "jts-release", "clipper2",
            "boost-1.83", "boost-develop", "boost-release", "cgal", "rust-geo", "polyclip-ts",
            "polygon-clipping", "turf", "martinez", "jsts"}


def targets(manifests):
    return [(d, t) for d, m in manifests.items() for t in m["target"]]


@pytest.mark.unit
def test_every_adapter_directory_has_a_manifest(repo, manifests):
    dirs = {p.name for p in (repo / "adapters").iterdir()
            if p.is_dir() and not p.name.startswith((".", "__"))}
    assert dirs == set(manifests)


@pytest.mark.unit
def test_manifest_structure(manifests):
    for d, m in manifests.items():
        assert m["manifest_version"] == 1, d
        assert set(m["adapter"]) >= ADAPTER_KEYS, d
        assert m["adapter"]["name"] == d
        assert m["adapter"]["contract"] in ("v1", "v2")
        assert m["target"], d
        for t in m["target"]:
            assert set(t) >= TARGET_KEYS, (d, t.get("id"))


@pytest.mark.unit
def test_target_ids_are_unique_and_cover_the_hunt(manifests):
    ids = [t["id"] for _, t in targets(manifests)]
    assert len(ids) == len(set(ids))
    assert set(ids) == HUNT_IDS | CONTROL_IDS


@pytest.mark.unit
def test_fields_partition_the_contract_fields(manifests):
    for d, t in targets(manifests):
        f = t["fields"]
        listed = [*f["supported"], *f["derived"], *f["unsupported"]]
        assert len(listed) == len(set(listed)), (d, t["id"], "a field is listed twice")
        # libraries speak both contracts; the harness controls speak v2 only
        expected = (V2_EXTRA | {"valid_a", "valid_b"}) if t["id"] in CONTROL_IDS else V1_FIELDS | V2_EXTRA
        assert set(listed) == expected, (d, t["id"])
        assert all(isinstance(v, str) and v for v in f["derived"].values()), (d, t["id"])


@pytest.mark.unit
def test_precision_and_coordinates(manifests):
    for d, t in targets(manifests):
        p = t["precision"]
        assert p["model"], (d, t["id"])
        assert p["delta"]["kind"] in DELTA_KINDS, (d, t["id"])
        if p["delta"]["kind"] != "undocumented":
            assert p["delta"]["value"] > 0, (d, t["id"])
        if p["delta"]["kind"] == "grid":
            assert p["grid"], (d, t["id"])
        assert isinstance(p["tolerance_predicates"], bool)
        assert not p["tolerance_predicates"] or p["tolerances"], (d, t["id"])
        assert t["coordinates"]["range"], (d, t["id"])
        assert t["coordinates"]["out_of_range"], (d, t["id"])


@pytest.mark.unit
def test_scripts_named_by_manifests_exist(repo, manifests):
    for d, m in manifests.items():
        build = m["adapter"]["build"]
        if build.startswith("adapters/"):
            assert (repo / build).is_file(), (d, build)
        if "build_root" in m["adapter"]:
            assert m["adapter"]["build_root"].startswith("$GEOTRUTH_BUILD_DIR/"), d
        for t in m["target"]:
            for command in (t["run"], t["version_command"]):
                paths = [w for w in shlex.split(command) if "/" in w]
                assert paths, (d, command)
                for w in paths:
                    assert (repo / w).is_file(), (d, t["id"], w)
