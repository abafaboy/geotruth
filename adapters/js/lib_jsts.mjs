// JSTS (the JavaScript port of JTS; 2.12.1 ports JTS 1.17: RelateOp and the classic
// OverlayOp, no RelateNG or OverlayNG). Geometries are built with the default
// GeometryFactory (floating precision); results are written back by this adapter.
//
//   relate            Geometry.relate(other) -> IntersectionMatrix (RelateOp)
//   predicates.<name> Geometry.intersects / disjoint / touches / crosses / overlaps / contains /
//                     covers / within / coveredBy / equalsTopo (RelateOp); GeometryCollection
//                     operands are unsupported, as in JTS
//   valid_a, valid_b  IsValidOp.isValid
//   overlay.<op>      OverlayOp.intersection / UnionOp.union (Geometry.union) /
//                     OverlayOp.difference / OverlayOp.symDifference
// GeometryCollection operands that RelateOp or OverlayOp reject (IllegalArgumentException)
// are "unsupported". v1 (legacy lines): validity, the nine v1 predicates and the four areas.
import GeometryFactory from 'jsts/org/locationtech/jts/geom/GeometryFactory.js';
import Coordinate from 'jsts/org/locationtech/jts/geom/Coordinate.js';
import 'jsts/org/locationtech/jts/monkey.js';
import OverlayOp from 'jsts/org/locationtech/jts/operation/overlay/OverlayOp.js';
import IsValidOp from 'jsts/org/locationtech/jts/operation/valid/IsValidOp.js';
import { areaOf, pkgVersion, typedOf, Unsupported } from './common.mjs';

export const LIB = `jsts@${pkgVersion('jsts')}`;
const gf = new GeometryFactory();

const C = (p) => {
  if (!Array.isArray(p) || p.length < 2) throw new TypeError('a position needs at least 2 numbers');
  return new Coordinate(p[0], p[1]);
};
const point = (p) => (p.length === 0 ? gf.createPoint() : gf.createPoint(C(p)));
const polygon = (rings) => (rings.length === 0 ? gf.createPolygon()
  : gf.createPolygon(gf.createLinearRing(rings[0].map(C)), rings.slice(1).map((r) => gf.createLinearRing(r.map(C)))));

function build(g) {
  switch (g.type) {
    case 'Point': return point(g.coordinates);
    case 'LineString': return gf.createLineString(g.coordinates.map(C));
    case 'Polygon': return polygon(g.coordinates);
    case 'MultiPoint': return gf.createMultiPoint(g.coordinates.map(point));
    case 'MultiLineString': return gf.createMultiLineString(g.coordinates.map((l) => gf.createLineString(l.map(C))));
    case 'MultiPolygon': return gf.createMultiPolygon(g.coordinates.map(polygon));
    case 'GeometryCollection': return gf.createGeometryCollection(g.geometries.map(build));
    default: throw new TypeError(`unknown geometry type ${JSON.stringify(g.type)}`);
  }
}

const xy = (c) => [c.x, c.y];
function typed(g) {
  const t = g.getGeometryType();
  switch (t) {
    case 'Point': return { type: 'Point', coordinates: g.isEmpty() ? [] : xy(g.getCoordinate()) };
    case 'LineString': case 'LinearRing': return { type: 'LineString', coordinates: g.getCoordinates().map(xy) };
    case 'Polygon': return { type: 'Polygon', coordinates: rings(g) };
    case 'MultiPoint': case 'MultiLineString': case 'MultiPolygon': {
      const parts = [];
      for (let i = 0; i < g.getNumGeometries(); i++) parts.push(typed(g.getGeometryN(i)).coordinates);
      return { type: t, coordinates: parts };
    }
    default: {
      const parts = [];
      for (let i = 0; i < g.getNumGeometries(); i++) parts.push(typed(g.getGeometryN(i)));
      return { type: 'GeometryCollection', geometries: parts };
    }
  }
}
function rings(p) {
  if (p.isEmpty()) return [];
  const out = [p.getExteriorRing().getCoordinates().map(xy)];
  for (let i = 0; i < p.getNumInteriorRing(); i++) out.push(p.getInteriorRingN(i).getCoordinates().map(xy));
  return out;
}

// Both operands of a case, built once per case (per worker).
const cache = new WeakMap();
function operands(c) {
  let v = cache.get(c);
  if (!v) {
    v = {};
    for (const k of ['a', 'b']) {
      try { v[k] = build(typedOf(c[k])); } catch (e) { v[k + 'Error'] = e; }
    }
    cache.set(c, v);
  }
  return v;
}
function need(c, ...keys) {
  const v = operands(c);
  for (const k of keys) {
    if (v[k + 'Error']) {
      const e = v[k + 'Error'];
      throw new Error(`building ${k.toUpperCase()}: ${e && e.name ? e.name : 'Error'}: ${e && e.message ? e.message : e}`);
    }
  }
  return v;
}
const isGC = (g) => g.getGeometryType() === 'GeometryCollection';
// RelateOp does not support GeometryCollection arguments (JTS checks and throws; JSTS does
// not check, and answers with a GeometryGraph that does not implement the GC semantics).
function relateOp(fn) {
  return (c) => {
    const { a, b } = need(c, 'a', 'b');
    if (isGC(a) || isGC(b)) throw new Unsupported('RelateOp does not support GeometryCollection arguments');
    return fn(a, b);
  };
}
function binary(fn) {
  return (c) => {
    const { a, b } = need(c, 'a', 'b');
    try {
      return fn(a, b);
    } catch (e) {
      if ((isGC(a) || isGC(b)) && /GeometryCollection|IllegalArgument/i.test(`${e && e.name} ${e && e.message}`)) throw new Unsupported(String(e.message));
      throw e;
    }
  };
}

export const OPS_V2 = {
  echo: (c) => { const { a, b } = need(c, 'a', 'b'); return { a: typed(a), b: typed(b) }; },
  relate: relateOp((a, b) => a.relate(b).toString()),
  'predicates.intersects': relateOp((a, b) => a.intersects(b)),
  'predicates.disjoint': relateOp((a, b) => a.disjoint(b)),
  'predicates.touches': relateOp((a, b) => a.touches(b)),
  'predicates.crosses': relateOp((a, b) => a.crosses(b)),
  'predicates.overlaps': relateOp((a, b) => a.overlaps(b)),
  'predicates.contains': relateOp((a, b) => a.contains(b)),
  'predicates.covers': relateOp((a, b) => a.covers(b)),
  'predicates.within': relateOp((a, b) => a.within(b)),
  'predicates.covered_by': relateOp((a, b) => a.coveredBy(b)),
  'predicates.equals': relateOp((a, b) => a.equalsTopo(b)),
  valid_a: (c) => IsValidOp.isValid(need(c, 'a').a),
  valid_b: (c) => IsValidOp.isValid(need(c, 'b').b),
  'overlay.intersection': binary((a, b) => typed(OverlayOp.intersection(a, b))),
  'overlay.union': binary((a, b) => typed(a.union(b))),
  'overlay.difference': binary((a, b) => typed(OverlayOp.difference(a, b))),
  'overlay.symdifference': binary((a, b) => typed(OverlayOp.symDifference(a, b))),
};

// Contract v1 (legacy lines): the same calls on the v1 fields.
const v1 = (key) => OPS_V2[key];
export const OPS = [
  ['valid_a', v1('valid_a')],
  ['valid_b', v1('valid_b')],
  ['intersects', v1('predicates.intersects')],
  ['disjoint', v1('predicates.disjoint')],
  ['touches', v1('predicates.touches')],
  ['overlaps', v1('predicates.overlaps')],
  ['contains', v1('predicates.contains')],
  ['covers', v1('predicates.covers')],
  ['within', v1('predicates.within')],
  ['covered_by', v1('predicates.covered_by')],
  ['equals', v1('predicates.equals')],
  ['area_inter', (c) => areaOf(OPS_V2['overlay.intersection'](c))],
  ['area_union', (c) => areaOf(OPS_V2['overlay.union'](c))],
  ['area_diff', (c) => areaOf(OPS_V2['overlay.difference'](c))],
  ['area_symdiff', (c) => areaOf(OPS_V2['overlay.symdifference'](c))],
];
