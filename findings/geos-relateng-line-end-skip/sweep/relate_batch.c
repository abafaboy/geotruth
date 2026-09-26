/* reads "WKT_A<TAB>WKT_B" lines, prints relate(A,B) per line (ERR on failure) */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <geos_c.h>
int main(void) {
    GEOSContextHandle_t c = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(c);
    static char buf[1 << 20];
    while (fgets(buf, sizeof buf, stdin)) {
        buf[strcspn(buf, "\n")] = 0;
        char *tab = strchr(buf, '\t');
        if (!tab) { puts("ERR"); continue; }
        *tab = 0;
        GEOSGeometry *a = GEOSWKTReader_read_r(c, r, buf), *b = GEOSWKTReader_read_r(c, r, tab + 1);
        char *m = (a && b) ? GEOSRelate_r(c, a, b) : NULL;
        puts(m ? m : "ERR");
        if (m) GEOSFree_r(c, m);
        if (a) GEOSGeom_destroy_r(c, a);
        if (b) GEOSGeom_destroy_r(c, b);
    }
    fflush(stdout);
    return 0;
}
