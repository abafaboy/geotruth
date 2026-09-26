// Variants of the minimal case (public API only): a single-subject union (AddSubject({A, B}), no
// clip, ClipType::Union, EvenOdd), and Difference(A, B) under Positive, NonZero and EvenOdd.
// For each, prints the top-level nodes, what Clipper2's own CheckPolytreeFullyContainsChildren
// (clipper.h) says about the tree, and the sum of signed areas over the tree. Shows why the
// upstream tests do not catch the bug: the misplaced ring is a direct child of the root, which
// has no polygon to check it against, and signed areas are unchanged.
//   g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include variants_check.cpp \
//       $C/CPP/Clipper2Lib/src/clipper.engine.cpp -o variants_check && ./variants_check
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;
static double sarea(const PolyPath64& n){double a=0;for(size_t i=0;i<n.Count();++i){a+=Area(n[i]->Polygon());a+=sarea(*n[i]);}return a;}
static void dump(const char* t, const PolyTree64& tr){
  printf("%s: top=%zu, CheckPolytreeFullyContainsChildren=%d, signed tree area=%.1f\n", t, tr.Count(), (int)CheckPolytreeFullyContainsChildren(tr), sarea(tr));
  for(size_t i=0;i<tr.Count();++i){auto c=tr[i]; printf("  L%u %s %+.1f parent-is-root=%d children=%zu\n", c->Level(), c->IsHole()?"hole":"outer", Area(c->Polygon()), (int)(c->Parent()==&tr), c->Count());}
}
int main(){
  printf("ver %s\n", CLIPPER2_VERSION);
  Path64 A=MakePath({0,0,6,2,2,6}), B=MakePath({3,1,4,4,1,3});
  { Clipper64 c; c.AddSubject({A,B}); PolyTree64 t; c.Execute(ClipType::Union, FillRule::EvenOdd, t); dump("Union({A,B}) EvenOdd single subject", t);}
  { Clipper64 c; c.AddSubject({A}); c.AddClip({B}); PolyTree64 t; c.Execute(ClipType::Difference, FillRule::Positive, t); dump("Difference Positive", t);}
  { Clipper64 c; c.AddSubject({A}); c.AddClip({B}); PolyTree64 t; c.Execute(ClipType::Difference, FillRule::NonZero, t); dump("Difference NonZero", t);}
  { Clipper64 c; c.AddSubject({A}); c.AddClip({B}); PolyTree64 t; c.Execute(ClipType::Difference, FillRule::EvenOdd, t); dump("Difference EvenOdd", t);}
}
