# Experiment E6: shared code. Research code, not the product. Self-made models only.
# Generic model (solid + shell + beam), node-based cut detection, exact statics by
# quadrature, own solve runner. Imports fb_lib; fb_lib, e1 and e2 stay unchanged.
#
# Sign convention. R is the reaction on the sub-model: the force the rest of the model
# puts on the selection S through the cut. With O_k a far-side part without support:
#   R_k = sum of the external loads on O_k.
# When O_k holds the support: R_k = -(sum of the external loads on everything but O_k).
import ctypes, ctypes.wintypes as W, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fb_lib import *

WD = os.environ.get("FB_WORK", "")
E_PA = 210000000000
NU = 0.3
RHO = 7850.0


# ---- elements: tables in Mecway order -----------------------------------------------
MID = {"hex20": [(0,1),(1,2),(2,3),(3,0),(0,4),(1,5),(2,6),(3,7),(4,5),(5,6),(6,7),(7,4)],
       "wedge15": [(0,1),(1,2),(2,0),(0,3),(1,4),(2,5),(3,4),(4,5),(5,3)],
       "pyr13": [(0,1),(1,2),(2,3),(3,0),(0,4),(1,4),(2,4),(3,4)],
       "tet10": [(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)]}
NC = {"hex8": 8, "hex20": 8, "wedge6": 6, "wedge15": 6, "pyr5": 5, "pyr13": 5, "tet4": 4, "tet10": 4}
FACES = {"hex": [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)],
         "wedge": [(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)],
         "tet": [(0,2,1),(0,1,3),(1,2,3),(0,3,2)],
         "pyr": [(0,1,4),(1,2,4),(2,3,4),(3,0,4),(0,3,2,1)]}
SHELL = ("quad4", "quad8", "tri3", "tri6")
LINE = ("line2",)


def family(shape):
    return re.match(r"[a-z]+", shape).group(0)


def mid_index(shape, a, b):
    for i, (p, q) in enumerate(MID[shape]):
        if (p, q) == (a, b) or (q, p) == (a, b):
            return NC[shape]+i
    raise KeyError((shape, a, b))


def solid_face(shape, f):
    """(surface shape, local node indices in alternating order) of face f of a solid."""
    c = FACES[family(shape)][f]
    if shape in MID:
        idx = []
        for i in range(len(c)):
            idx += [c[i], mid_index(shape, c[i], c[(i+1) % len(c)])]
        return ("quad8" if len(c) == 4 else "tri6"), idx
    return ("quad4" if len(c) == 4 else "tri3"), list(c)


# ---- shape functions. Derivatives by complex step: exact to rounding, also for the
# rational pyramid functions -------------------------------------------------------
def N_wedge6(r, s, t):
    L = [1-r-s, r, s]
    return [l*(1-t)/2 for l in L] + [l*(1+t)/2 for l in L]


def N_wedge15(r, s, t):
    L = [1-r-s, r, s]
    N = [l*(1-t)*(2*l-t-2)/2 for l in L] + [l*(1+t)*(2*l+t-2)/2 for l in L]
    for a, b in ((0,1),(1,2),(2,0)):
        N.append(2*L[a]*L[b]*(1-t))
    for a in range(3):
        N.append(L[a]*(1-t*t))
    for a, b in ((0,1),(1,2),(2,0)):
        N.append(2*L[a]*L[b]*(1+t))
    return N


BASE = ((-1,-1),(1,-1),(1,1),(-1,1))


def N_pyr5(r, s, t):
    q = r*s*t/(1-t)
    return [((1+a*r)*(1+b*s)-t+a*b*q)/4 for a, b in BASE] + [t]


def N_pyr13(r, s, t):
    h = 1-t
    q = r*s*t/h
    N = [((1+a*r)*(1+b*s)-t+a*b*q)*(a*r+b*s-1)/4 for a, b in BASE]
    N.append(t*(2*t-1))
    N.append((1+r-t)*(1-r-t)*(1-s-t)/h/2)      # 01 at s=-1
    N.append((1+s-t)*(1-s-t)*(1+r-t)/h/2)      # 12 at r=+1
    N.append((1+r-t)*(1-r-t)*(1+s-t)/h/2)      # 23 at s=+1
    N.append((1+s-t)*(1-s-t)*(1-r-t)/h/2)      # 30 at r=-1
    for a, b in BASE:
        N.append(t*(1+a*r-t)*(1+b*s-t)/h)
    return N


def _cs(fn):
    def f(r, s, t):
        h = 1e-30
        N = np.array([complex(v).real for v in fn(r, s, t)])
        d = [np.array([complex(v).imag/h for v in fn(*[x+(1j*h if i == k else 0) for k, x in enumerate((r, s, t))])])
             for i in range(3)]
        return N, np.column_stack(d)
    return f


SF6 = dict(SF)
SF6.update(wedge6=_cs(N_wedge6), wedge15=_cs(N_wedge15), pyr5=_cs(N_pyr5), pyr13=_cs(N_pyr13))


def N_quad4(a, b):
    return [(1+p*a)*(1+q*b)/4 for p, q in BASE]


def N_quad8(a, b):
    # alternating order: c0 m01 c1 m12 c2 m23 c3 m30
    c = [(1+p*a)*(1+q*b)*(p*a+q*b-1)/4 for p, q in BASE]
    return [c[0], (1-a*a)*(1-b)/2, c[1], (1+a)*(1-b*b)/2, c[2], (1-a*a)*(1+b)/2, c[3], (1-a)*(1-b*b)/2]


def N_tri3(a, b):
    return [1-a-b, a, b]


def N_tri6(a, b):
    L = [1-a-b, a, b]
    return [L[0]*(2*L[0]-1), 4*L[0]*L[1], L[1]*(2*L[1]-1), 4*L[1]*L[2], L[2]*(2*L[2]-1), 4*L[2]*L[0]]


def _cs2(fn):
    def f(a, b):
        h = 1e-30
        N = np.array([complex(v).real for v in fn(a, b)])
        d1 = np.array([complex(v).imag/h for v in fn(a+1j*h, b)])
        d2 = np.array([complex(v).imag/h for v in fn(a, b+1j*h)])
        return N, np.column_stack([d1, d2])
    return f


SF2 = dict(quad4=_cs2(N_quad4), quad8=_cs2(N_quad8), tri3=_cs2(N_tri3), tri6=_cs2(N_tri6))


# ---- quadrature tables (cached per shape) ---------------------------------------------
def rule_volume(shape):
    fam = family(shape)
    g, w = np.polynomial.legendre.leggauss(6)
    if fam == "hex":
        return gauss_hex(5)
    if fam == "tet":
        return gauss_tet()
    if fam == "wedge":
        tri = rule_surface("tri3")
        return [((a, b, t), wt*wq) for (a, b), wt in tri for t, wq in zip(g, w)]
    # pyramid: collapsed Gauss on t in (0,1)
    out = []
    for a, wa in zip(g, w):
        for b, wb in zip(g, w):
            for c, wc in zip(g, w):
                t = (c+1)/2; h = 1-t
                out.append(((a*h, b*h, t), wa*wb*wc/2*h*h))
    return out


def rule_surface(shape):
    g, w = np.polynomial.legendre.leggauss(6)
    if shape.startswith("quad"):
        return [((a, b), wa*wb) for a, wa in zip(g, w) for b, wb in zip(g, w)]
    out = []
    for a, wa in zip(g, w):
        for b, wb in zip(g, w):
            u, v = (a+1)/2, (b+1)/2
            out.append(((u, v*(1-u)), wa*wb/4*(1-u)))
    return out


_VT = {}; _ST = {}


def vol_tab(shape):
    if shape not in _VT:
        r = rule_volume(shape)
        tab = [SF6[shape](*q) for q, _ in r]
        _VT[shape] = (np.array([t[0] for t in tab]), np.array([t[1] for t in tab]), np.array([w for _, w in r]))
    return _VT[shape]


def surf_tab(shape):
    if shape not in _ST:
        r = rule_surface(shape)
        tab = [SF2[shape](*q) for q, _ in r]
        _ST[shape] = (np.array([t[0] for t in tab]), np.array([t[1] for t in tab]), np.array([w for _, w in r]))
    return _ST[shape]


def vol_integrate(shape, X):
    """(volume, first moment) of an element with node matrix X."""
    N, dN, w = vol_tab(shape)
    J = np.einsum("ji,qjk->qik", X, dN)
    dV = np.linalg.det(J)*w
    return dV.sum(), (dV[:, None]*(N @ X)).sum(axis=0)


def surf_points(shape, X):
    """(x_q, da_vec_q) of a surface with node matrix X (da = x,a cross x,b times weight)."""
    N, dN, w = surf_tab(shape)
    t1 = dN[:, :, 0] @ X; t2 = dN[:, :, 1] @ X
    return N @ X, np.cross(t1, t2)*w[:, None]


# ---- model ------------------------------------------------------------------------
def mat_xml(name, kind, **k):
    g = ""
    if kind == "shell":
        g = '<geometric type="Plate" thickness="%s m" />' % fmt(k["t"])
    elif kind == "beam":
        g = '<geometric type="RectBar" recta="%s m" rectb="%s m" />' % (fmt(k["a"]), fmt(k["b"]))
    return ('  <mat name="%s">%s<mechanical type="Isotropic" youngsmodulus="%d Pa" poissonratio="%s" />'
            '<density type="Simple" density="%s kg/m&#179;" /></mat>' % (name, g, E_PA, NU, fmt(RHO)))


class Model:
    """m: fb_lib.Mesh (ids 1..n). comps: name -> dict(kind, t or a+b).
    loads: dicts with type gravity, nforce, nmoment, fforce, traction, pressure, offset.
    root: supported node ids. Lc: section size, used to scale the errors."""

    def __init__(self):
        self.m = Mesh(); self.comps = {}; self.loads = []; self.root = set(); self.Lc = 0.02
        self.offset_sign = 1.0; self.loads_at_offset = False; self.grav_at_offset = False

    def X(self, n):
        return np.array(self.m.xyz[n-1])

    def Xe(self, e):
        return np.array([self.m.xyz[n-1] for n in self.m.elems[e][1]])

    def kind(self, e):
        return self.comps[self.m.comp[e]]["kind"]

    def rotnodes(self):
        out = set()
        for e, (sh, nds) in self.m.elems.items():
            if self.kind(e) != "solid":
                out.update(nds)
        return out

    def nodes_of(self, E):
        out = set()
        for e in E:
            out.update(self.m.elems[e][1])
        return out

    # -- geometry of one element ---------------------------------------------------
    def mass_centre(self, e):
        sh, nds = self.m.elems[e]; X = self.Xe(e); c = self.comps[self.m.comp[e]]
        if c["kind"] == "solid":
            V, Q = vol_integrate(sh, X)
            return RHO*V, Q/V
        if c["kind"] == "shell":
            x, da = surf_points(sh, X)
            a = np.linalg.norm(da, axis=1)
            A = a.sum(); cen = (a[:, None]*x).sum(axis=0)/A
            if self.grav_at_offset:
                cen = cen + self.elem_off(e)*self.offset_sign*self.normal(e)
            return RHO*c["t"]*A, cen
        return RHO*c["a"]*c["b"]*np.linalg.norm(X[1]-X[0]), X.mean(axis=0)

    def normal(self, e):
        sh, nds = self.m.elems[e]
        x, da = surf_points(sh, self.Xe(e))
        v = da.sum(axis=0)
        return v/np.linalg.norm(v)

    def elem_off(self, e):
        for L in self.loads:
            if L["type"] == "offset" and e in L["elems"]:
                return L["w"]
        return 0.0

    def face_surf(self, e, f):
        """(x_q, da_q with outward normal for solids and edges) of a face. Shell: f 0..3
        edges, 4 face, 5 face reversed."""
        sh, nds = self.m.elems[e]; X = self.Xe(e)
        if sh in SHELL:
            if f >= 4:
                x, da = surf_points(sh, X)
                return x, (da if f == 4 else -da)
            raise ValueError("shell edge: use edge_points")
        ss, idx = solid_face(sh, f)
        return surf_points(ss, X[idx])

    def edge_points(self, e, f):
        """Straight or quadratic shell edge: (x_q, length_q)."""
        sh, nds = self.m.elems[e]; X = self.Xe(e)
        step = 2 if sh in ("quad8", "tri6") else 1
        ncorner = len(nds)//step
        a = X[(f*step) % len(nds)]; b = X[((f+1)*step) % len(nds)]
        g, w = np.polynomial.legendre.leggauss(6)
        if step == 1:
            xs = np.array([(1-t)/2*a+(1+t)/2*b for t in g]); ds = np.array([np.linalg.norm(b-a)/2*q for q in w])
            return xs, ds
        m = X[(f*step+1) % len(nds)]
        Nn = np.array([[t*(t-1)/2, 1-t*t, t*(t+1)/2] for t in g]); dNn = np.array([[t-.5, -2*t, t+.5] for t in g])
        P = np.array([a, m, b])
        return Nn @ P, np.linalg.norm(dNn @ P, axis=1)*w

    def face_area(self, e, f):
        sh = self.m.elems[e][0]
        if sh in SHELL and f < 4:
            return self.edge_points(e, f)[1].sum()*self.comps[self.m.comp[e]]["t"]
        return np.linalg.norm(self.face_surf(e, f)[1], axis=1).sum()

    # -- exact statics ---------------------------------------------------------------
    def ext_points(self, E):
        """External loads acting on element set E, as wrenches (F, point, couple)."""
        E = set(E); nodes = self.nodes_of(E); pts = []
        for L in self.loads:
            t = L["type"]
            if t == "gravity":
                for e in E:
                    ms, c = self.mass_centre(e)
                    pts.append((ms*np.array(L["g"]), c, np.zeros(3)))
            elif t == "nforce":
                for n in L["nodes"]:
                    if n in nodes:
                        x = self.X(n)
                        if self.loads_at_offset:
                            x = x + L.get("off", np.zeros(3))
                        pts.append((np.array(L["F"], float)/len(L["nodes"]), x, np.zeros(3)))
            elif t == "nmoment":
                for n in L["nodes"]:
                    if n in nodes:
                        pts.append((np.zeros(3), self.X(n), np.array(L["M"], float)/len(L["nodes"])))
            elif t == "fforce":
                tot = sum(self.face_area(e, f) for e, f in L["faces"])
                for e, f in L["faces"]:
                    if e in E:
                        sh = self.m.elems[e][0]
                        if sh in SHELL and f < 4:
                            x, ds = self.edge_points(e, f)
                            a = ds
                        else:
                            x, da = self.face_surf(e, f)
                            a = np.linalg.norm(da, axis=1)
                        F = np.array(L["F"], float)/tot*self.face_area(e, f)
                        cen = (a[:, None]*x).sum(axis=0)/a.sum()
                        if self.loads_at_offset and sh in SHELL:
                            cen = cen+self.elem_off(e)*self.offset_sign*self.normal(e)
                        pts.append((F, cen, np.zeros(3)))
            elif t == "traction":
                for e, f in L["faces"]:
                    if e in E:
                        x, da = self.face_surf(e, f)
                        a = np.linalg.norm(da, axis=1)
                        cen = (a[:, None]*x).sum(axis=0)/a.sum()
                        if self.m.elems[e][0] in SHELL:
                            # Mecway applies it at the shell surface, t/2 from the mid-surface (P3)
                            n = da.sum(axis=0); cen = cen+self.comps[self.m.comp[e]]["t"]/2*n/np.linalg.norm(n)
                        pts.append((a.sum()*np.array(L["T"], float), cen, np.zeros(3)))
            elif t == "pressure":
                # positive pressure pushes on the element, so against the outward normal
                for e, f in L["faces"]:
                    if e in E:
                        x, da = self.face_surf(e, f)
                        Fq = -L["p"]*L.get("sign", 1.0)*da
                        pts.append((Fq.sum(axis=0), np.zeros(3), np.cross(x, Fq).sum(axis=0)))
        return pts

    # -- sub-model -------------------------------------------------------------------
    def sub(self, E, drop=(), exclude_nodes=()):
        """New model holding only elements E, renumbered 1..n, with the loads that act on them."""
        E2 = sorted(E); M = Model(); M.comps = self.comps; M.Lc = self.Lc; used = sorted(self.nodes_of(E2))
        nmap = {n: i+1 for i, n in enumerate(used)}
        M.m.xyz = [self.m.xyz[n-1] for n in used]
        emap = {}
        for e in E2:
            sh, nds = self.m.elems[e]
            emap[e] = M.m.add(sh, [nmap[n] for n in nds], self.m.comp[e])
        for L in self.loads:
            t = L["type"]
            if t in drop:
                continue
            if t == "gravity":
                M.loads.append(dict(L))
            elif t in ("nforce", "nmoment"):
                keep = [n for n in L["nodes"] if n in nmap and n not in exclude_nodes]
                if keep:
                    q = dict(L); q["nodes"] = [nmap[n] for n in keep]
                    k = "F" if t == "nforce" else "M"
                    q[k] = tuple(np.array(L[k], float)*len(keep)/len(L["nodes"]))
                    M.loads.append(q)
            elif t == "offset":
                keep = [emap[e] for e in L["elems"] if e in emap]
                if keep:
                    q = dict(L); q["elems"] = keep; M.loads.append(q)
            else:
                keep = [(e, f) for e, f in L["faces"] if e in emap]
                if keep:
                    q = dict(L); q["faces"] = [(emap[e], f) for e, f in keep]
                    if t == "fforce":
                        # a force is a total over its faces: scale to the part that is kept
                        share = sum(self.face_area(e, f) for e, f in keep)/sum(self.face_area(e, f) for e, f in L["faces"])
                        q["F"] = tuple(np.array(L["F"], float)*share)
                    M.loads.append(q)
        return M, nmap, emap

    # -- writer ------------------------------------------------------------------------
    def write(self, path, holds=None, fields=("displacement", "reaction force"), rootonly=True, rotdirs="xyz"):
        m = self.m
        assert sorted(m.elems) == list(range(1, len(m.elems)+1))
        used = self.nodes_of(m.elems)
        assert used == set(range(1, len(m.xyz)+1)), "node ids must be contiguous and all used"
        x = ['<?xml version="1.0" encoding="utf-8"?>', '<liml version="34">', '  <analysis type="S30" />']
        for i, p in enumerate(m.xyz):
            x.append('  <node nid="%d" x="%s" y="%s" z="%s" />' % (i+1, fmt(p[0]), fmt(p[1]), fmt(p[2])))
        for c in sorted(self.comps):
            ids = [e for e in sorted(m.elems) if m.comp[e] == c]
            if ids:
                x.append('  <elset name="%s" material="M_%s" colorrgb="00C800">' % (c, c))
                for e in ids:
                    x.append('    <elem eid="%d" shape="%s" nodes="%s" />' % (e, m.elems[e][0], " ".join(map(str, m.elems[e][1]))))
                x.append('  </elset>')
        for c, d in sorted(self.comps.items()):
            x.append(mat_xml("M_"+c, d["kind"], **{k: v for k, v in d.items() if k != "kind"}))
        rn = self.rotnodes()
        if self.root:
            ids = sorted(self.root)
            x.append('  <nodeselection name="ROOT">' + "".join('<node nid="%d" />' % n for n in ids) + '</nodeselection>')
            for d in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
                x.append('  <displacement selection="ROOT"><value>0 m</value><x>%d</x><y>%d</y><z>%d</z></displacement>' % d)
            rr = [n for n in ids if n in rn]
            if rr:
                x.append('  <nodeselection name="ROOTR">' + "".join('<node nid="%d" />' % n for n in rr) + '</nodeselection>')
                for d in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
                    x.append('  <noderotation selection="ROOTR"><value>0 rad</value><x>%d</x><y>%d</y><z>%d</z></noderotation>' % d)
        for k, L in enumerate(self.loads):
            t = L["type"]; nm = "L%d" % k
            if t == "gravity":
                x.append('  <gravity><x>%s m/s&#178;</x><y>%s m/s&#178;</y><z>%s m/s&#178;</z></gravity>' % tuple(fmt(v) for v in L["g"]))
            elif t == "nforce":
                x.append('  <nodeselection name="%s">' % nm + "".join('<node nid="%d" />' % n for n in L["nodes"]) + '</nodeselection>')
                x.append('  <force selection="%s"><x>%s N</x><y>%s N</y><z>%s N</z></force>' % ((nm,)+tuple(fmt(v) for v in L["F"])))
            elif t == "nmoment":
                # one selection per node: a moment on a selection of two or more nodes had no
                # effect at all in Mecway 34 (shell, probe P4), silently
                for n in L["nodes"]:
                    q = "%s_%d" % (nm, n)
                    x.append('  <nodeselection name="%s"><node nid="%d" /></nodeselection>' % (q, n))
                    x.append('  <moment selection="%s"><x>%s N.m</x><y>%s N.m</y><z>%s N.m</z></moment>'
                             % ((q,)+tuple(fmt(v/len(L["nodes"])) for v in L["M"])))
            elif t == "offset":
                x.append('  <elementselection name="%s">' % nm + "".join('<element eid="%d" />' % e for e in L["elems"]) + '</elementselection>')
                x.append('  <offset selection="%s"><u>0 m</u><v>0 m</v><w>%s m</w></offset>' % (nm, fmt(L["w"])))
            else:
                x.append('  <faceselection name="%s">' % nm + "".join('<face eid="%d" faceid="%d" />' % (e, f+1) for e, f in L["faces"]) + '</faceselection>')
                if t == "fforce":
                    x.append('  <force selection="%s"><x>%s N</x><y>%s N</y><z>%s N</z></force>' % ((nm,)+tuple(fmt(v) for v in L["F"])))
                elif t == "traction":
                    x.append('  <traction selection="%s"><x>%s Pa</x><y>%s Pa</y><z>%s Pa</z></traction>' % ((nm,)+tuple(fmt(v) for v in L["T"])))
                else:
                    x.append('  <surfacepressure selection="%s"><normal>%s Pa</normal></surfacepressure>' % (nm, fmt(L["p"])))
        for n, (u, r) in sorted((holds or {}).items()):
            x.append('  <nodeselection name="H%d"><node nid="%d" /></nodeselection>' % (n, n))
            for c in range(3):
                a = [0, 0, 0]; a[c] = 1
                x.append('  <displacement selection="H%d"><value>%s m</value><x>%d</x><y>%d</y><z>%d</z></displacement>'
                         % (n, fmt(u[c]), a[0], a[1], a[2]))
                if r is not None and "xyz"[c] in rotdirs:
                    x.append('  <noderotation selection="H%d"><value>%s rad</value><x>%d</x><y>%d</y><z>%d</z></noderotation>'
                             % (n, fmt(r[c]), a[0], a[1], a[2]))
        units = {"displacement": "m", "rotation": "rad", "reaction force": "N", "reaction moment": "N.m", "stress": "Pa"}
        for f in fields:
            x.append('  <fieldvariable name="%s" displayunit="%s" expanded="true" />' % (f, units[f]))
        x.append('</liml>')
        io.open(path, "w", encoding="ascii", newline="\n").write("\n".join(x))


# ---- own solve: no refusal when another Mecway runs. Window watch on the own PID only;
# on a dialog the own process object is killed, nothing else is touched -----------------
class MecwayDialog(RuntimeError):
    pass


class NoSolution(RuntimeError):
    pass


_user32 = ctypes.windll.user32
_ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def _text(h):
    b = ctypes.create_unicode_buffer(400); _user32.GetWindowTextW(h, b, 400)
    return b.value


def own_windows(pid):
    """Titles and child texts of the visible top-level windows of this PID (read only)."""
    res = []

    def cb(h, l):
        p = W.DWORD(); _user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _user32.IsWindowVisible(h):
            kids = []

            def ck(c, l2):
                t = _text(c)
                if t:
                    kids.append(t)
                return True
            _user32.EnumChildWindows(h, _ENUM(ck), 0)
            res.append((_text(h), kids))
        return True
    _user32.EnumWindows(_ENUM(cb), 0)
    return res


def other_mecways():
    o = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mecway.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return sorted(int(m) for m in re.findall(r'"mecway\.exe","(\d+)"', o, re.I))


def _log(rec):
    if WD:
        with open(os.path.join(WD, "solves.jsonl"), "a") as f:
            f.write(json.dumps(rec)+"\n")


def run_watched(args, tag, timeout):
    """Start Mecway hidden with args, watch its windows, kill only that process on trouble."""
    before = other_mecways()
    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
    p = subprocess.Popen([MECWAY]+args, startupinfo=si)
    t0 = time.time(); seen = None; rec = dict(tag=tag, pid=p.pid, others=before, status="ok")
    try:
        while p.poll() is None:
            w = own_windows(p.pid)
            if w:
                seen = seen or time.time()
                if time.time()-seen > 5:
                    rec.update(status="dialog", windows=w)
                    p.kill()
                    raise MecwayDialog(repr(w))
            if time.time()-t0 > timeout:
                rec.update(status="timeout")
                p.kill()
                raise RuntimeError("timeout")
            time.sleep(0.1)
    finally:
        rec["t"] = time.time()-t0; rec["after"] = [q for q in other_mecways() if q != p.pid]
        _log(rec)
    return rec["t"]


def solve6(liml_in, sol, timeout=240):
    assert os.path.isfile(liml_in) and os.path.isabs(liml_in)
    txt = io.open(liml_in, encoding="utf-8").read()
    if os.path.exists(sol):
        os.remove(sol)
    txt = txt.replace("</liml>", '  <solutionfile filename="%s" />\n</liml>' % sol.replace("/", "\\"))
    run = liml_in[:-5] + "_run.liml"
    io.open(run, "w", encoding="utf-8").write(txt)
    t = run_watched([run, "solve"], os.path.basename(liml_in), timeout)
    if not os.path.isfile(sol) or "<results" not in io.open(sol, encoding="utf-8", errors="replace").read():
        raise NoSolution(os.path.basename(liml_in))
    return t


class Res:
    def __init__(self, path):
        self.r = read_results(path)
        self.v = {k: {int(n): self.r["nv"][k][i] for i, n in enumerate(self.r["nids"][k])} for k in self.r["nv"]}

    def vec(self, n, names, default=None):
        out = []
        for k in names:
            if k not in self.v or n not in self.v[k]:
                if default is None:
                    raise KeyError("no %s at node %d" % (k, n))
                out.append(default)
            else:
                out.append(self.v[k][n])
        return np.array(out)

    def u(self, n):
        return self.vec(n, ("displx", "disply", "displz"))

    def rot(self, n):
        return self.vec(n, ("rotx", "roty", "rotz"))

    def R(self, n):
        return self.vec(n, ("reactionforcex", "reactionforcey", "reactionforcez"))

    def Rm(self, n):
        return self.vec(n, ("reactionmomx", "reactionmomy", "reactionmomz"))


def wrench(pts, P):
    F = np.zeros(3); M = np.zeros(3)
    for f, x, c in pts:
        F = F+f; M = M+np.cross(x-P, f)+c
    return F, M


# ---- cuts --------------------------------------------------------------------------
def analyse(M, S):
    """Far-side parts O_k and cut patches, from nodes alone: works for any element mix."""
    S = set(S); m = M.m; rest = [e for e in m.elems if e not in S]
    n2e = {}
    for e in rest:
        for n in m.elems[e][1]:
            n2e.setdefault(n, []).append(e)
    seen = set(); parts = []
    for e0 in rest:
        if e0 in seen:
            continue
        st = [e0]; seen.add(e0); comp = []
        while st:
            e = st.pop(); comp.append(e)
            for n in m.elems[e][1]:
                for q in n2e[n]:
                    if q not in seen:
                        seen.add(q); st.append(q)
        parts.append(comp)
    NS = M.nodes_of(S); out = []
    sup = 0
    for comp in parts:
        NO = M.nodes_of(comp); nodes = sorted(NS & NO)
        has = bool(NO & M.root)
        sup += has
        P = np.mean([M.X(n) for n in nodes], axis=0)
        out.append(dict(elems=comp, nodes=nodes, P=P, support=has))
    if sup > 1:
        raise ValueError("more than one far-side part holds supports: statically undetermined reference")
    allcut = [n for p in out for n in p["nodes"]]
    if len(allcut) != len(set(allcut)):
        raise ValueError("patches share nodes")
    layer = [e for e in S if set(m.elems[e][1]) & set(allcut)]
    return out, layer, set(allcut)


def exact(M, patch, S):
    if patch["support"]:
        others = [e for e in M.m.elems if e not in set(patch["elems"])]
        F, Mo = wrench(M.ext_points(others), patch["P"])
        return -F, -Mo
    return wrench(M.ext_points(patch["elems"]), patch["P"])


def node_normal(M, n, S):
    v = np.zeros(3)
    for e in S:
        sh, nds = M.m.elems[e]
        if n in nds and sh in SHELL:
            v = v+M.normal(e)
    L = np.linalg.norm(v)
    return v/L if L > 0 else None


def errors(F, Mm, Fx, Mx, Lc):
    sF = max(np.linalg.norm(Fx), np.linalg.norm(Mx)/Lc)
    sM = max(np.linalg.norm(Mx), np.linalg.norm(Fx)*Lc)
    return dict(eF=float(np.linalg.norm(F-Fx)/sF), eM=float(np.linalg.norm(Mm-Mx)/sM),
                eMraw=float(np.linalg.norm(Mm-Mx)/max(np.linalg.norm(Mx), 1e-300)))


RESULTS = []


def record(row):
    RESULTS.append(row)
    print("  %-26s %-8s %-9s %-7s eF=%.2e eM=%.2e eMraw=%.2e %s" % (
        row["case"], row["shape"], row["method"], row["cut"], row["eF"], row["eM"], row["eMraw"],
        ("drill=%.1e" % row["drill"]) if row.get("drill") is not None else ""), flush=True)


def fail(case, shape, method, why):
    row = dict(case=case, shape=shape, method=method, cut="-", failed=str(why)[:300])
    RESULTS.append(row)
    print("  %-26s %-8s %-9s FAILED %s" % (case, shape, method, str(why)[:300]), flush=True)


def save_results(name):
    fn = os.path.join(WD, name+".json")
    json.dump(RESULTS, open(fn, "w"), indent=0)
    print("wrote", fn, flush=True)


# ---- one complete case --------------------------------------------------------------
def solve_main(M, tag, stress=False):
    d = os.path.join(WD, tag); os.makedirs(d, exist_ok=True)
    rn = M.rotnodes()
    f = ["displacement", "reaction force"] + (["rotation", "reaction moment"] if rn else []) + (["stress"] if stress else [])
    p = os.path.join(d, "main.liml"); s = os.path.join(d, "main_sol.liml")
    M.write(p, fields=f)
    t = solve6(p, s)
    r = Res(s)
    # global check against statics: reactions on the supports + all external loads = 0
    P = np.mean([M.X(n) for n in M.root], axis=0)
    F = np.zeros(3); Mo = np.zeros(3)
    for n in sorted(M.root):
        f_ = r.R(n); F = F+f_; Mo = Mo+np.cross(M.X(n)-P, f_)
        if n in rn:
            Mo = Mo+r.Rm(n)
    Fe, Me = wrench(M.ext_points(M.m.elems), P)
    g = errors(F, Mo, -Fe, -Me, M.Lc)
    print("%s: %d el, %d nodes, main %.1fs, global eF=%.1e eM=%.1e" % (tag, len(M.m.elems), len(M.m.xyz), t, g["eF"], g["eM"]), flush=True)
    return r, g, s


def sub_solve(M, E, held, r, tag, name, drop=(), rotdirs="xyz", exclude=()):
    """Solve element set E with nodes `held` at the values of solution r; reactions by old id."""
    M2, nmap, emap = M.sub(E, drop=drop, exclude_nodes=exclude)
    rn = M2.rotnodes()
    holds = {}
    for n in held:
        q = nmap[n]
        holds[q] = (r.u(n), r.rot(n) if q in rn else None)
    d = os.path.join(WD, tag)
    p = os.path.join(d, name+".liml"); s = os.path.join(d, name+"_sol.liml")
    f = ["displacement", "reaction force"] + (["rotation", "reaction moment"] if rn else [])
    M2.write(p, holds=holds, fields=f, rotdirs=rotdirs)
    solve6(p, s)
    rr = Res(s)
    out = {}
    for n in held:
        q = nmap[n]
        rm = rr.vec(q, ("reactionmomx", "reactionmomy", "reactionmomz"), 0.0) if (q in rn) else np.zeros(3)
        if q in rn and "xyz" == rotdirs:
            rm = rr.Rm(q)
        out[n] = (rr.R(q), rm)
    return out


def cut_wrench(M, patch, R):
    F = np.zeros(3); Mo = np.zeros(3); mn = np.zeros(3)
    for n in patch["nodes"]:
        f, mm = R[n]
        F = F+f; Mo = Mo+np.cross(M.X(n)-patch["P"], f)+mm; mn = mn+mm
    return F, Mo, mn


def drill_part(M, patch, R, S):
    d = np.zeros(3)
    for n in patch["nodes"]:
        nn = node_normal(M, n, S)
        if nn is not None:
            d = d+np.dot(R[n][1], nn)*nn
    return d


def report(M, S, parts, R, case, shape, method, extra=None):
    tot = []
    for i, p in enumerate(parts):
        Fx, Mx = exact(M, p, S)
        F, Mo, mn = cut_wrench(M, p, R)
        e = errors(F, Mo, Fx, Mx, M.Lc)
        sM = max(np.linalg.norm(Mx), np.linalg.norm(Fx)*M.Lc)
        dr = float(np.linalg.norm(drill_part(M, p, R, S))/sM) if M.rotnodes() else None
        row = dict(case=case, shape=shape, method=method, cut="c%d" % (i+1), drill=dr, nodal=float(np.linalg.norm(mn)/sM),
                   F=[float(v) for v in F], M=[float(v) for v in Mo], Fx=[float(v) for v in Fx], Mx=[float(v) for v in Mx], **e)
        if extra:
            row.update(extra)
        record(row)
        tot.append((F, Mo, p["P"]))
    # closure: the sum over all cuts plus the known loads on S must vanish
    if all(not p["support"] for p in parts) or True:
        P0 = parts[0]["P"]
        Fs, Ms = wrench(M.ext_points(S), P0)
        for F, Mo, P in tot:
            Fs = Fs+F; Ms = Ms+Mo+np.cross(P-P0, F)
        sc = max(np.linalg.norm(p_) for p_ in [t[0] for t in tot])
        scm = max(np.linalg.norm(t[1]) for t in tot)
        ra = float(np.linalg.norm(Fs)/max(sc, 1e-300)); rb = float(np.linalg.norm(Ms)/max(scm, sc*M.Lc, 1e-300))
        print("    closure %-9s force %.1e moment %.1e" % (method, ra, rb), flush=True)
        RESULTS[-1]["closeF"] = ra; RESULTS[-1]["closeM"] = rb


def run_case(M, S, case, shape, negatives=(), do_m4=True, do_m4l=True, stress=False, m3=None):
    """Main solve, then M4, M4L and negative controls. Failures are recorded, never hidden."""
    tag = "%s_%s" % (case, shape)
    try:
        r, g, sol = solve_main(M, tag, stress=stress or m3 is not None)
    except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
        fail(case, shape, "main", ex)
        return None
    RESULTS.append(dict(case=case, shape=shape, method="global", cut="-", eF=g["eF"], eM=g["eM"], eMraw=g["eMraw"],
                        nel=len(M.m.elems), nn=len(M.m.xyz)))
    parts, layer, cut = analyse(M, S)
    print("  parts=%d cutnodes=%d S=%d layer=%d" % (len(parts), len(cut), len(S), len(layer)), flush=True)
    if do_m4:
        try:
            R = sub_solve(M, S, cut, r, tag, "m4", exclude=cut)
            report(M, S, parts, R, case, shape, "M4")
        except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
            fail(case, shape, "M4", ex)
    if do_m4l:
        try:
            R = sub_solve(M, layer, M.nodes_of(layer), r, tag, "m4l", exclude=cut)
            report(M, S, parts, R, case, shape, "M4L")
        except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
            fail(case, shape, "M4L", ex)
    if m3 is not None:
        try:
            R = m3(M, S, parts, sol, cut)
            report(M, S, parts, R, case, shape, "M3")
        except Exception as ex:
            fail(case, shape, "M3", ex)
    for name, kw in negatives:
        try:
            R = sub_solve(M, layer, M.nodes_of(layer), r, tag, "neg_"+name, exclude=cut, **kw)
            report(M, S, parts, R, case, shape, "NEG:"+name)
        except (MecwayDialog, NoSolution, RuntimeError, KeyError) as ex:
            fail(case, shape, "NEG:"+name, ex)
    return r


# ---- M3 for any solid shape, from element-node stress. Volumetric load gravity only ----
VARS = ["stressxx", "stressyy", "stresszz", "stressxy", "stressyz", "stresszx"]


def tens6(s):
    return np.array([[s[0], s[3], s[5]], [s[3], s[1], s[4]], [s[5], s[4], s[2]]])


def m3_nodal(M, S, parts, sol, cut):
    r = read_results(sol)
    se = {}; pos = 0
    for e in r["eids"]["stressxx"]:
        e = int(e); k = len(M.m.elems[e][1])
        se[e] = np.column_stack([r["ev"][v][pos:pos+k] for v in VARS]); pos += k
    g = np.zeros(3)
    for L in M.loads:
        if L["type"] == "gravity":
            g = np.array(L["g"], float)
    Rn = {}
    for e in S:
        sh, nds = M.m.elems[e]
        idx = [i for i, n in enumerate(nds) if n in cut]
        if not idx:
            continue
        X = M.Xe(e); Se = se[e]
        N, dN, w = vol_tab(sh)
        for q in range(len(w)):
            J = X.T @ dN[q]
            dNx = dN[q] @ np.linalg.inv(J)
            dV = np.linalg.det(J)*w[q]
            s = tens6(N[q] @ Se)
            for i in idx:
                Rn[nds[i]] = Rn.get(nds[i], 0) + (s @ dNx[i] - RHO*g*N[q, i])*dV
    return {n: (v, np.zeros(3)) for n, v in Rn.items()}
