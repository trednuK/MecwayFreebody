# E7 route D for shells and beams: the API call stops there, so try CALCUL FORC_NODA_ELEM.
from e7_routed import *

CAL = r'''
lst = DEFI_LIST_REEL(VALE=(0., 1.))
u = res.getField("DEPL", 1); sig = res.getField("SIEF_ELGA", 1)
du = u - u
t = CALCUL(__use_namedtuple__=True, OPTION=("FORC_NODA_ELEM",), MODELE=model, CHAM_MATER=cm, CARA_ELEM=cara,
           INCREMENT=_F(LIST_INST=lst, NUME_ORDRE=1), EXCIT=_F(CHARGE=bc), DEPL=u, INCR_DEPL=du, SIGM=sig,
           COMPORTEMENT=_F(RELATION="ELAS"))
print("CAL", t)
v = t.FORC_NODA_ELEM
q = v.getElementaryTerms()
print("TERMS", len(q), q[0].getOption())
vals = q[0].getValues()
print("VALS", len(vals), len(vals[0]))
gr = q[0].getFiniteElementDescriptor().getListOfGroupsOfElements()
print("GRELS", [len(g)-1 for g in gr])
ARR["vals"] = np.array(vals[0]); ARR["cells"] = np.array(gr[0][:-1])
'''

for name, c in (("dkt", shell_case("e2_dkt", "QUAD4", "DKT", g_turn)),
                ("bme", beam_case("e2_bme", "POU_D_E", g_turn, load=("grav",))),
                ("c3d", shell_case("e2_c3d", "QUAD8", "COQUE_3D", g_turn))):
    tag = c["tag"]; m = c["mesh"]
    m.free_ma = ("S", "S_SK"); m.free_no = ("CUTA", "CUTB")
    write_mail(os.path.join(WD, tag+".mail"), m)
    t = comm_first(c, "P").replace(chr(10)+"finish()"+chr(10), chr(10)+CAL+chr(10)+"finish()"+chr(10))
    r = run_aster(tag, t, mail=tag+".mail")
    print(name, r["errors"], r["rc"])
    log = open(os.path.join(WD, tag+".log"), encoding="utf-8", errors="replace").read()
    for ln in log.splitlines():
        if ln.startswith(("CAL ", "TERMS", "VALS", "GRELS")) or "Error" in ln:
            print("  ", ln[:150].encode("ascii", "replace").decode())
    mess = open(os.path.join(WD, tag+".mess"), encoding="utf-8", errors="replace").read()
    i = mess.find("<EXCEPTION>")
    if i >= 0:
        print(mess[i:i+500].encode("ascii", "replace").decode())
    if r["npz"] is not None and "vals" in r["npz"].files:
        print("  sum", r["npz"]["vals"].shape, r["npz"]["cells"].shape)
