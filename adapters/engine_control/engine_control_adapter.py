#!/usr/bin/env python3
"""The engine control adapter: geotruth's exact engine in adapter contract v2.

usage: engine_control_adapter.py [--timing] [--no-fork] CASES.jsonl|- > RESULTS.jsonl
       engine_control_adapter.py --version

See README.md; the implementation is geotruth.harness.control.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from geotruth.harness.control import ControlLibrary
from geotruth.harness.pyadapter import main

if __name__ == "__main__":
    sys.exit(main(ControlLibrary(), prog="engine_control_adapter.py"))
