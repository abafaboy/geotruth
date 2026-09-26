/* Minimal reproducer: GEOS overlay of two triangles loses most of B.
 *
 *   A = POLYGON((1 1, -1e-20 0, 1 0, 1 1))   area 0.5 (+5e-21)
 *   B = POLYGON((0 0, 1 1, 0 1, 0 0))        area 0.5
 *
 * B is on the upper-left side of the diagonal y = x, A on the lower-right side of the
 * line from (-1e-20, 0) to (1, 1), which lies a hair above the diagonal for x < 1.
 * They overlap only in a sliver of area ~5e-21, so the exact answers are
 *   area(A n B) ~ 5e-21, area(A u B) ~ 1.0, area(B - A) ~ 0.5.
 *
 * Uses only the public reentrant C API.
 * Build: cc -std=c11 repro.c -o repro $(geos-config --cflags) $(geos-config --clibs)
 */
#include <stdio.h>
#include <stdlib.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

static void on_msg(const char *fmt, void *userdata)
{
    (void)userdata;
    fprintf(stderr, "GEOS: %s\n", fmt);
}

static void report(GEOSContextHandle_t h, GEOSWKTWriter *w, const char *name,
                   GEOSGeometry *g, const char *expected)
{
    double area = -1;
    if (!g) {
        printf("%-14s ERROR\n", name);
        return;
    }
    GEOSArea_r(h, g, &area);
    char *wkt = GEOSWKTWriter_write_r(h, w, g);
    printf("%-14s area = %-24.17g (expected %s)\n               %s\n", name, area, expected, wkt);
    GEOSFree_r(h, wkt);
    GEOSGeom_destroy_r(h, g);
}

int main(void)
{
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(h, on_msg, NULL);

    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(h);
    GEOSWKTWriter_setTrim_r(h, w, 1);

    GEOSGeometry *a = GEOSWKTReader_read_r(h, r, "POLYGON ((1 1, -1e-20 0, 1 0, 1 1))");
    GEOSGeometry *b = GEOSWKTReader_read_r(h, r, "POLYGON ((0 0, 1 1, 0 1, 0 0))");
    if (!a || !b) return 1;

    double xa = 0;
    const GEOSGeometry *ra = GEOSGetExteriorRing_r(h, a);
    const GEOSCoordSequence *sa = GEOSGeom_getCoordSeq_r(h, ra);
    GEOSCoordSeq_getX_r(h, sa, 1, &xa);

    double area_a = 0, area_b = 0;
    GEOSArea_r(h, a, &area_a);
    GEOSArea_r(h, b, &area_b);
    printf("GEOS %s\n", GEOSversion());
    printf("A x-coordinate of 2nd vertex = %.17g\n", xa);
    printf("isValid(A) = %d, isValid(B) = %d, area(A) = %.17g, area(B) = %.17g\n",
           GEOSisValid_r(h, a), GEOSisValid_r(h, b), area_a, area_b);
    printf("intersects = %d, overlaps = %d, covers(A,B) = %d\n\n",
           GEOSIntersects_r(h, a, b), GEOSOverlaps_r(h, a, b), GEOSCovers_r(h, a, b));

    report(h, w, "union",        GEOSUnion_r(h, a, b),        "~1.0");
    report(h, w, "intersection", GEOSIntersection_r(h, a, b), "~5e-21");
    report(h, w, "B - A",        GEOSDifference_r(h, b, a),   "~0.5");
    report(h, w, "A - B",        GEOSDifference_r(h, a, b),   "~0.5");
    report(h, w, "symdifference", GEOSSymDifference_r(h, a, b), "~1.0");

    GEOSGeom_destroy_r(h, a);
    GEOSGeom_destroy_r(h, b);
    GEOSWKTReader_destroy_r(h, r);
    GEOSWKTWriter_destroy_r(h, w);
    GEOS_finish_r(h);
    return 0;
}
