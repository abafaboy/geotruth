"""Exact answers for cases.jsonl (and any other JSON-lines file of {id, a, b}).

For each case:
  exact      geotruth.relate.relate(strict=True): DE-9IM from the exact arrangement
  witness    geotruth.relate_witness.relate_witness: the independent witness-point route
  stripped   GEOS (via Shapely) on the same point sets with every EMPTY element removed:
             an empty element contributes no points, so the DE-9IM must not change
  valid      geotruth.validity.is_valid and GEOS isValid on the original operands

Run: PYTHONPATH=<geotruth>/src python3 exact_check.py [cases.jsonl]
"""
import json, sys
import shapely
from shapely import wkt as swkt
from shapely.geometry import GeometryCollection, MultiPolygon, MultiLineString, MultiPoint
from geotruth.io import read_wkt
from geotruth.relate import relate
from geotruth.relate_witness import relate_witness
from geotruth.validity import is_valid

def strip(g):
    if g.is_empty:
        return g
    t = g.geom_type
    if t == "GeometryCollection":
        parts = [strip(p) for p in g.geoms if not p.is_empty]
        return GeometryCollection(parts)
    if t in ("MultiPolygon", "MultiLineString", "MultiPoint"):
        return type(g)([p for p in g.geoms if not p.is_empty])
    return g

path = sys.argv[1] if len(sys.argv) > 1 else "cases.jsonl"
from geotruth.io import geometry_from_json, to_wkt


def wkt_of(c, k):
    """WKT of operand k: the a_wkt/b_wkt field, a WKT string, or a typed JSON geometry."""
    if k + "_wkt" in c:
        return c[k + "_wkt"]
    return c[k] if isinstance(c[k], str) else to_wkt(geometry_from_json(c[k]))

print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string} (for 'stripped' and GEOS isValid)")
for line in open(path):
    c = json.loads(line)
    c["a"], c["b"] = wkt_of(c, "a"), wkt_of(c, "b")
    ga, gb = read_wkt(c["a"]), read_wkt(c["b"])
    exact = relate(ga, gb, strict=True).matrix
    wit = relate_witness(ga, gb).matrix
    sa, sb = swkt.loads(c["a"]), swkt.loads(c["b"])
    stripped = shapely.relate(strip(sa), strip(sb))
    print(f"{c['id']}\n  A = {c['a']}\n  B = {c['b']}")
    print(f"  valid (exact) A={is_valid(ga)} B={is_valid(gb)}; GEOS isValid A={shapely.is_valid(sa)} B={shapely.is_valid(sb)}")
    print(f"  exact {exact}  witness {wit}  GEOS-on-stripped {stripped}  "
          f"{'AGREE' if exact == wit == stripped else 'DISAGREE'}")
