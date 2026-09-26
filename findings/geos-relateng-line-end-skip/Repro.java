// RelateNG line-end-skip (cases 1-3, fixed on master by #1200) and the same skip in
// computeAreaVertex (cases 4-5, not fixed) in JTS. Public API only.
// The default Geometry.relate (RelateOp) is shown for comparison; it does not accept
// GeometryCollections (IllegalArgumentException), so those cases reach only RelateNG.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;

public class Repro {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    String[][] cases = {
      {"case 1", "POINT (10 10)", "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))", "FF0FFF102"},
      {"case 1, B's elements swapped", "POINT (10 10)", "MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))", "FF0FFF102"},
      {"case 1, operands swapped", "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))", "POINT (10 10)", "FF1FF00F2"},
      {"case 1, degenerate closed elem", "POINT (10 10)", "MULTILINESTRING ((0 0, 1 0, 0 0), (5 5, 6 6))", "FF0FFF102"},
      {"case 2", "POLYGON ((1 2, 4 0, 1 0, 1 2))", "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))", "1F2001102"},
      {"case 2, operands swapped", "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))", "POLYGON ((1 2, 4 0, 1 0, 1 2))", "101F00212"},
      {"case 3 (JTS #1175)", "LINESTRING (10 10, 20 20)", "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (-1 0, 0 0))", "FF1FF0102"},
      {"case 4 (GC, computeAreaVertex)", "GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", "LINESTRING (10 10, 11 11)", "FF2FF1102"},
      {"case 4, squares swapped", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))", "LINESTRING (10 10, 11 11)", "FF2FF1102"},
      {"case 4, operands swapped", "LINESTRING (10 10, 11 11)", "GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", "FF1FF0212"},
      {"case 5 (GC, nested squares)", "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))", "LINESTRING (10 10, 11 11)", "FF2FF1102"},
      {"case 5, squares swapped", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)))", "LINESTRING (10 10, 11 11)", "FF2FF1102"},
      {"case 5, operands swapped", "LINESTRING (10 10, 11 11)", "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))", "FF1FF0212"},
    };
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    for (String[] c : cases) {
      Geometry a = r.read(c[1]), b = r.read(c[2]);
      String ng = RelateNG.relate(a, b).toString();
      String op;
      try {
        op = a.relate(b).toString();
      } catch (IllegalArgumentException e) {
        op = "IllegalArgumentException";   //-- RelateOp does not accept GeometryCollections
      }
      System.out.printf("%-30s RelateNG.relate = %s %-5s  Geometry.relate (RelateOp) = %s  exact %s%n",
          c[0], ng, ng.equals(c[3]) ? "ok" : "WRONG", op, c[3]);
    }
  }
}
