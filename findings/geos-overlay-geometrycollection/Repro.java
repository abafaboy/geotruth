// JTS on the inputs of the GEOS GeometryCollection overlay report, for contrast.
// JTS documents that Geometry.difference/symDifference/union do not support non-empty
// GeometryCollection arguments (IllegalArgumentException); Geometry.intersection maps a
// GC first operand element by element.  JTS has no counterpart of GEOS's
// StructuredCollection, so the GEOS defects cannot occur there.
//
// Build/run: javac -cp jts-core.jar -d out Repro.java && java -cp jts-core.jar:out Repro <version>
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

public class Repro {
    static final String[][] CASES = {
        {"1a", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "POINT (3 3)", "symdifference"},
        {"1b", "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", "symdifference"},
        {"1c", "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", "symdifference"},
        {"1e", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "LINESTRING (1 1, 6 6)", "symdifference"},
        {"2a", "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))", "difference"},
        {"3a", "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", "intersection"},
        {"3b", "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "intersection"},
        {"3c", "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "difference"},
        {"3d", "GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))", "MULTIPOLYGON EMPTY", "intersection"},
    };

    static String geometryOp(Geometry a, Geometry b, String op) {
        try {
            switch (op) {
                case "intersection": return a.intersection(b).toText();
                case "difference": return a.difference(b).toText();
                default: return a.symDifference(b).toText();
            }
        } catch (Exception e) {
            return e.getClass().getSimpleName() + ": " + e.getMessage();
        }
    }

    static String overlayNG(Geometry a, Geometry b, String op) {
        int code = op.equals("intersection") ? OverlayNG.INTERSECTION
                 : op.equals("difference") ? OverlayNG.DIFFERENCE : OverlayNG.SYMDIFFERENCE;
        try {
            return OverlayNGRobust.overlay(a, b, code).toText();
        } catch (Exception e) {
            return e.getClass().getSimpleName() + ": " + e.getMessage();
        }
    }

    public static void main(String[] args) throws Exception {
        WKTReader r = new WKTReader();
        System.out.println("JTS " + (args.length > 0 ? args[0] : "(pass the version as an argument)"));
        for (String[] c : CASES) {
            Geometry a = r.read(c[1]), b = r.read(c[2]);
            System.out.println("\ncase " + c[0] + " " + c[3] + "\n  A = " + c[1] + "\n  B = " + c[2]);
            System.out.println("  Geometry." + c[3] + ": " + geometryOp(a, b, c[3]));
            System.out.println("  OverlayNGRobust.overlay: " + overlayNG(a, b, c[3]));
        }
    }
}
