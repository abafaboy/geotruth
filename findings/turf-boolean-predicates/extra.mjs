// Supplementary checks (public API only) for the claims in FINAL.md's analysis and ISSUE.md.
// Run:   npm install && node extra.mjs
// Other build: TURF_MODULE=/abs/path/to/turf-master-bundle.mjs node extra.mjs  (see build-master.sh)
const mod = process.env.TURF_MODULE ? await import(process.env.TURF_MODULE) : await import('@turf/turf');
const { booleanTouches, booleanOverlap, booleanContains, polygon, multiPolygon } = mod;

const sq = (x, y) => [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]; // unit square, CCW
const show = (name, a, b, exp) =>
  console.log(`${name}: booleanTouches(A, B) = ${booleanTouches(a, b)}, booleanTouches(B, A) = ${booleanTouches(b, a)} (exact: ${exp}, ${exp})`);

// MultiPolygon/MultiPolygon branch (index.ts L727-L761): the vertex loop at L731 is bounded by the
// ring count of A's first polygon, so only A's first vertex is tested.
show('MP/MP, adjacent unit squares [0,1]x[0,1] and [1,2]x[0,1]',
  multiPolygon([sq(0, 0)]), multiPolygon([sq(1, 0)]), true);

// Polygon/MultiPolygon and MultiPolygon/Polygon: only the first part of the MultiPolygon is examined.
show('P/MP, the MultiPolygon\'s 2nd part shares the edge x = 1',
  polygon(sq(0, 0)), multiPolygon([sq(10, 10), sq(1, 0)]), true);

// The two minimised cases of lead turf-touches-overlaps-vertex-rules (corpus/curated/leads.toml).
const t = polygon([[[0.1, 0.5], [-0.7, -0.1], [-0.04, -0.5], [0.1, 0.5]]]);
show('lead tiny-rotation-1-000001.min (identical triangles)', t, t, false);
show('lead shared-sloped-edge-1-000001.min (B vertex (1 0.875) on A edge (0 0)-(8 7))',
  polygon([[[0, 0], [8, 7], [0, 9], [0, 0]]]),
  polygon([[[1, 0.875], [7, 6], [7, 3], [1, 0.875]]]), true);

// booleanOverlap sub-case for the draft comment on #2454: containment with a shared boundary
// (exact DE-9IM 212F11FF2: overlaps = false, contains = true).
const big = polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]), small = polygon(sq(0, 0));
console.log(`#2454 sub-case, [0,2]^2 contains [0,1]^2: booleanOverlap = ${booleanOverlap(big, small)} (exact false), booleanContains = ${booleanContains(big, small)} (exact true)`);

// The same pair for booleanTouches (Polygon/Polygon, a possible fixture): true in one order only.
show('P/P, [0,2]^2 contains [0,1]^2, the boundaries share two edges at (0,0)', big, small, false);

// Polygon/MultiPolygon (L598) and MultiPolygon/MultiPolygon (L753) pass a single ring as the
// coordinates of a Polygon, so booleanPointInPolygon never returns true there and the
// "vertex of A strictly inside B" test never fires. A lies inside B with a vertex on B's boundary:
const big4 = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]];
const tri = [[[2, 0], [3, 2], [1, 2], [2, 0]]]; // inside [0,4]^2, vertex (2,0) on its bottom edge
show('P/MP, triangle inside [0,4]^2 with its vertex (2,0) on the edge', polygon(tri), multiPolygon([big4]), false);
show('P/P, the same triangle and square as Polygons', polygon(tri), polygon(big4), false);
show('P/MP, [0,1]^2 and [0,4]^2', polygon(sq(0, 0)), multiPolygon([big4]), false);
show('MP/MP, [0,1]^2 and [0,4]^2, each a one-part MultiPolygon', multiPolygon([sq(0, 0)]), multiPolygon([big4]), false);
// In MP/MP the L731 bound tests only the first k vertices of each ring of A's first polygon
// (k = its ring count), so the inert test at L753 shows only when that polygon has holes:
const holedTri = [[[4, 0], [6, 4], [2, 4], [4, 0]], [[4, 2], [4, 3], [5, 3], [4, 2]]]; // (6,4) strictly inside
const big8 = [[[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]];
show('MP/MP, triangle with a hole inside [0,8]^2, vertex (4,0) on its edge', multiPolygon([holedTri]), multiPolygon([big8]), false);
show('MP/P, the same, B as a Polygon', multiPolygon([holedTri]), polygon(big8), false);

// Holes: the Polygon/Polygon branch never tests a hole as a contact location (case 5 of repro.mjs),
// but the MultiPolygon/Polygon branch loops over all rings of A's first polygon.
const donut = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]];
const inHole = [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]];
show('case 5, Polygon/Polygon: donut and a square in its hole', polygon(donut), polygon(inHole), true);
show('case 5, the donut as a one-part MultiPolygon', multiPolygon([donut]), polygon(inHole), true);
