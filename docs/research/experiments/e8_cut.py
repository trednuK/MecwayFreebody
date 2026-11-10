# E8 probe 2: CALC_CHAMP FORCE='REAC_NODA' with GROUP_MA in a POURSUITE, with and without EXCIT, against
# exact statics on two cuts at every stored step. First run in bridge style: load_1..n, FONC_MULT,
# TYPE_CHARGE='SUIV', mesh replaced by CREA_MAILLAGE, a full REAC_NODA already in `res`. The selection
# comes from a JSON with file positions. The reference is built on the mesh read back from Aster, so
# a mesh turned quadratic gets its own quadrature and its own cut nodes.
# Run: python e8_cut.py [filter]
import concurrent.futures as cf
from e8_lib import *
from e7_nl import NLCOMMON, lam, SY, ET, LMAX, nl_shell
from e7_routes import SOLID
from e7_struct import T, GOBL

FIRST = r"""DEBUT(LANG='EN')
def _bridge_helper(mesh):
    return mesh.getNumberOfNodes()
mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')
mesh = DEFI_GROUP(reuse=mesh, MAILLAGE=mesh, CREA_GROUP_MA=_F(NOM='all_elems', TOUT='OUI'),
                  CREA_GROUP_NO=_F(NOM='all_nodes', GROUP_MA='all_elems'))
%(meshops)s
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', PHENOMENE='MECANIQUE', MODELISATION='3D'))
%(mat)s
%(loads)s
EXC = %(excit)s
%(solve)s
%(post)s
FIN()
"""

SECOND = "POURSUITE(LANG='EN')\n" + HELP8 + r"""
lap('start')
sel = json.load(open('fort.32'))
lap('json')
M = res.getMesh()
OUT['mesh'] = dict(py_nodes=mesh.getNumberOfNodes(), res_nodes=M.getNumberOfNodes(),
                   model_nodes=res.getModel().getMesh().getNumberOfNodes(), py_name=mesh.getName(), res_name=M.getName())
for n, ids in sel['ma'].items():
    M.setGroupOfCells(n, [i-1 for i in ids])
lap('groups')
@EXTRA@
M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_NO=(
    _F(NOM='NS', GROUP_MA='F_S'), _F(NOM='NL', GROUP_MA='F_L'), _F(NOM='NR', GROUP_MA='F_R'),
    _F(NOM='CUTA', INTERSEC=('NS', 'NL')), _F(NOM='CUTB', INTERSEC=('NS', 'NR'))))
lap('cutnodes')
acc = res.getAccessParameters()
inst = dict(zip(acc['NUME_ORDRE'], acc['INST']))
ranks = [k for k in res.getIndexes() if k > 0]
OUT['ranks'] = ranks
OUT['inst'] = {str(k): inst[k] for k in ranks}
OUT['nodeids'] = {c: [int(i) for i in M.getNodes(c)] for c in ('CUTA', 'CUTB')}
dump_mesh(M)
OUT['has_loads'] = [bool(res.hasListOfLoads(k)) for k in ranks]
try:
    OUT['loads'] = {str(k): stored_loads(res, k) for k in (ranks[0], ranks[-1])}
except Exception as e:
    OUT['loads'] = 'ERR '+str(e)[:200]
OUT['fields'] = sorted(res.getFieldsNames())
OUT['load_ids'] = {n: globals()[n].getName() for n in ('load_1', 'load_2', 'load_3', 'load_4', 'load_5', 'bc', 'tip', 'grav', 'prs') if n in globals()}
stored = 'REAC_NODA' in OUT['fields']
for k in ranks:
    ARR['U_%d' % k] = node_array(res.getField('DEPL', k), M)
    if stored:
        ARR['STORED_%d' % k] = node_array(res.getField('REAC_NODA', k), M)
lap('dump')
OUT['v_err'] = {}
@EXCS@
for v, gm, exc in VARS:
    kw = {} if exc is None else {'EXCIT': exc}
    try:
        r = CALC_CHAMP(RESULTAT=res, GROUP_MA=gm, FORCE='REAC_NODA', **kw)
        for k in ranks:
            ARR['%s_%d' % (v, k)] = node_array(r.getField('REAC_NODA', k), M)
    except Exception as e:
        OUT['v_err'][v] = str(e)[-400:]
    lap('v_'+v)
finish()
FIN()
"""

MS_SOLVE = "res = MECA_STATIQUE(MODELE=model, CHAM_MATER=cm, EXCIT=EXC, SOLVEUR=_F(METHODE='MUMPS', RENUM='METIS')%s)"
PRE = "res = CALC_CHAMP(reuse=res, RESULTAT=res, CONTRAINTE=('SIGM_ELNO',), CRITERES=('SIEQ_ELNO',), FORCE=('REAC_NODA',))"


def excit_text(items, drop_fm=None, drop=None, drop_suiv=False):
    t = []
    for name, fm, suiv in items:
        if name == drop:
            continue
        s = "_F(CHARGE=%s" % name
        if fm and name != drop_fm:
            s += ", FONC_MULT=%s" % fm
        if suiv and not drop_suiv:
            s += ", TYPE_CHARGE='SUIV'"
        t.append(s+")")
    return "("+", ".join(t)+")"


def solid_case(tag, mode="nl", shape="HEXA20", dims=(20, 4, 8), defo="PETIT", relation="VMIS_ISOT_LINE", press=None,
               follow=False, lq=False, charf=False, arch=False, prereac=True, lmax=LMAX, varc=False, rigid=False, select=None):
    nx, ny, nz = dims
    if mode == "nl":
        sel = lambda i, j, k: 0 if i < nx//10 else (1 if i < nx//2 else 2)
    else:
        sel = None
    m = block(shape, dims, 0., select=select or sel)
    skin(m, "ROOT", lambda c: abs(c[0]) < 1e-9)
    skin(m, "TIPALL", lambda c: abs(c[0]-L) < 1e-9)
    skin(m, "TIPTOP", lambda c: abs(c[0]-L) < 1e-9 and c[2] > H/2)
    if press:
        skin(m, "PR", lambda c: abs(c[2]-H) < 1e-9)
    if varc:
        m.ma["HOT"] = [c for c in m.region if m.X()[np.array(m.cells[c-1][1])-1, 2].mean() > H/2]
    groups_from_regions(m)
    tr = TIPF/surf_area(m, m.ma["TIPALL"]); ar = TOPF/surf_area(m, m.ma["TIPTOP"])
    meshops = []
    if lq:
        meshops.append("_n_lin = mesh.getNumberOfNodes()\nmesh = CREA_MAILLAGE(MAILLAGE=mesh, LINE_QUAD=_F(TOUT='OUI'))")
    if press:
        meshops.append("mesh = MODI_MAILLAGE(reuse=mesh, MAILLAGE=mesh, ORIE_PEAU=_F(GROUP_MA_PEAU=('PR',)))")
    ecro = ", ECRO_LINE=_F(D_SIGM_EPSI=%r, SY=%r)" % (ET, SY) if relation.startswith("VMIS") else ""
    alpha = ", ALPHA=1.2e-5" if varc else ""
    mat = "mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r%s)%s)\n" % (E0, NU, RHO, alpha, ecro)
    if varc:
        mat += ("tfld = CREA_CHAMP(TYPE_CHAM='NOEU_TEMP_R', OPERATION='AFFE', MAILLAGE=mesh, AFFE=(\n"
                "  _F(TOUT='OUI', NOM_CMP='TEMP', VALE=20.), _F(GROUP_MA='HOT', NOM_CMP='TEMP', VALE=120.)))\n"
                "cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat),\n"
                "  AFFE_VARC=_F(TOUT='OUI', NOM_VARC='TEMP', CHAM_GD=tfld, VALE_REF=20.))\n")
    else:
        mat += "cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat))\n"
    bc = "DDL_IMPO=_F(GROUP_MA='ROOT', DX=0., DY=0., DZ=0.)"
    if rigid:
        bc += ", LIAISON_SOLIDE=_F(GROUP_MA='TIPALL')"
    ld = ["load_1 = AFFE_CHAR_MECA(MODELE=model, %s)" % bc]
    loads = [("load_1", None, False)]
    fac = None
    if mode == "nl":
        ld.insert(0, NLCOMMON % dict(lm=lmax, le=lmax*.25))
        ld.insert(1, "rampe2 = CALC_FONCTION(COMB=_F(FONCTION=rampe, COEF=.4))\n"
                     "rampg = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., 0., 1., 1., 2., 1.), PROL_DROITE='CONSTANT')")
        fac = lambda t: (lam(t, lmax), .4*lam(t, lmax), min(t, 1.), lam(t, lmax))
        fm = ("rampe", "rampe2", "rampg", "rampe")
    elif mode == "ms":
        ld.insert(0, "f06 = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., .6, 1., .6), PROL_DROITE='CONSTANT')")
        fac = lambda t: (.6, 1., 1., .6)
        fm = ("f06", None, None, "f06")
    else:
        ld.insert(0, "rampe = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., 0., 1., 1.), PROL_DROITE='CONSTANT')\n"
                     "lis3 = DEFI_LIST_REEL(VALE=(.25, .5, 1.))")
        fac = lambda t: (t, 1., 1., t)
        fm = ("rampe", None, None, "rampe")
    if charf:
        v = [lam(0, lmax), lam(1, lmax), lam(2, lmax)]
        for nm, q, s in (("ftx", tr[0], 1), ("fty", tr[1], 1), ("ftz", tr[2], 1), ("fpr", press, 1)):
            ld.append("%s = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., %r, 1., %r, 2., %r), PROL_DROITE='CONSTANT')"
                      % (nm, v[0]*q, v[1]*q, v[2]*q))
        ld.append("load_2 = AFFE_CHAR_MECA_F(MODELE=model, FORCE_FACE=_F(GROUP_MA='TIPALL', FX=ftx, FY=fty, FZ=ftz))")
        fm = (None,)+fm[1:3]+(None,)
    else:
        ld.append("load_2 = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=_F(GROUP_MA='TIPALL', FX=%r, FY=%r, FZ=%r))" % tuple(tr))
    ld.append("load_3 = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=_F(GROUP_MA='TIPTOP', FX=%r, FY=%r, FZ=%r))" % tuple(ar))
    ld.append("load_4 = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=9.81, DIRECTION=(0., 0., -1.)))")
    loads += [("load_2", fm[0], False), ("load_3", fm[1], False), ("load_4", fm[2], False)]
    if press:
        if charf:
            ld.append("load_5 = AFFE_CHAR_MECA_F(MODELE=model, PRES_REP=_F(GROUP_MA='PR', PRES=fpr))")
        else:
            ld.append("load_5 = AFFE_CHAR_MECA(MODELE=model, PRES_REP=_F(GROUP_MA='PR', PRES=%r))" % press)
        loads.append(("load_5", fm[3], follow))
    if mode == "nl":
        comp = "COMPORTEMENT=_F(RELATION='%s', DEFORMATION='%s')," % (relation, defo)
        ar_ = ""
        if arch:
            ld.append("outlist = DEFI_LIST_REEL(VALE=(.25, .625, 1., 1.5, 2.))")
            ar_ = " ARCHIVAGE=_F(LIST_INST=outlist),"
        solve = ("res = STAT_NON_LINE(MODELE=model, CHAM_MATER=cm, EXCIT=EXC, %s INCREMENT=_F(LIST_INST=inst),%s "
                 "NEWTON=_F(REAC_ITER=1, PREDICTION='ELASTIQUE'), CONVERGENCE=_F(RESI_GLOB_RELA=1e-8, ITER_GLOB_MAXI=30), "
                 "SOLVEUR=_F(METHODE='MUMPS'))" % (comp, ar_))
    elif mode == "ms":
        solve = MS_SOLVE % ""
    else:
        solve = MS_SOLVE % ", LIST_INST=lis3"
    # only loads on the selection enter REAC_NODA, so the wrong setups must touch those: gravity, pressure
    wrong_fm = next((n for n, f, s in reversed(loads) if f and n in ("load_4", "load_5")), None)
    ex = dict(V0=("F_SK", None), V1=("F_SK", excit_text(loads)), N_miss=("F_SK", excit_text(loads, drop="load_4")),
              N_noskin=("F_S", None))
    if wrong_fm:
        ex["N_nofm"] = ("F_SK", excit_text(loads, drop_fm=wrong_fm))
    if follow:
        ex["N_nosuiv"] = ("F_SK", excit_text(loads, drop_suiv=True))
    comm = FIRST % dict(meshops="\n".join(meshops), mat=mat, loads="\n".join(ld), excit=excit_text(loads), solve=solve,
                        post=PRE if prereac else "")
    return dict(tag=tag, m=m, comm=comm, ex=ex, lq=lq, tr=tr, ar=ar, press=press, follow=follow, large=defo != "PETIT",
                fac=fac, mode=mode, loads=loads)


def shell_case(tag, press=None, typ="QUAD8", model="COQUE_3D", defo="GROT_GDEP", relation="ELAS", lmax=20.):
    """Shell strip; COQUE_3D after the bridge's MODI_MAILLE; statics of e7_nl.nl_shell, plus a
    follower pressure on the deformed mid-surface (the centre node of QUAD9 has rotations only)."""
    c = nl_shell(tag, typ, model, defo, relation=relation, lmax=lmax)
    m = c["m"] = c["mesh"]
    su = c["setup"].replace("mesh0 = mesh\n", "").replace(
        "mesh = CREA_MAILLAGE(MAILLAGE=mesh0, MODI_MAILLE=_F(TOUT='OUI', OPTION='QUAD8_9'))",
        "mesh = CREA_MAILLAGE(MAILLAGE=mesh, MODI_MAILLE=(_F(GROUP_MA='SH', OPTION='QUAD8_9'),))")
    ex_ok = c["excit"]
    if press:
        su += "\nprs = AFFE_CHAR_MECA(MODELE=model, PRES_REP=_F(GROUP_MA='SH', PRES=%r))\n" % press
        ex_ok = ex_ok[:-1]+", _F(CHARGE=prs, FONC_MULT=rampe, TYPE_CHARGE='SUIV'))"
        X0 = m.X()
        byr = {r: [q for q, v in m.region.items() if v == r] for r in (0, 1, 2)}
        g0 = {r: nodal_surface(m, byr[r], trac=RHO*T*GOBL) for r in byr}
        ti = m.no["TIP1"][0]-1; tipf = np.array([300., 50., -12.])
        Pc = {a: np.array(b) for a, b in c["cuts"].items()}

        def ref2(t, u):
            xc = X0+u[:, :3]
            regs = {r: g0[r].copy() for r in g0}
            regs[2][ti] += lam(t, lmax)*tipf
            for r in byr:
                regs[r] = regs[r]+lam(t, lmax)*nodal_surface(m, byr[r], pres=press, X=xc)
            return ref_cuts(regs, xc, Pc)
        c["ref"] = ref2
    solve = c["solve"]
    comm = ("DEBUT(LANG='EN')\n"+su+"\nEXC = "+ex_ok+"\n"+solve+"\n"+PRE.replace(", CRITERES=('SIEQ_ELNO',)", "")+"\nFIN()\n")
    comm = comm.replace("CONTRAINTE=('SIGM_ELNO',), ", "")
    c.update(comm=comm, shell=True, press=press, ex=dict(
        V0=("F_SK", None), V1=("F_SK", ex_ok), N_miss=("F_SK", ex_ok.replace("_F(CHARGE=grav), ", "").replace(", _F(CHARGE=grav)", ""))))
    if press:
        c["ex"]["N_nofm"] = ("F_SK", ex_ok.replace("_F(CHARGE=prs, FONC_MULT=rampe,", "_F(CHARGE=prs,"))
    return c


def to_mq(c, a):
    """The mesh as Aster has it after CREA_MAILLAGE, cells numbered by position."""
    m = c["m"]; lq = c["lq"]
    start = np.concatenate(([0], np.cumsum(a["clen"])))
    delta = 0 if a["conn"].min() == 0 else 1
    q = Mesh(); q.parent = {m.pos[s]: m.pos[p] for s, p in m.parent.items()}
    q.xyz = [tuple(p) for p in a["xyz"]]
    for p in range(1, len(m.cells)+1):
        cid = m.cid[p]; t = m.cells[cid-1][0]
        t2 = {"HEXA8": "HEXA20", "QUAD4": "QUAD8"}[t] if lq else t
        q.cells.append((t2, [int(i)+1-delta for i in a["conn"][start[p-1]:start[p]]]))
        if cid in m.region:
            q.region[p] = m.region[cid]
    q.ma = {n: [m.pos[i] for i in ids] for n, ids in m.ma.items()}
    groups_from_regions(q)
    return q


def solid_ref(c, q, region=None):
    """ref(t, u) -> exact cuts on the mesh q. region: {cell position: 0, 1, 2}, default that of q."""
    X = q.X(); tr, ar, press = c["tr"], c["ar"], c["press"]
    reg = region or q.region
    grav = {r: nodal_gravity(q, cells=[p for p, v in reg.items() if v == r]) for r in (0, 1, 2)}
    t1 = nodal_surface(q, q.ma["TIPALL"], trac=tr); t2 = nodal_surface(q, q.ma["TIPTOP"], trac=ar)
    pr_by = {r: [s for s in q.ma.get("PR", []) if reg[q.parent[s]] == r] for r in (0, 1, 2)}
    nod = {r: set() for r in (0, 1, 2)}
    for p, r in reg.items():
        nod[r].update(q.cells[p-1][1])
    ca, cb = sorted(nod[0] & nod[1]), sorted(nod[1] & nod[2])
    Pc = {"CUTA": X[np.array(ca)-1].mean(axis=0), "CUTB": X[np.array(cb)-1].mean(axis=0)}
    tot = [t1, t2]

    def ref(t, u):
        f = c["fac"](t)
        xc = X+u[:, :3] if c["large"] else X
        regs = {r: f[2]*grav[r] for r in grav}
        regs[2] = regs[2]+f[0]*t1+f[1]*t2
        if press:
            xp = xc if c["follow"] else X
            for r in (0, 1, 2):
                if pr_by[r]:
                    regs[r] = regs[r]+f[3]*nodal_surface(q, pr_by[r], pres=press, X=xp)
        return ref_cuts(regs, xc, Pc)
    return ref, dict(CUTA=ca, CUTB=cb), Pc


def score(c, r, var, ref, cuts, Pc, X, nn=None):
    """Worst eF, eM over ranks and cuts, and per rank."""
    a = r["npz"]; d = r["data"]; rows = []
    for k in d["ranks"]:
        key = "%s_%d" % (var, k)
        if key not in a:
            continue
        n = len(X)
        u = a["U_%d" % k][:n]
        t = d["inst"][str(k)]
        Rx = ref(t, u)
        xc = X+u[:, :3] if c.get("large") else X
        for cut in ("CUTA", "CUTB"):
            i = np.array(cuts[cut])-1
            F, Mo = sum_about(a[key][:n][i, :3], xc[i], np.asarray(Pc[cut]), a[key][:n][i, 3:6])
            e = errors(F, Mo, *Rx[cut], L)
            rows.append(dict(rank=k, t=t, cut=cut, eF=e["eF"], eM=e["eM"], Fnorm=float(np.linalg.norm(Rx[cut][0]))))
    return rows


def evaluate(c, r, label=""):
    a = r["npz"]; d = r["data"]
    if c.get("shell"):
        m = c["m"]; X = m.X(); ref = c["ref"]
        cuts = dict(CUTA=m.no["CUTA"], CUTB=m.no["CUTB"]); Pc = c["cuts"]
        got = {k: [i+1 for i in v] for k, v in d["nodeids"].items()}
        same = all(sorted(got[k]) == sorted(cuts[k]) for k in cuts)
    else:
        q = to_mq(c, a); X = q.X()
        ref, cuts, Pc = solid_ref(c, q)
        got = {k: [i+1 for i in v] for k, v in d["nodeids"].items()}
        same = all(sorted(got[k]) == sorted(cuts[k]) for k in cuts)
    print("%s %s POURSUITE %.1f s, cut nodes A %d B %d match %s, meshinfo %s" % (
        c["tag"], label, r["wall"], len(cuts["CUTA"]), len(cuts["CUTB"]), same, d.get("mesh")))
    print("  loads", d.get("loads") if not isinstance(d.get("loads"), dict) else list(d["loads"].values())[-1], "has", set(d["has_loads"]), d.get("load_ids"))
    print("  fields", d.get("fields"), "alarms", r["alarms"], "verr", {k: re.findall(r"<(?:EXCEPTION|F|S)> <\w+>", v) or v[-80:].encode("ascii", "replace").decode() for k, v in d.get("v_err", {}).items()})
    res = {}
    for v in list(c["ex"])+["STORED"]:
        rows = score(c, r, v, ref, cuts, Pc, X)
        if rows:
            res[v] = (max(q["eF"] for q in rows), max(q["eM"] for q in rows))
            print("  %-9s worst eF=%.2e eM=%.2e  ranks %d" % (v, *res[v], len(rows)//2))
        else:
            print("  %-9s no field" % v)
    rows = score(c, r, "V0", ref, cuts, Pc, X)
    if c["tag"] in SHOW:
        for q in rows:
            f = c["fac"](q["t"]) if "fac" in c else ""
            print("   t=%.3f %s fac=%s eF=%.2e eM=%.2e |F|=%.0f" % (q["t"], q["cut"], f, q["eF"], q["eM"], q["Fnorm"]))
    sys.stdout.flush()
    return res


SHOW = ("n1_lq_log_suiv", "l2_ms_list")


def selection(m, region):
    """JSON content: file positions of selection, selection + skin, left and right of it."""
    S = [m.pos[e] for e, r in region.items() if r == 1]
    skc = [m.pos[s] for s, p in m.parent.items() if region[p] == 1]
    return dict(ma=dict(F_S=S, F_SK=S+skc, F_L=[m.pos[e] for e, r in region.items() if r == 0],
                        F_R=[m.pos[e] for e, r in region.items() if r == 2]))


def second_text(c, extra="", only=None):
    ex = {k: v for k, v in c["ex"].items() if only is None or k in only}
    excs = "VARS = ["+", ".join("(%r, %r, %s)" % (v, g, e) for v, (g, e) in ex.items())+"]"
    return SECOND.replace("@EXCS@", excs).replace("@EXTRA@", extra)


def run_case(c, keep=False, mem=3000, ncpus=2):
    tag = c["tag"]; m = c["m"]
    m.free = ("S", "S_SK", "CUTA", "CUTB")
    bridge_mail(os.path.join(WD8, tag+".mail"), m, free=m.free)
    bd = os.path.join(WD8, tag+"_base")
    if os.path.isdir(bd) and os.listdir(bd):
        r1 = dict(wall=0.)
    else:
        r1 = arun(tag+"_1", c["comm"], mail=tag+".mail", base_out=tag+"_base", mem=mem, ncpus=ncpus)
        if not r1["ok"]:
            print(tag, "FIRST FAILED", r1["errors"], r1["rc"], flush=True)
            return None
    json.dump(selection(m, m.region), open(os.path.join(WD8, tag+"_sel.json"), "w"))
    r2 = arun(tag+"_2", second_text(c), sel=tag+"_sel.json", base_in=tag+"_base", mem=mem, ncpus=ncpus)
    print(tag, "first %.0f s, base %.0f MB" % (r1["wall"], base_MB(os.path.join(WD8, tag+"_base"))), "errors second:", r2["errors"], flush=True)
    res = evaluate(c, r2) if r2["data"] else None
    if not keep:
        rm(tag+"_base")
    return res


CASES = {
    "l1_ms": lambda t: solid_case(t, "ms", "HEXA8", (10, 2, 4), relation="ELAS", press=2e6, lq=True, rigid=True),
    "l2_ms_list": lambda t: solid_case(t, "ms_list", "HEXA8", (10, 2, 4), relation="ELAS", press=2e6, lq=True),
    "l3_ms_varc": lambda t: solid_case(t, "ms", "HEXA20", (10, 2, 4), relation="ELAS", varc=True),
    "n1_lq_log_suiv": lambda t: solid_case(t, "nl", "HEXA8", defo="GDEF_LOG", press=2e6, follow=True, lq=True, lmax=7.),
    "n2_petit_arch": lambda t: solid_case(t, "nl", "HEXA20", press=2e6, arch=True),
    "n3_log_charf": lambda t: solid_case(t, "nl", "HEXA20", defo="GDEF_LOG", press=2e6, follow=True, charf=True, lmax=7.),
    "n4_noreac": lambda t: solid_case(t, "nl", "HEXA8", defo="GDEF_LOG", press=2e6, follow=True, lq=True, lmax=7., prereac=False),
    "s1_c3d": lambda t: shell_case(t),
    "s2_c3d_suiv": lambda t: shell_case(t, press=2e3),
    "s3_dkt": lambda t: shell_case(t, typ="QUAD4", model="DKT", defo="PETIT", relation="VMIS_ISOT_LINE", lmax=LMAX),
}

if __name__ == "__main__":
    flt = sys.argv[1:]
    todo = [n for n in CASES if not flt or n in flt]
    with cf.ThreadPoolExecutor(3) as ex:
        out = dict(zip(todo, ex.map(lambda n: run_case(CASES[n](n)), todo)))
    print("SUMMARY")
    for n, v in out.items():
        print(n, v)
