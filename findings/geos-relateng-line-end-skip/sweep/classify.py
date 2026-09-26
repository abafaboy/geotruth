import sys, collections
tsv, exact, *libs = sys.argv[1:]
cases = [l.rstrip("\n").split("\t") for l in open(tsv)]
ex = [l.strip() for l in open(exact)]
E = ("II","IB","IE","BI","BB","BE","EI","EB","EE")
for lib in libs:
    got = [l.strip() for l in open(lib)]
    cnt = collections.Counter(); samples = {}
    for (a, b), e, g in zip(cases, ex, got):
        if e == g: cnt["agree"] += 1; continue
        diff = [E[i] for i in range(9) if e[i] != g[i]]
        lost = all(e[E.index(d)] == "0" and g[E.index(d)] == "F" for d in diff) and set(diff) <= {"BE", "EB"}
        key = "lost-end " + ",".join(diff) if lost else "other " + ",".join(f"{d}:{e[E.index(d)]}->{g[E.index(d)]}" for d in diff)
        cnt[key] += 1
        samples.setdefault(key, (a, b, e, g))
    print("==", lib, dict(cnt))
    for k, s in samples.items():
        print("  ", k, "|", s[0], "|", s[1], "| exact", s[2], "got", s[3])
