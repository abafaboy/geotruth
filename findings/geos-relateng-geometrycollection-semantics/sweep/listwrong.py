"""python3 listwrong.py NAME build [build2]: list cases whose relate (either order) is wrong in build (and status in build2)."""
import sys
sys.path.insert(0, "/home/user/geotruth/src")
from geotruth.predicates import transpose
name, b1 = sys.argv[1], sys.argv[2]
others = sys.argv[3:]
rows = [l.rstrip("\n").split("\t") for l in open(f"{name}.tsv")]
ex = [l.strip() for l in open(f"{name}.exact")]
outs = {b: [l.split() for l in open(f"{name}.{b}")] for b in [b1, *others]}
for i, ((a, b), e) in enumerate(zip(rows, ex)):
    o = outs[b1][i]
    if o[0] != e or o[1] != transpose(e):
        st = " ".join(f"{bb}:{'ok' if outs[bb][i][0]==e and outs[bb][i][1]==transpose(e) else outs[bb][i][0]+'/'+outs[bb][i][1]}" for bb in others)
        print(f"#{i} exact {e} | {b1}: {o[0]} {o[1]} | {st}\n   A={a}\n   B={b}")
