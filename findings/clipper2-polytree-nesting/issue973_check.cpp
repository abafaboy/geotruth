// The input of Clipper2 issue #973 ("PolyTree still has issues after fix of #957"), taken from
// the issue text: Union, NonZero, PolyTree64. Prints the tree and counts nodes whose orientation
// contradicts their level (bad=N). Used to check that #973 had the same symptom as this finding
// (a hole at the top level) from the same commit e8ebdef, and that its input is fixed on main.
//   g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include issue973_check.cpp \
//       $C/CPP/Clipper2Lib/src/clipper.engine.cpp -o issue973_check && ./issue973_check
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;
static int bad(const PolyPath64& n){int b=0;for(size_t i=0;i<n.Count();++i){auto c=n[i]; if((Area(c->Polygon())<0)!=c->IsHole()) ++b; b+=bad(*c);} return b;}
static void dump(const PolyPath64& n, int d=0){
  for(size_t i=0;i<n.Count();++i){ auto c=n[i];
    printf("%*s L%u %s area=%+.1f n=%zu\n", d*2,"", c->Level(), c->IsHole()?"hole":"outer", Area(c->Polygon()), c->Polygon().size()); dump(*c,d+1);} }
int main(){
Paths64 subject = {
    MakePath({ 31290,1740,  77530,1740,  77530,3160,  31290,3160,  31290,1740 }),
    MakePath({ 3160,22820,  6210,22820,  6210,23540,  3160,23540,  3160,22820 }),
    MakePath({ 0,0,  79530,0,  79530,940,  0,940,  0,0 }),
    MakePath({ 31290,31140,  77530,31140,  77530,32560,  31290,32560,  31290,31140 }),
    MakePath({ 3160,28790,  28350,28790,  28350,30070,  3160,30070,  3160,28790 }),
    MakePath({ 0,33360,  79530,33360,  79530,34300,  0,34300,  0,33360 }),
    MakePath({ 6210,22390,  26130,22390,  26130,23590,  6210,23590,  6210,22390 }),
    MakePath({ 76250,3160,  77530,3160,  77530,31140,  76250,31140,  76250,3160 }),
    MakePath({ 78470,940,  79530,940,  79530,33360,  78470,33360,  78470,940 }),
    MakePath({ 27070,5330,  28350,5330,  28350,28790,  27070,28790,  27070,5330 }),
    MakePath({ 0,940,  940,940,  940,33360,  0,33360,  0,940 }),
    MakePath({ 26410,8325,  26790,8325,  26790,28350,  26410,28350,  26410,8325 }),
    MakePath({ 3160,4050,  28350,4050,  28350,5330,  3160,5330,  3160,4050 }),
    MakePath({ 1880,4050,  3160,4050,  3160,30070,  1880,30070,  1880,4050 }),
    MakePath({ 6210,23590,  26130,23590,  26130,23970,  6210,23970,  6210,23590 }),
    MakePath({ 31290,3160,  32570,3160,  32570,31140,  31290,31140,  31290,3160 }),
    MakePath({ 29290,940,  30350,940,  30350,33360,  29290,33360,  29290,940 })
  };
 PolyTree64 pt; Clipper64 c; c.AddSubject(subject); c.Execute(ClipType::Union, FillRule::NonZero, pt);
 printf("ver %s bad=%d\n", CLIPPER2_VERSION, bad(pt)); dump(pt);
}
