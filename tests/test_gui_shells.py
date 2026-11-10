# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_shells.py
# The panel on shells, beams and mixed cuts (phase 4): axes per case, names,
# masks, signs, texts, the drawing data, shell props from a fake mw. Plans and
# geometry are written by hand after the contract (test_gui_support), so this
# runs before the core of phase 4 is there; one smoke test uses the real core
# once it gives strips. CPython 3 and Mecway's IronPython (via test_gui_logic).
#   python tests/test_gui_shells.py

import io
import math
import os
import shutil
import sys
import tempfile

import test_gui_support as sup
from test_gui_support import FakeMw

import fb_core
import fb_gui
import fb_mecway


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# ---- shell strips -------------------------------------------------------------------
def test_strip_axes_and_names(r):
    model = sup.shell_case()
    a, b = model.cuts
    r.check("one strip: strip axes", model.axes_kind(a) == "strip", model.axes_kind(a))
    r.check("strip names", list(model.names(a)) == [u"N", u"V_t", u"V_w", u"T", u"M_t",
                                                     u"M_w"], model.names(a))
    n, t, w = a["geo"]["axes"]
    r.check("fixture: t = w x n", max(abs(x - y) for x, y in zip(sup.cross(w, n), t)) < 1e-12)
    for cut in model.cuts:
        s = model.sum6(cut)
        values = model.components(cut)
        axes = cut["geo"]["axes"]
        r.close("N along n out of the selection", values[0], _dot(s[:3], axes[0]), 1e-12)
        r.close("V_t along t", values[1], _dot(s[:3], axes[1]), 1e-12)
        r.close("M_w about w", values[5], _dot(s[3:], axes[2]), 1e-12)
    r.check("n points out of the selection",
            a["geo"]["axes"][0][0] < 0 < b["geo"]["axes"][0][0])


def test_strip_mw_unreliable(r):
    model = sup.shell_case()
    head = model.headers()
    r.check("M_w in the head", u"M_w" in head[7], head)
    r.check("head marks M_w", u"(?)" in head[7], head)
    row = model.rows()[0]
    r.check("M_w value marked", row[7].endswith(u"(?)"), row)
    r.check("other values not marked", not any(u"(?)" in c for c in row[2:7]), row)
    r.check("axes column", row[8] == u"strip n,t,w", row)
    r.check("warned", any(w[1] == "unreliable_mw" for w in model.warnings), model.warnings)
    view = model.view()
    r.check("drawing marks M_w", view["arrows"][5]["text"].endswith(u"(?)"),
            view["arrows"][5]["text"])
    copy = model.copy_rows()
    r.check("copy keeps numbers", isinstance(copy[7][-2], float), copy[7])
    model.axes = "global"
    r.check("global: no mark", not any(u"(?)" in c for c in model.rows()[0]))


def test_strip_set_is_a_section(r):
    model = sup.shell_case(across=2)
    cut = model.cuts[0]
    r.check("two strips: section axes", model.axes_kind(cut) == "section")
    r.check("section names", model.names(cut)[1] == u"Vy")
    r.check("two strips drawn", len(model.view()["strips"]) == 2)
    r.check("sections only: no axes column", not model.axes_column() and
            len(model.headers()) == 8 and len(model.rows()[0]) == 8)


def test_strip_drawing(r):
    model = sup.shell_case()
    view = model.view()
    strips = view["strips"]
    r.check("one strip drawn", len(strips) == 1, strips)
    us = [p[0] for p in strips[0]]
    vs = [p[1] for p in strips[0]]
    r.close("strip long along t", max(us) - min(us), 0.1, 1e-9)
    r.close("strip thick along w", max(vs) - min(vs), sup.THICKNESS, 1e-9)
    r.check("axis names t, w", view["axis_names"] == (u"t", u"w"), view["axis_names"])
    m = fb_gui.view_map(view, 400.0, 300.0)
    x0, _ = fb_gui.to_pixel(m, min(us), 0.0)
    x1, _ = fb_gui.to_pixel(m, max(us), 0.0)
    r.check("strip fits the picture", 0 < x0 < x1 < 400, (x0, x1))


def test_strip_offset(r):
    model = sup.shell_case()
    cut = model.cuts[0]
    cut["geo"]["strips"][0]["offset"] = 0.002
    vs = [p[1] for p in model.view()["strips"][0]]
    r.close("offset shifts along w", (max(vs) + min(vs)) / 2.0, 0.002, 1e-9)


# ---- beams ----------------------------------------------------------------------------
def test_beam_axes(r):
    model = sup.beam_case()
    a, b = model.cuts
    r.check("beam axes", model.axes_kind(a) == "beam", model.axes_kind(a))
    r.check("beam names", model.names(a)[1] == u"Vy")
    # the core mirrors at node 1; the panel uses the axes as they come
    for cut in model.cuts:
        s = model.sum6(cut)
        values = model.components(cut)
        axes = cut["geo"]["axes"]
        for k in range(3):
            r.close("beam F{0} on the given axes".format(k), values[k],
                    _dot(s[:3], axes[k]), 1e-12)
    r.check("node 1 cut keeps its mirrored axes", a["geo"]["axes"] == sup.BEAM_X1)
    model.index = 0
    note = model.axes_note()
    r.check("note on L sections", u"L section" in note and u"principal" in note, note)
    r.check("radio says beam axes", model.radio_text() == u"Beam axes", model.radio_text())
    sign = model.sign_text()
    r.check("sign for beams", u"node 1" in sign and u"mirrored" in sign, sign)
    r.check("sign has the base", sign.startswith(u"Sign: the force of the rest"), sign)
    r.check("hint in beam axes", u"of the beam" in model.point_hint(), model.point_hint())
    model.index = 1     # beam axes that happen to be X, Y, Z: still beam axes
    r.check("hint in beam axes at node 2", u"of the beam" in model.point_hint(),
            model.point_hint())
    r.check("letters of the beam", model.view()["axis_names"] == (u"y", u"z"))
    model.axes = "global"
    r.check("global choice: drawn in own axes, letters too",
            model.view()["axis_names"] == (u"y", u"z"), model.view()["axis_names"])
    model.axes = "section"


def test_beam_drawing(r):
    model = sup.beam_case()
    view = model.view()
    beams = view["beams"]
    r.check("one beam", len(beams) == 1 and len(beams[0]["loops"]) == 1, beams)
    loop = beams[0]["loops"][0]
    us = sorted(set(round(p[0], 9) for p in loop))
    vs = sorted(set(round(p[1], 9) for p in loop))
    r.close("HY along y", us[-1] - us[0], 0.02, 1e-9)
    r.close("HZ along z", vs[-1] - vs[0], 0.01, 1e-9)
    r.check("no area label with an outline", beams[0]["label"] is None)
    general = sup.beam_case(section={"cara": ["A", "IY", "IZ"], "vale": [2e-4, 1e-9, 1e-9],
                                     "shape": "GENERALE"})
    beam = general.view()["beams"][0]
    radius = max(math.sqrt(u * u + v * v) for u, v in beam["loops"][0])
    r.close("circle of area A", math.pi * radius ** 2, sup.BEAM_AREA, 1e-9)
    r.check("label with A", beam["label"] == u"A = 200 mm²", beam["label"])
    m = fb_gui.view_map(general.view(), 400.0, 300.0)
    r.check("circle sets the scale", m["s"] > 1000.0, m)


def test_beam_drawing_with_the_section_of_the_core(r):
    """The core gives beam["section"] as fb_aster.section_values made it (A,
    IY, ..., no cara/vale): the outline then comes from the manifest."""
    model = sup.beam_case()
    for cut in model.cuts:
        for beam in cut["geo"]["beams"]:
            beam["section"] = {"A": sup.BEAM_AREA, "IY": 1e-9, "IZ": 1e-9, "JX": 2e-9,
                               "shape": "RECTANGLE"}
    beam = model.view()["beams"][0]
    r.check("rectangle from the manifest", len(beam["loops"]) == 1 and
            len(beam["loops"][0]) == 4 and beam["label"] is None, beam)
    model.cuts[0]["geo"]["beams"][0]["section"] = {}
    beam = model.view()["beams"][0]
    r.check("empty section: the manifest too", len(beam["loops"][0]) == 4, beam)


def _no_area_case(kind):
    """A shell cut without thickness or a beam cut without section A: the core
    gives "area" None and a warning (contract)."""
    if kind == "shell":
        m, component = sup.models.plate(cells=(3, 1))
        mesh = sup._mesh_of(m, component)
        g1, geo1 = sup._strip_group(mesh, 1, 0.1, [2], -1.0)
        g2, geo2 = sup._strip_group(mesh, 2, 0.2, [2], 1.0)
        geos = {1: geo1, 2: geo2}
        plan = {"inside": [2], "outside": [1, 3], "cut_nodes": g1["nodes"] + g2["nodes"],
                "groups": [g1, g2], "warnings": []}
        man = sup.manifest("x", schema=2,
                           components={u"Plate": {"model": "DKT", "has_warping": False}})
        code = "thickness_missing"
    else:
        model = sup.beam_case()
        mesh, plan, man = model.mesh, model.plan, model.man
        geos = dict((cut["id"], cut["geo"]) for cut in model.cuts)
        code = "section_missing"
    for geo in geos.values():
        geo["area"] = None
        geo["warnings"] = list(geo.get("warnings") or []) + [code]
        for beam in geo.get("beams") or []:
            beam["A"] = None
    return sup.load_case(mesh, plan, geos, man), code


def test_cut_without_area(r):
    for kind in ("shell", "beam"):
        model, code = _no_area_case(kind)
        try:
            rows = model.rows()
            copied = model.copy_rows()
            view = model.view()
        except Exception as e:
            r.check("{0} without area: no error".format(kind), False, repr(e))
            continue
        r.check("{0}: A shown as –".format(kind), rows[0][1] == u"–", rows[0])
        r.check("{0}: numbers still shown".format(kind), rows[0][2] != u"–", rows[0])
        head = [i for i, row in enumerate(copied) if row and row[0] == model.headers()[0]][0]
        r.check("{0}: copy has no A".format(kind), copied[head + 1][1] is None, copied[head + 1])
        r.check("{0}: drawing made".format(kind), view is not None and view["arrows"])
        lines = model.warning_lines()
        r.check("{0}: warning in words".format(kind),
                any(code not in line and u"area" in line for line in lines), lines)
        cut = model.cuts[0]
        pts = [model.mesh["nodes"][n] for n in cut["group"]["nodes"]]
        diagonal = math.sqrt(sum((max(p[k] for p in pts) - min(p[k] for p in pts)) ** 2
                                 for k in range(3)))
        # a strip: the diagonal of its nodes; one beam end: 1 m
        r.close("{0}: size is a length of the cut".format(kind), model.size(cut),
                diagonal or 1.0, 1e-12)
        r.check("{0}: the strip has a length".format(kind), kind == "beam" or diagonal > 0)


def test_beam_loops(r):
    r.check("rectangle", len(fb_gui.beam_loops({"cara": ["HY", "HZ"], "vale": [2, 1]})) == 1)
    r.check("tube has a hole", len(fb_gui.beam_loops(
        {"cara": ["HY", "HZ", "EPY", "EPZ"], "vale": [2.0, 1.0, 0.1, 0.1]})) == 2)
    r.check("square by H", len(fb_gui.beam_loops({"cara": ["H"], "vale": [1.0]})) == 1)
    r.check("circle", len(fb_gui.beam_loops({"cara": ["R"], "vale": [1.0]})[0]) ==
            fb_gui._CIRCLE_SIDES)
    r.check("pipe", len(fb_gui.beam_loops({"cara": ["R", "EP"], "vale": [1.0, 0.1]})) == 2)
    r.check("general: unknown", fb_gui.beam_loops({"cara": ["A"], "vale": [1.0]}) == [])
    r.check("nothing", fb_gui.beam_loops(None) == [])
    r.check("bad numbers", fb_gui.beam_loops({"cara": ["HY", "HZ"], "vale": ["x", 1]}) == [])


def test_truss(r):
    model = sup.beam_case(model_name="BARRE")
    cut = model.cuts[0]
    r.check("truss", model.axes_kind(cut) == "truss", model.axes_kind(cut))
    row = model.rows()[0]
    r.check("only N", row[2] != fb_gui.fmt(None) and
            all(c == fb_gui.fmt(None) for c in row[3:8]), row)
    r.check("numbers stay six floats", len(model.components(cut)) == 6)
    copy = model.copy_rows()
    line = [x for x in copy if x and x[0] == u"1"][0]
    r.check("copy leaves the rest empty", line[5] is not None and
            all(v is None for v in line[6:11]), line)
    arrows = model.view()["arrows"]
    r.check("no arrows but N", all(a["value"] == 0.0 for a in arrows[1:]), arrows)
    r.check("warned", any(w[1] == "truss" for w in model.warnings))
    r.check("arrows in Mecway keep the real sum",
            model.arrow_cuts()[0]["sum6"] == model.sum6(cut))
    model.axes = "global"
    r.check("global: all six", all(c != fb_gui.fmt(None) for c in model.rows()[0][2:8]))


def test_truss_by_beam_entry(r):
    model = sup.beam_case()
    cut = model.cuts[0]
    cut["geo"]["beams"][0]["model"] = "CABLE"
    del cut["axes_kind"]
    r.check("model in the beam entry wins", model.axes_kind(cut) == "truss")
    cut["geo"]["axes_kind"] = "beam"
    del cut["axes_kind"]
    r.check("axes_kind of the core wins", model.axes_kind(cut) == "beam")


# ---- mixed and global ---------------------------------------------------------------
def test_mixed(r):
    model = sup.mixed_case()
    cut = model.cuts[0]
    r.check("mixed is global", model.axes_kind(cut) == "global")
    r.check("global names", model.names(cut)[0] == u"Fx")
    r.check("warned", any(w[1] == "mixed_cut" for w in model.warnings), model.warnings)
    r.check("text of the core's mixed_cut",
            u"mixes solids, shells or beams" in u" ".join(model.warning_lines()))
    view = model.view()
    r.check("strip and beam drawn", len(view["strips"]) == 1 and len(view["beams"]) == 1)
    r.check("round rib", len(view["beams"][0]["loops"][0]) == fb_gui._CIRCLE_SIDES)
    s = model.sum6(cut)
    r.check("global numbers", all(abs(x - y) < 1e-12
                                  for x, y in zip(model.components(cut), s)))
    r.check("sign says global", u"global axes" in model.sign_text(), model.sign_text())
    r.check("radio says global here", u"global here" in model.radio_text())
    r.check("axes column", model.rows()[0][8] == u"global")


def test_column_names_join(r):
    model = sup.shell_case()
    model.cuts[1]["axes_kind"] = "global"
    names = model.column_names()
    r.check("joined per column", names[0] == u"N/Fx" and names[5] == u"M_w/Mz", names)
    r.check("two kinds in the sign", u"Strip:" in model.sign_text() and
            u"Global:" in model.sign_text(), model.sign_text())


def test_global_choice(r):
    model = sup.beam_case()
    model.axes = "global"
    r.check("all global", all(model.names(c)[0] == u"Fx" for c in model.cuts))
    r.check("global: no axes column", len(model.rows()[0]) == 8 and
            len(model.copy_rows()[6]) == 11, model.copy_rows()[6])
    r.check("note", model.axes_note() == fb_gui.tx("ax_n_all_global", "en"))
    r.check("sign global only", u"Beam:" not in model.sign_text())
    r.check("hint global", model.point_hint() == fb_gui.tx("p_global", "en"))


def test_large_strip_is_global(r):
    def move(p, rank):
        return (0.0, 0.0, 0.0) if rank == 1 else (0.01, 0.002, 0.03)
    model = sup.shell_case(large=True, shift=move)
    cut = model.cuts[0]
    r.check("large strip: global", model.axes_kind(cut) == "global")
    r.check("warned large_axes", any(w[1] == "large_axes" for w in model.warnings),
            model.warnings)
    centre, axes = model.frame(cut, 2)
    c0 = cut["geo"]["centroid"]
    r.close("neutral point moves along x", centre[0], c0[0] + 0.01, 1e-12)
    r.close("neutral point moves along z", centre[2], c0[2] + 0.03, 1e-12)
    r.check("undeformed axes for the point", axes == cut["geo"]["axes"])
    s = model.sum6(cut)
    direct = [0.0] * 6
    where = fb_core.positions(model.result, 2)
    for i in cut["indices"]:
        f = model.result["forces"][2][i]
        d = [where[i][k] - centre[k] for k in range(3)]
        m = sup.cross(d, f[:3])
        for k in range(3):
            direct[k] += f[k]
            direct[3 + k] += m[k]
    for k in range(6):
        r.close("sum about the moved point {0}".format(k), s[k], direct[k], 1e-9)
    model.rank = 1
    r.close("step 1 does not move", model.frame(cut, 1)[0][0], c0[0], 1e-12)
    view = model.view()
    r.check("still drawn in its own axes", view["axis_names"] == (u"t", u"w"),
            view["axis_names"])
    r.check("hint still in its own axes", u"n, t, w" in model.point_hint(),
            model.point_hint())


def test_large_solid_unchanged(r):
    # a solid with large displacements keeps its turned section axes
    m, mesh = sup.make_mesh("hex20")
    plan = fb_core.plan_cuts(mesh, sup.selected_slice())
    geos = dict((g["id"], fb_core.section_geometry(mesh, g, None)) for g in plan["groups"])
    result = sup.make_result(plan, mesh, large=True)
    per = fb_core.assign_nodes(plan, mesh, result)
    model = fb_gui.PanelModel()
    model.load(mesh, plan, geos, result, per, sup.manifest("x"), u"f")
    r.check("solid stays section", all(model.axes_kind(c) == "section" for c in model.cuts))
    r.check("no large_axes", not any(w[1] == "large_axes" for w in model.warnings))


# ---- warnings and refusals --------------------------------------------------------------
PHASE4_WARNINGS = ("skin_shell", "beam_along_cut", "mixed_cut", "node_contact", "drilling",
                   "large_axes", "unreliable_mw", "no_thickness", "truss", "mixed_shape")
PHASE4_REFUSALS = ("beam_warping", "beam_large_rotation", "offset", "schema_old",
                   "not_shared_on_cut")


def test_phase4_texts(r):
    for code in PHASE4_WARNINGS:
        for lang in fb_gui.LANGS:
            text = fb_gui.warning_text(code, lang, u"x")
            r.check("warning {0} {1}".format(code, lang),
                    ("w_" + code) in fb_gui.T and text != code, text)
    for code in PHASE4_REFUSALS:
        for lang in fb_gui.LANGS:
            text = fb_gui.reason_text(code, lang, u"Rib")
            r.check("refusal {0} {1}".format(code, lang), ("r_" + code) in fb_gui.T, text)
    r.check("detail in the text", u"Rib" in fb_gui.reason_text("beam_warping", "nl", u"Rib"))
    for kind in fb_gui.AXES_KINDS:
        for prefix in ("ax_r_", "ax_s_", "ax_n_", "sign_"):
            r.check("text {0}{1}".format(prefix, kind), (prefix + kind) in fb_gui.T)


def test_drilling_names_the_coefficient(r):
    model = sup.shell_case(warnings=["drilling"])
    text = u" ".join(model.warning_lines())
    r.check("default named", u"default, 1e-5" in text, text)
    model = sup.shell_case(warnings=["drilling"], coef=0.001)
    model.lang = "nl"
    text = u" ".join(model.warning_lines())
    r.check("value named", u"COEF_RIGI_DRZ = 0,001" in text, text)
    model = sup.shell_case(warnings=[("drilling", None), "drilling"])
    r.check("once", [w[1] for w in model.warnings].count("drilling") == 1, model.warnings)


def test_core_warnings_shown(r):
    model = sup.shell_case(warnings=["skin_shell", "beam_along_cut", "node_contact"])
    lines = model.warning_lines()
    for code in ("skin shell", "both nodes on the cut", "no cut entity"):
        r.check("shown: " + code, any(code in line for line in lines), lines)


def test_not_shared_text(r):
    r.check("schema 1 list", fb_gui.not_shared_text(["tie", "contact"]) == u"tie, contact")
    r.check("schema 2 dict", fb_gui.not_shared_text(
        {"tie": {"nodes": [1], "origin": "user"}, "rbe3": {}}) == u"rbe3, tie")
    r.check("none", fb_gui.not_shared_text(None) == u"")


# ---- props from Mecway ------------------------------------------------------------------
def test_shell_props(r):
    m, component = sup.models.plate(cells=(3, 1), beam_along=True)
    component[1] = u"PlateBad"
    component[3] = u"Composite"
    mesh = sup._mesh_of(m, component)
    missing = {}
    props, unknown = fb_mecway.read_props(FakeMw(m), mesh, missing)
    r.close("thickness", props[2]["thickness"], 0.005)
    r.close("E of the shell", props[2]["E"], 70e9)
    r.check("beam has no thickness", "thickness" not in props[5], props[5])
    r.check("E of the beam", props[5]["E"] == 70e9)
    r.check("composite: thickness, no E", props[3] == {"thickness": 0.002}, props[3])
    r.check("unknown E named", unknown == [u"Composite"], unknown)
    r.check("missing thickness named", missing["thickness"] == [u"PlateBad"], missing)
    r.check("old call still works", len(fb_mecway.read_props(FakeMw(m), mesh)) == 2)
    model = sup.shell_case()
    model.note_missing({"thickness": [u"Plate", u"Other"]})
    lines = model.warning_lines()
    r.check("warned for the selection only", lines[-1].endswith(u"for: Plate."), lines)


def test_props_of_a_solid_unchanged(r):
    m, mesh = sup.make_mesh("hex8")
    props = fb_mecway.read_props(FakeMw(m), mesh)[0]
    r.check("no thickness on solids", all("thickness" not in p for p in props.values()))


# ---- nodal moments from the saved .liml (drilling warning) -------------------------------
class FaceId(object):
    def __init__(self, eid, face):
        self.element_id = eid
        self.face_number = face


class LoadsMw(FakeMw):
    """FakeMw with named selections and face nodes, as measured in Mecway 35:
    ints for node selections, FaceId for faces; face 2 and 3 of a line are its
    nodes 1 and 2, face k of a quad4 its edge from corner k."""

    def __init__(self, m, path, members):
        FakeMw.__init__(self, m, path=path)
        self.members = members

    def named_selection(self, name):
        self._touch()
        if name not in self.members:
            raise Exception('Named selection "{0}" does not exist.'.format(name))
        return [FaceId(*i) if isinstance(i, tuple) else i for i in self.members[name]]

    def face_nodes(self, face):
        shape, nids = self.m.elements[face.element_id]
        k = face.face_number
        if shape.startswith("line"):
            return [nids[0] if k == 2 else nids[1]]
        return [nids[k - 1], nids[k % 4]]


def _temp_liml(text):
    folder = tempfile.mkdtemp(prefix="fb_loads_")
    path = os.path.join(folder, u"plate.liml")
    with io.open(path, "w", encoding="utf-8", newline=u"\n") as f:
        f.write(text)
    return folder, path


def _read_moments(mw, mesh, size=fb_mecway.READ_BLOCK):
    out = {}
    count = 0
    for _ in fb_mecway.read_moments_steps(mw, mesh, out, size=size):
        count += 1
    return out, count


def _same_moments(got, want):
    return sorted(got) == sorted(want) and all(
        max(abs(a - b) for a, b in zip(got[n], want[n])) < 1e-12 for n in want)


def test_moments_from_the_liml(r):
    folder = tempfile.mkdtemp(prefix="fb_loads_")
    try:
        path = os.path.join(folder, u"plate.liml")
        m, component = sup.models.write_shell_liml(path, loads=True)
        lines, members, expected = sup.models.shell_loads(m)
        mesh = sup._mesh_of(m, component)
        for size in (fb_mecway.READ_BLOCK, 64, 7):
            out, count = _read_moments(LoadsMw(m, path, members), mesh, size)
            r.check("moments as the bridge sees them, blocks of {0}".format(size),
                    _same_moments(mesh["moments"], expected), mesh["moments"])
            r.check("no unknown direction", mesh["moment_nodes"] == [], mesh["moment_nodes"])
            r.check("all read", out["unread"] is None, out)
        r.check("hands back the thread", count > 3, count)
        plan = fb_core.plan_cuts(mesh, [2])
        r.check("a moment about the normal warns", "nodal_moment" in plan["drilling"],
                plan["drilling"])
        tip = members[u"MN1"][0]
        turned = members[u"ROT"][0]
        for n in (tip, turned):
            del mesh["moments"][n]
        plan = fb_core.plan_cuts(mesh, [2])
        r.check("in-plane moments only: no warning", "nodal_moment" not in plan["drilling"],
                plan["drilling"])
    finally:
        shutil.rmtree(folder, True)


def test_moments_unknown_direction(r):
    m, component = sup.models.plate(beam_along=True)
    mesh = sup._mesh_of(m, component)
    nids = sorted(m.xyz)
    members = dict((u"N{0}".format(n), [n]) for n in nids)
    body_kinds = [u'  <nodeselection name="N{0}" direct="true"></nodeselection>'.format(n)
                  for n in nids]
    members[u"A&B"] = [nids[0]]
    body = [
        u'<liml version="35">',
        u'  <solutionfile filename="x.liml" />'] + body_kinds + [
        # a formula (as text, or as an attribute), an unknown unit, a missing
        # component
        u'  <moment selection="N{0}"><x>2*x N.m</x><y>0 N.m</y><z>0 N.m</z></moment>'.format(nids[1]),
        u'  <moment selection="N{0}"><x formula="2*t">0 N.m</x><y>0 N.m</y><z>0 N.m</z>'
        u'</moment>'.format(nids[1]),
        u'  <moment selection="N{0}"><x>1 foo</x><y>0 foo</y><z>1 foo</z></moment>'.format(nids[2]),
        u'  <moment selection="N{0}"><x>1 N.m</x><y>0 N.m</y></moment>'.format(nids[3]),
        # a history that turns, and one that keeps its line
        u'  <moment selection="N{0}"><x time="0 s">1 N.m</x><x time="1 s">0 N.m</x>'
        u'<y time="0 s">0 N.m</y><y time="1 s">1 N.m</y><z>0 N.m</z></moment>'.format(nids[4]),
        u'  <moment selection="N{0}">\r\n<x time="0 s">0 N.m</x>\r\n<x time="1 s">-4 N.m</x>\r\n'
        u'<y>0 N.m</y><z>0 N.m</z></moment>'.format(nids[5]),
        # two loads on one node: N.m and kN.m add up after conversion
        u'  <moment selection="N{0}"><x>1000 N.m</x><y>0 N.m</y><z>0 N.m</z></moment>'.format(nids[6]),
        u'  <moment selection="N{0}"><x>0 kN.m</x><y>-1 kN.m</y><z>0 kN.m</z></moment>'.format(nids[6]),
        # a steady and a changing one on one node: no direction
        u'  <moment selection="N{0}"><x>1 N.m</x><y>0 N.m</y><z>0 N.m</z></moment>'.format(nids[7]),
        u'  <moment selection="N{0}"><x time="0 s">1 N.m</x><x time="1 s">2 N.m</x><y>0 N.m</y>'
        u'<z>0 N.m</z></moment>'.format(nids[7]),
        # an escaped name, a load without a selection, an unknown selection
        u'  <moment selection="A&amp;B"><x>0 N.m</x><y>0 N.m</y><z>-1e-3 MN.m</z></moment>',
        u'  <moment selection=""><x>0 N.m</x><y>0 N.m</y><z>5 N.m</z></moment>',
        u'  <moment selection="GONE"><x>0 N.m</x><y>0 N.m</y><z>5 N.m</z></moment>',
        u'  <nodeselection name="GONE" direct="true"></nodeselection>',
        # the first definition of a name counts
        u'  <elementselection name="N{0}"></elementselection>'.format(nids[6]),
        # the model copy of a solution repeats loads: not counted
        u'  <solution configuration="C">',
        u'  <moment selection="N{0}"><x>0 N.m</x><y>0 N.m</y><z>9 N.m</z></moment>'.format(nids[0]),
        u'  </solution>',
        u'</liml>']
    folder, path = _temp_liml(u"﻿" + u"\n".join(body))
    try:
        for size in (fb_mecway.READ_BLOCK, 5):
            mw = LoadsMw(m, path, members)
            out, _ = _read_moments(mw, mesh, size)
            want = {nids[5]: (-4.0, 0.0, 0.0), nids[6]: (1000.0, -1000.0, 0.0),
                    nids[0]: (0.0, 0.0, -1000.0)}
            r.check("directions that can be told, blocks of {0}".format(size),
                    _same_moments(mesh["moments"], want), mesh["moments"])
            r.check("the others count without one",
                    mesh["moment_nodes"] == sorted(nids[1:5] + [nids[7]]), mesh["moment_nodes"])
            r.check("unknown selection named", out["unread"] == [u"GONE"], out)
    finally:
        shutil.rmtree(folder, True)


def test_moments_not_read(r):
    m, component = sup.models.plate(beam_along=True)
    mesh = sup._mesh_of(m, component)
    folder = tempfile.mkdtemp(prefix="fb_loads_")
    try:
        for path, code in ((u"", "not_saved"), (os.path.join(folder, u"p.inp"), "not_liml"),
                           (os.path.join(folder, u"none.liml"), "unreadable")):
            out, _ = _read_moments(LoadsMw(m, path, {}), mesh)
            r.check("unread: " + code, out["unread"] == code, out)
            r.check("nothing guessed: " + code, mesh["moments"] == {} and
                    mesh["moment_nodes"] == [])
        folder2, path = _temp_liml(u'<liml><moment selection="S"><x>1 N.m</x>' + u" " * 64)
        try:
            out, _ = _read_moments(LoadsMw(m, path, {}), mesh, 16)
            r.check("a file that ends inside an element is unread", mesh["moments"] == {} and
                    out["unread"] == "unreadable", out)
        finally:
            shutil.rmtree(folder2, True)
    finally:
        shutil.rmtree(folder, True)


def test_moments_unread_warning(r):
    model = sup.shell_case()
    model.note_missing({"moments": "not_saved"})
    lines = model.warning_lines()
    r.check("file not read: said", u"Moment loads not read (model not saved yet)" in lines[-1],
            lines)
    model.lang = "nl"
    lines = model.warning_lines()
    r.check("in Dutch too", u"(model nog niet opgeslagen)" in lines[-1], lines)
    model = sup.shell_case()
    model.note_missing({"moments": [u"GONE", u"S2"]})
    r.check("selections named", u"unknown selection: GONE, S2" in model.warning_lines()[-1],
            model.warning_lines())
    m, mesh = sup.make_mesh("hex8")
    plan = fb_core.plan_cuts(mesh, sup.selected_slice())
    geos = dict((g["id"], fb_core.section_geometry(mesh, g, None)) for g in plan["groups"])
    result = sup.make_result(plan, mesh)
    model = fb_gui.PanelModel()
    model.load(mesh, plan, geos, result, fb_core.assign_nodes(plan, mesh, result),
               sup.manifest("x"), u"f")
    count = len(model.warnings)
    model.note_missing({"moments": "not_saved"})
    r.check("no shells: no warning", len(model.warnings) == count, model.warnings)


def test_has_shells(r):
    m, component = sup.models.plate()
    r.check("plate has shells", fb_gui.has_shells(sup._mesh_of(m, component)))
    r.check("block has none", not fb_gui.has_shells(sup.make_mesh("hex8")[1]))


# ---- the real core, once it is there ----------------------------------------------------
def test_real_core_smoke(r):
    """The real core on the plate: skipped until it gives strips."""
    m, component = sup.models.plate(cells=(3, 1))
    mesh = sup._mesh_of(m, component)
    props = dict((e, {"E": 210e9, "thickness": sup.THICKNESS}) for e in mesh["elements"])
    try:
        plan = fb_core.plan_cuts(mesh, [2])
        geos = dict((g["id"], fb_core.section_geometry(mesh, g, props))
                    for g in plan["groups"])
    except fb_core.Refused as e:
        r.check("real core smoke: skipped (core refuses shells: {0})".format(e.code), True)
        return
    if not all("strips" in g for g in geos.values()):
        r.check("real core smoke: skipped (no strips yet)", True)
        return
    model = sup.load_case(mesh, plan, geos, sup.manifest("x", schema=2))
    r.check("real core: two cuts", len(model.cuts) == 2, len(model.cuts))
    r.check("real core: strip axes", all(model.axes_kind(c) == "strip" for c in model.cuts),
            [model.axes_kind(c) for c in model.cuts])
    for i in range(len(model.cuts)):
        model.index = i
        r.check("real core: cut {0} drawn".format(i + 1),
                len(model.view()["strips"]) >= 1)
    r.check("real core: rows", len(model.rows()) == 2)


def main():
    report = sup.Report()
    report.run(globals())
    return report


if __name__ == "__main__":
    out = main()
    for line in out.lines:
        if not line.startswith("OK"):
            print(line)
    print("{0} checks, {1} failed".format(len(out.lines), out.failed))
    sys.exit(1 if out.failed else 0)
