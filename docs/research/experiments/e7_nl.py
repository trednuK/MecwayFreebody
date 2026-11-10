# E7 model 4: elastoplastic block, load up past yield and partly back, every stored step
# checked. Geometry and loads as model 1, tip loads scaled by a ramp. Selection close to the
# clamp, so that cut A runs through the plastic zone. With a large-strain formulation the
# reference uses the deformed positions, as a dead load, and a follower pressure on the deformed
# faces. Run: python e7_nl.py [filter]
import concurrent.futures as cf
from e7_routes import *
from e7_struct import strip, groups_struct, g_turn, T, GOBL

SY, ET = 250e6, 2e9
LMAX = 4.5
TLIST = [i/8 for i in range(1, 9)] + [1+i/4 for i in range(1, 5)]


def lam(t, lmax=LMAX):
    return lmax*t if t <= 1 else lmax*(1-(t-1)*.75)


NLCOMMON = r'''
rampe = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., 0., 1., %(lm)r, 2., %(le)r), PROL_DROITE='CONSTANT')
un = DEFI_FONCTION(NOM_PARA='INST', VALE=(0., 1., 2., 1.), PROL_DROITE='CONSTANT')
lis = DEFI_LIST_REEL(DEBUT=0., INTERVALLE=(_F(JUSQU_A=1., NOMBRE=8), _F(JUSQU_A=2., NOMBRE=4)))
inst = DEFI_LIST_INST(DEFI_LIST=_F(LIST_INST=lis), ECHEC=_F(ACTION='DECOUPE', SUBD_NIVEAU=4, SUBD_PAS=4))
'''


def nl_block(tag, shape="HEXA20", dims=(20, 4, 8), defo="PETIT", relation="VMIS_ISOT_LINE", resi=1e-8,
             press=None, distort=0., lmax=LMAX, follow=True):
    nx = dims[0]
    m = block(shape, dims, distort, select=lambda i, j, k: 0 if i < nx//10 else (1 if i < nx//2 else 2))
    skin(m, "ROOT", lambda c: abs(c[0]) < 1e-9)
    skin(m, "TIPALL", lambda c: abs(c[0]-L) < 1e-9)
    skin(m, "TIPTOP", lambda c: abs(c[0]-L) < 1e-9 and c[2] > H/2)
    if press:
        skin(m, "PR", lambda c: abs(c[2]-H) < 1e-9)
    groups_from_regions(m)
    AT, AU = surf_area(m, m.ma["TIPALL"]), surf_area(m, m.ma["TIPTOP"])
    tr = TIPF/AT; ar = TOPF/AU
    su = SOLID % dict(E=E0, NU=NU, RHO=RHO, tx=tr[0], ty=tr[1], tz=tr[2], ax=ar[0], ay=ar[1], az=ar[2])
    if relation.startswith("VMIS"):
        su = su.replace("mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r))" % (E0, NU, RHO),
                        "mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r), ECRO_LINE=_F(D_SIGM_EPSI=%r, SY=%r))"
                        % (E0, NU, RHO, ET, SY))
    su += NLCOMMON % dict(lm=lmax, le=lmax*.25)
    ex = "(_F(CHARGE=bc), _F(CHARGE=tip, FONC_MULT=rampe), _F(CHARGE=top, FONC_MULT=rampe), _F(CHARGE=grav)"
    if press:
        su += "prs = AFFE_CHAR_MECA(MODELE=model, PRES_REP=_F(GROUP_MA='PR', PRES=%r))" % press + chr(10) + "SKIP_S = True" + chr(10)
        ex += ", _F(CHARGE=prs, FONC_MULT=rampe%s)" % (", TYPE_CHARGE='SUIV'" if follow else "")
    ex += ")"
    comp = " COMPORTEMENT=_F(RELATION='%s', DEFORMATION='%s')," % (relation, defo)
    solve = ("res = STAT_NON_LINE(MODELE=model, CHAM_MATER=cm, EXCIT=EXC,%s INCREMENT=_F(LIST_INST=inst), "
             "NEWTON=_F(REAC_ITER=1, PREDICTION='ELASTIQUE'), CONVERGENCE=_F(RESI_GLOB_RELA=%r, ITER_GLOB_MAXI=30), "
             "SOLVEUR=_F(METHODE='MUMPS'))" % (comp, resi))
    regs0 = {r: nodal_gravity(m, cells=[c for c, q in m.region.items() if q == r]) for r in (0, 1, 2)}
    tipn = nodal_surface(m, m.ma["TIPALL"], trac=tr)+nodal_surface(m, m.ma["TIPTOP"], trac=ar)
    cuts = cut_points(m)
    X = m.X()
    Pc = {a: np.array(b) for a, b in cuts.items()}
    large = defo != "PETIT"
    pr_by = {}
    if press:
        for r in (0, 1, 2):
            pr_by[r] = [s for s in m.ma["PR"] if m.region[m.parent[s]] == r]

    def ref(t, u):
        lm = lam(t, lmax)
        xc = X+u[:, :3] if large else X
        regs = {r: regs0[r].copy() for r in regs0}
        regs[2] = regs[2]+lm*tipn
        if press:
            # the ramp multiplies the pressure; in a large-strain run it follows the faces
            for r in (0, 1, 2):
                regs[r] = regs[r]+lm*nodal_surface(m, pr_by[r], pres=press, X=xc)
        return ref_cuts(regs, xc, Pc)

    ranks = None         # all stored steps, known after the run
    return dict(tag=tag, mesh=m, setup=su, excit=ex, kind="noli", comp_kw=comp, large=large,
                fields=["DEPL", "SIEF_ELGA", "VARI_ELGA"], solve=solve, ranks=ranks, cuts=cuts, ref=ref)


def nl_shell(tag, typ, model, defo, relation="VMIS_ISOT_LINE", geo=None, resi=1e-8, lmax=LMAX, nx=20, ny=4):
    geo = geo or (lambda x, y: np.array([x, y, 0.]))
    m = strip(typ, nx, ny, geo)
    r0 = nx//10
    # selection next to the clamp, as for the block
    dx = L/nx
    X = m.X()
    for c in m.region:
        xm = X[np.array(m.cells[c-1][1])-1, 0].mean()
        m.region[c] = 0 if xm < r0*dx else (1 if xm < nx//2*dx else 2)
    groups_struct(m)
    q = model == "COQUE_3D"
    tip = np.array([300., 50., -12.])
    su = ["mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')"]
    if q:
        su += ["mesh0 = mesh", "mesh = CREA_MAILLAGE(MAILLAGE=mesh0, MODI_MAILLE=_F(TOUT='OUI', OPTION='QUAD8_9'))"]
    ecro = (", ECRO_LINE=_F(D_SIGM_EPSI=%r, SY=%r)" % (ET, SY)) if relation.startswith("VMIS") else ""
    rest = """
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', PHENOMENE='MECANIQUE', MODELISATION='%s'))
cara = AFFE_CARA_ELEM(MODELE=model, COQUE=_F(GROUP_MA='SH', EPAIS=%r, COQUE_NCOU=5, VECTEUR=(1., 0.3, 0.1)))
mat = DEFI_MATERIAU(ELAS=_F(E=%r, NU=%r, RHO=%r)%s)
cm = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT='OUI', MATER=mat))
bc = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_NO='ROOT', DX=0., DY=0., DZ=0., DRX=0., DRY=0., DRZ=0.))
tip = AFFE_CHAR_MECA(MODELE=model, FORCE_NODALE=(_F(GROUP_NO='TIP1', FX=%r, FY=%r, FZ=%r),))
""" % (model, T, E0, NU, RHO, ecro, tip[0], tip[1], tip[2])
    gn = np.linalg.norm(GOBL)
    rest += ("grav = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=%r, DIRECTION=(%r, %r, %r)))" % (gn, *(GOBL/gn))) + chr(10)
    rest += NLCOMMON % dict(lm=lmax, le=lmax*.25)
    ex = "(_F(CHARGE=bc), _F(CHARGE=tip, FONC_MULT=rampe), _F(CHARGE=grav))"
    comp = " COMPORTEMENT=_F(RELATION='%s', DEFORMATION='%s')," % (relation, defo)
    solve = ("res = STAT_NON_LINE(MODELE=model, CHAM_MATER=cm, CARA_ELEM=cara, EXCIT=EXC,%s INCREMENT=_F(LIST_INST=inst), "
             "NEWTON=_F(REAC_ITER=1, PREDICTION='ELASTIQUE'), CONVERGENCE=_F(RESI_GLOB_RELA=%r, ITER_GLOB_MAXI=30), "
             "SOLVEUR=_F(METHODE='MUMPS'))" % (comp, resi))
    regs0 = {}
    for r in (0, 1, 2):
        regs0[r] = nodal_surface(m, [c for c, q_ in m.region.items() if q_ == r], trac=RHO*T*GOBL)
    ti = m.no["TIP1"][0]-1
    cuts = cut_points(m)
    Pc = {a: np.array(b) for a, b in cuts.items()}
    large = defo not in ("PETIT",)

    def ref(t, u):
        xc = X+u[:, :3] if large else X
        regs = {r: regs0[r].copy() for r in regs0}
        regs[2][ti] += lam(t, lmax)*tip
        return ref_cuts(regs, xc, Pc)

    pre = "nu = NUME_DDL(MODELE=model, CHARGE=(bc, tip, grav))" if q else ""
    su2 = ["mesh = LIRE_MAILLAGE(UNITE=81, FORMAT='MED')"]
    return dict(tag=tag, mesh=m, setup=chr(10).join(su)+rest, setup_rmed=chr(10).join(su2)+rest, excit=ex, kind="noli",
                comp_kw=comp, large=large, fields=["DEPL", "SIEF_ELGA", "VARI_ELGA"], solve=solve, ranks=None, cuts=cuts,
                ref=ref, cara_impr=", CARA_ELEM=cara", lire_pre=pre,
                lire_kw=" CARA_ELEM=cara, NUME_DDL=nu," if q else " CARA_ELEM=cara,",
                plast=relation.startswith("VMIS"), Lref=L)


def summary(rows):
    """Worst error per route and variant, over steps and cuts."""
    out = {}
    for q in rows:
        k = (q["case"], q["route"], q["var"])
        a = out.setdefault(k, [0, 0, 0, 0])
        a[0] = max(a[0], q["eF"]); a[1] = max(a[1], q["eM"]); a[2] = max(a[2], q["tabF"]); a[3] = max(a[3], q["tabM"])
    for k, a in out.items():
        print("  %-22s %-3s %-7s worst eF=%.2e eM=%.2e | tab %.2e %.2e" % (*k, *a))
    sys.stdout.flush()


CASES = [("h20_petit", lambda t: nl_block(t)),
         ("h20_petit_r6", lambda t: nl_block(t, resi=1e-6)),
         ("t10_petit", lambda t: nl_block(t, "TETRA10", (10, 2, 4))),
         ("h8_petit", lambda t: nl_block(t, "HEXA8", (40, 8, 16))),
         ("h20_dist", lambda t: nl_block(t, distort=.1)),
         ("h20_log", lambda t: nl_block(t, defo="GDEF_LOG", lmax=7.)),
         ("h20_gl", lambda t: nl_block(t, defo="GREEN_LAGRANGE", relation="ELAS", lmax=7.)),
         ("h20_log_prs", lambda t: nl_block(t, defo="GDEF_LOG", press=2e6, lmax=7.)),
         ("dkt_vmis", lambda t: nl_shell(t, "QUAD4", "DKT", "PETIT")),
         ("c3d_elas", lambda t: nl_shell(t, "QUAD8", "COQUE_3D", "GROT_GDEP", relation="ELAS", lmax=20.)),
         ("c3d_vmis", lambda t: nl_shell(t, "QUAD8", "COQUE_3D", "GROT_GDEP"))]


def one(a):
    c = a[1]("n_"+a[0])
    rows, info = run_routes(c, routes=("A", "B", "C"))
    return c, rows, info


if __name__ == "__main__":
    flt = sys.argv[1:]
    todo = [a for a in CASES if not flt or a[0] in flt]
    all_r = []; infos = []
    with cf.ThreadPoolExecutor(4) as ex:
        for c, rows, info in ex.map(one, todo):
            summary(rows); all_r += rows; infos.append(info)
            print(info["case"], {k: (info[k]["err"], round(info[k]["wall"], 1)) for k in ("A", "P", "B", "C") if k in info},
                  info.get("rmed_MB"), info.get("base_MB"), flush=True)
    json.dump(dict(rows=all_r, info=infos), open(os.path.join(WD, "res_nl%s.json" % ("_"+flt[0] if flt else "")), "w"))
