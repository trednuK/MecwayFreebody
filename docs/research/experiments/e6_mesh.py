# E6 mesh builders: shell strips with a mapping (flat, folded, curved, turned), beams,
# solid blocks with every Mecway solid shape, and a block refined by Mecway's refine_x2.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_lib import *

L, W_, T = .2, .04, .005          # shell strip
BL, BB, BH = .2, .02, .04         # solid block
g_oblique = (1., -2., -9.81)


# ---- mappings of the strip (u, v, 0) to 3D --------------------------------------------
def rotation(ax=(1., 2., 3.), ang=0.7):
    a = np.array(ax)/np.linalg.norm(ax)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3)+np.sin(ang)*K+(1-np.cos(ang))*K @ K


def m_flat(p):
    return np.array(p, float)


def m_fold(deg, uf=L/2):
    a = np.radians(deg)

    def f(p):
        u, v, w = p
        if u <= uf+1e-12:
            return np.array([u, v, w])
        return np.array([uf+(u-uf)*np.cos(a), v, (u-uf)*np.sin(a)+w])
    return f


def m_arc(ang=np.pi/2):
    R = L/ang

    def f(p):
        u, v, w = p
        return np.array([R*np.sin(u/R), v, R*(1-np.cos(u/R))])
    return f


def m_skew(a=.25, du=.01, dv=.01):
    """In-plane distortion that leaves the edges straight in the parameter direction."""
    def f(p):
        u, v, w = p
        s = np.sin(np.pi*u/L*4)*np.sin(np.pi*v/W_)
        return np.array([u+a*du*s, v+a*dv*np.cos(np.pi*u/L*3)*np.sin(np.pi*v/W_), w])
    return f


def turned(fn, R):
    return lambda p: R @ fn(p)


def strip(shape, nu=20, nv=4, mapfn=m_flat, length=L, width=W_, t=T):
    M = Model(); M.comps = {"S": dict(kind="shell", t=t)}; m = M.m; M.Lc = width
    par = {}
    du, dv = length/nu, width/nv

    def nd(a):
        return m.node(float(a[0]), float(a[1]), 0.)

    for i in range(nu):
        for j in range(nv):
            c = [np.array(q) for q in ((i*du, j*dv), ((i+1)*du, j*dv), ((i+1)*du, (j+1)*dv), (i*du, (j+1)*dv))]
            if shape == "quad4":
                par[m.add(shape, [nd(q) for q in c], "S")] = i
            elif shape == "quad8":
                par[m.add(shape, [nd(c[0]), nd((c[0]+c[1])/2), nd(c[1]), nd((c[1]+c[2])/2), nd(c[2]),
                                  nd((c[2]+c[3])/2), nd(c[3]), nd((c[3]+c[0])/2)], "S")] = i
            else:
                tris = ((0, 1, 2), (0, 2, 3)) if (i+j) % 2 else ((0, 1, 3), (1, 2, 3))
                for a, b, d in tris:
                    if shape == "tri3":
                        par[m.add(shape, [nd(c[a]), nd(c[b]), nd(c[d])], "S")] = i
                    else:
                        par[m.add(shape, [nd(c[a]), nd((c[a]+c[b])/2), nd(c[b]), nd((c[b]+c[d])/2), nd(c[d]),
                                          nd((c[d]+c[a])/2)], "S")] = i
    M.par = par
    M.uv = [p[:2] for p in m.xyz]
    M.mapfn = mapfn
    m.xyz = [tuple(mapfn(p)) for p in m.xyz]
    M.root = {i+1 for i, q in enumerate(M.uv) if abs(q[0]) < 1e-9}
    M.tip = [i+1 for i, q in enumerate(M.uv) if abs(q[0]-length) < 1e-9]
    M.corner = [i+1 for i, q in enumerate(M.uv) if abs(q[0]-length) < 1e-9 and abs(q[1]) < 1e-9]
    M.corner2 = [i+1 for i, q in enumerate(M.uv) if abs(q[0]-length) < 1e-9 and abs(q[1]-width) < 1e-9]
    M.length, M.width = length, width
    return M


def tip_axes(M):
    """Unit tangents along u and v at the tip, from the mapping."""
    p = M.mapfn((M.length-1e-6, M.width/2, 0.)); q = M.mapfn((M.length-2e-6, M.width/2, 0.))
    t1 = (p-q)/np.linalg.norm(p-q)
    r = M.mapfn((M.length-1e-6, M.width/2+1e-6, 0.))
    t2 = (r-p)/np.linalg.norm(r-p)
    return t1, t2


def beam(nx=20, mapfn=m_flat, length=L):
    M = Model(); M.comps = {"B": dict(kind="beam", a=.02, b=.01)}; M.Lc = .02
    m = M.m
    par = {}
    for i in range(nx):
        a = m.node(i*length/nx, 0., 0.); b = m.node((i+1)*length/nx, 0., 0.)
        par[m.add("line2", [a, b], "B")] = i
    M.par = par; M.uv = [p[:2] for p in m.xyz]; M.mapfn = mapfn; M.length = length
    m.xyz = [tuple(mapfn(p)) for p in m.xyz]
    M.root = {1}; M.tip = [len(m.xyz)]
    return M


def beam_tee(nx=20, Rm=None):
    """Main line along x, clamped at x=0, free end at x=L, branch from mid-span along y."""
    Rm = np.eye(3) if Rm is None else Rm
    M = Model(); M.comps = {"B": dict(kind="beam", a=.02, b=.01)}; M.Lc = .02; m = M.m
    h = L/nx
    for i in range(nx):
        m.add("line2", [m.node(i*h, 0., 0.), m.node((i+1)*h, 0., 0.)], "B")
    nb = nx//2
    for i in range(nb):
        m.add("line2", [m.node(L/2, i*h, 0.), m.node(L/2, (i+1)*h, 0.)], "B")
    m.xyz = [tuple(Rm @ np.array(p)) for p in m.xyz]
    M.root = {1}
    M.tip = [m.elems[nx][1][1]]
    M.tip2 = [m.elems[nx+nb][1][1]]
    M.S = [e for e in m.elems if (nx//4 <= e-1 < 3*nx//4) or (nx < e-1+1 and e-1-nx < nb//2)]
    return M


# ---- solids ------------------------------------------------------------------------
def qnodes(shape, corners):
    pts = list(corners)
    if shape in MID:
        pts += [(corners[a]+corners[b])/2 for a, b in MID[shape]]
    return pts


def add_wedges(m, x0, dx, shape, axis, comp="P"):
    x0 = np.array(x0, float); dx = np.array(dx, float)
    e = np.zeros(3); e["xyz".index(axis)] = 1
    a, b = [np.eye(3)[i] for i in range(3) if i != "xyz".index(axis)]

    def pt(p, q, h):
        return x0+dx*(a*p+b*q+e*h)
    out = []
    for tri in (((0, 0), (1, 0), (1, 1)), ((0, 0), (1, 1), (0, 1))):
        p = [pt(*q, 0) for q in tri]
        if np.dot(np.cross(p[1]-p[0], p[2]-p[0]), e) < 0:
            p[1], p[2] = p[2], p[1]
        c = p+[v+dx*e for v in p]
        out.append(m.add(shape, [m.node(*v) for v in qnodes(shape, c)], comp))
    return out


def add_pyramids(m, x0, dx, shape, comp="P"):
    x0 = np.array(x0, float); dx = np.array(dx, float)
    c = [x0+dx*(np.array(q)+1)/2 for q in HEX20C[:8]]
    centre = x0+dx/2; out = []
    for f in FACES["hex"]:
        base = [c[i] for i in f[::-1]]        # normal towards the apex
        out.append(m.add(shape, [m.node(*v) for v in qnodes(shape, base+[centre])], comp))
    return out


def distort(M, a, d):
    out = []
    for x, y, z in M.m.xyz:
        f = np.sin(np.pi*x/BL)*np.sin(np.pi*y/BB)*np.sin(np.pi*z/BH)
        g = np.sin(2*np.pi*x/BL)*np.sin(2*np.pi*y/BB)*np.sin(2*np.pi*z/BH)
        out.append((x+a*d[0]*f, y+a*d[1]*g, z+a*d[2]*f*g))
    M.m.xyz = out


def block(code, n=1, dist=0.):
    M = Model(); M.comps = {"P": dict(kind="solid")}; M.Lc = BH; m = M.m
    nx, ny, nz = 10*n, 2*n, 4*n
    d = (BL/nx, BB/ny, BH/nz)
    cell = {}
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                x0 = (i*d[0], j*d[1], k*d[2])
                if code in ("hex8", "hex20", "tet4", "tet10"):
                    es = add_cell(m, x0, d, code, "P")
                elif code in ("wedge6y", "wedge15y", "wedge6x", "wedge15x", "wedge6z", "wedge15z"):
                    es = add_wedges(m, x0, d, code[:-1], code[-1])
                elif code in ("pyr5", "pyr13"):
                    es = add_pyramids(m, x0, d, code)
                elif code in ("hp8", "hp20"):
                    # checkerboard of hex cells and cells of six pyramids: conformal mix
                    q = (code == "hp20")
                    if (i+j+k) % 2:
                        es = add_cell(m, x0, d, "hex20" if q else "hex8", "P")
                    else:
                        es = add_pyramids(m, x0, d, "pyr13" if q else "pyr5")
                for e in es:
                    cell[e] = (i, j, k)
    M.cell = cell; M.dims = (nx, ny, nz); M.d = d
    if dist:
        distort(M, dist, d)
    M.root = {i+1 for i, p in enumerate(m.xyz) if abs(p[0]) < 1e-9}
    return M


def free_faces(M, where):
    d = {}
    for e, (sh, nds) in M.m.elems.items():
        if sh in SHELL or sh in LINE:
            continue
        for f, c in enumerate(FACES[family(sh)]):
            k = tuple(sorted(nds[i] for i in c))
            d.setdefault(k, []).append((e, f))
    out = []
    for k, lst in d.items():
        if len(lst) == 1:
            if where(np.mean([M.X(n) for n in k], axis=0)):
                out.append(lst[0])
    return out


def block_loads(M, g=g_oblique):
    tip = free_faces(M, lambda c: abs(c[0]-BL) < 1e-9)
    top = [f for f in tip if np.mean(M.face_surf(*f)[0], axis=0)[2] > BH/2]
    M.loads.append(dict(type="fforce", faces=tip, F=(2000., 500., -1000.)))
    M.loads.append(dict(type="fforce", faces=top, F=(0., 800., 0.)))
    if g is not None:
        M.loads.append(dict(type="gravity", g=g))


def elem_x(M, e):
    return M.Xe(e).mean(axis=0)[0]


def select_x(M, x1, x2):
    return [e for e in M.m.elems if x1 < elem_x(M, e) < x2]


# ---- block refined by Mecway ---------------------------------------------------------
def refined_block(base, region, tag):
    """Block of 80 hex cells; part of it refined by mw.refine_x2 in a hidden Mecway, so that
    the mesh holds the real transition elements. Read back and renumbered 1..n."""
    M = block(base, 1)
    if region == "sec":
        ref = [e for e, c in M.cell.items() if 3 <= c[0] <= 6]
    else:
        ref = [e for e, c in M.cell.items() if 3 <= c[0] <= 6 and c[1] == 0 and c[2] >= 2]
    d = os.path.join(WD, tag); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "base.liml"); out = os.path.join(d, "refined.liml"); log = os.path.join(d, "refine.log")
    M.write(p)
    txt = io.open(p, encoding="utf-8").read()
    sel = '  <elementselection name="REF">' + "".join('<element eid="%d" />' % e for e in ref) + '</elementselection>\n'
    io.open(p, "w", encoding="ascii", newline="\n").write(txt.replace("</liml>", sel+"</liml>"))
    sc = os.path.join(d, "refine.py")
    io.open(sc, "w", encoding="ascii", newline="\n").write(
        "import traceback\n"
        "log = open(r'%s', 'w')\n"
        "try:\n"
        "    ids = list(mw.named_selection('REF'))\n"
        "    log.write('ref %%d\\n' %% len(ids))\n"
        "    mw.refine_x2(None, None, ids)\n"
        "    mw.save_as(r'%s')\n"
        "    log.write('saved\\n')\n"
        "except Exception as ex:\n"
        "    log.write(traceback.format_exc())\n"
        "log.close()\n" % (log, out))
    if os.path.exists(out):
        os.remove(out)
    run_watched([p, "script", sc], "refine_"+tag, 120)
    if not os.path.isfile(out):
        raise NoSolution("refine gave no file: "+io.open(log).read())
    s = io.open(out, encoding="utf-8", errors="replace").read()
    s = s.split("<solution")[0]
    nodes = {int(a): (float(x), float(y), float(z)) for a, x, y, z in
             re.findall(r'<node nid="(\d+)" x="([^"]+)" y="([^"]+)" z="([^"]+)"', s)}
    els = re.findall(r'<elem eid="(\d+)" shape="(\w+)" nodes="([^"]+)"', s)
    R = Model(); R.comps = {"P": dict(kind="solid")}; R.Lc = BH
    used = sorted({int(q) for _, _, q2 in els for q in q2.split()})
    mp = {n: i+1 for i, n in enumerate(used)}
    R.m.xyz = [nodes[n] for n in used]
    for _, sh, q in els:
        R.m.add(sh, [mp[int(v)] for v in q.split()], "P")
    R.root = {i+1 for i, p_ in enumerate(R.m.xyz) if abs(p_[0]) < 1e-9}
    counts = {}
    for sh, _ in R.m.elems.values():
        counts[sh] = counts.get(sh, 0)+1
    print("  refined:", counts, flush=True)
    return R
