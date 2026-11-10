# E6: compact table from the result files in FB_WORK. One line per case, shape and method,
# with the worst cut. eF, eM: |error| / scale, scale = max(|F|, |M|/Lc) and max(|M|, |F|*Lc);
# eMraw: |error| / |M exact|. closure: sum over the cuts plus the loads on S.
import glob, json, os, sys

wd = os.environ["FB_WORK"]
names = sys.argv[1:] or ["e6_shell", "e6_solid", "e6_load", "e6_mixed"]
for nm in names:
    fn = os.path.join(wd, nm+".json")
    if not os.path.isfile(fn):
        continue
    rows = json.load(open(fn))
    print("\n== %s: %d rows" % (nm, len(rows)))
    keys = []
    for r in rows:
        k = (r["case"], r["shape"], r["method"])
        if k not in keys:
            keys.append(k)
    for k in keys:
        g = [r for r in rows if (r["case"], r["shape"], r["method"]) == k]
        bad = [r for r in g if "failed" in r]
        if bad:
            print("%-24s %-16s %-16s FAILED %s" % (k+(bad[0]["failed"][:90],)))
            continue
        if k[2] in ("global", "hypothesis"):
            continue
        cl = [r for r in g if "closeF" in r]
        print("%-24s %-16s %-16s eF %.1e eM %.1e eMraw %.1e  cuts %d  close %s  nodal %s  drill %s" % (
            k[0], k[1], k[2], max(r["eF"] for r in g), max(r["eM"] for r in g), max(r["eMraw"] for r in g), len(g),
            ("%.0e/%.0e" % (cl[0]["closeF"], cl[0]["closeM"])) if cl else "-",
            ("%.2f" % max(r.get("nodal", 0) for r in g)),
            ("%.0e" % max(r.get("drill") or 0 for r in g))))
    gl = [r for r in rows if r["method"] == "global"]
    if gl:
        print("worst global check: eF %.1e eM %.1e over %d models" % (max(r["eF"] for r in gl), max(r["eM"] for r in gl), len(gl)))
    ok = [r for r in rows if r["method"] in ("M4", "M4L", "M3") and "failed" not in r]
    for meth in ("M4", "M4L", "M3"):
        q = [r for r in ok if r["method"] == meth]
        if q:
            print("worst %s: eF %.1e (%s %s), eM %.1e (%s %s)" % (
                meth, *max((r["eF"], r["case"], r["shape"]) for r in q), *max((r["eM"], r["case"], r["shape"]) for r in q)))
