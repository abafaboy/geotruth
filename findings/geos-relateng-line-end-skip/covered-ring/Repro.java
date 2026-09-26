// RelateNG (JTS master since c3d56e6, #1099): a linear or GC operand B is not self-noded
// when A is polygonal.
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;

public class Repro {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    String[][] cases = {
      {"case 1", "POLYGON ((0 0, 2 0, 1 1, 0 0))", "MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))", "FF210F102"},
      {"case 1, operands swapped", "MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))", "POLYGON ((0 0, 2 0, 1 1, 0 0))", "F11F002F2"},
      {"case 2 (rectangle)", "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))", "MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))", "FF210F102"},
      {"case 3 (one LineString)", "POLYGON ((0 0, 2 0, 1 1, 0 0))", "LINESTRING (0 0, 2 0, 1 1, 0 0, 1 -1, 1 0)", "FF210F1F2"},
      {"case 4 (hole touch)", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))", "LINESTRING (0 0, 4 0)", "FF2101FF2"},
      {"case 5 (touching parts)", "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))", "LINESTRING (0 2, 2 2)", "FF2101FF2"},
      {"case 6 (GC as B)", "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))", "2FF11F212"},
    };
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    for (String[] c : cases) {
      Geometry a = r.read(c[1]), b = r.read(c[2]);
      String ng = RelateNG.relate(a, b).toString();
      //-- the default RelateOp does not accept GeometryCollections
      String op = b.getClass() == org.locationtech.jts.geom.GeometryCollection.class ? "(n/a: GC)" : a.relate(b).toString();
      System.out.printf("%-26s RelateNG.relate = %s %-5s  Geometry.relate (RelateOp) = %s  exact %s%n",
          c[0], ng, ng.equals(c[3]) ? "ok" : "WRONG", op, c[3]);
    }
    Geometry a4 = r.read(cases[4][1]), b4 = r.read(cases[4][2]);
    Geometry a5 = r.read(cases[5][1]), b5 = r.read(cases[5][2]);
    System.out.println("case 4: RelateNG contains = " + RelateNG.relate(a4, b4, RelatePredicate.contains())
        + " (exact false), touches = " + RelateNG.relate(a4, b4, RelatePredicate.touches()) + " (exact true)");
    System.out.println("case 5: RelateNG covers = " + RelateNG.relate(a5, b5, RelatePredicate.covers()) + " (exact true)");
    Geometry a6 = r.read(cases[6][1]), b6 = r.read(cases[6][2]);
    System.out.println("case 6: RelateNG within = " + RelateNG.relate(a6, b6, RelatePredicate.within())
        + " (exact true), contains(B, A) = " + RelateNG.relate(b6, a6, RelatePredicate.contains()) + " (exact true)");
  }
}
