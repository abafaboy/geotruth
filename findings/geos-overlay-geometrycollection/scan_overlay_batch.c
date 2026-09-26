/* Reads "id\tA\tB" lines; prints "id\top\tresult-or-ERR" for the four public overlay
 * functions.  Each case runs in a forked child (a crash is reported, not fatal). */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#define GEOS_USE_ONLY_R_API
#include <geos_c.h>

static char errbuf[1024];
static void on_error(const char *fmt, void *u) { (void)u; snprintf(errbuf, sizeof errbuf, "%s", fmt); }

static void one(const char *id, const char *wa, const char *wb)
{
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(h, on_error, NULL);
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(h);
    GEOSWKTWriter_setTrim_r(h, w, 1);
    GEOSWKTWriter_setRoundingPrecision_r(h, w, -1);
    GEOSGeometry *a = GEOSWKTReader_read_r(h, r, wa);
    GEOSGeometry *b = GEOSWKTReader_read_r(h, r, wb);
    const char *names[4] = {"intersection", "union", "difference", "symdifference"};
    for (int op = 0; op < 4; op++) {
        errbuf[0] = '\0';
        GEOSGeometry *g = NULL;
        if (a && b) {
            switch (op) {
            case 0: g = GEOSIntersection_r(h, a, b); break;
            case 1: g = GEOSUnion_r(h, a, b); break;
            case 2: g = GEOSDifference_r(h, a, b); break;
            default: g = GEOSSymDifference_r(h, a, b); break;
            }
        }
        if (g) {
            char *s = GEOSWKTWriter_write_r(h, w, g);
            printf("%s\t%s\t%s\n", id, names[op], s);
            GEOSFree_r(h, s);
            GEOSGeom_destroy_r(h, g);
        } else {
            printf("%s\t%s\tERR %s\n", id, names[op], errbuf);
        }
    }
    fflush(stdout);
    _exit(0);
}

int main(void)
{
    char *line = NULL;
    size_t cap = 0;
    while (getline(&line, &cap, stdin) > 0) {
        line[strcspn(line, "\n")] = '\0';
        char *id = strtok(line, "\t"), *wa = strtok(NULL, "\t"), *wb = strtok(NULL, "\t");
        if (!id || !wa || !wb) continue;
        fflush(stdout);
        pid_t pid = fork();
        if (pid == 0) one(id, wa, wb);
        int st = 0;
        waitpid(pid, &st, 0);
        if (WIFSIGNALED(st)) printf("%s\tALL\tCRASH signal %d\n", id, WTERMSIG(st));
    }
    free(line);
    return 0;
}
