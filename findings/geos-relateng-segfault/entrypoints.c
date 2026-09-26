/* Which GEOS C API entry points crash on the geos-relateng-segfault inputs.
 *
 * For each input pair, every relate / pattern / named predicate / prepared entry point is
 * called with (A,B) and with (B,A), each in a forked child, and the same calls are made on the
 * EMPTY-free control pair (the same point sets without the EMPTY element; an empty element adds
 * no points, so every answer should equal the control's).  Whether a named predicate crashes
 * depends on whether it reaches the located point before it can decide its answer, so the set
 * of crashing entry points differs between the point, line and polygon operands.
 *
 * Build: cc -std=c11 -O1 entrypoints.c -o entrypoints $(geos-config --cflags) $(geos-config --clibs)
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

#define SQUARES "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0))"
typedef struct { const char *name, *a, *b, *a_ctrl, *b_ctrl, *exact; } Case;
static const Case CASES[] = {
    {"crash 1, point operand", "POINT (2 1)",
     "GEOMETRYCOLLECTION (" SQUARES ", POLYGON EMPTY)",
     "POINT (2 1)", "GEOMETRYCOLLECTION (" SQUARES ")", "0FFFFF212"},
    {"crash 1, line operand", "LINESTRING (1 1, 3 1)",
     "GEOMETRYCOLLECTION (" SQUARES ", POLYGON EMPTY)",
     "LINESTRING (1 1, 3 1)", "GEOMETRYCOLLECTION (" SQUARES ")", "1FF0FF212"},
    {"crash 1, polygon operand", "POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))",
     "GEOMETRYCOLLECTION (" SQUARES ", POLYGON EMPTY)",
     "POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))", "GEOMETRYCOLLECTION (" SQUARES ")", "2FF11F212"},
    {"crash 2", "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)", "POINT EMPTY",
     "POINT (0 0)", "POINT EMPTY", "FF0FFFFF2"},
};

enum { REL, RP_T, RP_ALL, RP_DISJ, RP_EXACT, RBNR, INTS, DISJ, TOUCH, CROSS, WITHIN, CONT, OVER,
       EQ, COV, COVBY, P_INTS, P_DISJ, P_TOUCH, P_CROSS, P_WITHIN, P_CONT, P_CONTP, P_OVER, P_COV,
       P_COVBY, P_REL, P_RP_DISJ, NOPS };
static const char *NAMES[NOPS] = {
    "GEOSRelate", "GEOSRelatePattern T********", "GEOSRelatePattern *********",
    "GEOSRelatePattern FF*FF****", "GEOSRelatePattern <exact(A,B)>",
    "GEOSRelateBoundaryNodeRule OGC", "GEOSIntersects", "GEOSDisjoint", "GEOSTouches",
    "GEOSCrosses", "GEOSWithin", "GEOSContains", "GEOSOverlaps", "GEOSEquals", "GEOSCovers",
    "GEOSCoveredBy", "GEOSPreparedIntersects", "GEOSPreparedDisjoint", "GEOSPreparedTouches",
    "GEOSPreparedCrosses", "GEOSPreparedWithin", "GEOSPreparedContains",
    "GEOSPreparedContainsProperly", "GEOSPreparedOverlaps", "GEOSPreparedCovers",
    "GEOSPreparedCoveredBy", "GEOSPreparedRelate", "GEOSPreparedRelatePattern FF*FF****"};

/* Runs one entry point on (x, y); the prepared ones prepare x.  Called in the child. */
static void run_op(int op, const char *wx, const char *wy, const char *pat, char *buf, size_t n)
{
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSGeometry *x = GEOSWKTReader_read_r(h, r, wx), *y = GEOSWKTReader_read_r(h, r, wy);
    const GEOSPreparedGeometry *p = op >= P_INTS ? GEOSPrepare_r(h, x) : NULL;
    char *m = NULL;
    char v = 2;
    switch (op) {
    case REL: m = GEOSRelate_r(h, x, y); break;
    case RP_T: v = GEOSRelatePattern_r(h, x, y, "T********"); break;
    case RP_ALL: v = GEOSRelatePattern_r(h, x, y, "*********"); break;
    case RP_DISJ: v = GEOSRelatePattern_r(h, x, y, "FF*FF****"); break;
    case RP_EXACT: v = GEOSRelatePattern_r(h, x, y, pat); break;
    case RBNR: m = GEOSRelateBoundaryNodeRule_r(h, x, y, GEOSRELATE_BNR_OGC); break;
    case INTS: v = GEOSIntersects_r(h, x, y); break;
    case DISJ: v = GEOSDisjoint_r(h, x, y); break;
    case TOUCH: v = GEOSTouches_r(h, x, y); break;
    case CROSS: v = GEOSCrosses_r(h, x, y); break;
    case WITHIN: v = GEOSWithin_r(h, x, y); break;
    case CONT: v = GEOSContains_r(h, x, y); break;
    case OVER: v = GEOSOverlaps_r(h, x, y); break;
    case EQ: v = GEOSEquals_r(h, x, y); break;
    case COV: v = GEOSCovers_r(h, x, y); break;
    case COVBY: v = GEOSCoveredBy_r(h, x, y); break;
    case P_INTS: v = GEOSPreparedIntersects_r(h, p, y); break;
    case P_DISJ: v = GEOSPreparedDisjoint_r(h, p, y); break;
    case P_TOUCH: v = GEOSPreparedTouches_r(h, p, y); break;
    case P_CROSS: v = GEOSPreparedCrosses_r(h, p, y); break;
    case P_WITHIN: v = GEOSPreparedWithin_r(h, p, y); break;
    case P_CONT: v = GEOSPreparedContains_r(h, p, y); break;
    case P_CONTP: v = GEOSPreparedContainsProperly_r(h, p, y); break;
    case P_OVER: v = GEOSPreparedOverlaps_r(h, p, y); break;
    case P_COV: v = GEOSPreparedCovers_r(h, p, y); break;
    case P_COVBY: v = GEOSPreparedCoveredBy_r(h, p, y); break;
    case P_REL: m = GEOSPreparedRelate_r(h, p, y); break;
    case P_RP_DISJ: v = GEOSPreparedRelatePattern_r(h, p, y, "FF*FF****"); break;
    }
    if (m) {
        snprintf(buf, n, "%s", m);
        GEOSFree_r(h, m);
    } else {
        snprintf(buf, n, "%s", v == 1 ? "true" : v == 0 ? "false" : "exception");
    }
    if (p) GEOSPreparedGeom_destroy_r(h, p);
    GEOSGeom_destroy_r(h, x);
    GEOSGeom_destroy_r(h, y);
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
}

/* Forks, runs the entry point in the child, returns the child's answer or the signal. */
static void isolated(int op, const char *wx, const char *wy, const char *pat, char *out, size_t n)
{
    int fd[2];
    if (pipe(fd) != 0) { perror("pipe"); exit(1); }
    fflush(stdout);
    pid_t pid = fork();
    if (pid == 0) {
        char buf[64] = "";
        close(fd[0]);
        run_op(op, wx, wy, pat, buf, sizeof buf);
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
        snprintf(out, n, "CRASH(%s)", WTERMSIG(status) == SIGSEGV ? "SIGSEGV" : strsignal(WTERMSIG(status)));
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
    printf("columns: (A,B) and (B,A) on the input; the same on the EMPTY-free control;\n"
           "prepared entry points prepare the first argument; '!' marks an answer that differs\n"
           "from the control's\n");
    for (size_t i = 0; i < sizeof CASES / sizeof CASES[0]; i++) {
        const Case *c = &CASES[i];
        char et[10];
        transpose(c->exact, et);
        printf("\n## %s\n  A = %s\n  B = %s\n  control: A = %s, B = %s\n"
               "  exact relate(A,B) = %s, relate(B,A) = %s\n",
               c->name, c->a, c->b, c->a_ctrl, c->b_ctrl, c->exact, et);
        printf("  %-36s %-16s %-16s %-11s %-11s\n", "entry point", "(A,B)", "(B,A)",
               "ctrl (A,B)", "ctrl (B,A)");
        for (int op = 0; op < NOPS; op++) {
            char ab[64], ba[64], cab[64], cba[64], sab[72], sba[72];
            isolated(op, c->a, c->b, c->exact, ab, sizeof ab);
            isolated(op, c->b, c->a, et, ba, sizeof ba);
            isolated(op, c->a_ctrl, c->b_ctrl, c->exact, cab, sizeof cab);
            isolated(op, c->b_ctrl, c->a_ctrl, et, cba, sizeof cba);
            snprintf(sab, sizeof sab, "%s%s", ab, strcmp(ab, cab) ? " !" : "");
            snprintf(sba, sizeof sba, "%s%s", ba, strcmp(ba, cba) ? " !" : "");
            printf("  %-36s %-16s %-16s %-11s %-11s\n", NAMES[op], sab, sba, cab, cba);
        }
    }
    return 0;
}
