# E7 probe: LIRE_RESU on COQUE_3D (QUAD9): which keyword makes CALC_CHAMP work after it.
from e7_struct import *
c = shell_case("p_c3d", "QUAD8", "COQUE_3D", g_turn)
rows, info = run_routes(c, routes=("P",))
c["lire_pre"] = "nu = NUME_DDL(MODELE=model, CHARGE=(bc, tip, grav))"
c["lire_kw"] = " CARA_ELEM=cara, NUME_DDL=nu,"
rows = []
r = run_aster("p_c3d_B", comm_reread(c, "B", ["DEPL"]), mail="p_c3d.mail", med_in="p_c3d_P.rmed", sel="p_c3d_sel.json")
print(r["errors"], r["rc"])
if r["data"]:
    compare(c, "B", r, c["ranks"], rows); show(rows)
