"""Characterise the systematic Boost.Geometry predicate differences on cases/seed.jsonl
(families rotated-neighbours and tiny-rotation[-offset]) against the exact oracle.

usage: python systematic_check.py SEED.jsonl ORACLE.jsonl BG183.jsonl BGDEV.jsonl SEGX_BINARY
  BG*.jsonl: adapters/boost_geometry/run_{1.83,develop}.sh output for SEED.jsonl
  SEGX_BINARY: segx.cpp built against the Boost.Geometry to inspect (develop here)
"""
import json, math, subprocess, sys
from collections import Counter
from fractions import Fraction as F

EPS = 2.220446049250313e-16
seed, orc_p, b183_p, bdev_p, segx = sys.argv[1:6]
load = lambda p: {r['id']: r for r in map(json.loads, filter(str.strip, open(p)))}
cases, orc, res = load(seed), load(orc_p), {'1.83': load(b183_p), 'develop': load(bdev_p)}

def state(r):
    return 'disjoint' if r['disjoint'] else 'touches' if r['touches'] else 'overlaps' if r['overlaps'] else 'within/contains/equal'

def orient(p, q, r):
    return (F(q[0]) - F(p[0])) * (F(r[1]) - F(p[1])) - (F(q[1]) - F(p[1])) * (F(r[0]) - F(p[0]))

def gap(A, B):  # exact min vertex-to-segment distance (sqrt rounded); boundaries are disjoint here
    best = None
    for P, Q in ((A, B), (B, A)):
        for p in P[:-1]:
            for i in range(len(Q) - 1):
                a, b = Q[i], Q[i + 1]
                dx, dy = F(b[0]) - F(a[0]), F(b[1]) - F(a[1])
                t = min(1, max(0, ((F(p[0]) - F(a[0])) * dx + (F(p[1]) - F(a[1])) * dy) / (dx * dx + dy * dy)))
                ex, ey = F(a[0]) + t * dx - F(p[0]), F(a[1]) + t * dy - F(p[1])
                d = ex * ex + ey * ey
                best = d if best is None or d < best else best
    return math.sqrt(best)

print('== rotated-neighbours: two unit squares edge to edge, the second shifted by 0..2 ulps')
rn = [c for c in cases.values() if c['family'] == 'rotated-neighbours']
for v in res:
    print(' ', v, sorted(Counter(('exact ' + state(orc[c['id']]), 'boost ' + state(res[v][c['id']])) for c in rn).items()))
dis = [c for c in rn if orc[c['id']]['disjoint']]
for v in res:
    wrong = [gap(c['a'][0][0], c['b'][0][0]) for c in dis if not res[v][c['id']]['disjoint']]
    right = [gap(c['a'][0][0], c['b'][0][0]) for c in dis if res[v][c['id']]['disjoint']]
    print('  %s: exact-disjoint pairs reported intersecting: %d, boundary gap %.3g .. %.3g; reported disjoint: %d, gap %.3g .. %.3g'
          % (v, len(wrong), min(wrong), max(wrong), len(right), min(right), max(right)))
# side_by_triangle on the shared-edge pair (the A/B edge pair whose midpoints are closest)
lines, ids = [], []
for c in dis:
    A, B = c['a'][0][0], c['b'][0][0]
    best = min(((math.hypot((A[i][0] + A[i+1][0] - B[j][0] - B[j+1][0]) / 2, (A[i][1] + A[i+1][1] - B[j][1] - B[j+1][1]) / 2), i, j)
                for i in range(4) for j in range(4)))
    _, i, j = best
    lines.append(' '.join(repr(x) for x in A[i] + A[i+1] + B[j] + B[j+1])); ids.append(c['id'])
out = subprocess.run([segx], input='\n'.join(lines) + '\n', capture_output=True, text=True, check=True).stdout.split('\n')
pat = {cid: tuple(map(int, o.split())) for cid, o in zip(ids, out)}
exact = {cid: tuple((lambda v: (v > 0) - (v < 0))(orient(*t)) for t in
                    ((l[4:6], l[6:8], l[0:2]), (l[4:6], l[6:8], l[2:4]), (l[0:2], l[2:4], l[4:6]), (l[0:2], l[2:4], l[6:8])))
         for cid, l in ((cid, list(map(float, s.split()))) for cid, s in zip(ids, lines))}
for tag, sel in (('reported touching', lambda c: res['develop'][c['id']]['touches']), ('reported disjoint', lambda c: res['develop'][c['id']]['disjoint'])):
    sub = [c['id'] for c in dis if sel(c)]
    print('  develop, exact-disjoint & %s (n=%d): shared-edge pair (intersects, 4 x side_by_triangle): %s; exact sides: %s'
          % (tag, len(sub), dict(Counter(pat[i] for i in sub)), dict(Counter(exact[i] for i in sub))))

print('\n== tiny-rotation(-offset): B = A (star polygon) rotated by 1e-16..1e-8 rad about one of its vertices')
tr = [c for c in cases.values() if c['family'].startswith('tiny-rotation')]
P = ['intersects', 'disjoint', 'touches', 'overlaps', 'within', 'covered_by', 'contains', 'covers', 'equals']
AR = ['area_inter', 'area_union', 'area_diff', 'area_symdiff']
def ratio(c):  # largest vertex displacement, in units of the math::equals tolerance eps*max(|a|,|b|,1)
    A, B = c['a'][0][0][:-1], c['b'][0][0][:-1]
    return max(abs(p[k] - q[k]) / (EPS * max(abs(p[k]), abs(q[k]), 1.0)) for p, q in zip(A, B) for k in (0, 1))
def bucket(x):
    return '0 (B==A)' if x == 0 else '<=1' if x <= 1 else '(1,4]' if x <= 4 else '(4,16]' if x <= 16 else '>16'
for v in res:
    cnt = Counter(); gross = 0
    for c in tr:
        o, r = orc[c['id']], res[v][c['id']]
        wrong = any(r[k] != o[k] for k in P)
        sc = max(o['area_a'], o['area_b'])
        gross += any(abs(r[k] - o[k]) > 1e-6 * sc for k in AR)
        cnt[(bucket(ratio(c)), 'wrong' if wrong else 'right')] += 1
    print('  %s: max vertex displacement / (eps*max(|coord|,1)) -> predicate results: %s; cases with an area error > 1e-6 relative: %d'
          % (v, dict(sorted(cnt.items())), gross))
    print('     wrong predicates:', dict(Counter(k for c in tr for k in P if res[v][c['id']][k] != orc[c['id']][k])))
