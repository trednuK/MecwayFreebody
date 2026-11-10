# E7: run time and file sizes of the routes on hex20 blocks of about 2000 and 20000 elements,
# linear and nonlinear. Run alone on the machine. Run: python e7_scale.py [filter]
import e7_lib
from e7_routed import *

BRIDGE = ["DEPL", "REAC_NODA", "SIGM_ELNO", "SIGM_NOEU", "SIEQ_NOEU"]
SIZES = {"2k": (40, 5, 10), "20k": (72, 12, 24)}


def sizes(tag):
    d = os.path.join(WD, tag+"_base")
    return dict(rmed_MB=os.path.getsize(os.path.join(WD, tag+"_P.rmed"))/1e6,
                base_MB=sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))/1e6)


def linear(name, dims):
    tag = "z_"+name
    c = block_case(tag, "HEXA20", dims)
    t0 = time.perf_counter()
    rows, info = run_routes(c, routes=("A", "B", "B0", "C"))
    out = dict(case=tag, cells=len(c["mesh"].region), nodes=len(c["mesh"].xyz), info=info)
    out.update(sizes(tag))
    w = {k: max((r["eF"], r["eM"]) for r in rows if r["route"] == k and r["var"] == "REAC") for k in ("A", "B", "B0", "C")}
    out["worst"] = w
    # the fields the bridge writes with med_export on
    cq = dict(c); cq["tag"] = tag+"Q"; cq["fields"] = BRIDGE
    cq["solve"] = c["solve"]+chr(10)+("res = CALC_CHAMP(reuse=res, RESULTAT=res, FORCE=('REAC_NODA',), "
                                      "CONTRAINTE=('SIGM_ELNO', 'SIGM_NOEU'), CRITERES=('SIEQ_ELNO', 'SIEQ_NOEU'))")
    r = run_aster(tag+"Q_P", comm_first(cq, "P", rmed=True), mail=tag+".mail", rmed_out=True)
    out["bridge_rmed_MB"] = os.path.getsize(os.path.join(WD, tag+"Q_P.rmed"))/1e6
    out["bridge_err"] = r["errors"]
    cq2 = dict(c); cq2["tag"] = tag+"Q"
    r = run_aster(tag+"Q_B", comm_reread(cq2, "B", ["DEPL"]), mail=tag+".mail", med_in=tag+"Q_P.rmed", sel=tag+"_sel.json")
    if r["data"]:
        rr = []; compare(cq2, "B", r, [1], rr)
        out["bridge_B"] = dict(wall=r["wall"], worst=max((q["eF"], q["eM"]) for q in rr if q["var"] == "REAC"))
    else:
        out["bridge_B"] = dict(err=r["errors"])
    # route D
    r = run_aster(tag+"_D", comm_d(c, ["bc", "tip", "top", "grav"]), mail=tag+".mail")
    out["D"] = dict(wall=r["wall"], err=r["errors"], times=(r["data"] or {}).get("times"),
                    MB=os.path.getsize(os.path.join(WD, tag+"_D.npz"))/1e6)
    if r["data"]:
        rr, ts = d_sum(c, r)
        out["D"].update(py=ts, worst=max((q["eF"], q["eM"]) for q in rr), values=r["data"]["dump_values"], load=r["data"]["dump_loads"])
    print(json.dumps(out, indent=0, default=float)[:3000], flush=True)
    return out


def nonlinear(name, dims, steps):
    tag = "y_"+name
    c = nl_block(tag, "HEXA20", dims)
    c["setup"] = c["setup"].replace("_F(JUSQU_A=1., NOMBRE=8), _F(JUSQU_A=2., NOMBRE=4)", "_F(JUSQU_A=1., NOMBRE=%d)," % steps)
    big = name == "20k"       # one solve only: A costs the same solve, D the same plus a dump
    rows, info = run_routes(c, routes=("B", "C") if big else ("A", "B", "C"))
    out = dict(case=tag, cells=len(c["mesh"].region), nodes=len(c["mesh"].xyz), info=info, steps=steps)
    out.update(sizes(tag))
    if rows:
        out["worst"] = {k: max((r["eF"], r["eM"]) for r in rows if r["route"] == k and r["var"] == "REAC")
                        for k in ("A", "B", "C") if any(r["route"] == k for r in rows)}
    if big:
        print(json.dumps(out, indent=0, default=float)[:3000], flush=True)
        return out
    r = run_aster(tag+"_D", comm_d(c, ["bc", "grav"], False, True), mail=tag+".mail")
    out["D"] = dict(wall=r["wall"], err=r["errors"], times=(r["data"] or {}).get("times"),
                    MB=os.path.getsize(os.path.join(WD, tag+"_D.npz"))/1e6)
    if r["data"]:
        rr, ts = d_sum(c, r)
        out["D"].update(py=ts, worst=max((q["eF"], q["eM"]) for q in rr))
    print(json.dumps(out, indent=0, default=float)[:3000], flush=True)
    return out


if __name__ == "__main__":
    flt = sys.argv[1:]
    res = []
    for n, d in SIZES.items():
        if not flt or "l"+n in flt:
            res.append(linear(n, d))
            json.dump(res, open(os.path.join(WD, "res_scale.json"), "w"), default=float)
    for n, d, s in (("2k", SIZES["2k"], 8), ("20k", SIZES["20k"], 3)):
        if not flt or "n"+n in flt:
            res.append(nonlinear(n, d, s))
            json.dump(res, open(os.path.join(WD, "res_scale_%s.json" % n), "w"), default=float)
