# E8: the kept base. About 20 000 cells: time to make the group in the POURSUITE, read-only opening,
# two follow-up runs at once, memory_limit of the POURSUITE. A first run that failed.
# Run: python e8_base.py big | ro | par | mem | fail | path
from e8_cut import *

DIMS = (72, 12, 24)
EXTRA = r"""
_tm = time_mod.perf_counter()
_names = tuple("M%d" % i for i in sel['ma']['F_SK'])
M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_MA=_F(NOM='G_NAM', MAILLE=_names))
OUT['maille_s'] = time_mod.perf_counter()-_tm
OUT['maille_same'] = sorted(int(i) for i in M.getCells('G_NAM')) == sorted(int(i) for i in M.getCells('F_SK'))
OUT['n_sel'] = len(_names)
lap('maille')
M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_MA=_F(NOM='G_UNI', UNION=('F_S', 'G_NAM')))
lap('union')
"""
EXTRA = "import time as time_mod\n"+EXTRA


def big_case(tag):
    nx = DIMS[0]
    return solid_case(tag, "ms", "HEXA8", DIMS, relation="ELAS", press=2e6, lq=True,
                      select=lambda i, j, k: 0 if i < 3 else (1 if i < 69 else 2))


def first(c, mem, ncpus=4, base=None):
    tag = c["tag"]; m = c["m"]
    if not hasattr(m, "pos"):
        bridge_mail(os.path.join(WD8, tag+".mail"), m, free=("S", "S_SK", "CUTA", "CUTB"))
    b = base or tag+"_base"
    r = arun(tag+"_1", c["comm"], mail=tag+".mail", base_out=b, mem=mem, ncpus=ncpus, poll=True)
    print(tag, "first run mem", mem, "ok", r["ok"], r["errors"], "wall %.0f s, base %.0f MB, OS peak %.0f MB, VmPeak %s, opt %s" % (
        r["wall"], base_MB(os.path.join(WD8, b)), r["peak_MB"], r["vmpeak"], r["optimum"]), flush=True)
    return r


def second(c, tag, base, mem, seljson, extra="", only=("V0",), ncpus=2, poll=True):
    r = arun(tag, second_text(c, extra, only), sel=seljson, base_in=base, mem=mem, ncpus=ncpus, poll=poll)
    return r


def verdict(c, r, region=None, label=""):
    """Worst error of V0 against statics; region: file positions -> 0, 1, 2 for another selection."""
    if not r["data"] or "ranks" not in r["data"] or not r["npz"]:
        print(label, "NO RESULT", r["errors"], "rc", r["rc"], "wall %.1f" % r["wall"], "VmPeak", r["vmpeak"], flush=True)
        return None
    a = r["npz"]; q = to_mq(c, a); X = q.X()
    ref, cuts, Pc = solid_ref(c, q, region)
    rows = score(c, r, "V0", ref, cuts, Pc, X)
    if not rows:
        print(label, "no REAC", r["data"].get("v_err"), r["errors"], flush=True)
        return None
    same = all(sorted(i+1 for i in r["data"]["nodeids"][k]) == cuts[k] for k in cuts)
    e = (max(w["eF"] for w in rows), max(w["eM"] for w in rows))
    print(label, "eF %.2e eM %.2e cutnodes match %s wall %.1f s, OS peak %.0f MB, VmPeak %s, opt %s, min %s, tmp %.0f MB, errs %s, alarms %s" % (
        *e, same, r["wall"], r["peak_MB"], r["vmpeak"], r["optimum"], r["minimum"], r["peak_tmp_MB"], r["errors"], r["alarms"]), flush=True)
    return e


def do_big():
    c = big_case("big6")
    bd = os.path.join(WD8, "big6_base")
    if os.path.isdir(bd) and os.listdir(bd):
        bridge_mail(os.path.join(WD8, "big6.mail"), c["m"], free=("S", "S_SK", "CUTA", "CUTB"))
    else:
        first(c, 6000)
    json.dump(selection(c["m"], c["m"].region), open(os.path.join(WD8, "big_sel.json"), "w"))
    print("sel json KB", os.path.getsize(os.path.join(WD8, "big_sel.json"))/1e3)
    r = second(c, "big6_t", "big6_base", 2048, "big_sel.json", extra=EXTRA)
    print("comm KB", os.path.getsize(os.path.join(WD8, "big6_t.comm"))/1e3)
    verdict(c, r, label="timing run")
    if r["data"]:
        print({k: round(v, 3) for k, v in r["data"]["times"].items()}, r["data"].get("n_sel"), r["data"].get("maille_same"))
    return c


def do_mem():
    c = big_case("big6")
    bridge_mail(os.path.join(WD8, "big6.mail"), c["m"], free=("S", "S_SK", "CUTA", "CUTB"))
    d = big_case("big2")
    r = first(d, 2048)
    bm = os.path.join(WD8, "big2_base")
    for base, cc, tag in (("big6_base", c, "first6000"), ("big2_base", d, "first2048")):
        if not os.path.isdir(os.path.join(WD8, base)) or not os.listdir(os.path.join(WD8, base)):
            print(base, "missing"); continue
        for mem in (6000, 2048, 1024, 768, 512, 256):
            if base == "big2_base" and mem not in (2048, 1024):
                continue
            r = second(cc, "m_%s_%d" % (tag, mem), base, mem, "big_sel.json")
            verdict(cc, r, label="%s POURSUITE %d" % (tag, mem))
    rm("big2_base")
    # nonlinear, 12+ steps, follower pressure
    for mem0 in (6000, 2048):
        tag = "nlm%d" % mem0
        e = solid_case(tag, "nl", "HEXA20", (40, 5, 10), defo="GDEF_LOG", press=2e6, follow=True, lmax=7.)
        r = first(e, mem0)
        if not r["ok"]:
            continue
        json.dump(selection(e["m"], e["m"].region), open(os.path.join(WD8, tag+"_sel.json"), "w"))
        for mem in (2048, 1024, 512, 256):
            r = second(e, "%s_%d" % (tag, mem), tag+"_base", mem, tag+"_sel.json")
            verdict(e, r, label="NL first %d POURSUITE %d" % (mem0, mem))
        rm(tag+"_base")


def do_neg():
    """Negative controls for memory: limits low enough that something must give."""
    c = big_case("big6")
    bridge_mail(os.path.join(WD8, "big6.mail"), c["m"], free=("S", "S_SK", "CUTA", "CUTB"))
    for mem in (128, 64, 32):
        r = second(c, "mn_%d" % mem, "big6_base", mem, "big_sel.json")
        verdict(c, r, label="POURSUITE %d" % mem)
    d = big_case("bign")
    r = first(d, 256)
    rm("bign_base")


def do_ro():
    c = big_case("big6")
    bridge_mail(os.path.join(WD8, "big6.mail"), c["m"], free=("S", "S_SK", "CUTA", "CUTB"))
    bd = os.path.join(WD8, "big6_base")
    print("base MB", base_MB(bd), sorted(os.listdir(bd)))
    s0 = base_state(bd)
    # startup cost: no base, empty POURSUITE, plain copy
    t = arun("t_debut", "DEBUT(LANG='EN')\nFIN()\n", mem=2048, ncpus=1)
    print("DEBUT+FIN wall %.2f" % t["wall"], t["ok"])
    t = arun("t_pours", "POURSUITE(LANG='EN')\nFIN()\n", base_in="big6_base", mem=2048, ncpus=1, poll=True)
    print("POURSUITE+FIN wall %.2f tmp %.0f MB" % (t["wall"], t["peak_tmp_MB"]), t["ok"], t["errors"])
    t0 = time.perf_counter(); shutil.copytree(bd, os.path.join(WD8, "copy1")); print("plain copy %.2f s" % (time.perf_counter()-t0))
    r = second(c, "ro_1", "big6_base", 2048, "big_sel.json")
    verdict(c, r, label="read-only")
    s1 = base_state(bd)
    print("base unchanged by D 0 POURSUITE:", s0 == s1)
    # negative control: DR writes back; the same test must then see a change
    cp0 = base_state(os.path.join(WD8, "copy1"))
    r = arun("ro_dr", second_text(c, "", ("V0",)), sel="big_sel.json", base_inout="copy1", mem=2048, ncpus=2)
    cp1 = base_state(os.path.join(WD8, "copy1"))
    print("DR run ok", r["ok"], "base changed:", cp0 != cp1, {f: (cp0.get(f, (0,))[0], cp1.get(f, (0,))[0]) for f in sorted(set(cp0) | set(cp1))})
    # a second follow-up on the rewritten base fails or not: groups already there
    r = arun("ro_dr2", second_text(c, "", ("V0",)), sel="big_sel.json", base_in="copy1", mem=2048, ncpus=2)
    print("repeat on written base ok", r["ok"], r["errors"][:2], r["alarms"], "data", bool(r["data"] and "ranks" in r["data"]))
    rm("copy1")


def do_par():
    c = big_case("big6")
    m = c["m"]
    bridge_mail(os.path.join(WD8, "big6.mail"), m, free=("S", "S_SK", "CUTA", "CUTB"))
    bd = os.path.join(WD8, "big6_base")
    s0 = base_state(bd)
    X = m.X()
    reg2 = {}
    for e in m.region:
        x = X[np.array(m.cells[e-1][1])-1, 0].mean()
        reg2[e] = 0 if x < .05 else (1 if x < .15 else 2)
    json.dump(selection(m, reg2), open(os.path.join(WD8, "big_sel2.json"), "w"))
    txt = second_text(c, "", ("V0",))
    with cf.ThreadPoolExecutor(2) as ex:
        f1 = ex.submit(arun, "p_1", txt, sel="big_sel.json", base_in="big6_base", mem=2048, ncpus=2, poll=True)
        f2 = ex.submit(arun, "p_2", txt, sel="big_sel2.json", base_in="big6_base", mem=2048, ncpus=2, poll=True)
        r1, r2 = f1.result(), f2.result()
    ov = min(r1["end"], r2["end"])-max(r1["start"], r2["start"])
    print("walls %.1f %.1f overlap %.1f s" % (r1["wall"], r2["wall"], ov))
    print("calc window", (r1["data"] or {}).get("times"), (r2["data"] or {}).get("times"))
    verdict(c, r1, label="parallel sel 1")
    verdict(c, r2, region={m.pos[e]: v for e, v in reg2.items()}, label="parallel sel 2")
    # negative control: selection 2 judged with the statics of selection 1 must fail
    verdict(c, r2, label="NEG sel 2 against statics of sel 1")
    print("base unchanged:", base_state(bd) == s0)


def do_fail():
    """First run stops at a step without convergence: what reaches the base?"""
    c = solid_case("fa", "nl", "HEXA20", (10, 2, 4), press=None, lmax=20.)
    c["comm"] = c["comm"].replace("ECHEC=_F(ACTION='DECOUPE', SUBD_NIVEAU=4, SUBD_PAS=4)", "ECHEC=_F(ACTION='ARRET')").replace(
        "ITER_GLOB_MAXI=30", "ITER_GLOB_MAXI=4").replace("D_SIGM_EPSI=2000000000.0", "D_SIGM_EPSI=2.0e5")
    r = first(c, 2048, 2)
    bd = os.path.join(WD8, "fa_base")
    print("first ok", r["ok"], "rc", r["rc"], r["errors"], "base files", os.listdir(bd), "MB", base_MB(bd))
    json.dump(selection(c["m"], c["m"].region), open(os.path.join(WD8, "fa_sel.json"), "w"))
    probe = "POURSUITE(LANG='EN')\n"+HELP8+r"""
OUT['names'] = [n for n in ('mesh', 'model', 'res', 'load_1') if n in globals()]
if 'res' in globals():
    OUT['ranks'] = list(res.getIndexes())
    OUT['inst'] = list(res.getAccessParameters()['INST'])
finish()
FIN()
"""
    r2 = arun("fa_2", probe, sel="fa_sel.json", base_in="fa_base", mem=2048, ncpus=1)
    print("POURSUITE on it: ok", r2["ok"], r2["errors"], r2["data"], "rc", r2["rc"])
    mess = open(os.path.join(WD8, "fa_1.mess"), encoding="utf-8", errors="replace").read()
    print("markers", re.findall(r"<ConvergenceError> <\w+>|DIAGNOSTIC JOB : \S+|EXIT_\d+=\d", mess))
    r3 = second(c, "fa_3", "fa_base", 2048, "fa_sel.json", only=("V0", "V1"), ncpus=1)
    verdict(c, r3, label="cut forces on the converged steps")
    if r3["data"] and "ranks" in r3["data"]:
        print("ranks", r3["data"]["ranks"], r3["data"]["inst"])
    rm("fa_base")


def do_path():
    """Absolute path of the base, and a folder with a space, on a small model."""
    c = solid_case("pa", "ms", "HEXA20", (10, 2, 4), relation="ELAS")
    first(c, 2048, 2)
    json.dump(selection(c["m"], c["m"].region), open(os.path.join(WD8, "pa_sel.json"), "w"))
    shutil.copytree(os.path.join(WD8, "pa_base"), os.path.join(WD8, "pa base"))
    txt = second_text(c, "", ("V0",))
    r = arun("pa_abs", txt, sel="pa_sel.json", base_in=os.path.join(WD8, "pa_base"), mem=2048, ncpus=1)
    verdict(c, r, label="absolute path")
    r = arun("pa_sp", txt, sel="pa_sel.json", base_in=os.path.join(WD8, "pa base"), mem=2048, ncpus=1)
    verdict(c, r, label="path with a space")
    r = arun("pa_sq", txt, sel="pa_sel.json", base_in='"%s"' % os.path.join(WD8, "pa base"), mem=2048, ncpus=1)
    verdict(c, r, label="quoted path with a space")
    rm("pa_base", "pa base")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        dict(big=do_big, neg=do_neg, ro=do_ro, par=do_par, mem=do_mem, fail=do_fail, path=do_path)[a]()
