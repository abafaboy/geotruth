// Independent checks for cases.jsonl: Turf's own booleanValid, booleanIntersects and intersect
// (polyclip-ts), and JSTS 2.12.1 relate/touches (the JTS port Turf's own tests compare against).
import * as turf from '@turf/turf';
import GeoJSONReader from 'jsts/org/locationtech/jts/io/GeoJSONReader.js';
import 'jsts/org/locationtech/jts/monkey.js';
import fs from 'node:fs';
const reader = new GeoJSONReader();
for (const l of fs.readFileSync(process.argv[2], 'utf8').trim().split('\n')) {
  const c = JSON.parse(l);
  const A = turf.feature(c.a), B = turf.feature(c.b);
  const inter = turf.intersect(turf.featureCollection([A, B]));
  const ga = reader.read(c.a), gb = reader.read(c.b);
  console.log(JSON.stringify({ id: c.id,
    turf_booleanValid: [turf.booleanValid(A), turf.booleanValid(B)],
    turf_booleanIntersects: turf.booleanIntersects(A, B),
    turf_intersect_has_area: inter !== null && turf.area(inter) > 0,
    jsts_relate: ga.relate(gb).toString(), jsts_touches: [ga.touches(gb), gb.touches(ga)] }));
}
