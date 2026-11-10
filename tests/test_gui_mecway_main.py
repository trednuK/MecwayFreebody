# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_mecway_main.py
# The script Mecway runs: `mecway.exe <model> script <this file>`, hidden, from
# test_gui_all.py. What to do comes from FB_TEST; everything is caught and goes
# to the JSON file in FB_RESULT, because a script error would open a dialog.
#   solve    solve the model and save it as FB_SOLVED
#   logic    test_gui_logic in this IronPython
#   compile  compile the scripts of the panel as this IronPython's Python 2.7
#   real     fb_mecway on the real mw and solution of a solved block
#   window   the real window (test_gui_window)
#   nodes    the real window with a cut by nodes on a plane
#   docs     the tab Documentation of the real window
#   trap     the focus trap on a small window of its own (test_gui_focus)

import io
import json
import os
import sys
import traceback

_RESULT = os.environ["FB_RESULT"]
_ROOT = os.environ["FB_ROOT"]
_OUT = {"lines": [], "failed": 0}


def _save():
    window = sys.modules.get("test_gui_window")
    if window is not None and window.INVALID:
        _OUT["invalid"] = u" | ".join(window.INVALID)
    trap = sys.modules.get("test_gui_focus")
    for attempt in (trap.unreported() if trap is not None else []):
        # refused by the trap after the last check of the window (or an error
        # in the hook): counts as a failure
        _OUT["failed"] += 1
        _OUT["lines"].append(u"FAIL  focus trap, after the last check  [{0}]".format(
            trap.describe(attempt)))
    with io.open(_RESULT, "w", encoding="utf-8") as f:
        f.write(u"{0}".format(json.dumps(_OUT, ensure_ascii=False, indent=0)))


def do_solve():
    mw.solve()
    mw.save_as(os.environ["FB_SOLVED"])
    _OUT["python"] = sys.version


def do_logic():
    import test_gui_logic
    report = test_gui_logic.main()
    _OUT["lines"], _OUT["failed"] = report.lines, report.failed


def do_compile():
    import test_gui_support as sup
    report = sup.Report()
    report.check("IronPython 2.7.9", sys.version.startswith("2.7.9"), sys.version)
    for name in ("MecwayFreebody.py", "fb_mecway.py", "fb_gui.py", "fb_nodecut.py", "fb_docs.py"):
        path = os.path.join(_ROOT, "Scripts", name)
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        text = text.replace(u"coding: utf-8", u"coding- utf-8")
        try:
            compile(text, path, "exec")
            report.check("compiles: " + name, True)
        except SyntaxError as e:
            report.check("compiles: " + name, False, e)
    _OUT["lines"], _OUT["failed"] = report.lines, report.failed


def _check_mesh(r):
    """The mesh through the API against the numbers written in the file."""
    import fb_aster
    import fb_mecway
    with io.open(os.environ["FB_EXPECT"], encoding="utf-8") as f:
        expect = json.loads(f.read())
    out = {}
    for _ in fb_mecway.read_mesh_steps(mw, out):
        pass
    mesh = out["mesh"]
    r.check("all nodes", len(mesh["nodes"]) == len(expect["nodes"]))
    r.check("all elements", len(mesh["elements"]) == len(expect["elements"]))
    bad = [e for e, row in expect["elements"].items()
           if list(mesh["elements"][int(e)]) != row]
    r.check("node order and shape as in the file", not bad, bad[:3])
    far = max(max(abs(mesh["nodes"][int(n)][k] - xyz[k]) for k in range(3))
              for n, xyz in expect["nodes"].items())
    r.check("coordinates as in the file", far < 1e-12, far)
    # the fingerprint of the API against the one of the numbers in the file, as
    # the bridge hashes them
    nodes = dict((int(n), tuple(v)) for n, v in expect["nodes"].items())
    r.check("fingerprint API = file",
            fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"])) ==
            fb_aster.mesh_fingerprint(nodes, [int(e) for e in expect["elements"]]))
    r.check("area and centroid", _geometry(r, mesh))
    return mesh


def do_splice():
    """A copy of the model with the results of its run, as the bridge writes it
    back (bridge code, which runs in IronPython)."""
    sys.path.insert(0, os.environ["FB_BRIDGE"])
    import bridge_results_liml
    bridge_results_liml.splice_results(mw.file_name(), os.environ["FB_FRAGMENT"],
                                       os.environ["FB_SOLVED"])


def do_mesh():
    import test_gui_support as sup
    r = sup.Report()
    _check_mesh(r)
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_real():
    import test_gui_support as sup
    import fb_mecway
    r = sup.Report()
    mesh = _check_mesh(r)
    props, unknown = fb_mecway.read_props(mw, mesh)
    r.check("E read", props[1]["E"] == 210e9 and not unknown, unknown)
    r.check("path", fb_mecway.model_path(mw).endswith(".liml"))
    selection = fb_mecway.read_selection(mw, solution)
    r.check("selection reads", selection["elements"] == [], selection)
    r.check("node selection reads", selection["node_ids"] == [] and selection["nodes"] == 0,
            selection)
    r.check("solution fits", fb_mecway.check_solution(mw, solution, list(mesh["nodes"])) is None)
    own = {}
    values = {1: (3.0, 4.0, 0.0, 0.0, 0.0, 0.0), 7: (0.0, -8.0, 6.0, 0.0, 0.0, 2.0)}
    res = {}
    for _ in fb_mecway.arrow_steps(mw, solution, values, own, res):
        pass
    r.check("both vectors written", sorted(res["written"]) == ["force", "moment"], res)
    r.close("first write holds the true value", solution.node_value("externalforcey", 1), 4.0)
    r.check("rest stays empty", solution.node_value("externalforcey", 2) is None)
    r.close("magnitude follows", solution.node_value("externalforcemag", 7), 10.0)
    r.close("moment at its own scale", solution.node_value("reactionmomz", 7), 2.0)
    # second write by this panel
    res = {}
    for _ in fb_mecway.arrow_steps(mw, solution, {9: (0.0, 0.0, 9.0, 0.0, 0.0, 0.0)}, own, res):
        pass
    r.check("own field written again", res["written"] == ["force"], res)
    r.close("same length as the first write", solution.node_value("externalforcez", 9), 10.0)
    r.check("old arrow gone", solution.node_value("externalforcey", 1) is None)
    # the moment of this write is zero: the panel's old moment is cleared with
    # an all-None set_variable (measured here)
    r.check("old moment cleared", res["cleared"] == ["moment"] and not res["skipped"], res)
    r.check("cleared moment is empty in Mecway",
            all(solution.node_value(f, 7) is None
                for f in ("reactionmomx", "reactionmomy", "reactionmomz", "reactionmommag")),
            [solution.node_value(f, 7) for f in ("reactionmomz", "reactionmommag")])
    res = {}
    for _ in fb_mecway.arrow_steps(mw, solution, {7: (0.0, 0.0, 1.0, 0.0, 0.0, 4.0)}, own, res):
        pass
    r.check("a moment goes in again after the clear",
            sorted(res["written"]) == ["force", "moment"], res)
    r.close("at the length of the first write", solution.node_value("reactionmomz", 7), 2.0)
    # another session of the panel: the field is no longer known as ours
    res = {}
    for _ in fb_mecway.arrow_steps(mw, solution, values, {}, res):
        pass
    r.check("field of an earlier session is refused", ("force", "exists") in res["skipped"], res)
    mw.save_as(os.environ["FB_SAVED"])
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def _geometry(r, mesh):
    """fb_core on what mw gave: wrong node order gives a wrong area."""
    import fb_core
    plan = fb_core.plan_cuts(mesh, [int(e) for e in os.environ["FB_SELECT"].split()])
    area = float(os.environ["FB_AREA"])
    ok = True
    for group in plan["groups"]:
        geo = fb_core.section_geometry(mesh, group, None)
        ok = r.close("area of a cut", geo["area"], area, 1e-9) and ok
        ok = r.check("planar", geo["planar"]) and ok
    return ok and len(plan["groups"]) == 2


def _quiet_settings():
    """Keep the settings of a user out of it."""
    import fb_gui
    fb_gui.SETTINGS_PATH = os.path.join(os.environ["FB_PNG"], "settings.json")
    fb_gui._CACHE["settings"] = dict(fb_gui._DEFAULTS)
    fb_gui._CACHE["settings"].update({
        "language": "en", "folder": "other", "folder_other": os.environ["FB_RUNS"],
        "exe_aster": os.environ["FB_EXE"]})


def _check_moments(r, mesh):
    """The moment loads of test_gui_model.shell_loads through the real mw and
    the saved file: one node, a beam end face, a rotation; not two nodes, a
    shell face or a rotation held at zero."""
    import fb_core
    import fb_mecway
    import test_gui_model as models
    m, _ = models.plate(beam_along=True)
    expected = models.shell_loads(m)[2]
    # read what Mecway itself writes: save a copy, which becomes the model's file
    copy = os.path.join(os.path.dirname(mw.file_name()), "plate_saved.liml")
    mw.save_as(copy)
    r.check("the saved copy is the model's file",
            os.path.normcase(fb_mecway.model_path(mw)) == os.path.normcase(copy),
            fb_mecway.model_path(mw))
    out = {}
    steps = 0
    for _ in fb_mecway.read_moments_steps(mw, mesh, out):
        steps += 1
    got = mesh["moments"]
    same = sorted(got) == sorted(expected) and all(
        max(abs(a - b) for a, b in zip(got[n], expected[n])) < 1e-12 for n in expected)
    _OUT["moments"] = u"{0}".format(sorted(got.items()))
    r.check("moments read as the bridge sees them", same, (got, expected))
    r.check("no moment without a direction", mesh["moment_nodes"] == [], mesh["moment_nodes"])
    r.check("all selections known", out["unread"] is None, out)
    r.check("read in steps", steps >= 1, steps)
    r.check("moment about the normal warns",
            "nodal_moment" in fb_core.plan_cuts(mesh, [2])["drilling"])


def do_shells():
    """Shell props through the real mw, then the window with shell and beam
    cuts made by hand."""
    import test_gui_support as sup
    import test_gui_window
    import fb_mecway
    r = sup.Report()
    mesh = {}
    for _ in fb_mecway.read_mesh_steps(mw, mesh):
        pass
    mesh = mesh["mesh"]
    shapes = sorted(set(s for s, _ in mesh["elements"].values()))
    r.check("plate and rib read", shapes == ["line2", "quad4"], shapes)
    r.check("components", sorted(set(mesh["component"].values())) == [u"Plate", u"Rib"],
            sorted(set(mesh["component"].values())))
    missing = {}
    props, unknown = fb_mecway.read_props(mw, mesh, missing)
    shells = [e for e, (s, _) in mesh["elements"].items() if s == "quad4"]
    beams = [e for e, (s, _) in mesh["elements"].items() if s == "line2"]
    try:
        material = mw.material(u"Plate")
        _OUT["geometric"] = u"{0}".format(mw.material_type(material, "geometric"))
        _OUT["thickness_raw"] = u"{0!r}".format(mw.material_property(material, "thickness"))
    except Exception as e:
        _OUT["geometric"] = u"error: {0}".format(e)
    r.check("thickness of the shells", all(abs(props[e].get("thickness", 0) - 0.005) < 1e-12
                                           for e in shells), [props.get(e) for e in shells])
    r.check("E of the shells", all(props[e].get("E") == 210e9 for e in shells))
    r.check("no thickness on beams", all("thickness" not in props[e] for e in beams))
    r.check("E of the beams", all(props[e].get("E") == 70e9 for e in beams),
            [props.get(e) for e in beams])
    r.check("nothing missing", not unknown and missing["thickness"] == [], (unknown, missing))
    _check_moments(r, mesh)
    _quiet_settings()
    test_gui_window.phase4(mw, solution, r, os.environ["FB_PNG"])
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_entry():
    import test_gui_support as sup
    import test_gui_window
    r = sup.Report()
    _quiet_settings()
    test_gui_window.entry_point(mw, solution, r, os.environ["FB_PNG"], [],
                                os.path.join(_ROOT, "Scripts", "MecwayFreebody.py"))
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_reopen():
    import test_gui_support as sup
    import test_gui_window
    r = sup.Report()
    _quiet_settings()
    selection = [int(e) for e in os.environ["FB_SELECT"].split()]
    box = test_gui_window.reopened(mw, solution, r, os.environ["FB_PNG"], selection,
                                   mw.file_name())
    _OUT["reason"] = box.get("reason")
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_window():
    import test_gui_support as sup
    import test_gui_window
    import fb_aster
    import fb_gui
    r = sup.Report()
    folder = os.path.dirname(mw.file_name())
    run_dir = os.environ["FB_RUNS"]
    _quiet_settings()
    nodes = {}
    for n in mw.all_nodes():
        p = mw.node(n)
        nodes[int(n)] = (p.x, p.y, p.z)
    fp = fb_aster.mesh_fingerprint(nodes, [int(e) for e in mw.all_elements()])
    stem = os.path.splitext(os.path.basename(mw.file_name()))[0]
    sup.write_run(run_dir, sup.manifest(fp, model=stem))
    sup.write_run(run_dir, sup.manifest(fp, run_id="20261001_100000", aster_version="16.9",
                                        model=stem))
    selection = [int(e) for e in os.environ["FB_SELECT"].split()]
    test_gui_window.run(mw, solution, r, os.environ["FB_PNG"], folder, None, selection)
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_trap():
    """The focus trap on a small window of its own, before the real window
    parts (test_gui_focus.proof)."""
    import test_gui_support as sup
    import test_gui_focus
    import test_gui_window
    r = sup.Report()
    done = test_gui_focus.proof(r, test_gui_window.offscreen_location())
    _OUT["trap"] = {"attempts": done.get("attempts"), "counts": done.get("counts")}
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_docs():
    """The tab Documentation in the window, on the solved block."""
    import test_gui_support as sup
    import test_gui_window
    r = sup.Report()
    _quiet_settings()
    test_gui_window.docs_tab(mw, solution, r, os.environ["FB_PNG"])
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_nodes():
    """A cut by nodes on a plane in the window, on the solved block (x = 0.08
    between its cells 2 and 3)."""
    import test_gui_support as sup
    import test_gui_window
    import fb_aster
    r = sup.Report()
    run_dir = os.environ["FB_RUNS"]
    _quiet_settings()
    nodes = {}
    for n in mw.all_nodes():
        p = mw.node(n)
        nodes[int(n)] = (p.x, p.y, p.z)
    fp = fb_aster.mesh_fingerprint(nodes, [int(e) for e in mw.all_elements()])
    stem = os.path.splitext(os.path.basename(mw.file_name()))[0]
    sup.write_run(run_dir, sup.manifest(fp, model=stem))
    mesh = {"nodes": nodes,
            "elements": dict((int(e), (str(mw.element_shape(e)), [int(q) for q in mw.nodes(e)]))
                             for e in mw.all_elements())}
    full = sup.nodes_at(mesh, 0.08)
    picked = {"full": full, "top": sup.nodes_at(mesh, 0.08, lambda y, z: z > -1e-9),
              "bent": full + sup.nodes_at(mesh, 0.12)[:1]}
    r.check("nodes of the section found", len(full) == 21, len(full))
    test_gui_window.node_cut(mw, solution, r, os.environ["FB_PNG"], picked)
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


def do_real_run():
    """The panel on a base of the bridge: experiment E9's bar of 200 x 20 x 40
    mm, 20 x 4 x 8 cells, the middle half selected, tip and side loads and
    gravity. The reference is statics: the loads beyond a cut, about its
    centroid."""
    import test_gui_support as sup
    import test_gui_window
    import fb_aster
    import fb_gui
    r = sup.Report()
    _quiet_settings()
    per_slice = 4 * 8
    selection = list(range(5 * per_slice + 1, 15 * per_slice + 1))
    rho, g = 7850.0, 9.81
    area = 0.02 * 0.04
    weight = -rho * g * area            # N per metre of bar, along z
    tip = (2000.0, 500.0, -1000.0)
    side = -300.0

    def expected(x_cut, sign):
        """sign +1: the far side of the cut at x_cut pulls on the selection."""
        if sign > 0:
            fz = tip[2] + weight * (0.2 - x_cut)
            my = -((0.2 - x_cut) * tip[2] + (0.2 - x_cut) / 2 * weight * (0.2 - x_cut))
            mz = (0.2 - x_cut) * tip[1]
            return ((tip[0], tip[1], fz), (0.0, my, mz))
        fz = -(tip[2] + side + weight * (0.2 - x_cut))
        # the side load stands on two cells from x = 0.05, on the top face
        arm_side = 0.05 + 0.01 - x_cut
        arm = (0.2 - x_cut) / 2
        my = (0.2 - x_cut) * tip[2] + arm_side * side + arm * weight * (0.2 - x_cut)
        return ((-tip[0], -tip[1], fz), (0.0, my, -(0.2 - x_cut) * tip[1]))
    expect = {0.15: expected(0.15, 1), 0.05: expected(0.05, -1)}
    box = test_gui_window.real_run(mw, solution, r, os.environ["FB_PNG"], selection, expect,
                                   os.environ.get("FB_SOLVED_MODEL") == "1")
    _OUT["seconds"] = box.get("seconds")
    _OUT["arrow_text"] = box.get("arrow_text")
    _OUT["lines"], _OUT["failed"] = r.lines, r.failed


try:
    for _path in (os.path.join(_ROOT, "tests"), os.path.join(_ROOT, "Scripts"),
                  os.environ.get("FB_CORE_DIR")):
        if _path and _path not in sys.path:
            sys.path.insert(0, _path)
    {"solve": do_solve, "logic": do_logic, "compile": do_compile, "real": do_real,
     "window": do_window, "real_run": do_real_run, "mesh": do_mesh, "entry": do_entry, "splice": do_splice,
     "reopen": do_reopen, "shells": do_shells, "nodes": do_nodes,
     "docs": do_docs, "trap": do_trap}[os.environ["FB_TEST"]]()
except Exception:
    _OUT["failed"] += 1
    _OUT["lines"].append(u"FAIL  script  [{0}]".format(traceback.format_exc()))
_save()
