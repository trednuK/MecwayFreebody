# E7: the routes A (in the first run), B (second run from .rmed), C (POURSUITE) on one case.
# A case is a dict: tag, mesh, setup (text: mesh, model, material, loads), excit (text),
# solve (text), kind ('elas' or 'noli'), fields for the rmed, ranks, ref(rank, u) -> exact cuts.
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e7_lib import *

POST = r'''
def post(route, R, excit, ranks, cuts, extra=None):
    """FORC_NODA and REAC_NODA on the selection, nodal arrays and POST_RELEVE_T per cut."""
    lap(route+"_before")
    acc = R.getAccessParameters()
    inst = dict(zip(acc["NUME_ORDRE"], acc["INST"]))
    if ranks is None:
        ranks = [k for k in R.getIndexes() if k > 0]
    OUT["ranks"] = ranks
    OUT["inst"] = {str(k): inst.get(k, 0.) for k in ranks}
    rf = CALC_CHAMP(RESULTAT=R, GROUP_MA="S", FORCE="FORC_NODA", NUME_ORDRE=ranks)
    lap(route+"_forc")
    variants = {"FORC": (rf, "FORC_NODA")}
    if not globals().get("SKIP_S"):     # a follower load cannot be evaluated without its skin cells
        rr = CALC_CHAMP(RESULTAT=R, GROUP_MA="S", FORCE="REAC_NODA", EXCIT=excit, NUME_ORDRE=ranks)
        lap(route+"_reac")
        variants["REAC"] = (rr, "REAC_NODA")
    if mesh.hasGroupOfCells("S_SK"):
        rs = CALC_CHAMP(RESULTAT=R, GROUP_MA="S_SK", FORCE="REAC_NODA", EXCIT=excit, NUME_ORDRE=ranks)
        variants["REACSK"] = (rs, "REAC_NODA")
    for v, (r, c) in variants.items():
        for k in ranks:
            ARR["%s_%s_%d" % (route, v, k)] = node_array(r.getField(c, k), mesh)
            for cut, P in cuts.items():
                OUT["tab"]["%s_%s_%d_%s" % (route, v, k, cut)] = tab_cut(r, c, cut, P, False, k)
    for k in ranks:
        ARR["%s_U_%d" % (route, k)] = node_array(R.getField("DEPL", k), mesh)
    lap(route+"_tables")
'''


PLAST = r'''
def plast_info(R, sel):
    """Largest V1 (cumulated plastic strain) per stored step: all cells, and the cells of S that
    touch cut A, to show that the cut runs through the plastic zone."""
    con = mesh.getConnectivity()
    d = 1-min(min(c) for c in con)
    ca = set(sel["no"]["CUTA"])
    near = [c-1 for c in sel["ma"]["S"] if ca & set(q+d for q in con[c-1])]
    out = {}
    for k in R.getIndexes():
        if k == 0:
            continue
        val, desc = R.getField("VARI_ELGA", k).getValuesWithDescription("V1")
        v1 = np.array(val); cell = np.array(desc[0])+1
        nearset = np.isin(cell-1, near)
        out[str(k)] = [float(v1.max()), float(v1[nearset].max()) if nearset.any() else 0.,
                       len(set(cell[v1 > 0].tolist()))]
    OUT["plast"] = out
'''


def impr_fields(c):
    return "(" + ",".join("'%s'" % f for f in c["fields"]) + ",)"


def comm_first(c, route, rmed=False):
    """First run: solve; route A also posts in the same run."""
    t = ["DEBUT(LANG='EN')", HELP, POST, PLAST, c["setup"], "lap('setup')", "EXC = " + c["excit"],
         c["solve"], "lap('solve')"]
    if route == "A":
        t += ["sel = set_groups(mesh)", "post('A', res, EXC, %r, sel['cuts'])" % (c["ranks"],)]
        if c.get("post_extra"):
            t += [c["post_extra"]]
        if c["kind"] == "noli" and c.get("plast", True):
            t += ["plast_info(res, sel)"]
    if rmed:
        t += ["IMPR_RESU(FORMAT='MED', UNITE=80, RESU=_F(RESULTAT=res%s, NOM_CHAM=%s))"
              % (c.get("cara_impr", ""), impr_fields(c)), "lap('impr')"]
    t += ["finish()", "FIN()"]
    return "\n".join(t)+"\n"


def comm_reread(c, route, fields, mesh_from="mail"):
    """Route B: same setup, no solve, LIRE_RESU."""
    su = c["setup"]
    if mesh_from == "rmed":
        su = c.get("setup_rmed") or su.replace("mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')",
                                               "mesh = LIRE_MAILLAGE(UNITE=81, FORMAT='MED')")
    fm = ",".join("_F(NOM_CHAM='%s', NOM_RESU='res')" % f for f in fields)
    typ = "EVOL_ELAS" if c["kind"] == "elas" else "EVOL_NOLI"
    extra = c.get("lire_kw", "") if c["kind"] == "elas" else c.get("lire_kw", "")+c["comp_kw"]
    t = ["DEBUT(LANG='EN')", HELP, POST, su, c.get("lire_pre", ""), "lap('setup')", "EXC = " + c["excit"],
         "res = LIRE_RESU(TYPE_RESU='%s', FORMAT='MED', UNITE=81, MODELE=model, CHAM_MATER=cm,%s "
         "TOUT_ORDRE='OUI', EXCIT=EXC, FORMAT_MED=(%s,))" % (typ, extra, fm),
         "lap('lire')", "sel = set_groups(mesh, %r)" % (mesh_from == "rmed"),
         "post('%s', res, EXC, %r, sel['cuts'])" % (route, c["ranks"]), "finish()", "FIN()"]
    return "\n".join(t)+"\n"


def comm_pours(c):
    t = ["POURSUITE(LANG='EN')", HELP, POST, "EXC = " + c["excit"], "lap('pours')",
         "sel = set_groups(mesh)", "post('C', res, EXC, %r, sel['cuts'])" % (c["ranks"],),
         "finish()", "FIN()"]
    return "\n".join(t)+"\n"


def select_file(tag, m, cuts):
    p = os.path.join(WD, tag+"_sel.json")
    ma = {"S": m.ma["S"]}
    if "S_SK" in m.ma:
        ma["S_SK"] = m.ma["S_SK"]
    conn = {str(i): m.cells[i-1][1] for ids in ma.values() for i in ids}
    json.dump(dict(ma=ma, no={"CUTA": m.no["CUTA"], "CUTB": m.no["CUTB"]}, cuts=cuts, conn=conn, nn0=len(m.xyz)), open(p, "w"))
    return tag+"_sel.json"


def compare(c, route, r, ranks, rows, variants=("FORC", "REAC", "REACSK")):
    """All variants of a run against the statics."""
    m = c["mesh"]; X = m.X(); data = r["data"]; arr = r["npz"]
    ranks = data["ranks"]
    for k in ranks:
        u = arr["%s_U_%d" % (route, k)][:len(X)]    # QUAD9, TRIA7: the added nodes carry no cut force
        lg = c.get("large")
        xcur = X+u[:, :3] if lg else X
        Pc = c["cuts"]
        ref = c["ref"](data["inst"][str(k)] if c["kind"] == "noli" else k, u)
        for v in variants:
            key = "%s_%s_%d" % (route, v, k)
            if key not in arr:
                continue
            a = arr[key][:len(X)]
            # what is left on the nodes of S outside the cuts: must be nil if nothing else acts
            inner = np.zeros(len(a), bool)        # REAC_NODA also shows nodal loads outside S
            inner[np.array(sorted({n for e in m.ma["S"] for n in m.cells[e-1][1]}))-1] = True
            inner[np.array(m.no["CUTA"]+m.no["CUTB"])-1] = False
            big = max(np.linalg.norm(a[~inner, :3], axis=1).max(), 1e-30)
            rout = float(np.linalg.norm(a[inner, :3], axis=1).max()/big)
            for cut, ids in (("CUTA", m.no["CUTA"]), ("CUTB", m.no["CUTB"])):
                i = np.array(ids)-1
                P = np.array(Pc[cut])
                F, M = sum_about(a[i, :3], xcur[i], P, a[i, 3:6])
                Fx, Mx = ref[cut]
                e = errors(F, M, Fx, Mx, c.get("Lref", L))
                tb = data["tab"]["%s_%s" % (key, cut)]
                Ft = np.array([tb.get("RESULT_X", 0.), tb.get("RESULT_Y", 0.), tb.get("RESULT_Z", 0.)])
                Mt = np.array([tb.get("MOMENT_X", 0.), tb.get("MOMENT_Y", 0.), tb.get("MOMENT_Z", 0.)])
                et = errors(Ft, Mt, Fx, Mx, c.get("Lref", L))
                rows.append(dict(case=c["tag"], route=route, var=v, rank=int(k), cut=cut, rout=rout,
                                 F=F.tolist(), M=M.tolist(), Fx=np.asarray(Fx).tolist(),
                                 Mx=np.asarray(Mx).tolist(), Ft=Ft.tolist(), Mt=Mt.tolist(), **e,
                                 tabF=et["eF"], tabM=et["eM"]))
    return rows


def show(rows, hdr=""):
    if hdr:
        print(hdr)
    for q in rows:
        print("  %-22s %-4s %-7s k=%-3d %s eF=%.2e eM=%.2e rawF=%.2e rawM=%.2e | tab %.2e %.2e"
              % (q["case"], q["route"], q["var"], q["rank"], q["cut"], q["eF"], q["eM"], q["rawF"], q["rawM"],
                 q["tabF"], q["tabM"]))
    sys.stdout.flush()


def run_routes(c, routes=("A", "B", "B0", "Bm", "C"), fields_b=None, keep=False):
    tag = c["tag"]; m = c["mesh"]; rows = []; info = {"case": tag, "cells": len(m.region)}
    os.makedirs(WD, exist_ok=True)
    mail = tag+".mail"
    m.free_ma = ("S", "S_SK"); m.free_no = ("CUTA", "CUTB")
    write_mail(os.path.join(WD, mail), m)
    sel = select_file(tag, m, c["cuts"])
    ranks = c["ranks"]
    if "A" in routes:
        r = run_aster(tag+"_A", comm_first(c, "A"), mail=mail, sel=sel)
        info["A"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"],
                         plast=(r["data"] or {}).get("plast"))
        if r["data"]:
            compare(c, "A", r, ranks, rows)
        else:
            print("A failed", r["errors"], r["rc"])
    need_p = set(routes) & {"P", "B", "B0", "Bm", "C"}
    if need_p:
        base = tag+"_base"
        r = run_aster(tag+"_P", comm_first(c, "P", rmed=True), mail=mail, rmed_out=True,
                      base=base if "C" in routes else None)
        info["P"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"])
        pm = os.path.join(WD, tag+"_P.rmed")
        info["rmed_MB"] = os.path.getsize(pm)/1e6 if os.path.exists(pm) else None
        if "C" in routes:
            bd = os.path.join(WD, base)
            info["base_MB"] = sum(os.path.getsize(os.path.join(bd, f)) for f in os.listdir(bd))/1e6
    if "B" in routes:
        f = fields_b or c["fields"]
        r = run_aster(tag+"_B", comm_reread(c, "B", f), mail=mail, med_in=tag+"_P.rmed", sel=sel)
        info["B"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"])
        if r["data"]:
            compare(c, "B", r, ranks, rows)
        else:
            print("B failed", r["errors"], r["rc"])
    if "B0" in routes:      # displacement only: linear results are rebuilt from it
        r = run_aster(tag+"_B0", comm_reread(c, "B0", ["DEPL"]), mail=mail, med_in=tag+"_P.rmed", sel=sel)
        info["B0"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"])
        if r["data"]:
            compare(c, "B0", r, ranks, rows)
        else:
            print("B0 failed", r["errors"], r["rc"])
    if "Bm" in routes:
        f = fields_b or c["fields"]
        r = run_aster(tag+"_Bm", comm_reread(c, "Bm", f, mesh_from="rmed"), med_in=tag+"_P.rmed", sel=sel)
        info["Bm"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"])
        if r["data"]:
            compare(c, "Bm", r, ranks, rows)
        else:
            print("Bm failed", r["errors"], r["rc"])
    if "C" in routes:
        r = run_aster(tag+"_C", comm_pours(c), base_in=tag+"_base", sel=sel)
        info["C"] = dict(wall=r["wall"], times=(r["data"] or {}).get("times"), err=r["errors"])
        if r["data"]:
            compare(c, "C", r, ranks, rows)
        else:
            print("C failed", r["errors"], r["rc"])
    return rows, info


SOLID = r'''
mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', PHENOMENE='MECANIQUE', MODELISATION='3D'))
mat = DEFI_MATERIAU(ELAS=_F(E=%(E)r, NU=%(NU)r, RHO=%(RHO)r))
cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat))
bc = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_MA='ROOT', DX=0., DY=0., DZ=0.))
tip = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=_F(GROUP_MA='TIPALL', FX=%(tx)r, FY=%(ty)r, FZ=%(tz)r))
top = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=_F(GROUP_MA='TIPTOP', FX=%(ax)r, FY=%(ay)r, FZ=%(az)r))
grav = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=9.81, DIRECTION=(0., 0., -1.)))
'''
EX4 = "(_F(CHARGE=bc), _F(CHARGE=tip), _F(CHARGE=top), _F(CHARGE=grav))"


def cut_points(m):
    X = m.X()
    return {c: X[np.array(m.no[c])-1].mean(axis=0).tolist() for c in ("CUTA", "CUTB")}


def block_case(tag, shape, dims, distort=0.):
    m = block(shape, dims, distort)
    skin(m, "ROOT", lambda c: abs(c[0]) < 1e-9)
    skin(m, "TIPALL", lambda c: abs(c[0]-L) < 1e-9)
    skin(m, "TIPTOP", lambda c: abs(c[0]-L) < 1e-9 and c[2] > H/2)
    groups_from_regions(m)
    AT, AU = surf_area(m, m.ma["TIPALL"]), surf_area(m, m.ma["TIPTOP"])
    tr = TIPF/AT; ar = TOPF/AU
    su = SOLID % dict(E=E0, NU=NU, RHO=RHO, tx=tr[0], ty=tr[1], tz=tr[2], ax=ar[0], ay=ar[1], az=ar[2])
    regs = {r: nodal_gravity(m, cells=[c for c, q in m.region.items() if q == r]) for r in (0, 1, 2)}
    regs[2] = regs[2]+nodal_surface(m, m.ma["TIPALL"], trac=tr)+nodal_surface(m, m.ma["TIPTOP"], trac=ar)
    cuts = cut_points(m)
    return dict(tag=tag, mesh=m, setup=su, excit=EX4, kind="elas", fields=["DEPL", "SIEF_ELGA"],
                solve="res = MECA_STATIQUE(MODELE=model, CHAM_MATER=cm, EXCIT=EXC, "
                      "SOLVEUR=_F(METHODE='MUMPS', RENUM='METIS'))",
                ranks=[1], cuts=cuts, ref=lambda k, u, X=m.X(): ref_cuts(regs, X, {a: np.array(b) for a, b in cuts.items()}),
                regs=regs)


