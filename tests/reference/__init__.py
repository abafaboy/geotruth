"""Vendored exact references from the geometry bug hunt (DESIGN.md §0.2 and §8, Phase 0).

These three modules predate the geotruth engine. They are kept, unchanged apart from their
docstrings and imports, as independent second opinions that the engine is cross-checked
against:

- ``oracle``: polygon/polygon predicates and exact overlay areas (vertical slab
  decomposition, gmpy2 ``mpq``).
- ``indep``: an independent exact implementation written for the oracle review, sharing no
  code or algorithm with ``oracle`` (``fractions.Fraction``, winding numbers, Green's theorem).
- ``validity``: exact GEOS-default validity for any polygonal input, rules R0-R6.

Each file's docstring names the commit it was vendored from. The audit that backs them is in
``tools/oracle_review/``.

They can be used in two ways:

- as a package, with the repository root on ``sys.path``:
  ``from tests.reference import oracle``;
- as scripts or top-level modules, with this directory on ``sys.path``:
  ``python tests/reference/oracle.py CASES.jsonl > ORACLE.jsonl``. The corpus generators
  and the review tools import them this way.
"""
