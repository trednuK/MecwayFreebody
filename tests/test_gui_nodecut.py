# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_nodecut.py
# The panel's part of a cut by nodes on a plane, without Windows Forms: the
# start of the run with the prepare hook of fb_aster, the filter on the result,
# the two sides, a partial section, texts, drawing and arrows. On the bar of
# test_gui_model (5 x 2 x 2 hex20, 0.2 x 0.02 x 0.04 m) with a
# stand-in for Code-Aster. Run from test_gui_logic.main(), in CPython 3 and in
# Mecway's IronPython. The stand-in gives each node the force of the side of
# the selection (test_gui_support.follow_up), so "opposite" and "equal to the
# element cut" hold by construction here: these tests check the plumbing
# (side, plan, normal, filter, texts); the physics is in test_nodecut_e2e.

import test_gui_support as sup

import fb_aster
import fb_core
import fb_gui
import fb_mecway
import fb_nodecut

X_CUT = 0.08            # between the cells i = 1 and i = 2
X_BACK = 0.12           # the back of the layer i = 2


def _bar():
    return sup.make_mesh("hex20")[1]


def _full(mesh):
    return sup.nodes_at(mesh, X_CUT)


def _top(mesh):
    """The upper half of the section: the nodes close no body."""
    return sup.nodes_at(mesh, X_CUT, lambda y, z: z > -1e-9)


def _right(mesh):
    return sorted(e for e, (s, nids) in mesh["elements"].items()
                  if min(mesh["nodes"][n][0] for n in nids) > X_CUT - 1e-9)


def _model(mesh, nids, side=1, lang="en", axes="global"):
    """A PanelModel as the window makes it: plan_and_start, job.result(),
    assign_nodes, load. Returns (model, cut, box)."""
    box = {}
    real = fb_aster.start
    fb_aster.start = sup.start_hook(box, polls=0)
    try:
        plan, geos, job, cut = fb_gui.plan_and_start(
            mesh, nids, "nodes", side, None, sup.manifest("x"), u"folder", u"exe")
    finally:
        fb_aster.start = real
    result = job.result()
    per = fb_core.assign_nodes(plan, mesh, result)
    model = fb_gui.PanelModel()
    model.lang, model.axes = lang, axes
    model.load(mesh, plan, geos, result, per, sup.manifest("x"), u"folder", nodecut=cut)
    box["job_used"] = job
    return model, cut, box


def _elements_model(mesh, eids, axes="global"):
    box = {}
    real = fb_aster.start
    fb_aster.start = sup.start_hook(box, polls=0)
    try:
        plan, geos, job, cut = fb_gui.plan_and_start(
            mesh, eids, "elements", 1, None, sup.manifest("x"), u"folder", u"exe")
    finally:
        fb_aster.start = real
    result = job.result()
    per = fb_core.assign_nodes(plan, mesh, result)
    model = fb_gui.PanelModel()
    model.axes = axes
    model.load(mesh, plan, geos, result, per, sup.manifest("x"), u"folder")
    return model, cut


# ---- starting the run: the prepare hook of fb_aster --------------------------------
def test_fb_aster_has_the_hook(r):
    code = getattr(fb_aster.start, "__code__", None) or fb_aster.start.func_code
    r.check("fb_aster.start takes prepare",
            "prepare" in code.co_varnames[:code.co_argcount], code.co_varnames)


def test_elements_start_as_before(r):
    """An element cut calls start with the five arguments it always had."""
    seen = []

    def five(man, folder, plan, mesh, exe):
        seen.append(exe)
        return "job"
    real = fb_aster.start
    fb_aster.start = five
    try:
        out = fb_gui.plan_and_start(_bar(), _right(_bar()), "elements", 1, None,
                                    sup.manifest("x"), u"f", u"exe")
    finally:
        fb_aster.start = real
    r.check("element cut: no prepare", out[2] == "job" and seen == [u"exe"] and out[3] is None)


def test_start_with_hook(r):
    """The filter runs in Job.result() before link_nodes and judge_rest (the
    real ones), so on_cut is judged over the kept nodes."""
    mesh = _bar()
    model, cut, box = _model(mesh, _top(mesh))
    job = box["job_used"]
    r.check("hook: the job itself", job is box["job"])
    r.check("prepare given", box["prepare"] is not None)
    r.check("prepare ran once", job.prepared == 1 and job.result() is job.result(), job.prepared)
    on_cut = model.result["on_cut"][model.rank]
    r.check("on_cut judged after the filter", "valid" not in on_cut and "cuts" in on_cut, on_cut)
    r.check("filtered", len(model.result["nodes"]) == len(cut["keep"]))
    xyz = set(q["xyz"] for q in model.result["nodes"])
    r.check("the back of the layer is left out",
            all(abs(p[0] - X_BACK) > 1e-9 for p in xyz))
    r.check("flags of the filter", model.result["nodecut"]["partial"] is True)
    rest = model.result["rest"][model.rank]
    r.check("judge_rest: a partial rest has no count", rest["valid"] is False and
            rest["count"] is None, rest)
    state, title, text = model.equilibrium()
    r.check("no unknown on_cut", u"cannot be told" not in text, text)
    r.check("a rest without count is no equilibrium", state == "none", state)
    model.result["on_cut"][model.rank]["valid"] = False
    r.check("an on_cut step marked not valid is said",
            u"cannot be told" in model.equilibrium()[2], model.equilibrium()[2])


def test_node_mismatch_from_result(r):
    """A full section that loses a node is refused out of job.result()."""
    mesh = _bar()
    cut = fb_nodecut.plan_from_nodes(mesh, _full(mesh), 1)
    # a run of another selection: the back of its slice is no cut node here
    wrong = sup.follow_up(mesh, sup.selected_slice(), judged=False)
    job = sup.HookJob(wrong, lambda res: fb_nodecut.filter_result(res, cut), polls=0,
                      plan=cut["plan"], mesh=mesh)
    try:
        job.result()
        r.check("node_mismatch", False, "no refusal")
    except fb_core.Refused as e:
        r.check("node_mismatch", e.code == "node_mismatch", e.code)
        text = fb_gui.reason_text(e.code, "nl", e.detail, mode="nodes")
        r.check("Dutch text of node_mismatch",
                text.startswith(u"De knopen van de vervolgrun passen niet") and
                e.detail in text, text)
    text = fb_gui.reason_text("node_mismatch", "en", u"x", mode="nodes")
    r.check("English text of node_mismatch", u"selected nodes" in text, text)
    r.check("element cut keeps its own text",
            fb_gui.reason_text("node_mismatch", "en", u"x") ==
            fb_gui.tx("r_node_mismatch", "en").format(u"x"))


# ---- full section and the two sides ------------------------------------------------
def test_full_is_the_element_cut(r):
    mesh = _bar()
    nodes, cut, _ = _model(mesh, _full(mesh), side=1)
    elements, none = _elements_model(mesh, _right(mesh))
    r.check("full section", not cut["partial"] and cut["rest_valid"])
    r.check("same body", sorted(cut["elements"]) == _right(mesh))
    r.check("element cut has no nodecut", none is None and elements.nodecut is None)
    r.check("one cut each", len(nodes.cuts) == 1 and len(elements.cuts) == 1)
    a = nodes.components(nodes.cuts[0])
    b = elements.components(elements.cuts[0])
    for k in range(6):
        r.close("full = elements, component {0}".format(k), a[k], b[k], 1e-12)
    r.check("equilibrium shown", nodes.equilibrium()[0] == "ok", nodes.equilibrium())


def test_other_side_is_opposite(r):
    mesh = _bar()
    plus, cut_p, _ = _model(mesh, _full(mesh), side=1)
    minus, cut_m, _ = _model(mesh, _full(mesh), side=-1)
    r.check("both full", not cut_p["partial"] and not cut_m["partial"])
    c1, c2 = plus.cuts[0], minus.cuts[0]
    for k in range(3):
        r.close("same neutral point {0}".format(k), c1["geo"]["centroid"][k],
                c2["geo"]["centroid"][k], 1e-12)
    a, b = plus.components(c1), minus.components(c2)
    r.check("not zero", max(abs(v) for v in a) > 1.0, a)
    for k in range(6):
        r.close("opposite, global {0}".format(k), a[k], -b[k], 1e-12)
    plus.axes = minus.axes = "section"
    r.close("N the same at both sides", plus.components(c1)[0], minus.components(c2)[0], 1e-12)
    r.check("normals opposite", all(abs(cut_p["normal"][k] + cut_m["normal"][k]) < 1e-12
                                    for k in range(3)))
    r.check("plane normal fixed", cut_p["plane"]["normal"] == cut_m["plane"]["normal"])


def test_side_in_table_and_sign(r):
    mesh = _bar()
    model, cut, _ = _model(mesh, _full(mesh), side=-1)
    r.check("row names the side", model.rows()[0][0] == u"1  ·  side −", model.rows()[0][0])
    sign = model.sign_text()
    r.check("sign names the normal", u"n = (1; 0; 0)" in sign, sign)
    r.check("sign names the side", u"side −, against n" in sign, sign)
    r.check("sign says the other side is opposite", u"exactly opposite" in sign, sign)
    model.lang = "nl"
    r.check("Dutch row", model.rows()[0][0] == u"1  ·  kant −", model.rows()[0][0])
    r.check("Dutch sign", u"tegengestelde" in model.sign_text() and
            u"kant −, tegen n in" in model.sign_text(), model.sign_text())
    model.lang = "en"
    rows = model.copy_rows()
    flat = [u"{0}".format(c) for row in rows for c in row]
    r.check("copy names the cut by nodes", u"Cut by nodes on a plane" in flat, rows[:8])
    r.check("copy names side and normal", u"side −" in flat and u"normal n (1; 0; 0)" in flat,
            rows[:8])
    r.check("copy rows still parse", fb_core.table_text(rows, u".").count(u"\r\n") == len(rows))
    plus, _, _ = _model(mesh, _full(mesh), side=1)
    r.check("side +", u"side +, where n points" in plus.sign_text(), plus.sign_text())


def test_drawing_plane(r):
    mesh = _bar()
    for side, toward in ((1, False), (-1, True)):
        model, cut, _ = _model(mesh, _full(mesh), side=side)
        view = model.view()
        mark = view.get("plane")
        r.check("side {0}: plane in the drawing".format(side), mark is not None)
        r.check("side {0}: normal {1}".format(side, "toward the viewer" if toward else "inward"),
                mark["toward"] is toward, mark)
        r.check("side {0}: text".format(side),
                u"n = (1; 0; 0)" in mark["text"] and
                (u"toward you" if toward else u"into the picture") in mark["text"] and
                u"side {0}".format(fb_gui.side_sign(side)) in mark["text"], mark["text"])
        plain = dict(view)
        plain.pop("plane")
        m1 = fb_gui.view_map(view, 600.0, 500.0)
        m0 = fb_gui.view_map(plain, 600.0, 500.0)
        r.check("side {0}: room under the title".format(side),
                m1["oy"] > m0["oy"] and m1["s"] <= m0["s"], (m1, m0))
    elements, _ = _elements_model(mesh, _right(mesh))
    r.check("no plane for an element cut", "plane" not in elements.view())


# ---- a partial section ---------------------------------------------------------------
def test_partial_section(r):
    mesh = _bar()
    model, cut, _ = _model(mesh, _top(mesh), side=1)
    r.check("partial", cut["partial"] and "partial_section" in cut["warnings"])
    state, title, text = model.equilibrium()
    r.check("no equilibrium shown", state == "none", state)
    r.check("title says partial", title == fb_gui.tx("eq_partial", "en"), title)
    for words in (u"close no body", u"force through the plane at these nodes",
                  u"edge nodes carry part", u"tie, support or contact in that layer stays unseen",
                  u"Area and centroid do not fit"):
        r.check("rule 7: " + words, words in text, text)
    lines = model.warning_lines()
    r.check("warning partial_section once",
            sum(1 for line in lines if line.startswith(u"Partial section")) == 1, lines)
    r.check("rest of a partial is never ok", model.result["rest"][model.rank]["valid"] is False)
    model.lang = "nl"
    state, title, text = model.equilibrium()
    r.check("Dutch partial", title.startswith(u"Deeldoorsnede") and
            u"de knopen sluiten geen lichaam af" in text.lower() and
            u"randknopen" in text and u"tie" in text, text)
    r.check("Dutch drawing says partial", u"deeldoorsnede" in model.view()["plane"]["text"])
    model.lang = "en"
    copy = [u"{0}".format(c) for row in model.copy_rows() for c in row]
    r.check("copy says partial", u"partial section" in copy)
    r.check("copy has the partial text", fb_gui.tx("eq_partial", "en") in copy)


def test_partial_by_result_flag(r):
    """A result marked by the filter is partial even without the cut."""
    mesh = _bar()
    model, cut, _ = _model(mesh, _top(mesh), side=1)
    model.nodecut = None
    r.check("flag of the result", model.partial())
    r.check("still no equilibrium", model.equilibrium()[0] == "none")
    full, _, _ = _model(mesh, _full(mesh))
    full.result["rest"][full.rank]["valid"] = False
    r.check("a rest marked not valid is no equilibrium", full.equilibrium()[0] == "none")


def test_arrows_on_the_reduced_plan(r):
    mesh = _bar()
    model, cut, _ = _model(mesh, _top(mesh), side=1)
    keep = set(cut["keep"])
    cuts = model.arrow_cuts()
    on = set(n for c in cuts for n in c["nodes"])
    r.check("arrow nodes are the cut nodes", on == keep, (sorted(on - keep), sorted(keep - on)))
    values, lumped = fb_mecway.per_node_values(mesh, cuts)
    r.check("per node: only cut nodes", set(values) <= keep and values, sorted(values)[:5])
    r.check("nothing lumped", lumped == 0, lumped)
    back = set(sup.nodes_at(mesh, X_BACK))
    r.check("none at the back of the layer", not (set(values) & back))
    bottom = set(sup.nodes_at(mesh, X_CUT, lambda y, z: z < -1e-9))
    r.check("none on the lower half", not (set(values) & bottom))
    values, places = fb_mecway.resultant_values(mesh, cuts)
    r.check("resultant on a cut node", set(values) <= keep and len(places) == len(cuts))


def test_resultant_of_a_full_node_section(r):
    """Resultant mode on a full section, as the user had it: one arrow, on the
    centre node of the section, with the sum of the cut; that node lies inside
    the solid and the text says so. A write per node afterwards removes the
    resultant's moment (a solid has no nodal moments)."""
    m, mesh = sup.make_mesh("hex20")
    model, cut, _ = _model(mesh, _full(mesh), side=1)
    cuts = model.arrow_cuts()
    r.check("one cut, arrays of one length", len(cuts) == 1 and
            len(cuts[0]["nodes"]) == len(cuts[0]["points"]) == len(cuts[0]["forces"]),
            [(len(c["nodes"]), len(c["points"]), len(c["forces"])) for c in cuts])
    values, places = fb_mecway.resultant_values(mesh, cuts)
    centre = [n for n in _full(mesh) if abs(mesh["nodes"][n][1]) < 1e-9 and
              abs(mesh["nodes"][n][2]) < 1e-9]
    r.check("on the centre node of the section", list(values) == centre and
            places[0]["node"] == centre[0] and places[0]["distance"] < 1e-12,
            (sorted(values), centre, places))
    r.check("that node is inside the solid", places[0]["inside"] is True, places)
    sol = sup.FakeSolution(m)
    mw = sup.FakeMw(m)
    own, out = {}, {}
    for _ in fb_mecway.arrow_steps(mw, sol, values, own, out, time=model.step_time()):
        pass
    r.check("force and moment written", sorted(out["written"]) == ["force", "moment"], out)
    nid = centre[0]
    s = model.sum6(model.cuts[0])
    for k, field in enumerate(fb_mecway.FIELDS_FORCE + fb_mecway.FIELDS_MOMENT):
        got = sol.node_value(field, nid)
        r.close("{0} on node {1} is the sum".format(field, nid), got, s[k], 1e-9)
        others = [n for n in sorted(mesh["nodes"]) if n != nid and
                  sol.node_value(field, n) is not None]
        r.check(field + ": no other node", not others, others[:5])
    lines = fb_gui.arrow_report(out, fb_gui.arrow_lines(places, 0, model.rank, "en", u"."),
                                "en", fb_gui.UNITS[0], u".")
    r.check("text names the node and that it is inside",
            any(u"stands on node {0}".format(nid) in t for t in lines) and
            any(u"Cut 1: node {0} lies inside the solid".format(nid) in t for t in lines),
            lines)
    nl = fb_gui.arrow_lines(places, 0, model.rank, "nl", u",")
    r.check("Dutch: inside", any(u"ligt binnen in het volume" in t for t in nl), nl)
    places[0]["inside"] = False
    r.check("an outside node gets no such line", not any(
        u"inside the solid" in t for t in fb_gui.arrow_lines(places, 0, 1, "en", u".")))
    values, lumped = fb_mecway.per_node_values(mesh, cuts)
    out = {}
    for _ in fb_mecway.arrow_steps(mw, sol, values, own, out, time=model.step_time()):
        pass
    r.check("per node then: moment removed", out["cleared"] == ["moment"], out)
    r.check("no old moment arrow left", all(sol.node_value(f, nid) is None
                                            for f in fb_mecway.FIELDS_MOMENT))


def test_selected_not_cut(r):
    """A step in the bar: the upper cells left of the plane are missing, so the
    selected nodes on the free part of the plane carry no force."""
    mesh = _bar()
    for e in [e for e, (s, nids) in mesh["elements"].items()
              if max(mesh["nodes"][n][0] for n in nids) < X_CUT + 1e-9 and
              min(mesh["nodes"][n][2] for n in nids) > -1e-9]:
        del mesh["elements"][e]
        del mesh["component"][e]
    model, cut, _ = _model(mesh, _full(mesh), side=1)
    r.check("still full", not cut["partial"], cut["warnings"])
    r.check("selected_not_cut", cut["not_cut"] and "selected_not_cut" in cut["warnings"])
    lines = model.warning_lines()
    named = [line for line in lines if line.startswith(u"Selected nodes the rest does not share")]
    r.check("warning names the nodes", len(named) == 1 and
            u"{0}".format(cut["not_cut"][0]) in named[0], lines)
    model.lang = "nl"
    r.check("Dutch warning", any(line.startswith(u"Geselecteerde knopen die de rest niet deelt")
                                 for line in model.warning_lines()), model.warning_lines())


# ---- refusals ------------------------------------------------------------------------
NODE_CODES = ("empty", "unknown_node", "nodes_collinear", "nodes_without_solid",
              "nodes_not_planar", "shell_or_beam", "plane_through_elements", "side_empty",
              "no_cut", "node_mismatch")


def test_refusal_texts(r):
    for code in NODE_CODES:
        for lang in ("nl", "en"):
            text = fb_gui.reason_text(code, lang, u"DETAIL", mode="nodes")
            generic = fb_gui.tx("r_error", lang).format(u"{0} DETAIL".format(code))
            r.check("text of {0} in {1}".format(code, lang), text and text != generic, text)
        nl = fb_gui.reason_text(code, "nl", u"", mode="nodes")
        en = fb_gui.reason_text(code, "en", u"", mode="nodes")
        r.check("{0}: Dutch and English differ".format(code), nl != en, nl)
    r.check("empty in node mode asks for nodes",
            u"knopen" in fb_gui.reason_text("empty", "nl", mode="nodes") and
            u"nodes" in fb_gui.reason_text("empty", "en", mode="nodes"))
    r.check("empty of elements unchanged",
            fb_gui.reason_text("empty", "en") == fb_gui.tx("r_empty", "en"))
    for key in ("w_partial_section", "w_selected_not_cut", "eq_partial", "eq_partial2",
                "side_button", "side_tip", "sel_nodes_n", "d_plane", "nc_sign"):
        nl, en = fb_gui.T[key]
        r.check("text " + key, nl and en and nl != en, key)
    r.check("mode choice no longer to come", u"(" not in fb_gui.tx("mode_nodes", "en"))


def test_real_refusals_have_texts(r):
    """The refusals fb_nodecut really gives on the bar reach a text of their own."""
    mesh = _bar()
    full = _full(mesh)
    line = [n for n in full if abs(mesh["nodes"][n][1]) < 1e-9 and abs(mesh["nodes"][n][2]) < 1e-9]
    line += [n for n in full if abs(mesh["nodes"][n][1]) < 1e-9][:2]
    lonely = max(mesh["nodes"]) + 1
    mesh_lonely = dict(mesh)
    mesh_lonely["nodes"] = dict(mesh["nodes"])
    mesh_lonely["nodes"][lonely] = (X_CUT, 0.5, 0.5)
    middle = sup.nodes_at(mesh, 0.10)
    cases = (("nodes_collinear", mesh, sorted(set(line))),
             ("nodes_collinear", mesh, full[:2]),
             ("nodes_without_solid", mesh_lonely, full + [lonely]),
             ("nodes_not_planar", mesh, full + sup.nodes_at(mesh, X_BACK)[:1]),
             ("plane_through_elements", mesh, middle),
             ("side_empty", mesh, sup.nodes_at(mesh, 0.2)),
             ("unknown_node", mesh, full + [lonely + 7]))
    for code, m, nids in cases:
        side = 1
        try:
            fb_gui.plan_and_start(m, nids, "nodes", side, None, sup.manifest("x"), u"f", u"e")
            r.check("refused: " + code, False, "no refusal")
        except fb_core.Refused as e:
            r.check("refused: " + code, e.code == code, (e.code, e.detail))
            for lang in ("nl", "en"):
                text = fb_gui.reason_text(e.code, lang, e.detail, mode="nodes")
                r.check("{0} in {1}: own text with detail".format(code, lang),
                        text == fb_gui.tx("r_" + code, lang).format(e.detail), text)


# ---- selection and mode ------------------------------------------------------------
def test_selection_of_nodes(r):
    m = sup.models.block("hex20")[0]
    mw = sup.FakeMw(m, selected=[9, 10])
    mw.selected_node_list = [5, 3, 4]
    sel = fb_mecway.read_selection(mw)
    r.check("node ids read", sel["node_ids"] == [5, 3, 4] and sel["nodes"] == 3, sel)
    r.check("elements still read", sel["elements"] == [9, 10])
    r.check("chosen: elements", fb_gui.chosen_ids(sel, "elements") == [9, 10])
    r.check("chosen: nodes", fb_gui.chosen_ids(sel, "nodes") == [5, 3, 4])
    r.check("key sorted", fb_gui.selection_key(sel, "nodes") == ("nodes", [3, 4, 5]))
    r.check("no selection", fb_gui.selection_key(None, "nodes") is None and
            fb_gui.chosen_ids(None, "nodes") == [])

    class Broken(sup.FakeMw):
        def selected_nodes(self):
            raise RuntimeError("no nodes here")

    class Holder(object):
        def selected_elements(self):
            return []

        def selected_nodes(self):
            return [7]
    sel = fb_mecway.read_selection(Broken(m, selected=[1]), Holder())
    r.check("nodes of the solution when the model has none", sel["node_ids"] == [7], sel)
    sel = fb_mecway.read_selection(Broken(m, selected=[1]))
    r.check("a failing selected_nodes is no nodes", sel["node_ids"] == [] and
            sel["elements"] == [1], sel)


def test_basis(r):
    mesh = _bar()
    model, cut, _ = _model(mesh, _top(mesh))
    r.check("basis of a node cut", model.basis() == ("nodes", 1, sorted(_top(mesh))))
    other, _, _ = _model(mesh, _full(mesh), side=-1)
    r.check("the side is in the basis", other.basis()[:2] == ("nodes", -1))
    elements, _ = _elements_model(mesh, _right(mesh))
    r.check("basis of an element cut", elements.basis() == ("elements", 0, _right(mesh)))
    r.check("empty model", fb_gui.PanelModel().basis() is None)


def test_plan_and_start_elements(r):
    mesh = _bar()
    box = {}
    real = fb_aster.start
    fb_aster.start = sup.start_hook(box)
    try:
        plan, geos, job, cut = fb_gui.plan_and_start(
            mesh, _right(mesh), "elements", 1, None, sup.manifest("x"), u"f", u"e")
    finally:
        fb_aster.start = real
    r.check("elements: no cut, no prepare", cut is None and box["prepare"] is None)
    r.check("elements: the plan of plan_cuts",
            plan["cut_nodes"] == fb_core.plan_cuts(mesh, _right(mesh))["cut_nodes"])
    try:
        fb_gui.plan_and_start(mesh, list(mesh["elements"]), "elements", 1, None,
                              sup.manifest("x"), u"f", u"e")
        r.check("everything selected: no cut", False)
    except fb_core.Refused as e:
        r.check("everything selected: no cut", e.code == "no_cut", e.code)


def main():
    report = sup.Report()
    report.run(globals())
    return report
