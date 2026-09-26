// Shared helpers for the JavaScript adapters (contract: ../../harness/FORMAT-v1.md).
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

// Every result line has all of these fields (null when unsupported), in this order.
export const FIELDS = [
  'valid_a', 'valid_b',
  'intersects', 'disjoint', 'touches', 'overlaps', 'contains', 'covers', 'within', 'covered_by', 'equals',
  'area_inter', 'area_union', 'area_diff', 'area_symdiff',
];

const localRequire = createRequire(import.meta.url);

// Version of an installed package, read from its package.json (the "exports" maps of some
// packages hide package.json from require, so read the file from the lookup path).
// `fromDir` resolves the package as seen from another package (e.g. turf's own dependency).
export function pkgVersion(name, fromDir) {
  const req = fromDir ? createRequire(path.join(fromDir, 'package.json')) : localRequire;
  const dir = pkgDir(name, req);
  return JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')).version;
}

export function pkgDir(name, req = localRequire) {
  for (const base of req.resolve.paths(name) || []) {
    const dir = path.join(base, name);
    if (fs.existsSync(path.join(dir, 'package.json'))) return fs.realpathSync(dir);
  }
  throw new Error(`package ${name} not found (run install.sh)`);
}

// Case coordinates are GeoJSON MultiPolygon coordinates. FORMAT-v1.md: one part -> Polygon.
// Returns a fresh deep copy, so a library that mutates its input cannot affect later operations.
export function geometryOf(mp) {
  if (!Array.isArray(mp)) throw new TypeError('multipolygon coordinates must be an array');
  const coords = structuredClone(mp);
  return coords.length === 1
    ? { type: 'Polygon', coordinates: coords[0] }
    : { type: 'MultiPolygon', coordinates: coords };
}

// ---------------------------------------------------------------------------------------------
// Planar area (shoelace), NOT turf.area (which is geodesic on the WGS84 sphere).
//
// Each ring is translated so that its first vertex is the origin before the cross products are
// formed: for vertices far from the origin (the tiny-rotation-offset family sits at 1e7) this
// avoids the catastrophic cancellation of the textbook formula. The terms are summed with
// Neumaier's compensated summation. Polygon area = |shell| - sum |holes| (the GeoJSON / OGC
// reading, independent of ring orientation). Unclosed rings are treated as implicitly closed.

function ringArea(ring) {
  const n = ring.length;
  if (n < 3) return 0;
  const x0 = ring[0][0], y0 = ring[0][1];
  let sum = 0, comp = 0;
  let px = ring[1][0] - x0, py = ring[1][1] - y0;
  for (let i = 2; i < n; i++) {
    const qx = ring[i][0] - x0, qy = ring[i][1] - y0;
    const term = px * qy - qx * py;
    const t = sum + term;
    comp += Math.abs(sum) >= Math.abs(term) ? (sum - t) + term : (term - t) + sum;
    sum = t;
    px = qx; py = qy;
  }
  return Math.abs((sum + comp) / 2);
}

function polygonArea(rings) {
  if (!Array.isArray(rings) || rings.length === 0) return 0;
  let a = ringArea(rings[0]);
  for (let i = 1; i < rings.length; i++) a -= ringArea(rings[i]);
  return a;
}

function isPosition(p) {
  return Array.isArray(p) && typeof p[0] === 'number';
}

// Area of whatever an overlay returned: null/undefined (empty), a GeoJSON Feature, a
// FeatureCollection, a Polygon/MultiPolygon geometry, or bare Polygon/MultiPolygon coordinates.
export function areaOf(g) {
  if (g === null || g === undefined) return 0;
  if (Array.isArray(g)) {
    if (g.length === 0) return 0;
    if (Array.isArray(g[0]) && isPosition(g[0][0])) return polygonArea(g); // Polygon coords
    let a = 0; // MultiPolygon coords
    for (const poly of g) a += polygonArea(poly);
    return a;
  }
  switch (g.type) {
    case 'Feature': return areaOf(g.geometry);
    case 'FeatureCollection': return g.features.reduce((s, f) => s + areaOf(f), 0);
    case 'GeometryCollection': return g.geometries.reduce((s, x) => s + areaOf(x), 0);
    case 'Polygon': return polygonArea(g.coordinates);
    case 'MultiPolygon': return g.coordinates.reduce((s, p) => s + polygonArea(p), 0);
    case 'Point': case 'MultiPoint': case 'LineString': case 'MultiLineString': return 0;
    default: throw new TypeError(`unexpected overlay result type ${JSON.stringify(g.type)}`);
  }
}

export function fmtErr(e) {
  let s;
  if (e instanceof Error) s = `${e.name}: ${e.message}`;
  else { try { s = `thrown non-Error: ${JSON.stringify(e)}`; } catch { s = `thrown non-Error: ${String(e)}`; } }
  return s.length > 500 ? s.slice(0, 500) + '...' : s;
}

// =============================================================================================
// Adapter contract v2 (docs/DESIGN.md §4.1, schemas/result.v2.schema.json)
// =============================================================================================

export const PREDICATES_V2 = ['intersects', 'disjoint', 'touches', 'crosses', 'overlaps', 'contains',
  'covers', 'within', 'covered_by', 'equals'];
export const OVERLAYS_V2 = ['intersection', 'union', 'difference', 'symdifference'];
export const V2_PATHS = ['echo', 'relate', ...PREDICATES_V2.map((p) => `predicates.${p}`), 'valid_a',
  'valid_b', ...OVERLAYS_V2.map((o) => `overlay.${o}`)];

// Thrown by an operation when the input is outside the library's contract ("unsupported").
export class Unsupported extends Error {
  constructor(why) { super(why || 'unsupported'); this.name = 'Unsupported'; }
}

// A v2 case: an operand is a typed geometry (an object) or "ops" is present.
export function isV2(kase) {
  return kase !== null && typeof kase === 'object' && ('ops' in kase
    || (kase.a !== null && typeof kase.a === 'object' && !Array.isArray(kase.a))
    || (kase.b !== null && typeof kase.b === 'object' && !Array.isArray(kase.b)));
}

function groupOf(path) {
  return path === 'valid_a' || path === 'valid_b' ? 'validity' : path.split('.')[0];
}

// The field paths a case asks for ("ops"; absent = everything but echo).
export function requestedPaths(kase) {
  let groups = ['relate', 'predicates', 'validity', 'overlay'];
  if ('ops' in kase) {
    if (!Array.isArray(kase.ops)) throw new TypeError('"ops" must be an array');
    for (const o of kase.ops) {
      if (!['echo', 'relate', 'predicates', 'validity', 'overlay'].includes(o)) throw new TypeError(`unknown op ${JSON.stringify(o)}`);
    }
    groups = kase.ops;
  }
  return V2_PATHS.filter((p) => groups.includes(groupOf(p)));
}

// A typed geometry for an operand (legacy FORMAT-v1 arrays become Polygon / MultiPolygon).
export function typedOf(x) {
  if (Array.isArray(x)) return geometryOf(x);
  if (x === null || typeof x !== 'object' || typeof x.type !== 'string') throw new TypeError('not a typed geometry');
  return structuredClone(x);
}

// Does the typed geometry contain an empty element (or an empty coordinate list)?
export function hasEmpty(g) {
  switch (g.type) {
    case 'GeometryCollection': return g.geometries.length === 0 || g.geometries.some(hasEmpty);
    case 'Point': return g.coordinates.length === 0;
    case 'LineString': case 'MultiPoint': return g.coordinates.length === 0 || (g.type === 'MultiPoint' && g.coordinates.some((p) => p.length === 0));
    case 'Polygon': case 'MultiLineString': return g.coordinates.length === 0 || g.coordinates.some((r) => r.length === 0);
    case 'MultiPolygon': return g.coordinates.length === 0 || g.coordinates.some((p) => p.length === 0 || p.some((r) => r.length === 0));
    default: throw new TypeError(`unknown geometry type ${JSON.stringify(g.type)}`);
  }
}

// Every number of a typed geometry is finite (GeoJSON has no NaN / Infinity).
export function allFinite(g) {
  if (g.type === 'GeometryCollection') return g.geometries.every(allFinite);
  const walk = (x) => (typeof x === 'number' ? Number.isFinite(x) : x.every(walk));
  return walk(g.coordinates);
}

// MultiPolygon coordinates of a Polygon / MultiPolygon operand, for the polygon clippers;
// anything else (or empties, non-finite numbers) is outside their contract.
export function clipperInput(x) {
  const g = typedOf(x);
  if (g.type !== 'Polygon' && g.type !== 'MultiPolygon') throw new Unsupported(`${g.type} operand: the library clips polygons only`);
  if (hasEmpty(g) || !allFinite(g)) throw new Unsupported('empty elements or non-finite coordinates');
  return g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
}

// A clipper's output (MultiPolygon or Polygon coordinates, null or []) as a typed MultiPolygon.
export function multiPolygonOf(r) {
  if (r === null || r === undefined || (Array.isArray(r) && r.length === 0)) return { type: 'MultiPolygon', coordinates: [] };
  if (!Array.isArray(r)) {  // a GeoJSON Feature or geometry
    const g = r.type === 'Feature' ? r.geometry : r;
    if (g === null) return { type: 'MultiPolygon', coordinates: [] };
    return g.type === 'Polygon' ? { type: 'MultiPolygon', coordinates: [g.coordinates] } : { type: g.type, coordinates: g.coordinates };
  }
  if (typeof r[0][0][0] === 'number') return { type: 'MultiPolygon', coordinates: [r] };  // Polygon coordinates
  return { type: 'MultiPolygon', coordinates: r };
}

// JSON text of a result value: numbers in shortest round-trip form (String(x)), -0 as -0.0,
// NaN / Infinity as Python's json module writes them (JSON.stringify would write 0 and null).
export function jsonOut(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return 'NaN';
    if (v === Infinity) return 'Infinity';
    if (v === -Infinity) return '-Infinity';
    if (Object.is(v, -0)) return '-0.0';
    return String(v);
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'string') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(jsonOut).join(', ') + ']';
  return '{' + Object.entries(v).map(([k, x]) => JSON.stringify(k) + ': ' + jsonOut(x)).join(', ') + '}';
}
