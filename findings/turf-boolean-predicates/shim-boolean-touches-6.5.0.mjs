import bt from '@turf/boolean-touches';
import * as turf from '@turf/turf';
export const booleanTouches = bt.default ?? bt;
export const polygon = turf.polygon, multiPolygon = turf.multiPolygon;
