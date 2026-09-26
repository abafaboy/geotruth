/* reads "A\tB" lines; prints relate(A,B) relate(B,A) and predicate bits of (A,B):
   intersects contains within covers coveredBy touches overlaps crosses (no fork: inputs have no EMPTY elements) */
#include <stdio.h>
#include <string.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>
int main(void) {
    static char line[1 << 20];
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\n")] = 0;
        char *tab = strchr(line, '\t'); if (!tab) continue; *tab = 0;
        GEOSGeometry *a = GEOSWKTReader_read_r(h, r, line), *b = GEOSWKTReader_read_r(h, r, tab + 1);
        char *m1 = GEOSRelate_r(h, a, b), *m2 = GEOSRelate_r(h, b, a);
        printf("%s %s %d%d%d%d%d%d%d%d\n", m1 ? m1 : "ERR", m2 ? m2 : "ERR",
               GEOSIntersects_r(h, a, b), GEOSContains_r(h, a, b), GEOSWithin_r(h, a, b), GEOSCovers_r(h, a, b),
               GEOSCoveredBy_r(h, a, b), GEOSTouches_r(h, a, b), GEOSOverlaps_r(h, a, b), GEOSCrosses_r(h, a, b));
        GEOSFree_r(h, m1); GEOSFree_r(h, m2); GEOSGeom_destroy_r(h, a); GEOSGeom_destroy_r(h, b);
        fflush(stdout);
    }
    return 0;
}
