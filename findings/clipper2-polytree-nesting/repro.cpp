// Clipper2: PolyTree64 puts a ring at the wrong nesting level when every vertex
// of the ring lies on the boundary of the ring that contains it.
//
//   case 1  a hole whose vertices all touch its outer ring comes back as a
//           second top-level node (a direct child of the root, Level() == 1,
//           IsHole() == false) with clockwise (negative) orientation, instead
//           of as a child of the outer ring;
//   case 2  an island whose vertices all touch its hole comes back as a
//           second hole of the outer ring (Level() == 2, IsHole() == true,
//           positive orientation), instead of as a child of the hole.
//
// The flat Paths64 result of the same Execute call is right in both cases.
// Uses only the public Clipper2 API (clipper2/clipper.h).
// Build and run (C = a Clipper2 checkout):
//   g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include repro.cpp \
//       $C/CPP/Clipper2Lib/src/clipper.engine.cpp -o repro && ./repro
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;

static const char* pip_name(PointInPolygonResult r) {
  return r == PointInPolygonResult::IsInside ? "IsInside"
       : r == PointInPolygonResult::IsOutside ? "IsOutside" : "IsOn";
}

static void print_path(const Path64& p) {
  for (const Point64& pt : p) printf(" (%lld,%lld)", (long long)pt.x, (long long)pt.y);
}

// Prints the tree and counts nodes whose orientation contradicts their level
// (Clipper2 returns outer rings with positive area and holes with negative area).
static int dump(const PolyPath64& node, int depth) {
  int bad = 0;
  for (size_t i = 0; i < node.Count(); ++i) {
    const PolyPath64* c = node[i];
    double a = Area(c->Polygon());
    bool mismatch = (a < 0) != c->IsHole();
    bad += mismatch;
    printf("  %*slevel %u %s  area %+.1f ", depth * 2, "", c->Level(),
           c->IsHole() ? "hole " : "outer", a);
    print_path(c->Polygon());
    printf("%s\n", mismatch ? "   <-- orientation contradicts level" : "");
    bad += dump(*c, depth + 1);
  }
  return bad;
}

static void run(const char* title, const Paths64& subject, const Paths64& clip, ClipType ct) {
  printf("%s\n", title);
  Paths64 flat;
  { Clipper64 c; c.AddSubject(subject); c.AddClip(clip); c.Execute(ct, FillRule::EvenOdd, flat); }
  printf("  Paths64 result: %zu path(s), total signed area %.1f\n", flat.size(), Area(flat));
  for (const Path64& p : flat) { printf("    area %+.1f ", Area(p)); print_path(p); printf("\n"); }
  PolyTree64 tree;
  { Clipper64 c; c.AddSubject(subject); c.AddClip(clip); c.Execute(ct, FillRule::EvenOdd, tree); }
  printf("  PolyTree64 result: %zu top-level node(s)\n", tree.Count());
  int bad = dump(tree, 0);
  printf("  => %s\n\n", bad ? "WRONG nesting" : "nesting OK");
}

int main() {
  printf("Clipper2 %s\n\n", CLIPPER2_VERSION);

  // Case 1. A = triangle (0,0) (6,2) (2,6), area 16.
  //         B = its medial triangle (3,1) (4,4) (1,3), area 4: each vertex of B
  //             is the midpoint of an edge of A.
  //         A - B is the three corner triangles, area 12.
  Path64 A = MakePath({0,0, 6,2, 2,6});
  Path64 B = MakePath({3,1, 4,4, 1,3});
  printf("Clipper2's own PointInPolygon: vertices of B against A:");
  for (const Point64& pt : B) printf(" %s", pip_name(PointInPolygon(pt, A)));
  printf("; (3,3), inside B, against A: %s, against B: %s\n\n",
         pip_name(PointInPolygon(Point64(3, 3), A)), pip_name(PointInPolygon(Point64(3, 3), B)));
  run("Case 1: Difference(A, B)", {A}, {B}, ClipType::Difference);
  run("Case 1: Xor(A, B)", {A}, {B}, ClipType::Xor);
  // Control: move one vertex of B strictly inside A; the hole is then nested correctly.
  Path64 B2 = MakePath({3,2, 4,4, 1,3});
  run("Control: Difference(A, B2), B2 = (3,2) (4,4) (1,3)", {A}, {B2}, ClipType::Difference);

  // Case 2. S = square (0,0) (12,12) with the hole H = (2,2) (4,10) (10,4);
  //         I = the triangle on the midpoints of H's edges, (6,3) (7,7) (3,6).
  //         Union(S-with-hole, I) = S minus H plus I, area 144 - 30 + 7.5 = 121.5.
  Paths64 S = {MakePath({0,0, 12,0, 12,12, 0,12}), MakePath({2,2, 4,10, 10,4})};
  Path64 I = MakePath({6,3, 7,7, 3,6});
  run("Case 2: Union(S with hole H, I)", S, {I}, ClipType::Union);
  return 0;
}
