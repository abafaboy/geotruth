/* geos-relateng-geometrycollection-semantics: RelateNG on valid GeometryCollections.
 * Public GEOS C API only. For every case: GEOSisValid of both operands, GEOSRelate(A,B) and
 * GEOSRelate(B,A) against the exact matrix (and its transpose), the named predicates of (A,B)
 * against the exact values, and GEOSRelate of the GEOSUnaryUnion of A (GEOS on its own union).
 * Build: cc -std=c11 repro.c $(geos-config --cflags) $(geos-config --clibs) -o repro
 */
#include <stdio.h>
#include <string.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

typedef struct { const char *id, *a, *b, *exact, *preds; } Case;
/* preds: intersects contains within covers coveredBy touches overlaps crosses equals (exact) */
static const Case CASES[] = {
  {"d1-far-point-contains", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))",
   "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))", "212FF1FF2", "110100000"},
  {"d1-own-polygon", "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))",
   "POLYGON ((0 0, 1 0, 0 1, 0 0))", "2F0F1FFF2", "110100000"},
  {"d1-own-polygon-within", "POLYGON ((0 0, 1 0, 0 1, 0 0))",
   "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))", "2FFF1F0F2", "101010000"},
  {"d1-interior-point-eb", "GEOMETRYCOLLECTION (POINT (2 2), POLYGON ((-1 -1, 5 -1, 5 5, -1 5, -1 -1), (1 1, 3 1, 3 3, 1 3, 1 1)))",
   "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "2121F12F2", "100000100"},
  {"d1-line-covers-boundary-eb", "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 1 1, 0 1, 0 0), POINT (5 5))",
   "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))", "F10FFF2F2", "100001000"},
  {"d1-line-end-on-points", "LINESTRING (0 0, 1 0)",
   "GEOMETRYCOLLECTION (POINT (0 0), POINT (1 0), LINESTRING (5 5, 6 6))", "FF10FF102", "100001000"},
  {"d1-ring-within-point", "LINESTRING (0 0, 1 0, 0 1, 0 0)",
   "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))", "0F1FFF102", "100000010"},
  {"d1-testfile-closed-line", "GEOMETRYCOLLECTION (POLYGON ((3 2, 3 1, 1 0, 3 2)), MULTIPOINT ((3 4)))",
   "LINESTRING (3 4, 4 3, 3 4)", "0F2FF11F2", "100000010"},
  {"d1-testfile-line-ends", "LINESTRING (0 0, 1 0)",
   "GEOMETRYCOLLECTION (MULTIPOINT ((1 0), (0 0)), LINESTRING (5 5, 6 6))", "FF10FF102", "100001000"},
  {"d2-reflex-point", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))",
   "POINT (2 1)", "0F2FF1FF2", "110100000"},
  {"d2-reflex-point-swapped-elements", "GEOMETRYCOLLECTION (POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)), POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)))",
   "POINT (2 1)", "0F2FF1FF2", "110100000"},
  {"d2-reflex-line", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))",
   "LINESTRING (2 2, 2 0)", "102F01FF2", "110100000"},
  {"d2-adjacent-control", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((0 0, 2 1, 4 0, 0 0)))",
   "POINT (2 1)", "0F2FF1FF2", "110100000"},
  {"d2-testfile-gc-reflex", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))",
   "POINT (1 2)", "0F2FF1FF2", "110100000"},
  {"d2-testfile-gc-reflex-line", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))",
   "LINESTRING (1 2, 1 3)", "102FF1FF2", "110100000"},
  {"d3-frame-equals", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)), POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))",
   "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
  {"d3-frame-two-l-shapes", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 1 1, 1 3, 0 3, 0 0)), POLYGON ((3 3, 0 3, 0 2, 2 2, 2 0, 3 0, 3 3)))",
   "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
  {"d3-frame-control-polygon", "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0), (1 1, 1 2, 2 2, 2 1, 1 1))",
   "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
  {"d3-frame-control-center", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)), POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))",
   "POINT (1.5 1.5)", "FF2FF10F2", "000000000"},
  {"d3-no-boundary-vertex", "GEOMETRYCOLLECTION (POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2, 0 0, 1 1)))",
   "LINESTRING (5 5, 6 6)", "FF2FF1102", "000000000"},
  {"known-gc-overlap-as-b", "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))",
   "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))", "2FF11F212", "101010000"},
  {"known-empty-element", "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)",
   "POINT (5 5)", "FF1FF00F2", "000000000"},
};

static void transpose(const char *m, char *t) {
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) t[3 * i + j] = m[3 * j + i];
    t[9] = 0;
}

int main(void) {
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    static const char *PN[] = {"intersects", "contains", "within", "covers", "coveredBy", "touches", "overlaps", "crosses", "equals"};
    printf("GEOS %s\n", GEOSversion());
    int nwrong = 0;
    for (size_t k = 0; k < sizeof CASES / sizeof CASES[0]; k++) {
        const Case *c = &CASES[k];
        GEOSGeometry *a = GEOSWKTReader_read_r(h, r, c->a), *b = GEOSWKTReader_read_r(h, r, c->b);
        char *m1 = GEOSRelate_r(h, a, b), *m2 = GEOSRelate_r(h, b, a);
        char tr[10]; transpose(c->exact, tr);
        int got[9] = {GEOSIntersects_r(h, a, b), GEOSContains_r(h, a, b), GEOSWithin_r(h, a, b), GEOSCovers_r(h, a, b),
                      GEOSCoveredBy_r(h, a, b), GEOSTouches_r(h, a, b), GEOSOverlaps_r(h, a, b), GEOSCrosses_r(h, a, b), GEOSEquals_r(h, a, b)};
        const GEOSPreparedGeometry *pa = GEOSPrepare_r(h, a);
        int pgot[4] = {GEOSPreparedContains_r(h, pa, b), GEOSPreparedCovers_r(h, pa, b), GEOSPreparedWithin_r(h, pa, b), GEOSPreparedTouches_r(h, pa, b)};
        int pidx[4] = {1, 3, 2, 5};
        GEOSGeometry *ua = GEOSUnaryUnion_r(h, a);
        char *mu = ua ? GEOSRelate_r(h, ua, b) : NULL;
        int bad = strcmp(m1, c->exact) != 0 || strcmp(m2, tr) != 0;
        printf("\n[%s]\n  A = %s\n  B = %s\n  isValid(A) = %d, isValid(B) = %d\n", c->id, c->a, c->b,
               GEOSisValid_r(h, a), GEOSisValid_r(h, b));
        printf("  relate(A,B) = %s   exact %s%s\n", m1, c->exact, strcmp(m1, c->exact) ? "   <-- WRONG" : "");
        printf("  relate(B,A) = %s   exact %s%s\n", m2, tr, strcmp(m2, tr) ? "   <-- WRONG" : "");
        printf("  relate(unaryUnion(A),B) = %s%s\n", mu ? mu : "ERR", mu && strcmp(mu, c->exact) == 0 ? "   (= exact)" : "");
        for (int i = 0; i < 9; i++) {
            int want = c->preds[i] == '1';
            if (got[i] != want) { printf("  %s(A,B) = %d   exact %d   <-- WRONG\n", PN[i], got[i], want); bad = 1; }
        }
        for (int i = 0; i < 4; i++) {
            int want = c->preds[pidx[i]] == '1';
            if (pgot[i] != want) { printf("  prepared %s(A,B) = %d   exact %d   <-- WRONG\n", PN[pidx[i]], pgot[i], want); bad = 1; }
        }
        if (!bad) printf("  ok\n");
        nwrong += bad;
        GEOSFree_r(h, m1); GEOSFree_r(h, m2); if (mu) GEOSFree_r(h, mu);
        GEOSPreparedGeom_destroy_r(h, pa); if (ua) GEOSGeom_destroy_r(h, ua);
        GEOSGeom_destroy_r(h, a); GEOSGeom_destroy_r(h, b);
    }
    printf("\n%d of %zu cases wrong\n", nwrong, sizeof CASES / sizeof CASES[0]);
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
    return 0;
}
