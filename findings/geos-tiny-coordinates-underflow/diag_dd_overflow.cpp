// Diagnostic only (uses the C++ header geos/math/DD.h): evaluates the DD path of
// CGAlgorithmsDD::orientationIndex (src/algorithm/CGAlgorithmsDD.cpp:69-79) for the
// near-collinear triple of primitives_scaling.c at unit scale and at 2^512.
//   g++ -std=c++17 diag_dd_overflow.cpp $(geos-config --cflags) -L$(geos-config --prefix)/lib -lgeos -o diag_dd_overflow
#include <geos/math/DD.h>
#include <cmath>
#include <cstdio>
#include <initializer_list>
using geos::math::DD;
int main() {
    const double t[6] = {-1.6, 1.2, -3.2, -1.8, -6.4, -7.8};
    for (int k : {0, 512}) {
        double p1x = std::ldexp(t[0], k), p1y = std::ldexp(t[1], k), p2x = std::ldexp(t[2], k),
               p2y = std::ldexp(t[3], k), qx = std::ldexp(t[4], k), qy = std::ldexp(t[5], k);
        DD dx1 = DD(p2x) + DD(-p1x), dy1 = DD(p2y) + DD(-p1y);
        DD dx2 = DD(qx) + DD(-p2x), dy2 = DD(qy) + DD(-p2y);
        DD a(dx1 * dy2), b(dy1 * dx2);
        DD d = a - b;
        std::printf("k=%d  dx1*dy2 = %g  dy1*dx2 = %g  d = %g  d.isNaN=%d  d<0=%d d>0=%d\n", k,
                    a.doubleValue(), b.doubleValue(), d.doubleValue(), (int)d.isNaN(), (int)(d < DD(0.0)), (int)(d > DD(0.0)));
    }
}
