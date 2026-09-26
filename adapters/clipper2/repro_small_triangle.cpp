// Minimal Clipper2 repro for the "very small triangle" cleanup (clipper.engine.cpp,
// IsVerySmallTriangle): a 3-vertex result ring is discarded when two of its vertices are
// within 1 unit in x and y, whatever its area. Build (after build.sh), with
// B=/tmp/claude-0/gb-build/clipper2:
//   g++ -O2 -std=c++17 -I$B/src/CPP/Clipper2Lib/include repro_small_triangle.cpp
//       $B/obj/clipper.engine.o -o $B/bin/repro_small_triangle
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;

static Paths64 P(std::initializer_list<std::pair<int64_t, int64_t>> pts) {
  Path64 path;
  for (auto& xy : pts) path.push_back(Point64(xy.first, xy.second));
  return Paths64{path};
}

// exact |area| (coordinates here are below 2^45, so int128 cannot overflow)
static long long exact_area(const Paths64& ps) {
  __int128 twice = 0;
  for (auto& p : ps)
    for (size_t i = 0; i < p.size(); ++i) {
      const Point64 &a = p[i], &b = p[(i + 1) % p.size()];
      twice += (__int128)a.x * b.y - (__int128)b.x * a.y;
    }
  if (twice < 0) twice = -twice;
  return (long long)(twice / 2);  // all areas below are integers
}

static void show(const char* what, const Paths64& p) {
  printf("%-34s %zu path(s), area %.17g\n", what, p.size(), Area(p));
}

int main() {
  const int64_t L = int64_t(1) << 40;
  Paths64 tri = P({{0, 0}, {1, 0}, {0, L}});  // valid, area L/2 = 549755813888
  Paths64 far = P({{10 * L, 0}, {11 * L, 0}, {11 * L, L}, {10 * L, L}});
  printf("input triangle area %.17g\n", Area(tri));
  show("Union(tri) alone:", Union(tri, FillRule::NonZero));
  show("Intersect(tri, tri):", Intersect(tri, tri, FillRule::NonZero));
  show("Union(tri, far square):", Union(tri, far, FillRule::NonZero));
  show("Difference(tri, far square):", Difference(tri, far, FillRule::NonZero));
  // same triangle scaled by 2: kept
  Paths64 tri2 = P({{0, 0}, {2, 0}, {0, 2 * L}});
  show("Union(tri scaled by 2):", Union(tri2, FillRule::NonZero));
  // an exact lattice intersection that is dropped while Difference keeps its complement:
  // A∩B is the triangle (0,0),(0,1),(2^43,1)
  const int64_t M = int64_t(1) << 44;
  Paths64 A = P({{0, 1}, {M, 1}, {M, -M - 1}, {0, -M + 1}});
  Paths64 B = P({{0, 0}, {M, 2}, {M, M}, {0, M}});
  show("Intersect(A, B) [exact 2^42]:", Intersect(A, B, FillRule::EvenOdd));
  printf("exact |A| - |Difference(A, B)| = %lld (should equal |A∩B| = 2^42 = %lld)\n",
         exact_area(A) - exact_area(Difference(A, B, FillRule::EvenOdd)), 1LL << 42);
  return 0;
}
