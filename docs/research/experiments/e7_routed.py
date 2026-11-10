# E7 route D: element-wise nodal forces and element-wise loads stored for ALL elements in the
# first run, through the Python API of code_aster. The selection is made afterwards in plain
# Python, without Code-Aster. Run: python e7_routed.py [filter]
from e7_struct import *
from e7_nl import nl_block, nl_shell, summary, lam
from e7_loads import load_case

DUMP = r'''
import importlib
_CA = importlib.import_module('code_aster.CA')
def _split(term, tag):
    """One elementary term: per group of elements the cell ids and the flat values."""
    vals = term.getValues()
    fed = term.getFiniteElementDescriptor() or model.getFiniteElementDescriptor()
    grels = fed.getListOfGroupsOfElements()
    con = mesh.getConnectivity()
    j = 0; n = 0
    for g in grels:
        cells = np.array(g[:-1])
        if j >= len(vals):
            break
        v = np.array(vals[j])
        if len(v) == 0 or len(v) % len(cells) != 0:
            continue
        nn = len(con[int(cells[0])-1]); nv = len(v)//len(cells)
        if nv not in (3*nn, 6*nn, 6*(nn-1)+3, 6*(nn-1)):
            continue
        ARR["%s_c_%d" % (tag, j)] = cells
        ARR["%s_v_%d" % (tag, j)] = v.reshape(len(cells), -1)
        n += v.size
        j += 1
    if j != len(vals):
        OUT.setdefault("dump_warn", []).append("%s: %d of %d" % (tag, j, len(vals)))
    return n
def load_by_step(R, ranks, loads):
    """Loads with their time function: element-wise load vectors per stored step."""
    pb = _CA.PhysicalProblem(model, cm)
    for ch, fn in loads:
        pb.addLoad(ch, fn, "FIXE_CSTE") if fn is not None else pb.addLoad(ch)
    pb.computeListOfLoads()
    pb.computeDOFNumbering()
    dc = _CA.DiscreteComputation(pb)
    acc = R.getAccessParameters()
    inst = dict(zip(acc["NUME_ORDRE"], acc["INST"]))
    ranks = ranks or [k for k in R.getIndexes() if k > 0]
    for k in ranks:
        t = inst[k]
        for nm, v in (("V", dc.getMechanicalVolumetricForces(time_curr=t, assembly=False)),
                      ("N", dc.getMechanicalNeumannForces(time_curr=t, assembly=False))):
            for i, q in enumerate(v.getElementaryTerms()):
                _split(q, "P%d%s_%d" % (k, nm, i))
    lap("dump_step_load")
def elem_dump(R, ranks, loads, cara_=None, nl=False):
    """FORC_NODA per element at every rank; loads per element once, multiplier 1."""
    lap("before_dump")
    pb = _CA.PhysicalProblem(model, cm, cara_) if cara_ else _CA.PhysicalProblem(model, cm)
    for ch in loads:
        pb.addLoad(ch)
    pb.computeListOfLoads()
    pb.computeDOFNumbering()
    dc = _CA.DiscreteComputation(pb)
    lap("dump_setup")
    acc = R.getAccessParameters()
    inst = dict(zip(acc["NUME_ORDRE"], acc["INST"]))
    if ranks is None:
        ranks = [k for k in R.getIndexes() if k > 0]
    OUT["ranks"] = ranks
    OUT["inst"] = {str(k): inst.get(k, 0.) for k in ranks}
    size = 0
    for k in ranks:
        sig = R.getField("SIEF_ELGA", k); u = R.getField("DEPL", k)
        kw = {}
        if nl:
            kw["behaviourMap"] = R.getField("COMPORTEMENT", k)
        if cara_:
            # the API call stops on shells and beams; CALCUL gives the same elementary vector
            lst = DEFI_LIST_REEL(VALE=(0., 1.))
            v = CALCUL(__use_namedtuple__=True, OPTION=("FORC_NODA_ELEM",), MODELE=model, CHAM_MATER=cm,
                       CARA_ELEM=cara_, INCREMENT=_F(LIST_INST=lst, NUME_ORDRE=1), EXCIT=_F(CHARGE=bc), DEPL=u,
                       INCR_DEPL=u-u, SIGM=sig, COMPORTEMENT=_F(**globals().get("CALCOMP", {"RELATION": "ELAS"}))).FORC_NODA_ELEM
        else:
            v = dc.getMechanicalNodalForces(sig, u, assembly=False, **kw)
        t = v.getElementaryTerms()
        for i, q in enumerate(t):
            size += _split(q, "F%d_%d" % (k, i))
        ARR["U_%d" % k] = node_array(u, mesh)
    lap("dump_forc")
    OUT["dump_values"] = size
    nload = 0
    for nm, v in (("V", dc.getMechanicalVolumetricForces(assembly=False)),
                  ("N", dc.getMechanicalNeumannForces(assembly=False))):
        for i, q in enumerate(v.getElementaryTerms()):
            OUT.setdefault("load_terms", []).append(q.getOption())
            nload += _split(q, "L%s_%d" % (nm, i))
    OUT["dump_loads"] = nload
    lap("dump_load")
'''


def comm_d(c, loads, cara=False, nl=False, steploads=None):
    t = ["DEBUT(LANG='EN')", HELP, DUMP, c["setup"], c.get("calcomp", ""), "lap('setup')", "EXC = " + c["excit"], c["solve"], "lap('solve')",
         "elem_dump(res, %r, (%s), %s, %r)" % (c["ranks"], ",".join(loads)+",", "cara" if cara else "None", nl)]
    if steploads:
        t.append("load_by_step(res, [1], %s)" % steploads)
    t += ["finish()", "FIN()"]
    return "\n".join(t)+"\n"


def assemble(prefix, arr, m, nn, S):
    """Sum of element vectors of the cells in S onto the nodes. The values of one element run
    node by node; the number of components per node comes from the size."""
    f = np.zeros((nn, 6))
    keys = [q for q in arr.files if q.startswith(prefix+"_v_")]
    for key in keys:
        cells = arr[key.replace("_v_", "_c_")]
        v = arr[key]
        for i, c in enumerate(cells):
            c = int(c)
            if c not in S:
                continue
            nds = m.cells[c-1][1]
            w = v[i]
            nc = len(w)//len(nds) if len(w) % len(nds) == 0 else 6     # QUAD9, TRIA7: inner node apart
            p = 0
            for n in nds:
                f[n-1, :nc] += w[p:p+nc]; p += nc
    return f


def d_sum(c, r):
    """Selection made afterwards: only numpy, no Code-Aster."""
    m = c["mesh"]; X = m.X(); arr = r["npz"]; data = r["data"]; rows = []
    S = set(m.ma["S"]); Ssk = set(m.ma.get("S_SK", m.ma["S"]))
    t0 = time.perf_counter()
    nn = len(X)
    L = np.zeros((nn, 6))
    pre = sorted({q.split("_v_")[0] for q in arr.files if q.startswith("L") and "_v_" in q})
    for p in pre:
        L = L+assemble(p, arr, m, nn, Ssk)
    # a load with a time function: elementary vectors are not scaled by it, so it is stored once
    # with multiplier 1 and scaled here
    L1 = np.zeros((nn, 6))
    for p in sorted({q.split("_v_")[0] for q in arr.files if q.startswith("P") and "_v_" in q}):
        L1 = L1+assemble(p, arr, m, nn, Ssk)
    L0 = L
    for k in data["ranks"]:
        if c.get("steplam"):
            L = L0+c["steplam"](data["inst"][str(k)])*L1
        f = np.zeros((nn, 6))
        for p in sorted({q.split("_v_")[0] for q in arr.files if q.startswith("F%d_" % k) and "_v_" in q}):
            f = f+assemble(p, arr, m, nn, S)
        a = f-L
        u = arr["U_%d" % k][:nn]
        xc = X+u[:, :3] if c.get("large") else X
        ref = c["ref"](data["inst"][str(k)] if c["kind"] == "noli" else k, u)
        for cut in ("CUTA", "CUTB"):
            i = np.array(m.no[cut])-1
            Fm, Mm = sum_about(a[i, :3], xc[i], np.array(c["cuts"][cut]), a[i, 3:6])
            rows.append(dict(case=c["tag"], route="D", var="ELEM", rank=int(k), cut=cut, rout=0., tabF=0., tabM=0.,
                             **errors(Fm, Mm, ref[cut][0], ref[cut][1], c.get("Lref", L_REF))))
    return rows, time.perf_counter()-t0


L_REF = .2
CASES = [("h20", lambda t: (block_case(t, "HEXA20", (10, 2, 4)), ["bc", "tip", "top", "grav"], False, False)),
         ("h20d", lambda t: (block_case(t, "HEXA20", (10, 2, 4), .15), ["bc", "tip", "top", "grav"], False, False)),
         ("t10d", lambda t: (block_case(t, "TETRA10", (10, 2, 4), .15), ["bc", "tip", "top", "grav"], False, False)),
         ("h8d", lambda t: (block_case(t, "HEXA8", (20, 4, 8), .3), ["bc", "tip", "top", "grav"], False, False)),
         ("mixd", lambda t: (block_case(t, "MIX", (10, 2, 4), .15), ["bc", "tip", "top", "grav"], False, False)),
         ("prs", lambda t: (load_case(t, distort=.15), ["bc", "tip", "top", "grav", "prs", "sd"], False, False)),
         ("dkt", lambda t: (shell_case(t, "QUAD4", "DKT", g_turn), ["bc", "tip", "grav"], True, False)),
         ("c3d", lambda t: (shell_case(t, "QUAD8", "COQUE_3D", g_turn), ["bc", "tip", "grav"], True, False)),
         ("bme", lambda t: (beam_case(t, "POU_D_E", g_turn, load=("grav",)), ["bc", "tip", "grav"], True, False)),
         ("nlp", lambda t: (nl_block(t), ["bc", "grav"], False, True)),
         ("nll", lambda t: (nl_block(t, defo="GDEF_LOG", lmax=7.), ["bc", "grav"], False, True)),
         ("nldkt", lambda t: (dict(nl_shell(t, "QUAD4", "DKT", "PETIT"), calcomp="CALCOMP = dict(RELATION='VMIS_ISOT_LINE')"),
                              ["bc", "grav"], True, False)),
         ("nlc3d", lambda t: (dict(nl_shell(t, "QUAD8", "COQUE_3D", "GROT_GDEP", relation="ELAS", lmax=20.),
                                   calcomp="CALCOMP = dict(RELATION='ELAS', DEFORMATION='GROT_GDEP')"),
                              ["bc", "grav"], True, False)),
         ("nlt", lambda t: (nl_block(t, press=2e6, follow=False), ["bc", "grav"], False, True,
                            "((prs, None),)"))]


if __name__ == "__main__":
    flt = sys.argv[1:]
    out = []
    for name, f in CASES:
        if flt and name not in flt:
            continue
        tag = "e_"+name
        q = f(tag)
        c, loads, cara, nl = q[:4]
        if len(q) > 4:
            c["steplam"] = lam
        stp = q[4] if len(q) > 4 else None
        m = c["mesh"]
        m.free_ma = ("S", "S_SK"); m.free_no = ("CUTA", "CUTB")
        write_mail(os.path.join(WD, tag+".mail"), m)
        r = run_aster(tag, comm_d(c, loads, cara, nl, stp), mail=tag+".mail")
        print(name, r["errors"], round(r["wall"], 1), (r["data"] or {}).get("dump_warn"), (r["data"] or {}).get("load_terms"), flush=True)
        if r["data"]:
            rows, ts = d_sum(c, r)
            summary(rows)
            sz = os.path.getsize(os.path.join(WD, tag+".npz"))/1e6
            d = r["data"]
            print("   cells %d stored values forc %d load %d, file %.2f MB, times %s, python %.3fs" % (
                len(m.cells), d["dump_values"], d["dump_loads"], sz,
                {k: round(v, 2) for k, v in d["times"].items()}, ts), flush=True)
            out.append(dict(case=name, cells=len(m.cells), values=d["dump_values"], load=d["dump_loads"], MB=sz,
                            times=d["times"], py=ts, rows=rows, wall=r["wall"]))
    json.dump(out, open(os.path.join(WD, "res_d%s.json" % ("_"+flt[0] if flt else "")), "w"))
