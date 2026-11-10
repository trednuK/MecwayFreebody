# E6 cases 4 and 5.
# Case 4: solid flange and shell web that share nodes (T section), cut through both.
# Case 5: shell with element offset. First the global moment shows where Mecway puts the
# loads of an offset shell (hypotheses, not fitted to the cuts), then M4/M4L, with and
# without the offset in the sub-model.
# Run: python e6_mixed.py [filter words]
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *
from e6_shell import turned, R3, select

os.makedirs(WD, exist_ok=True)
FILTER = sys.argv[1:]
B_, Hf, Dw = .03, .01, .04
NEG = (("noRot", dict(rotdirs="")),)


def wanted(*w):
    return not FILTER or any(any(f in q for q in w) for f in FILTER)


def tee(code, shell, nu=20, nw=4):
    M = Model(); M.Lc = Dw+Hf; m = M.m
    M.comps = {"P": dict(kind="solid"), "S": dict(kind="shell", t=T)}
    du = L/nu; dy = B_/2; dz = Dw/nw
    for i in range(nu):
        for j in range(2):
            x0 = (i*du, -B_/2+j*dy, 0.); d = (du, dy, Hf)
            if code.startswith("wedge"):
                add_wedges(m, x0, d, code[:-1], code[-1], "P")
            else:
                add_cell(m, x0, d, code, "P")
    for i in range(nu):
        for k in range(nw):
            c = [np.array(q) for q in ((i*du, 0., -k*dz), ((i+1)*du, 0., -k*dz),
                                       ((i+1)*du, 0., -(k+1)*dz), (i*du, 0., -(k+1)*dz))]

            def nd(p):
                return m.node(float(p[0]), float(p[1]), float(p[2]))
            if shell == "quad4":
                m.add(shell, [nd(q) for q in c], "S")
            elif shell == "quad8":
                m.add(shell, [nd(c[0]), nd((c[0]+c[1])/2), nd(c[1]), nd((c[1]+c[2])/2), nd(c[2]),
                              nd((c[2]+c[3])/2), nd(c[3]), nd((c[3]+c[0])/2)], "S")
            else:
                for a, b, e in ((0, 1, 2), (0, 2, 3)):
                    if shell == "tri3":
                        m.add(shell, [nd(c[a]), nd(c[b]), nd(c[e])], "S")
                    else:
                        m.add(shell, [nd(c[a]), nd((c[a]+c[b])/2), nd(c[b]), nd((c[b]+c[e])/2), nd(c[e]),
                                      nd((c[e]+c[a])/2)], "S")
    M.root = {i+1 for i, p in enumerate(m.xyz) if abs(p[0]) < 1e-9}
    tipshell = sorted(M.nodes_of([e for e in m.elems if m.comp[e] == "S"]))
    tipshell = [n for n in tipshell if abs(m.xyz[n-1][0]-L) < 1e-9 and m.xyz[n-1][2] < -1e-9]
    M.loads.append(dict(type="fforce", F=(800., 200., -500.), faces=free_faces(M, lambda c: abs(c[0]-L) < 1e-9)))
    M.loads.append(dict(type="nforce", nodes=tipshell, F=(100., 300., -200.)))
    M.loads.append(dict(type="gravity", g=g_oblique))
    return M


def offset_case(sh, fn, w, part=None, edge=False):
    M = strip(sh, mapfn=fn)
    M.Lc = W_
    elems = sorted(M.m.elems) if part is None else [e for e, i in M.par.items() if i < part]
    M.loads.append(dict(type="offset", elems=elems, w=w))
    if edge:
        from e6_load import edge_faces
        M.loads.append(dict(type="fforce", F=(300., 200., -100.), faces=edge_faces(M, lambda u, v: abs(u-L) < 1e-9)))
    else:
        M.loads.append(dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)))
    M.loads.append(dict(type="gravity", g=g_oblique))
    return M


def hypotheses(M, r, tag):
    """Global moment on the supports against statics, for each place the loads could act."""
    P = np.mean([M.X(n) for n in M.root], axis=0)
    F = sum(r.R(n) for n in M.root)
    Mo = sum(np.cross(M.X(n)-P, r.R(n))+r.Rm(n) for n in M.root)
    best = None
    for sign in (1., -1.):
        for ga in (False, True):
            for la in (False, True):
                M.offset_sign = sign; M.grav_at_offset = ga; M.loads_at_offset = la
                for Lq in M.loads:
                    if Lq["type"] == "nforce":
                        Lq["off"] = sign*M.loads[0]["w"]*node_n(M, Lq["nodes"][0])
                Fe, Me = wrench(M.ext_points(M.m.elems), P)
                e = float(np.linalg.norm(Mo+Me)/np.linalg.norm(Me))
                print("    hyp %s sign=%+d gravity_at_offset=%d loads_at_offset=%d: global eM=%.2e" % (tag, sign, ga, la, e), flush=True)
                if best is None or e < best[0]-1e-12:
                    best = (e, sign, ga, la)
    _, M.offset_sign, M.grav_at_offset, M.loads_at_offset = best
    for Lq in M.loads:
        if Lq["type"] == "nforce":
            Lq["off"] = M.offset_sign*M.loads[0]["w"]*node_n(M, Lq["nodes"][0])
    RESULTS.append(dict(case=tag, shape="", method="hypothesis", cut="-", eF=0, eM=best[0], eMraw=best[0], sign=best[1], grav=best[2], load=best[3]))
    return best


def node_n(M, n):
    for e, (sh, nds) in M.m.elems.items():
        if n in nds:
            return M.normal(e)


def offset_run(M, S, case, sh, neg=True):
    tag = "%s_%s" % (case, sh)
    try:
        r, g, sol = solve_main(M, tag)
    except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
        fail(case, sh, "main", ex)
        return
    best = hypotheses(M, r, tag)
    print("    chosen:", best, flush=True)
    parts, layer, cut = analyse(M, S)
    for name, E, held, kw in (("M4", S, cut, {}), ("M4L", layer, M.nodes_of(layer), {}),
                              ("NEG:noOffset", layer, M.nodes_of(layer), dict(drop=("offset",)))):
        if name.startswith("NEG") and not neg:
            continue
        try:
            R = sub_solve(M, E, held, r, tag, name.replace(":", "_"), exclude=cut, **kw)
            report(M, S, parts, R, case, sh, name)
        except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
            fail(case, sh, name, ex)


if __name__ == "__main__":
    for code, sh in (("hex8", "quad4"), ("hex20", "quad8"), ("tet10", "quad8"), ("wedge15z", "quad8"),
                     ("hex8", "tri3"), ("hex20", "tri6")):
        if wanted(code, sh, "tee"):
            M = tee(code, sh)
            S = select_x(M, .05, .15)
            run_case(M, S, "m4_tee", code+"+"+sh, negatives=NEG if code in ("hex8", "hex20") else ())
            save_results("e6_mixed")
    for sh in ("quad4", "quad8", "tri3", "tri6"):
        if wanted(sh, "offset"):
            M = offset_case(sh, m_flat, .01)
            offset_run(M, select(M, 5, 15), "o5_flat", sh)
            M = offset_case(sh, turned(m_fold(60), R3), .01)
            offset_run(M, select(M, 5, 15), "o5_fold60_turned", sh)
            M = offset_case(sh, m_flat, .01, edge=True)
            offset_run(M, select(M, 5, 15), "o5_edgeforce", sh, neg=False)
            save_results("e6_mixed")
