// JTS RelateNG on GeometryCollections with an EMPTY element (the GEOS segfault cases).
// Uses only the public JTS API.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;
import org.locationtech.jts.operation.valid.IsValidOp;

public class Repro {
  static final String[][] CASES = {
    // name, A, B, expected RelateNG.relate(A, B)
    {"1 point on the shared edge of two squares, GC has a POLYGON EMPTY (GEOS: SIGSEGV)",
     "POINT (2 1)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)",
     "0FFFFF212"},
    {"2 GC(point, LINESTRING EMPTY) vs POINT EMPTY (GEOS: SIGSEGV)",
     "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)",
     "POINT EMPTY",
     "FF0FFFFF2"},
    {"3 GC(line, POLYGON EMPTY) vs a disjoint point (GEOS: wrong matrix)",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)",
     "POINT (5 5)",
     "FF1FF00F2"},
  };

  static String run(java.util.concurrent.Callable<Object> f) {
    try {
      return String.valueOf(f.call());
    } catch (Throwable t) {
      StackTraceElement top = t.getStackTrace().length > 0 ? t.getStackTrace()[0] : null;
      return "THROWS " + t + (top == null ? "" : "\n      at " + top);
    }
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    WKTReader r = new WKTReader();
    for (String[] c : CASES) {
      Geometry a = r.read(c[1]), b = r.read(c[2]);
      System.out.println("\ncase " + c[0]);
      System.out.println("  A = " + c[1]);
      System.out.println("  B = " + c[2]);
      System.out.println("  isValid(A) = " + new IsValidOp(a).isValid() + ", isValid(B) = " + new IsValidOp(b).isValid());
      System.out.println("  expected relate(A,B)      = " + c[3]);
      String m = run(() -> RelateNG.relate(a, b));
      System.out.println("  RelateNG.relate(A,B)      = " + m + (m.equals(c[3]) ? "   ok" : "   <-- WRONG"));
      System.out.println("  RelateNG.relate(B,A)      = " + run(() -> RelateNG.relate(b, a)));
      System.out.println("  RelateNG intersects(A,B)  = " + run(() -> RelateNG.relate(a, b, RelatePredicate.intersects())));
    }
  }
}
