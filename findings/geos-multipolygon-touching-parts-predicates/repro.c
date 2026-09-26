/* GEOS repro: RelateNG gives wrong predicates when a ring vertex of a valid polygonal
 * geometry touches the interior of another ring's edge (MultiPolygon parts touching
 * vertex-to-edge, or a hole touching its shell), and the other operand's boundary runs
 * along that edge through the touch point.
 *
 * Uses only the public reentrant C API.
 * Build: cc -O1 -o repro repro.c $(geos-config --cflags) $(geos-config --clibs)
 * Run:   ./repro
 */
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>
#include <stdio.h>
#include <stdlib.h>

static void handler(const char *msg, void *ud) { (void)ud; fprintf(stderr, "GEOS: %s\n", msg); }

static const char *tf(char c) { return c == 1 ? "true" : c == 0 ? "false" : "EXCEPTION"; }

static void run(GEOSContextHandle_t h, const char *name, const char *wa, const char *wb,
                const char *expected_im)
{
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSGeometry *a = GEOSWKTReader_read_r(h, r, wa);
    GEOSGeometry *b = GEOSWKTReader_read_r(h, r, wb);
    char *im = GEOSRelate_r(h, a, b);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(h, a);

    printf("%s\n", name);
    printf("  A = %s\n  B = %s\n", wa, wb);
    printf("  isValid(A)=%s isValid(B)=%s\n", tf(GEOSisValid_r(h, a)), tf(GEOSisValid_r(h, b)));
    printf("  relate(A,B)   expected %s  got %s\n", expected_im, im);
    printf("  contains=%s covers=%s touches=%s overlaps=%s  prepared contains=%s\n",
           tf(GEOSContains_r(h, a, b)), tf(GEOSCovers_r(h, a, b)),
           tf(GEOSTouches_r(h, a, b)), tf(GEOSOverlaps_r(h, a, b)),
           tf(GEOSPreparedContains_r(h, pa, b)));

    GEOSPreparedGeom_destroy_r(h, pa);
    GEOSFree_r(h, im);
    GEOSGeom_destroy_r(h, a);
    GEOSGeom_destroy_r(h, b);
    GEOSWKTReader_destroy_r(h, r);
}

int main(void)
{
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(h, handler, NULL);
    printf("GEOS %s\n\n", GEOSversion());

    /* The triangle's vertex (1 2) lies in the middle of the square's top edge. */
    run(h, "case 1: MultiPolygon A contains its own part B (expected contains=true, overlaps=false)",
        "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
        "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
        "2F2F11FF2");

    /* The hole's vertex (2 0) lies in the middle of the shell's bottom edge. */
    run(h, "case 2: shell A contains polygon-with-touching-hole B (expected contains=true, overlaps=false)",
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
        "212F1FFF2");

    run(h, "case 3: polygon-with-touching-hole A vs adjacent B (expected touches=true, overlaps=false)",
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
        "POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))",
        "FF2F11212");

    GEOS_finish_r(h);
    return 0;
}
