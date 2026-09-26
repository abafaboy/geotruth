/*
 * RelateNG: a vertex that lies within rounding distance of the other polygon's edge
 * gives wrong polygon/polygon predicates (touches instead of overlaps, contains
 * instead of overlaps).
 *
 * Uses only the public GEOS C API.
 *   cc repro.c $(geos-config --cflags) $(geos-config --clibs) -o repro && ./repro
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <geos_c.h>

static GEOSContextHandle_t ctx;

static const char *tf(char r) { return r == 1 ? "true" : r == 0 ? "false" : "ERROR"; }

static GEOSGeometry *rd(const char *wkt)
{
    GEOSWKTReader *r = GEOSWKTReader_create_r(ctx);
    GEOSGeometry *g = GEOSWKTReader_read_r(ctx, r, wkt);
    GEOSWKTReader_destroy_r(ctx, r);
    if (!g) { fprintf(stderr, "cannot parse %s\n", wkt); exit(1); }
    return g;
}

static int nbad = 0;
static void check(const char *what, char got, int expected)
{
    int ok = (got == expected);
    if (!ok) nbad++;
    printf("  %-34s %-5s  (expected %-5s) %s\n", what, tf(got), expected ? "true" : "false",
           ok ? "" : "<-- WRONG");
}

static void run(const char *title, const char *wa, const char *wb, const char *wv,
                const char *exp_im, int e_touches, int e_overlaps, int e_contains,
                int e_covers, int e_v_in_a)
{
    GEOSGeometry *a = rd(wa), *b = rd(wb), *v = rd(wv);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(ctx, a);
    char *im = GEOSRelate_r(ctx, a, b);
    printf("%s\n  A = %s\n  B = %s\n", title, wa, wb);
    printf("  isValid(A) = %s, isValid(B) = %s\n", tf(GEOSisValid_r(ctx, a)), tf(GEOSisValid_r(ctx, b)));
    printf("  relate(A, B)                       %s  (expected %s) %s\n", im, exp_im,
           strcmp(im, exp_im) == 0 ? "" : "<-- WRONG");
    if (strcmp(im, exp_im) != 0) nbad++;
    check("touches(A, B)", GEOSTouches_r(ctx, a, b), e_touches);
    check("overlaps(A, B)", GEOSOverlaps_r(ctx, a, b), e_overlaps);
    check("contains(A, B)", GEOSContains_r(ctx, a, b), e_contains);
    check("covers(A, B)", GEOSCovers_r(ctx, a, b), e_covers);
    check("prepared touches(A, B)", GEOSPreparedTouches_r(ctx, pa, b), e_touches);
    check("prepared overlaps(A, B)", GEOSPreparedOverlaps_r(ctx, pa, b), e_overlaps);
    check("prepared contains(A, B)", GEOSPreparedContains_r(ctx, pa, b), e_contains);
    check("prepared covers(A, B)", GEOSPreparedCovers_r(ctx, pa, b), e_covers);
    printf("  P = %s (a vertex of B)\n", wv);
    check("intersects(B, P)", GEOSIntersects_r(ctx, b, v), 1);
    check("contains(A, P)", GEOSContains_r(ctx, a, v), e_v_in_a);
    check("intersects(A, P)", GEOSIntersects_r(ctx, a, v), e_v_in_a);
    printf("\n");
    GEOSFree_r(ctx, im);
    GEOSPreparedGeom_destroy_r(ctx, pa);
    GEOSGeom_destroy_r(ctx, a);
    GEOSGeom_destroy_r(ctx, b);
    GEOSGeom_destroy_r(ctx, v);
}

int main(void)
{
    ctx = GEOS_init_r();
    printf("GEOS %s\n\n", GEOSversion());

    /* A: the triangle 0 <= y <= x/3, x <= 3.
     * 0.6666666666666666 is the double nearest to 2/3; it is 2/3 - 1/(3*2^53), i.e. just
     * BELOW the edge y = x/3, so P = (2, 0.6666666666666666) is in the interior of A. */
    run("Case 1: B's vertex P lies inside A, 3.7e-17 (vertically) below A's edge (0 0)-(3 1)",
        "POLYGON ((0 0, 3 0, 3 1, 0 0))",
        "POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))",
        "POINT (2 0.6666666666666666)",
        "212101212", /*touches*/ 0, /*overlaps*/ 1, /*contains*/ 0, /*covers*/ 0, /*P in A*/ 1);

    /* 0.8333333333333334 is the double nearest to 5/6 = 2.5/3; it is 5/6 + 1/(3*2^53), i.e.
     * just ABOVE the edge y = x/3, so P = (2.5, 0.8333333333333334) is outside A. */
    run("Case 2: B's vertex P lies outside A, 3.7e-17 (vertically) above A's edge (0 0)-(3 1)",
        "POLYGON ((0 0, 3 0, 3 1, 0 0))",
        "POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))",
        "POINT (2.5 0.8333333333333334)",
        "212101212", /*touches*/ 0, /*overlaps*/ 1, /*contains*/ 0, /*covers*/ 0, /*P in A*/ 0);

    printf("%d wrong answer(s)\n", nbad);
    GEOS_finish_r(ctx);
    return 0;
}
