# E6: where do the 1e-3 on curved quad8/tri6 shells come from (case 3, arc)? Each load alone,
# global moment and force against the exact integral; then the discrete load: Mecway's own
# nodal loads on the far side, read as reactions of that part with all its nodes held at
# zero. If M4L matches those, the method is exact and the gap lies in how Mecway integrates
# the load on a curved element.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *
from e6_shell import select
from e6_load import edge_faces

os.makedirs(WD, exist_ok=True)


def build(sh, which):
    M = strip(sh, mapfn=m_arc())
    near1 = [e for e, i in M.par.items() if 3 <= i < 7]
    near2 = [e for e, i in M.par.items() if 13 <= i < 17]
    if which == "pressure":
        M.loads.append(dict(type="pressure", p=5e4, faces=[(e, 4) for e in near1]))
    elif which == "traction":
        M.loads.append(dict(type="traction", T=(2e4, -1e4, 3e4), faces=[(e, 5) for e in near2]))
    elif which == "edge":
        M.loads.append(dict(type="fforce", F=(50., -80., 120.), faces=edge_faces(M, lambda u, v: abs(v) < 1e-9 and abs(u-.05) < .02)))
    elif which == "gravity":
        M.loads.append(dict(type="gravity", g=g_oblique))
    elif which == "tip":
        M.loads.append(dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)))
    elif which == "all":
        M.loads.append(dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)))
        M.loads.append(dict(type="gravity", g=g_oblique))
        M.loads.append(dict(type="pressure", p=5e4, faces=[(e, 4) for e in near1]))
        M.loads.append(dict(type="traction", T=(2e4, -1e4, 3e4), faces=[(e, 5) for e in near2]))
        M.loads.append(dict(type="fforce", F=(50., -80., 120.), faces=edge_faces(M, lambda u, v: abs(v) < 1e-9 and abs(u-.05) < .02)))
    return M


def discrete(M, E, tag, name):
    """Wrench of Mecway's nodal loads on element set E about the origin."""
    M2, nmap, emap = M.sub(E)
    # the full load on these elements: nforce nodes shared with S do not occur here
    holds = {q: (np.zeros(3), np.zeros(3)) for q in nmap.values()}
    d = os.path.join(WD, tag); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name+".liml"); s = os.path.join(d, name+"_sol.liml")
    M2.write(p, holds=holds, fields=["displacement", "rotation", "reaction force", "reaction moment"])
    solve6(p, s)
    r = Res(s)
    F = np.zeros(3); Mo = np.zeros(3)
    for q in holds:
        F = F-r.R(q); Mo = Mo-r.Rm(q)-np.cross(M2.X(q), r.R(q))
    return F, Mo


for sh in ("quad8", "tri6", "quad4"):
    for which in ("pressure", "traction", "edge", "gravity", "tip"):
        M = build(sh, which)
        tag = "a_%s_%s" % (sh, which)
        r, g, sol = solve_main(M, tag)
        print("  %s %s alone: global eF=%.2e eM=%.2e" % (sh, which, g["eF"], g["eM"]), flush=True)

for sh in ("quad8", "tri6"):
    M = build(sh, "all"); S = select(M, 5, 15)
    tag = "a_%s_all" % sh
    r, g, sol = solve_main(M, tag)
    parts, layer, cut = analyse(M, S)
    R = sub_solve(M, layer, M.nodes_of(layer), r, tag, "m4l", exclude=cut)
    for i, p in enumerate(parts):
        F, Mo, _ = cut_wrench(M, p, R)
        Fx, Mx = exact(M, p, S)
        if p["support"]:
            E = [e for e in M.m.elems if e not in set(p["elems"])]
            Fd, Md = discrete(M, E, tag, "disc%d" % i)
            Fd, Md = -Fd, -Md
        else:
            Fd, Md = discrete(M, p["elems"], tag, "disc%d" % i)
        Md = Md-np.cross(p["P"], Fd)
        print("  %s cut %d: M4L vs integral eF=%.2e eM=%.2e | M4L vs Mecway's nodal loads eF=%.2e eM=%.2e" % (
            sh, i+1, *[errors(F, Mo, Fx, Mx, M.Lc)[k] for k in ("eF", "eM")],
            *[errors(F, Mo, Fd, Md, M.Lc)[k] for k in ("eF", "eM")]), flush=True)
