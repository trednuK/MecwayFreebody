# E7 models 2 and 3: shells (DKT, COQUE_3D) and beams (POU_D_E, POU_D_T), two cuts, loads that
# include nodal moments. Geometry is mapped from a flat strip to fold, arc or a turned plane,
# so DRX, DRY and DRZ all carry something. Run: python e7_struct.py [filter]
import concurrent.futures as cf
from e7_routes import *

T = .002; W = .04; SEC = (.02, .04)
GOBL = np.array([3., -4., -8.])


def rot3():
    a, b, c = .5, -.7, 1.1
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def g_flat(x, y):
    return np.array([x, y, 0.])


def g_turn(x, y):
    return rot3() @ np.array([x, y, 0.])


def g_fold(x, y, a=np.radians(60), x0=L*.5):
    if x <= x0:
        return rot3() @ np.array([x, y, 0.])
    return rot3() @ np.array([x0+(x-x0)*np.cos(a), y, (x-x0)*np.sin(a)])


def g_arc(x, y, R=L/(np.pi/2)):
    return rot3() @ np.array([R*np.sin(x/R), y, R*(1-np.cos(x/R))])


def strip(typ, nx, ny, geo):
    """Surface cells on a strip; regions by column. Mid-side nodes on the mapped surface."""
    m = Mesh(); m.parent = {}
    dx, dy = L/nx, W/ny
    pt = lambda u, v: m.node(*geo(u, v))
    mid = lambda a, b: ((a[0]+b[0])/2, (a[1]+b[1])/2)
    for i in range(nx):
        r = 0 if i < nx//4 else (1 if i < 3*nx//4 else 2)
        for j in range(ny):
            x0, y0 = i*dx, j*dy
            c = [(x0, y0), (x0+dx, y0), (x0+dx, y0+dy), (x0, y0+dy)]
            if typ == "QUAD4":
                m.add("QUAD4", [pt(*p) for p in c], r)
            elif typ == "QUAD8":
                m.add("QUAD8", [pt(*p) for p in c+[mid(c[q], c[(q+1) % 4]) for q in range(4)]], r)
            elif typ == "TRIA3":
                m.add("TRIA3", [pt(*c[q]) for q in (0, 1, 2)], r)
                m.add("TRIA3", [pt(*c[q]) for q in (0, 2, 3)], r)
            elif typ == "TRIA6":
                for t in ((0, 1, 2), (0, 2, 3)):
                    v = [c[q] for q in t]
                    m.add("TRIA6", [pt(*p) for p in v+[mid(v[q], v[(q+1) % 3]) for q in range(3)]], r)
            elif typ == "MIX":     # quads and triangles interleaved, DKT
                if (i+j) % 2:
                    m.add("QUAD4", [pt(*p) for p in c], r)
                else:
                    m.add("TRIA3", [pt(*c[q]) for q in (0, 1, 2)], r)
                    m.add("TRIA3", [pt(*c[q]) for q in (0, 2, 3)], r)
    m.ma["SH"] = list(m.region)
    root = []; tip = []
    for j in range(2*ny+1):
        for lst, xx in ((root, 0.), (tip, L)):
            k = tuple(round(v*1e10) for v in geo(xx, j*dy/2))
            if k in m.key:
                lst.append(m.key[k])
    m.no["ROOT"] = sorted(set(root)); m.no["TIPN"] = sorted(set(tip))
    m.no["TIP1"] = [m.key[tuple(round(v*1e10) for v in geo(L, 0.))]]
    return m


def groups_struct(m):
    S = [c for c, r in m.region.items() if r == 1]
    nod = {r: set() for r in (0, 1, 2)}
    for c, r in m.region.items():
        nod[r].update(m.cells[c-1][1])
    m.ma["S"] = S
    m.no["CUTA"] = sorted(nod[0] & nod[1]); m.no["CUTB"] = sorted(nod[1] & nod[2])


def shell_case(tag, typ, model, geo, nx=20, ny=4, grav=True, exc=None, press=None, drill=False, drz=None):
    m = strip(typ, nx, ny, geo)
    groups_struct(m)
    q = model == "COQUE_3D"
    tip = np.array([300., 200., -100.]); mt = np.array([2., 3., -1.])
    if not drill:
        # no moment about the shell normal at the tip: it has no physical stiffness
        back = L/nx if model == "DKT" else 1e-4      # DKT: the facet itself
        n = np.cross(geo(L, W/ny)-geo(L, 0.), geo(L, 0.)-geo(L-back, 0.))
        n = n/np.linalg.norm(n)
        mt = mt-(mt @ n)*n
    su = ["mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')"]
    su2 = ["mesh = LIRE_MAILLAGE(UNITE=81, FORMAT='MED')"]
    if q:
        o = "QUAD8_9" if typ == "QUAD8" else "TRIA6_7"
        su += ["mesh0 = mesh", "mesh = CREA_MAILLAGE(MAILLAGE=mesh0, MODI_MAILLE=_F(TOUT='OUI', OPTION='%s'))" % o]
    ek = (", EXCENTREMENT=%r, INER_ROTA='OUI'" % exc) if exc else ""
    ek += (", COEF_RIGI_DRZ=%r" % drz) if drz else ""
    rest = """
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', PHENOMENE='MECANIQUE', MODELISATION='%s'))
cara = AFFE_CARA_ELEM(MODELE=model, COQUE=_F(GROUP_MA='SH', EPAIS=%r, VECTEUR=(1., 0.3, 0.1)%s))
mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r))
cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat))
bc = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_NO='ROOT', DX=0., DY=0., DZ=0., DRX=0., DRY=0., DRZ=0.))
tip = AFFE_CHAR_MECA(MODELE=model, FORCE_NODALE=(_F(GROUP_NO='TIP1', FX=%r, FY=%r, FZ=%r, MX=%r, MY=%r, MZ=%r),))
""" % (model, T, ek, E0, NU, RHO, tip[0], tip[1], tip[2], mt[0], mt[1], mt[2])
    ex = ["_F(CHARGE=bc)", "_F(CHARGE=tip)"]
    gn = np.linalg.norm(GOBL)
    if grav:
        rest += "grav = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=%r, DIRECTION=(%r, %r, %r)))\n" % (gn, *(GOBL/gn))
        ex.append("_F(CHARGE=grav)")
    if press:
        rest += "prs = AFFE_CHAR_MECA(MODELE=model, FORCE_COQUE=_F(TOUT='OUI', PRES=%r))\n" % press
        ex.append("_F(CHARGE=prs)")
    regs = {}; X = m.X()
    for r in (0, 1, 2):
        ids = [c for c, q_ in m.region.items() if q_ == r]
        regs[r] = np.zeros_like(X)
        if grav:
            regs[r] = regs[r]+nodal_surface(m, ids, trac=RHO*T*GOBL)
        if press:
            regs[r] = regs[r]+nodal_surface(m, ids, pres=press)
    ti = m.no["TIP1"][0]-1
    regs[2] = regs[2].copy(); regs[2][ti] += tip
    mom = {2: np.zeros_like(X)}; mom[2][ti] = mt
    cuts = cut_points(m)
    return dict(tag=tag, mesh=m, setup="\n".join(su)+rest, setup_rmed="\n".join(su2)+rest,
                excit="("+", ".join(ex)+")", kind="elas", fields=["DEPL"] if q else ["DEPL", "SIEF_ELGA"],
                solve="res = MECA_STATIQUE(MODELE=model, CHAM_MATER=cm, CARA_ELEM=cara, EXCIT=EXC, "
                      "SOLVEUR=_F(METHODE='MUMPS'))", ranks=[1], cuts=cuts,
                lire_kw=" CARA_ELEM=cara, NUME_DDL=nu," if q else " CARA_ELEM=cara,", cara_impr=", CARA_ELEM=cara",
                lire_pre=("nu = NUME_DDL(MODELE=model, CHARGE=(%s))" % ", ".join(e[10:-1] for e in ex)) if q else "",
                ref=lambda k, u: ref_cuts(regs, X, {a: np.array(b) for a, b in cuts.items()}, mom))


def beam_case(tag, model, geo, n=20, load=("grav", "line")):
    """Line of SEG2 along a mapped polyline; rectangular section; tip load with moment, line
    load, gravity."""
    m = Mesh(); m.parent = {}
    ids = [m.node(*geo(i*L/n, 0.)) for i in range(n+1)]
    A = SEC[0]*SEC[1]
    for i in range(n):
        r = 0 if i < n//4 else (1 if i < 3*n//4 else 2)
        m.add("SEG2", [ids[i], ids[i+1]], r)
    m.ma["BM"] = list(m.region)
    m.no["ROOT"] = [ids[0]]; m.no["TIP1"] = [ids[-1]]
    groups_struct(m)
    tip = np.array([300., 200., -100.]); mt = np.array([2., 3., -1.]); q = np.array([50., -30., 80.])
    gn = np.linalg.norm(GOBL)
    su = """
mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', PHENOMENE='MECANIQUE', MODELISATION='%s'))
cara = AFFE_CARA_ELEM(MODELE=model, POUTRE=_F(GROUP_MA='BM', SECTION='RECTANGLE', CARA=('HY', 'HZ'), VALE=%r),
    ORIENTATION=_F(GROUP_MA='BM', CARA='VECT_Y', VALE=(.3, .9, .2)))
mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r))
cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat))
bc = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_NO='ROOT', DX=0., DY=0., DZ=0., DRX=0., DRY=0., DRZ=0.))
tip = AFFE_CHAR_MECA(MODELE=model, FORCE_NODALE=_F(GROUP_NO='TIP1', FX=%r, FY=%r, FZ=%r, MX=%r, MY=%r, MZ=%r))
""" % (model, SEC, E0, NU, RHO, *tip, *mt)
    ex = ["_F(CHARGE=bc)", "_F(CHARGE=tip)"]
    if "line" in load:
        su += ("lin = AFFE_CHAR_MECA(MODELE=model, FORCE_POUTRE=_F(GROUP_MA='BM', FX=%r, FY=%r, FZ=%r))"+chr(10)) % tuple(q)
        ex.append("_F(CHARGE=lin)")
    if "grav" in load:
        su += ("grav = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=%r, DIRECTION=(%r, %r, %r)))"+chr(10)) % (gn, *(GOBL/gn))
        ex.append("_F(CHARGE=grav)")
    X = m.X(); regs = {}
    for r in (0, 1, 2):
        f = np.zeros_like(X)
        for c, q_ in m.region.items():
            if q_ == r:
                a, b = np.array(m.cells[c-1][1])-1
                le = np.linalg.norm(X[b]-X[a])
                w = ((RHO*A*GOBL if "grav" in load else 0)+(q if "line" in load else 0))*le/2
                f[a] += w; f[b] += w
        regs[r] = f
    ti = ids[-1]-1
    regs[2][ti] += tip
    mom = {2: np.zeros_like(X)}; mom[2][ti] = mt
    cuts = cut_points(m)
    return dict(tag=tag, mesh=m, setup=su, excit="("+", ".join(ex)+")",
                kind="elas", fields=["DEPL", "SIEF_ELGA"],
                solve="res = MECA_STATIQUE(MODELE=model, CHAM_MATER=cm, CARA_ELEM=cara, EXCIT=EXC, "
                      "SOLVEUR=_F(METHODE='MUMPS'))", ranks=[1], cuts=cuts, lire_kw=" CARA_ELEM=cara,",
                cara_impr=", CARA_ELEM=cara",
                ref=lambda k, u: ref_cuts(regs, X, {a: np.array(b) for a, b in cuts.items()}, mom))


CASES = [("dkt_q4_flat", lambda t: shell_case(t, "QUAD4", "DKT", g_flat)),
         ("dkt_q4_turn", lambda t: shell_case(t, "QUAD4", "DKT", g_turn)),
         ("dkt_t3_turn", lambda t: shell_case(t, "TRIA3", "DKT", g_turn)),
         ("dkt_mix_turn", lambda t: shell_case(t, "MIX", "DKT", g_turn)),
         ("dkt_q4_fold", lambda t: shell_case(t, "QUAD4", "DKT", g_fold)),
         ("dkt_q4_arc", lambda t: shell_case(t, "QUAD4", "DKT", g_arc)),
         ("dkt_q4_prs", lambda t: shell_case(t, "QUAD4", "DKT", g_turn, press=5000.)),
         ("dkt_q4_drill", lambda t: shell_case(t, "QUAD4", "DKT", g_turn, drill=True)),
         ("c3d_q8_drill", lambda t: shell_case(t, "QUAD8", "COQUE_3D", g_turn, drill=True)),
         ("dkt_q4_exc", lambda t: shell_case(t, "QUAD4", "DKT", g_turn, grav=False, exc=.003)),
         ("dkt_q4_excg", lambda t: shell_case(t, "QUAD4", "DKT", g_turn, exc=.003)),
         ("c3d_q8_turn", lambda t: shell_case(t, "QUAD8", "COQUE_3D", g_turn)),
         ("c3d_t6_turn", lambda t: shell_case(t, "TRIA6", "COQUE_3D", g_turn)),
         ("c3d_q8_fold", lambda t: shell_case(t, "QUAD8", "COQUE_3D", g_fold)),
         ("dkt_q4_arc7", lambda t: shell_case(t, "QUAD4", "DKT", g_arc, drz=1e-7)),
         ("dkt_q4_arc3", lambda t: shell_case(t, "QUAD4", "DKT", g_arc, drz=1e-3)),
         ("dkt_q4_arcf", lambda t: shell_case(t, "QUAD4", "DKT", g_arc, nx=80, ny=8)),
         ("dkt_q4_fold7", lambda t: shell_case(t, "QUAD4", "DKT", g_fold, drz=1e-7)),
         ("c3d_q8_arc", lambda t: shell_case(t, "QUAD8", "COQUE_3D", g_arc)),
         ("c3d_q8_prs", lambda t: shell_case(t, "QUAD8", "COQUE_3D", g_turn, press=5000.)),
         ("bme_grav", lambda t: beam_case(t, "POU_D_E", g_turn, load=("grav",))),
         ("bme_line", lambda t: beam_case(t, "POU_D_E", g_turn, load=("line",))),
         ("bmt_grav", lambda t: beam_case(t, "POU_D_T", g_turn, load=("grav",))),
         ("bmt_line", lambda t: beam_case(t, "POU_D_T", g_turn, load=("line",))),
         ("bme_frameg", lambda t: beam_case(t, "POU_D_E", g_fold, load=("grav",))),
         ("bmt_framel", lambda t: beam_case(t, "POU_D_T", g_fold, load=("line",))),
         ("bme_noload", lambda t: beam_case(t, "POU_D_E", g_turn, load=()))]


def one(a):
    c = a[1]("b_"+a[0])
    return run_routes(c)


if __name__ == "__main__":
    flt = sys.argv[1:]
    todo = [a for a in CASES if not flt or any(f in a[0] for f in flt)]
    all_r = []; infos = []
    with cf.ThreadPoolExecutor(4) as ex:
        for rows, info in ex.map(one, todo):
            show([q for q in rows if q["var"] != "FORC"]); all_r += rows; infos.append(info)
            print(info["case"], {k: info[k]["err"] for k in ("A", "P", "B", "B0", "Bm", "C") if k in info}, flush=True)
    json.dump(dict(rows=all_r, info=infos), open(os.path.join(WD, "res_struct%s.json" % ("_"+flt[0] if flt else "")), "w"))
