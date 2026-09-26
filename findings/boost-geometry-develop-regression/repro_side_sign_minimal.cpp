#include <boost/geometry.hpp>
#include <iomanip>
#include <iostream>

namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;
using mpolygon_t = bg::model::multi_polygon<polygon_t>;

int main()
{
    polygon_t a, b;
    bg::read_wkt("POLYGON((-2 -1.2,1 1.2,2 0,-2 -1.2))", a);
    bg::read_wkt("POLYGON((-3 -2,-2 3,0 0.4,-3 -2))", b);
    mpolygon_t i, u;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    std::cout << std::setprecision(17) << std::boolalpha
              << "relation: " << bg::relation(a, b).str()
              << "  within: " << bg::within(a, b) << "  touches: " << bg::touches(a, b) << "\n"
              << "intersection: " << bg::area(i) << "  union: " << bg::area(u) << "\n"
              << "side_by_triangle((-3,-2),(0,0.4),(1,1.2)) = "
              << bg::strategy::side::side_by_triangle<>::apply(point_t(-3, -2), point_t(0, 0.4), point_t(1, 1.2))
              << "\n";
}
