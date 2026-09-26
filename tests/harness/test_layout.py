"""The repository layout of Phase 0 (DESIGN.md §8): the bug-hunt harness moved into place,
with build trees under $GEOTRUTH_BUILD_DIR and no host-specific paths."""

import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

# assembled so that this file does not match itself
HOST_PATHS = ["/tmp/" + "claude-0", "/home/" + "user", "gb-" + "build", "gb-" + "hunt"]
SCANNED_DIRS = ["adapters", "harness", "corpus", "tools", "findings", "tests/reference",
                "tests/harness"]
COMPILED_RUN_WRAPPERS = ["geos_main/run.sh", "jts_main/run.sh", "clipper2/run.sh",
                         "boost_geometry/run_1.83.sh", "boost_geometry/run_develop.sh",
                         "rust_geo/run.sh"]
needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def text_files(repo):
    for top in SCANNED_DIRS:
        for path in (repo / top).rglob("*"):
            parts = set(path.relative_to(repo).parts)
            if (path.is_file() and path.suffix not in (".jsonl", ".lock", ".pyc")
                    and not parts & {"node_modules", "target", "__pycache__"}
                    and path.name != "package-lock.json"):
                yield path


def shell_scripts(repo):
    return sorted(p for p in text_files(repo) if p.suffix == ".sh")


@pytest.mark.unit
def test_old_layout_is_gone_and_new_layout_exists(repo):
    for old in ["oracle.py", "compare.py", "hunt.sh", "FORMAT.md", "gen_seed.py", "gen",
                "cases", "oracle_review", "adapters/shapely_adapter.py"]:
        assert not (repo / old).exists(), old
    for new in ["tests/reference/oracle.py", "tests/reference/indep.py",
                "tests/reference/validity.py", "harness/compare.py", "harness/hunt.sh",
                "harness/FORMAT-v1.md", "corpus/generators/seed.py", "corpus/cases/seed.jsonl",
                "corpus/expected-v1/seed.jsonl", "corpus/LICENSE", "corpus/README.md",
                "tools/oracle_review/check.py", "findings/registry.toml"]:
        assert (repo / new).is_file(), new


@pytest.mark.unit
def test_no_host_specific_paths(repo):
    offenders = []
    for path in text_files(repo):
        text = path.read_text(errors="replace")
        offenders += [f"{path.relative_to(repo)}: {p}" for p in HOST_PATHS if p in text]
    assert offenders == []


@pytest.mark.unit
@needs_bash
def test_shell_scripts_parse_and_are_executable(repo):
    for path in shell_scripts(repo):
        subprocess.run(["bash", "-n", str(path)], check=True)
        assert path.stat().st_mode & stat.S_IXUSR, path


@pytest.mark.unit
def test_build_and_run_scripts_use_geotruth_build_dir(repo):
    adapters = repo / "adapters"
    scripts = [*adapters.glob("*/build.sh"), *adapters.glob("*/run*.sh"),
               adapters / "js" / "install.sh"]
    for path in scripts:
        text = path.read_text()
        delegates = re.search(r'exec "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/run_lib.sh"', text)
        assert "GEOTRUTH_BUILD_DIR" in text or delegates, path


@pytest.mark.unit
@needs_bash
@pytest.mark.parametrize("wrapper", COMPILED_RUN_WRAPPERS)
def test_run_wrappers_look_in_geotruth_build_dir(repo, tmp_path, wrapper):
    env = {k: v for k, v in os.environ.items()
           if k not in ("BUILD_ROOT", "JTS_BUILD_DIR", "CARGO_TARGET_DIR")}
    env["GEOTRUTH_BUILD_DIR"] = str(tmp_path)  # empty: nothing is built there
    out = subprocess.run([str(repo / "adapters" / wrapper), str(repo / "corpus/cases/seed.jsonl")],
                         env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 2, out.stderr
    assert "build.sh" in out.stderr
    assert str(tmp_path) in out.stderr or wrapper.startswith("jts_main")


@pytest.mark.unit
def test_hunt_runs_exactly_the_manifest_targets(repo, manifests):
    hunt = (repo / "harness" / "hunt.sh").read_text()
    run_ids = set(re.findall(r"^(?:\w+=\S+ )?run ([\w.-]+) ", hunt, flags=re.M))
    # harness self-checks, run by geotruth run, not the hunt
    controls = {"engine-control", "mutant"}
    assert run_ids == {t["id"] for m in manifests.values() for t in m["target"]} - controls


@pytest.mark.unit
def test_mutation_harness_still_matches_the_vendored_oracle(repo):
    """tools/oracle_review/mutants.py patches the oracle by exact string match."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import mutants\n"
         "src = open(mutants.ORACLE).read()\n"
         "bad = [m[0] for m in mutants.MUTANTS if src.count(m[1]) != 1]\n"
         "print(mutants.ORACLE); assert not bad, bad"],
        cwd=repo / "tools" / "oracle_review", capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith(os.path.join("tests", "reference", "oracle.py"))


@pytest.mark.unit
def test_indep_adapter_runs_from_tools(repo):
    cases = repo / "tools" / "oracle_review" / "findings_cases.jsonl"
    out = subprocess.run([sys.executable, str(repo / "tools/oracle_review/indep_adapter.py"),
                          str(cases)], capture_output=True, text=True, check=True)
    assert len(out.stdout.splitlines()) == len(cases.read_text().splitlines())


@pytest.mark.unit
def test_generators_run_from_their_new_home(repo, tmp_path):
    gen = repo / "corpus" / "generators"
    subprocess.run([sys.executable, str(gen / "run_all.py"), "3", "1", "--families",
                    "vertex-on-edge", "--outdir", str(tmp_path)], check=True, capture_output=True)
    cases = tmp_path / "vertex-on-edge.jsonl"
    assert len(cases.read_text().splitlines()) == 3
    out = subprocess.run([sys.executable, str(gen / "validate.py"), str(cases)],
                         capture_output=True, text=True, check=True)
    assert "vertex-on-edge" in out.stdout + out.stderr
