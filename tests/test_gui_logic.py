# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_logic.py
# Panel logic without Windows Forms: numbers and texts, PanelModel, fb_mecway on
# a fake mw and solution, finding the bridge, the mw queue. The same tests run in
# CPython 3 and in Mecway's IronPython (test_gui_mecway_main.py).
#   python tests/test_gui_logic.py

import io
import math
import os
import re
import shutil
import sys
import tempfile

import test_gui_support as sup
from test_gui_support import FakeMw, FakeSolution, models

import fb_aster
import fb_core
import fb_gui
import fb_mecway


def _case(rest=None, large=False, shift=None, shape="hex20", extra=None, ranks=(1, 2)):
    m, mesh = sup.make_mesh(shape)
    plan = fb_core.plan_cuts(mesh, sup.selected_slice())
    geos = dict((g["id"], fb_core.section_geometry(mesh, g, None)) for g in plan["groups"])
    result = sup.make_result(plan, mesh, rest=rest, large=large, shift=shift, extra=extra,
                             ranks=ranks)
    per = fb_core.assign_nodes(plan, mesh, result)
    model = fb_gui.PanelModel()
    model.load(mesh, plan, geos, result, per, sup.manifest("x"), u"folder")
    return model, m, mesh, plan, result


def _direct(model, cut, point, rank=None):
    """A sum by hand, for comparison with the shifted one."""
    rank = model.rank if rank is None else rank
    where = fb_core.positions(model.result, rank)
    total = [0.0] * 6
    for i in cut["indices"]:
        x = where[i]
        f = model.result["forces"][rank][i]
        r = [x[k] - point[k] for k in range(3)]
        m = fb_gui._cross(r, f[:3])
        for k in range(3):
            total[k] += f[k]
            total[3 + k] += m[k]
    return total


# ---- numbers and texts -------------------------------------------------------------
def test_fmt(r):
    f = fb_gui.fmt
    r.check("fmt zero", f(0.0) == u"0")
    r.check("fmt comma", f(1234.5, u",") == u"1234,5", f(1234.5, u","))
    r.check("fmt grouped", f(1234567.0) == u"1\u2009234\u2009567", f(1234567.0))
    r.check("fmt minus", f(-2.5) == u"−2.5", f(-2.5))
    r.check("fmt small", u"10⁻" in f(1.2e-7, u","), f(1.2e-7, u","))
    r.check("fmt large", u"10¹²" in f(3.0e12), f(3.0e12))
    r.check("fmt none", f(None) == u"–")
    r.check("fmt 5 digits", f(123.456789) == u"123.46", f(123.456789))


def test_parse(r):
    p = fb_gui.parse_number
    r.close("point", p(u"1.5"), 1.5)
    r.close("comma", p(u"1,5"), 1.5)
    r.close("minus sign", p(u"−2,5"), -2.5)
    r.close("grouped", p(u"1\u2009234,5"), 1234.5)
    for bad in (u"", u"abc", u"1,2,3", u"nan", u"inf"):
        try:
            p(bad)
            r.check("refuses " + bad, False)
        except ValueError:
            r.check("refuses " + bad, True)


def test_clean(r):
    values = fb_gui.clean((1000.0, 1e-9, 0.0, 1e-8, 5.0, 2.0), 0.02)
    r.check("round-off force", values[1] == 0.0)
    r.check("round-off moment", values[3] == 0.0)
    r.check("value stays", values[0] == 1000.0 and values[4] == 5.0)
    r.check("all zero stays", fb_gui.clean((0.0,) * 6, 1.0) == [0.0] * 6)


def test_texts_complete(r):
    fields = re.compile(r"\{(\d*)\}")
    for key, pair in fb_gui.T.items():
        r.check("both languages " + key, len(pair) == 2 and all(pair), pair)
        r.check("same fields " + key,
                sorted(fields.findall(pair[0])) == sorted(fields.findall(pair[1])), pair)


def test_refusals_have_text(r):
    for code in fb_aster.REFUSE + ("empty", "stale", "unknown_element", "shell_or_beam", "shape",
                                   "no_cut", "no_aster", "path", "start", "run", "timeout",
                                   "stopped", "node_mismatch", "busy", "no_model",
                                   "mesh_changed"):
        for lang in fb_gui.LANGS:
            text = fb_gui.reason_text(code, lang, u"detail", u"17.4")
            r.check("refusal {0} {1}".format(code, lang),
                    ("r_" + code) in fb_gui.T and text, text)
    r.check("version names the version",
            u"17.4" in fb_gui.reason_text("version", "en", u"", u"17.4"))
    # start() gives the version of the run as the detail; _fail passes no version
    r.check("version from the detail",
            u"16.9" in fb_gui.reason_text("version", "en", u"16.9"),
            fb_gui.reason_text("version", "en", u"16.9"))
    for lang in fb_gui.LANGS:
        text = fb_gui.reason_text("launcher_version", lang, u"D:\\aster\\run_aster.bat")
        r.check("launcher: the setting, not the run " + lang,
                u"exe_aster" in text and u"run_aster.bat" in text and u"bin" in text, text)
        text = fb_gui.reason_text("run_version", lang)
        r.check("run without version: the bridge's launcher " + lang,
                u"exe_aster" in text and u".mess" in text, text)
    r.check("unknown code is shown", u"odd" in fb_gui.reason_text("odd", "nl"))


def test_warnings_have_text(r):
    for code in ("no_cut", "shell_or_beam_at_cut", "midside_not_shared", "edge_contact",
                 "E_missing", "mixed_deformation", "skin_on_cut", "non_planar", "large",
                 "mixed_cut", "mixed_shape", "edge_merge", "deformation", "solution_unknown",
                 "other_model"):
        r.check("warning " + code, ("w_" + code) in fb_gui.T)
    r.check("unknown warning is shown", fb_gui.warning_text("odd", "en") == u"odd")


def test_csv(r):
    rows = [[u"Cut", u"N [kN]"], [1, 2.5], [u"a;b", u'say "x"', u"two\r\nlines", None]]
    text = fb_gui.csv_text(rows, u",", u";")
    r.check("decimal comma", u"1;2,5\r\n" in text, text)
    r.check("list separator", text.startswith(u"Cut;N [kN]\r\n"), text)
    r.check("separator in a cell is quoted", u'"a;b"' in text, text)
    r.check("quote is doubled", u'"say ""x"""' in text, text)
    r.check("line end is quoted", u'"two\r\nlines"' in text, text)
    r.check("empty cell", text.endswith(u'lines";\r\n'), text)
    plain = fb_gui.csv_text([[1.5, u"a,b"]], u".", u",")
    r.check("comma separator quotes the comma", plain == u'1.5,"a,b"\r\n', plain)


# ---- the model ---------------------------------------------------------------------
def test_two_cuts(r):
    model, m, mesh, plan, result = _case()
    r.check("two cuts", len(model.cuts) == 2)
    a, b = model.cuts
    r.check("last step shown", model.rank == 2)
    r.close("cut 1 at x", a["geo"]["centroid"][0], 0.08)
    r.close("cut 2 at x", b["geo"]["centroid"][0], 0.12)
    r.close("area", a["geo"]["area"], 0.02 * 0.04, 1e-9)
    # opposite forces: the rest of the model holds the slice in balance
    sa, sb = model.sum6(a), model.sum6(b)
    r.close("forces cancel", sa[0] + sb[0], 0.0, 1e-9)
    direct = _direct(model, a, a["geo"]["centroid"])
    for k in range(6):
        r.close("neutral point sum {0}".format(k), sa[k], direct[k], 1e-9)


def test_tension_positive(r):
    model, m, mesh, plan, result = _case()
    for cut in model.cuts:
        n = cut["geo"]["normal"]
        s = model.sum6(cut)
        r.close("N is F along the outward normal",
                model.components(cut)[0], fb_gui._dot(s[:3], n), 1e-12)
    r.check("normals point out of the slice",
            model.cuts[0]["geo"]["normal"][0] < 0 < model.cuts[1]["geo"]["normal"][0])


def test_point_shift(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    model.set_point_shown((0.0, 3.0, -4.0))
    p = model.point_global(cut)
    direct = _direct(model, cut, p)
    s = model.sum6(cut)
    for k in range(6):
        r.close("shifted equals resummed {0}".format(k), s[k], direct[k], 1e-9)
    shown = model.point_shown(cut)
    r.close("typed back", shown[1], 3.0, 1e-9)
    r.close("typed back z", shown[2], -4.0, 1e-9)
    model.axes = "global"
    shown = model.point_shown(cut)
    r.close("global mm", shown[0], p[0] * 1e3, 1e-9)
    model.set_point_shown(shown)
    r.check("global point kept", cut["point"][0] == "global")
    p2 = model.point_global(cut)
    r.close("same place in space", p2[1], p[1], 1e-12)
    model.axes = "section"
    shown = model.point_shown(cut)
    r.close("back in section axes", shown[1], 3.0, 1e-9)
    model.set_neutral(cut)
    r.check("preset neutral", cut["point"] == fb_gui.NEUTRAL_POINT)


def test_drag(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    model.set_point_plane(0.004, -0.002)
    r.close("dragged u", cut["point"][1][1], 0.004, 1e-12)
    r.close("dragged v", cut["point"][1][2], -0.002, 1e-12)
    view = model.view()
    r.close("view has the point", view["point"][0], 0.004, 1e-12)
    w, h = 500.0, 400.0
    mp = fb_gui.view_map(view, w, h)
    x, y = fb_gui.to_pixel(mp, 0.004, -0.002)
    u, v = fb_gui.from_pixel(mp, x, y)
    r.close("pixel back u", u, 0.004, 1e-12)
    r.close("pixel back v", v, -0.002, 1e-12)
    r.check("grab near", fb_gui.near_point(mp, view, x + 5, y - 5))
    r.check("no grab far", not fb_gui.near_point(mp, view, x + 40, y))
    r.check("map inside the picture", 0 < x < w and 0 < y < h)


def test_small_map(r):
    model, m, mesh, plan, result = _case()
    view = model.view()
    for w, h in ((120.0, 90.0), (260.0, 160.0), (1600.0, 1200.0)):
        mp = fb_gui.view_map(view, w, h)
        for loop in view["loops"]:
            for u, v in loop:
                x, y = fb_gui.to_pixel(mp, u, v)
                r.check("outline fits {0}".format(w), -1 <= x <= w + 1 and -1 <= y <= h + 1,
                        (x, y))


def test_drag_in_global_axes(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    model.axes = "global"
    model.set_point_plane(0.004, -0.002)
    r.check("stored as a global point", cut["point"][0] == "global", cut["point"])
    view = model.view()
    r.close("still under the mouse u", view["point"][0], 0.004, 1e-12)
    r.close("still under the mouse v", view["point"][1], -0.002, 1e-12)
    model.axes = "section"
    model.set_point_plane(0.001, 0.002)
    r.check("section axes stay section", cut["point"][0] == "section")


def test_node_preset(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    nid = cut["group"]["nodes"][3]
    model.set_node(nid, cut)
    p = model.point_global(cut)
    x = mesh["nodes"][nid]
    for k in range(3):
        r.close("point on node {0}".format(k), p[k], x[k], 1e-12)
    r.check("nearest is that node", model.nearest_cut_node(cut) == nid)
    r.check("view names the node", u"node {0}".format(nid) in model.view()["about"])


def test_axes_switch_and_units(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    section = model.components(cut)
    model.axes = "global"
    glob = model.components(cut)
    r.check("names global", model.headers()[2].startswith(u"Fx"))
    r.close("force size stays", sum(v * v for v in section[:3]), sum(v * v for v in glob[:3]),
            1e-9)
    r.close("moment size stays", sum(v * v for v in section[3:]), sum(v * v for v in glob[3:]),
            1e-9)
    model.axes = "section"
    r.check("names section", model.headers()[2].startswith(u"N "))
    model.unit = "kN"
    r.check("unit in the head", u"[kN·m]" in model.headers()[-2], model.headers())
    model.lang = "nl"
    row = model.rows()[0]
    r.check("eight columns, no axes column for sections",
            len(row) == 8 and len(model.headers()) == 8 and not model.axes_column())
    r.check("comma in Dutch", u"," in u"".join(row), row)


def test_steps(r):
    model, m, mesh, plan, result = _case()
    cut = model.cuts[0]
    second = model.components(cut)
    model.rank = 1
    first = model.components(cut)
    r.close("step 2 is twice step 1", second[0], 2 * first[0], 1e-9)


def test_equilibrium(r):
    model, m, mesh, plan, result = _case()
    state, title, text = model.equilibrium()
    r.check("clean run is ok", state == "ok" and u"equilibrium" in title, title)
    r.check("sum and largest also when fine", u"sum F" in text, text)
    bad = {"sum": (0.0, 0.0, 2690.0, 0.0, 0.0, 0.0), "largest": 900.0, "cut_largest": 10.0,
           "count": 3, "where": [(0.1, 0.0, 0.02)]}
    model, m, mesh, plan, result = _case(rest=bad)
    state, title, text = model.equilibrium()
    r.check("a tie shows", state == "bad" and u"NOT" in title, title)
    r.check("sum and largest shown", u"sum F" in text and u"largest 900" in text, text)
    r.check("names the force", u"2\u2009690" in text or u"2690" in text, text)
    r.check("names the place", u"100" in text, text)
    r.check("the moment of the rest names its point",
            u"N·m about the origin (0; 0; 0)." in text, text)
    model.lang = "nl"
    r.check("Dutch", u"NIET" in model.equilibrium()[1])
    r.check("Dutch: point named", u"om de oorsprong" in model.equilibrium()[2])
    model.rank = 99
    r.check("step without rest", model.equilibrium()[0] == "none")


def test_check_solution_every_node_is_there(r):
    """More cut nodes than the sample of positions: a cut node the solution
    lacks (an older solution of a smaller mesh) is mesh_differs, never an
    IndexError while writing."""
    class Points(object):
        def __init__(self, count):
            self.count = count

        def all_nodes(self):
            return list(range(1, self.count + 1))

        def node(self, nid):
            if not 1 <= nid <= self.count:
                raise IndexError(nid)
            return sup.Vec((float(nid), 0.0, 0.0))
    model, solution = Points(4001), Points(4000)
    nids = list(range(1, 4002))
    nids[1], nids[4000] = nids[4000], nids[1]     # node 4001 off the sample of positions
    r.check("all there: fits", fb_mecway.check_solution(model, Points(4001), nids) is None)
    r.check("one missing: mesh differs",
            fb_mecway.check_solution(model, solution, nids) == "mesh_differs",
            fb_mecway.check_solution(model, solution, nids))


def test_rank_zero(r):
    """Rank 0 of a nonlinear run is no equilibrium: not shown first, no alarm."""
    bad = {"sum": (900.0, 0.0, 0.0, 0.0, 0.0, 0.0), "largest": 900.0, "cut_largest": 900.0,
           "count": 50, "where": [(0.1, 0.0, 0.02)]}
    model = _case(rest=bad, ranks=(0, 1, 2))[0]
    r.check("last step first", model.rank == 2)
    model.result["rest"][2] = {"sum": (0.0,) * 6, "largest": 1e-9, "cut_largest": 900.0,
                               "count": 0, "where": []}
    model.result["rest"][1] = model.result["rest"][2]
    r.check("last step is fine", model.equilibrium()[0] == "ok")
    model.rank = 0
    state, title, text = model.equilibrium()
    r.check("rank 0 is no alarm", state == "none", state)
    r.check("rank 0 says why", u"starting state" in title, title)


def test_copy_rows(r):
    model, m, mesh, plan, result = _case()
    r.check("copy names the version", model.copy_rows()[0] ==
            [fb_gui.PANEL_TITLE, fb_core.VERSION], model.copy_rows()[0])
    model.man = sup.manifest("x")
    text = fb_core.table_text(model.copy_rows(), u",")
    r.check("run in the copy", u"20261107_120000" in text)
    r.check("sign in the copy", u"outward" in text)
    r.check("equilibrium in the copy", u"In equilibrium" in text)
    head = [line for line in text.split(u"\r\n") if line.startswith(u"Cut\t")]
    r.check("one head", len(head) == 1, text)
    r.check("no decimal point in numbers",
            not re.search(r"\t-?\d+\.\d", text), text)


def test_translation_large(r):
    """All cut nodes move the same way: the neutral point goes along, and the
    moment about it does not change."""
    def move(p, rank):
        return (0.0, 0.0, 0.0) if rank == 1 else (0.01, 0.0, 0.03)
    plain = _case()[0]
    model = _case(large=True, shift=move)[0]
    for a, b in zip(plain.cuts, model.cuts):
        c0 = plain.frame(a)[0]
        c1 = model.frame(b)[0]
        r.close("neutral point moved x", c1[0], c0[0] + 0.01, 1e-9)
        r.close("neutral point moved z", c1[2], c0[2] + 0.03, 1e-9)
        s0, s1 = plain.components(a), model.components(b)
        for k in range(6):
            r.close("same numbers {0}".format(k), s1[k], s0[k], 1e-7)
    r.check("warning for large", any(w[1] == "large" for w in model.warnings))
    model.rank = 1
    r.close("step 1 not moved", model.frame(model.cuts[0])[0][0], 0.08, 1e-9)


def test_translation_beyond_an_element(r):
    """A shift of several elements along the normal: the sign of N must not flip
    (the core judges outward by nodes that are not in the result)."""
    def far(p, rank):
        return (0.0, 0.0, 0.0) if rank == 1 else (0.35, 0.0, 0.0)
    plain = _case()[0]
    model = _case(large=True, shift=far)[0]
    for a, b in zip(plain.cuts, model.cuts):
        r.close("normal unchanged", model.frame(b)[1][0][0], a["geo"]["normal"][0], 1e-9)
        r.close("N keeps its sign", model.components(b)[0], plain.components(a)[0], 1e-7)


def test_rotation_large(r):
    """The slice turns as a rigid body, also beyond 90 degrees: normal and axes
    turn along, so the numbers stay those of the section."""
    axes_of_turn = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
    for axis in axes_of_turn:
        for angle in (0.2, 1.4, 2.0, 3.0):
            name = "turn {0} about {1}: ".format(angle, axis)
            shift = sup.rigid_rotation(angle, (0.1, 0.0, 0.0), axis)
            model = _case(large=True, shift=shift)[0]
            for k in (0, 1):
                cut = model.cuts[k]
                c, axes = model.frame(cut, 2)
                old = cut["geo"]["axes"]
                for i in range(3):
                    turned = sup.rotate(old[i], angle, axis)
                    for j in range(3):
                        r.close(name + "axis {0}".format(i), axes[i][j], turned[j], 1e-8)
                r.close(name + "right handed",
                        fb_gui._dot(fb_gui._cross(axes[0], axes[1]), axes[2]), 1.0, 1e-9)
                s = model.sum6(cut, 2)
                r.close(name + "N along the turned normal", model.components(cut)[0],
                        fb_gui._dot(s[:3], axes[0]), 1e-12)
    model = _case(large=True, shift=sup.rigid_rotation(0.2, (0.1, 0.0, 0.0)))[0]
    cut = model.cuts[1]
    c, axes = model.frame(cut, 2)
    model.set_point_shown((0.0, 1.0, 0.0), cut)
    p = model.point_global(cut, 2)
    d = [p[k] - c[k] for k in range(3)]
    r.close("section point moves along", math.sqrt(sum(v * v for v in d)), 1e-3, 1e-9)


def test_non_planar(r):
    model, m, mesh, plan, result = _case()
    m2, mesh2 = sup.make_mesh()
    # a step in the selection: L shaped, so one cut with two planes
    plan2 = fb_core.plan_cuts(mesh2, sup.selected_slice() + [5])
    geos = dict((g["id"], fb_core.section_geometry(mesh2, g, None)) for g in plan2["groups"])
    r.check("a non-planar cut", any(not g["planar"] for g in geos.values()))
    result2 = sup.make_result(plan2, mesh2)
    per = fb_core.assign_nodes(plan2, mesh2, result2)
    model2 = fb_gui.PanelModel()
    model2.load(mesh2, plan2, geos, result2, per, sup.manifest("x"), u"f")
    cut = [c for c in model2.cuts if not c["geo"]["planar"]][0]
    model2.index = model2.cuts.index(cut)
    r.check("no N on it", model2.names(cut)[0] == u"Fx")
    r.check("marked in the table", model2.axes_short(cut) == u"global")
    r.check("warned", any(w[1] == "non_planar" for w in model2.warnings))
    view = model2.view()
    r.check("drawing has points", len(view["points"]) == len(cut["group"]["nodes"]))
    model2.set_point_plane(0.001, 0.002)
    r.close("drag on a projection", model2.view()["point"][0], 0.001, 1e-9)
    r.close("drag on a projection", model2.view()["point"][1], 0.002, 1e-9)


def test_added_midside_nodes(r):
    m, mesh = sup.make_mesh("hex8")
    plan = fb_core.plan_cuts(mesh, sup.selected_slice())
    group = plan["groups"][0]
    a, b = group["nodes"][0], [n for n in group["nodes"]][1]
    xa, xb = mesh["nodes"][a], mesh["nodes"][b]
    mid = tuple((xa[k] + xb[k]) / 2 for k in range(3))
    result = sup.make_result(plan, mesh, extra=[(mid, group["id"])])
    per = fb_core.assign_nodes(plan, mesh, result)
    geos = dict((g["id"], fb_core.section_geometry(mesh, g, None)) for g in plan["groups"])
    model = fb_gui.PanelModel()
    model.load(mesh, plan, geos, result, per, sup.manifest("x"), u"f")
    values, lumped = fb_mecway.per_node_values(mesh, model.arrow_cuts())
    r.check("added node is lumped", lumped == 1, lumped)
    r.close("no force lost", sum(v[0] for v in values.values()),
            sum(c["forces"][i][0] for c in model.arrow_cuts()
                for i in range(len(c["forces"]))), 1e-12)


# ---- fb_mecway on a fake ------------------------------------------------------------
def _exhaust(gen):
    count = 0
    for _ in gen:
        count += 1
    return count


def test_read_mesh(r):
    m, _, _ = models.block("hex20")
    mw = FakeMw(m)
    out = {}
    yields = _exhaust(fb_mecway.read_mesh_steps(mw, out, chunk=20))
    mesh = out["mesh"]
    r.check("nodes", len(mesh["nodes"]) == len(m.xyz))
    r.check("element", mesh["elements"][1] == ("hex20", m.elements[1][1]), mesh["elements"][1])
    r.check("component", mesh["component"][1] == u"Bar")
    r.check("yields between chunks", yields > 5, yields)
    r.check("floats", isinstance(mesh["nodes"][1][0], float))


def test_mesh_changes_while_reading(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    out = {}
    gen = fb_mecway.read_mesh_steps(mw, out, chunk=5)
    next(gen)
    m.xyz[max(m.xyz) + 1] = (9.0, 9.0, 9.0)
    try:
        _exhaust(gen)
        r.check("edit noticed", False)
    except fb_mecway.MeshChanged:
        r.check("edit noticed", True)
    r.check("no half mesh", "mesh" not in out)


def test_selection(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m, selected=[3, 4])
    out = fb_mecway.read_selection(mw)
    r.check("elements", out["elements"] == [3, 4])

    class Sol(object):
        def selected_elements(self):
            return [7]
    mw.selected = []
    r.check("from the solution view", fb_mecway.read_selection(mw, Sol())["elements"] == [7])


def test_props(r):
    m, mesh = sup.make_mesh("hex8", component={1: u"Alu", 2: u"Wood", 3: u"Odd"})
    props, unknown = fb_mecway.read_props(FakeMw(m), mesh)
    r.check("steel", props[5]["E"] == 210e9)
    r.check("aluminium", props[1]["E"] == 70e9)
    r.check("orthotropic has none", 2 not in props)
    r.check("names what is missing", sorted(unknown) == [u"Odd", u"Wood"], unknown)


def test_scale(r):
    values = {1: (3.0, 4.0, 0.0, 0.0, 0.0, 2.0), 2: (6.0, 8.0, 0.0, 0.0, 0.0, 0.0)}
    scaled, big = fb_mecway.scale_values(values)
    r.close("largest force is the size", math.sqrt(scaled[2][0] ** 2 + scaled[2][1] ** 2),
            fb_mecway.ARROW_SIZE)
    r.close("relative stays", scaled[1][0] / scaled[2][0], 0.5)
    r.close("moment own factor", scaled[1][5], fb_mecway.ARROW_SIZE)
    r.close("true value", big["force"], 10.0)
    r.check("no force", fb_mecway.scale_values({1: (0.0,) * 6})[1]["force"] == 0.0)


def test_resultant_place(r):
    m, mesh = sup.make_mesh("hex8")
    nids = sorted(mesh["nodes"])[:8]
    p = mesh["nodes"][nids[2]]
    cuts = [{"id": 1, "nodes": nids, "point": p, "sum6": (1.0, 0, 0, 0, 0, 0)}]
    values, places = fb_mecway.resultant_values(mesh, cuts)
    r.check("on the node", places[0]["node"] == nids[2] and places[0]["distance"] == 0)
    off = (p[0] + 0.0005, p[1], p[2])
    cuts[0]["point"] = off
    values, places = fb_mecway.resultant_values(mesh, cuts)
    r.close("distance named", places[0]["distance"], 0.0005, 1e-9)
    r.check("value there", values[nids[2]][0] == 1.0)
    r.check("a corner of the bar is outside", places[0]["inside"] is False, places)


def _node_at(mesh, p):
    for nid, q in mesh["nodes"].items():
        if max(abs(q[k] - p[k]) for k in range(3)) < 1e-9:
            return nid
    return None


def test_outside_nodes(r):
    """The bar 0.2 x 0.02 x 0.04 m, 5 x 2 x 2 cells, y and z around 0."""
    for shape in ("hex20", "hex8", "tet10"):
        m, mesh = sup.make_mesh(shape)
        centre = _node_at(mesh, (0.08, 0.0, 0.0))
        mid = _node_at(mesh, (0.08, 0.005, 0.0))
        face = _node_at(mesh, (0.08, 0.01, 0.0))
        corner = _node_at(mesh, (0.08, 0.01, 0.02))
        end = _node_at(mesh, (0.2, 0.0, 0.0))
        ids = [n for n in (centre, mid, face, corner, end) if n is not None]
        out = fb_mecway.outside_nodes(mesh, ids)
        r.check(shape + ": centre of a section inside", centre is not None and
                centre not in out, (centre, sorted(out)))
        if mid is not None:
            r.check(shape + ": midside node on two inner faces inside", mid not in out)
        r.check(shape + ": node on the side outside", face in out and corner in out)
        r.check(shape + ": node on the end face outside", end in out)
    m, mesh = sup.make_mesh("hex20")
    centre = _node_at(mesh, (0.08, 0.0, 0.0))
    mesh["elements"][max(mesh["elements"]) + 1] = (
        "quad4", [centre, _node_at(mesh, (0.08, 0.01, 0.0)),
                  _node_at(mesh, (0.08, 0.01, 0.02)), _node_at(mesh, (0.08, 0.0, 0.02))])
    r.check("a node of a shell is outside", centre in fb_mecway.outside_nodes(mesh, [centre]))
    mesh["nodes"][9999] = (1.0, 1.0, 1.0)
    r.check("a node on no element counts as outside",
            fb_mecway.outside_nodes(mesh, [9999]) == set([9999]))


def _arrows(mw, sol, values, own, time=None):
    out = {}
    _exhaust(fb_mecway.arrow_steps(mw, sol, values, own, out, chunk=50, time=time))
    return out


def test_arrow_refusals(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    v = {1: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)}
    r.check("no solution", _arrows(mw, None, v, {})["refused"] == "no_solution")

    class Dead(object):
        def all_nodes(self):
            raise RuntimeError("closed")
    r.check("stale", _arrows(mw, Dead(), v, {})["refused"] == "stale")

    class Empty(object):
        def all_nodes(self):
            return []
    r.check("empty", _arrows(mw, Empty(), v, {})["refused"] == "no_solution")
    other, _, _ = models.block("hex8", length=0.3)
    far = {max(m.xyz): (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)}
    r.check("other mesh", _arrows(mw, FakeSolution(other), far, {})["refused"] == "mesh_differs")
    gap, _, _ = models.block("hex8")
    gap.xyz[max(gap.xyz) + 5] = (9.0, 9.0, 9.0)
    r.check("gaps", _arrows(mw, FakeSolution(gap), v, {})["refused"] == "numbering")


def test_arrows_written(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    sol = FakeSolution(m)
    own = {}
    v = {1: (3.0, 4.0, 0.0, 0.0, 0.0, 0.0), 2: (0.0, 0.0, 5.0, 0.0, 0.0, 1.0)}
    out = _arrows(mw, sol, v, own)
    r.check("both written", sorted(out["written"]) == ["force", "moment"], out)
    r.close("first write keeps true values", sol.fields["externalforcex"][0], 3.0)
    r.check("other nodes empty", sol.fields["externalforcex"][2] is None)
    r.check("view refreshed", mw.displayed == 1)
    # second write of this panel: allowed, same size, field replaced
    out = _arrows(mw, sol, {5: (10.0, 0.0, 0.0, 0.0, 0.0, 0.0)}, own)
    r.check("own field written again", out["written"] == ["force"], out)
    # the moment of the first write is ours: a zero moment now removes it
    r.check("own zero moment cleared", out["cleared"] == ["moment"] and
            not out["skipped"], out)
    r.close("same length as the first write", sol.fields["externalforcex"][4], 5.0)
    r.check("old arrow gone", sol.fields["externalforcex"][0] is None)


def test_arrows_zero_clears(r):
    """A zero vector removes this panel's earlier arrows of that vector (a
    solid per node after a resultant), never a foreign field."""
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    sol = FakeSolution(m)
    own = {}
    resultant = {5: (3.0, 4.0, 0.0, 0.0, 2.0, 0.0)}
    per_node = {1: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0, 0.0, 0.0, 0.0)}
    out = _arrows(mw, sol, per_node, own)
    r.check("first per node: zero moment in a free field is only zero",
            out["skipped"] == [("moment", "zero")] and out["cleared"] == [] and
            "reactionmomx" not in sol.fields, out)
    out = _arrows(mw, sol, resultant, own)
    r.check("then the resultant writes its moment", sorted(out["written"]) ==
            ["force", "moment"] and not out["cleared"], out)
    r.close("moment there", sol.fields["reactionmomy"][4], 2.0)
    shown = mw.displayed
    out = _arrows(mw, sol, per_node, own)
    r.check("per node again: the old moment is cleared",
            out["written"] == ["force"] and out["cleared"] == ["moment"], out)
    for field in fb_mecway.FIELDS_MOMENT + ("reactionmommag",):
        r.check(field + " empty everywhere", all(v is None for v in sol.fields[field]))
    r.check("own of the moment emptied", all(own[f] == {} for f in fb_mecway.FIELDS_MOMENT))
    r.check("sizes kept", "moment" in own["sizes"], own.get("sizes"))
    r.check("view refreshed", mw.displayed == shown + 1)
    out = _arrows(mw, sol, per_node, own)
    r.check("cleared field is free: zero again", out["skipped"] == [("moment", "zero")], out)
    out = _arrows(mw, sol, resultant, own)
    r.check("a moment goes in again after a clear", "moment" in out["written"], out)
    # a field that holds something else is left as it is
    sol.fields["reactionmomz"] = [0.5] * len(m.xyz)
    out = _arrows(mw, sol, per_node, own)
    r.check("foreign field: not cleared", ("moment", "zero") in out["skipped"] and
            not out["cleared"] and sol.fields["reactionmomy"][4] is not None, out)
    # a clear that fails says so and the force is still written
    sol2 = FakeSolution(m)
    own2 = {}
    _arrows(mw, sol2, resultant, own2)

    class NoClear(FakeSolution):
        def set_variable(self, name, values, time_step=None):
            if all(v is None for v in values):
                raise Exception("refused")
            FakeSolution.set_variable(self, name, values, time_step)
    sol3 = NoClear(m)
    sol3.fields = sol2.fields
    out = _arrows(mw, sol3, per_node, own2)
    r.check("clear failed: reported", ("moment", "clear_failed") in out["skipped"] and
            out["written"] == ["force"], out)


def test_arrows_foreign_field(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    sol = FakeSolution(m)
    # zero nearly everywhere, as CalculiX leaves it
    sol.fields["externalforcez"] = [None] * (len(m.xyz) - 1) + [0.0]
    v = {1: (3.0, 0.0, 0.0, 0.0, 0.0, 1.0)}
    out = _arrows(mw, sol, v, {})
    r.check("field exists", ("force", "exists") in out["skipped"], out)
    r.check("nothing overwritten", "externalforcex" not in sol.fields)
    r.check("moment still goes", out["written"] == ["moment"], out)


def test_arrows_after_new_solve(r):
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    sol = FakeSolution(m)
    own = {}
    v = {1: (3.0, 0.0, 0.0, 0.0, 0.0, 0.0)}
    _arrows(mw, sol, v, own)
    # a new solve puts its own values in the field
    sol.fields["externalforcex"] = [0.25] * len(m.xyz)
    out = _arrows(mw, sol, v, own)
    r.check("no longer ours", ("force", "exists") in out["skipped"], out)
    r.close("kept", sol.fields["externalforcex"][0], 0.25)
    # a new solve that emptied the field: free again
    sol.fields = {}
    out = _arrows(mw, sol, v, own)
    r.check("empty again", "force" in out["written"], out)


def test_arrow_report(r):
    unit = fb_gui.UNITS[0]
    out = {"written": ["force"], "skipped": [("moment", "exists")], "refused": None,
           "largest": {"force": 1234.0, "moment": 0.0}}
    text = u" ".join(fb_gui.arrow_report(out, [u"line"], "en", unit, u"."))
    r.check("says the legend is right", u"legend" in text and u"1234" in text, text)
    r.check("says skipped", u"reaction moment already exists" in text, text)
    r.check("passes on the node line", u"line" in text)
    text = u" ".join(fb_gui.arrow_report({"refused": "no_solution"}, [], "nl", unit, u","))
    r.check("refusal in Dutch", u"Geen oplossing" in text, text)
    out = {"written": ["force"], "cleared": ["moment"], "skipped": [], "refused": None,
           "largest": {"force": 1.0, "moment": 0.0}}
    text = u" ".join(fb_gui.arrow_report(out, [], "en", unit, u"."))
    r.check("says the old moment is removed", u"reaction moment is zero here: the earlier "
            u"arrows of this panel are removed" in text and u"not written" not in text, text)
    text = u" ".join(fb_gui.arrow_report(out, [], "nl", unit, u","))
    r.check("removed in Dutch", u"eerdere pijlen van dit paneel zijn weggehaald" in text, text)
    out["cleared"], out["skipped"] = [], [("moment", "clear_failed")]
    text = u" ".join(fb_gui.arrow_report(out, [], "en", unit, u"."))
    r.check("says a failed clear", u"could not be removed" in text, text)
    for key in ("a_cleared", "a_clear_failed", "a_inside"):
        nl, en = fb_gui.T[key]
        r.check("text " + key, nl and en and nl != en)


# ---- the bridge ------------------------------------------------------------------------
BRIDGE_TEXT = u'''# settings
CONFIG = {
    # Working directory
    "work_dir":        "",
    "work_dir_beside_model": False,
    "exe_aster":       r"%LOCALAPPDATA%\\code_aster\\v2025\\17.4\\bin\\run_aster.bat",
}
'''


def _temp():
    return tempfile.mkdtemp(prefix="fbtest_")


def test_bridge_text(r):
    folder = _temp()
    try:
        path = os.path.join(folder, "bridge_utils.py")
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(BRIDGE_TEXT)
        out = fb_mecway.read_bridge_settings(path)
        r.check("work dir", out["work_dir"] == u"")
        r.check("beside", out["beside_model"] is False)
        r.check("launcher", out["exe"].endswith(u"17.4\\bin\\run_aster.bat"), out)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"CONFIG = {}\n")
        out = fb_mecway.read_bridge_settings(path)
        r.check("refactored bridge: nothing", out["work_dir"] is None and out["exe"] is None)
    finally:
        shutil.rmtree(folder)


def test_find_bridge(r):
    folder = _temp()
    try:
        scripts = os.path.join(folder, "Bridge", "Scripts")
        os.makedirs(scripts)
        exe = os.path.join(folder, "17.4", "bin", "run_aster.bat")
        os.makedirs(os.path.dirname(exe))
        with io.open(exe, "w", encoding="utf-8") as f:
            f.write(u"rem")
        text = BRIDGE_TEXT.replace(u'"work_dir":        ""',
                                   u'"work_dir":        r"{0}"'.format(folder))
        text = text.replace(u'r"%LOCALAPPDATA%\\code_aster\\v2025\\17.4\\bin\\run_aster.bat"',
                            u'r"{0}"'.format(exe))
        with io.open(os.path.join(scripts, "bridge_utils.py"), "w", encoding="utf-8") as f:
            f.write(text)
        out = fb_mecway.find_bridge(os.path.join(folder, "x"), u"", {"bridge_scripts": scripts})
        r.check("found", out["scripts"] == scripts, out)
        r.check("work folder", out["work_dir"] == folder, out)
        r.check("launcher", out["exe"] == exe and not out["problems"], out)
        with io.open(os.path.join(scripts, "bridge_utils.py"), "w", encoding="utf-8") as f:
            f.write(u"nothing\n")
        out = fb_mecway.find_bridge(os.path.join(folder, "x"), u"", {"bridge_scripts": scripts})
        r.check("loud when unreadable", "unreadable" in out["problems"], out)
        out = fb_mecway.find_bridge(os.path.join(folder, "x"), u"",
                                    {"bridge_scripts": scripts, "exe_aster": exe})
        r.check("own launcher wins", out["exe"] == exe and "no_aster" not in out["problems"], out)
    finally:
        shutil.rmtree(folder)


def test_run_folders(r):
    model = u"C:\\work\\My Model (v2).liml"
    bridge = {"work_dir": u"C:\\bridge\\WorkDir"}
    auto = fb_mecway.run_folders(model, bridge)
    r.check("next to the model", auto[0] == u"C:\\work", auto)
    r.check("bridge folder of the model", auto[1] == u"C:\\work\\My_Model_v2_aster", auto)
    r.check("work folder last", auto[2] == bridge["work_dir"], auto)
    r.check("other", fb_mecway.run_folders(model, bridge, "other", u"D:\\x") == [u"D:\\x"])
    r.check("unsaved model", fb_mecway.run_folders(u"", bridge) == [bridge["work_dir"]])
    r.check("no bridge", fb_mecway.run_folders(u"", None, "bridge") == [])


def test_scan_runs(r):
    folder = _temp()
    keep = dict(fb_gui._CACHE)
    try:
        m, mesh = sup.make_mesh("hex8")
        path = os.path.join(folder, "bar.liml")
        fp = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
        sup.write_run(folder, sup.manifest(fp, run_id="20261101_100000"))
        sup.write_run(folder, sup.manifest(fp, run_id="20261102_100000"))
        sup.write_run(folder, sup.manifest("other", run_id="20261103_100000"))
        fb_gui._CACHE["settings"] = dict(fb_gui._DEFAULTS)
        scan = fb_gui.scan_runs(mesh, path, "other", folder)
        r.check("two fit", len(scan["runs"]) == 2, scan["runs"])
        r.check("newest first", scan["runs"][0]["run_id"] == "20261102_100000")
        r.check("fingerprint kept", scan["fingerprint"] == fp)
        m.xyz[1] = (5.0, 5.0, 5.0)
        _, mesh2 = sup.make_mesh("hex8", m=m)
        scan = fb_gui.scan_runs(mesh2, path, "other", folder)
        r.check("changed model: none fit", not scan["runs"])
        r.check("but says there were some", scan["other"] == 3, scan["other"])
    finally:
        fb_gui._CACHE.clear()
        fb_gui._CACHE.update(keep)
        shutil.rmtree(folder)


def test_fingerprint_half_nm(r):
    """The hash rounds to 1 nm: a coordinate from a file and the same one from
    the API, a whisker apart, must not differ."""
    a = {1: (0.1, 0.2, 0.3)}
    b = {1: (0.1 + 1e-13, 0.2 - 1e-13, 0.3)}
    r.check("same hash", fb_aster.mesh_fingerprint(a, [1]) == fb_aster.mesh_fingerprint(b, [1]))


# ---- settings ------------------------------------------------------------------------
def test_other_model(r):
    fp = sup.manifest("x", model="bar")
    r.check("same name", not fb_gui.foreign_run(fp, u"C:\\work\\bar.liml"))
    r.check("other name", fb_gui.foreign_run(fp, u"C:\\work\\beam.liml"))
    r.check("stem of the bridge", not fb_gui.foreign_run(
        sup.manifest("x", model="My_Model_v2"), u"C:\\work\\My Model (v2).liml"))
    r.check("unsaved model", not fb_gui.foreign_run(fp, u""))
    r.check("manifest without a name", not fb_gui.foreign_run({}, u"C:\\work\\bar.liml"))
    folder = _temp()
    keep = dict(fb_gui._CACHE)
    try:
        m, mesh = sup.make_mesh("hex8")
        got = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
        sup.write_run(folder, sup.manifest(got, run_id="20261103_100000", model="beam"))
        sup.write_run(folder, sup.manifest(got, run_id="20261101_100000", model="bar"))
        fb_gui._CACHE["settings"] = dict(fb_gui._DEFAULTS)
        scan = fb_gui.scan_runs(mesh, os.path.join(folder, "bar.liml"), "other", folder)
        r.check("own model first, also when older", scan["runs"][0]["model"] == "bar")
    finally:
        fb_gui._CACHE.clear()
        fb_gui._CACHE.update(keep)
        shutil.rmtree(folder)


def test_selection_differs(r):
    r.check("same", not fb_gui.selection_differs([3, 1], [1, 3]))
    r.check("other", fb_gui.selection_differs([1], [1, 3]))
    r.check("nothing selected", fb_gui.selection_differs([], [1, 3]))
    r.check("not known", not fb_gui.selection_differs(None, [1]))
    r.check("no table", not fb_gui.selection_differs([1], None))


def test_solution_disp(r):
    m, _, _ = models.block("hex8")
    sol = FakeSolution(m)
    sol.KNOWN = sol.KNOWN + ("displx", "disply", "displz")
    n = len(m.xyz)
    out = {}
    _exhaust(fb_mecway.solution_disp_steps(sol, [1, 2], out))
    r.check("no field: no values", out["values"] == {}, out)
    sol.fields.update({"displx": [1.0] * n, "disply": [2.0] * n, "displz": [3.0] * (n - 1) + [None]})
    out = {}
    _exhaust(fb_mecway.solution_disp_steps(sol, [1, n], out, chunk=1))
    r.check("values by node", out["values"] == {1: (1.0, 2.0, 3.0)}, out)
    out = {}
    _exhaust(fb_mecway.solution_disp_steps(None, [1], out))
    r.check("no solution", out["values"] == {})


def test_support_on_a_cut_is_named(r):
    """A support on a cut node counts as the rest; the sentence says so."""
    model = fb_gui.PanelModel()
    model.lang = "en"
    model.rank = 1
    model.index = 0
    model.cuts = [{"id": 2}]
    model.steps = lambda: [1]
    model.result = {"on_cut": {1: {"cuts": {2: {"count": 5, "sum": (30.0, 40.0, 0, 0, 0, 0)}}}}}
    text = model._on_cut_text(lambda v: u"{0} N".format(v))
    r.check("support named with its force", u"5 cut nodes" in text and u"50.0 N" in text, text)
    model.result = {"on_cut": {1: {"cuts": {2: {"count": 0, "sum": (0.0,) * 6}}}}}
    r.check("no sentence without a support", model._on_cut_text(lambda v: u"") == u"")
    model.result = {}
    r.check("older result without on_cut", model._on_cut_text(lambda v: u"") == u"")


def test_arrow_size_only_after_writing(r):
    """A refused or skipped write must not fix the size of later arrows."""
    m, _, _ = models.block("hex8")
    mw = FakeMw(m)
    sol = FakeSolution(m, times=(0.0, 1.0))
    own = {}
    out = _arrows(mw, sol, {1: (10.0, 0.0, 0.0, 0.0, 0.0, 0.0)}, own, time=0.5)
    r.check("no step at that time: refused", out["refused"] == "no_step", out)
    r.check("refusal fixes no size", "sizes" not in own, own)
    out = _arrows(mw, sol, {1: (100.0, 0.0, 0.0, 0.0, 0.0, 0.0)}, own, time=1.0)
    r.check("first real write keeps true values", abs(sol.fields["externalforcex"][0] - 100.0)
            < 1e-9, out)
    text = u" ".join(fb_gui.arrow_report(out, [], "en", (u"N", 1.0, u"N", u"N.m"), "."))
    r.check("says the legend is right", u"legend in Mecway is right" in text, text)
    out = _arrows(mw, sol, {2: (400.0, 0.0, 0.0, 0.0, 0.0, 0.0)}, own, time=1.0)
    r.close("second write keeps the first length", sol.fields["externalforcex"][1], 100.0)
    text = u" ".join(fb_gui.arrow_report(out, [], "en", (u"N", 1.0, u"N", u"N.m"), "."))
    r.check("says the length is kept", u"keep the length of the first" in text and u"400" in text, text)


def test_time_steps(r):
    """A solution with time steps refuses calls without a step (measured)."""
    m, _, _ = models.block("hex8")
    sol = FakeSolution(m, times=(0.0, 0.5, 1.0))
    n = len(m.xyz)
    sol.KNOWN = sol.KNOWN + ("displx", "disply", "displz")
    for name in ("displx", "disply", "displz"):
        sol.fields[name] = [1.0] * n
    r.check("last step by default", fb_mecway.solution_step(sol) == 2)
    r.check("nearest step to a time", fb_mecway.solution_step(sol, 0.4) == 1)
    r.check("a step at that time", fb_mecway.step_matches(sol, 1, 0.5))
    r.check("no step at that time", not fb_mecway.step_matches(sol, 1, 0.4))
    r.check("no steps: None", fb_mecway.solution_step(FakeSolution(m)) is None)
    out = {}
    _exhaust(fb_mecway.solution_disp_steps(sol, [1, 2], out))
    r.check("displacements read with a step", out["values"] == {1: (1.0, 1.0, 1.0),
                                                                2: (1.0, 1.0, 1.0)}, out)
    # A real field must not look empty because the call was refused
    sol.fields["externalforcex"] = [5.0] * n
    state = {}
    _exhaust(fb_mecway.field_state_steps(sol, "externalforcex", [1, 2], {}, state,
                                         step=2))
    r.check("existing field seen with a step", state["externalforcex"] == "foreign", state)


def test_solution_state(r):
    keep = getattr(fb_aster, "check_solution", None)
    try:
        fb_aster.check_solution = lambda result, rank, values: "stale"
        r.check("the core decides", fb_gui.solution_state({}, {}) == "stale")
        del fb_aster.check_solution
        r.check("without its check: unknown", fb_gui.solution_state({}, {}) == "unknown")
    finally:
        if keep is not None:
            fb_aster.check_solution = keep


def test_settings(r):
    folder = _temp()
    keep = dict(fb_gui._CACHE)
    try:
        path = os.path.join(folder, "s.json")
        fb_gui._CACHE.clear()
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(u"{ not json")
        r.check("broken file: defaults", fb_gui.settings(path)["unit"] == "N")
        fb_gui.save_setting("unit", "kN", path)
        fb_gui._CACHE.clear()
        r.check("remembered", fb_gui.settings(path)["unit"] == "kN")
        fb_gui._CACHE.clear()
        fb_gui.save_setting("folder_other", u"C:\\mäp", path)
        fb_gui._CACHE.clear()
        r.check("non-ASCII path", fb_gui.settings(path)["folder_other"] == u"C:\\mäp")
    finally:
        fb_gui._CACHE.clear()
        fb_gui._CACHE.update(keep)
        shutil.rmtree(folder)


# ---- the queue to the script thread ----------------------------------------------------
def test_caller(r):
    c = fb_gui._MwCaller(False)
    t = c.post(lambda: 5)
    r.check("waits for the script thread", not t["done"])
    c.serve_once()
    r.check("answered", t["done"] and t["result"] == 5)
    log = []

    def steps():
        log.append(1)
        yield
        log.append(2)
    t = c.post_steps(steps())
    c.serve_once()
    r.check("one piece per turn", log == [1] and not t["done"], log)
    c.serve_once()
    r.check("finished", log == [1, 2], log)
    c.serve_once()
    r.check("generator done", t["done"])

    def bad():
        raise RuntimeError("no model")
    t = c.post(bad)
    c.serve_once()
    r.check("an error stays in the ticket", t["done"] and t["error"] is not None)
    t = c.post(lambda: 1)
    c.cancel(t)
    r.check("cancelled leaves the queue", not c.serve_once() and not t["done"])
    t = c.post(lambda: 1)
    c.cancel_all()
    r.check("cancel all", not c.serve_once())
    d = fb_gui._MwCaller(True)
    r.check("direct", d.post(lambda: 3)["result"] == 3)


def test_worker_stops_a_late_job(r):
    import threading
    go = threading.Event()
    job = sup.FakeJob(None)

    def plan():
        go.wait(5.0)
        return (None, None, job)
    w = fb_gui._Worker(plan)
    w.when_done(fb_gui._stop_started_job)
    r.check("still working", not job.stopped)
    go.set()
    w.thread.join(5.0)
    r.check("stopped as soon as it started", job.stopped)
    job2 = sup.FakeJob(None)
    done = fb_gui._Worker(lambda: (None, None, job2))
    done.thread.join(5.0)
    done.when_done(fb_gui._stop_started_job)
    r.check("also when it had ended", job2.stopped)


def test_worker_error_stays_in_its_slot(r):
    def bad():
        raise ValueError("wrong")
    w = fb_gui._Worker(bad)
    w.thread.join(5.0)
    r.check("slot", w.done and isinstance(w.error, ValueError) and w.value is None)
    r.check("refusal is an error too", isinstance(fb_core.Refused("x", "y"), Exception))


def main():
    import test_gui_docs
    import test_gui_nodecut
    import test_gui_shells
    report = sup.Report()
    report.run(globals())
    # shells, beams and mixed cuts (phase 4)
    report.run(vars(test_gui_shells))
    # a cut by nodes on a plane
    report.run(vars(test_gui_nodecut))
    # the documentation tab (fb_docs)
    report.run(vars(test_gui_docs))
    return report


if __name__ == "__main__":
    out = main()
    for line in out.lines:
        if not line.startswith("OK"):
            print(line)
    print("{0} checks, {1} failed".format(len(out.lines), out.failed))
    sys.exit(1 if out.failed else 0)
