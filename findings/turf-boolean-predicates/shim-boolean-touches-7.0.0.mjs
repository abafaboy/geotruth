// booleanTouches from @turf/boolean-touches 7.0.0, with its Turf dependencies pinned to 7.0.0.
// `npm install @turf/turf@7.0.0` is not enough: its "^7.0.0" dependencies resolve to the newest
// 7.x (7.4.0 on 2026-09-26). In an empty directory:
//   npm install @turf/boolean-touches@7.0.0 @turf/boolean-point-on-line@7.0.0 \
//       @turf/boolean-point-in-polygon@7.0.0 @turf/helpers@7.0.0 @turf/invariant@7.0.0
//   cp <this directory>/shim-boolean-touches-7.0.0.mjs .
//   TURF_MODULE=$PWD/shim-boolean-touches-7.0.0.mjs node <this directory>/repro.mjs
import * as bt from '@turf/boolean-touches';
import { polygon, multiPolygon } from '@turf/helpers';
export const booleanTouches = bt.booleanTouches ?? bt.default;
export { polygon, multiPolygon };
