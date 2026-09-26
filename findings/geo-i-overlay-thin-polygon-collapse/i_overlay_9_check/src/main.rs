// i_overlay 9.0.0 (latest release): same inputs as the geo repro, float API with the
// default i32 engine and with the i64 engine, OGC options (as geo uses), EvenOdd.
use i_overlay::core::fill_rule::FillRule;
use i_overlay::core::overlay_rule::OverlayRule;
use i_overlay::float::overlay::{FloatOverlay, OverlayOptions};

fn area(shapes: &Vec<Vec<Vec<[f64; 2]>>>) -> f64 {
    let mut s = 0.0;
    for sh in shapes { for (k, c) in sh.iter().enumerate() {
        let mut a = 0.0;
        let o = c[0]; // shoelace relative to the first vertex (exact for these inputs)
        for i in 0..c.len() { let p = c[i]; let q = c[(i + 1) % c.len()]; a += (p[0] - o[0]) * (q[1] - o[1]) - (q[0] - o[0]) * (p[1] - o[1]); }
        s += if k == 0 { a.abs() / 2.0 } else { -a.abs() / 2.0 };
    }}
    s
}
fn run(name: &str, a: &Vec<[f64; 2]>, b: &Vec<[f64; 2]>, rule: OverlayRule) {
    let r32 = FloatOverlay::<[f64; 2], i32>::from_subj_and_clip_custom(a, b, OverlayOptions::<f64, i32>::ogc(), Default::default()).overlay(rule, FillRule::EvenOdd);
    let r64 = FloatOverlay::<[f64; 2], i64>::from_subj_and_clip_custom(a, b, OverlayOptions::<f64, i64>::ogc(), Default::default()).overlay(rule, FillRule::EvenOdd);
    println!("{name:<22} i32: area {:<14} {:?}", area(&r32), r32);
    println!("{:<22} i64: area {:<14} {:?}", "", area(&r64), r64);
}
fn main() {
    let t = vec![[0.0, 0.0], [1.0, 0.0], [0.0, 2e9]];
    run("[1] A∩A", &t, &t, OverlayRule::Intersect);
    run("[1] A∪A", &t, &t, OverlayRule::Union);
    let a = vec![[0.0, 0.0], [2e9, 0.0], [2e9, 2e9], [0.0, 2e9]];
    let b = vec![[-2e9 + 1.0, 0.0], [1.0, 0.0], [1.0, 2e9], [-2e9 + 1.0, 2e9]];
    run("[2] A∩B", &a, &b, OverlayRule::Intersect);
    let d = vec![[0.0, 0.0], [1.0, 0.0], [0.0, 1e9]];
    run("[3] A∩A", &d, &d, OverlayRule::Intersect);
    let f = vec![[-17592186044416.0, -17592186044416.0], [-17592186044415.0, -17592186044415.0], [-16492674416638.0, -18691697672192.0]];
    run("[4] A∩A", &f, &f, OverlayRule::Intersect);
    run("[4] A∪A", &f, &f, OverlayRule::Union);
}
