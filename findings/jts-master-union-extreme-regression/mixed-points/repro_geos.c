/* The same input through the GEOS port (OverlayMixedPoints.cpp), C API with gridSize 1.
 *   cc repro_geos.c $(geos-config --cflags) $(geos-config --clibs) -o repro_geos && ./repro_geos */
#include <stdio.h>
#include <stdarg.h>
#include <geos_c.h>

static void msg(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); printf("\n"); va_end(ap); }

static void show(GEOSContextHandle_t h, GEOSWKTWriter *w, const char *label, GEOSGeometry *g) {
  char *s = g ? GEOSWKTWriter_write_r(h, w, g) : NULL;
  printf("%s = %s\n", label, s ? s : "(null: exception)");
  if (s) GEOSFree_r(h, s);
  if (g) GEOSGeom_destroy_r(h, g);
}

int main(void) {
  GEOSContextHandle_t h = GEOS_init_r();
  GEOSContext_setErrorHandler_r(h, msg);
  printf("GEOS %s\n", GEOSversion());
  GEOSWKTReader *r = GEOSWKTReader_create_r(h);
  GEOSWKTWriter *w = GEOSWKTWriter_create_r(h);
  GEOSWKTWriter_setTrim_r(h, w, 1);
  GEOSGeometry *a = GEOSWKTReader_read_r(h, r, "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((3 0, 5 0, 5 0.4, 3 0)))");
  GEOSGeometry *p = GEOSWKTReader_read_r(h, r, "POINT (7 7)");
  GEOSGeometry *l = GEOSWKTReader_read_r(h, r, "LINESTRING (7 7, 8 8)");
  show(h, w, "GEOSUnionPrec_r(A, POINT (7 7), 1)        ", GEOSUnionPrec_r(h, a, p, 1.0));
  show(h, w, "GEOSSymDifferencePrec_r(A, POINT (7 7), 1)", GEOSSymDifferencePrec_r(h, a, p, 1.0));
  show(h, w, "GEOSDifferencePrec_r(A, POINT (7 7), 1)   ", GEOSDifferencePrec_r(h, a, p, 1.0));
  show(h, w, "GEOSUnionPrec_r(A, LINESTRING (7 7, 8 8), 1)", GEOSUnionPrec_r(h, a, l, 1.0));
  GEOSGeom_destroy_r(h, a); GEOSGeom_destroy_r(h, p); GEOSGeom_destroy_r(h, l);
  GEOSWKTReader_destroy_r(h, r); GEOSWKTWriter_destroy_r(h, w);
  GEOS_finish_r(h);
  return 0;
}
