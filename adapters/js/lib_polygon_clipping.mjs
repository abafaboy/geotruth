// polygon-clipping (Mike Fogel's Martinez-Rueda-Feito sweep line, double arithmetic with an
// epsilon-based comparator and robust-predicates orient2d). Areas only.
import polygonClipping from 'polygon-clipping';
import { geometryOf, areaOf, pkgVersion, clipperInput, multiPolygonOf, typedOf } from './common.mjs';

export const LIB = `polygon-clipping@${pkgVersion('polygon-clipping')}`;
const g = (mp) => geometryOf(mp).coordinates;

export const OPS = [
  ['area_inter', (c) => areaOf(polygonClipping.intersection(g(c.a), g(c.b)))],
  ['area_union', (c) => areaOf(polygonClipping.union(g(c.a), g(c.b)))],
  ['area_diff', (c) => areaOf(polygonClipping.difference(g(c.a), g(c.b)))],
  ['area_symdiff', (c) => areaOf(polygonClipping.xor(g(c.a), g(c.b)))],
];

// Contract v2: overlay output geometry (typed MultiPolygon, coordinates as the library returned
// them) and the parse-echo canary; relate, predicates and validity are not provided (null).
// Operands other than Polygon / MultiPolygon, empty elements and non-finite coordinates are
// outside the library's contract ("unsupported").
const v2 = (fn) => (c) => multiPolygonOf(fn(clipperInput(c.a), clipperInput(c.b)));
export const OPS_V2 = {
  echo: (c) => ({ a: typedOf(c.a), b: typedOf(c.b) }),
  'overlay.intersection': v2((a, b) => polygonClipping.intersection(a, b)),
  'overlay.union': v2((a, b) => polygonClipping.union(a, b)),
  'overlay.difference': v2((a, b) => polygonClipping.difference(a, b)),
  'overlay.symdifference': v2((a, b) => polygonClipping.xor(a, b)),
};
