//! Stand-alone repro (geo public API only): a valid thin triangle vanishes from BooleanOps.
//!
//! cargo run --release --example repro_thin_triangle
//!
//! Case int-thin-triangle-1-0010 of ../clipper2/int_cases.jsonl. The triangle's exact area
//! is 1099511627777 (about 1.1e12), but A ∩ A and A ∪ A both come back empty.
//! geo's BooleanOps goes through i_overlay, which snaps every input to an integer grid with
//! step 2^(round(log2(half-extent)) - 29) around the bounding-box centre; here that is 1024
//! units, and the triangle is only about 1.4 units wide, so it collapses to nothing.
use geo::{Area, BooleanOps, Coord, LineString, Polygon};

fn main() {
    let a = Polygon::new(
        LineString(vec![
            Coord { x: -17592186044416.0, y: -17592186044416.0 },
            Coord { x: -17592186044415.0, y: -17592186044415.0 },
            Coord { x: -16492674416638.0, y: -18691697672192.0 },
            Coord { x: -17592186044416.0, y: -17592186044416.0 },
        ]),
        vec![],
    );
    use geo::Validation;
    println!("A valid: {}", a.is_valid());
    println!("area(A)     = {}", a.unsigned_area());
    println!("area(A ∩ A) = {}", a.intersection(&a).unsigned_area());
    println!("area(A ∪ A) = {}", a.union(&a).unsigned_area());
    println!("A ∪ A       = {:?}", a.union(&a));
}
