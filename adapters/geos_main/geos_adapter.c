/*
 * GEOS (git main) adapter for the geometry bug hunt, written against the reentrant
 * GEOS C API (geos_c.h, *_r functions).  Implements the contract in ../../FORMAT.md:
 *
 *     geos_adapter CASES.jsonl > RESULTS.jsonl
 *
 * One output line per non-blank input line, in order.
 *
 * Robustness: by default every case runs in a forked child process that reports each
 * operation's result to the parent over a pipe as soon as it is computed.  If GEOS
 * crashes (signal) or hangs (per-operation timeout, SIGKILL), the parent records the
 * failure for that one operation in "errors" and continues with the next operation in
 * a fresh child, so a single bad case or operation never takes the run down and all
 * other fields are still reported.  `--no-fork` runs everything in-process (debugging).
 *
 * Environment:
 *   GEOS_ADAPTER_TIMEOUT   per-operation wall-clock limit in seconds (default 10)
 *   GEOS_ADAPTER_MEM_MB    address-space limit of each child in MiB (default 4096, 0 = none)
 *   GEOS_ADAPTER_TEST_FAULT  "crash:<key>" / "hang_:<key>": inject a fault (self-test only)
 */
#define _GNU_SOURCE
#include <errno.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

/* ------------------------------------------------------------------ operations */

enum {
    OP_VALID_A, OP_VALID_B,
    OP_INTERSECTS, OP_DISJOINT, OP_TOUCHES, OP_OVERLAPS, OP_CONTAINS, OP_COVERS,
    OP_WITHIN, OP_COVERED_BY, OP_EQUALS,
    OP_AREA_INTER, OP_AREA_UNION, OP_AREA_DIFF, OP_AREA_SYMDIFF,
    NOPS
};

static const char *OP_KEYS[NOPS] = {
    "valid_a", "valid_b",
    "intersects", "disjoint", "touches", "overlaps", "contains", "covers",
    "within", "covered_by", "equals",
    "area_inter", "area_union", "area_diff", "area_symdiff",
};

#define VALLEN 64    /* "true" / "false" / "null" / a %.17g double */
#define ERRLEN 1536  /* max length of one JSON-escaped error message (incl. quotes) */

typedef struct {
    int done;
    char val[VALLEN];
    char err[ERRLEN]; /* JSON string literal incl. quotes, or "" for no error */
} OpResult;

/* ------------------------------------------------------------------ small utils */

static void *xrealloc(void *p, size_t n)
{
    void *q = realloc(p, n ? n : 1);
    if (!q) {
        fprintf(stderr, "geos_adapter: out of memory\n");
        exit(2);
    }
    return q;
}

/* Write s as a JSON string literal (with quotes) into out[cap]; truncates long input. */
static void json_quote(char *out, size_t cap, const char *s)
{
    size_t o = 0;
    const size_t reserve = 12; /* room for an escape, the ellipsis, closing quote, NUL */
    out[o++] = '"';
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (o + reserve >= cap) {
            memcpy(out + o, "...", 3);
            o += 3;
            break;
        }
        unsigned char c = *p;
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c == '\n') {
            out[o++] = '\\'; out[o++] = 'n';
        } else if (c == '\r') {
            out[o++] = '\\'; out[o++] = 'r';
        } else if (c == '\t') {
            out[o++] = '\\'; out[o++] = 't';
        } else if (c < 0x20 || c == 0x7f) {
            o += (size_t)snprintf(out + o, cap - o, "\\u%04x", c);
        } else {
            out[o++] = (char)c; /* UTF-8 passes through unchanged */
        }
    }
    out[o++] = '"';
    out[o] = '\0';
}

/* Shortest decimal form that round-trips to the same double, always JSON-float-looking. */
static void fmt_double(char *out, size_t cap, double v)
{
    for (int prec = 15; prec <= 17; prec++) {
        snprintf(out, cap, "%.*g", prec, v);
        if (strtod(out, NULL) == v)
            break;
    }
    if (!strpbrk(out, ".eEn")) /* integral: make it read back as a float */
        strncat(out, ".0", cap - strlen(out) - 1);
}

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

/* ------------------------------------------------------------------ JSON input */

typedef struct {
    size_t n;    /* number of points */
    double *xy;  /* interleaved x, y */
} Ring;

typedef struct {
    size_t nrings;
    Ring *rings; /* shell first, then holes */
} Poly;

typedef struct {
    size_t npolys;
    Poly *polys;
} MPoly;

typedef struct {
    char *id_json;  /* raw JSON string token (with quotes) of "id", or NULL */
    int have_a, have_b;
    MPoly a, b;
} Case;

typedef struct {
    const char *start, *p, *end;
    char err[256];
} Parser;

static int perr(Parser *P, const char *fmt, ...)
{
    if (!P->err[0]) {
        va_list ap;
        va_start(ap, fmt);
        char tmp[200];
        vsnprintf(tmp, sizeof tmp, fmt, ap);
        va_end(ap);
        snprintf(P->err, sizeof P->err, "%s at byte %ld", tmp, (long)(P->p - P->start));
    }
    return 0;
}

static void ws(Parser *P)
{
    while (P->p < P->end && (*P->p == ' ' || *P->p == '\t' || *P->p == '\n' || *P->p == '\r'))
        P->p++;
}

static int peek(Parser *P)
{
    ws(P);
    return P->p < P->end ? (unsigned char)*P->p : -1;
}

static int expect(Parser *P, char c)
{
    if (peek(P) != (unsigned char)c)
        return perr(P, "expected '%c'", c);
    P->p++;
    return 1;
}

/* String token: returns the span including quotes (escapes kept verbatim). */
static int parse_string(Parser *P, const char **s, size_t *n)
{
    if (peek(P) != '"')
        return perr(P, "expected string");
    const char *start = P->p++;
    while (P->p < P->end && *P->p != '"') {
        if (*P->p == '\\')
            P->p++;
        P->p++;
    }
    if (P->p >= P->end)
        return perr(P, "unterminated string");
    P->p++;
    *s = start;
    *n = (size_t)(P->p - start);
    return 1;
}

static int is_num_char(char c)
{
    return (c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E' ||
           (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); /* NaN / Infinity */
}

/* glibc strtod rounds correctly, so JSON numbers map to the exact intended doubles. */
static int parse_number(Parser *P, double *v)
{
    ws(P);
    const char *s = P->p;
    while (P->p < P->end && is_num_char(*P->p))
        P->p++;
    size_t n = (size_t)(P->p - s);
    if (n == 0 || n > 400)
        return perr(P, "expected number");
    char buf[512];
    memcpy(buf, s, n);
    buf[n] = '\0';
    char *e;
    errno = 0;
    *v = strtod(buf, &e);
    if (*e != '\0')
        return perr(P, "bad number '%.40s'", buf);
    return 1;
}

static int skip_value(Parser *P, int depth)
{
    if (depth > 64)
        return perr(P, "nesting too deep");
    int c = peek(P);
    if (c == '"') {
        const char *s; size_t n;
        return parse_string(P, &s, &n);
    }
    if (c == '[' || c == '{') {
        char close = c == '[' ? ']' : '}';
        P->p++;
        if (peek(P) == close) {
            P->p++;
            return 1;
        }
        for (;;) {
            if (c == '{') {
                const char *s; size_t n;
                if (!parse_string(P, &s, &n) || !expect(P, ':'))
                    return 0;
            }
            if (!skip_value(P, depth + 1))
                return 0;
            int d = peek(P);
            if (d == ',') { P->p++; continue; }
            if (d == close) { P->p++; return 1; }
            return perr(P, "expected ',' or '%c'", close);
        }
    }
    static const char *LITERALS[] = {"true", "false", "null"};
    for (int i = 0; i < 3; i++) {
        size_t n = strlen(LITERALS[i]);
        if ((size_t)(P->end - P->p) >= n && !memcmp(P->p, LITERALS[i], n) &&
            ((size_t)(P->end - P->p) == n || !is_num_char(P->p[n]))) {
            P->p += n;
            return 1;
        }
    }
    double v;
    return parse_number(P, &v);
}

/* Parse "[" item ("," item)* "]" calling fn for each item. */
typedef int (*ItemFn)(Parser *, void *);
static int parse_array(Parser *P, ItemFn fn, void *ctx)
{
    if (!expect(P, '['))
        return 0;
    if (peek(P) == ']') {
        P->p++;
        return 1;
    }
    for (;;) {
        if (!fn(P, ctx))
            return 0;
        int d = peek(P);
        if (d == ',') { P->p++; continue; }
        if (d == ']') { P->p++; return 1; }
        return perr(P, "expected ',' or ']'");
    }
}

typedef struct { int k; double c[2]; } PointCtx;
static int point_item(Parser *P, void *vctx)
{
    PointCtx *pc = vctx;
    double v;
    if (!parse_number(P, &v))
        return 0;
    if (pc->k < 2)
        pc->c[pc->k] = v; /* extra ordinates (z) are ignored */
    pc->k++;
    return 1;
}

typedef struct { Ring r; size_t cap; } RingCtx;
static int ring_item(Parser *P, void *vctx)
{
    RingCtx *rc = vctx;
    PointCtx pc = {0, {0, 0}};
    if (!parse_array(P, point_item, &pc))
        return 0;
    if (pc.k < 2)
        return perr(P, "point with %d ordinates", pc.k);
    if (rc->r.n == rc->cap) {
        rc->cap = rc->cap ? 2 * rc->cap : 8;
        rc->r.xy = xrealloc(rc->r.xy, 2 * rc->cap * sizeof(double));
    }
    rc->r.xy[2 * rc->r.n] = pc.c[0];
    rc->r.xy[2 * rc->r.n + 1] = pc.c[1];
    rc->r.n++;
    return 1;
}

static int poly_item(Parser *P, void *vctx)
{
    Poly *pg = vctx;
    RingCtx rc = {{0, NULL}, 0};
    if (!parse_array(P, ring_item, &rc)) {
        free(rc.r.xy);
        return 0;
    }
    pg->rings = xrealloc(pg->rings, (pg->nrings + 1) * sizeof(Ring));
    pg->rings[pg->nrings++] = rc.r;
    return 1;
}

static int mpoly_item(Parser *P, void *vctx)
{
    MPoly *mp = vctx;
    Poly pg = {0, NULL};
    int ok = parse_array(P, poly_item, &pg);
    mp->polys = xrealloc(mp->polys, (mp->npolys + 1) * sizeof(Poly));
    mp->polys[mp->npolys++] = pg; /* kept even on failure so it gets freed */
    return ok;
}

static void free_mpoly(MPoly *mp)
{
    for (size_t i = 0; i < mp->npolys; i++) {
        for (size_t j = 0; j < mp->polys[i].nrings; j++)
            free(mp->polys[i].rings[j].xy);
        free(mp->polys[i].rings);
    }
    free(mp->polys);
    mp->polys = NULL;
    mp->npolys = 0;
}

static void free_case(Case *c)
{
    free(c->id_json);
    free_mpoly(&c->a);
    free_mpoly(&c->b);
    memset(c, 0, sizeof *c);
}

static int key_is(const char *s, size_t n, const char *k)
{
    size_t kl = strlen(k);
    return n == kl + 2 && memcmp(s + 1, k, kl) == 0;
}

/* Returns 1 on success; on failure fills err (c->id_json may still be set). */
static int parse_case(const char *line, size_t len, Case *c, char *err, size_t errcap)
{
    Parser P = {line, line, line + len, {0}};
    memset(c, 0, sizeof *c);
    int ok = expect(&P, '{');
    if (ok && peek(&P) == '}')
        P.p++;
    else
        while (ok) {
            const char *k; size_t kn;
            if (!parse_string(&P, &k, &kn) || !expect(&P, ':')) {
                ok = 0;
                break;
            }
            if (key_is(k, kn, "id") && peek(&P) == '"') {
                const char *s; size_t n;
                if (!(ok = parse_string(&P, &s, &n)))
                    break;
                free(c->id_json);
                c->id_json = xrealloc(NULL, n + 1);
                memcpy(c->id_json, s, n);
                c->id_json[n] = '\0';
            } else if (key_is(k, kn, "a")) {
                free_mpoly(&c->a);
                ok = parse_array(&P, mpoly_item, &c->a);
                c->have_a = ok;
            } else if (key_is(k, kn, "b")) {
                free_mpoly(&c->b);
                ok = parse_array(&P, mpoly_item, &c->b);
                c->have_b = ok;
            } else {
                ok = skip_value(&P, 0);
            }
            if (!ok)
                break;
            int d = peek(&P);
            if (d == ',') { P.p++; continue; }
            if (d == '}') { P.p++; break; }
            ok = perr(&P, "expected ',' or '}'");
        }
    if (ok && peek(&P) != -1)
        ok = perr(&P, "trailing characters");
    if (ok && (!c->have_a || !c->have_b))
        ok = perr(&P, "missing \"a\" or \"b\"");
    if (!ok)
        snprintf(err, errcap, "input parse error: %s", P.err[0] ? P.err : "unknown");
    return ok;
}

/* ------------------------------------------------------------------ GEOS work */

typedef struct {
    char msg[1024];
} Msg;

static void on_error(const char *message, void *userdata)
{
    Msg *m = userdata;
    snprintf(m->msg, sizeof m->msg, "%s", message ? message : "(no message)");
}

static void on_notice(const char *message, void *userdata)
{
    (void)message;
    (void)userdata;
}

/* Build a GEOS geometry: Polygon when there is exactly one part, else MultiPolygon. */
static GEOSGeometry *build_poly(GEOSContextHandle_t h, const Poly *pg)
{
    if (pg->nrings == 0)
        return GEOSGeom_createEmptyPolygon_r(h);
    GEOSGeometry **rings = calloc(pg->nrings, sizeof *rings);
    size_t k;
    for (k = 0; k < pg->nrings; k++) {
        const Ring *r = &pg->rings[k];
        GEOSCoordSequence *cs = GEOSCoordSeq_copyFromBuffer_r(h, r->xy, (unsigned)r->n, 0, 0);
        if (!cs)
            break;
        rings[k] = GEOSGeom_createLinearRing_r(h, cs); /* takes ownership of cs */
        if (!rings[k])
            break;
    }
    GEOSGeometry *g = NULL;
    if (k == pg->nrings)
        g = GEOSGeom_createPolygon_r(h, rings[0], rings + 1, (unsigned)(pg->nrings - 1));
    else
        for (size_t j = 0; j < k; j++)
            GEOSGeom_destroy_r(h, rings[j]);
    free(rings);
    return g;
}

static GEOSGeometry *build_geom(GEOSContextHandle_t h, const MPoly *mp)
{
    if (mp->npolys == 1)
        return build_poly(h, &mp->polys[0]);
    GEOSGeometry **parts = calloc(mp->npolys ? mp->npolys : 1, sizeof *parts);
    size_t k;
    for (k = 0; k < mp->npolys; k++)
        if (!(parts[k] = build_poly(h, &mp->polys[k])))
            break;
    GEOSGeometry *g = NULL;
    if (k == mp->npolys)
        g = GEOSGeom_createCollection_r(h, GEOS_MULTIPOLYGON, parts, (unsigned)mp->npolys);
    else
        for (size_t j = 0; j < k; j++)
            GEOSGeom_destroy_r(h, parts[j]);
    free(parts);
    return g;
}

typedef char (*PredFn)(GEOSContextHandle_t, const GEOSGeometry *, const GEOSGeometry *);
typedef GEOSGeometry *(*OverlayFn)(GEOSContextHandle_t, const GEOSGeometry *, const GEOSGeometry *);

static PredFn pred_fn(int op)
{
    switch (op) {
    case OP_INTERSECTS: return GEOSIntersects_r;
    case OP_DISJOINT: return GEOSDisjoint_r;
    case OP_TOUCHES: return GEOSTouches_r;
    case OP_OVERLAPS: return GEOSOverlaps_r;
    case OP_CONTAINS: return GEOSContains_r;
    case OP_COVERS: return GEOSCovers_r;
    case OP_WITHIN: return GEOSWithin_r;
    case OP_COVERED_BY: return GEOSCoveredBy_r;
    case OP_EQUALS: return GEOSEquals_r;
    default: return NULL;
    }
}

static OverlayFn overlay_fn(int op)
{
    switch (op) {
    case OP_AREA_INTER: return GEOSIntersection_r;
    case OP_AREA_UNION: return GEOSUnion_r;
    case OP_AREA_DIFF: return GEOSDifference_r;
    case OP_AREA_SYMDIFF: return GEOSSymDifference_r;
    default: return NULL;
    }
}

static const char *err_or(const Msg *m, const char *fallback)
{
    return m->msg[0] ? m->msg : fallback;
}

typedef void (*EmitFn)(int op, const OpResult *r, void *ctx);

/* GEOS_ADAPTER_TEST_FAULT="crash:<key>" or "hang_:<key>" injects a fault (tests only). */
static char TEST_FAULT[64];

/* Run operations start..NOPS-1 on one case, emitting each result as soon as it is known. */
static void run_ops(const Case *c, int start, EmitFn emit, void *ectx)
{
    GEOSContextHandle_t h = GEOS_init_r();
    Msg m = {{0}};
    GEOSContext_setErrorMessageHandler_r(h, on_error, &m);
    GEOSContext_setNoticeMessageHandler_r(h, on_notice, NULL);

    char berr_a[1100] = "", berr_b[1100] = "";
    GEOSGeometry *A = build_geom(h, &c->a);
    if (!A)
        snprintf(berr_a, sizeof berr_a, "building A: %s", err_or(&m, "failed"));
    m.msg[0] = '\0';
    GEOSGeometry *B = build_geom(h, &c->b);
    if (!B)
        snprintf(berr_b, sizeof berr_b, "building B: %s", err_or(&m, "failed"));

    for (int op = start; op < NOPS; op++) {
        OpResult r;
        memset(&r, 0, sizeof r);
        r.done = 1;
        strcpy(r.val, "null");
        const char *err = NULL;
        char ebuf[2300];
        m.msg[0] = '\0';

        if (TEST_FAULT[0] && !strcmp(TEST_FAULT + 6, OP_KEYS[op])) { /* self-test hook */
            if (!strncmp(TEST_FAULT, "crash:", 6))
                raise(SIGSEGV);
            if (!strncmp(TEST_FAULT, "hang_:", 6))
                for (;;)
                    pause();
        }
        const int need_a = op != OP_VALID_B, need_b = op != OP_VALID_A;
        if (need_a && !A) {
            err = berr_a;
        } else if (need_b && !B) {
            err = berr_b;
        } else if (op == OP_VALID_A || op == OP_VALID_B) {
            char v = GEOSisValid_r(h, op == OP_VALID_A ? A : B);
            if (v == 0 || v == 1)
                strcpy(r.val, v ? "true" : "false");
            else
                err = err_or(&m, "GEOSisValid_r failed");
        } else if (pred_fn(op)) {
            char v = pred_fn(op)(h, A, B);
            if (v == 0 || v == 1)
                strcpy(r.val, v ? "true" : "false");
            else
                err = err_or(&m, "predicate failed");
        } else {
            GEOSGeometry *g = overlay_fn(op)(h, A, B);
            if (!g) {
                err = err_or(&m, "overlay failed");
            } else {
                double area = 0;
                if (!GEOSArea_r(h, g, &area)) {
                    snprintf(ebuf, sizeof ebuf, "GEOSArea_r: %s", err_or(&m, "failed"));
                    err = ebuf;
                } else if (!isfinite(area)) {
                    snprintf(ebuf, sizeof ebuf, "non-finite area %g", area);
                    err = ebuf;
                } else {
                    fmt_double(r.val, sizeof r.val, area);
                }
                GEOSGeom_destroy_r(h, g);
            }
        }
        if (err)
            json_quote(r.err, sizeof r.err, err);
        emit(op, &r, ectx);
    }
    if (A) GEOSGeom_destroy_r(h, A);
    if (B) GEOSGeom_destroy_r(h, B);
    GEOS_finish_r(h);
}

/* ------------------------------------------------------------------ driver */

static char LIB[128];

static void init_lib_string(void)
{
    /* GEOSversion(): "3.16.0dev-CAPI-1.23.0"; GEOSrevision(): "ae9cdd9" or
       "3.15.0rc1-3-g952699419 (dirty)" depending on how the tree was cloned. */
    char ver[64], rev[64];
    snprintf(ver, sizeof ver, "%s", GEOSversion());
    char *cut = strstr(ver, "-CAPI");
    if (cut)
        *cut = '\0';
    snprintf(rev, sizeof rev, "%s", GEOSrevision());
    int dirty = strstr(rev, "(dirty)") != NULL;
    char *sp = strchr(rev, ' ');
    if (sp)
        *sp = '\0';
    char *g = strstr(rev, "-g");
    const char *hash = g ? g + 2 : rev;
    char shorthash[16];
    snprintf(shorthash, sizeof shorthash, "%.7s", hash);
    snprintf(LIB, sizeof LIB, "geos@%s-%s%s", ver, shorthash, dirty ? "-dirty" : "");
}

static void emit_store(int op, const OpResult *r, void *ctx)
{
    ((OpResult *)ctx)[op] = *r;
}

/* Child side of the pipe protocol: "<op>\t<value>\t<json error or empty>\n", one write. */
static void emit_pipe(int op, const OpResult *r, void *ctx)
{
    int fd = *(int *)ctx;
    char line[VALLEN + ERRLEN + 16];
    int n = snprintf(line, sizeof line, "%d\t%s\t%s\n", op, r->val, r->err);
    const char *p = line;
    while (n > 0) {
        ssize_t w = write(fd, p, (size_t)n);
        if (w < 0) {
            if (errno == EINTR)
                continue;
            _exit(3);
        }
        p += w;
        n -= (int)w;
    }
}

static double TIMEOUT_S = 10.0;
static long MEM_MB = 4096;

static void set_err(OpResult *r, const char *msg)
{
    r->done = 1;
    strcpy(r->val, "null");
    json_quote(r->err, sizeof r->err, msg);
}

/* Parse one protocol line from the child into res[]; returns the op index or -1. */
static int take_record(char *line, OpResult *res)
{
    char *t1 = strchr(line, '\t');
    if (!t1)
        return -1;
    char *t2 = strchr(t1 + 1, '\t');
    if (!t2)
        return -1;
    *t1 = *t2 = '\0';
    int op = atoi(line);
    if (op < 0 || op >= NOPS)
        return -1;
    OpResult *r = &res[op];
    r->done = 1;
    snprintf(r->val, sizeof r->val, "%s", t1 + 1);
    snprintf(r->err, sizeof r->err, "%s", t2 + 1);
    return op;
}

/* Run a case op by op in forked children; fills res[], records timeouts in *timed_out. */
static void run_case_forked(const Case *c, OpResult *res, char *timeouts, size_t tcap)
{
    int next = 0;
    timeouts[0] = '\0';
    while (next < NOPS) {
        int fds[2];
        if (pipe(fds) != 0) {
            perror("pipe");
            exit(2);
        }
        fflush(stdout);
        fflush(stderr);
        pid_t pid = fork();
        if (pid < 0) {
            perror("fork");
            exit(2);
        }
        if (pid == 0) {
            close(fds[0]);
            if (MEM_MB > 0) {
                struct rlimit rl;
                rl.rlim_cur = rl.rlim_max = (rlim_t)MEM_MB << 20;
                setrlimit(RLIMIT_AS, &rl);
            }
            int fd = fds[1];
            run_ops(c, next, emit_pipe, &fd);
            _exit(0);
        }
        close(fds[1]);

        char buf[8192];
        size_t have = 0;
        double deadline = now_s() + TIMEOUT_S;
        int timed_out = 0, eof = 0;
        while (!eof && next < NOPS) {
            double left = deadline - now_s();
            if (left <= 0) {
                timed_out = 1;
                break;
            }
            struct pollfd pfd = {fds[0], POLLIN, 0};
            int pr = poll(&pfd, 1, (int)(left * 1000) + 1);
            if (pr < 0) {
                if (errno == EINTR)
                    continue;
                perror("poll");
                exit(2);
            }
            if (pr == 0)
                continue; /* loop re-checks the deadline */
            ssize_t n = read(fds[0], buf + have, sizeof buf - 1 - have);
            if (n < 0) {
                if (errno == EINTR)
                    continue;
                perror("read");
                exit(2);
            }
            if (n == 0) {
                eof = 1;
                break;
            }
            have += (size_t)n;
            buf[have] = '\0';
            char *nl;
            while ((nl = memchr(buf, '\n', have)) != NULL) {
                *nl = '\0';
                int op = take_record(buf, res);
                if (op >= 0) {
                    next = op + 1;
                    deadline = now_s() + TIMEOUT_S; /* per-operation budget */
                }
                size_t used = (size_t)(nl + 1 - buf);
                memmove(buf, nl + 1, have - used);
                have -= used;
                buf[have] = '\0';
            }
            if (have >= sizeof buf - 1)
                have = 0; /* garbage without newline; drop */
        }
        if (timed_out)
            kill(pid, SIGKILL);
        close(fds[0]);
        int status = 0;
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR)
            ;
        if (next >= NOPS)
            break;
        /* The child stopped before finishing operation `next`. */
        char msg[256];
        if (timed_out) {
            snprintf(msg, sizeof msg, "timeout: no result after %g s (killed)", TIMEOUT_S);
            size_t tl = strlen(timeouts);
            snprintf(timeouts + tl, tcap - tl, "%s%s", tl ? "," : "", OP_KEYS[next]);
        } else if (WIFSIGNALED(status)) {
            snprintf(msg, sizeof msg, "crash: process killed by signal %d (%s)",
                     WTERMSIG(status), strsignal(WTERMSIG(status)));
        } else {
            snprintf(msg, sizeof msg, "crash: process exited with status %d",
                     WIFEXITED(status) ? WEXITSTATUS(status) : -1);
        }
        set_err(&res[next], msg);
        next++;
    }
}

static void print_result(const char *id_json, const OpResult *res, const char *timeouts,
                         const char *parse_err)
{
    static char out[64 * 1024];
    size_t o = 0;
    o += (size_t)snprintf(out + o, sizeof out - o, "{\"id\": %s, \"lib\": \"%s\"",
                          id_json ? id_json : "null", LIB);
    for (int op = 0; op < NOPS; op++)
        o += (size_t)snprintf(out + o, sizeof out - o, ", \"%s\": %s", OP_KEYS[op],
                              res[op].done ? res[op].val : "null");
    o += (size_t)snprintf(out + o, sizeof out - o, ", \"errors\": {");
    int first = 1;
    for (int op = 0; op < NOPS; op++) {
        if (!res[op].err[0])
            continue;
        o += (size_t)snprintf(out + o, sizeof out - o, "%s\"%s\": %s", first ? "" : ", ",
                              OP_KEYS[op], res[op].err);
        first = 0;
    }
    if (timeouts && timeouts[0]) {
        char q[512], msg[400];
        snprintf(msg, sizeof msg, "operations exceeded %g s: %s", TIMEOUT_S, timeouts);
        json_quote(q, sizeof q, msg);
        o += (size_t)snprintf(out + o, sizeof out - o, "%s\"timeout\": %s", first ? "" : ", ", q);
    }
    if (parse_err) {
        char q[512];
        json_quote(q, sizeof q, parse_err);
        o += (size_t)snprintf(out + o, sizeof out - o, "%s\"parse\": %s", first ? "" : ", ", q);
    }
    snprintf(out + o, sizeof out - o, "}}\n");
    fputs(out, stdout);
    if (fflush(stdout) != 0 || ferror(stdout)) {
        fprintf(stderr, "geos_adapter: cannot write output: %s\n", strerror(errno));
        exit(1); /* reader went away: stop instead of computing into the void */
    }
}

static void usage(void)
{
    fprintf(stderr, "usage: geos_adapter [--no-fork] CASES.jsonl > RESULTS.jsonl\n"
                    "       geos_adapter --version\n");
    exit(2);
}

int main(int argc, char **argv)
{
    int use_fork = 1;
    const char *path = NULL;
    init_lib_string();
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--no-fork"))
            use_fork = 0;
        else if (!strcmp(argv[i], "--version")) {
            printf("%s\n", LIB);
            return 0;
        } else if (argv[i][0] == '-' && argv[i][1])
            usage();
        else
            path = argv[i];
    }
    if (!path)
        usage();
    const char *e;
    if ((e = getenv("GEOS_ADAPTER_TIMEOUT")) && *e)
        TIMEOUT_S = atof(e) > 0 ? atof(e) : TIMEOUT_S;
    if ((e = getenv("GEOS_ADAPTER_MEM_MB")) && *e)
        MEM_MB = atol(e);
    if ((e = getenv("GEOS_ADAPTER_TEST_FAULT")) && strlen(e) > 6)
        snprintf(TEST_FAULT, sizeof TEST_FAULT, "%s", e);
    signal(SIGPIPE, SIG_IGN);

    FILE *in = strcmp(path, "-") ? fopen(path, "r") : stdin;
    if (!in) {
        perror(path);
        return 2;
    }
    char *line = NULL;
    size_t cap = 0;
    ssize_t len;
    while ((len = getline(&line, &cap, in)) > 0) {
        size_t n = (size_t)len;
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r' || line[n - 1] == ' '))
            n--;
        size_t s = 0;
        while (s < n && (line[s] == ' ' || line[s] == '\t'))
            s++;
        if (s == n)
            continue; /* blank line: no output, like the reference adapter */

        Case c;
        OpResult res[NOPS];
        memset(res, 0, sizeof res);
        char perrbuf[400], timeouts[512] = "";
        int parsed = parse_case(line + s, n - s, &c, perrbuf, sizeof perrbuf);
        if (!parsed) {
            /* every field stays null; the message goes under errors.parse */
        } else if (use_fork) {
            run_case_forked(&c, res, timeouts, sizeof timeouts);
        } else {
            run_ops(&c, 0, emit_store, res);
        }
        print_result(c.id_json, res, timeouts, parsed ? NULL : perrbuf);
        free_case(&c);
    }
    free(line);
    if (in != stdin)
        fclose(in);
    return 0;
}
