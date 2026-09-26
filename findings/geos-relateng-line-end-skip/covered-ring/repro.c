/*
 * RelateNG (GEOS >= 3.13.1) no longer self-nodes a linear B when A is polygonal.
 * Cases 1-3: relate(polygon, lines) reports Boundary(A) x Exterior(B) = 1 although the
 * lines cover the polygon's boundary (a line end or vertex of B lies inside another B
 * segment that runs along A's boundary).
 * Cases 4-5: A's own ring self-touch (hole/shell, touching parts) with a line along the
 * touched edge: wrong contains/touches/covers.
 * Case 6: B is a GeometryCollection of overlapping polygons: wrong within.
 * GEOS 3.13.0 is right on all six.
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

static void check(const char *name, const char *a, const char *b, const char *expected)
{
    GEOSGeometry *ga = rd(a), *gb = rd(b);
    char *m = GEOSRelate_r(ctx, ga, gb);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(ctx, ga);
    char *pm = GEOSPreparedRelate_r(ctx, pa, gb);
    int ok = strcmp(m, expected) == 0, pok = strcmp(pm, expected) == 0;
    nwrong += !ok + !pok;
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

/* contains / touches / covers (and the prepared forms) against the exact values */
static void pred(const char *name, const char *a, const char *b, int contains, int touches, int covers)
{
    GEOSGeometry *ga = rd(a), *gb = rd(b);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(ctx, ga);
    int v[6] = {GEOSContains_r(ctx, ga, gb), GEOSTouches_r(ctx, ga, gb), GEOSCovers_r(ctx, ga, gb),
                GEOSPreparedContains_r(ctx, pa, gb), GEOSPreparedTouches_r(ctx, pa, gb),
                GEOSPreparedCovers_r(ctx, pa, gb)};
    int e[6] = {contains, touches, covers, contains, touches, covers};
    const char *n[6] = {"contains", "touches", "covers", "preparedContains", "preparedTouches", "preparedCovers"};
    printf("  %s:", name);
    for (int i = 0; i < 6; i++) {
        printf(" %s=%d%s", n[i], v[i], v[i] == e[i] ? "" : "(WRONG)");
        nwrong += v[i] != e[i];
    }
    printf("\n");
    GEOSPreparedGeom_destroy_r(ctx, pa);
    GEOSGeom_destroy_r(ctx, ga);
    GEOSGeom_destroy_r(ctx, gb);
}

int main(void)
{
    ctx = GEOS_init_r();
    printf("GEOS %s\n\n", GEOSversion());

    const char *A = "POLYGON ((0 0, 2 0, 1 1, 0 0))";
    const char *B = "MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))";

    check("case 1: B = A's boundary ring + a segment starting at (1 0) on it", A, B, "FF210F102");
    {
        GEOSGeometry *ga = rd(A), *gb = rd(B), *bd = GEOSBoundary_r(ctx, ga);
        char c = GEOSCovers_r(ctx, gb, bd);
        char p = GEOSRelatePattern_r(ctx, ga, gb, "*****F***");
        nwrong += (c != 1) + (p != 1);
        printf("  covers(B, boundary(A))          = %d   expected 1   %s\n", c, c == 1 ? "ok" : "WRONG");
        printf("  relatePattern(A, B, \"*****F***\") = %d   expected 1   %s\n", p, p == 1 ? "ok" : "WRONG");
        GEOSGeom_destroy_r(ctx, bd);
        GEOSGeom_destroy_r(ctx, ga);
        GEOSGeom_destroy_r(ctx, gb);
    }
    check("case 1, operands swapped (expected = transpose)", B, A, "F11F002F2");
    check("case 1 with (1 0) added as a vertex of B's ring (same point sets)", A,
          "MULTILINESTRING ((0 0, 1 0, 2 0, 1 1, 0 0), (1 0, 1 -1))", "FF210F102");
    printf("\n");
    check("case 2: the same with a rectangle",
          "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))",
          "MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))", "FF210F102");
    check("case 3: B is a single self-touching LineString", A,
          "LINESTRING (0 0, 2 0, 1 1, 0 0, 1 -1, 1 0)", "FF210F1F2");

    printf("\n");
    /* The same missing node sections at a ring self-touch of A: since 3.13.1 these
       polygon/line pairs are no longer fully noded either, and named predicates go wrong. */
    check("case 4: polygon whose hole touches the shell at (2 0), vs the shell's bottom edge",
          "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
          "LINESTRING (0 0, 4 0)", "FF2101FF2");
    pred("case 4", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
         "LINESTRING (0 0, 4 0)", 0, 1, 1);
    check("case 5: MultiPolygon whose parts touch at (1 2), vs the square's top edge",
          "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
          "LINESTRING (0 2, 2 2)", "FF2101FF2");
    pred("case 5", "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
         "LINESTRING (0 2, 2 2)", 0, 1, 1);

    printf("\n");
    /* A GeometryCollection of overlapping polygons as operand B is not self-noded either */
    check("case 6: polygon inside the union of two overlapping polygons of a GC",
          "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))",
          "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))",
          "2FF11F212");
    {
        GEOSGeometry *ga = rd("POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))");
        GEOSGeometry *gb = rd("GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))");
        char w = GEOSWithin_r(ctx, ga, gb), c = GEOSContains_r(ctx, gb, ga);
        nwrong += (w != 1) + (c != 1);
        printf("  case 6: within(A, B)=%d%s contains(B, A)=%d%s\n", w, w == 1 ? "" : "(WRONG)", c, c == 1 ? "" : "(WRONG)");
        GEOSGeom_destroy_r(ctx, ga);
        GEOSGeom_destroy_r(ctx, gb);
    }

    printf("\n%d wrong result(s)\n", nwrong);
    GEOS_finish_r(ctx);
    return 0;
}
