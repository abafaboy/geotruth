// JTS: same cases as repro.c, with RelateNG and with the default (old RelateOp) engine.
// Uses only the public JTS API.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;

public class Repro {
  static int nbad = 0;

  static void check(String what, boolean got, boolean expected) {
    if (got != expected) nbad++;
    System.out.printf("  %-34s %-5s  (expected %-5s) %s%n", what, got, expected, got == expected ? "" : "<-- WRONG");
  }

  static void run(String title, String wa, String wb, String wp, String expIM,
                  boolean touches, boolean overlaps, boolean contains, boolean pInA) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a = r.read(wa), b = r.read(wb), p = r.read(wp);
    System.out.println(title + "\n  A = " + wa + "\n  B = " + wb);
    System.out.println("  isValid(A) = " + a.isValid() + ", isValid(B) = " + b.isValid());
    String imOld = a.relate(b).toString();
    String imNG = RelateNG.relate(a, b).toString();
    if (!imOld.equals(expIM)) nbad++;
    if (!imNG.equals(expIM)) nbad++;
    System.out.printf("  Geometry.relate (RelateOp)         %s  (expected %s) %s%n", imOld, expIM, imOld.equals(expIM) ? "" : "<-- WRONG");
    System.out.printf("  RelateNG.relate                    %s  (expected %s) %s%n", imNG, expIM, imNG.equals(expIM) ? "" : "<-- WRONG");
    check("RelateNG touches(A, B)", RelateNG.relate(a, b, RelatePredicate.touches()), touches);
    check("RelateNG overlaps(A, B)", RelateNG.relate(a, b, RelatePredicate.overlaps()), overlaps);
    check("RelateNG contains(A, B)", RelateNG.relate(a, b, RelatePredicate.contains()), contains);
    check("RelateNG covers(A, B)", RelateNG.relate(a, b, RelatePredicate.covers()), contains);
    RelateNG prep = RelateNG.prepare(a);
    check("RelateNG prepared touches(A, B)", prep.evaluate(b, RelatePredicate.touches()), touches);
    check("RelateNG prepared contains(A, B)", prep.evaluate(b, RelatePredicate.contains()), contains);
    System.out.println("  P = " + wp + " (a vertex of B)");
    check("RelateNG intersects(B, P)", RelateNG.relate(b, p, RelatePredicate.intersects()), true);
    check("RelateNG contains(A, P)", RelateNG.relate(a, p, RelatePredicate.contains()), pInA);
    System.out.println();
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + org.locationtech.jts.JTSVersion.CURRENT_VERSION + "\n");
    run("Case 1: B's vertex P lies inside A, 3.7e-17 (vertically) below A's edge (0 0)-(3 1)",
        "POLYGON ((0 0, 3 0, 3 1, 0 0))",
        "POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))",
        "POINT (2 0.6666666666666666)",
        "212101212", false, true, false, true);
    run("Case 2: B's vertex P lies outside A, 3.7e-17 (vertically) above A's edge (0 0)-(3 1)",
        "POLYGON ((0 0, 3 0, 3 1, 0 0))",
        "POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))",
        "POINT (2.5 0.8333333333333334)",
        "212101212", false, true, false, false);
    System.out.println(nbad + " wrong answer(s)");
  }
}
