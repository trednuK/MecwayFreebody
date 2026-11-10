# E7 model 5: loads on and next to the cut. Pressure and face traction on skin cells on both
# sides of a cut, gravity, a nodal force on a cut node, a support on cut nodes, and a tie
# through the cut (no shared nodes). Run: python e7_loads.py [filter]
import concurrent.futures as cf
from e7_routes import *

PR = 2e5
TR = np.array([3e5, -2e5, 1e5])
FNOD = np.array([150., -250., 100.])


def load_case(tag, shape="HEXA20", dims=(10, 2, 4), distort=0., node_force=False, support=False, tie=False):
    m = block(shape, dims, distort)
    nx = dims[0]
    S_nodes = None
    if tie:
        # the right part gets its own nodes on the interface: no shared nodes at cut B
        nod = {r: set() for r in (0, 1, 2)}
        for c, r in m.region.items():
            nod[r].update(m.cells[c-1][1])
        iface = nod[1] & nod[2]
        twin = {}
        for n in sorted(iface):
            m.xyz.append(m.xyz[n-1]); twin[n] = len(m.xyz)
        for c, r in m.region.items():
            if r == 2:
                t, nds = m.cells[c-1]
                m.cells[c-1] = (t, [twin.get(q, q) for q in nds])
        m._free = free_faces(m)
        m.no["TIESL"] = sorted(twin.values()); m.no["TIEMA"] = sorted(iface)
        m.ma["SMAST"] = [c for c, r in m.region.items() if r == 1]
    skin(m, "ROOT", lambda c: abs(c[0]) < 1e-9)
    skin(m, "TIPALL", lambda c: abs(c[0]-L) < 1e-9)
    skin(m, "TIPTOP", lambda c: abs(c[0]-L) < 1e-9 and c[2] > H/2)
    skin(m, "PR", lambda c: abs(c[2]-H) < 1e-9)
    skin(m, "SD", lambda c: abs(c[1]) < 1e-9 and .03 < c[0] < .07)
    groups_from_regions(m)
    if tie:
        m.no["CUTB"] = m.no["TIEMA"]
    X = m.X()
    AT, AU = surf_area(m, m.ma["TIPALL"]), surf_area(m, m.ma["TIPTOP"])
    tr = TIPF/AT; ar = TOPF/AU
    su = SOLID % dict(E=E0, NU=NU, RHO=RHO, tx=tr[0], ty=tr[1], tz=tr[2], ax=ar[0], ay=ar[1], az=ar[2])
    su += "prs = AFFE_CHAR_MECA(MODELE=model, PRES_REP=_F(GROUP_MA='PR', PRES=%r))\n" % PR
    su += "sd = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=_F(GROUP_MA='SD', FX=%r, FY=%r, FZ=%r))\n" % tuple(TR)
    ex = ["_F(CHARGE=bc)", "_F(CHARGE=tip)", "_F(CHARGE=top)", "_F(CHARGE=grav)", "_F(CHARGE=prs)", "_F(CHARGE=sd)"]
    regs = {r: nodal_gravity(m, cells=[c for c, q in m.region.items() if q == r]) for r in (0, 1, 2)}
    regs[2] = regs[2]+nodal_surface(m, m.ma["TIPALL"], trac=tr)+nodal_surface(m, m.ma["TIPTOP"], trac=ar)
    for r in (0, 1, 2):
        ids = [s for s in m.ma["PR"] if m.region[m.parent[s]] == r]
        regs[r] = regs[r]+nodal_surface(m, ids, pres=PR)
        ids = [s for s in m.ma["SD"] if m.region[m.parent[s]] == r]
        regs[r] = regs[r]+nodal_surface(m, ids, trac=TR)
    cuts = cut_points(m)
    Pc = {a: np.array(b) for a, b in cuts.items()}
    extra = {}
    if node_force:
        # a node inside the cross-section of cut B, on an inner corner
        k = m.no["CUTB"][len(m.no["CUTB"])//2]
        m.no["FN"] = [k]
        su += "fn = AFFE_CHAR_MECA(MODELE=model, FORCE_NODALE=_F(GROUP_NO='FN', FX=%r, FY=%r, FZ=%r))\n" % tuple(FNOD)
        ex.append("_F(CHARGE=fn)")
        extra["k"] = k-1
    if support:
        m.no["SUP"] = m.no["CUTB"][:3]
        su += "sup = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_NO='SUP', DZ=0.))\n"
        ex.append("_F(CHARGE=sup)")
    if tie:
        su += "tie = AFFE_CHAR_MECA(MODELE=model, LIAISON_MAIL=_F(GROUP_MA_MAIT='SMAST', GROUP_NO_ESCL='TIESL'))\n"
        ex.append("_F(CHARGE=tie)")

    def ref(k, u):
        rg = {r: regs[r].copy() for r in regs}
        if node_force:
            rg[2][extra["k"]] += FNOD       # the node's load counts as the other side
        return ref_cuts(rg, X, Pc)

    return dict(tag=tag, mesh=m, setup=su, excit="("+", ".join(ex)+")", kind="elas", fields=["DEPL", "SIEF_ELGA"],
                solve="res = MECA_STATIQUE(MODELE=model, CHAM_MATER=cm, EXCIT=EXC, SOLVEUR=_F(METHODE='MUMPS'))",
                ranks=[1], cuts=cuts, ref=ref, regs=regs,
                post_extra="rall = CALC_CHAMP(RESULTAT=res, FORCE='REAC_NODA')\n"
                           "ARR['ALLREAC'] = node_array(rall.getField('REAC_NODA', 1), mesh)")


CASES = [("h20", lambda t: load_case(t)), ("h20d", lambda t: load_case(t, distort=.15)),
         ("t10", lambda t: load_case(t, "TETRA10")), ("t10d", lambda t: load_case(t, "TETRA10", distort=.15)),
         ("h8", lambda t: load_case(t, "HEXA8", (20, 4, 8))), ("h8d", lambda t: load_case(t, "HEXA8", (20, 4, 8), .3)),
         ("mixd", lambda t: load_case(t, "MIX", distort=.15)),
         ("fnode", lambda t: load_case(t, node_force=True)),
         ("supp", lambda t: load_case(t, support=True)),
         ("tie", lambda t: load_case(t, tie=True))]


def one(a):
    c = a[1]("l_"+a[0])
    rows, info = run_routes(c)
    return c, rows, info


if __name__ == "__main__":
    flt = sys.argv[1:]
    todo = [a for a in CASES if not flt or a[0] in flt]
    all_r = []; infos = []
    with cf.ThreadPoolExecutor(3) as ex:
        for c, rows, info in ex.map(one, todo):
            show([q for q in rows if q["route"] in ("A", "B")]); all_r += rows; infos.append(info)
            print(info["case"], {k: info[k]["err"] for k in ("A", "P", "B", "B0", "Bm", "C") if k in info}, flush=True)
    json.dump(dict(rows=all_r, info=infos), open(os.path.join(WD, "res_loads%s.json" % ("_"+flt[0] if flt else "")), "w"))
