// Boost.Geometry: side_by_triangle returns a wrong (non-zero) sign for nearly collinear
// points with coordinates of magnitude ~3, and within/intersection/union then fail for two
// triangles sharing a (decimal) line. Present in 1.83 ... 1.92 and develop.
// Public API only. Build: g++ -std=c++17 -O2 -I<boost-root> repro_side_sign.cpp
// Add -DBOOST_GEOMETRY_DEFAULT_STRATEGY_SIDE_USE_SIDE_ROBUST to use side_robust as default.
#include <boost/geometry.hpp>
#include <boost/geometry/strategy/cartesian/side_robust.hpp>
#include <iomanip>
#include <iostream>
#include <string>

namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;          // default: clockwise, closed
using mpolygon_t = bg::model::multi_polygon<polygon_t>;

int main()
{
    // All four points below lie on the line y = 0.8 x + 0.4 in decimal arithmetic.
    // A's edge (-2,-1.2)-(1,1.2) and B's edge (-3,-2)-(0,0.4) overlap for x in [-2,0].
    // A lies below that line, B above it. After rounding to double the two edges
    // cross at a tiny angle; the exact overlap is a sliver of area 1.85e-17.
    polygon_t a, b;
    bg::read_wkt("POLYGON((-2 -1.2,1 1.2,2 0,-2 -1.2))", a);
    bg::read_wkt("POLYGON((-3 -2,-2 3,0 0.4,-3 -2))", b);

    std::string why_a, why_b;
    mpolygon_t i, u, d;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    bg::difference(a, b, d);
    std::cout << std::setprecision(17) << std::boolalpha
              << "is_valid(A) = " << bg::is_valid(a, why_a) << " (" << why_a << ")\n"
              << "is_valid(B) = " << bg::is_valid(b, why_b) << " (" << why_b << ")\n"
              << "area(A) = " << bg::area(a) << "   area(B) = " << bg::area(b) << "\n"
              << "relation(A,B) = " << bg::relation(a, b).str() << "\n"
              << "within(A,B) = " << bg::within(a, b)
              << "   touches(A,B) = " << bg::touches(a, b)
              << "   overlaps(A,B) = " << bg::overlaps(a, b) << "\n"
              << "area(intersection) = " << bg::area(i) << "\n"
              << "area(union)        = " << bg::area(u) << "\n"
              << "area(difference)   = " << bg::area(d) << "\n"
              << "intersection = " << bg::wkt(i) << "\n"
              << "union        = " << bg::wkt(u) << "\n";

    // The side of A's vertex (1, 1.2) relative to B's edge (-3,-2) -> (0,0.4).
    // Exact value of the determinant: -2.22e-16 (right side).
    point_t const q1(-3, -2), q2(0, 0.4), p(1, 1.2);
    std::cout << "side_by_triangle((-3,-2),(0,0.4),(1,1.2)) = "
              << bg::strategy::side::side_by_triangle<>::apply(q1, q2, p)
              << "   side_robust = "
              << bg::strategy::side::side_robust<>::apply(q1, q2, p)
              << "   (exact: -1)\n";
    return 0;
}
