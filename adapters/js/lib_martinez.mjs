// martinez-polygon-clipping (w8r's Martinez-Rueda-Feito implementation). Areas only.
//
// The package's ESM build is imported on purpose: in 0.8.1 the CommonJS build
// (dist/martinez.cjs, what `require()` gets) does `require("tinyqueue")`, but its dependency
// tinyqueue@3.0.0 is ESM-only, so under Node 22 every operation throws
// "TypeError: Y is not a constructor" (older Node: ERR_REQUIRE_ESM at load time).
// The result of an empty overlay is null.
import { intersection, union, diff, xor } from 'martinez-polygon-clipping';
import { geometryOf, areaOf, pkgVersion } from './common.mjs';

export const LIB = `martinez@${pkgVersion('martinez-polygon-clipping')}`;
const g = (mp) => geometryOf(mp).coordinates;

export const OPS = [
  ['area_inter', (c) => areaOf(intersection(g(c.a), g(c.b)))],
  ['area_union', (c) => areaOf(union(g(c.a), g(c.b)))],
  ['area_diff', (c) => areaOf(diff(g(c.a), g(c.b)))],
  ['area_symdiff', (c) => areaOf(xor(g(c.a), g(c.b)))],
];
