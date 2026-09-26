// Records the resolved versions of geo and i_overlay (from Cargo.lock) so the adapter can
// report them in the `lib` field without hard-coding.
use std::{env, fs, path::Path};

fn locked_version(lock: &str, name: &str) -> String {
    let mut in_pkg = false;
    for line in lock.lines() {
        let line = line.trim();
        if line == "[[package]]" {
            in_pkg = false;
        } else if line == format!("name = \"{name}\"") {
            in_pkg = true;
        } else if in_pkg && line.starts_with("version = \"") {
            return line["version = \"".len()..line.len() - 1].to_string();
        }
    }
    "unknown".to_string()
}

fn main() {
    let dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let lock_path = Path::new(&dir).join("Cargo.lock");
    println!("cargo:rerun-if-changed={}", lock_path.display());
    let lock = fs::read_to_string(&lock_path).unwrap_or_default();
    println!("cargo:rustc-env=GEO_VERSION={}", locked_version(&lock, "geo"));
    println!("cargo:rustc-env=I_OVERLAY_VERSION={}", locked_version(&lock, "i_overlay"));
}
