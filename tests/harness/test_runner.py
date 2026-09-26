"""The runner (src/geotruth/harness/runner.py, `geotruth run`): tier resolution, case
conversion, the watchdog (hangs and crashes restart the adapter), schema validation of
adapter output, the wall budget and the provenance record; end to end with the engine
control adapter and `geotruth score`."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from geotruth import schemas
from geotruth.harness import manifest, runner

pytestmark = pytest.mark.unit
pytest.importorskip("jsonschema")

REPO = Path(__file__).resolve().parents[2]

FAKE = textwrap.dedent(
    """\
    #!{python}
    # A fake contract-v2 adapter whose behaviour is chosen by the case id.
    import json, sys, time
    LIB = "fake@1.0"
    if "--version" in sys.argv:
        print(LIB)
        sys.exit(0)
    for line in open(sys.argv[-1]):
        c = json.loads(line)
        cid = c["id"]
        rec = {{"id": cid, "lib": LIB, "relate": "212101212", "errors": {{}}}}
        if cid.startswith("hang"):
            time.sleep(3600)
        if cid.startswith("crash"):
            sys.exit(3)
        if cid.startswith("noise"):
            print("debug: chatter from the library", flush=True)
        if cid.startswith("bad"):
            rec["relate"] = "XYZ"
        if cid.startswith("wrongid"):
            rec["id"] = "someone-else"
        print(json.dumps(rec), flush=True)
    """
)


def square(x0: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x0, 0], [x0 + 1, 0], [x0 + 1, 1], [x0, 1], [x0, 0]]],
    }


def write_cases(path: Path, ids: list[str]) -> Path:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "id": i,
                    "family": "t",
                    "tags": {},
                    "provenance": {},
                    "a": square(0),
                    "b": square(0.5),
                }
            )
            + "\n"
            for i in ids
        )
    )
    return path


@pytest.fixture
def fake_target(tmp_path, monkeypatch):
    adir = tmp_path / "adapters" / "fake"
    adir.mkdir(parents=True)
    script = adir / "fake_adapter.py"
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    (adir / "adapter.toml").write_text(
        textwrap.dedent(f"""\
        manifest_version = 1
        [adapter]
        name = "fake"
        language = "Python"
        contract = "v2"
        build = "true"
        build_root_override = "FAKE_ROOT"
        [[target]]
        id = "fake"
        library = "Fake"
        version = "1.0"
        lib = "fake@1.0"
        run = "{script}"
        version_command = "{script} --version"
        toolchain = "CPython 3, -O0"
        options = ["an option"]
        [target.fields]
        supported = ["relate"]
        [target.precision]
        model = "none"
        delta = {{ kind = "undocumented" }}
        tolerance_predicates = false
        [target.coordinates]
        range = "any"
        """)
    )
    monkeypatch.setenv("GEOTRUTH_ADAPTERS_DIR", str(tmp_path / "adapters"))
    monkeypatch.setattr(runner, "_LINE_SLACK", 0.5)
    monkeypatch.setattr(runner, "_STARTUP_SLACK", 10.0)
    schemas.validate("adapter", manifest.load_manifests()["fake"])
    return manifest.find_target("fake")


# ============================================================================ tiers, cases


def test_resolve_tier_and_corpus_version(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "cases").mkdir(parents=True)
    f = write_cases(corpus / "cases" / "a.jsonl", ["x1"])
    (corpus / "MANIFEST.json").write_text(
        json.dumps(
            {
                "corpus_version": "9.9.9",
                "tiers": {
                    "core": {"files": {"cases/a.jsonl": {}}},
                    "full": {"files": {"cases/missing.jsonl": {}}},
                },
            }
        )
    )
    assert runner.resolve_tier("core", corpus) == [f]
    with pytest.raises(FileNotFoundError, match="missing locally"):
        runner.resolve_tier("full", corpus)
    with pytest.raises(FileNotFoundError, match="not in"):
        runner.resolve_tier("curated", corpus)
    assert runner.corpus_version([f], corpus) == "9.9.9"
    other = write_cases(tmp_path / "other.jsonl", ["y"])
    assert runner.corpus_version([other], corpus).startswith("sha256:")


def test_repository_tiers_resolve():
    files = runner.resolve_tier("core")
    assert files and all(p.is_file() for p in files)
    assert (
        runner.corpus_version(files)
        == json.loads((REPO / "corpus" / "MANIFEST.json").read_text())["corpus_version"]
    )


def test_load_cases_converts_legacy_operands(tmp_path):
    seed = REPO / "corpus" / "cases" / "seed.jsonl"
    first = seed.read_text().splitlines()[0]
    p = tmp_path / "one.jsonl"
    p.write_text(first + "\n")
    ((cid, line),) = list(runner.load_cases([p]))
    obj = json.loads(line)
    assert cid == json.loads(first)["id"]
    assert obj["a"]["type"] == "Polygon" and obj["b"]["type"] == "Polygon"
    schemas.validate("case", {**obj, "tags": {}, "provenance": {}})


# ============================================================================ running


def test_run_records_watchdog_and_validation(fake_target, tmp_path):
    ids = ["ok-1", "noise-1", "bad-1", "wrongid-1", "hang-1", "ok-2", "crash-1", "ok-3"]
    cases = write_cases(tmp_path / "cases.jsonl", ids)
    opts = runner.RunOptions(
        target=fake_target,
        files=[cases],
        tier="core",
        out_dir=tmp_path / "out",
        op_timeout=0.2,
        budget_s=120,
    )
    rep = runner.run_target(opts)
    recs = [json.loads(x) for x in rep.results_path.read_text().splitlines()]
    assert [r["id"] for r in recs] == ids
    validator = schemas.validator("result")
    for r in recs:
        validator.validate(r)
    by = {r["id"]: r for r in recs}
    assert by["ok-1"]["relate"] == "212101212" and by["noise-1"]["relate"] == "212101212"
    assert by["bad-1"]["errors"]["*"]["message"].startswith("adapter output violates result.v2")
    assert "someone-else" in by["wrongid-1"]["errors"]["*"]["message"]
    assert by["hang-1"]["errors"]["*"]["kind"] == "timeout"
    assert by["crash-1"]["errors"]["*"]["kind"] == "crash"
    assert by["ok-3"]["relate"] == "212101212"
    s = rep.stats
    assert s["cases_run"] == 8 and s["watchdog_timeouts"] == 1 and s["early_exits"] == 1
    assert s["invalid_lines"] == 2 and s["noise_lines"] == 1 and s["id_mismatches"] == 1
    assert s["adapter_restarts"] == 2
    bad = [
        json.loads(x)
        for x in (rep.results_path.parent / "core.invalid.jsonl").read_text().splitlines()
    ]
    assert [b["problem"][:5] for b in bad] == ["noise", "adapt", "id mi"]
    # provenance
    run = json.loads(rep.run_path.read_text())
    schemas.validate("run", run)
    assert run["lib"] == "fake@1.0" and run["tier"] == "core"
    assert run["adapter"]["name"] == "fake" and len(run["adapter"]["manifest_sha256"]) == 64
    assert run["compiler"] == {"name": "CPython", "version": "3", "flags": "-O0"}
    assert run["options"]["manifest"] == ["an option"]
    assert run["options"]["runner"]["op_timeout_s"] == 0.2
    assert run["engine_version"] and run["corpus_version"].startswith("sha256:")


def test_wall_budget_stops_the_run(fake_target, tmp_path):
    cases = write_cases(tmp_path / "cases.jsonl", ["ok-1", "hang-1", "hang-2", "hang-3", "ok-2"])
    opts = runner.RunOptions(
        target=fake_target, files=[cases], out_dir=tmp_path / "out", op_timeout=0.2, budget_s=1.0
    )
    rep = runner.run_target(opts)
    assert rep.stats["budget_exhausted"] is True
    assert rep.stats["cases_run"] < 5
    assert len(rep.results_path.read_text().splitlines()) == rep.stats["cases_run"]


def test_repeated_silent_exits_abort(fake_target, tmp_path):
    cases = write_cases(
        tmp_path / "cases.jsonl", ["crash-1", "crash-2", "crash-3", "crash-4", "ok-1"]
    )
    opts = runner.RunOptions(
        target=fake_target, files=[cases], out_dir=tmp_path / "out", op_timeout=0.2
    )
    rep = runner.run_target(opts)
    assert "aborted" in rep.stats and rep.stats["cases_run"] == 3


def test_prefix_and_timeouts_reach_the_adapter(fake_target):
    env = runner.adapter_env(
        runner.RunOptions(target=fake_target, files=[], prefix="/opt/mybuild", op_timeout=2.5)
    )
    assert env["FAKE_ROOT"] == "/opt/mybuild" and env["GEOTRUTH_PREFIX"] == "/opt/mybuild"
    assert env["GEOTRUTH_OP_TIMEOUT"] == "2.5" and env["GEOS_ADAPTER_TIMEOUT"] == "2.5"


def test_v1_adapters_and_missing_builds_are_refused(fake_target, tmp_path, monkeypatch):
    t = fake_target
    t.adapter["contract"] = "v1"
    with pytest.raises(RuntimeError, match="contract v1"):
        runner.run_target(runner.RunOptions(target=t, files=[]))
    t.adapter["contract"] = "v2"
    t.table["version_command"] = str(tmp_path / "nope.sh")
    with pytest.raises(RuntimeError, match="build it first"):
        runner.check_available(t, dict(os.environ))


# ============================================================================ end to end


def test_engine_control_run_and_score(tmp_path, capsys):
    """`geotruth run` + `geotruth score` with the engine control: every graded record is
    correct (the control must score 100%)."""
    from geotruth.commands import run as run_cmd
    from geotruth.commands import score as score_cmd

    cases = tmp_path / "cases.jsonl"
    rows = [
        {"id": f"c{i}", "family": "t", "tags": {}, "provenance": {}, "a": square(0), "b": square(x)}
        for i, x in enumerate((0.5, 1.0, 2.0, 0.0, 1 / 3))
    ]
    rows.append(json.loads((REPO / "schemas" / "examples" / "case.v2.valid.json").read_text())[0])
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def call(mod, argv):
        p = argparse.ArgumentParser()
        mod.add_arguments(p)
        return mod.run(p.parse_args(argv))

    out = tmp_path / "results"
    assert (
        call(
            run_cmd,
            [
                "--lib",
                "engine-control",
                "--cases",
                str(cases),
                "--out",
                str(out),
                "--timeout",
                "30",
            ],
        )
        == 0
    )
    assert (
        call(
            score_cmd,
            [
                "--lib",
                "engine-control",
                "--tier",
                "cases",
                "--results-dir",
                str(out),
                "--jobs",
                "1",
            ],
        )
        == 0
    )
    summary = json.loads((out / "engine-control" / "cases.summary.json").read_text())
    assert summary["headline_failures"] == 0
    assert summary["cases"] == 6 and summary["verdicts"]["echo"] == {"correct": 1}
    for line in (out / "engine-control" / "cases.score.jsonl").read_text().splitlines():
        r = json.loads(line)
        schemas.validate("score", r)
        assert r["verdict"] == "correct", r
    assert "0 headline failures" in capsys.readouterr().out


def test_commands_are_registered():
    from geotruth import cli

    cmds = cli.discover()
    assert {"run", "score"} <= set(cmds)
    assert cmds["run"].error is None and cmds["score"].error is None
