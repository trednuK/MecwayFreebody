# E6 probes on one element, before any cut is measured:
#  P1 sign of surface pressure, for a solid and a shell in both windings (not from a fit)
#  P2 reaction convention: a load applied on a held node. Is it in the reaction?
#  P3 traction and pressure on a shell face: per area of the mid-surface?
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_lib import *

os.makedirs(WD, exist_ok=True)


def hex_one():
    M = Model(); M.comps = {"P": dict(kind="solid")}
    add_cell(M.m, (0, 0, 0), (.1, .1, .1), "hex8", "P")
    return M


def quad_one(reverse=False):
    M = Model(); M.comps = {"S": dict(kind="shell", t=.005)}
    c = [(0, 0, 0), (.1, 0, 0), (.1, .1, 0), (0, .1, 0)]
    if reverse:
        c = c[::-1]
    M.m.add("quad4", [M.m.node(*p) for p in c], "S")
    return M


def solve_all_held(M, tag, zero=True):
    """All nodes held at zero: every load ends up in the reactions, if it is counted there."""
    M2 = M
    rn = M2.rotnodes()
    holds = {n: (np.zeros(3), np.zeros(3) if n in rn else None) for n in range(1, len(M.m.xyz)+1)}
    d = os.path.join(WD, "probe"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, tag+".liml"); s = os.path.join(d, tag+"_sol.liml")
    M2.write(p, holds=holds, fields=["displacement", "reaction force"]+(["rotation", "reaction moment"] if rn else []))
    solve6(p, s)
    r = Res(s)
    F = sum(r.R(n) for n in holds)
    Mm = sum(np.cross(M.X(n), r.R(n)) + (r.Rm(n) if n in rn else 0) for n in holds)
    return F, Mm, r


def line(name, F, Mm, want):
    print("%-40s R=%s  M=%s  expected R=%s" % (name, np.round(F, 6), np.round(Mm, 6), want), flush=True)


# P1
M = hex_one(); M.loads.append(dict(type="pressure", faces=[(1, 1)], p=1e6))
line("P1 hex8 top face, p=+1e6 (n=+z)", *solve_all_held(M, "p1_hex")[:2], "+1e4 z if p pushes on the element (reaction balances)")
for rev in (False, True):
    for f in (4, 5):
        M = quad_one(rev); M.loads.append(dict(type="pressure", faces=[(1, f)], p=1e6))
        x, da = M.face_surf(1, f)
        line("P1 quad4 rev=%s faceid=%d, da=%s" % (rev, f+1, np.round(da.sum(axis=0), 4)), *solve_all_held(M, "p1_q%d_%d" % (rev, f))[:2], "?")

# P2 force on a held node
M = hex_one(); M.loads.append(dict(type="nforce", nodes=[1], F=(10., 20., 30.)))
F, Mm, r = solve_all_held(M, "p2_hex")
line("P2 hex8 force on held node 1", F, Mm, "-(10,20,30) if the load is in the reaction, 0 if not")
M = quad_one(); M.loads.append(dict(type="nforce", nodes=[1], F=(10., 20., 30.)))
line("P2 quad4 force on held node 1", *solve_all_held(M, "p2_q")[:2], "same question")
M = quad_one(); M.loads.append(dict(type="nmoment", nodes=[3], M=(1., 2., 3.)))
line("P2 quad4 moment on held node 3", *solve_all_held(M, "p2_qm")[:2], "M -(1,2,3) if counted")
M = hex_one(); M.loads.append(dict(type="fforce", faces=[(1, 1)], F=(0., 0., 100.)))
line("P2 hex8 force on a held face", *solve_all_held(M, "p2_hf")[:2], "-100 z if counted")

# P3 traction on a shell face, gravity in a held shell
M = quad_one(); M.loads.append(dict(type="traction", faces=[(1, 4)], T=(1e5, 2e5, 3e5)))
line("P3 quad4 traction on face 5", *solve_all_held(M, "p3_t")[:2], "-(1000,2000,3000) if per area")
M = quad_one(); M.loads.append(dict(type="fforce", faces=[(1, 0)], F=(0., 0., 60.)))
line("P3 quad4 force on edge 1", *solve_all_held(M, "p3_e")[:2], "-60 z")
M = quad_one(); M.loads.append(dict(type="gravity", g=(0., 0., -10.)))
line("P3 quad4 gravity", *solve_all_held(M, "p3_g")[:2], "+%.3f z" % (RHO*.005*.01*10))

# P3b the lever of a traction on a shell face: both faces, in-plane force only
for f in (4, 5):
    M = quad_one(); M.loads.append(dict(type="traction", faces=[(1, f)], T=(1e5, 0., 0.)))
    line("P3b quad4 traction x on faceid %d" % (f+1), *solve_all_held(M, "p3b_%d" % f)[:2], "M about y = -/+ 1000*t/2 = -/+2.5 if at the surface")

# P4 a moment on several nodes: written here as one selection, on purpose
from e6_mesh import strip, m_flat
for n in (1, 2, 5):
    M = strip("quad4")
    d = os.path.join(WD, "probe"); p = os.path.join(d, "p4_%d.liml" % n); s = os.path.join(d, "p4_%d_sol.liml" % n)
    M.write(p, fields=["displacement", "rotation", "reaction force", "reaction moment"])
    t = io.open(p, encoding="utf-8").read()
    sel = '  <nodeselection name="MM">' + "".join('<node nid="%d" />' % q for q in M.tip[:n]) + '</nodeselection>'
    mom = '  <moment selection="MM"><x>2 N.m</x><y>3 N.m</y><z>0 N.m</z></moment>'
    io.open(p, "w", encoding="ascii").write(t.replace("</liml>", sel+mom+"</liml>"))
    solve6(p, s); r = Res(s)
    print("P4 moment (2,3,0) on one selection of %d node(s): sum reaction moment = %s" % (n, np.round(sum(r.Rm(q) for q in M.root), 6)), flush=True)
