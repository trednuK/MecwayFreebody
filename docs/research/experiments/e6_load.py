# E6 case 3: loads next to the cut with M4L. Pressure, traction and force on free faces that
# span the cut: part in the layer (kept in the sub-model), part on the far side (statics
# reference). Each cut against statics, and the sum over the cuts plus the loads on S.
# Run: python e6_load.py [filter words]
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *
from e6_shell import turned, R3, select

os.makedirs(WD, exist_ok=True)
FILTER = sys.argv[1:]
NEG = (("noLoadInLayer", dict(drop=("pressure", "traction", "fforce"))),)


def wanted(*w):
    return not FILTER or any(any(f in q for q in w) for f in FILTER)


def solid_case(code, n, dist):
    M = block(code, n, dist); block_loads(M)
    nx, ny, nz = M.dims; dx = M.d[0]
    x1, x2 = (nx//4)*dx, (3*nx//4)*dx
    M.loads.append(dict(type="pressure", p=2e6,
                        faces=free_faces(M, lambda c: abs(c[2]-BH) < 1e-9 and abs(c[0]-x1) < 2*dx)))
    M.loads.append(dict(type="traction", T=(1e6, 5e5, -8e5),
                        faces=free_faces(M, lambda c: abs(c[1]) < 1e-9 and abs(c[0]-x2) < 2*dx)))
    M.loads.append(dict(type="fforce", F=(-300., -900., 400.),
                        faces=free_faces(M, lambda c: abs(c[1]-BB) < 1e-9 and abs(c[0]-x1) < 2*dx)))
    S = [e for e, c in M.cell.items() if nx//4 <= c[0] < 3*nx//4]
    return M, S


def edge_faces(M, where):
    """Shell edges (e, f) with free edge and centre satisfying where(u, v)."""
    d = {}
    for e, (sh, nds) in M.m.elems.items():
        step = 2 if sh in ("quad8", "tri6") else 1
        nc = len(nds)//step
        for f in range(nc):
            a, b = nds[f*step], nds[((f+1) % nc)*step]
            d.setdefault(tuple(sorted((a, b))), []).append((e, f))
    out = []
    for (a, b), lst in d.items():
        if len(lst) == 1:
            u = (M.uv[a-1][0]+M.uv[b-1][0])/2; v = (M.uv[a-1][1]+M.uv[b-1][1])/2
            if where(u, v):
                out.append(lst[0])
    return out


def shell_case(sh, fn):
    M = strip(sh, mapfn=fn)
    M.loads.append(dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)))
    M.loads.append(dict(type="gravity", g=g_oblique))
    near1 = [e for e, i in M.par.items() if 3 <= i < 7]
    near2 = [e for e, i in M.par.items() if 13 <= i < 17]
    M.loads.append(dict(type="pressure", p=5e4, faces=[(e, 4) for e in near1]))
    M.loads.append(dict(type="traction", T=(2e4, -1e4, 3e4), faces=[(e, 5) for e in near2]))
    M.loads.append(dict(type="fforce", F=(50., -80., 120.),
                        faces=edge_faces(M, lambda u, v: abs(v) < 1e-9 and abs(u-.05) < .02)))
    return M, select(M, 5, 15)


if __name__ == "__main__":
    for code, n in (("hex8", 2), ("hex20", 1), ("tet4", 1), ("tet10", 1), ("wedge15y", 1), ("pyr13", 1)):
        for dist in (0., .3):
            case = "l3_solid" + ("_dist" if dist else "")
            if wanted(code, case):
                M, S = solid_case(code, n, dist)
                run_case(M, S, case, code, negatives=NEG if not dist else ())
                save_results("e6_load")
    for sh in ("quad4", "quad8", "tri3", "tri6"):
        for name, fn in (("flat", m_flat), ("fold60_turned", turned(m_fold(60), R3)), ("arc", m_arc())):
            case = "l3_shell_"+name
            if wanted(sh, case):
                M, S = shell_case(sh, fn)
                run_case(M, S, case, sh, negatives=NEG if name == "flat" else ())
                save_results("e6_load")
    # a nodal force exactly on a cut node: left out of the sub-model, so it must count as a
    # load on the far side (R = statics of the rest, with that load in it). Closure is then
    # double-counted on purpose: ignore it in this row.
    if wanted("cutnode"):
        for code, n in (("hex8", 1), ("hex20", 1)):
            M = block(code, n); block_loads(M)
            nx = M.dims[0]; x2 = (3*nx//4)*M.d[0]
            cn = [i+1 for i, p in enumerate(M.m.xyz) if abs(p[0]-x2) < 1e-9 and abs(p[2]-BH) < 1e-9 and abs(p[1]) < 1e-9]
            M.loads.append(dict(type="nforce", nodes=cn, F=(100., 400., -900.)))
            S = [e for e, c in M.cell.items() if nx//4 <= c[0] < 3*nx//4]
            run_case(M, S, "l3_on_cut_node", code)
            save_results("e6_load")
