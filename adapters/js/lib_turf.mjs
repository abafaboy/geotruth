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
import { geometryOf, areaOf, pkgDir, pkgVersion, typedOf, hasEmpty, allFinite, multiPolygonOf, Unsupported } from './common.mjs';

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
  `${EQ_ENV === 'exact' ? ' (tolerance 5e-324)' : ''}; area_symdiff = area(difference(A,B)) + area(difference(B,A)), ` +
  `overlay.symdifference = union(difference(A,B), difference(B,A)) (Turf has no symmetric difference); ` +
  `covers/covered_by unsupported (null)`;

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

// Contract v2. Turf has no relate and no covers / coveredBy (null). Its boolean functions
// throw "... not supported" for type pairs they do not implement: that is "unsupported", as
// are operands with empty elements or non-finite coordinates (GeoJSON has neither). Overlays
// take Polygon / MultiPolygon operands only; symdifference is derived from two differences,
// merged with turf.union (union(difference(A, B), difference(B, A)), what a Turf user writes;
// concatenating the two would be an invalid MultiPolygon wherever they share an edge).
function operand(x) {
  const g = typedOf(x);
  if (hasEmpty(g) || !allFinite(g)) throw new Unsupported('empty elements or non-finite coordinates');
  return turf.feature(g);
}

function boolean(fn) {
  return (c) => {
    const a = operand(c.a), b = operand(c.b);
    try {
      return fn(a, b);
    } catch (e) {
      if (/not supported|unsupported|is not a supported/i.test(String(e && e.message))) throw new Unsupported(e.message);
      throw e;
    }
  };
}

function polygonal(x) {
  const f = operand(x);
  if (f.geometry.type !== 'Polygon' && f.geometry.type !== 'MultiPolygon') throw new Unsupported('Turf overlays take polygons only');
  return f;
}

const clip = (fn) => (c) => multiPolygonOf(fn(turf.featureCollection([polygonal(c.a), polygonal(c.b)])));

export const OPS_V2 = {
  echo: (c) => ({ a: typedOf(c.a), b: typedOf(c.b) }),
  'predicates.intersects': boolean((a, b) => turf.booleanIntersects(a, b)),
  'predicates.disjoint': boolean((a, b) => turf.booleanDisjoint(a, b)),
  'predicates.touches': boolean((a, b) => turf.booleanTouches(a, b)),
  'predicates.crosses': boolean((a, b) => turf.booleanCrosses(a, b)),
  'predicates.overlaps': boolean((a, b) => turf.booleanOverlap(a, b)),
  'predicates.contains': boolean((a, b) => turf.booleanContains(a, b)),
  'predicates.within': boolean((a, b) => turf.booleanWithin(a, b)),
  'predicates.equals': boolean((a, b) => turf.booleanEqual(a, b, { precision: EQ_PRECISION })),
  valid_a: (c) => turf.booleanValid(operand(c.a)),
  valid_b: (c) => turf.booleanValid(operand(c.b)),
  'overlay.intersection': clip((fc) => turf.intersect(fc)),
  'overlay.union': clip((fc) => turf.union(fc)),
  'overlay.difference': clip((fc) => turf.difference(fc)),
  'overlay.symdifference': (c) => {
    const a = polygonal(c.a), b = polygonal(c.b);
    const parts = [turf.difference(turf.featureCollection([a, b])), turf.difference(turf.featureCollection([b, a]))]
      .filter((f) => f && f.geometry);
    if (parts.length === 0) return multiPolygonOf(null);
    if (parts.length === 1) return multiPolygonOf(parts[0]);
    return multiPolygonOf(turf.union(turf.featureCollection(parts)));
  },
};
