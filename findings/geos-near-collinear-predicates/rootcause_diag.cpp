// Diagnostic (internal C++ API): what LineIntersector and PolygonNodeTopology return
#include <geos/algorithm/LineIntersector.h>
#include <geos/algorithm/Orientation.h>
#include <geos/algorithm/PolygonNodeTopology.h>
#include <geos/geom/Coordinate.h>
#include <cstdio>
using namespace geos::algorithm;
using geos::geom::CoordinateXY;
static void seg(const char* name, CoordinateXY a0, CoordinateXY a1, CoordinateXY b0, CoordinateXY b1, CoordinateXY V) {
    LineIntersector li;
    li.computeIntersection(a0, a1, b0, b1);
    auto p = li.getIntersection(0);
    std::printf("%s: hasInt=%d n=%zu isProper=%d  intPt=(%.17g %.17g)  intPt==B vertex: %d\n", name, li.hasIntersection(),
        (size_t)li.getIntersectionNum(), li.isProper(), p.x, p.y, (p.x == V.x && p.y == V.y));
    std::printf("   orient(a0,a1,b0)=%d orient(a0,a1,b1)=%d orient(b0,b1,a0)=%d orient(b0,b1,a1)=%d\n",
        Orientation::index(a0, a1, b0), Orientation::index(a0, a1, b1), Orientation::index(b0, b1, a0), Orientation::index(b0, b1, a1));
}
int main() {
    // case 1 (touches): A edge (3 1)->(0 0); B edges V->(2 2) and (1 2)->V
    CoordinateXY a0(3, 1), a1(0, 0), V(2, 0.6666666666666666);
    std::printf("case1: orient((3,1),(0,0),V)=%d  (A is CCW; +1 = V left of A's edge = inside A)\n", Orientation::index(a0, a1, V));
    seg("  A(3 1)-(0 0) x B(1 2)-V", a0, a1, CoordinateXY(1, 2), V, V);
    seg("  A(3 1)-(0 0) x B V-(2 2)", a0, a1, V, CoordinateXY(2, 2), V);
    CoordinateXY b0(1, 2), b1(2, 2);
    std::printf("  PolygonNodeTopology::isCrossing(V, a0, a1, b0, b1) = %d\n", PolygonNodeTopology::isCrossing(&V, &a0, &a1, &b0, &b1));
    // case 2 (contains): A edge (3 1)->(0 0); B edges (3 0.5)->V and V->(2.5 0.5)
    CoordinateXY W(2.5, 0.8333333333333334);
    std::printf("case2: orient((3,1),(0,0),W)=%d\n", Orientation::index(a0, a1, W));
    seg("  A(3 1)-(0 0) x B(3 0.5)-W", a0, a1, CoordinateXY(3, 0.5), W, W);
    seg("  A(3 1)-(0 0) x B W-(2.5 0.5)", a0, a1, W, CoordinateXY(2.5, 0.5), W);
    CoordinateXY c0(3, 0.5), c1(2.5, 0.5);
    std::printf("  PolygonNodeTopology::isCrossing(W, a0, a1, c0, c1) = %d\n", PolygonNodeTopology::isCrossing(&W, &a0, &a1, &c0, &c1));
}
