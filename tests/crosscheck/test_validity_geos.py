"""Exact validity (:mod:`geotruth.validity`) against GEOS ``is_valid`` (via Shapely).

Inputs:

- every geometry of ``corpus/cases/seed.jsonl``;
- the oracle-review families (``tools/oracle_review/gen_review.py all 100 1``);
- the hand-written table of ``tests/unit/test_validity.py``;
- ``GEOTRUTH_VALIDITY_N`` (default 20000) random small-integer-lattice geometries of every
  type, valid and invalid (``unit.test_validity_lattice.random_geometry``).

Geometries go to GEOS as WKT with shortest round-trip doubles (checked to round-trip
exactly), so GEOS sees exactly the doubles the engine sees. Every disagreement must be
*explained*, or the test fails:

``unconstructible``
    GEOS refuses to build the geometry (an unclosed ring, a one-point line, holes in an
    empty shell, NaN breaking a ring's closure). The exact answer must then be invalid,
    for a reason that makes the geometry unbuildable.
``geos-arithmetic``
    GEOS's orientation arithmetic (double-double) under- or overflows at extreme
    magnitudes (about ``2**-1000`` or ``2**600``). The explanation is checked exactly:
    the geometry is multiplied by a power of two, which is exact and preserves validity;
    on that rescaled copy GEOS must agree with the engine, and the engine's own answer
    must not change.

When both sides say invalid, the engine's first reason (GEOS precedence and, for area
intersections, GEOS's emulated noding order) must equal GEOS's, and for (ring)
self-intersections GEOS's reported location must be one of the exact defect locations
(within GEOS's rounding of computed crossing points).
"""

from __future__ import annotations

import collections
import math
import os
import random
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")
from shapely.validation import explain_validity  # noqa: E402

from geotruth.geom import Geometry  # noqa: E402
from geotruth.io import geometry_from_json, read_wkt, to_wkt  # noqa: E402
from geotruth.numbers import json_loads  # noqa: E402
from geotruth.validity import ValidityReport, code_of_message, validate  # noqa: E402
from unit.test_validity import CASES  # noqa: E402
from unit.test_validity_lattice import random_geometry  # noqa: E402

pytestmark = pytest.mark.crosscheck

ROOT = Path(__file__).resolve().parents[2]
UNBUILDABLE_REASONS = {
    "ring_not_closed",
    "too_few_points",
    "invalid_coordinate",
    "hole_outside_shell",
}
EXTREME_LOW, EXTREME_HIGH = 2.0**-400, 2.0**400
_LOC = re.compile(r"\[(\S+) (\S+)\]")


def _same_double(a: float, b: float) -> bool:
    return (a == b and math.copysign(1, a) == math.copysign(1, b)) or (a != a and b != b)


def geos_validity(geom: Geometry) -> tuple[bool | None, str | None, str]:
    """GEOS's ``(is_valid, reason code, message)``; ``is_valid`` is None when GEOS
    cannot build the geometry."""
    wkt = to_wkt(geom)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            g = shapely.from_wkt(wkt)
        except shapely.errors.GEOSException as exc:
            return None, None, str(exc)
        ours = [v for c in geom.iter_coords() for v in c]
        theirs = [float(v) for v in shapely.get_coordinates(g).ravel()]
        assert len(ours) == len(theirs) and all(map(_same_double, ours, theirs)), wkt
        msg = explain_validity(g)  # GEOS warns (overflow) at extreme magnitudes
        return bool(g.is_valid), code_of_message(msg), msg


def _rescaled(geom: Geometry) -> tuple[Geometry, int] | None:
    """``geom`` times ``2**k``, with its largest ordinate brought to about ``2**20``;
    None unless the scaling is exact (it round-trips bit for bit)."""
    vals = [abs(v) for v in geom.iter_values() if v != 0 and math.isfinite(v)]
    if not vals:
        return None
    k = 20 - math.frexp(max(vals))[1]
    h = geom.map_coords(lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k)))
    back = h.map_coords(lambda c: (math.ldexp(c[0], -k), math.ldexp(c[1], -k)))
    if not all(map(_same_double, geom.iter_values(), back.iter_values())):
        return None
    return h, k


def _is_extreme(geom: Geometry) -> bool:
    vals = [abs(v) for v in geom.iter_values() if v != 0 and math.isfinite(v)]
    return bool(vals) and (min(vals) < EXTREME_LOW or max(vals) > EXTREME_HIGH)


def _location_matches(report: ValidityReport, message: str) -> bool:
    m = _LOC.search(message)
    if m is None or report.first is None:
        return False
    gx, gy = float(m.group(1)), float(m.group(2))
    for x, y in report.first.location:
        fx, fy = float(x), float(y)
        tol_x = 1e-9 * max(1.0, abs(fx))
        tol_y = 1e-9 * max(1.0, abs(fy))
        if abs(fx - gx) <= tol_x and abs(fy - gy) <= tol_y:
            return True
    return False


class Tally:
    """Counts of every outcome, and the unexplained disagreements."""

    def __init__(self) -> None:
        self.counts: collections.Counter = collections.Counter()
        self.problems: list[str] = []

    def check(self, geom: Geometry, label: str) -> None:
        report = validate(geom)
        valid, code, msg = geos_validity(geom)
        wkt = to_wkt(geom)
        if valid is None:
            if report.valid or not (set(report.reasons) & UNBUILDABLE_REASONS):
                self.problems.append(
                    f"{label}: GEOS cannot build it ({msg}) but engine says "
                    f"{report.to_json()}: {wkt[:300]}"
                )
            else:
                self.counts["unconstructible (engine invalid)"] += 1
            return
        if valid != report.valid or (not valid and code != report.first_reason):
            self._explain(geom, report, valid, code, msg, label)
            return
        self.counts["agree valid" if valid else "agree invalid"] += 1
        if valid:
            return
        self.counts[f"first reason agrees ({report.first_basis})"] += 1
        if code in ("self_intersection", "ring_self_intersection"):
            if _location_matches(report, msg):
                self.counts["area-intersection location agrees"] += 1
            else:
                self.problems.append(
                    f"{label}: location of {code} differs: GEOS {msg}, "
                    f"engine {report.first.describe()}: {wkt[:300]}"
                )

    def _explain(self, geom, report, valid, code, msg, label) -> None:
        wkt = to_wkt(geom)
        what = f"engine {report.valid}/{report.first_reason} vs GEOS {valid}/{code} ({msg})"
        if _is_extreme(geom):
            scaled = _rescaled(geom)
            if scaled is not None:
                h, k = scaled
                r2 = validate(h)
                v2, c2, _ = geos_validity(h)
                if (
                    (r2.valid, r2.reasons) == (report.valid, report.reasons)
                    and v2 == r2.valid
                    and (v2 or c2 == r2.first_reason)
                ):
                    kind = "boolean" if valid != report.valid else "reason"
                    self.counts[f"geos-arithmetic ({kind}; exact after scaling by 2^{k})"] += 1
                    return
        self.problems.append(f"{label}: UNEXPLAINED {what}: {wkt[:300]}")

    def report(self) -> str:
        return "\n".join(f"  {k}: {v}" for k, v in sorted(self.counts.items()))


def _assert_clean(tally: Tally, what: str) -> None:
    print(f"\n{what}\n{tally.report()}")
    assert not tally.problems, "\n".join(tally.problems[:20])


# ------------------------------------------------------------------------ inputs


def test_table_of_unit_cases():
    tally = Tally()
    for wkt, *_ in CASES:
        tally.check(read_wkt(wkt), wkt)
    _assert_clean(tally, "unit table")
    assert tally.counts["agree invalid"] > 20


def test_seed_corpus():
    tally = Tally()
    for line in (ROOT / "corpus" / "cases" / "seed.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        case = json_loads(line)
        for op in ("a", "b"):
            tally.check(geometry_from_json(case[op]), f"{case['id']}/{op}")
    _assert_clean(tally, "corpus/cases/seed.jsonl")
    assert sum(tally.counts.values()) == 2000


@pytest.fixture(scope="module")
def review_cases(tmp_path_factory) -> list[dict]:
    gen = ROOT / "tools" / "oracle_review" / "gen_review.py"
    out = subprocess.run(
        [sys.executable, str(gen), "all", "100", "1"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout
    return [json_loads(line) for line in out.splitlines() if line.strip()]


def test_oracle_review_families(review_cases):
    ref_dir = ROOT / "tests" / "reference"
    if str(ref_dir) not in sys.path:
        sys.path.insert(0, str(ref_dir))
    import validity as reference  # tests/reference/validity.py, as a top-level module

    tally = Tally()
    for case in review_cases:
        for op in ("a", "b"):
            geom = geometry_from_json(case[op])
            tally.check(geom, f"{case['id']}/{op}")
            # the vendored reference (R0-R6) sees the same doubles
            assert reference.valid_geometry(case[op]) == validate(geom).valid, case["id"]
    _assert_clean(tally, "tools/oracle_review families (all 100 1)")
    assert len(review_cases) > 700
    # GEOS is known to fail at the extreme scales; each such case is explained exactly
    assert any(k.startswith("geos-arithmetic") for k in tally.counts)


def test_random_lattice_geometries():
    n = int(os.environ.get("GEOTRUTH_VALIDITY_N", "20000"))
    rng = random.Random(20260926)
    tally = Tally()
    kinds = collections.Counter()
    for i in range(n):
        geom = random_geometry(rng)
        kinds[geom.geom_type] += 1
        tally.check(geom, f"lattice#{i}")
    _assert_clean(tally, f"{n} random lattice geometries: {dict(kinds)}")
    assert tally.counts["agree invalid"] > n // 3 and tally.counts["agree valid"] > n // 5
    assert len(kinds) == 7
