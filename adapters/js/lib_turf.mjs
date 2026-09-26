// Turf (@turf/turf 7.x). Predicates are Turf's own boolean* functions; overlays are
// turf.intersect / turf.union / turf.difference on a FeatureCollection, and their areas are
// measured with the planar shoelace formula in common.mjs (turf.area is geodesic).
//
// Engine: in Turf 7.4 @turf/intersect, @turf/union and @turf/difference are thin wrappers over
// polyclip-ts (Turf 6.x, 7.0 and 7.1 used polygon-clipping; 7.2 switched). The boolean* predicates are Turf's own code
// (point-in-polygon, line-intersect with a sweep line, geojson-equality-ts), not an overlay.
import path from 'node:path';
import { createRequire } from 'node:module';
import * as turf from '@turf/turf';
import { geometryOf, areaOf, pkgDir, pkgVersion } from './common.mjs';

export const LIB = `turf@${pkgVersion('@turf/turf')}`;
// The polyclip-ts that @turf/intersect actually resolves (reported on stderr at startup).
const requireFromTurf = createRequire(path.join(pkgDir('@turf/turf'), 'package.json'));
const engine = `polyclip-ts@${pkgVersion('polyclip-ts', pkgDir('@turf/intersect', requireFromTurf))}`;

// booleanEqual compares vertices with an absolute tolerance of 10^-precision (default 6).
// Default here: "exact", a precision whose tolerance is the smallest subnormal (10**-323.3 ===
// 5e-324), so two coordinates match only when they are the same double. Set
// TURF_EQUAL_PRECISION=6 (or any number) to use a Turf tolerance instead.
const EQ_ENV = process.env.TURF_EQUAL_PRECISION ?? 'exact';
const EQ_PRECISION = EQ_ENV === 'exact' ? 323.3 : Number(EQ_ENV);
if (!(EQ_PRECISION >= 0)) throw new Error(`bad TURF_EQUAL_PRECISION=${EQ_ENV}`);

export const NOTE = `overlays use ${engine}; booleanEqual precision=${EQ_ENV}` +
  `${EQ_ENV === 'exact' ? ' (tolerance 5e-324)' : ''}; area_symdiff = area(difference(A,B)) + area(difference(B,A)) ` +
  `(Turf has no symmetric difference); covers/covered_by unsupported (null)`;

const feat = (mp) => turf.feature(geometryOf(mp));
const fc = (x, y) => turf.featureCollection([feat(x), feat(y)]);

export const OPS = [
  ['valid_a', (c) => turf.booleanValid(feat(c.a))],
  ['valid_b', (c) => turf.booleanValid(feat(c.b))],
  ['intersects', (c) => turf.booleanIntersects(feat(c.a), feat(c.b))],
  ['disjoint', (c) => turf.booleanDisjoint(feat(c.a), feat(c.b))],
  ['touches', (c) => turf.booleanTouches(feat(c.a), feat(c.b))],
  ['overlaps', (c) => turf.booleanOverlap(feat(c.a), feat(c.b))],
  ['contains', (c) => turf.booleanContains(feat(c.a), feat(c.b))],
  ['within', (c) => turf.booleanWithin(feat(c.a), feat(c.b))],
  ['equals', (c) => turf.booleanEqual(feat(c.a), feat(c.b), { precision: EQ_PRECISION })],
  ['area_inter', (c) => areaOf(turf.intersect(fc(c.a, c.b)))],
  ['area_union', (c) => areaOf(turf.union(fc(c.a, c.b)))],
  ['area_diff', (c) => areaOf(turf.difference(fc(c.a, c.b)))],
  ['area_symdiff', (c) => areaOf(turf.difference(fc(c.a, c.b))) + areaOf(turf.difference(fc(c.b, c.a)))],
];
