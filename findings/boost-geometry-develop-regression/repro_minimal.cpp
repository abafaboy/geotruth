#include <boost/geometry.hpp>
#include <iomanip>
#include <iostream>

namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;   // default: clockwise, closed
using mpolygon_t = bg::model::multi_polygon<polygon_t>;

int main()
{
    polygon_t a, b;
    bg::read_wkt("POLYGON((-0.6 3,2 -1,-1.7 1.9,-0.6 3))", a);
    bg::read_wkt("POLYGON((-1.6999999999999997 1.9000000000000004,-1 2,-2.6 1,"
                 "-1.6999999999999997 1.9000000000000004))", b);

    mpolygon_t i, u, d;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    bg::difference(a, b, d);

    std::cout << std::setprecision(17) << std::boolalpha
              << "is_valid: " << bg::is_valid(a) << " " << bg::is_valid(b) << "\n"
              << "relation: " << bg::relation(a, b).str() << "\n"
              << "within: " << bg::within(a, b) << "  overlaps: " << bg::overlaps(a, b) << "\n"
              << "area A: " << bg::area(a) << "  area B: " << bg::area(b) << "\n"
              << "intersection: " << bg::area(i) << "\n"
              << "union: " << bg::area(u) << "\n"
              << "difference: " << bg::area(d) << "\n";
}
