/*
 * Part 1: GEOSOrientationIndex on three point triples, at unit scale and after multiplying
 * every ordinate by 2^k. Multiplying by a power of two is exact for these values
 * (no overflow, no subnormal results), and it multiplies the orientation
 * determinant by 2^(2k) > 0, so the correct orientation never depends on k.
 * The expected signs are checked with exact rational arithmetic in exact_check.py.
 *
 * Part 2: GEOSSegmentIntersection of the segments (2 0)-(2 2) and (1 1)-(3 1), scaled
 * by 2^k. They cross at (2 1) at unit scale, so at every scale the answer is exactly
 * (2*2^k, 1*2^k).
 *
 * Part 3: the same segments with the decimal unit S = 1e<k> (2S = 2*S exactly, and the
 * vertical segment x = 2S crosses the horizontal one y = S at (2S S) exactly).
 *
 * Uses only the public GEOS C API.
 *   cc primitives_scaling.c $(geos-config --cflags) $(geos-config --clibs) -lm -o primitives_scaling
 *   ./primitives_scaling
 */
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <geos_c.h>

struct triple { const char *name; double ax, ay, bx, by, px, py; int expected; };

int main(void)
{
    GEOSContextHandle_t ctx = GEOS_init_r();
    printf("GEOS %s\n", GEOSversion());
    printf("GEOSOrientationIndex(A, B, P): 1 = P is left of A->B, -1 = right, 0 = collinear\n\n");

    const struct triple t[] = {
        /* right triangle, clearly counter-clockwise */
        {"A=(0 0) B=(1 0) P=(0 1)", 0, 0, 1, 0, 0, 1, 1},
        /* nearly collinear: the doubles nearest to these decimals are not exactly
           collinear; exact determinant = -3602879701896397 * 2^-103 (about -3.55e-16),
           so P is to the right (see exact_check.py) */
        {"A=(-1.6 1.2) B=(-3.2 -1.8) P=(-6.4 -7.8)", -1.6, 1.2, -3.2, -1.8, -6.4, -7.8, -1},
        /* the same, with a larger margin: P moved by 2^-40 */
        {"A=(0 0) B=(1 1) P=(2 2+2^-40)", 0, 0, 1, 1, 2, 2 + 0x1p-40, 1},
    };
    const int ks[] = {0, -400, -500, -505, -510, -514, -520, -530, -537, -538, -540, -600, -1000,
                      400, 500, 505, 508, 510, 512, 600, 1000};
    int nbad = 0;
    for (size_t i = 0; i < sizeof t / sizeof *t; i++) {
        printf("%s   (exact orientation %+d at every scale)\n", t[i].name, t[i].expected);
        for (size_t j = 0; j < sizeof ks / sizeof *ks; j++) {
            int k = ks[j];
            double ax = ldexp(t[i].ax, k), ay = ldexp(t[i].ay, k), bx = ldexp(t[i].bx, k),
                   by = ldexp(t[i].by, k), px = ldexp(t[i].px, k), py = ldexp(t[i].py, k);
            /* sanity: the scaling must be exact (it is, for all k listed) */
            if (ldexp(ax, -k) != t[i].ax || ldexp(ay, -k) != t[i].ay || ldexp(bx, -k) != t[i].bx ||
                ldexp(by, -k) != t[i].by || ldexp(px, -k) != t[i].px || ldexp(py, -k) != t[i].py) {
                printf("  2^%-5d scaling not exact, skipped\n", k);
                continue;
            }
            int got = GEOSOrientationIndex_r(ctx, ax, ay, bx, by, px, py);
            int ok = got == t[i].expected;
            nbad += !ok;
            printf("  x 2^%-5d (~1e%-4d) -> %+d%s\n", k, (int)lround(k * log10(2.0)), got,
                   ok ? "" : got == 0 ? "   <-- WRONG (reported collinear)" : "   <-- WRONG (opposite side)");
        }
        printf("\n");
    }

    printf("GEOSSegmentIntersection((2 0)-(2 2), (1 1)-(3 1)) scaled by 2^k; exact answer (2 1)*2^k\n");
    const int ks2[] = {0, -300, -340, -345, -350, -355, -358, -359, -360, -361, -400, -500, -537, -538,
                       -600, -1000, 300, 339, 340, 341, 342, 345, 400, 500, 1000};
    for (size_t j = 0; j < sizeof ks2 / sizeof *ks2; j++) {
        int k = ks2[j];
        double s = ldexp(1.0, k), cx = 0, cy = 0;
        int r = GEOSSegmentIntersection_r(ctx, 2 * s, 0, 2 * s, 2 * s, s, s, 3 * s, s, &cx, &cy);
        int ok = r == 1 && cx == 2 * s && cy == s;
        nbad += !ok;
        if (r == 1)
            printf("  x 2^%-5d (~1e%-4d) -> 1, point/2^k = (%.17g %.17g)%s\n", k, (int)lround(k * log10(2.0)),
                   ldexp(cx, -k), ldexp(cy, -k), ok ? "" : "   <-- WRONG");
        else
            printf("  x 2^%-5d (~1e%-4d) -> %d (no intersection)   <-- WRONG\n", k, (int)lround(k * log10(2.0)), r);
    }

    printf("\nGEOSSegmentIntersection((2S 0)-(2S 2S), (1S 1S)-(3S 1S)), S = 1e<k>; exact answer (2S 1S)\n");
    const char *units[] = {"1", "1e-100", "1e-102", "1e-103", "1e-105", "1e-120", "1e-160", "1e-200",
                           "1e100", "1e102", "1e103", "1e105", "1e150", NULL};
    for (int j = 0; units[j]; j++) {
        double s = strtod(units[j], NULL), s3 = 3 * s, cx = 0, cy = 0;
        int r = GEOSSegmentIntersection_r(ctx, 2 * s, 0, 2 * s, 2 * s, s, s, s3, s, &cx, &cy);
        int ok = r == 1 && cx == 2 * s && cy == s;
        nbad += !ok;
        if (r == 1)
            printf("  S = %-7s -> 1, point/S = (%.17g %.17g)%s\n", units[j], cx / s, cy / s, ok ? "" : "   <-- WRONG");
        else
            printf("  S = %-7s -> %d (no intersection)   <-- WRONG\n", units[j], r);
    }
    printf("\n%d wrong result(s)\n", nbad);
    GEOS_finish_r(ctx);
    return 0;
}
