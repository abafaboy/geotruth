// OverlayNG: union / symDifference of a polygonal geometry and a point throw ClassCastException
// ("LineString cannot be cast to Polygon") when a polygon of the input collapses to a line
// under the precision model (OverlayMixedPoints.extractPolygons casts every element of the
// noded polygonal operand to Polygon).
//
// Public API only.
//   javac -cp jts-core.jar -d out Repro.java && java -cp jts-core.jar:out Repro
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.PrecisionModel;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

public class Repro {
  static final String[] NAMES = {"", "INTERSECTION", "UNION", "DIFFERENCE", "SYMDIFFERENCE"};

  static String run(Geometry a, Geometry b, int op, PrecisionModel pm, boolean strict) {
    try {
      OverlayNG ov = new OverlayNG(a, b, pm, op);
      ov.setStrictMode(strict);
      return ov.getResult().toText();
    } catch (RuntimeException e) {
      return "threw " + e;
    }
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    WKTReader r = new WKTReader();
    PrecisionModel grid1 = new PrecisionModel(1.0);
    // a unit square plus a thin triangle; on the integer grid (5 0.4) snaps to (5 0) and the
    // triangle collapses to the segment (3 0)-(5 0)
    Geometry a = r.read("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((3 0, 5 0, 5 0.4, 3 0)))");
    Geometry p = r.read("POINT (7 7)");
    System.out.println("A = " + a + "\nP = " + p + "\nprecision model: " + grid1);

    System.out.println("\n1. OverlayNG.overlay(A, P, op, new PrecisionModel(1))");
    for (int op = 1; op <= 4; op++) {
      System.out.println("  " + NAMES[op] + "(A, P) = " + run(a, p, op, grid1, false));
      System.out.println("  " + NAMES[op] + "(P, A) = " + run(p, a, op, grid1, false));
    }
    System.out.println("  expected UNION and SYMDIFFERENCE (non-strict, as for a line or polygon operand below):");
    System.out.println("    GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0), POINT (7 7))");

    System.out.println("\n2. Strict mode (setStrictMode(true))");
    for (int op = 1; op <= 4; op++)
      System.out.println("  " + NAMES[op] + "(A, P) = " + run(a, p, op, grid1, true));

    System.out.println("\n3. The same A with a line or a polygon instead of the point (how collapses are treated)");
    Geometry l = r.read("LINESTRING (7 7, 8 8)");
    Geometry q = r.read("POLYGON ((7 7, 8 7, 8 8, 7 7))");
    System.out.println("  UNION(A, " + l + ")         = " + run(a, l, OverlayNG.UNION, grid1, false));
    System.out.println("  UNION(A, " + l + ") strict  = " + run(a, l, OverlayNG.UNION, grid1, true));
    System.out.println("  UNION(A, " + q + ")         = " + run(a, q, OverlayNG.UNION, grid1, false));
    System.out.println("  UNION(A, " + q + ") strict  = " + run(a, q, OverlayNG.UNION, grid1, true));

    System.out.println("\n4. OverlayNGRobust (floating precision) on the corpus case point-geometry-1-000016-in-hole.ba.int.extreme");
    System.out.println("   (coordinates ~1e-161: the orientation underflow of JTS/GEOS at this scale collapses the small triangle,");
    System.out.println("    then the same cast fails)");
    Geometry ca = r.read("MULTIPOLYGON (((-1.1513195710223487e-161 -6.121269212449139e-162, -7.736242366371891e-162 -7.163187376270269e-162, -6.173365120640196e-162 -6.750761436424405e-162, -9.364239497342407e-162 -1.8233567866869776e-162, -1.1513195710223487e-161 -6.121269212449139e-162), (-8.930106929083602e-162 -4.254499168936281e-162, -7.866482136849532e-162 -5.904202928319737e-162, -8.387441218760097e-162 -6.034442698797378e-162, -9.64642566671063e-162 -5.687136644190335e-162, -8.930106929083602e-162 -4.254499168936281e-162)), ((5.730549901016215e-162 9.125466584800064e-162, 5.752256529429156e-162 9.125466584800064e-162, 5.730549901016215e-162 9.147173213213004e-162, 5.730549901016215e-162 9.125466584800064e-162)))");
    Geometry cb = r.read("POINT (-8.708699319271612e-162 -5.470070360060933e-162)");
    for (int op : new int[] {OverlayNG.UNION, OverlayNG.SYMDIFFERENCE}) {
      String res;
      try {
        Geometry g = OverlayNGRobust.overlay(ca, cb, op);
        res = g.getGeometryType() + " with " + g.getNumGeometries() + " elements";
      } catch (RuntimeException e) {
        res = "threw " + e;
      }
      System.out.println("  OverlayNGRobust.overlay(A, P, " + NAMES[op] + ") " + res);
    }
  }
}
