# E7: route A as a user would write it in #ASTER-POST lines: pure command language, groups from
# DEFI_GROUP, after the bridge's own CALC_CHAMP has already put REAC_NODA in the result.
from e7_loads import *

c = load_case("r_a", distort=.15)
m = c["mesh"]
m.ma["L"] = [q for q, r in m.region.items() if r == 0]
m.ma["R"] = [q for q, r in m.region.items() if r == 2]
m.free_no = ("CUTA", "CUTB")
write_mail(os.path.join(WD, "r_a.mail"), m)
P = c["cuts"]
cuts_a, cuts_b = P["CUTA"], P["CUTB"]
POSTTXT = """
res = CALC_CHAMP(reuse=res, RESULTAT=res, FORCE=('REAC_NODA',))
mesh = DEFI_GROUP(reuse=mesh, MAILLAGE=mesh, CREA_GROUP_NO=(
    _F(NOM='NS', GROUP_MA='S'), _F(NOM='NL', GROUP_MA='L'), _F(NOM='NR', GROUP_MA='R'),
    _F(NOM='CUTA', INTERSEC=('NS', 'NL')), _F(NOM='CUTB', INTERSEC=('NS', 'NR'))))
rs = CALC_CHAMP(RESULTAT=res, GROUP_MA='S_SK', FORCE='REAC_NODA')
ta = POST_RELEVE_T(ACTION=_F(OPERATION='EXTRACTION', INTITULE='cutA', RESULTAT=rs, NOM_CHAM='REAC_NODA',
    GROUP_NO='CUTA', RESULTANTE=('DX', 'DY', 'DZ'), MOMENT=('DRX', 'DRY', 'DRZ'), POINT=%r, TOUT_ORDRE='OUI'))
tb = POST_RELEVE_T(ACTION=_F(OPERATION='EXTRACTION', INTITULE='cutB', RESULTAT=rs, NOM_CHAM='REAC_NODA',
    GROUP_NO='CUTB', RESULTANTE=('DX', 'DY', 'DZ'), MOMENT=('DRX', 'DRY', 'DRZ'), POINT=%r, TOUT_ORDRE='OUI'))
OUT['ta'] = {k: v[0] for k, v in ta.EXTR_TABLE().values().items() if k.startswith(('RESULT', 'MOMENT'))}
OUT['tb'] = {k: v[0] for k, v in tb.EXTR_TABLE().values().items() if k.startswith(('RESULT', 'MOMENT'))}
""" % (tuple(P["CUTA"]), tuple(P["CUTB"]))
txt = comm_first(c, "P").replace(chr(10)+"finish()"+chr(10), chr(10)+POSTTXT+chr(10)+"finish()"+chr(10))
r = run_aster("r_a", txt, mail="r_a.mail")
print(r["errors"])
ref = c["ref"](1, None)
for cut, key in (("CUTA", "ta"), ("CUTB", "tb")):
    d = r["data"][key]
    F = np.array([d.get("RESULT_"+q, 0.) for q in "XYZ"]); M = np.array([d.get("MOMENT_"+q, 0.) for q in "XYZ"])
    print(cut, errors(F, M, *ref[cut], L))

# the same with a hex8 mesh turned quadratic inside the run: the cut then has nodes the .mail
# does not know, so the groups must come from DEFI_GROUP in that run
c = load_case("r_lq", "HEXA8", (20, 4, 8), .3)
m = c["mesh"]
m.ma["L"] = [q for q, r in m.region.items() if r == 0]
m.ma["R"] = [q for q, r in m.region.items() if r == 2]
m.free_no = ("CUTA", "CUTB")
write_mail(os.path.join(WD, "r_lq.mail"), m)
c["setup"] = c["setup"].replace("mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')",
                                "mesh0 = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')" + chr(10) +
                                "mesh = CREA_MAILLAGE(MAILLAGE=mesh0, LINE_QUAD=_F(TOUT='OUI'))")
P = c["cuts"]
POSTTXT2 = POSTTXT.replace(repr(tuple(cuts_a)), repr(tuple(P["CUTA"]))).replace(repr(tuple(cuts_b)), repr(tuple(P["CUTB"])))
POSTTXT2 += "OUT['n'] = [len(mesh.getNodes('CUTA')), len(mesh.getNodes('CUTB')), mesh.getNumberOfNodes()]" + chr(10)
txt = comm_first(c, "P").replace(chr(10)+"finish()"+chr(10), chr(10)+POSTTXT2+chr(10)+"finish()"+chr(10))
r = run_aster("r_lq", txt, mail="r_lq.mail")
print(r["errors"], r["data"]["n"] if r["data"] else None, len(m.no["CUTA"]), len(m.xyz))
ref = c["ref"](1, None)
for cut, key in (("CUTA", "ta"), ("CUTB", "tb")):
    d = r["data"][key]
    F = np.array([d.get("RESULT_"+q, 0.) for q in "XYZ"]); M = np.array([d.get("MOMENT_"+q, 0.) for q in "XYZ"])
    e = errors(F, M, *ref[cut], L)
    print(cut, e["eF"], e["eM"])
