# Developer shortcuts. CI (.github/workflows/ci.yml) calls the lint and test targets below,
# so `make ci` runs locally what a pull request runs (on one Python version).
#
#   make dev            editable install with the development tools and Shapely
#   make lint           ruff
#   make unit           the fast engine and harness tests (pytest -m unit)
#   make crosscheck-ci  the cross-check subset CI runs (needs Shapely)
#   make fractions-ci   the engine tests on the fractions backend (run it in an
#                       environment without gmpy2, as CI does)
#   make crosscheck     every cross-check (about 10 minutes)
#   make slow           the long-running tests
#   make dist           sdist and wheel in dist/, checked (pip install build twine)
#   make ci             lint + unit + crosscheck-ci

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
PYTEST_ARGS ?= -ra

# The cross-checks CI leaves out to stay small: the large randomized dual-route runs, the
# exhaustive grid and the widest lattice sweeps (make crosscheck runs them all).
CROSSCHECK_CI_DESELECT = \
	--deselect tests/crosscheck/test_relate_dual.py::test_tool_large_run \
	--deselect tests/crosscheck/test_relate_dual.py::test_exhaustive_grid_full \
	--deselect tests/crosscheck/test_relate_dual.py::test_lattice_every_type_pair \
	--deselect tests/crosscheck/test_overlay_crosscheck.py::test_review_families

# Engine tests on the fractions backend. This one test imports gmpy2 directly, so it cannot
# run without it.
FRACTIONS_CI_DESELECT = \
	--deselect tests/unit/test_arrangement.py::test_random_points_against_oracle_point_in

.PHONY: help dev lint unit crosscheck crosscheck-ci fractions-ci slow test-all dist ci clean

help:
	@sed -n '4,14p' Makefile

dev:
	$(PYTHON) -m pip install -e '.[dev,shapely]'

lint:
	$(RUFF) check .

unit:
	$(PYTEST) -m unit $(PYTEST_ARGS)

crosscheck:
	$(PYTEST) -m crosscheck $(PYTEST_ARGS)

crosscheck-ci:
	$(PYTEST) -m crosscheck $(CROSSCHECK_CI_DESELECT) $(PYTEST_ARGS)

fractions-ci:
	@$(PYTHON) -c "import geotruth.numbers as n, sys; \
		sys.exit(0 if n.get_backend() == 'fractions' else \
		'fractions-ci: the rational backend is ' + n.get_backend() + ', not fractions')"
	$(PYTEST) -m unit tests/unit $(FRACTIONS_CI_DESELECT) $(PYTEST_ARGS)

slow:
	$(PYTEST) -m slow $(PYTEST_ARGS)

test-all:
	$(PYTEST) $(PYTEST_ARGS)

dist:
	rm -rf dist
	$(PYTHON) -m build
	$(PYTHON) -m twine check --strict dist/*

ci: lint unit crosscheck-ci

clean:
	rm -rf dist build src/*.egg-info .pytest_cache .ruff_cache
