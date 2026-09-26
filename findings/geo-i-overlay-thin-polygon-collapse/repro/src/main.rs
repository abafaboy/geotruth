//! geo BooleanOps: a valid thin polygon vanishes (or changes area) because the overlay
//! snaps every input coordinate to an i32 grid sized from the joint bounding box.
//! Uses only geo's public API.
use geo::{Area, BooleanOps, Coord, LineString, MultiPolygon, Polygon, Relate, Validation};

fn poly(pts: &[(f64, f64)]) -> Polygon<f64> {
    let mut v: Vec<Coord<f64>> = pts.iter().map(|&(x, y)| Coord { x, y }).collect();
    v.push(v[0]);
    Polygon::new(LineString(v), vec![])
}

fn wkt(mp: &MultiPolygon<f64>) -> String {
    if mp.0.is_empty() {
        return "MULTIPOLYGON EMPTY".to_string();
    }
    let polys: Vec<String> = mp
        .0
        .iter()
        .map(|p| {
            let rings: Vec<String> = std::iter::once(p.exterior())
                .chain(p.interiors())
                .map(|r| {
                    let c: Vec<String> = r.0.iter().map(|c| format!("{} {}", c.x, c.y)).collect();
                    format!("({})", c.join(","))
                })
                .collect();
            format!("({})", rings.join(","))
        })
        .collect();
    format!("MULTIPOLYGON({})", polys.join(","))
}

fn show(label: &str, mp: &MultiPolygon<f64>) {
    println!("  {:<10} area = {:<22} {}", label, mp.unsigned_area(), wkt(mp));
}

fn main() {
    // 1. Minimal case: a right triangle 1 unit wide and 2e9 units tall (area exactly 1e9).
    let t = poly(&[(0.0, 0.0), (1.0, 0.0), (0.0, 2e9)]);
    println!("[1] A = POLYGON((0 0,1 0,0 2000000000,0 0))");
    println!("  is_valid(A) = {}   area(A) = {}", t.is_valid(), t.unsigned_area());
    show("A ∩ A", &t.intersection(&t));
    show("A ∪ A", &t.union(&t));
    show("A ∪ EMPTY", &t.union(&Polygon::<f64>::new(LineString(vec![]), vec![])));
    // Control: the same triangle made 4 units wide is returned exactly.
    let t4 = poly(&[(0.0, 0.0), (4.0, 0.0), (0.0, 2e9)]);
    println!("[1c] control A = POLYGON((0 0,4 0,0 2000000000,0 0)), area(A) = {}", t4.unsigned_area());
    show("A ∩ A", &t4.intersection(&t4));

    // 2. Two valid rectangles that overlap in a 1 x 2e9 strip (overlap area exactly 2e9).
    let a = poly(&[(0.0, 0.0), (2e9, 0.0), (2e9, 2e9), (0.0, 2e9)]);
    let b = poly(&[(-2e9 + 1.0, 0.0), (1.0, 0.0), (1.0, 2e9), (-2e9 + 1.0, 2e9)]);
    println!("[2] A = POLYGON((0 0,2000000000 0,2000000000 2000000000,0 2000000000,0 0))");
    println!("    B = POLYGON((-1999999999 0,1 0,1 2000000000,-1999999999 2000000000,-1999999999 0))");
    println!(
        "  is_valid(A) = {}  is_valid(B) = {}  relate(A,B) = {}",
        a.is_valid(),
        b.is_valid(),
        format!("{:?}", a.relate(&b))
    );
    println!("  relate(A,B).is_overlaps() = {}", a.relate(&b).is_overlaps());
    show("A ∩ B", &a.intersection(&b));

    // 3. Width 1, height 1e9: the triangle survives but is snapped to twice its width.
    let d = poly(&[(0.0, 0.0), (1.0, 0.0), (0.0, 1e9)]);
    println!("[3] A = POLYGON((0 0,1 0,0 1000000000,0 0))");
    println!("  is_valid(A) = {}   area(A) = {}", d.is_valid(), d.unsigned_area());
    show("A ∩ A", &d.intersection(&d));

    // 4. The fuzzer's original case (int-thin-triangle-1-0010), ~1.1e12 long and ~1.4 wide.
    let f = poly(&[
        (-17592186044416.0, -17592186044416.0),
        (-17592186044415.0, -17592186044415.0),
        (-16492674416638.0, -18691697672192.0),
    ]);
    println!("[4] A = POLYGON((-17592186044416 -17592186044416,-17592186044415 -17592186044415,-16492674416638 -18691697672192,-17592186044416 -17592186044416))");
    println!("  is_valid(A) = {}   area(A) = {}", f.is_valid(), f.unsigned_area());
    show("A ∩ A", &f.intersection(&f));
    show("A ∪ A", &f.union(&f));
}
