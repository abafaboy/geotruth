// Shared helpers for the JavaScript adapters (contract: ../../FORMAT.md).
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

// Case coordinates are GeoJSON MultiPolygon coordinates. FORMAT.md: one part -> Polygon.
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
