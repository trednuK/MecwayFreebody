# Experiment E2: shell cantilever cut across, and a beam. Selection solved again with the
# cut nodes held in displacement AND rotation; compare the reactions with statics.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fb_lib import *

wd = os.environ["FB_WORK"]; os.makedirs(wd, exist_ok=True)
L, W_, T = .2, .04, .005
F_TIP = np.array([300., 200., -100.])


def write(path, nodes, elems, fixed, tipnodes, F, extra="", geo="plate"):
    x = ['<?xml version="1.0" encoding="utf-8"?>', '<liml version="34">', '  <analysis type="S30" />']
    for i, p in enumerate(nodes):
        x.append('  <node nid="%d" x="%s" y="%s" z="%s" />' % (i+1, fmt(p[0]), fmt(p[1]), fmt(p[2])))
    x.append('  <elset name="P" material="M" colorrgb="00C800">')
    for i, (sh, n) in enumerate(elems):
        x.append('    <elem eid="%d" shape="%s" nodes="%s" />' % (i+1, sh, " ".join(map(str, n))))
    x.append('  </elset>')
    g = ('<geometric type="Plate" thickness="%s m" />' % fmt(T)) if geo == "plate" else \
        ('<geometric type="RectBar" recta="0.02 m" rectb="0.01 m" />')
    x.append('  <mat name="M">' + g + '<mechanical type="Isotropic" youngsmodulus="210000000000 Pa" poissonratio="0.3" /></mat>')
    if fixed:
        x.append('  <nodeselection name="ROOT">' + "".join('<node nid="%d" />' % n for n in fixed) + '</nodeselection>')
        x.append('  <fixed selection="ROOT" />')
    if tipnodes:
        x.append('  <nodeselection name="TIP">' + "".join('<node nid="%d" />' % n for n in tipnodes) + '</nodeselection>')
        x.append('  <force selection="TIP"><x>%s N</x><y>%s N</y><z>%s N</z></force>' % tuple(fmt(v) for v in F))
    if extra:
        x.append(extra)
    for f, u in (("displacement", "m"), ("rotation", "rad"), ("reaction force", "N"), ("reaction moment", "N.m")):
        x.append('  <fieldvariable name="%s" displayunit="%s" expanded="true" />' % (f, u))
    x.append('</liml>')
    io.open(path, "w", encoding="ascii", newline="\n").write("\n".join(x))


def mesh_shell(shape, nx, ny):
    key = {}; nodes = []

    def nd(p):
        k = (round(p[0]*1e9), round(p[1]*1e9), round(p[2]*1e9))
        if k not in key:
            nodes.append(p); key[k] = len(nodes)
        return key[k]
    els = []; centr = []
    dx, dy = L/nx, W_/ny
    for i in range(nx):
        for j in range(ny):
            c = [(i*dx, j*dy, 0.), ((i+1)*dx, j*dy, 0.), ((i+1)*dx, (j+1)*dy, 0.), (i*dx, (j+1)*dy, 0.)]
            if shape == "quad4":
                n = [nd(p) for p in c]
            else:
                m = [tuple((np.array(c[a])+np.array(c[(a+1) % 4]))/2) for a in range(4)]
                n = [nd(c[0]), nd(m[0]), nd(c[1]), nd(m[1]), nd(c[2]), nd(m[2]), nd(c[3]), nd(m[3])]
            els.append((shape, n)); centr.append((i+.5)*dx)
    return nodes, els, np.array(centr)


def mesh_beam(nx):
    nodes = [(i*L/nx, 0., 0.) for i in range(nx+1)]
    els = [("line2", [i+1, i+2]) for i in range(nx)]
    return nodes, els, np.array([(i+.5)*L/nx for i in range(nx)])


def run(shape, nx, ny):
    tag = "sh_%s_%d" % (shape, nx)
    nodes, els, cx = mesh_beam(nx) if shape == "line2" else mesh_shell(shape, nx, ny)
    geo = "bar" if shape == "line2" else "plate"
    root = [i+1 for i, p in enumerate(nodes) if abs(p[0]) < 1e-9]
    tip = [i+1 for i, p in enumerate(nodes) if abs(p[0]-L) < 1e-9]
    p = os.path.join(wd, tag+".liml"); s = os.path.join(wd, tag+"_sol.liml")
    # clamp: all six DOFs of the root nodes (<fixed> on shell nodes did not hold, see report)
    hold = ['  <nodeselection name="ROOT">' + "".join('<node nid="%d" />' % n for n in root) + '</nodeselection>']
    for d in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        hold.append('  <displacement selection="ROOT"><value>0 m</value><x>%d</x><y>%d</y><z>%d</z></displacement>' % d)
        hold.append('  <noderotation selection="ROOT"><value>0 rad</value><x>%d</x><y>%d</y><z>%d</z></noderotation>' % d)
    write(p, nodes, els, None, tip, F_TIP, extra=chr(10).join(hold), geo=geo)
    solve(p, s)
    r = read_results(s)
    print(tag, sorted(r["nv"]))
    nid = {v: {int(n): r["nv"][v][i] for i, n in enumerate(r["nids"][v])} for v in r["nv"]}
    # selection: right half; rebuild with new numbers
    # selection between two cuts, so that each cut is a real test and not only
    # the global equilibrium of the sub-model
    X1, X2 = L/2, 3*L/4
    S = [e for e, c in enumerate(cx) if X1 < c < X2]
    cut = [i+1 for i, p_ in enumerate(nodes) if abs(p_[0]-X1) < 1e-9 or abs(p_[0]-X2) < 1e-9]
    used = sorted({n for e in S for n in els[e][1]})
    mp = {n: i+1 for i, n in enumerate(used)}
    n2 = [nodes[n-1] for n in used]
    e2 = [(els[e][0], [mp[n] for n in els[e][1]]) for e in S]
    x = []
    for n in cut:
        q = mp[n]
        x.append('  <nodeselection name="C%d"><node nid="%d" /></nodeselection>' % (q, q))
        for c, (a, b) in enumerate(zip("xyz", ("rotx", "roty", "rotz"))):
            d = [0, 0, 0]; d[c] = 1
            x.append('  <displacement selection="C%d"><value>%s m</value><x>%d</x><y>%d</y><z>%d</z></displacement>'
                     % (q, fmt(nid["displ"+a][n]), d[0], d[1], d[2]))
            x.append('  <noderotation selection="C%d"><value>%s rad</value><x>%d</x><y>%d</y><z>%d</z></noderotation>'
                     % (q, fmt(nid.get(b, {}).get(n, 0.)), d[0], d[1], d[2]))
    p2 = os.path.join(wd, tag+"_sub.liml"); s2 = os.path.join(wd, tag+"_sub_sol.liml")
    write(p2, n2, e2, None, None, F_TIP, extra=chr(10).join(x), geo=geo)
    solve(p2, s2)
    r2 = read_results(s2)
    R = {v: {int(n): r2["nv"][v][i] for i, n in enumerate(r2["nids"][v])} for v in r2["nv"]}
    back = {v: k for k, v in mp.items()}
    Ptip = np.mean([np.array(nodes[n-1]) for n in tip], axis=0)
    for xc, sign in ((X1, -1), (X2, 1)):
        nn = [n for n in cut if abs(nodes[n-1][0]-xc) < 1e-9]
        P = np.mean([np.array(nodes[n-1]) for n in nn], axis=0)
        Fc = np.zeros(3); Mc = np.zeros(3)
        for n in nn:
            q = mp[n]
            f = np.array([R["reactionforce"+c][q] for c in "xyz"])
            mm = np.array([R["reactionmom"+c].get(q, 0.) for c in "xyz"])
            Fc += f; Mc += np.cross(np.array(nodes[n-1])-P, f)+mm
        # statics: the part to the right of the cut carries the tip load
        Fx = sign*F_TIP; Mx = sign*np.cross(Ptip-P, F_TIP)
        print("  x=%.3f" % xc, "F", np.round(Fc, 6), "exact", Fx, "eF %.2e" % (np.linalg.norm(Fc-Fx)/np.linalg.norm(Fx)))
        print("         M", np.round(Mc, 6), "exact", Mx, "eM %.2e" % (np.linalg.norm(Mc-Mx)/np.linalg.norm(Mx)))


for a in sys.argv[1:]:
    sh, nx, ny = a.split(":")
    run(sh, int(nx), int(ny))
