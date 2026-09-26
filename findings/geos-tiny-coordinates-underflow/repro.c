/*
 * Tiny coordinates (|x| < ~1e-162): orientation tests underflow to "collinear",
 * which gives wrong isValid, wrong point-in-polygon, wrong predicates and wrong
 * overlay results for simple, valid polygons.
 *
 * Every case is run twice: with the unit "S" = e-200 (so "2S" is 2e-200) and,
 * as a control, with S = "" (so "2S" is 2). The two inputs are the same shapes;
 * all expected answers are identical.
 *
 * Uses only the public GEOS C API.
 *   cc repro.c $(geos-config --cflags) $(geos-config --clibs) -o repro && ./repro
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <geos_c.h>

static GEOSContextHandle_t ctx;
static int nbad = 0;
static char lastmsg[512];

static void on_error(const char *msg, void *userdata)
{
    (void)userdata;
    snprintf(lastmsg, sizeof lastmsg, "%s", msg);
}

/* Replace every 'S' in a template by the unit string ("e-200" or ""). */
static void subst(char *out, size_t n, const char *tmpl, const char *unit)
{
    size_t k = 0, ul = strlen(unit);
    for (const char *p = tmpl; *p && k + ul + 1 < n; p++) {
        if (*p == 'S') { memcpy(out + k, unit, ul); k += ul; }
        else out[k++] = *p;
    }
    out[k] = 0;
}

static GEOSGeometry *rd(const char *tmpl, const char *unit, char *wkt_out, size_t n)
{
    subst(wkt_out, n, tmpl, unit);
    GEOSWKTReader *r = GEOSWKTReader_create_r(ctx);
    GEOSGeometry *g = GEOSWKTReader_read_r(ctx, r, wkt_out);
    GEOSWKTReader_destroy_r(ctx, r);
    if (!g) { fprintf(stderr, "cannot parse %s\n", wkt_out); exit(1); }
    return g;
}

static char *wkt(const GEOSGeometry *g)
{
    GEOSGeometry *c = GEOSGeom_clone_r(ctx, g);
    GEOSNormalize_r(ctx, c);
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(ctx);
    GEOSWKTWriter_setTrim_r(ctx, w, 1);
    char *s = GEOSWKTWriter_write_r(ctx, w, c);
    GEOSWKTWriter_destroy_r(ctx, w);
    GEOSGeom_destroy_r(ctx, c);
    return s;
}

static const char *tf(char r) { return r == 1 ? "true" : r == 0 ? "false" : "EXCEPTION"; }

static void check_bool(const char *what, char got, int expected)
{
    int ok = (got == expected);
    if (!ok) nbad++;
    printf("  %-28s %-9s (expected %s)%s", what, tf(got), expected ? "true" : "false",
           ok ? "\n" : "  <-- WRONG");
    if (!ok && got == 2) printf(": %s", lastmsg);
    if (!ok) printf("\n");
}

static void check_str(const char *what, const char *got, const char *expected)
{
    int ok = got && strcmp(got, expected) == 0;
    if (!ok) nbad++;
    printf("  %-28s %s (expected %s)%s\n", what, got ? got : "NULL (exception)", expected,
           ok ? "" : "  <-- WRONG");
}

static double num(const char *tmpl, const char *unit)
{
    char buf[64];
    subst(buf, sizeof buf, tmpl, unit);
    return strtod(buf, NULL);
}

/* shortest decimal that round-trips */
static const char *fmt(double v, char *buf, size_t n)
{
    for (int prec = 15; prec <= 17; prec++) {
        snprintf(buf, n, "%.*g", prec, v);
        if (strtod(buf, NULL) == v) break;
    }
    return buf;
}

static void run(const char *unit)
{
    char w1[512], w2[512], w3[512], w4[512], exp[512];
    printf("===== unit S = \"%s\" =====\n", unit);

    /* 0. The two primitives everything else is built on. */
    double s1 = num("1S", unit), s2 = num("2S", unit), s3 = num("3S", unit);
    int oi = GEOSOrientationIndex_r(ctx, 0, 0, s1, 0, 0, s1);
    printf("GEOSOrientationIndex((0 0), (1S 0), (0 1S)) = %d%s\n", oi,
           oi == 0 ? "  <-- WRONG: the three points are not collinear" : "  (non-zero: not collinear)");
    if (oi == 0) nbad++;
    double cx = -1, cy = -1;
    int sxr = GEOSSegmentIntersection_r(ctx, s2, 0, s2, s2, s1, s1, s3, s1, &cx, &cy);
    if (sxr == 1)
    {
        char bx[32], by[32];
        printf("GEOSSegmentIntersection((2S 0)-(2S 2S), (1S 1S)-(3S 1S)) = 1, (%s %s)  (expected (2S 1S))%s\n",
               fmt(cx, bx, sizeof bx), fmt(cy, by, sizeof by), (cx == s2 && cy == s1) ? "" : "  <-- WRONG");
    }
    else
        printf("GEOSSegmentIntersection((2S 0)-(2S 2S), (1S 1S)-(3S 1S)) = %d  (expected 1, point (2S 1S))  <-- WRONG\n", sxr);
    if (!(sxr == 1 && cx == s2 && cy == s1)) nbad++;

    /* 1. A right triangle with legs of length S. Valid. */
    GEOSGeometry *t = rd("POLYGON ((0 0, 1S 0, 0 1S, 0 0))", unit, w1, sizeof w1);
    printf("T = %s\n", w1);
    check_bool("isValid(T)", GEOSisValid_r(ctx, t), 1);
    char *reason = GEOSisValidReason_r(ctx, t);
    printf("  %-28s %s\n", "isValidReason(T)", reason ? reason : "NULL (exception)");
    if (reason) GEOSFree_r(ctx, reason);

    /* 2. A square with a square hole strictly inside it. Valid. */
    GEOSGeometry *h = rd("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), "
                         "(1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit, w2, sizeof w2);
    printf("H = %s\n", w2);
    check_bool("isValid(H)", GEOSisValid_r(ctx, h), 1);

    /* 3. Point at the centre of a square. */
    GEOSGeometry *a = rd("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))", unit, w3, sizeof w3);
    GEOSGeometry *p = rd("POINT (1S 1S)", unit, w4, sizeof w4);
    printf("A = %s\nP = %s  (the centre of A)\n", w3, w4);
    check_bool("contains(A, P)", GEOSContains_r(ctx, a, p), 1);
    const GEOSPreparedGeometry *pa = GEOSPrepare_r(ctx, a);
    check_bool("prepared contains(A, P)", GEOSPreparedContains_r(ctx, pa, p), 1);
    char *im = GEOSRelate_r(ctx, a, p);
    check_str("relate(A, P)", im, "0F2FF1FF2");
    if (im) GEOSFree_r(ctx, im);

    /* 4. Two overlapping squares: A = [0,2S]^2, B = [1S,3S]^2. */
    GEOSGeometry *b = rd("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))", unit, w1, sizeof w1);
    printf("B = %s\n", w1);
    im = GEOSRelate_r(ctx, a, b);
    check_str("relate(A, B)", im, "212101212");
    if (im) GEOSFree_r(ctx, im);
    check_bool("intersects(A, B)", GEOSIntersects_r(ctx, a, b), 1);
    check_bool("overlaps(A, B)", GEOSOverlaps_r(ctx, a, b), 1);
    check_bool("touches(A, B)", GEOSTouches_r(ctx, a, b), 0);
    check_bool("prepared overlaps(A, B)", GEOSPreparedOverlaps_r(ctx, pa, b), 1);

    GEOSGeometry *i = GEOSIntersection_r(ctx, a, b);
    char *si = i ? wkt(i) : NULL;
    subst(exp, sizeof exp, "POLYGON ((1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit);
    check_str("intersection(A, B)", si, exp);
    GEOSGeometry *u = GEOSUnion_r(ctx, a, b);
    char *su = u ? wkt(u) : NULL;
    subst(exp, sizeof exp,
          "POLYGON ((0 0, 0 2S, 1S 2S, 1S 3S, 3S 3S, 3S 1S, 2S 1S, 2S 0, 0 0))", unit);
    check_str("union(A, B)", su, exp);
    printf("\n");

    if (si) GEOSFree_r(ctx, si);
    if (su) GEOSFree_r(ctx, su);
    if (i) GEOSGeom_destroy_r(ctx, i);
    if (u) GEOSGeom_destroy_r(ctx, u);
    GEOSPreparedGeom_destroy_r(ctx, pa);
    GEOSGeom_destroy_r(ctx, t);
    GEOSGeom_destroy_r(ctx, h);
    GEOSGeom_destroy_r(ctx, a);
    GEOSGeom_destroy_r(ctx, p);
    GEOSGeom_destroy_r(ctx, b);
}

int main(void)
{
    ctx = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(ctx, on_error, NULL);
    printf("GEOS %s\n\n", GEOSversion());
    run("");       /* control: coordinates 0..4 */
    run("e-200");  /* same shapes, coordinates 0..4e-200 */

    /* Threshold for the triangle T: valid down to about 1e-161. */
    printf("isValid(POLYGON ((0 0, s 0, 0 s, 0 0))) by s:\n");
    const char *ss[] = {"1e-150", "1e-155", "1e-160", "1e-161", "1.6e-162", "1.5e-162",
                        "1e-162", "1e-170", "1e-300", NULL};
    for (int k = 0; ss[k]; k++) {
        char w[256];
        snprintf(w, sizeof w, "POLYGON ((0 0, %s 0, 0 %s, 0 0))", ss[k], ss[k]);
        GEOSWKTReader *r = GEOSWKTReader_create_r(ctx);
        GEOSGeometry *g = GEOSWKTReader_read_r(ctx, r, w);
        GEOSWKTReader_destroy_r(ctx, r);
        char *reason = GEOSisValidReason_r(ctx, g);
        printf("  s = %-9s %s\n", ss[k], reason);
        GEOSFree_r(ctx, reason);
        GEOSGeom_destroy_r(ctx, g);
    }
    printf("\n%d wrong result(s)\n", nbad);
    GEOS_finish_r(ctx);
    return 0;
}
