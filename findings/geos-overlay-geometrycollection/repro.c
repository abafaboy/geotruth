/* GEOS overlay (GEOSSymDifference / GEOSDifference / GEOSIntersection) gives wrong
 * results or throws AssertionFailedException when an operand is a GeometryCollection
 * that HeuristicOverlay hands to StructuredCollection (a mixed-dimension GC, or a GC
 * that contains a polygon, even an empty one).  Uses only the public reentrant C API.
 *
 *   1  symdifference: B's lower-dimensional parts are dropped, A's kept even where B
 *      covers them                       (StructuredCollection::doSymDifference)
 *   2  difference: A's points on B's lines survive (StructuredCollection::doDifference)
 *   3  AssertionFailedException for an operand with no non-empty element
 *   4  (secondary) the GC's lines are noded on their own before the overlay, so a
 *      rounded node moves them off exact coincidences with the other operand
 *   5  (minor) a nested GEOMETRYCOLLECTION EMPTY makes a lineal GC "mixed-dimension"
 *
 * For every case the program prints
 *   - GEOSisValid of both operands,
 *   - the result of the public function (GEOSSymDifference_r etc.),
 *   - the exact result and GEOSEquals_r(result, exact) (GEOS's own point-set equality),
 *   - the same operation through the *Prec_r function with gridSize = 0, which calls
 *     OverlayNGRobust directly (no HeuristicOverlay), as a control (OverlayNG proper
 *     requires homogeneous collections, so it may reject a mixed-dimension GC),
 *   - a GEOS predicate that shows GEOS itself locates the point correctly (where useful).
 *
 * Build: cc -std=c11 -O1 repro.c -o repro $(geos-config --cflags) $(geos-config --clibs)
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

enum { INTERSECTION, DIFFERENCE, SYMDIFFERENCE };
static const char *OPN[] = {"GEOSIntersection", "GEOSDifference", "GEOSSymDifference"};
static const char *OPP[] = {"GEOSIntersectionPrec", "GEOSDifferencePrec", "GEOSSymDifferencePrec"};

typedef struct {
    const char *name, *a, *b;
    int op;
    const char *exact;   /* exact result (geotruth; hand-checked in ISSUE.md) */
    const char *check;   /* optional: a GEOS predicate to print, "intersects:P|Q" or "equals:P|Q" */
} Case;

static const Case CASES[] = {
    /* --- 1. symdifference drops B's lower-dimensional parts ------------------------ */
    {"1a symdifference, A = GC with one polygon (a simple GC), B = point outside it",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "POINT (3 3)", SYMDIFFERENCE,
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))",
     "intersects:POLYGON ((0 0, 4 0, 0 4, 0 0))|POINT (3 3)"},
    {"1a' control: operands swapped",
     "POINT (3 3)", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", SYMDIFFERENCE,
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))", NULL},
    {"1a\" control: the polygon not wrapped in a GC",
     "POLYGON ((0 0, 4 0, 0 4, 0 0))", "POINT (3 3)", SYMDIFFERENCE,
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))", NULL},
    {"1b symdifference, A = GC(POLYGON EMPTY) (a simple GC), B = point",
     "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", SYMDIFFERENCE,
     "POINT (1 1)", NULL},
    {"1b' control: POLYGON EMPTY not wrapped in a GC",
     "POLYGON EMPTY", "POINT (1 1)", SYMDIFFERENCE, "POINT (1 1)", NULL},
    {"1c symdifference, B = mixed GC (line + point), A = point on B's line",
     "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", SYMDIFFERENCE,
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))",
     "intersects:POINT (1 0)|LINESTRING (0 0, 2 0)"},
    {"1c' control: operands swapped",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", "POINT (1 0)", SYMDIFFERENCE,
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", NULL},

    {"1d symdifference of two equal point sets (A = square + a line inside it, B = square)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", SYMDIFFERENCE, "POLYGON EMPTY",
     "equals:GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))"
     "|POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"},

    /* --- 2. difference ignores B's lines when removing A's points ------------------ */
    {"2a difference, A = point on the line of the mixed GC B",
     "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", DIFFERENCE,
     "POINT EMPTY", "intersects:POINT (1 0)|LINESTRING (0 0, 2 0)"},
    {"2a' control: B's line alone",
     "POINT (1 0)", "LINESTRING (0 0, 2 0)", DIFFERENCE, "POINT EMPTY", NULL},

    /* --- 3. AssertionFailedException for an empty operand -------------------------- */
    {"3a intersection, A = GC(POLYGON EMPTY) (a simple GC), B = point",
     "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", INTERSECTION, "POINT EMPTY", NULL},
    {"3a' control: POLYGON EMPTY not wrapped in a GC",
     "POLYGON EMPTY", "POINT (1 1)", INTERSECTION, "POINT EMPTY", NULL},
    {"3b intersection, A = POINT EMPTY, B = GC with one polygon (a simple GC)",
     "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", INTERSECTION,
     "POINT EMPTY", NULL},
    {"3c difference, A = POINT EMPTY, B = GC with one polygon",
     "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", DIFFERENCE,
     "POINT EMPTY", NULL},
    {"3d intersection, A = mixed GC (point + line), B = MULTIPOLYGON EMPTY",
     "GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))", "MULTIPOLYGON EMPTY",
     INTERSECTION, "LINESTRING EMPTY", NULL},

    /* --- 4. (secondary) the GC's lines are noded on their own first ---------------- */
    {"4a intersection, A = point on a line of B; B's lines cross at (1.2 3.2), not a double",
     "POINT (3 2)", "GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9))",
     INTERSECTION, "POINT (3 2)", "intersects:POINT (3 2)|LINESTRING (0 4, 6 0)"},
    {"4a' control: B's lines as a MULTILINESTRING (OverlayNG proper)",
     "POINT (3 2)", "MULTILINESTRING ((0 2, 2 4), (0 4, 6 0))",
     INTERSECTION, "POINT (3 2)", NULL},
    {"4b intersection, A = segment lying on a line of B",
     "LINESTRING (3 2, 6 0)", "GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9))",
     INTERSECTION, "LINESTRING (3 2, 6 0)", NULL},
    {"4b' control: B's lines as a MULTILINESTRING (OverlayNG proper)",
     "LINESTRING (3 2, 6 0)", "MULTILINESTRING ((0 2, 2 4), (0 4, 6 0))",
     INTERSECTION, "LINESTRING (3 2, 6 0)", NULL},

    /* --- 5. (minor) a nested GEOMETRYCOLLECTION EMPTY in a lineal GC --------------- */
    {"5a intersection, B = GC(line, GEOMETRYCOLLECTION EMPTY)",
     "LINESTRING (0 0, 1 1)", "GEOMETRYCOLLECTION (LINESTRING (0 1, 1 0), GEOMETRYCOLLECTION EMPTY)",
     INTERSECTION, "POINT (0.5 0.5)", NULL},
    {"5a' control: POINT EMPTY instead of GEOMETRYCOLLECTION EMPTY",
     "LINESTRING (0 0, 1 1)", "GEOMETRYCOLLECTION (LINESTRING (0 1, 1 0), POINT EMPTY)",
     INTERSECTION, "POINT (0.5 0.5)", NULL},
};

static char errbuf[1024];
static void on_error(const char *fmt, void *userdata)
{
    (void)userdata;
    snprintf(errbuf, sizeof errbuf, "%s", fmt);
}

static GEOSGeometry *run(GEOSContextHandle_t h, int op, int prec,
                         const GEOSGeometry *a, const GEOSGeometry *b)
{
    errbuf[0] = '\0';
    if (!prec) {
        switch (op) {
        case INTERSECTION: return GEOSIntersection_r(h, a, b);
        case DIFFERENCE: return GEOSDifference_r(h, a, b);
        default: return GEOSSymDifference_r(h, a, b);
        }
    }
    switch (op) {
    case INTERSECTION: return GEOSIntersectionPrec_r(h, a, b, 0.0);
    case DIFFERENCE: return GEOSDifferencePrec_r(h, a, b, 0.0);
    default: return GEOSSymDifferencePrec_r(h, a, b, 0.0);
    }
}

static void show(GEOSContextHandle_t h, GEOSWKTWriter *w, const char *label, int prec,
                 GEOSGeometry *res, const GEOSGeometry *exact)
{
    if (!res) {
        /* OverlayNG proper (the *Prec_r route) documents that its inputs must be
         * homogeneous: rejecting a mixed-dimension GC there is documented behaviour */
        const char *mark = !strstr(errbuf, "mixed-dimension") ? "   <-- WRONG"
            : prec ? "   (documented: OverlayNG rejects a mixed-dimension GC)"
                   : "   <-- EXCEPTION";
        printf("  %-34s EXCEPTION: %s%s\n", label, errbuf, mark);
        return;
    }
    char *s = GEOSWKTWriter_write_r(h, w, res);
    char eq = GEOSEquals_r(h, res, exact);
    int typed = GEOSGeomTypeId_r(h, res) == GEOSGeomTypeId_r(h, exact);
    const char *mark = eq != 1 ? "   <-- WRONG (point set differs)"
                     : (GEOSisEmpty_r(h, exact) && !typed) ? "   (same point set, other empty type)"
                     : "   ok";
    printf("  %-34s %s%s\n", label, s, mark);
    GEOSFree_r(h, s);
    GEOSGeom_destroy_r(h, res);
}

int main(void)
{
    printf("GEOS %s\n", GEOSversion());
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(h, on_error, NULL);
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(h);
    GEOSWKTWriter_setTrim_r(h, w, 1);
    for (size_t i = 0; i < sizeof CASES / sizeof CASES[0]; i++) {
        const Case *c = &CASES[i];
        GEOSGeometry *a = GEOSWKTReader_read_r(h, r, c->a);
        GEOSGeometry *b = GEOSWKTReader_read_r(h, r, c->b);
        GEOSGeometry *x = GEOSWKTReader_read_r(h, r, c->exact);
        printf("\ncase %s\n  A = %s\n  B = %s\n", c->name, c->a, c->b);
        printf("  GEOSisValid(A) = %d, GEOSisValid(B) = %d\n",
               GEOSisValid_r(h, a), GEOSisValid_r(h, b));
        printf("  exact %-28s %s\n", OPN[c->op], c->exact);
        char label[64];
        snprintf(label, sizeof label, "%s_r(A, B)", OPN[c->op]);
        show(h, w, label, 0, run(h, c->op, 0, a, b), x);
        snprintf(label, sizeof label, "%s_r(A, B, 0)", OPP[c->op]);
        show(h, w, label, 1, run(h, c->op, 1, a, b), x);
        if (c->check) {
            char p[512], *q;
            int eq = !strncmp(c->check, "equals:", 7);
            snprintf(p, sizeof p, "%s", strchr(c->check, ':') + 1);
            q = strchr(p, '|');
            *q++ = '\0';
            GEOSGeometry *gp = GEOSWKTReader_read_r(h, r, p);
            GEOSGeometry *gq = GEOSWKTReader_read_r(h, r, q);
            printf("  %s(%s, %s) = %d\n", eq ? "GEOSEquals_r" : "GEOSIntersects_r", p, q,
                   eq ? GEOSEquals_r(h, gp, gq) : GEOSIntersects_r(h, gp, gq));
            GEOSGeom_destroy_r(h, gp);
            GEOSGeom_destroy_r(h, gq);
        }
        GEOSGeom_destroy_r(h, a);
        GEOSGeom_destroy_r(h, b);
        GEOSGeom_destroy_r(h, x);
    }
    GEOSWKTWriter_destroy_r(h, w);
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
    return 0;
}
