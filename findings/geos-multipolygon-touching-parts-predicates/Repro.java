// JTS repro for RelateNG with polygonal rings that touch vertex-to-edge.
// Uses only the public JTS API.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;
import org.locationtech.jts.operation.valid.IsValidOp;

public class Repro {
  static final String[][] CASES = {
    // name, A, B, expected A.relate(B)
    {"1 MultiPolygon contains its own part",
     "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
     "2F2F11FF2"},
    {"2 Polygon shell contains the polygon with a touching hole",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
     "212F1FFF2"},
    {"3 Polygon with touching hole vs. adjacent polygon",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
     "POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))",
     "FF2F11212"},
  };

  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    for (String[] c : CASES) {
      Geometry a = r.read(c[1]), b = r.read(c[2]);
      System.out.println("case " + c[0]);
      System.out.println("  A = " + c[1]);
      System.out.println("  B = " + c[2]);
      System.out.println("  isValid(A) = " + new IsValidOp(a).isValid() + ", isValid(B) = " + new IsValidOp(b).isValid());
      System.out.println("  expected relate      = " + c[3]);
      System.out.println("  RelateOp (default)   = " + a.relate(b)
          + "  contains=" + a.contains(b) + " touches=" + a.touches(b) + " overlaps=" + a.overlaps(b));
      System.out.println("  RelateNG.relate      = " + RelateNG.relate(a, b)
          + "  contains=" + RelateNG.relate(a, b, RelatePredicate.contains())
          + " touches=" + RelateNG.relate(a, b, RelatePredicate.touches())
          + " overlaps=" + RelateNG.relate(a, b, RelatePredicate.overlaps()));
    }
  }
}
