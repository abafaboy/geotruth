// Helper for systematic_check.py. Public Boost.Geometry API only.
// stdin: one line per segment pair "ax1 ay1 ax2 ay2 bx1 by1 bx2 by2"
// stdout: intersects(segA, segB), then the four side_by_triangle results
//         side(b1,b2,a1) side(b1,b2,a2) side(a1,a2,b1) side(a1,a2,b2)
// Build: g++ -std=c++17 -O2 -I<boost-root> segx.cpp -o segx
#include <boost/geometry.hpp>
#include <cstdio>
namespace bg = boost::geometry;
using P = bg::model::d2::point_xy<double>;
using S = bg::model::segment<P>;
int main()
{
    double v[8];
    while (std::scanf("%lf %lf %lf %lf %lf %lf %lf %lf", v, v+1, v+2, v+3, v+4, v+5, v+6, v+7) == 8)
    {
        P a1(v[0], v[1]), a2(v[2], v[3]), b1(v[4], v[5]), b2(v[6], v[7]);
        using side = bg::strategy::side::side_by_triangle<>;
        std::printf("%d %d %d %d %d\n", int(bg::intersects(S(a1, a2), S(b1, b2))),
                    side::apply(b1, b2, a1), side::apply(b1, b2, a2),
                    side::apply(a1, a2, b1), side::apply(a1, a2, b2));
    }
}
