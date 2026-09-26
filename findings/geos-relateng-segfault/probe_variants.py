"""Run each (case, op) in a fresh subprocess; print result or the signal."""
import subprocess, sys, json
CODE = r'''
import sys, shapely
from shapely import wkt
a, b, op = wkt.loads(sys.argv[1]), wkt.loads(sys.argv[2]), sys.argv[3]
if op == "relate": print(shapely.relate(a, b))
elif op.startswith("prep_"):
    shapely.prepare(a); print(getattr(shapely, op[5:])(a, b))
else: print(getattr(shapely, op)(a, b))
'''
def run(a, b, op):
    p = subprocess.run([sys.executable, "-c", CODE, a, b, op], capture_output=True, text=True)
    if p.returncode < 0: return f"CRASH(signal {-p.returncode})"
    if p.returncode: return "ERROR " + p.stderr.strip().splitlines()[-1]
    return p.stdout.strip()
OPS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["relate"]
for line in sys.stdin:
    line = line.strip()
    if not line or line.startswith("#"): continue
    a, b = [s.strip() for s in line.split("|")]
    print(f"A = {a}\nB = {b}")
    for op in OPS:
        print(f"   {op:22s} {run(a, b, op)}   (swapped: {run(b, a, op)})", flush=True)
