# Research code for the method comparison (docs/research). Not the product.
# Self-made models only. CPython 3 with numpy.
import base64, ctypes, ctypes.wintypes as W, io, os, re, subprocess, time
import numpy as np

MECWAY = r"C:\Program Files\Mecway\mecway.exe"


# ---- shape functions (natural coordinates) -------------------------------
def sf_hex8(r, s, t):
    c = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]
    N = np.array([(1+a*r)*(1+b*s)*(1+d*t)/8 for a,b,d in c])
    dN = np.array([[a*(1+b*s)*(1+d*t)/8, b*(1+a*r)*(1+d*t)/8, d*(1+a*r)*(1+b*s)/8] for a,b,d in c])
    return N, dN


# hex20 in Mecway order: corners 0-7, then 01 12 23 30, 04 15 26 37, 45 56 67 74
HEX20C = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1),
          (0,-1,-1),(1,0,-1),(0,1,-1),(-1,0,-1),
          (-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),
          (0,-1,1),(1,0,1),(0,1,1),(-1,0,1)]


def sf_hex20(r, s, t):
    N = np.zeros(20); dN = np.zeros((20,3))
    for i,(a,b,c) in enumerate(HEX20C):
        if a and b and c:
            N[i] = (1+a*r)*(1+b*s)*(1+c*t)*(a*r+b*s+c*t-2)/8
            dN[i,0] = a*(1+b*s)*(1+c*t)*(2*a*r+b*s+c*t-1)/8
            dN[i,1] = b*(1+a*r)*(1+c*t)*(a*r+2*b*s+c*t-1)/8
            dN[i,2] = c*(1+a*r)*(1+b*s)*(a*r+b*s+2*c*t-1)/8
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


def sf_tet4(r, s, t):
    return np.array([1-r-s-t, r, s, t]), np.array([[-1,-1,-1],[1,0,0],[0,1,0],[0,0,1.]])


# tet10 Mecway order: 0-3, 01 12 20, 03 13 23
def sf_tet10(r, s, t):
    L = [1-r-s-t, r, s, t]
    dL = np.array([[-1,-1,-1],[1,0,0],[0,1,0],[0,0,1.]])
    pairs = [(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)]
    N = [L[i]*(2*L[i]-1) for i in range(4)] + [4*L[a]*L[b] for a,b in pairs]
    dN = [(4*L[i]-1)*dL[i] for i in range(4)] + [4*(L[a]*dL[b]+L[b]*dL[a]) for a,b in pairs]
    return np.array(N), np.array(dN)


SF = {"hex8": sf_hex8, "hex20": sf_hex20, "tet4": sf_tet4, "tet10": sf_tet10}


def gauss_hex(n):
    g, w = np.polynomial.legendre.leggauss(n)
    return [((a,b,c), wa*wb*wc) for a,wa in zip(g,w) for b,wb in zip(g,w) for c,wc in zip(g,w)]


def gauss_tet():
    # collapsed Gauss-Legendre rule on the unit tetrahedron
    g, w = np.polynomial.legendre.leggauss(5)
    pts = []
    for a,wa in zip(g,w):
        for b,wb in zip(g,w):
            for c,wc in zip(g,w):
                u,v,x = (a+1)/2,(b+1)/2,(c+1)/2
                r = u; s = v*(1-u); t = x*(1-u)*(1-v)
                pts.append(((r,s,t), wa*wb*wc/8*(1-u)**2*(1-v)))
    return pts


def elem_rule(shape):
    return gauss_hex(3) if shape.startswith("hex") else gauss_tet()


def own_rule(shape):
    """The rule the element itself is taken to use (found by experiment E3)."""
    if shape.startswith("hex"):
        return gauss_hex(2)
    if shape == "tet4":
        return [((.25, .25, .25), 1/6.)]
    a, b = 0.1381966011250105, 0.5854101966249685
    return [((a, a, a), 1/24.), ((b, a, a), 1/24.), ((a, b, a), 1/24.), ((a, a, b), 1/24.)]


# faces: corner indices, outward normal (0-based face index = faceid-1)
HEX_F = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
TET_F = [(0,2,1),(0,1,3),(1,2,3),(0,3,2)]


def face_points(shape, faceidx):
    """Quadrature on a face: (natural point in the element, weight, dxi, deta),
    dxi/deta natural tangents, so that dA_vec = (J dxi) x (J deta) * weight."""
    if shape.startswith("hex"):
        c = np.array(HEX20C[:8], float)
        q = np.array([c[i] for i in HEX_F[faceidx]])
        g, w = np.polynomial.legendre.leggauss(4)
        out = []
        for a,wa in zip(g,w):
            for b,wb in zip(g,w):
                sh = np.array([(1-a)*(1-b),(1+a)*(1-b),(1+a)*(1+b),(1-a)*(1+b)])/4
                p = sh @ q
                dxi = (np.array([-(1-b),(1-b),(1+b),-(1+b)])/4) @ q
                de = (np.array([-(1-a),-(1+a),(1+a),(1-a)])/4) @ q
                out.append((p, wa*wb, dxi, de))
        return out
    c = np.array([(0,0,0),(1,0,0),(0,1,0),(0,0,1.)])
    q = [c[i] for i in TET_F[faceidx]]
    g, w = np.polynomial.legendre.leggauss(6)
    out = []
    for a,wa in zip(g,w):
        for b,wb in zip(g,w):
            u,v = (a+1)/2,(b+1)/2
            xi = u; eta = v*(1-u)
            p = q[0]*(1-xi-eta)+q[1]*xi+q[2]*eta
            out.append((p, wa*wb/4*(1-u), q[1]-q[0], q[2]-q[0]))
    return out


def face_corners(shape, faceidx):
    return (HEX_F if shape.startswith("hex") else TET_F)[faceidx]


def face_nodes_local(shape, faceidx):
    """Local node indices of a face, incl. midsides."""
    fn = SF[shape]
    N = np.array([fn(*p)[0] for p,_,_,_ in face_points(shape, faceidx)])
    return [i for i in range(N.shape[1]) if np.abs(N[:,i]).max() > 1e-9]


# ---- model -----------------------------------------------------------------
class Mesh:
    def __init__(self):
        self.key = {}; self.xyz = []; self.elems = {}; self.comp = {}

    def node(self, x, y, z):
        k = (round(x*1e9), round(y*1e9), round(z*1e9))
        if k not in self.key:
            self.xyz.append((x,y,z)); self.key[k] = len(self.xyz)
        return self.key[k]

    def add(self, shape, nodes, comp="P"):
        eid = len(self.elems)+1
        self.elems[eid] = (shape, list(nodes)); self.comp[eid] = comp
        return eid

    def X(self, nid):
        return np.array(self.xyz[nid-1])


TET_SPLIT = [(0,1,2,6),(0,2,3,6),(0,3,7,6),(0,7,4,6),(0,4,5,6),(0,5,1,6)]


def add_cell(m, x0, dx, shape, comp="P"):
    x0 = np.array(x0, float); dx = np.array(dx, float)
    c = [x0+dx*(np.array(q)+1)/2 for q in HEX20C[:8]]
    if shape == "hex8":
        return [m.add(shape, [m.node(*p) for p in c], comp)]
    if shape == "hex20":
        nat = [x0+dx*(np.array(q)+1)/2 for q in HEX20C]
        return [m.add(shape, [m.node(*p) for p in nat], comp)]
    out = []
    for t in TET_SPLIT:
        v = [c[i] for i in t]
        if np.linalg.det(np.array([v[1]-v[0], v[2]-v[0], v[3]-v[0]])) < 0:
            v[1], v[2] = v[2], v[1]
        pts = list(v)
        if shape == "tet10":
            pts += [(v[0]+v[1])/2,(v[1]+v[2])/2,(v[2]+v[0])/2,(v[0]+v[3])/2,(v[1]+v[3])/2,(v[2]+v[3])/2]
        out.append(m.add(shape, [m.node(*p) for p in pts], comp))
    return out


def face_key(m, eid, f):
    shape, nodes = m.elems[eid]
    return tuple(sorted(nodes[i] for i in face_corners(shape, f)))


def all_faces(m):
    d = {}
    for eid,(shape,_) in m.elems.items():
        for f in range(6 if shape.startswith("hex") else 4):
            d.setdefault(face_key(m, eid, f), []).append((eid, f))
    return d


def cut_faces(m, S):
    """Faces of elements in S whose neighbour is outside S."""
    S = set(S); out = []
    for k, lst in all_faces(m).items():
        ins = [x for x in lst if x[0] in S]; outs = [x for x in lst if x[0] not in S]
        if ins and outs:
            out.extend(ins)
    return out


def boundary_faces(m, where):
    """Free faces whose centre satisfies where(centre)."""
    out = []
    for k, lst in all_faces(m).items():
        if len(lst) == 1:
            c = np.mean([m.X(n) for n in k], axis=0)
            if where(c):
                out.append(lst[0])
    return out


def fmt(v):
    return repr(float(v))


def write_liml(path, m, E=210e9, nu=0.3, rho=7850.0, gravity=None, fixed_faces=None,
               forces=(), extra="", fields=("displacement","stress","reaction force"),
               elems=None):
    """forces: list of (name, [(eid,f0based),..], (Fx,Fy,Fz)) on faces; elems: subset of ids."""
    ids = sorted(m.elems) if elems is None else sorted(elems)
    sv = os.environ.get("FB_SOLVER", "")
    L = ['<?xml version="1.0" encoding="utf-8"?>', '<liml version="34">',
         '  <analysis type="S30"%s />' % (' solver="%s"' % sv if sv else "")]
    used = set()
    for eid in ids:
        used.update(m.elems[eid][1])
    for nid in sorted(used):
        x,y,z = m.xyz[nid-1]
        L.append('  <node nid="%d" x="%s" y="%s" z="%s" />' % (nid, fmt(x), fmt(y), fmt(z)))
    L.append('  <elset name="P" material="Steel" colorrgb="00C800">')
    for eid in ids:
        s,n = m.elems[eid]
        L.append('    <elem eid="%d" shape="%s" nodes="%s" />' % (eid, s, " ".join(map(str,n))))
    L.append('  </elset>')
    L.append('  <mat name="Steel"><mechanical type="Isotropic" youngsmodulus="%d Pa" poissonratio="%s" />'
             '<density type="Simple" density="%s kg/m&#179;" /></mat>' % (int(E), nu, fmt(rho)))
    if fixed_faces:
        L.append('  <faceselection name="CLAMP">' + "".join('<face eid="%d" faceid="%d" />' % (e,f+1) for e,f in fixed_faces) + '</faceselection>')
        L.append('  <fixed selection="CLAMP" />')
    for name, faces, F in forces:
        L.append('  <faceselection name="%s">' % name + "".join('<face eid="%d" faceid="%d" />' % (e,f+1) for e,f in faces) + '</faceselection>')
        L.append('  <force selection="%s"><x>%s N</x><y>%s N</y><z>%s N</z></force>' % ((name,)+tuple(fmt(v) for v in F)))
    if gravity is not None:
        L.append('  <gravity><x>%s m/s&#178;</x><y>%s m/s&#178;</y><z>%s m/s&#178;</z></gravity>' % tuple(fmt(v) for v in gravity))
    if extra:
        L.append(extra)
    for f in fields:
        L.append('  <fieldvariable name="%s" displayunit="%s" expanded="true" />' % (f, {"stress":"Pa","displacement":"m","reaction force":"N","external force":"N"}.get(f,"")))
    L.append('</liml>')
    io.open(path, "w", encoding="ascii", newline="\n").write("\n".join(L))


# ---- safe run of Mecway ------------------------------------------------------
user32 = ctypes.windll.user32
WNDENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def _visible_windows(pid):
    res = []

    def cb(h, l):
        p = W.DWORD(); user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(200); user32.GetWindowTextW(h, b, 200); res.append(b.value)
        return True
    user32.EnumWindows(WNDENUM(cb), 0)
    return res


def mecway_running():
    o = subprocess.run(["tasklist","/FI","IMAGENAME eq mecway.exe"],capture_output=True,text=True).stdout
    return "mecway.exe" in o.lower()


def solve(liml_in, sol, timeout=180):
    """Hidden solve with window watch; kills only its own PID."""
    assert os.path.isfile(liml_in) and os.path.isabs(liml_in)
    if mecway_running():
        raise RuntimeError("Mecway is running: refuse to start")
    txt = io.open(liml_in, encoding="utf-8").read()
    if os.path.exists(sol):
        os.remove(sol)
    txt = txt.replace("</liml>", '  <solutionfile filename="%s" />\n</liml>' % sol.replace("/", "\\"))
    run = liml_in[:-5] + "_run.liml"
    io.open(run, "w", encoding="utf-8").write(txt)
    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
    p = subprocess.Popen([MECWAY, run, "solve"], startupinfo=si)
    t0 = time.time(); seen = None
    while p.poll() is None:
        w = _visible_windows(p.pid)
        if w:
            seen = seen or time.time()
            if time.time()-seen > 5:
                subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True)
                raise RuntimeError("dialog from Mecway: %r" % w)
        if time.time()-t0 > timeout:
            subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True)
            raise RuntimeError("timeout")
        time.sleep(0.25)
    return time.time()-t0


# ---- results reader ----------------------------------------------------------
def read_results(sol):
    """nv: {var: array}, ev: {var: array}, nids/eids: {var: ids}."""
    txt = io.open(sol, encoding="utf-8", errors="replace").read()
    i = txt.find("<results"); r = txt[i:]
    prec = re.search(r'precision="(\w+)"', r[:80]).group(1)

    def b64(s):
        return base64.b64decode(re.sub(r"\s", "", s))
    nids = {m.group(1): np.frombuffer(b64(m.group(2)), "<i4")
            for m in re.finditer(r'<nodeids name="([^"]+)">(.*?)</nodeids>', r, re.S)}
    eids = {m.group(1): np.frombuffer(b64(m.group(2)), "<i4")
            for m in re.finditer(r'<elementnodeids name="([^"]+)">(.*?)</elementnodeids>', r, re.S)}
    nv = {}; ev = {}
    for m in re.finditer(r'<(element)?nodevariable name="([^"]+)"[^>]*>(.*?)</(?:element)?nodevariable>', r, re.S):
        vals = re.search(r'<values(single|double)>(.*?)</values', m.group(3), re.S)
        if not vals:
            continue
        a = np.frombuffer(b64(vals.group(2)), "<f4" if vals.group(1) == "single" else "<f8")
        (ev if m.group(1) else nv)[m.group(2)] = a
    return dict(prec=prec, nids=nids, eids=eids, nv=nv, ev=ev, head=r[:1500])
