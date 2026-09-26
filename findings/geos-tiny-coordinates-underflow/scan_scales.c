/*
 * Runs the checks of repro.c for the unit S = 1e<k>, k = -320 .. 307, and prints,
 * for each check, the ranges of k where GEOS gives a wrong answer.
 * The expected answers do not depend on k (the shapes are the same).
 *
 * Uses only the public GEOS C API.
 *   cc scan_scales.c $(geos-config --cflags) $(geos-config --clibs) -o scan_scales && ./scan_scales
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <geos_c.h>

static GEOSContextHandle_t ctx;
static void quiet(const char *m, void *u) { (void)m; (void)u; }

static void subst(char *out, size_t n, const char *tmpl, const char *unit)
{
    size_t k = 0, ul = strlen(unit);
    for (const char *p = tmpl; *p && k + ul + 1 < n; p++) {
        if (*p == 'S') { memcpy(out + k, unit, ul); k += ul; }
        else out[k++] = *p;
    }
    out[k] = 0;
}

static GEOSGeometry *rd(const char *tmpl, const char *unit)
{
    char w[512];
    subst(w, sizeof w, tmpl, unit);
    GEOSWKTReader *r = GEOSWKTReader_create_r(ctx);
    GEOSGeometry *g = GEOSWKTReader_read_r(ctx, r, w);
    GEOSWKTReader_destroy_r(ctx, r);
    return g;
}

/* vertex-by-vertex equality after normalization, each ordinate within tol.
 * (Compares ordinates directly: GEOSEqualsExact with a tolerance uses distances,
 * which themselves underflow/overflow at these scales.) */
static int same(GEOSGeometry *got, GEOSGeometry *exp, double tol)
{
    if (!got) return 0;
    GEOSNormalize_r(ctx, got);
    GEOSNormalize_r(ctx, exp);
    if (tol == 0.0) return GEOSEqualsExact_r(ctx, got, exp, 0.0) == 1;
    if (GEOSGeomTypeId_r(ctx, got) != GEOS_POLYGON || GEOSGetNumInteriorRings_r(ctx, got) != 0)
        return 0;
    const GEOSCoordSequence *cg = GEOSGeom_getCoordSeq_r(ctx, GEOSGetExteriorRing_r(ctx, got));
    const GEOSCoordSequence *ce = GEOSGeom_getCoordSeq_r(ctx, GEOSGetExteriorRing_r(ctx, exp));
    unsigned ng = 0, ne = 0;
    GEOSCoordSeq_getSize_r(ctx, cg, &ng);
    GEOSCoordSeq_getSize_r(ctx, ce, &ne);
    if (ng != ne) return 0;
    for (unsigned j = 0; j < ng; j++) {
        double gx, gy, ex, ey;
        GEOSCoordSeq_getXY_r(ctx, cg, j, &gx, &gy);
        GEOSCoordSeq_getXY_r(ctx, ce, j, &ex, &ey);
        if (!(fabs(gx - ex) <= tol && fabs(gy - ey) <= tol)) return 0;
    }
    return 1;
}

#define NCHECK 9
static const char *names[NCHECK] = {
    "orientationIndex((0 0),(1S 0),(0 1S)) != 0",
    "isValid(T)", "isValid(H)", "contains(A, P)", "relate(A, B) = 212101212",
    "intersection(A, B) exact", "union(A, B) exact",
    "intersection(A, B) vertices within 1e-9*S", "union(A, B) vertices within 1e-9*S"};

int main(void)
{
    ctx = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(ctx, quiet, NULL);
    printf("GEOS %s\n", GEOSversion());
    int lo = -320, hi = 307;  /* 4e308 would overflow to inf */
    int bad[NCHECK][700];
    for (int k = lo; k <= hi; k++) {
        char unit[16];
        snprintf(unit, sizeof unit, "e%d", k);
        char buf[32];
        snprintf(buf, sizeof buf, "1%s", unit);
        double s = strtod(buf, NULL);
        GEOSGeometry *t = rd("POLYGON ((0 0, 1S 0, 0 1S, 0 0))", unit);
        GEOSGeometry *h = rd("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), (1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit);
        GEOSGeometry *a = rd("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))", unit);
        GEOSGeometry *p = rd("POINT (1S 1S)", unit);
        GEOSGeometry *b = rd("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))", unit);
        GEOSGeometry *ei = rd("POLYGON ((1S 1S, 2S 1S, 2S 2S, 1S 2S, 1S 1S))", unit);
        GEOSGeometry *eu = rd("POLYGON ((0 0, 2S 0, 2S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 2S, 0 2S, 0 0))", unit);
        int i = k - lo;
        bad[0][i] = GEOSOrientationIndex_r(ctx, 0, 0, s, 0, 0, s) == 0;
        bad[1][i] = GEOSisValid_r(ctx, t) != 1;
        bad[2][i] = GEOSisValid_r(ctx, h) != 1;
        bad[3][i] = GEOSContains_r(ctx, a, p) != 1;
        char *im = GEOSRelate_r(ctx, a, b);
        bad[4][i] = !im || strcmp(im, "212101212") != 0;
        if (im) GEOSFree_r(ctx, im);
        GEOSGeometry *gi = GEOSIntersection_r(ctx, a, b);
        GEOSGeometry *gu = GEOSUnion_r(ctx, a, b);
        bad[5][i] = !same(gi, ei, 0.0);
        bad[6][i] = !same(gu, eu, 0.0);
        bad[7][i] = !same(gi, ei, 1e-9 * s);
        bad[8][i] = !same(gu, eu, 1e-9 * s);
        GEOSGeometry *all[] = {t, h, a, p, b, ei, eu, gi, gu};
        for (size_t j = 0; j < sizeof all / sizeof *all; j++) if (all[j]) GEOSGeom_destroy_r(ctx, all[j]);
    }
    for (int c = 0; c < NCHECK; c++) {
        printf("  %-44s wrong for S = 1e<k>, k in:", names[c]);
        int any = 0;
        for (int k = lo; k <= hi; k++) {
            if (!bad[c][k - lo]) continue;
            int e = k;
            while (e + 1 <= hi && bad[c][e + 1 - lo]) e++;
            printf(" [%d, %d]", k, e);
            any = 1;
            k = e;
        }
        printf("%s\n", any ? "" : " none");
    }
    GEOS_finish_r(ctx);
    return 0;
}
