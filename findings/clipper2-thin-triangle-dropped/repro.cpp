// Clipper2: a triangle with one edge shorter than 2 units is removed from every
// solution, whatever its area.
//
// Uses only the public Clipper2 API (clipper2/clipper.h).
// Build and run (C = a Clipper2 checkout):
//   g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include repro.cpp \
//       $C/CPP/Clipper2Lib/src/clipper.engine.cpp -o repro && ./repro
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;

static void show(const char* what, const Paths64& p) {
  printf("%-44s %zu path(s), area %.0f\n", what, p.size(), Area(p));
  for (const Path64& path : p) {
    printf("    ");
    for (const Point64& pt : path) printf(" (%lld,%lld)", (long long)pt.x, (long long)pt.y);
    printf("\n");
  }
}

int main() {
  printf("Clipper2 %s\n\n", CLIPPER2_VERSION);

  // 1. A single valid triangle, 1 unit wide and 1,000,000 units tall
  //    (area 500,000). Union / Intersect of it with itself should return it.
  Paths64 t1 = {MakePath({0, 0, 1, 0, 0, 1000000})};
  printf("input t1 = (0,0) (1,0) (0,1000000), |area| = %.0f\n", std::fabs(Area(t1)));
  show("Union(t1, NonZero):", Union(t1, FillRule::NonZero));
  show("Union(t1, EvenOdd):", Union(t1, FillRule::EvenOdd));
  show("Intersect(t1, t1, NonZero):", Intersect(t1, t1, FillRule::NonZero));

  //    The same triangle 2 units wide is kept.
  Paths64 t2 = {MakePath({0, 0, 2, 0, 0, 1000000})};
  printf("\ninput t2 = (0,0) (2,0) (0,1000000), |area| = %.0f\n", std::fabs(Area(t2)));
  show("Union(t2, NonZero):", Union(t2, FillRule::NonZero));

  // 2. Two large, fat polygons (no edge shorter than 2,000,000 units) whose exact
  //    intersection is the triangle (0,0) (0,1) (1000000,1), area 500,000.
  //    Every vertex of that triangle is an integer point, so no rounding is needed.
  Paths64 a = {MakePath({0, -2000000, 2000000, -2000000, 2000000, 1, 0, 1})};
  Paths64 b = {MakePath({-2000000, -2, 2000000, 2, -2000000, 2000000})};
  printf("\nA = (0,-2000000) (2000000,-2000000) (2000000,1) (0,1),  |area| = %.0f\n",
         std::fabs(Area(a)));
  printf("B = (-2000000,-2) (2000000,2) (-2000000,2000000),        |area| = %.0f\n",
         std::fabs(Area(b)));
  Paths64 i = Intersect(a, b, FillRule::NonZero);
  Paths64 d = Difference(a, b, FillRule::NonZero);
  show("Intersect(A, B):", i);
  show("Difference(A, B):", d);
  printf("|A| - |A-B| = %.0f, but |A∩B| returned = %.0f\n",
         std::fabs(Area(a)) - std::fabs(Area(d)), std::fabs(Area(i)));
  return 0;
}
