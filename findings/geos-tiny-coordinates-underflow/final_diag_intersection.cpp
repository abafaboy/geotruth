#include <geos/algorithm/CGAlgorithmsDD.h>
#include <geos/geom/Coordinate.h>
#include <cstdio>
#include <initializer_list>
using geos::algorithm::CGAlgorithmsDD; using geos::geom::CoordinateXY;
int main() {
    for (double S : {1e102, 1e103, 1e-102, 1e-103, 1e-105, 1e105}) {
        CoordinateXY r = CGAlgorithmsDD::intersection({2*S,0},{2*S,2*S},{S,S},{3*S,S});
        std::printf("S=%g  raw CGAlgorithmsDD::intersection / S = (%.17g, %.17g)   exact (2, 1)\n", S, r.x/S, r.y/S);
    }
}
