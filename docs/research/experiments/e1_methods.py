# Experiment E1: four ways to get the force and moment on a cut, against statics.
# All models are self-made blocks, solved by Mecway's internal solver.
#   M1 face integral of the averaged nodal stress
#   M2 face integral of the element-node stress of the selected side
#   M3 nodal forces from stress: integral of B^T sigma over the layer at the cut
#   M4 selection solved again with the cut nodes held at their displacement;
#      the reactions are the cut forces
# Reference: equilibrium with the external loads on the selection.
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fb_lib import *

wd = os.environ["FB_WORK"]; os.makedirs(wd, exist_ok=True)
RHO = 7850.0; GRAV = np.array([0, 0, -9.81])
L, B, H = .2, .02, .04
LOADS = (("TIPALL", (2000., 500., -1000.)), ("TIPTOP", (0., 800., 0.)))


def build(model, shape, n):
    nx, ny, nz = 10*n, 2*n, 4*n
    d = (L/nx, B/ny, H/nz)
    m = Mesh(); cells = {}
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                if model == "step" and i >= nx//2 and k >= nz//2:
                    continue     # thin part x > L/2, eccentric
                cells[(i, j, k)] = add_cell(m, (i*d[0], j*d[1], k*d[2]), d, shape)
    if os.environ.get("FB_DISTORT"):
        # smooth distortion that leaves the root, the tip and the outer faces in place
        a = float(os.environ["FB_DISTORT"])
        out = []
        for x, y, z in m.xyz:
            f = np.sin(np.pi*x/L)*np.sin(np.pi*y/B)*np.sin(np.pi*z/H)
            g = np.sin(2*np.pi*x/L)*np.sin(2*np.pi*y/B)*np.sin(2*np.pi*z/H)
            out.append((x+a*d[0]*f, y+a*d[1]*g, z+a*d[2]*f*g))
        m.xyz = out
    return m, cells, (nx, ny, nz), d


def selection(model, cells, dims):
    nx, ny, nz = dims
    S = []
    for (i, j, k), es in cells.items():
        if model in ("block", "step"):
            inside = i >= nx//2
        elif model == "mid":
            inside = nx//4 <= i < 3*nx//4
        elif model == "stair":
            inside = i >= nx//2 + (1 if k*2 >= nz else 0)*2*max(1, nx//20)
        if inside:
            S.extend(es)
    return S


def ext_on(m, S, faces_tipall, faces_tiptop):
    """Sum of external loads on S: (force list [(F, point)])."""
    S = set(S); pts = []
    # gravity
    for e in S:
        shape, nds = m.elems[e]
        X = np.array([m.X(n) for n in nds])
        for q, w in elem_rule(shape):
            N, dN = SF[shape](*q)
            J = X.T @ dN
            dV = np.linalg.det(J)*w
            pts.append((RHO*GRAV*dV, N @ X))
    for name, F in LOADS:
        faces = faces_tipall if name == "TIPALL" else faces_tiptop
        faces = [f for f in faces if f[0] in S]
        tot = sum(area(m, e, f) for e, f in faces)
        for e, f in faces:
            pts.append((np.array(F)*area(m, e, f)/tot, centre(m, e, f)))
    return pts


def area(m, e, f):
    shape, nds = m.elems[e]; X = np.array([m.X(n) for n in nds]); a = 0
    for p, w, dxi, de in face_points(shape, f):
        _, dN = SF[shape](*p)
        J = X.T @ dN
        a += np.linalg.norm(np.cross(J @ dxi, J @ de))*w
    return a


def centre(m, e, f):
    shape, nds = m.elems[e]; X = np.array([m.X(n) for n in nds]); a = 0; c = 0
    for p, w, dxi, de in face_points(shape, f):
        N, dN = SF[shape](*p)
        J = X.T @ dN
        da = np.linalg.norm(np.cross(J @ dxi, J @ de))*w
        a += da; c = c + da*(N @ X)
    return c/a


VARS = ["stressxx", "stressyy", "stresszz", "stressxy", "stressyz", "stresszx"]


class Sol:
    def __init__(self, m, path):
        r = read_results(path); self.m = m
        self.n_id = {int(n): i for i, n in enumerate(r["nids"]["stressxx"])}
        self.sn = np.column_stack([r["nv"][v] for v in VARS])
        self.u = {int(n): np.array([r["nv"]["displx"][i], r["nv"]["disply"][i], r["nv"]["displz"][i]])
                  for i, n in enumerate(r["nids"]["displx"])}
        self.se = {}
        pos = 0
        if "stressxx" not in r["eids"]:
            # CCX through Mecway: only nodal (averaged) stress is stored
            print("   no element-node stress: M2, M3 on the averaged stress")
            for e, (sh, nds) in m.elems.items():
                self.se[e] = np.array([self.sn[self.n_id[n]] for n in nds])
            return
        for e in r["eids"]["stressxx"]:
            e = int(e); k = len(m.elems[e][1])
            self.se[e] = np.column_stack([r["ev"][v][pos:pos+k] for v in VARS]); pos += k
        assert pos == len(r["ev"]["stressxx"])

    def elem_stress(self, e):
        return self.se[e]

    def nodal_stress(self, e):
        return np.array([self.sn[self.n_id[n]] for n in self.m.elems[e][1]])


def tens(s):
    return np.array([[s[0], s[3], s[5]], [s[3], s[1], s[4]], [s[5], s[4], s[2]]])


def face_integral(m, faces, stress_of):
    pts = []
    for e, f in faces:
        shape, nds = m.elems[e]; X = np.array([m.X(n) for n in nds]); Se = stress_of(e)
        for p, w, dxi, de in face_points(shape, f):
            N, dN = SF[shape](*p)
            J = X.T @ dN
            da = np.cross(J @ dxi, J @ de)*w
            pts.append((tens(N @ Se) @ da, N @ X))
    return pts


def nodal_forces_from_stress(m, S, cutnodes, stress_of, rule=elem_rule):
    R = {}
    cut = set(cutnodes)
    for e in S:
        shape, nds = m.elems[e]
        idx = [i for i, n in enumerate(nds) if n in cut]
        if not idx:
            continue
        X = np.array([m.X(n) for n in nds]); Se = stress_of(e)
        for q, w in rule(shape):
            N, dN = SF[shape](*q)
            J = X.T @ dN
            dNx = dN @ np.linalg.inv(J)
            dV = np.linalg.det(J)*w
            s = tens(N @ Se)
            for i in idx:
                R[nds[i]] = R.get(nds[i], 0) + (s @ dNx[i] - RHO*GRAV*N[i])*dV
    return R


def resultant(pts, P):
    F = sum(p[0] for p in pts); M = sum(np.cross(p[1]-P, p[0]) for p in pts)
    return F, M


def patches(m, faces):
    """Connected groups of cut faces (shared node)."""
    left = list(faces); out = []
    while left:
        grp = [left.pop()]
        nodes = set(m.elems[grp[0][0]][1][i] for i in face_nodes_local(m.elems[grp[0][0]][0], grp[0][1]))
        grew = True
        while grew:
            grew = False
            for x in list(left):
                n = set(m.elems[x[0]][1][i] for i in face_nodes_local(m.elems[x[0]][0], x[1]))
                if n & nodes:
                    nodes |= n; grp.append(x); left.remove(x); grew = True
        out.append((grp, nodes))
    return out


def run(model, shape, n):
    tag = "%s_%s_%d" % (model, shape, n)
    m, cells, dims, d = build(model, shape, n)
    tipx = (L if model != "step" else L)
    tipall = boundary_faces(m, lambda c: abs(c[0]-tipx) < 1e-9)
    tiptop = [f for f in tipall if centre(m, *f)[2] > (H/2 if model != "step" else H/4)]
    root = boundary_faces(m, lambda c: abs(c[0]) < 1e-9)
    p = os.path.join(wd, tag+".liml"); sol = os.path.join(wd, tag+"_sol.liml")
    write_liml(p, m, rho=RHO, gravity=GRAV, fixed_faces=root,
               forces=[("TIPALL", tipall, LOADS[0][1]), ("TIPTOP", tiptop, LOADS[1][1])])
    t = solve(p, sol)
    s = Sol(m, sol)
    # check: the mean of the element-node stress at a node equals the nodal stress
    acc = {}
    for e, (sh, nds) in m.elems.items():
        for i, nid in enumerate(nds):
            acc.setdefault(nid, []).append(s.se[e][i])
    chk = max(np.abs(np.mean(v, axis=0)-s.sn[s.n_id[k]]).max() for k, v in acc.items())
    S = selection(model, cells, dims)
    Sset = set(S)
    cf = cut_faces(m, S)
    # M4: solve the selection again with the cut nodes held
    cutn = set()
    for e, f in cf:
        sh, nds = m.elems[e]
        cutn.update(nds[i] for i in face_nodes_local(sh, f))
    # Mecway needs contiguous ids: renumber the selection into its own mesh
    m2 = Mesh(); emap = {}; nmap = {}
    for e in S:
        sh, nds = m.elems[e]
        ids = [m2.node(*m.xyz[n-1]) for n in nds]
        nmap.update(zip(nds, ids))
        emap[e] = m2.add(sh, ids)
    x = []
    for nid in sorted(cutn):
        n2 = nmap[nid]
        x.append('  <nodeselection name="C%d"><node nid="%d" /></nodeselection>' % (n2, n2))
        for c, v in enumerate(s.u[nid]):
            a = [0, 0, 0]; a[c] = 1
            x.append('  <displacement selection="C%d"><value>%s m</value><x>%d</x><y>%d</y><z>%d</z></displacement>'
                     % (n2, fmt(v), a[0], a[1], a[2]))
    p2 = os.path.join(wd, tag+"_sub.liml"); sol2 = os.path.join(wd, tag+"_sub_sol.liml")
    # the same loads as far as they act on the selection (force = total over the
    # whole load face, so scale when only a part of it lies in the selection)
    fs = []
    for name, faces, F in (("TIPALL", tipall, LOADS[0][1]), ("TIPTOP", tiptop, LOADS[1][1])):
        sub = [(emap[f[0]], f[1]) for f in faces if f[0] in Sset]
        if sub:
            share = sum(area(m, *f) for f in faces if f[0] in Sset)/sum(area(m, *f) for f in faces)
            fs.append((name, sub, tuple(share*v for v in F)))
    write_liml(p2, m2, rho=RHO, gravity=GRAV, forces=fs, extra=chr(10).join(x),
               fields=("displacement", "external force" if os.environ.get("FB_SOLVER") else "reaction force"))
    t2 = solve(p2, sol2)
    r2 = read_results(sol2)
    back = {v: k for k, v in nmap.items()}
    Rn = {}
    # CCX through Mecway stores its nodal forces as "external force", at all nodes
    rv = "externalforce" if "externalforcex" in r2["nv"] else "reactionforce"
    for i, nid in enumerate(r2["nids"][rv+"x"]):
        Rn[back[int(nid)]] = np.array([r2["nv"][rv+c][i] for c in "xyz"])
    # M4L: only the layer of elements at the cut, all its nodes held; no loads but gravity
    layer = [e for e in S if set(m.elems[e][1]) & cutn]
    m3 = Mesh(); nmap3 = {}
    for e in layer:
        sh, nds = m.elems[e]
        ids = [m3.node(*m.xyz[n-1]) for n in nds]
        nmap3.update(zip(nds, ids)); m3.add(sh, ids)
    x3 = []
    for nid in sorted(nmap3):
        n3 = nmap3[nid]
        x3.append('  <nodeselection name="C%d"><node nid="%d" /></nodeselection>' % (n3, n3))
        for c, v in enumerate(s.u[nid]):
            a = [0, 0, 0]; a[c] = 1
            x3.append('  <displacement selection="C%d"><value>%s m</value><x>%d</x><y>%d</y><z>%d</z></displacement>'
                      % (n3, fmt(v), a[0], a[1], a[2]))
    p3 = os.path.join(wd, tag+"_lay.liml"); sol3 = os.path.join(wd, tag+"_lay_sol.liml")
    write_liml(p3, m3, rho=RHO, gravity=GRAV, extra=chr(10).join(x3),
               fields=("displacement", "external force" if os.environ.get("FB_SOLVER") else "reaction force"))
    t3 = solve(p3, sol3)
    r3 = read_results(sol3)
    back3 = {v: k for k, v in nmap3.items()}
    rv3 = "externalforce" if "externalforcex" in r3["nv"] else "reactionforce"
    Rl = {}
    for i, nid in enumerate(r3["nids"][rv3+"x"]):
        Rl[back3[int(nid)]] = np.array([r3["nv"][rv3+c][i] for c in "xyz"])
    print("   layer: %d elements, %d nodes, solve %.1fs" % (len(layer), len(nmap3), t3))
    rows = []
    for grp, nodes in patches(m, cf):
        # centroid of the patch as summation point
        A = sum(area(m, *f) for f in grp); P = sum(area(m, *f)*centre(m, *f) for f in grp)/A
        # exact: what the rest does to S through this patch
        if model == "mid":
            x_pat = P[0]
            right = [e for e in m.elems if np.mean([m.X(q)[0] for q in m.elems[e][1]]) > x_pat]
            pts = ext_on(m, right, tipall, tiptop)
            sign = -1 if x_pat < L/2 else 1
            Fx, Mx = resultant(pts, P); Fx, Mx = sign*Fx, sign*Mx
        else:
            Fx, Mx = resultant(ext_on(m, S, tipall, tiptop), P); Fx, Mx = -Fx, -Mx
        res = {}
        res["M1"] = resultant(face_integral(m, grp, s.nodal_stress), P)
        res["M2"] = resultant(face_integral(m, grp, s.elem_stress), P)
        R3 = nodal_forces_from_stress(m, S, nodes, s.elem_stress)
        res["M3"] = resultant([(R3[k], m.X(k)) for k in nodes], P)
        R3o = nodal_forces_from_stress(m, S, nodes, s.elem_stress, own_rule)
        res["M3own"] = resultant([(R3o[k], m.X(k)) for k in nodes], P)
        res["M4"] = resultant([(Rn[k], m.X(k)) for k in nodes], P)
        res["M4L"] = resultant([(Rl[k], m.X(k)) for k in nodes], P)
        for k, (Fm, Mm) in res.items():
            rows.append(dict(model=model, shape=shape, n=n, nel=len(m.elems), patch=round(float(P[0]), 4), method=k,
                             eF=float(np.linalg.norm(Fm-Fx)/np.linalg.norm(Fx)),
                             eM=float(np.linalg.norm(Mm-Mx)/np.linalg.norm(Mx)),
                             Fexact=[float(v) for v in Fx], Mexact=[float(v) for v in Mx],
                             F=[float(v) for v in Fm], M=[float(v) for v in Mm]))
    print("%-20s el=%6d cutn=%5d solve %.1fs sub %.1fs  avgchk %.2e" % (tag, len(m.elems), len(cutn), t, t2, chk), flush=True)
    for r in rows:
        print("   x=%.3f %s eF=%.2e eM=%.2e" % (r["patch"], r["method"], r["eF"], r["eM"]), flush=True)
    return rows


if __name__ == "__main__":
    cases = [tuple(c.split(":")) for c in sys.argv[1:]]
    out = []
    for model, shape, n in cases:
        out += run(model, shape, int(n))
    fn = os.path.join(wd, "e1_%d.json" % int(time.time()))
    json.dump(out, open(fn, "w"))
    print(fn)
