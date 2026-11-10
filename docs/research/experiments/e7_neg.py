# E7 negative controls: a wrong setup must give a visible error, otherwise the small errors
# of the other runs prove nothing. Uses the files of e7_loads.py, e7_struct.py and e7_nl.py.
from e7_nl import *
from e7_loads import load_case
from e7_struct import shell_case

OUT_ROWS = []


def note(name, e=None, txt=""):
    if e is not None:
        s = "eF=%.3g eM=%.3g raw %.3g %.3g" % (e["eF"], e["eM"], e["rawF"], e["rawM"])
    else:
        s = ""
    print("%-46s %s %s" % (name, s, txt), flush=True)
    OUT_ROWS.append(dict(name=name, err=e, txt=txt))


def worst(rows, route=None, var=None, ranks=None):
    q = [r for r in rows if (route is None or r["route"] == route) and (var is None or r["var"] == var)
         and (ranks is None or r["rank"] in ranks)]
    return {k: max(r[k] for r in q) for k in ("eF", "eM", "rawF", "rawM")}


def reread(c, name, fields, setup_edit=None, kind=None, comp=None, excit=None, sel=None):
    """Route B on the existing .rmed of case c, with a deliberate change."""
    c2 = dict(c)
    if setup_edit:
        c2["setup"] = setup_edit(c["setup"])
    if kind:
        c2["kind"] = kind
    if comp is not None:
        c2["comp_kw"] = comp
    if excit:
        c2["excit"] = excit
    c2["tag"] = name
    t = comm_reread(c2, "B", fields)
    r = run_aster(name, t, mail=c["tag"]+".mail", med_in=c["tag"]+"_P.rmed", sel=sel or c["tag"]+"_sel.json")
    rows = []
    if r["data"]:
        c2["kind"] = c["kind"]
        compare(c2, "B", r, c["ranks"], rows)
    return rows, r


def linear():
    c = load_case("l_h20d", distort=.15)
    m = c["mesh"]; m.free_ma = ("S", "S_SK"); m.free_no = ("CUTA", "CUTB")
    X = m.X()
    a = np.load(os.path.join(WD, "l_h20d_A.npz"))
    R = a["A_REACSK_1"]
    ref = c["ref"](1, None)
    Pc = {k: np.array(v) for k, v in c["cuts"].items()}

    def ev(arr, cuts=None, sign=1):
        out = None
        for cut in ("CUTA", "CUTB"):
            i = np.array(m.no[cut])-1
            if cuts:
                i = np.array(cuts[cut])-1
            F, M = sum_about(sign*arr[i, :3], X[i], Pc[cut], sign*arr[i, 3:6])
            e = errors(F, M, *ref[cut], L)
            out = e if out is None else {k: max(out[k], e[k]) for k in e}
        return out

    note("baseline REAC_NODA on S + skin", ev(R))
    note("sign flipped", ev(R, sign=-1))
    note("FORC_NODA, load not removed", ev(a["A_FORC_1"]))
    note("REAC_NODA on S without its skin cells", ev(a["A_REAC_1"]))
    note("whole model, no GROUP_MA", ev(a["ALLREAC"] if "ALLREAC" in a.files else 0*R))
    corner = {}
    mid = set()
    for c_ in m.ma["S"]:
        mid.update(m.cells[c_-1][1][8:])
    for cut in ("CUTA", "CUTB"):
        corner[cut] = [n for n in m.no[cut] if n not in mid]
    note("midside nodes left out of the cut", ev(R, cuts=corner))
    # second run with other data than the first
    rows, r = reread(c, "n_E2_d", ["DEPL"], lambda s: s.replace("E=%r," % E0, "E=%r," % (2*E0)))
    note("route B, E x 2, DEPL only", worst(rows, var="REACSK") if rows else None, str(r["errors"]))
    rows, r = reread(c, "n_E2_s", ["DEPL", "SIEF_ELGA"], lambda s: s.replace("E=%r," % E0, "E=%r," % (2*E0)))
    note("route B, E x 2, DEPL + SIEF_ELGA", worst(rows, var="REACSK") if rows else None, str(r["errors"]))
    rows, r = reread(c, "n_noload", ["DEPL", "SIEF_ELGA"], excit="(_F(CHARGE=bc),)")
    note("route B, loads forgotten in EXCIT", worst(rows, var="REACSK") if rows else None, str(r["errors"]))
    # mesh from the .rmed, cells taken by their number in the .mail
    c3 = dict(c); c3["tag"] = "n_ids"
    t = comm_reread(c3, "Bm", ["DEPL", "SIEF_ELGA"], mesh_from="rmed").replace("set_groups(mesh, True)", "set_groups(mesh, False)")
    r = run_aster("n_ids", t, med_in="l_h20d_P.rmed", sel="l_h20d_sel.json")
    rows = []
    if r["data"]:
        compare(c3, "Bm", r, [1], rows)
        note("mesh from .rmed, cell numbers of the .mail", worst(rows, var="REACSK"), str(r["errors"]))
    else:
        note("mesh from .rmed, cell numbers of the .mail", None, "run failed: "+str(r["errors"]))
    # tie: cut found from shared nodes only, so cut B does not exist
    c = load_case("l_tie", tie=True)
    m = c["mesh"]; a = np.load(os.path.join(WD, "l_tie_A.npz")); R = a["A_REACSK_1"]
    i = np.array(m.no["CUTA"])-1
    Fa = R[i, :3].sum(axis=0)
    Ls = c["regs"][1].sum(axis=0)
    inner = np.ones(len(R), bool); inner[i] = False
    note("tie at cut B: F_A + load on S, should be 0", None, "imbalance %.1f N of |F_A| %.1f N; largest force on a "
         "node outside the found cut %.1f N" % (np.linalg.norm(Fa+Ls), np.linalg.norm(Fa),
                                                np.linalg.norm(R[inner, :3], axis=1).max()))
    # shell without the nodal moments
    c = shell_case("b_dkt_q4_turn", "QUAD4", "DKT", g_turn)
    m = c["mesh"]; X = m.X(); a = np.load(os.path.join(WD, "b_dkt_q4_turn_A.npz")); R = a["A_REAC_1"]
    ref = c["ref"](1, None); Pc = {k: np.array(v) for k, v in c["cuts"].items()}
    out = {}
    for cut in ("CUTA", "CUTB"):
        i = np.array(m.no[cut])-1
        F, M = sum_about(R[i, :3], X[i], Pc[cut])
        e = errors(F, M, *ref[cut], L)
        out = e if not out else {k: max(out[k], e[k]) for k in e}
    note("shell, DRX DRY DRZ left out of the sum", out)
    rows, r = reread(c, "n_thick", ["DEPL"], lambda s: s.replace("EPAIS=%r" % T, "EPAIS=%r" % (2*T)))
    note("shell route B, thickness x 2, DEPL only", worst(rows, var="REAC") if rows else None, str(r["errors"]))


def nonlinear():
    c = nl_block("n_h20_petit")
    ref_rows = json.load(open(os.path.join(WD, "res_nl.json")))["rows"]
    # a linear re-read of a plastic result: what a rebuild from displacements would give
    rows, r = reread(c, "n_elas", ["DEPL"], kind="elas", setup_edit=lambda s: s)
    if rows:
        c2 = rows
    note("plastic result read as EVOL_ELAS, DEPL only", None, str(r["errors"]))
    if rows:
        for k in (4, 8, 12):
            q = [x for x in rows if x["rank"] == k and x["var"] == "REAC"]
            if q:
                note("  step %d" % k, {n: max(x[n] for x in q) for n in ("eF", "eM", "rawF", "rawM")})
    rows, r = reread(c, "n_depl", ["DEPL"])
    note("EVOL_NOLI, DEPL only", worst(rows, var="REAC") if rows else None, str(r["errors"]))
    rows, r = reread(c, "n_vari", ["DEPL", "SIEF_ELGA"])
    note("EVOL_NOLI, DEPL + SIEF_ELGA, no VARI_ELGA", worst(rows, var="REAC") if rows else None, str(r["errors"]))
    c = nl_block("n_h20_log", defo="GDEF_LOG", lmax=7.)
    rows, r = reread(c, "n_petit", ["DEPL", "SIEF_ELGA", "VARI_ELGA"],
                     comp=" COMPORTEMENT=_F(RELATION='VMIS_ISOT_LINE', DEFORMATION='PETIT'),")
    note("GDEF_LOG result read with DEFORMATION PETIT", worst(rows, var="REAC") if rows else None, str(r["errors"]))
    rows, r = reread(c, "n_nov", ["DEPL", "SIEF_ELGA"])
    note("GDEF_LOG, no VARI_ELGA", worst(rows, var="REAC") if rows else None, str(r["errors"]))
    q = [x for x in ref_rows if x["case"] == "n_h20_log" and x["route"] == "B" and x["var"] == "REAC"]
    if q:
        note("GDEF_LOG, POST_RELEVE_T moment (undeformed)", None, "eM %.3g against %.3g of the sum on x+u"
             % (max(x["tabM"] for x in q), max(x["eM"] for x in q)))
    # wrong step: the field of one step against the statics of another
    q = [x for x in ref_rows if x["case"] == "n_h20_petit" and x["route"] == "B" and x["var"] == "REAC"]
    a = {(x["rank"], x["cut"]): x for x in q}
    if (7, "CUTA") in a:
        e = errors(np.array(a[(7, "CUTA")]["F"]), np.array(a[(7, "CUTA")]["M"]), np.array(a[(8, "CUTA")]["Fx"]),
                   np.array(a[(8, "CUTA")]["Mx"]), L)
        note("step 7 against the statics of step 8", e)


if __name__ == "__main__":
    which = sys.argv[1:] or ["linear", "nonlinear"]
    if "linear" in which:
        linear()
    if "nonlinear" in which:
        nonlinear()
    json.dump(OUT_ROWS, open(os.path.join(WD, "res_neg_%s.json" % which[0]), "w"))
