// Which change is responsible for which part of the KdTree behaviour (public API only).
// Run against jts-core built at several commits (javac of modules/core/src/main/java, as in
// bisect_step.sh) and against release jars; the output is in output_history.txt.
//
//   1. new KdTree(0.0), insert (0 0) and (1e-170 0): number of nodes (2 is right)
//   2. new KdTree(1e155), insert (0 0) and (1e300 0): number of nodes (2 is right)
//   3. OverlayNGRobust UNION of A*2^k with itself, A = POLYGON ((0 0, 2 1, 1 2, 0 0)):
//      the first k in [500, 1021] where the result is empty ("none" is right)
//   4. the corpus case line-polygon-1-000090 divided by 2^194 (max |ordinate| 1.5e162):
//      is OverlayNGRobust UNION empty? ("false" is right)
import org.locationtech.jts.geom.*;
import org.locationtech.jts.index.kdtree.KdTree;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;

public class History {
  public static void main(String[] args) throws Exception {
    KdTree tiny = new KdTree(0.0);
    tiny.insert(new Coordinate(0, 0));
    tiny.insert(new Coordinate(1e-170, 0));
    KdTree big = new KdTree(1e155);
    big.insert(new Coordinate(0, 0));
    big.insert(new Coordinate(1e300, 0));

    GeometryFactory gf = new GeometryFactory();
    String firstEmpty = "none";
    for (int k = 500; k <= 1021; k++) {
      double s = Math.scalb(1.0, k);
      Geometry a = gf.createPolygon(new Coordinate[] {
          new Coordinate(0, 0), new Coordinate(2 * s, s), new Coordinate(s, 2 * s), new Coordinate(0, 0) });
      if (OverlayNGRobust.overlay(a, a, OverlayNG.UNION).isEmpty()) { firstEmpty = "k = " + k; break; }
    }

    WKTReader r = new WKTReader();
    Geometry ca = r.read("POLYGON ((-1.4498499853679761e162 1.5242294244407106e162, -1.4498493417931955e162 1.524226850141588e162, -1.4498486982184148e162 1.52422878086593e162, -1.4498499853679761e162 1.5242294244407106e162))");
    Geometry cb = r.read("MULTILINESTRING ((-1.4498493417931955e162 1.524226850141588e162, -1.4498486982184148e162 1.52422878086593e162), (-1.4498433350952429e162 1.5242335004143213e162, -1.4498429060453891e162 1.524234143989102e162))");
    boolean corpusEmpty = OverlayNGRobust.overlay(ca, cb, OverlayNG.UNION).isEmpty();

    System.out.println("  1. KdTree(0.0), points 1e-170 apart: " + tiny.size() + " node(s)");
    System.out.println("  2. KdTree(1e155), points 1e300 apart: " + big.size() + " node(s)");
    System.out.println("  3. triangle self-union, first empty: " + firstEmpty);
    System.out.println("  4. corpus case at 1.5e162, union empty: " + corpusEmpty);
  }
}
