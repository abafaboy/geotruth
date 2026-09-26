// The same defect through JTS (public API only).
// Build/run: javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
//
// Case 1 is the GEOS reproducer (repro.c). JTS 1.20.0 happens to get it right.
// Case 2 is a sibling input with the same structure that JTS 1.20.0 (and GEOS 3.13.1,
// 3.14.1) get wrong: the intersection comes out empty although it is a triangle of area
// 1/6 (vertices (-1e-20,0), (1,1) and about (0, 1/3)).
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

public class Repro {
  static void run(String label, String wa, String wb, String[] expected) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a = r.read(wa);
    Geometry b = r.read(wb);
    System.out.println("== " + label + ": A = " + wa + "  B = " + wb);
    System.out.println("isValid(A)=" + a.isValid() + " isValid(B)=" + b.isValid()
        + " area(A)=" + a.getArea() + " area(B)=" + b.getArea());
    String[] names = {"union", "intersection", "B - A", "A - B", "symdifference"};
    Geometry[][] args = {{a, b}, {a, b}, {b, a}, {a, b}, {a, b}};
    int[] ops = {OverlayNG.UNION, OverlayNG.INTERSECTION, OverlayNG.DIFFERENCE,
                 OverlayNG.DIFFERENCE, OverlayNG.SYMDIFFERENCE};
    for (int i = 0; i < ops.length; i++) {
      Geometry g = OverlayNGRobust.overlay(args[i][0], args[i][1], ops[i]);
      System.out.printf("OverlayNGRobust %-13s area = %-22s (expected %s)%n",
          names[i], g.getArea(), expected[i]);
    }
  }

  public static void main(String[] argv) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    run("case 1", "POLYGON ((1 1, -1e-20 0, 1 0, 1 1))", "POLYGON ((0 0, 1 1, 0 1, 0 0))",
        new String[] {"~1.0", "~5e-21", "~0.5", "~0.5", "~1.0"});
    run("case 2", "POLYGON ((1 1, -1e-20 0, 0 1, 1 1))", "POLYGON ((0 0, 1 1, -2 -1, 0 0))",
        new String[] {"~0.8333", "~0.1667", "~0.3333", "~0.3333", "~0.6667"});
  }
}
