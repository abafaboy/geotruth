"""Run exported XML with the libraries' own test runners (JTS TestRunner, GEOS xmltester).

Both runners are built under ``$GEOTRUTH_BUILD_DIR`` (default ``~/.cache/geotruth``) from
the source trees the adapters already use:

``jts-testrunner/``
    ``modules/tests/src/main/java`` of ``$GEOTRUTH_BUILD_DIR/jts-main/src`` compiled with
    javac against ``jts-main/out/jts-core.jar``, jdom2 and commons-lang3 (fetched into
    ``jts-main/m2`` with Maven if absent). ``classpath.txt`` holds the class path.
``geos-main-testing/build/bin/test_xmltester``
    GEOS from ``$GEOTRUTH_BUILD_DIR/geos-main/src`` configured in a separate build tree
    with ``-DBUILD_TESTING=ON`` and only the ``test_xmltester`` target built (``-j2``).

:func:`build_jts_testrunner` and :func:`build_geos_xmltester` do that (``geotruth export
--build-runners``); :func:`run_jts` and :func:`run_geos` run a file and parse the summary.
JTS runs with ``-Djts.relate=ng`` by default (RelateNG, which supports
GeometryCollections; ``relate="old"`` selects the original RelateOp).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RunnerResult",
    "build_dir",
    "build_geos_xmltester",
    "build_jts_testrunner",
    "geos_xmltester",
    "jts_classpath",
    "run_geos",
    "run_jts",
]

JDOM2 = ("org/jdom/jdom2/2.0.6.1", "jdom2-2.0.6.1.jar", "org.jdom:jdom2:2.0.6.1")
LANG3 = (
    "org/apache/commons/commons-lang3/3.12.0",
    "commons-lang3-3.12.0.jar",
    "org.apache.commons:commons-lang3:3.12.0",
)


def build_dir() -> Path:
    return Path(os.environ.get("GEOTRUTH_BUILD_DIR", Path.home() / ".cache" / "geotruth"))


@dataclass
class RunnerResult:
    runner: str
    tests: int
    passed: int
    failed: int
    exceptions: int
    failures: list[str] = field(default_factory=list)
    output: str = ""

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.exceptions == 0 and self.tests > 0


# ============================================================================ JTS


def jts_classpath(root: Path | None = None) -> str | None:
    """The TestRunner class path, or None when it has not been built."""
    d = (root or build_dir()) / "jts-testrunner"
    cp = d / "classpath.txt"
    if not (d / "classes" / "org" / "locationtech" / "jtstest").is_dir() or not cp.exists():
        return None
    return f"{d / 'classes'}{os.pathsep}{cp.read_text().strip()}"


def build_jts_testrunner(root: Path | None = None) -> str:
    """Compile JTS's TestRunner (modules/tests) against the adapter's jts-core.jar."""
    root = root or build_dir()
    jts = root / "jts-main"
    core = jts / "out" / "jts-core.jar"
    src = jts / "src" / "modules" / "tests" / "src" / "main" / "java"
    if not core.exists() or not src.is_dir():
        raise RuntimeError(f"build JTS first (adapters/jts_main/build.sh): {core} / {src}")
    m2 = jts / "m2"
    jars = []
    for rel, name, coord in (JDOM2, LANG3):
        jar = m2 / rel / name
        if not jar.exists():
            subprocess.run(
                [
                    "mvn",
                    "-q",
                    "-B",
                    "dependency:get",
                    f"-Dartifact={coord}",
                    f"-Dmaven.repo.local={m2}",
                ],
                check=True,
            )
        jars.append(str(jar))
    out = root / "jts-testrunner"
    classes = out / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    classes.mkdir(parents=True)
    sources = sorted(str(p) for p in src.rglob("*.java"))
    (out / "sources.txt").write_text("\n".join(sources) + "\n")
    cp = os.pathsep.join([str(core), *jars])
    subprocess.run(
        [
            "javac",
            "-nowarn",
            "-encoding",
            "UTF-8",
            "--release",
            "8",
            "-cp",
            cp,
            "-d",
            str(classes),
            f"@{out / 'sources.txt'}",
        ],
        check=True,
    )
    (out / "classpath.txt").write_text(cp + "\n")
    return f"{classes}{os.pathsep}{cp}"


_JTS_SUMMARY = re.compile(
    r"(\d+) cases with (\d+) tests\s+--\s+(\d+) passed, (\d+) failed, (\d+) exceptions"
)


def run_jts(
    xml: Path, *, relate: str = "ng", classpath: str | None = None, timeout: float = 600
) -> RunnerResult:
    cp = classpath or jts_classpath()
    if cp is None:
        raise RuntimeError("JTS TestRunner not built (geotruth export --build-runners)")
    cmd = [
        "java",
        f"-Djts.relate={relate}",
        "-cp",
        cp,
        "org.locationtech.jtstest.testrunner.JTSTestRunnerCmd",
        "-verbose",
        str(xml),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    out = proc.stdout + proc.stderr
    m = _JTS_SUMMARY.search(out)
    if m is None:
        raise RuntimeError(f"no JTS TestRunner summary:\n{out[-2000:]}")
    _, tests, passed, failed, exc = (int(x) for x in m.groups())
    fails = [
        ln.strip()
        for ln in out.splitlines()
        if ln.startswith(("Test Failed", "Test Threw Exception"))
    ]
    return RunnerResult(f"jts ({relate})", tests, passed, failed, exc, fails, out)


# ============================================================================ GEOS


def geos_xmltester(root: Path | None = None) -> Path | None:
    exe = (root or build_dir()) / "geos-main-testing" / "build" / "bin" / "test_xmltester"
    return exe if exe.exists() else None


def build_geos_xmltester(root: Path | None = None, jobs: int = 2) -> Path:
    """Configure GEOS main with -DBUILD_TESTING=ON in a separate tree; build the tester."""
    root = root or build_dir()
    src = root / "geos-main" / "src"
    if not (src / "CMakeLists.txt").exists():
        raise RuntimeError(f"no GEOS source in {src} (adapters/geos_main/build.sh fetches it)")
    bld = root / "geos-main-testing" / "build"
    subprocess.run(
        [
            "cmake",
            "-S",
            str(src),
            "-B",
            str(bld),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_TESTING=ON",
        ],
        check=True,
    )
    subprocess.run(
        ["cmake", "--build", str(bld), "--target", "test_xmltester", f"-j{jobs}"], check=True
    )
    exe = geos_xmltester(root)
    assert exe is not None
    return exe


def run_geos(xml: Path, *, exe: Path | None = None, timeout: float = 600) -> RunnerResult:
    exe = exe or geos_xmltester()
    if exe is None:
        raise RuntimeError("GEOS xmltester not built (geotruth export --build-runners)")
    proc = subprocess.run(
        [str(exe), "-v", str(xml)], capture_output=True, text=True, timeout=timeout, check=False
    )
    out = proc.stdout + proc.stderr

    def num(label: str) -> int:
        m = re.search(rf"^{label}:\s+(\d+)", out, re.M)
        if m is None:
            raise RuntimeError(f"no xmltester summary ({label}):\n{out[-2000:]}")
        return int(m.group(1))

    tests, failed, passed = num("Tests"), num("Failed"), num("Succeeded")
    fails = [ln.split("\t")[0].strip() for ln in out.splitlines() if " failed." in ln]
    # an operation that throws counts as failed in the summary and prints "EXCEPTION in"
    exc = sum(1 for ln in out.splitlines() if "EXCEPTION in" in ln)
    return RunnerResult("geos xmltester", tests, passed, failed - exc, exc, fails, out)
