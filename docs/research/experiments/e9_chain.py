# E9: the whole chain on self-made models, through the real bridge code (no Mecway):
# .liml -> bridge with keep_base -> Code-Aster -> manifest -> POURSUITE on the kept base ->
# forces per cut node -> sum on x+u -> statics, with two cuts and per stored step.
# Bridge folder in FB_BRIDGE, work folder in FB_WORK.
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("E7_WD", os.environ["FB_WORK"])
from fb_lib import *
from e8_lib import HELP8, run_aster

wd = os.environ["FB_WORK"]; os.makedirs(wd, exist_ok=True)
BRIDGE = os.environ["FB_BRIDGE"]
ONE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e9_one.py")
L, B, H = .2, .02, .04
NX, NY, NZ = 20, 4, 8
RHO = 7850.0; GRAV = np.array([0, 0, -9.81])

SECOND = "POURSUITE(LANG='EN')\n" + HELP8 + r"""
sel = json.load(open('fort.32'))
M = res.getMesh()
for n, ids in sel.items():
    M.setGroupOfCells(n, [i-1 for i in ids])
M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_NO=(
    _F(NOM='NS', GROUP_MA='F_S'), _F(NOM='NR', GROUP_MA='F_R'), _F(NOM='CUT', INTERSEC=('NS', 'NR'))))
rs = CALC_CHAMP(RESULTAT=res, GROUP_MA='F_SK', FORCE='REAC_NODA')
ranks = [k for k in res.getIndexes()]
acc = res.getAccessParameters()
OUT['ranks'] = ranks
OUT['inst'] = dict((str(k), t) for k, t in zip(acc['NUME_ORDRE'], acc['INST'])) if 'INST' in acc else {}
OUT['cut'] = [int(i) for i in M.getNodes('CUT')]
ARR['xyz'] = np.asarray(M.getCoordinates().getValues(), dtype=float).reshape(-1, 3)
for k in ranks:
    ARR['R_%d' % k] = node_array(rs.getField('REAC_NODA', k), M)
    ARR['U_%d' % k] = node_array(res.getField('DEPL', k), M)
try:
    OUT['pmax'] = float(max(res.getField('VARI_ELGA', ranks[-1]).getValues()))
except Exception as e:
    OUT['pmax'] = None
finish()
FIN()
"""


def statics(m, right, loads, P, U):
    """Sum on the part to the right of the cut, on the deformed shape (dead loads); loads:
    [(faces, F)], total on those faces. U: (nn, 3), index nid-1."""
    pts = []
    for e in right:
        shape, nds = m.elems[e]
        X = np.array([m.X(n) for n in nds]); u = np.array([U[n-1] for n in nds])
        for q, w in elem_rule(shape):
            N, dN = SF[shape](*q)
            pts.append((RHO*GRAV*np.linalg.det(X.T @ dN)*w, N @ (X+u)))
    for faces, F in loads:
        pts.append((np.array(F), load_centre(m, faces, U)))
    return sum(p[0] for p in pts), sum(np.cross(p[1]-P, p[0]) for p in pts)


def load_centre(m, faces, U):
    """Centre of a uniform load on the deformed faces, area taken undeformed."""
    a = 0; c = 0
    for e, f in faces:
        shape, nds = m.elems[e]
        X = np.array([m.X(n) for n in nds]); u = np.array([U[n-1] for n in nds])
        for p, w, dxi, de in face_points(shape, f):
            N, dN = SF[shape](*p)
            J = X.T @ dN
            da = np.linalg.norm(np.cross(J @ dxi, J @ de))*w
            a += da; c = c + da*(N @ (X+u))
    return c/a


def case(tag, shape, analysis, settings, general, text_patch, F_tip, F_side, rank_check="last"):
    m = Mesh(); cells = {}
    d = (L/NX, B/NY, H/NZ)
    for i in range(NX):
        for j in range(NY):
            for k in range(NZ):
                cells[(i, j, k)] = add_cell(m, (i*d[0], j*d[1], k*d[2]), d, shape)
    S = [e for (i, j, k), es in cells.items() if NX//4 <= i < 3*NX//4 for e in es]
    Sset = set(S)
    root = boundary_faces(m, lambda c: abs(c[0]) < 1e-9)
    tip = boundary_faces(m, lambda c: abs(c[0]-L) < 1e-9)
    # a load on free faces of the selection, next to the first cut (a skin cell of the selection)
    side = boundary_faces(m, lambda c: abs(c[2]-H) < 1e-9 and L/4 < c[0] < L/4+2*d[0])
    p = os.path.join(wd, tag+".liml")
    write_liml(p, m, rho=RHO, gravity=GRAV, fixed_faces=root,
               forces=[("TIP", tip, tuple(F_tip)), ("SIDE", side, tuple(F_side))])
    t = open(p, encoding="ascii").read()
    t = text_patch(t) if text_patch else t
    open(p, "w", encoding="ascii", newline="\n").write(t)
    cfgp = os.path.join(wd, tag+"_cfg.json")
    json.dump(dict(general=dict(general, keep_base=True, keep_base_runs=2), settings=settings), open(cfgp, "w"))
    w = os.path.join(wd, tag)
    r = subprocess.run([sys.executable, ONE, BRIDGE, w, p, analysis, cfgp], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(tag, r.stdout.strip()[-120:], r.stderr.strip()[-300:])
    man = json.load(open(os.path.join(w, tag+"_20261107_120000_manifest.json"), encoding="utf-8"))
    pos = dict((n, i+1) for i, n in enumerate(man["cells"]))
    print("  cells", len(man["cells"]), "skin", len(man["skin"]), "extra_nodes", man["extra_nodes"], "solver", man["solver"], man["deformation_by_component"],
          "not_shared", man["not_shared"])
    skin = [k for k, parents in man["skin"].items() if any(e in Sset for e, f in parents)]
    F_S = [pos["M%d" % e] for e in S]
    F_R = [pos["M%d" % e] for e in m.elems if e not in Sset]
    json.dump(dict(F_S=F_S, F_R=F_R, F_SK=F_S+[pos[k] for k in skin]), open(os.path.join(w, "sel.json"), "w"))
    out = run_aster("post", SECOND, sel="sel.json", base_in=man["base"], wd=w, mem=2048)
    if out.get("npz") is None:
        print("  POURSUITE failed", out.get("rc"), out.get("errors"))
        return
    o = out["data"]
    z = out["npz"]; xyz = z["xyz"]
    cut = np.array(o["cut"])   # 0-based, as setGroupOfCells
    print("  POURSUITE %.1f s, %d cut nodes, ranks %s" % (out.get("wall", 0), len(cut), o["ranks"]))
    k = o["ranks"][-1]
    R = z["R_%d" % k]; U = z["U_%d" % k]
    large = man["deformation"] != "PETIT"
    xdef = xyz + U[:, :3] if large else xyz
    print("  deformation", man["deformation"])
    print("  u max %.2f mm, plastic strain max %s" % (1e3*np.abs(U[:, :3]).max(), o.get("pmax")))
    for xc, sign in ((L/4, -1), (3*L/4, 1)):
        nn = cut[np.abs(xyz[cut, 0]-xc) < 1e-7]
        P = np.array([xc, B/2, H/2])
        Fc = R[nn, :3].sum(axis=0)
        Mc = np.cross(xdef[nn]-P, R[nn, :3]).sum(axis=0)
        right = [e for e in m.elems if np.mean([m.X(q)[0] for q in m.elems[e][1]]) > xc]
        loads = [(tip, F_tip)] + ([(side, F_side)] if xc < L/2 else [])
        Fx, Mx = statics(m, right, loads, P, U[:, :3] if large else 0*U[:, :3])
        Fx, Mx = sign*Fx, sign*Mx
        lc = L
        eF = np.linalg.norm(Fc-Fx)/max(np.linalg.norm(Fx), np.linalg.norm(Mx)/lc)
        eM = np.linalg.norm(Mc-Mx)/max(np.linalg.norm(Mx), np.linalg.norm(Fx)*lc)
        print("  x=%.3f nodes %d F %s exact %s eF %.1e eM %.1e" % (xc, len(nn), np.round(Fc, 3), np.round(Fx, 3), eF, eM))


def nonlin(t):
    t = t.replace('<analysis type="S30" />', '<analysis type="L30" />\n  <timesteps timeperiod="1 s" stepsize="0.25 s" />')
    return t.replace('poissonratio="0.3" />', 'poissonratio="0.3" /><plastic type="BilinearIsotropic" yieldstrength="250000000 Pa" tangentmodulus="2000000000 Pa" />')


def ramp(t):
    """The tip force grows with time, so every step shows other forces."""
    t = nonlin(t)
    a = '<z>-12000.0 N</z></force>'
    assert a in t
    return t.replace(a, '<z time="0 s">0 N</z><z time="1 s">-12000 N</z></force>')


if __name__ == "__main__":
    which = sys.argv[1:] or ["lin", "lq", "nl"]
    if "ramp" in which:
        case("c_ramp", "hex20", "nonlin_static_3d", {}, {}, ramp, (0., 0., -12000.), (0., 0., -300.))
    if "lin" in which:
        case("c_lin", "hex20", "lin_static_3d", {}, {}, None, (2000., 500., -1000.), (0., 0., -300.))
    if "lq" in which:
        case("c_lq", "hex8", "lin_static_3d", {}, dict(elem_hex8="LINE_QUAD"), None, (2000., 500., -1000.), (0., 0., -300.))
    if "nl" in which:
        case("c_nl", "hex20", "nonlin_static_3d", {}, {}, nonlin, (0., 0., -12000.), (0., 0., -300.))
