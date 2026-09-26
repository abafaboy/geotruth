// Boost.Geometry: within/intersection/union wrong for two triangles whose vertices
// nearly coincide (regression in 1.87.0, still present in 1.92.0 and develop).
// Public API only. Build (any Boost >= 1.87 or develop):
//   g++ -std=c++17 -O2 -I<boost-root> repro.cpp -o repro && ./repro
#include <boost/geometry.hpp>
#include <iomanip>
#include <iostream>
#include <string>

namespace bg = boost::geometry;
using point_t = bg::model::d2::point_xy<double>;
using polygon_t = bg::model::polygon<point_t>;          // default: clockwise, closed
using mpolygon_t = bg::model::multi_polygon<polygon_t>;

static void run(char const* name, char const* wkt_a, char const* wkt_b)
{
    polygon_t a, b;
    bg::read_wkt(wkt_a, a);
    bg::read_wkt(wkt_b, b);
    std::string why_a, why_b;
    bool const valid_a = bg::is_valid(a, why_a);
    bool const valid_b = bg::is_valid(b, why_b);

    mpolygon_t i, u, d;
    bg::intersection(a, b, i);
    bg::union_(a, b, u);
    bg::difference(a, b, d);

    std::cout << std::setprecision(17) << std::boolalpha
              << "== " << name << "\n"
              << "A = " << bg::wkt(a) << "\n"
              << "B = " << bg::wkt(b) << "\n"
              << "is_valid(A) = " << valid_a << " (" << why_a << ")\n"
              << "is_valid(B) = " << valid_b << " (" << why_b << ")\n"
              << "area(A) = " << bg::area(a) << "   area(B) = " << bg::area(b) << "\n"
              << "relation(A,B) = " << bg::relation(a, b).str() << "\n"
              << "within(A,B) = " << bg::within(a, b)
              << "   covered_by(A,B) = " << bg::covered_by(a, b)
              << "   overlaps(A,B) = " << bg::overlaps(a, b) << "\n"
              << "area(intersection) = " << bg::area(i) << "\n"
              << "area(union)        = " << bg::area(u) << "\n"
              << "area(difference)   = " << bg::area(d) << "\n"
              << "intersection = " << bg::wkt(i) << "\n"
              << "union        = " << bg::wkt(u) << "\n";
}

int main()
{
    // Minimal case. A0=(-0.6,3), A1=(-1.7,1.9) and B's (-2.6,1) are on the line y = x + 3.6
    // (in decimal); B's first vertex is A1 moved by +1 ulp in x and +2 ulps in y.
    // B's vertex (-1,2) lies well inside A, so A and B overlap in a small triangle
    // (exact area ~0.0777); A is not within B (area(A) = 3.63 > area(B) = 0.27).
    run("minimal",
        "POLYGON((-0.6 3,2 -1,-1.7 1.9,-0.6 3))",
        "POLYGON((-1.6999999999999997 1.9000000000000004,-1 2,-2.6 1,"
        "-1.6999999999999997 1.9000000000000004))");

    // Original differential-testing case: two unit squares, B = A shifted by one edge
    // vector, overlapping along the shared edge in a sliver of exact area 3.9e-16.
    run("original (rotated-neighbours-1-000230)",
        "POLYGON((-0.07442943330621471 -0.7031786824539803,-0.7031786824539803 0.07442943330621471,"
        "0.07442943330621471 0.7031786824539803,0.7031786824539803 -0.07442943330621471,"
        "-0.07442943330621471 -0.7031786824539803))",
        "POLYGON((0.7031786824539801 -0.07442943330621504,0.07442943330621438 0.7031786824539801,"
        "0.8520375490664094 1.3319279316017456,1.480786798214175 0.5543198158415505,"
        "0.7031786824539801 -0.07442943330621504))");
    return 0;
}
