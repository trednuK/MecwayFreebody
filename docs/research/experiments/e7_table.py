# E7: the compact tables out of the result files. Worst cut, worst step, per route and case.
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e7_lib import WD


def load(names):
    rows = []; info = []
    for n in names:
        p = os.path.join(WD, n)
        if os.path.exists(p):
            d = json.load(open(p))
            rows += d["rows"]; info += d["info"]
    return rows, info


def table(rows, var_pick):
    """Per case: worst eF, eM, raw F, raw M for each route."""
    t = {}
    for q in rows:
        v = var_pick(q["case"])
        if q["var"] != v:
            continue
        a = t.setdefault((q["case"], q["route"]), [0, 0, 0, 0, 0, 0])
        for i, k in enumerate(("eF", "eM", "rawF", "rawM", "tabM", "rout")):
            a[i] = max(a[i], q.get(k, 0.))
    return t


def show(t):
    cases = []
    for c, r in t:
        if c not in cases:
            cases.append(c)
    for c in cases:
        s = ["%-16s" % c]
        for r in ("A", "B", "B0", "Bm", "C"):
            if (c, r) in t:
                a = t[(c, r)]
                s.append("%s %.0e/%.0e" % (r, a[0], a[1]))
        a = t[(c, [r for r in ("A", "B", "C") if (c, r) in t][0])]
        s.append("raw %.0e/%.0e tabM %.0e rout %.0e" % (a[2], a[3], a[4], a[5]))
        print("  ".join(s))


if __name__ == "__main__":
    rows, info = load(["res_solid.json", "res_struct.json", "res_struct_c3d.json"])
    print("linear, volume and structural (REAC on S, for solids without skin next to S)")
    show(table(rows, lambda c: "REAC"))
    rows, info2 = load(["res_loads.json"])
    print("model 5, S plus skin")
    show(table(rows, lambda c: "REACSK"))
    print("model 5, S without skin")
    show(table(rows, lambda c: "REAC"))
    rows, info3 = load(["res_nl.json"])
    print("nonlinear, S (S plus skin with a follower)")
    show(table(rows, lambda c: "REACSK" if "prs" in c else "REAC"))
    for i in info+info2+info3:
        print(i["case"], i["cells"], "rmed %.2f MB base %.1f MB" % (i.get("rmed_MB") or 0, i.get("base_MB") or 0),
              {k: round(i[k]["wall"], 1) for k in ("A", "P", "B", "B0", "Bm", "C") if k in i and "wall" in i[k]})
