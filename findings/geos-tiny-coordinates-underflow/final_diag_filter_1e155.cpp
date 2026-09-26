#include <geos/math/DD.h>
#include <cmath>
#include <cstdio>
using geos::math::DD;
int main() {
    // GEOSOrientationIndex(Ax,Ay, Bx,By, Px,Py) with A=(2S 0), B=(2S 2S), P=(S S); exact answer +1
    const double S = 1e155;
    double pax = 2*S, pay = 0, pbx = 2*S, pby = 2*S, pcx = S, pcy = S;
    // filter, as in CGAlgorithmsDD.h:102-110
    double detleft = (pax - pcx) * (pby - pcy), detright = (pay - pcy) * (pbx - pcx);
    double det = detleft - detright, error = std::abs(detleft + detright) * 3.3306690621773724e-16;
    std::printf("filter: detleft=%g detright=%g det=%g error=%g -> %s\n", detleft, detright, det, error,
                std::abs(det) >= error ? "returns sign(det)" : "FAILURE (defers to DD)");
    // DD stage, as in CGAlgorithmsDD.cpp:70-79
    DD dx1 = DD(pbx) + DD(-pax), dy1 = DD(pby) + DD(-pay), dx2 = DD(pcx) + DD(-pbx), dy2 = DD(pcy) + DD(-pby);
    DD a(dx1 * dy2), b(dy1 * dx2), d = a - b;
    std::printf("DD: dx1*dy2=%g dy1*dx2=%g d=%g isNaN=%d -> OrientationDD returns %s\n", a.doubleValue(), b.doubleValue(),
                d.doubleValue(), (int)d.isNaN(), d < DD(0.0) ? "RIGHT" : d > DD(0.0) ? "LEFT" : "STRAIGHT (0)");
    // pre-3.14 (Shewchuk-branch) filter: detleft > 0 and detright <= 0 -> returns sign(det) immediately
    std::printf("pre-3.14 filter: detleft>0 && detright<=0 -> sign(det) = %d\n", (det > 0) - (det < 0));
}
