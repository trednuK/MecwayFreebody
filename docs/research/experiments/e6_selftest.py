# E6 self-test, no Mecway: shape functions and quadrature against analytic values, so that
# the statics reference and M3 cannot share an unnoticed table or node-order error.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_lib import *

NAT = {"hex8": [tuple(float(v) for v in q) for q in HEX20C[:8]],
       "hex20": [tuple(float(v) for v in q) for q in HEX20C],
       "tet4": [(0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,1.)],
       "wedge6": [(0.,0.,-1.),(1.,0.,-1.),(0.,1.,-1.),(0.,0.,1.),(1.,0.,1.),(0.,1.,1.)],
       "pyr5": [(-1.,-1.,0.),(1.,-1.,0.),(1.,1.,0.),(-1.,1.,0.),(0.,0.,.999999)]}


def quad(shape, base):
    c = np.array(NAT[base]); out = [tuple(p) for p in c]
    for a, b in MID[shape]:
        out.append(tuple((c[a]+c[b])/2))
    return out


NAT["hex20"] = quad("hex20", "hex8"); NAT["tet10"] = quad("tet10", "tet4")
NAT["wedge15"] = quad("wedge15", "wedge6"); NAT["pyr13"] = quad("pyr13", "pyr5")
rng = np.random.default_rng(1)
ok = True


def chk(name, val, tol=1e-9):
    global ok
    good = abs(val) < tol
    ok = ok and good
    print("  %-46s %.2e %s" % (name, val, "" if good else "FAIL"))


for sh, pts in NAT.items():
    X = np.array(pts)
    # Kronecker delta at the nodes (pyramid apex slightly below t=1: rational term)
    A = np.array([SF6[sh](*p)[0] for p in pts])
    chk(sh+" delta at nodes", np.abs(A-np.eye(len(pts))).max(), 2e-5 if sh.startswith("pyr") else 1e-12)
    # partition of unity, linear precision and derivative of the geometry, inside
    N, dN, w = vol_tab(sh)
    chk(sh+" partition of unity", np.abs(N.sum(axis=1)-1).max())
    Xi = X.copy()
    if sh.startswith("pyr"):
        Xi[4] = (0, 0, 1)
        if sh == "pyr13":
            c = Xi[:5]
            for k, (a, b) in enumerate(MID[sh]):
                Xi[5+k] = (c[a]+c[b])/2
    pts_q = np.array([q for q, _ in rule_volume(sh)])
    chk(sh+" linear precision x", np.abs(N @ Xi - pts_q).max())
    J = np.einsum("ji,qjk->qik", Xi, dN)
    chk(sh+" Jacobian = I", np.abs(J-np.eye(3)).max())

# volume, centroid, closed surface on randomly disturbed elements
for sh in NAT:
    fam = family(sh); nc = NC[sh]
    Xc = {"hex": np.array(HEX20C[:8], float), "tet": np.array(NAT["tet4"]),
          "wedge": np.array(NAT["wedge6"]), "pyr": np.array([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),(0,0,1.)])}[fam]
    Xc = Xc + rng.normal(0, .06, Xc.shape)
    Xe = list(Xc)
    if sh in MID:
        Xe += [(Xc[a]+Xc[b])/2 + rng.normal(0, .02, 3) for a, b in MID[sh]]
    Xe = np.array(Xe)
    V, Q = vol_integrate(sh, Xe)
    In = np.zeros(3); Id = 0.; Iq = np.zeros(3)
    for f in range(len(FACES[fam])):
        ss, idx = solid_face(sh, f)
        x, da = surf_points(ss, Xe[idx])
        In = In + da.sum(axis=0)
        Id += np.einsum("qi,qi->", x, da)/3
        Iq = Iq + np.einsum("qi,qi,qj->j", x, da, x)/4   # div(x_j x) = 4 x_j
    chk(sh+" closed surface: int n dA", np.linalg.norm(In), 1e-11)
    chk(sh+" divergence: V = int x.n dA/3", V-Id, 2e-5 if sh.startswith("pyr") else 1e-10)
    chk(sh+" first moment via surface", np.linalg.norm(Q-Iq), 3e-5 if sh.startswith("pyr") else 1e-10)

print("analytic unit shapes")
Xp = np.array([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),(0,0,1.)])
V, Q = vol_integrate("pyr5", Xp)
chk("pyr5 V = 4/3", V-4/3); chk("pyr5 centroid z = 1/4", Q[2]/V-.25)
Xw = np.array(NAT["wedge6"])
V, Q = vol_integrate("wedge6", Xw)
chk("wedge6 V = 1", V-1); chk("wedge6 centroid x = 1/3", Q[0]/V-1/3)
print("ALL OK" if ok else "SOME FAILED")
