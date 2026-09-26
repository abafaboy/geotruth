"""Print geotruth, engine and arithmetic backend versions."""

from __future__ import annotations

import argparse
import json
import platform

HELP = "print geotruth, engine and arithmetic backend versions"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="print a JSON object (for provenance records)"
    )


def version_info() -> dict[str, str | None]:
    """Versions recorded with every expected answer and result."""
    from geotruth import ENGINE_VERSION, __version__
    from geotruth.numbers import HAVE_GMPY2, get_backend

    gmpy2_version = None
    if HAVE_GMPY2:
        import gmpy2

        gmpy2_version = gmpy2.version()
    return {
        "geotruth": __version__,
        "engine": ENGINE_VERSION,
        "python": platform.python_version(),
        "gmpy2": gmpy2_version,
        "rational_backend": get_backend(),
    }


def run(args: argparse.Namespace) -> int:
    info = version_info()
    if args.json:
        print(json.dumps(info, sort_keys=True))
    else:
        print(f"geotruth {info['geotruth']} (engine {info['engine']})")
        print(
            f"python {info['python']}, gmpy2 {info['gmpy2'] or 'not installed'}, "
            f"rational backend {info['rational_backend']}"
        )
    return 0
