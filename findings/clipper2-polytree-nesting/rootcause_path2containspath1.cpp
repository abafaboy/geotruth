// Root cause, shown through the public helper Clipper2Lib::Path2ContainsPath1
// (clipper.h, public since 1.5.3; BuildTree64 reaches the same template through the
// OutPt overload in clipper.engine.cpp once every vertex tested IsOn).
//   g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include rootcause_path2containspath1.cpp -o rc && ./rc
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;
int main() {
  printf("Clipper2 %s\n", CLIPPER2_VERSION);
  Path64 A = MakePath({0,0, 6,2, 2,6});           // triangle
  Path64 B = MakePath({3,1, 4,4, 1,3});           // its medial triangle: every vertex on A
  Path64 Bsmall = MakePath({3,2, 4,4, 2,3});      // control: same shape, one vertex strictly inside A
  Path64 H = MakePath({2,2, 4,10, 10,4});         // a hole ring
  Path64 I = MakePath({6,3, 7,7, 3,6});           // island: every vertex on H
  printf("Path2ContainsPath1(B, A)      = %d   (B lies inside A, touching it at its 3 vertices)\n", Path2ContainsPath1(B, A));
  printf("Path2ContainsPath1(Bsmall, A) = %d   (control: one vertex of Bsmall strictly inside A)\n", Path2ContainsPath1(Bsmall, A));
  printf("Path2ContainsPath1(I, H)      = %d   (I lies inside H, touching it at its 3 vertices)\n", Path2ContainsPath1(I, H));
  printf("Path2ContainsPath1(A, B)      = %d   (A is not inside B)\n", Path2ContainsPath1(A, B));
  return 0;
}
