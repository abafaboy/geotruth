/*
 * RelateNG: an element skipped by the "known exterior" optimisation in computeLineEnds
 * (cases 1-3) or computeAreaVertex (cases 4-5) never has its boundary recorded
 * (DE-9IM EB/BE = F instead of 0 or 1); the result depends on element order.
 *
 * Public GEOS C API only. Build and run:
 *   cc repro.c $(geos-config --cflags) $(geos-config --clibs) -o repro && ./repro
 */
#include <stdio.h>
#include <string.h>
#include <geos_c.h>

static GEOSContextHandle_t ctx;
static int nwrong = 0;

static GEOSGeometry *rd(const char *wkt)
{
    GEOSWKTReader *r = GEOSWKTReader_create_r(ctx);
    GEOSGeometry *g = GEOSWKTReader_read_r(ctx, r, wkt);
    GEOSWKTReader_destroy_r(ctx, r);
    return g;
}

static void wkt(const char *label, const GEOSGeometry *g)
{
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(ctx);
    GEOSWKTWriter_setTrim_r(ctx, w, 1);
    char *s = GEOSWKTWriter_write_r(ctx, w, g);
    printf("  %s%s\n", label, s);
    GEOSFree_r(ctx, s);
    GEOSWKTWriter_destroy_r(ctx, w);
}

/* relate(A, B) against the expected matrix; also the prepared relate */
static void check(const char *name, const char *a, const char *b, const char *expected)
{
    GEOSGeometry *ga = rd(a), *gb = rd(b);
    char *m = GEOSRelate_r(ctx, ga, gb);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(ctx, ga);
    char *pm = GEOSPreparedRelate_r(ctx, pa, gb);
    int ok = strcmp(m, expected) == 0, pok = strcmp(pm, expected) == 0;
    if (!ok) nwrong++;
    if (!pok) nwrong++;
    printf("%s\n  A = %s   (valid=%d)\n  B = %s   (valid=%d)\n", name, a,
           GEOSisValid_r(ctx, ga), b, GEOSisValid_r(ctx, gb));
    printf("  relate(A, B)         = %s   expected %s   %s\n", m, expected, ok ? "ok" : "WRONG");
    printf("  preparedRelate(A, B) = %s   expected %s   %s\n", pm, expected, pok ? "ok" : "WRONG");
    GEOSFree_r(ctx, m);
    GEOSFree_r(ctx, pm);
    GEOSPreparedGeom_destroy_r(ctx, pa);
    GEOSGeom_destroy_r(ctx, ga);
    GEOSGeom_destroy_r(ctx, gb);
}

int main(void)
{
    ctx = GEOS_init_r();
    printf("GEOS %s\n\n", GEOSversion());

    const char *P = "POINT (10 10)";
    const char *B1 = "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))";
    const char *B1swap = "MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))";

    check("case 1: B's boundary is {(5 5), (6 6)}, both far from A", P, B1, "FF0FFF102");
    /* GEOS's own view of B's boundary, and of the location of (5 5) */
    {
        GEOSGeometry *gb = rd(B1), *bd = GEOSBoundary_r(ctx, gb);
        GEOSGeometry *q = rd("POINT (5 5)");
        char *m = GEOSRelate_r(ctx, q, gb);
        wkt("GEOSBoundary(B)                 = ", bd);
        printf("  relate(POINT (5 5), B)          = %s   (row 1 'F0F': (5 5) is on B's boundary)\n", m);
        /* a pattern that asks for "disjoint, and B has a boundary point outside A" (EB = 0) */
        GEOSGeometry *ga = rd(P);
        char pat = GEOSRelatePattern_r(ctx, ga, gb, "FF*FF**0*");
        if (pat != 1) nwrong++;
        printf("  relatePattern(A, B, \"FF*FF**0*\") = %d   expected 1   %s\n", pat, pat == 1 ? "ok" : "WRONG");
        GEOSGeom_destroy_r(ctx, ga);
        GEOSFree_r(ctx, m);
        GEOSGeom_destroy_r(ctx, q);
        GEOSGeom_destroy_r(ctx, bd);
        GEOSGeom_destroy_r(ctx, gb);
    }
    check("case 1, B's elements swapped (same point set, same boundary)", P, B1swap, "FF0FFF102");
    check("case 1, operands swapped (expected = transpose)", B1, P, "FF1FF00F2");
    check("case 1, variant: the closed element is the degenerate (valid) line (0 0, 1 0, 0 0)", P,
          "MULTILINESTRING ((0 0, 1 0, 0 0), (5 5, 6 6))", "FF0FFF102");
    printf("\n");

    check("case 2: polygon target; (2 3) is shared by both elements (Mod-2 interior)",
          "POLYGON ((1 2, 4 0, 1 0, 1 2))",
          "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))", "1F2001102");
    check("case 2, operands swapped (expected = transpose)",
          "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))",
          "POLYGON ((1 2, 4 0, 1 0, 1 2))", "101F00212");
    check("case 3: the input of JTS issue #1175",
          "LINESTRING (10 10, 20 20)",
          "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (-1 0, 0 0))", "FF1FF0102");

    printf("\n");

    /* The same skip in computeAreaVertex (not covered by JTS #1200): the first polygon's
       first vertex (1 1) lies inside the second polygon, so it is an INTERIOR point of the
       collection; after it, the second polygon is skipped and A's boundary is never
       recorded against B's exterior. */
    check("case 4: GeometryCollection of overlapping squares, far from B",
          "GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
          "LINESTRING (10 10, 11 11)", "FF2FF1102");
    check("case 4, the two squares swapped",
          "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))",
          "LINESTRING (10 10, 11 11)", "FF2FF1102");
    check("case 4, operands swapped (expected = transpose)",
          "LINESTRING (10 10, 11 11)",
          "GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
          "FF1FF0212");

    printf("\n");

    /* The same skip, with no vertex of the first polygon on the collection's boundary: every
       vertex of the small square lies inside the big one. So choosing a better vertex per ring
       (the TODO in computeAreaVertex) cannot help here; the skip itself must change. */
    check("case 5: GeometryCollection of nested squares, far from B",
          "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))",
          "LINESTRING (10 10, 11 11)", "FF2FF1102");
    check("case 5, the two squares swapped",
          "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)))",
          "LINESTRING (10 10, 11 11)", "FF2FF1102");
    check("case 5, operands swapped (expected = transpose)",
          "LINESTRING (10 10, 11 11)",
          "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))",
          "FF1FF0212");

    printf("\n%d wrong result(s)\n", nwrong);
    GEOS_finish_r(ctx);
    return 0;
}
