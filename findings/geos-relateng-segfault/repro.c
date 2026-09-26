/* GEOS RelateNG crashes (SIGSEGV) on valid GeometryCollections that contain an EMPTY
 * element.  Uses only the public reentrant C API.
 *
 * Every call runs in a forked child so that one crash does not hide the others; the
 * parent prints the answer or the signal.  Each case has a control: the same point set
 * with the EMPTY element removed (an empty element adds no points, so the DE-9IM
 * matrix cannot change).
 *
 * Build: cc -std=c11 -O1 repro.c -o repro $(geos-config --cflags) $(geos-config --clibs)
 */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <sys/wait.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

typedef struct { const char *name, *a, *b, *expected; } Case;

static const Case CASES[] = {
    /* 1: AdjacentEdgeLocator walks the 0-point shell of POLYGON EMPTY */
    {"1  point on the shared edge of two squares, GC has a POLYGON EMPTY",
     "POINT (2 1)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)",
     "0FFFFF212"},
    {"1c control: same GC without the POLYGON EMPTY",
     "POINT (2 1)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)))",
     "0FFFFF212"},
    /* 2: GC dimension taken from the empty LineString; LinearBoundary is null */
    {"2  GC(point, LINESTRING EMPTY) vs POINT EMPTY",
     "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)",
     "POINT EMPTY",
     "FF0FFFFF2"},
    {"2c control: the point alone",
     "POINT (0 0)",
     "POINT EMPTY",
     "FF0FFFFF2"},
    /* 3: same cause as 2, no crash: wrong exterior entries */
    {"3  GC(line, POLYGON EMPTY) vs a disjoint point (no crash, wrong matrix)",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)",
     "POINT (5 5)",
     "FF1FF00F2"},
    {"3c control: the line alone",
     "LINESTRING (0 0, 1 0)",
     "POINT (5 5)",
     "FF1FF00F2"},
};

enum { OP_RELATE_AB, OP_RELATE_BA, OP_INTERSECTS, OP_CONTAINS_BA, OP_WITHIN,
       OP_TOUCHES, OP_RELATE_PATTERN, OP_PREP_COVERS_BA, OP_COUNT };
static const char *OP_NAMES[OP_COUNT] = {
    "GEOSRelate(A,B)", "GEOSRelate(B,A)", "GEOSIntersects(A,B)", "GEOSContains(B,A)",
    "GEOSWithin(A,B)", "GEOSTouches(A,B)", "GEOSRelatePattern(A,B,\"T********\")",
    "GEOSPreparedCovers(prep B, A)"};

/* Runs one operation; writes its answer to buf.  Called in the child. */
static void run_op(int op, const Case *c, char *buf, size_t n)
{
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSGeometry *a = GEOSWKTReader_read_r(h, r, c->a);
    GEOSGeometry *b = GEOSWKTReader_read_r(h, r, c->b);
    char *m = NULL;
    char v = 2;
    switch (op) {
    case OP_RELATE_AB: m = GEOSRelate_r(h, a, b); break;
    case OP_RELATE_BA: m = GEOSRelate_r(h, b, a); break;
    case OP_INTERSECTS: v = GEOSIntersects_r(h, a, b); break;
    case OP_CONTAINS_BA: v = GEOSContains_r(h, b, a); break;
    case OP_WITHIN: v = GEOSWithin_r(h, a, b); break;
    case OP_TOUCHES: v = GEOSTouches_r(h, a, b); break;
    case OP_RELATE_PATTERN: v = GEOSRelatePattern_r(h, a, b, "T********"); break;
    case OP_PREP_COVERS_BA: {
        const GEOSPreparedGeometry *p = GEOSPrepare_r(h, b);
        v = GEOSPreparedCovers_r(h, p, a);
        GEOSPreparedGeom_destroy_r(h, p);
        break;
    }
    }
    if (m) {
        snprintf(buf, n, "%s", m);
        GEOSFree_r(h, m);
    } else {
        snprintf(buf, n, "%s", v == 1 ? "true" : v == 0 ? "false" : "exception");
    }
    GEOSGeom_destroy_r(h, a);
    GEOSGeom_destroy_r(h, b);
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
}

/* Forks, runs the op in the child, returns the child's answer or the signal. */
static void isolated(int op, const Case *c, char *out, size_t n)
{
    int fd[2];
    if (pipe(fd) != 0) { perror("pipe"); exit(1); }
    fflush(stdout);
    pid_t pid = fork();
    if (pid == 0) {
        char buf[64] = "";
        close(fd[0]);
        run_op(op, c, buf, sizeof buf);
        if (write(fd[1], buf, strlen(buf)) < 0) _exit(3);
        _exit(0);
    }
    close(fd[1]);
    ssize_t k = read(fd[0], out, n - 1);
    out[k > 0 ? k : 0] = '\0';
    close(fd[0]);
    int status = 0;
    waitpid(pid, &status, 0);
    if (WIFSIGNALED(status))
        snprintf(out, n, "CRASH (signal %d, %s)", WTERMSIG(status), strsignal(WTERMSIG(status)));
}

static void transpose(const char *m, char *t)
{
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) t[3 * j + i] = m[3 * i + j];
    t[9] = '\0';
}

int main(void)
{
    printf("GEOS %s\n", GEOSversion());
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    for (size_t i = 0; i < sizeof CASES / sizeof CASES[0]; i++) {
        const Case *c = &CASES[i];
        GEOSGeometry *a = GEOSWKTReader_read_r(h, r, c->a);
        GEOSGeometry *b = GEOSWKTReader_read_r(h, r, c->b);
        char et[10];
        transpose(c->expected, et);
        printf("\ncase %s\n  A = %s\n  B = %s\n", c->name, c->a, c->b);
        printf("  GEOSisValid(A) = %d, GEOSisValid(B) = %d\n",
               GEOSisValid_r(h, a), GEOSisValid_r(h, b));
        printf("  expected relate(A,B) = %s, relate(B,A) = %s\n", c->expected, et);
        for (int op = 0; op < OP_COUNT; op++) {
            char out[96];
            isolated(op, c, out, sizeof out);
            const char *mark = "";
            if (op == OP_RELATE_AB) mark = strcmp(out, c->expected) ? "   <-- WRONG" : "   ok";
            if (op == OP_RELATE_BA) mark = strcmp(out, et) ? "   <-- WRONG" : "   ok";
            if (!strncmp(out, "CRASH", 5)) mark = "   <-- CRASH";
            printf("  %-38s %s%s\n", OP_NAMES[op], out, mark);
        }
        GEOSGeom_destroy_r(h, a);
        GEOSGeom_destroy_r(h, b);
    }
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
    return 0;
}
