#!/usr/bin/env python3
"""The mutant adapter: the engine control with deliberate faults (every 17th predicate
negated, every 17th polygonal overlay output perturbed), which the scorer must catch.

usage: mutant_adapter.py [--timing] [--no-fork] CASES.jsonl|- > RESULTS.jsonl
       mutant_adapter.py --version

See README.md; the implementation is geotruth.harness.control.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from geotruth.harness.control import MutantLibrary  # noqa: E402
from geotruth.harness.pyadapter import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(MutantLibrary(), prog="mutant_adapter.py"))
