// Random-configuration check of PolyTree64 nesting (public API only), used for the numbers in ISSUE.md.
// Build: g++ -O2 -std=c++17 -I$C/CPP/Clipper2Lib/include fuzz_inscribed.cpp $C/CPP/Clipper2Lib/src/clipper.engine.cpp -o fuzz && ./fuzz 20000
// (SHOW=1 prints every configuration whose tree is wrong.)
// Random inscribed rings: A = random lattice polygon (convex hull of random points, 3..6 vertices),
// B = polygon through lattice points strictly inside A's edges (one per edge where available).
// Checks the PolyTree of Difference(A,B) and of Union({outer square, A, B}) for orientation/level agreement.
#include "clipper2/clipper.h"
#include <cstdio>
#include <random>
#include <numeric>
using namespace Clipper2Lib;
static int bad_nodes(const PolyPath64& n){int b=0;for(size_t i=0;i<n.Count();++i){const PolyPath64*c=n[i];if((Area(c->Polygon())<0)!=c->IsHole())++b;b+=bad_nodes(*c);}return b;}
int main(int argc,char**argv){
  int N=argc>1?atoi(argv[1]):20000; std::mt19937_64 rng(12345);
  std::uniform_int_distribution<int> U(-60,60), K(3,6);
  int tried=0, badDiff=0, badNest=0;
  for(int it=0;it<N;++it){
    Paths64 pts1={Path64()}; int k=K(rng);
    Path64 pts; for(int i=0;i<k*3;++i) pts.emplace_back(U(rng),U(rng));
    // convex hull (monotone chain)
    std::sort(pts.begin(),pts.end(),[](const Point64&a,const Point64&b){return a.x<b.x||(a.x==b.x&&a.y<b.y);});
    pts.erase(std::unique(pts.begin(),pts.end()),pts.end());
    if(pts.size()<3)continue;
    Path64 h(2*pts.size()); size_t m=0;
    auto cr=[](const Point64&o,const Point64&a,const Point64&b){return (a.x-o.x)*(b.y-o.y)-(a.y-o.y)*(b.x-o.x);};
    for(size_t i=0;i<pts.size();++i){while(m>=2&&cr(h[m-2],h[m-1],pts[i])<=0)--m;h[m++]=pts[i];}
    for(size_t i=pts.size()-1,t=m+1;i-->0;){while(m>=t&&cr(h[m-2],h[m-1],pts[i])<=0)--m;h[m++]=pts[i];}
    h.resize(m-1); if(h.size()<3)continue;
    if(h.size()>(size_t)k){ h.resize(k); }
    // A must still be convex & ccw: take first k hull vertices is still convex
    Path64 B;
    for(size_t i=0;i<h.size();++i){const Point64&p=h[i],&q=h[(i+1)%h.size()];
      long long g=std::gcd(std::llabs(q.x-p.x),std::llabs(q.y-p.y)); if(g<2)continue;
      long long t=1+(long long)(rng()%(g-1)); B.emplace_back(p.x+(q.x-p.x)/g*t,p.y+(q.y-p.y)/g*t);}
    if(B.size()<3||std::fabs(Area(B))==0)continue;
    ++tried;
    {Clipper64 c;c.AddSubject({h});c.AddClip({B});PolyTree64 t;c.Execute(ClipType::Difference,FillRule::EvenOdd,t);if(bad_nodes(t)){++badDiff; if(getenv("SHOW")){printf("D A:");for(auto&p:h)printf(" %lld,%lld",(long long)p.x,(long long)p.y);printf("  B:");for(auto&p:B)printf(" %lld,%lld",(long long)p.x,(long long)p.y);printf("\n");}}}
    {Clipper64 c;c.AddSubject({MakePath({-100,-100,100,-100,100,100,-100,100}),h,B});PolyTree64 t;c.Execute(ClipType::Union,FillRule::EvenOdd,t);if(bad_nodes(t)){++badNest; if(getenv("SHOW")){printf("A:");for(auto&p:h)printf(" %lld,%lld",(long long)p.x,(long long)p.y);printf("  B:");for(auto&p:B)printf(" %lld,%lld",(long long)p.x,(long long)p.y);printf("\n");}}}
  }
  printf("Clipper2 %s: %d random inscribed configurations; Difference(A,B) tree wrong in %d; Union({square,A,B}) tree wrong in %d\n",CLIPPER2_VERSION,tried,badDiff,badNest);
}
