// polygon-clipping (Mike Fogel's Martinez-Rueda-Feito sweep line, double arithmetic with an
// epsilon-based comparator and robust-predicates orient2d). Areas only.
import polygonClipping from 'polygon-clipping';
import { geometryOf, areaOf, pkgVersion } from './common.mjs';

export const LIB = `polygon-clipping@${pkgVersion('polygon-clipping')}`;
const g = (mp) => geometryOf(mp).coordinates;

export const OPS = [
  ['area_inter', (c) => areaOf(polygonClipping.intersection(g(c.a), g(c.b)))],
  ['area_union', (c) => areaOf(polygonClipping.union(g(c.a), g(c.b)))],
  ['area_diff', (c) => areaOf(polygonClipping.difference(g(c.a), g(c.b)))],
  ['area_symdiff', (c) => areaOf(polygonClipping.xor(g(c.a), g(c.b)))],
];
