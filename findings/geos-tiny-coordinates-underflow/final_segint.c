#include <stdio.h>
#include <geos_c.h>
int main(void) {
    initGEOS(NULL, NULL);
    const double scales[] = {1e102, 1e103, 1e-105, 1e-110};
    for (int i = 0; i < 4; i++) {
        double S = scales[i], x, y;
        /* (0 0)-(4S 2S) crosses (0 2S)-(4S 0) at (2S S) */
        int r = GEOSSegmentIntersection(0, 0, 4*S, 2*S, 0, 2*S, 4*S, 0, &x, &y);
        printf("S=%g: r=%d, point/S = (%.12g %.12g)   expected (2 1)\n", S, r, x / S, y / S);
    }
    finishGEOS();
    return 0;
}
