// geos-relateng-geometrycollection-semantics: JTS RelateNG on valid GeometryCollections.
// Public JTS API only (RelateNG, RelatePredicate, IsValidOp, Geometry.union).
//   javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro
import org.locationtech.jts.JTSVersion;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;
import org.locationtech.jts.operation.relateng.TopologyPredicate;
import org.locationtech.jts.operation.valid.IsValidOp;

public class Repro {
  // id, A, B, exact relate(A,B), exact predicates: intersects contains within covers coveredBy touches overlaps crosses equals
  static final String[][] CASES = {
    {"d1-far-point-contains", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))",
     "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))", "212FF1FF2", "110100000"},
    {"d1-own-polygon", "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))",
     "POLYGON ((0 0, 1 0, 0 1, 0 0))", "2F0F1FFF2", "110100000"},
    {"d1-own-polygon-within", "POLYGON ((0 0, 1 0, 0 1, 0 0))",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))", "2FFF1F0F2", "101010000"},
    {"d1-interior-point-eb", "GEOMETRYCOLLECTION (POINT (2 2), POLYGON ((-1 -1, 5 -1, 5 5, -1 5, -1 -1), (1 1, 3 1, 3 3, 1 3, 1 1)))",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "2121F12F2", "100000100"},
    {"d1-line-covers-boundary-eb", "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 1 1, 0 1, 0 0), POINT (5 5))",
     "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))", "F10FFF2F2", "100001000"},
    {"d1-line-end-on-points", "LINESTRING (0 0, 1 0)",
     "GEOMETRYCOLLECTION (POINT (0 0), POINT (1 0), LINESTRING (5 5, 6 6))", "FF10FF102", "100001000"},
    {"d1-ring-within-point", "LINESTRING (0 0, 1 0, 0 1, 0 0)",
     "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))", "0F1FFF102", "100000010"},
    {"d1-testfile-closed-line", "GEOMETRYCOLLECTION (POLYGON ((3 2, 3 1, 1 0, 3 2)), MULTIPOINT ((3 4)))",
     "LINESTRING (3 4, 4 3, 3 4)", "0F2FF11F2", "100000010"},
    {"d1-testfile-line-ends", "LINESTRING (0 0, 1 0)",
     "GEOMETRYCOLLECTION (MULTIPOINT ((1 0), (0 0)), LINESTRING (5 5, 6 6))", "FF10FF102", "100001000"},
    {"d2-reflex-point", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))",
     "POINT (2 1)", "0F2FF1FF2", "110100000"},
    {"d2-reflex-point-swapped-elements", "GEOMETRYCOLLECTION (POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)), POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)))",
     "POINT (2 1)", "0F2FF1FF2", "110100000"},
    {"d2-reflex-line", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))",
     "LINESTRING (2 2, 2 0)", "102F01FF2", "110100000"},
    {"d2-adjacent-control", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((0 0, 2 1, 4 0, 0 0)))",
     "POINT (2 1)", "0F2FF1FF2", "110100000"},
    {"d2-testfile-gc-reflex", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))",
     "POINT (1 2)", "0F2FF1FF2", "110100000"},
    {"d2-testfile-gc-reflex-line", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))",
     "LINESTRING (1 2, 1 3)", "102FF1FF2", "110100000"},
    {"d3-frame-equals", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)), POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))",
     "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
    {"d3-frame-two-l-shapes", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 1 1, 1 3, 0 3, 0 0)), POLYGON ((3 3, 0 3, 0 2, 2 2, 2 0, 3 0, 3 3)))",
     "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
    {"d3-frame-control-polygon", "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0), (1 1, 1 2, 2 2, 2 1, 1 1))",
     "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", "2FF11F2F2", "101010000"},
    {"d3-frame-control-center", "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)), POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))",
     "POINT (1.5 1.5)", "FF2FF10F2", "000000000"},
    {"d3-no-boundary-vertex", "GEOMETRYCOLLECTION (POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2, 0 0, 1 1)))",
     "LINESTRING (5 5, 6 6)", "FF2FF1102", "000000000"},
    {"known-gc-overlap-as-b", "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))", "2FF11F212", "101010000"},
    {"known-empty-element", "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)",
     "POINT (5 5)", "FF1FF00F2", "000000000"},
  };
  static final String[] PN = {"intersects", "contains", "within", "covers", "coveredBy", "touches", "overlaps", "crosses", "equalsTopo"};

  static TopologyPredicate pred(int i) {
    switch (i) {
      case 0: return RelatePredicate.intersects();
      case 1: return RelatePredicate.contains();
      case 2: return RelatePredicate.within();
      case 3: return RelatePredicate.covers();
      case 4: return RelatePredicate.coveredBy();
      case 5: return RelatePredicate.touches();
      case 6: return RelatePredicate.overlaps();
      case 7: return RelatePredicate.crosses();
      default: return RelatePredicate.equalsTopo();
    }
  }

  static String transpose(String m) {
    StringBuilder s = new StringBuilder();
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) s.append(m.charAt(3 * j + i));
    return s.toString();
  }

  static String relate(Geometry a, Geometry b) {
    try { return RelateNG.relate(a, b).toString(); } catch (Throwable t) { return "THROWS " + t; }
  }

  public static void main(String[] args) throws Exception {
    System.out.println("JTS " + JTSVersion.CURRENT_VERSION);
    WKTReader r = new WKTReader();
    int wrong = 0;
    for (String[] c : CASES) {
      Geometry a = r.read(c[1]), b = r.read(c[2]);
      String m1 = relate(a, b), m2 = relate(b, a), tr = transpose(c[3]);
      String mu;
      try { mu = RelateNG.relate(a.union(), b).toString(); } catch (Throwable t) { mu = "THROWS " + t; }
      boolean bad = !m1.equals(c[3]) || !m2.equals(tr);
      System.out.println("\n[" + c[0] + "]  isValid: " + new IsValidOp(a).isValid() + ", " + new IsValidOp(b).isValid());
      System.out.println("  RelateNG.relate(A,B) = " + m1 + "   exact " + c[3] + (m1.equals(c[3]) ? "" : "   <-- WRONG"));
      System.out.println("  RelateNG.relate(B,A) = " + m2 + "   exact " + tr + (m2.equals(tr) ? "" : "   <-- WRONG"));
      System.out.println("  RelateNG.relate(A.union(),B) = " + mu + (mu.equals(c[3]) ? "   (= exact)" : ""));
      for (int i = 0; i < 9; i++) {
        boolean want = c[4].charAt(i) == '1';
        String got;
        try { got = String.valueOf(RelateNG.relate(a, b, pred(i))); } catch (Throwable t) { got = "THROWS " + t; }
        if (!got.equals(String.valueOf(want))) { System.out.println("  " + PN[i] + "(A,B) = " + got + "   exact " + want + "   <-- WRONG"); bad = true; }
      }
      if (!bad) System.out.println("  ok");
      if (bad) wrong++;
    }
    System.out.println("\n" + wrong + " of " + CASES.length + " cases wrong");
  }
}
