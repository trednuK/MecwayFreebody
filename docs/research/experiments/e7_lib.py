# Experiment E7: cut forces out of Code-Aster results. Research code, not the product.
# Self-made models only. Mesh in Aster format (as the bridge writes it), own statics as the
# reference: per region (left of the selection, selection, right of it) the consistent nodal
# load from own quadrature. CPython 3 with numpy. No dependency on Mecway.
import json, os, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
WD = os.path.join(ROOT, "WorkDir", "exp7")
RUN_ASTER = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4", "bin",
                         "run_aster.bat")
L, B, H = .2, .02, .04
E0, NU, RHO = 210e9, .3, 7850.
GZ = np.array([0, 0, -9.81])
TIPF = np.array([2000., 500., -1000.])
TOPF = np.array([0., 800., 0.])


# ---- shape functions: natural coordinates, N and dN/d(natural) -----------------------------
HEX20C = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1),
          (0,-1,-1),(1,0,-1),(0,1,-1),(-1,0,-1),
          (-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),
          (0,-1,1),(1,0,1),(0,1,1),(-1,0,1)]


def sf_hexa8(r, s, t):
    c = HEX20C[:8]
    N = np.array([(1+a*r)*(1+b*s)*(1+d*t)/8 for a, b, d in c])
    dN = np.array([[a*(1+b*s)*(1+d*t)/8, b*(1+a*r)*(1+d*t)/8, d*(1+a*r)*(1+b*s)/8] for a, b, d in c])
    return N, dN


def sf_hexa20(r, s, t):
    N = np.zeros(20); dN = np.zeros((20, 3))
    for i, (a, b, c) in enumerate(HEX20C):
        if a and b and c:
            N[i] = (1+a*r)*(1+b*s)*(1+c*t)*(a*r+b*s+c*t-2)/8
            dN[i] = [a*(1+b*s)*(1+c*t)*(2*a*r+b*s+c*t-1)/8, b*(1+a*r)*(1+c*t)*(a*r+2*b*s+c*t-1)/8,
                     c*(1+a*r)*(1+b*s)*(a*r+b*s+2*c*t-1)/8]
        elif a == 0:
            N[i] = (1-r*r)*(1+b*s)*(1+c*t)/4
            dN[i] = [-2*r*(1+b*s)*(1+c*t)/4, b*(1-r*r)*(1+c*t)/4, c*(1-r*r)*(1+b*s)/4]
        elif b == 0:
            N[i] = (1-s*s)*(1+a*r)*(1+c*t)/4
            dN[i] = [a*(1-s*s)*(1+c*t)/4, -2*s*(1+a*r)*(1+c*t)/4, c*(1-s*s)*(1+a*r)/4]
        else:
            N[i] = (1-t*t)*(1+a*r)*(1+b*s)/4
            dN[i] = [a*(1-t*t)*(1+b*s)/4, b*(1-t*t)*(1+a*r)/4, -2*t*(1+a*r)*(1+b*s)/4]
    return N, dN


def sf_tetra10(r, s, t):
    Lm = [1-r-s-t, r, s, t]
    dL = np.array([[-1, -1, -1], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    pairs = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
    N = [Lm[i]*(2*Lm[i]-1) for i in range(4)] + [4*Lm[a]*Lm[b] for a, b in pairs]
    dN = [(4*Lm[i]-1)*dL[i] for i in range(4)] + [4*(Lm[a]*dL[b]+Lm[b]*dL[a]) for a, b in pairs]
    return np.array(N), np.array(dN)


def sf_penta15(r, s, t):
    # triangle coordinates l0 = 1-r-s, l1 = r, l2 = s; t in [-1, 1]
    # 0-2 bottom, 3-5 top, 6-8 bottom edges 01 12 20, 9-11 verticals, 12-14 top edges
    Lm = [1-r-s, r, s]
    dL = np.array([[-1, -1.], [1, 0], [0, 1]])
    N = np.zeros(15); dN = np.zeros((15, 3))
    for i in range(3):
        l = Lm[i]
        N[i] = l*(1-t)*(2*l-t-2)/2
        dN[i, :2] = dL[i]*(1-t)*(4*l-t-2)/2
        dN[i, 2] = l*(-(2*l-t-2)-(1-t))/2
        N[i+3] = l*(1+t)*(2*l+t-2)/2
        dN[i+3, :2] = dL[i]*(1+t)*(4*l+t-2)/2
        dN[i+3, 2] = l*((2*l+t-2)+(1+t))/2
        N[i+9] = l*(1-t*t)
        dN[i+9, :2] = dL[i]*(1-t*t)
        dN[i+9, 2] = -2*t*l
    for i, (a, b) in enumerate([(0, 1), (1, 2), (2, 0)]):
        q = Lm[a]*Lm[b]; dq = Lm[a]*dL[b]+Lm[b]*dL[a]
        N[i+6] = 2*q*(1-t)
        dN[i+6, :2] = 2*dq*(1-t)
        dN[i+6, 2] = -2*q
        N[i+12] = 2*q*(1+t)
        dN[i+12, :2] = 2*dq*(1+t)
        dN[i+12, 2] = 2*q
    return N, dN


def sf_quad(nn):
    def f(a, b):
        cor = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        if nn == 4:
            N = np.array([(1+x*a)*(1+y*b)/4 for x, y in cor])
            dN = np.array([[x*(1+y*b)/4, y*(1+x*a)/4] for x, y in cor])
            return N, dN
        N = np.zeros(nn); dN = np.zeros((nn, 2))
        for i, (x, y) in enumerate(cor):
            N[i] = (1+x*a)*(1+y*b)*(x*a+y*b-1)/4
            dN[i] = [x*(1+y*b)*(2*x*a+y*b)/4, y*(1+x*a)*(x*a+2*y*b)/4]
        mid = [(0, -1), (1, 0), (0, 1), (-1, 0)]
        for i, (x, y) in enumerate(mid):
            if x == 0:
                N[4+i] = (1-a*a)*(1+y*b)/2
                dN[4+i] = [-a*(1+y*b), y*(1-a*a)/2]
            else:
                N[4+i] = (1+x*a)*(1-b*b)/2
                dN[4+i] = [x*(1-b*b)/2, -b*(1+x*a)]
        return N, dN
    return f


def sf_tri(nn):
    def f(a, b):
        Lm = [1-a-b, a, b]
        dL = np.array([[-1, -1.], [1, 0], [0, 1]])
        if nn == 3:
            return np.array(Lm), dL
        pairs = [(0, 1), (1, 2), (2, 0)]
        N = [Lm[i]*(2*Lm[i]-1) for i in range(3)] + [4*Lm[p]*Lm[q] for p, q in pairs]
        dN = [(4*Lm[i]-1)*dL[i] for i in range(3)] + [4*(Lm[p]*dL[q]+Lm[q]*dL[p]) for p, q in pairs]
        return np.array(N), np.array(dN)
    return f


def _gl(n):
    return np.polynomial.legendre.leggauss(n)


def rule_hex(n):
    g, w = _gl(n)
    return [((a, b, c), wa*wb*wc) for a, wa in zip(g, w) for b, wb in zip(g, w) for c, wc in zip(g, w)]


def rule_tet(n=6):
    g, w = _gl(n); pts = []
    for a, wa in zip(g, w):
        for b, wb in zip(g, w):
            for c, wc in zip(g, w):
                u, v, x = (a+1)/2, (b+1)/2, (c+1)/2
                pts.append(((u, v*(1-u), x*(1-u)*(1-v)), wa*wb*wc/8*(1-u)**2*(1-v)))
    return pts


def rule_penta(n=6):
    g, w = _gl(n); pts = []
    for a, wa in zip(g, w):
        for b, wb in zip(g, w):
            u, v = (a+1)/2, (b+1)/2
            for c, wc in zip(g, w):
                pts.append(((u, v*(1-u), c), wa*wb*wc/4*(1-u)))
    return pts


def rule_quad(n=6):
    g, w = _gl(n)
    return [((a, b), wa*wb) for a, wa in zip(g, w) for b, wb in zip(g, w)]


def rule_tri(n=6):
    g, w = _gl(n); pts = []
    for a, wa in zip(g, w):
        for b, wb in zip(g, w):
            u, v = (a+1)/2, (b+1)/2
            pts.append(((u, v*(1-u)), wa*wb/4*(1-u)))
    return pts


VOL = {"HEXA8": (sf_hexa8, lambda: rule_hex(6)), "HEXA20": (sf_hexa20, lambda: rule_hex(6)),
       "TETRA10": (sf_tetra10, lambda: rule_tet(6)), "PENTA15": (sf_penta15, lambda: rule_penta(6))}
SURF = {"QUAD4": (sf_quad(4), lambda: rule_quad(4)), "QUAD8": (sf_quad(8), lambda: rule_quad(6)),
        "TRIA3": (sf_tri(3), lambda: rule_tri(4)), "TRIA6": (sf_tri(6), lambda: rule_tri(6))}
_TAB = {}


def table(kind, typ):
    k = (kind, typ)
    if k not in _TAB:
        fn, rule = (VOL if kind == "v" else SURF)[typ]
        q = rule()
        N = []; dN = []
        for p, w in q:
            a, b = fn(*p); N.append(a); dN.append(b)
        _TAB[k] = (np.array(N), np.array(dN), np.array([w for p, w in q]))
    return _TAB[k]


# ---- mesh -----------------------------------------------------------------------------------
HEX_F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
TET_F = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)]
TET_SPLIT = [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]
HEXMID = {frozenset(p): 8+i for i, p in enumerate(
    [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7), (4, 5), (5, 6), (6, 7), (7, 4)])}
TETMID = {frozenset(p): 4+i for i, p in enumerate([(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)])}
PEN_F = [(0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5), (0, 2, 1), (3, 4, 5)]
PENMID = {frozenset(p): q for p, q in [((0, 1), 6), ((1, 2), 7), ((2, 0), 8), ((0, 3), 9), ((1, 4), 10),
                                       ((2, 5), 11), ((3, 4), 12), ((4, 5), 13), ((5, 3), 14)]}


class Mesh:
    def __init__(self):
        self.key = {}; self.xyz = []; self.cells = []; self.ma = {}; self.no = {}
        self.region = {}     # volume or structural cell id -> 0 left, 1 selection, 2 right

    def node(self, x, y, z):
        k = (round(x*1e10), round(y*1e10), round(z*1e10))
        if k not in self.key:
            self.xyz.append((x, y, z)); self.key[k] = len(self.xyz)
        return self.key[k]

    def add(self, typ, nodes, region=None):
        self.cells.append((typ, list(nodes)))
        cid = len(self.cells)
        if region is not None:
            self.region[cid] = region
        return cid

    def X(self):
        return np.array(self.xyz)


def faces_of(typ):
    if typ.startswith("HEXA"):
        return HEX_F, (HEXMID if typ == "HEXA20" else None)
    if typ.startswith("TETRA"):
        return TET_F, (TETMID if typ == "TETRA10" else None)
    return PEN_F, (PENMID if typ == "PENTA15" else None)


def face_cell(typ, nds, f):
    """Skin cell (Aster node order, normal outward) of local face f."""
    fs, mid = faces_of(typ)
    c = fs[f]; out = [nds[i] for i in c]
    if mid is None:
        return ("QUAD4" if len(c) == 4 else "TRIA3"), out
    out += [nds[mid[frozenset((c[i], c[(i+1) % len(c)]))]] for i in range(len(c))]
    return ("QUAD8" if len(c) == 4 else "TRIA6"), out


def free_faces(m):
    """{sorted corners: (cell id, local face)} of faces that belong to one volume cell."""
    seen = {}
    for cid in m.region:
        typ, nds = m.cells[cid-1]
        if typ not in VOL:
            continue
        for f, c in enumerate(faces_of(typ)[0]):
            k = tuple(sorted(nds[i] for i in c))
            if k in seen:
                seen[k] = None
            else:
                seen[k] = (cid, f)
    return {k: v for k, v in seen.items() if v is not None}


def skin(m, name, where, side_of=None):
    """Add skin cells on the free faces with where(centre of the corners)."""
    X = m.X(); ids = []
    for k, (cid, f) in m._free.items():
        if where(X[np.array(k)-1].mean(axis=0)):
            typ, nds = m.cells[cid-1]
            t, conn = face_cell(typ, nds, f)
            s = m.add(t, conn)
            m.parent[s] = cid
            ids.append(s)
    m.ma[name] = ids
    return ids


def block(shape, dims, distort=0.0, select=None):
    """Block in cells (nx, ny, nz); shape HEXA8, HEXA20, TETRA10 or MIX (HEXA20 + PENTA15, cells
    interleaved in the file). select(i, j, k) gives the region; default middle half in x."""
    nx, ny, nz = dims
    d = np.array([L/nx, B/ny, H/nz])
    m = Mesh(); m.parent = {}
    sel = select or (lambda i, j, k: 0 if i < nx//4 else (1 if i < 3*nx//4 else 2))
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                r = sel(i, j, k)
                x0 = np.array((i*d[0], j*d[1], k*d[2]))
                nat = [x0+d*(np.array(q)+1)/2 for q in HEX20C]
                if shape == "HEXA8":
                    m.add("HEXA8", [m.node(*p) for p in nat[:8]], r)
                elif shape == "HEXA20" or (shape == "MIX" and (k+i) % 2 == 0):
                    m.add("HEXA20", [m.node(*p) for p in nat], r)
                elif shape == "MIX":
                    # column split along the x-z diagonal: two wedges, triangles on y = const;
                    # conformal only if the whole column splits, so it depends on (i, k) alone
                    # bottom triangle at y-, top at y+: corners c0 c1 c2 / c3(=7..) by hand
                    c = nat[:8]
                    for t in ((0, 4, 5, 3, 7, 6), (0, 5, 1, 3, 6, 2)):
                        v = [c[q] for q in t]
                        a, b, e = v[1]-v[0], v[2]-v[0], v[3]-v[0]
                        if np.linalg.det(np.array([a, b, e])) < 0:
                            v = [v[0], v[2], v[1], v[3], v[5], v[4]]
                        pts = list(v)
                        pts += [(v[0]+v[1])/2, (v[1]+v[2])/2, (v[2]+v[0])/2,
                                (v[0]+v[3])/2, (v[1]+v[4])/2, (v[2]+v[5])/2,
                                (v[3]+v[4])/2, (v[4]+v[5])/2, (v[5]+v[3])/2]
                        m.add("PENTA15", [m.node(*p) for p in pts], r)
                else:
                    c = nat[:8]
                    for t in TET_SPLIT:
                        v = [c[q] for q in t]
                        if np.linalg.det(np.array([v[1]-v[0], v[2]-v[0], v[3]-v[0]])) < 0:
                            v[1], v[2] = v[2], v[1]
                        pts = list(v)+[(v[0]+v[1])/2, (v[1]+v[2])/2, (v[2]+v[0])/2,
                                       (v[0]+v[3])/2, (v[1]+v[3])/2, (v[2]+v[3])/2]
                        m.add("TETRA10", [m.node(*p) for p in pts], r)
    if distort:
        X = m.X()
        f = np.sin(np.pi*X[:, 0]/L)*np.sin(np.pi*X[:, 1]/B)*np.sin(np.pi*X[:, 2]/H)
        g = np.sin(2*np.pi*X[:, 0]/L)*np.sin(2*np.pi*X[:, 1]/B)*np.sin(2*np.pi*X[:, 2]/H)
        m.xyz = [tuple(v) for v in np.column_stack(
            (X[:, 0]+distort*d[0]*f, X[:, 1]+distort*d[1]*g, X[:, 2]+distort*d[2]*f*g))]
    m._free = free_faces(m)
    return m


def groups_from_regions(m, side_skin=()):
    """Volume cells by region; cut nodes A (shared with region 0) and B (with region 2).
    side_skin: names of skin groups to split by the region of their parent."""
    S = [c for c, r in m.region.items() if r == 1]
    nod = {r: set() for r in (0, 1, 2)}
    for c, r in m.region.items():
        nod[r].update(m.cells[c-1][1])
    m.ma["S"] = S
    m.no["CUTA"] = sorted(nod[0] & nod[1])
    m.no["CUTB"] = sorted(nod[1] & nod[2])
    # skin cells next to S
    skS = [s for s, p in m.parent.items() if m.region.get(p) == 1]
    if skS:
        m.ma["S_SK"] = S + skS
    return m


def write_mail(path, m, groups=True):
    X = m.xyz; L_ = ["TITRE", "e7 self-made model", "FINSF", "COOR_3D"]
    for i, (x, y, z) in enumerate(X):
        L_.append("N%d %.17g %.17g %.17g" % (i+1, x, y, z))
    L_.append("FINSF")
    # blocks of equal type in file order, so a mixed mesh stays interleaved
    i = 0
    while i < len(m.cells):
        t = m.cells[i][0]; L_.append(t)
        while i < len(m.cells) and m.cells[i][0] == t:
            items = ["M%d" % (i+1)] + ["N%d" % n for n in m.cells[i][1]]
            line = items[0]
            for q in items[1:]:
                if len(line)+len(q)+1 > 78:
                    L_.append(line); line = " "
                line += " "+q
            L_.append(line); i += 1
        L_.append("FINSF")
    def grp(kw, name, ids, pre):
        L_.append(kw); L_.append(name); line = ""
        for q in ids:
            s = "%s%d" % (pre, q)
            if len(line)+len(s)+1 > 78:
                L_.append(line); line = ""
            line += " "+s
        L_.append(line); L_.append("FINSF")
    if groups:
        for n, ids in m.ma.items():
            if ids and n not in getattr(m, "free_ma", ()):
                grp("GROUP_MA", n, ids, "M")
        for n, ids in m.no.items():
            if ids and n not in getattr(m, "free_no", ()):
                grp("GROUP_NO", n, ids, "N")
    L_.append("FIN")
    open(path, "w", newline="\n").write("\n".join(L_)+"\n")


# ---- own statics ----------------------------------------------------------------------------
def nodal_gravity(m, g=GZ, rho=RHO, cells=None):
    """Consistent nodal gravity: dict typ -> vectorised; returns (nn, 3) array."""
    X = m.X(); F = np.zeros((len(X), 3))
    cells = list(m.region) if cells is None else cells
    bytype = {}
    for c in cells:
        bytype.setdefault(m.cells[c-1][0], []).append(c)
    for t, ids in bytype.items():
        if t not in VOL:
            continue
        N, dN, w = table("v", t)
        con = np.array([m.cells[c-1][1] for c in ids])-1
        Xe = X[con]                                    # ne nn 3
        J = np.einsum("enk,qnj->eqkj", Xe, dN)
        det = np.linalg.det(J)
        if det.min() <= 0:
            raise RuntimeError("negative jacobian in "+t)
        fe = np.einsum("qn,eq,q->en", N, det, w)        # ne nn
        np.add.at(F, con, rho*fe[:, :, None]*g)
    return F


def surf_vectors(typ, Xe):
    N, dN, w = table("s", typ)
    t1 = np.einsum("enk,qn->eqk", Xe, dN[:, :, 0])
    t2 = np.einsum("enk,qn->eqk", Xe, dN[:, :, 1])
    return N, w, np.cross(t1, t2)


def nodal_surface(m, ids, trac=None, pres=None, X=None, X0=None):
    """Consistent nodal load of a uniform traction or a pressure on surface cells. trac: per
    unit area in the reference geometry; pres: along -n on the geometry X (deformed if given)."""
    X = m.X() if X is None else X
    F = np.zeros((len(X), 3))
    bytype = {}
    for c in ids:
        bytype.setdefault(m.cells[c-1][0], []).append(c)
    for t, cs in bytype.items():
        con = np.array([m.cells[c-1][1] for c in cs])-1
        N, w, nv = surf_vectors(t, X[con])
        if trac is not None:
            da = np.linalg.norm(nv, axis=2)
            fe = np.einsum("qn,eq,q->en", N, da, w)
            np.add.at(F, con, fe[:, :, None]*np.array(trac))
        else:
            fe = -pres*np.einsum("qn,eqk,q->enk", N, nv, w)
            np.add.at(F, con, fe)
    return F


def surf_area(m, ids):
    X = m.X(); A = 0.
    for c in ids:
        t, nds = m.cells[c-1]
        N, w, nv = surf_vectors(t, X[np.array([nds])-1])
        A += float(np.sum(np.linalg.norm(nv, axis=2)[0]*w))
    return A


def sum_about(f, x, P, mom=None):
    """Resultant of nodal forces f at positions x about P, plus nodal moments."""
    r = x-P
    F = f.sum(axis=0); M = np.cross(r, f).sum(axis=0)
    if mom is not None:
        M = M+mom.sum(axis=0)
    return F, M


def ref_cuts(load_regions, x, P, mom_regions=None):
    """Exact action of the rest on S through cut A and cut B. load_regions: {region: nodal load}.
    Cut B: what hangs to the right. Cut A: minus everything to the right of cut A."""
    z = np.zeros_like(x)
    fR = load_regions.get(2, z); fS = load_regions.get(1, z)
    mR = (mom_regions or {}).get(2, z); mS = (mom_regions or {}).get(1, z)
    FB, MB = sum_about(fR, x, P["CUTB"], mR)
    FA, MA = sum_about(fR+fS, x, P["CUTA"], mR+mS)
    return {"CUTA": (-FA, -MA), "CUTB": (FB, MB)}


def errors(F, M, Fx, Mx, Lref):
    dF = np.linalg.norm(F-Fx); dM = np.linalg.norm(M-Mx)
    nF = np.linalg.norm(Fx); nM = np.linalg.norm(Mx)
    return dict(rawF=dF/nF if nF else float("inf"), rawM=dM/nM if nM else float("inf"),
                eF=dF/max(nF, nM/Lref), eM=dM/max(nM, nF*Lref), dF=dF, dM=dM)


# ---- Code-Aster run ---------------------------------------------------------------------------
def run_aster(tag, comm, mail=None, med_in=None, rmed_out=False, sel=None, base=None, base_in=None,
              ncpus=int(os.environ.get("E7_NCPUS", 4)), mem=int(os.environ.get("E7_MEM", 6000)), tlim=3000, wd=None):
    """Write the .comm and .export in WD and run; relative names only, so that no absolute
    path lands in the files. Returns a dict with wall time, status and file sizes."""
    wd = wd or WD
    os.makedirs(wd, exist_ok=True)
    open(os.path.join(wd, tag+".comm"), "w", newline="\n").write(comm)
    x = ["P time_limit %d" % tlim, "P memory_limit %d" % mem, "P mpi_nbcpu 1", "P ncpus %d" % ncpus,
         "F comm %s.comm D 1" % tag, "F mess %s.mess R 6" % tag, "F libr %s.json R 33" % tag,
         "F libr %s.npz R 34" % tag]
    if mail:
        x.append("F mail %s D 20" % mail)
    if med_in:
        x.append("F rmed %s D 81" % med_in)
    if rmed_out:
        x.append("F rmed %s.rmed R 80" % tag)
    if sel:
        x.append("F libr %s D 32" % sel)
    if base:
        os.makedirs(os.path.join(wd, base), exist_ok=True)
        x.append("R base %s R 0" % base)
    if base_in:
        x.append("R base %s D 0" % base_in)
    open(os.path.join(wd, tag+".export"), "w", newline="\n").write("\n".join(x)+"\n")
    for suf in (".json", ".npz", ".mess"):
        p = os.path.join(wd, tag+suf)
        if os.path.exists(p):
            os.remove(p)
    t0 = time.perf_counter()
    r = subprocess.run(["cmd", "/c", RUN_ASTER, tag+".export"], cwd=wd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    wall = time.perf_counter()-t0
    log = r.stdout.decode("utf-8", "replace")
    open(os.path.join(wd, tag+".log"), "w", encoding="utf-8").write(log)
    mess = ""
    p = os.path.join(wd, tag+".mess")
    if os.path.exists(p):
        mess = open(p, encoding="utf-8", errors="replace").read()
    ok = "FIN()" in mess or "fermeture" in mess.lower()
    errs = [ln.encode("ascii", "replace").decode().strip("? ") for ln in mess.splitlines()
            if "<F>" in ln or "<EXCEPTION>" in ln or "<S>" in ln][:6]
    out = dict(tag=tag, wall=wall, rc=r.returncode, errors=errs, ok=(r.returncode == 0 and not errs))
    jp = os.path.join(wd, tag+".json")
    out["data"] = json.load(open(jp)) if os.path.exists(jp) and os.path.getsize(jp) else None
    np_ = os.path.join(wd, tag+".npz")
    out["npz"] = np.load(np_) if os.path.exists(np_) and os.path.getsize(np_) else None
    return out


# Text put in every .comm: helpers that run inside Code-Aster.
HELP = r'''
import json, time as _t
import numpy as np
_T0 = _t.perf_counter()
OUT = {"times": {}, "tab": {}}
ARR = {}
def lap(name):
    global _T0
    OUT["times"][name] = _t.perf_counter()-_T0
    _T0 = _t.perf_counter()
def finish():
    json.dump(OUT, open("fort.33", "w"))
    with open("fort.34", "wb") as fh:
        np.savez(fh, **ARR)
def set_groups(mesh, remap_cells=False):
    """Selection given after the run: groups from unit 32 (1-based ids)."""
    sel = json.load(open("fort.32"))
    remap = None
    if sel.get("conn") and remap_cells:
        # mesh read back from the .rmed: cells sorted by type, so find them by their nodes
        # (the node numbers are checked against the file's coordinates in the driver)
        con = mesh.getConnectivity()
        delta = 1-min(min(c) for c in con)
        nn0 = sel.get("nn0", 10**9)
        idx = {tuple(sorted(q for q in c if q+delta <= nn0)): i for i, c in enumerate(con)}
        remap = {int(k): idx[tuple(sorted(q-delta for q in v))] for k, v in sel["conn"].items()}
    for n, ids in sel.get("ma", {}).items():
        mesh.setGroupOfCells(n, [remap[int(i)] if remap else int(i)-1 for i in ids])
    for n, ids in sel.get("no", {}).items():
        mesh.setGroupOfNodes(n, [int(i)-1 for i in ids])
    return sel
def node_array(field, mesh):
    """(nn, ncmp) array of a nodal field, in the components DX DY DZ DRX DRY DRZ; absent = 0."""
    sf = field.toSimpleFieldOnNodes()
    v, mask = sf.toNumpy()
    cmp_ = list(sf.getComponents())
    out = np.zeros((mesh.getNumberOfNodes(), 6))
    for i, c in enumerate(("DX", "DY", "DZ", "DRX", "DRY", "DRZ")):
        if c in cmp_:
            q = cmp_.index(c)
            out[:, i] = np.where(mask[:, q], v[:, q], 0.)
    return out
def tab_cut(R, cham, cut, P, rot, rank):
    kw = dict(MOMENT=("DRX", "DRY", "DRZ"), POINT=tuple(P), RESULTANTE=("DX", "DY", "DZ"))
    t = POST_RELEVE_T(ACTION=_F(OPERATION="EXTRACTION", INTITULE="c", RESULTAT=R, NOM_CHAM=cham,
                                GROUP_NO=cut, NUME_ORDRE=rank, **kw))
    d = t.EXTR_TABLE().values()
    keys = [k for k in d if k.startswith("RESULT") or k.startswith("MOMENT")]
    return {k: float(d[k][0]) for k in keys}
'''
