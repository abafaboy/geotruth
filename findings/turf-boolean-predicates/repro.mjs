// booleanTouches on polygons: minimal cases (public API only).
// Run:   npm install @turf/turf@7.4.0 && node repro.mjs
// Other build: TURF_MODULE=/abs/path/to/bundle.mjs node repro.mjs  (a module exporting
// booleanTouches, polygon and multiPolygon, e.g. an esbuild bundle of Turf master sources).
const mod = process.env.TURF_MODULE ? await import(process.env.TURF_MODULE) : await import('@turf/turf');
const { booleanTouches, polygon, multiPolygon } = mod;

const cases = [
  // 1. identical triangles: the interiors coincide, so they do not touch.
  ['identical triangles',
    polygon([[[0, 0], [1, 0], [0, 1], [0, 0]]]),
    polygon([[[0, 0], [1, 0], [0, 1], [0, 0]]]), false, false],
  // 2. overlapping squares (overlap is [1,2]x[0,2], area 2): they do not touch.
  ['overlapping squares',
    polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]),
    polygon([[[1, 0], [3, 0], [3, 2], [1, 2], [1, 0]]]), false, false],
  // 3. triangle whose apex (1,2) lies on the square's top edge: they touch, in either order.
  ['apex of B on edge of A',
    polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]),
    polygon([[[1, 2], [2, 3], [0, 3], [1, 2]]]), true, true],
  // 4. MultiPolygon: the square touching B is the 2nd part of A (shared edge x = 1).
  ['2nd part of MultiPolygon shares an edge',
    multiPolygon([[[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
                  [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]),
    polygon([[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]), true, true],
  // 5. B lies in A's hole and shares an edge with the hole: they touch.
  ['B in hole of A, sharing an edge',
    polygon([[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]]),
    polygon([[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]), true, true],
];

let wrong = 0;
for (const [name, a, b, expAB, expBA] of cases) {
  const ab = booleanTouches(a, b), ba = booleanTouches(b, a);
  const ok = ab === expAB && ba === expBA;
  if (!ok) wrong++;
  console.log(`${ok ? 'ok   ' : 'WRONG'} ${name}: booleanTouches(A, B) = ${ab} (expected ${expAB}), booleanTouches(B, A) = ${ba} (expected ${expBA})`);
}
console.log(`${wrong} of ${cases.length} cases wrong`);
