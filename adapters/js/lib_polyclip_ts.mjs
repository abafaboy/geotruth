// polyclip-ts (TypeScript port of polygon-clipping that computes with bignumber.js). The default
// precision (no setPrecision call) is used: no snapping epsilon. Areas only.
import { intersection, union, difference, xor } from 'polyclip-ts';
import { geometryOf, areaOf, pkgVersion, clipperInput, multiPolygonOf, typedOf } from './common.mjs';

export const LIB = `polyclip-ts@${pkgVersion('polyclip-ts')}`;
const g = (mp) => geometryOf(mp).coordinates;

export const OPS = [
  ['area_inter', (c) => areaOf(intersection(g(c.a), g(c.b)))],
  ['area_union', (c) => areaOf(union(g(c.a), g(c.b)))],
  ['area_diff', (c) => areaOf(difference(g(c.a), g(c.b)))],
  ['area_symdiff', (c) => areaOf(xor(g(c.a), g(c.b)))],
];

// Contract v2: overlay output geometry (typed MultiPolygon, coordinates as the library returned
// them) and the parse-echo canary; relate, predicates and validity are not provided (null).
// Operands other than Polygon / MultiPolygon, empty elements and non-finite coordinates are
// outside the library's contract ("unsupported").
const v2 = (fn) => (c) => multiPolygonOf(fn(clipperInput(c.a), clipperInput(c.b)));
export const OPS_V2 = {
  echo: (c) => ({ a: typedOf(c.a), b: typedOf(c.b) }),
  'overlay.intersection': v2(intersection),
  'overlay.union': v2(union),
  'overlay.difference': v2(difference),
  'overlay.symdifference': v2(xor),
};
