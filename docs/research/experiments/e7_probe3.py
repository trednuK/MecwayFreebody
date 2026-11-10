# E7 probe: are ELGA fields with sub-points (DKT) and beam fields really read back by LIRE_RESU?
# If the second run has E x 2 and the result follows E, the stress field was not used.
from e7_struct import *

for c in (shell_case("b_dkt_q4_turn", "QUAD4", "DKT", g_turn), beam_case("b_bme_grav", "POU_D_E", g_turn, load=("grav",))):
    tag = c["tag"]
    c2 = dict(c); c2["tag"] = "x"+tag
    c2["setup"] = c["setup"].replace("E=%r," % E0, "E=%r," % (2*E0))
    r = run_aster("x"+tag, comm_reread(c2, "B", ["DEPL", "SIEF_ELGA"]), mail=tag+".mail", med_in=tag+"_P.rmed", sel=tag+"_sel.json")
    rows = []
    if r["data"]:
        compare(c2, "B", r, [1], rows)
        print(tag, r["errors"], max(q["eF"] for q in rows if q["var"] == "REAC"), max(q["eM"] for q in rows if q["var"] == "REAC"))
    else:
        print(tag, r["errors"])
    mess = open(os.path.join(WD, "x"+tag+".mess"), encoding="utf-8", errors="replace").read()
    for ln in mess.splitlines():
        if "<A>" in ln and "MODELISA" not in ln:
            print("  ", ln.encode("ascii", "replace").decode()[:110])
