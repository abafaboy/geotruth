"""geotruth: exact ground truth for computational geometry.

The engine decides every geometric question in exact integer or rational arithmetic on
the exact binary values of the input doubles (see ``docs/DESIGN.md``).

Module map (Phase 0 primitives, DESIGN §2.1):

- :mod:`geotruth.numbers` -- doubles as exact rationals, JSON numbers with ``float()``
  semantics, per-case dyadic integer scaling, correctly rounded conversion back.
- :mod:`geotruth.exact` -- integer primitives: orientation, segment intersection
  (homogeneous points), angular order, squared distances, point in ring.
- :mod:`geotruth.geom` -- the typed geometry model (OGC Simple Features types).
- :mod:`geotruth.io` -- typed-JSON and WKT readers/writers, rational side-car,
  canonical ordering.
- :mod:`geotruth.arrangement_api` -- the frozen DCEL interface shared by the arrangement,
  relate and overlay.
- :mod:`geotruth.cli` -- the ``geotruth`` command dispatcher.
"""

__all__ = ["ENGINE_VERSION", "__version__"]

#: Version of the Python package.
__version__ = "0.1.0"

#: Version of the exact engine's *answers*. Bump it whenever any expected answer could
#: change (a semantic fix, a new canonical form). Every expected-answer record cites it,
#: and the golden tests refuse a changed ``expected/`` without a bump.
ENGINE_VERSION = "0.1.0"
