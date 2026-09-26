"""Export crosscheck_relate sources as a TSV with exact answers: python3 xsweep.py NAME
(lattice 4000 seed 11, dense 1500 seed 12, adversarial 3000 seed 13, exhaustive stride 3000);
keeps GEOS-eligible pairs without EMPTY elements (the unpatched batch runner does not fork)."""
import sys, importlib.util
from multiprocessing import Pool
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path[:0] = [GEOTRUTH_ROOT + "/src", GEOTRUTH_ROOT + "/tests", GEOTRUTH_ROOT + "/tests/reference"]
spec = importlib.util.spec_from_file_location("crosscheck_relate", GEOTRUTH_ROOT + "/tools/crosscheck_relate.py")
X = importlib.util.module_from_spec(spec); sys.modules["crosscheck_relate"] = X; spec.loader.exec_module(X)
from geotruth.io import to_wkt
from geotruth.relate import relate

def has_empty(g):
    return g.is_empty or any(e.is_empty for e in g.elements())

def ex(pair):
    a, b = pair
    try:
        return relate(a, b, strict=True).matrix
    except Exception as e:
        return "ENGINE:" + type(e).__name__

if __name__ == "__main__":
    name = sys.argv[1]
    cases = [*X.lattice_cases(4000, 11), *X.dense_cases(1500, 12), *X.adversarial_cases(3000, 13), *X.exhaustive_cases(3000)]
    keep = [(c.a, c.b) for c in cases if X.geos_eligible(c.a, c.b) and not has_empty(c.a) and not has_empty(c.b)]
    with Pool(2) as p:
        res = p.map(ex, keep, chunksize=25)
    with open(f"{name}.tsv", "w") as f, open(f"{name}.exact", "w") as g:
        for (a, b), m in zip(keep, res):
            f.write(f"{to_wkt(a)}\t{to_wkt(b)}\n"); g.write(m + "\n")
    print(len(cases), len(keep), sum(1 for m in res if m.startswith("ENGINE")))
