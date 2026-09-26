// polyclip-ts (TypeScript port of polygon-clipping that computes with bignumber.js). The default
// precision (no setPrecision call) is used: no snapping epsilon. Areas only.
import { intersection, union, difference, xor } from 'polyclip-ts';
import { geometryOf, areaOf, pkgVersion } from './common.mjs';

export const LIB = `polyclip-ts@${pkgVersion('polyclip-ts')}`;
const g = (mp) => geometryOf(mp).coordinates;

export const OPS = [
  ['area_inter', (c) => areaOf(intersection(g(c.a), g(c.b)))],
  ['area_union', (c) => areaOf(union(g(c.a), g(c.b)))],
  ['area_diff', (c) => areaOf(difference(g(c.a), g(c.b)))],
  ['area_symdiff', (c) => areaOf(xor(g(c.a), g(c.b)))],
];
