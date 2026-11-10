# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_window.py
# The real window with the real threads, in Mecway's IronPython (through
# test_gui_mecway_main.py). It stands off-screen, never takes the focus, is
# driven by calling its handlers, and draws itself into PNG files in the folder
# FB_PNG. Only the run of Code-Aster is stood in for (FakeJob).
# Hard rules, checked on every timer tick: the window lies beyond the whole
# virtual desktop, is not in the taskbar, shows without activation, and neither
# it nor anything of this process is the foreground window. A broken focus rule
# makes the run invalid (INVALID); test_gui_runner then stops the whole set.

import os
import time
import traceback

import test_gui_focus as focus_trap
import test_gui_support as sup

import fb_aster
import fb_gui
import fb_mecway

INVALID = []        # broken focus rules: the run does not count
_SPAN = 6000        # more than any size the tests give the window


def offscreen_location():
    """A point beyond the bottom-right of the whole virtual desktop, all
    monitors: the window and what it grows into (sizes go right and down from
    the location) stay off every monitor. Coordinates in window messages are
    16-bit, so a desktop far to the right puts it beyond the top-left."""
    import clr
    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import SystemInformation
    v = SystemInformation.VirtualScreen
    x, y = v.Right + 2000, v.Bottom + 2000
    if x + _SPAN > 30000 or y + _SPAN > 30000:
        x, y = v.Left - 2000 - _SPAN, v.Top - 2000 - _SPAN
    return (x, y)


def quiet_options(**extra):
    """Options of run_window for a test: off-screen, never activated, and the
    focus trap on the window thread (test_gui_focus): an attempt to activate or
    focus is refused and written down, and ScreenGuard reports it."""
    options = {"no_activate": True, "location": offscreen_location(),
               "on_thread": focus_trap.on_thread}
    options.update(extra)
    return options


def _user32():
    import ctypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindow.restype = ctypes.c_void_p
    u.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    return ctypes, u


def screen_rules(window):
    """(placement problems, focus problems) of the test window right now."""
    import System
    from System.Windows.Forms import SystemInformation, FormWindowState, Form
    ctypes, u = _user32()
    form = window.form
    place, focus = [], []
    desk = SystemInformation.VirtualScreen
    if form.Bounds.IntersectsWith(desk):
        place.append(u"on the desktop: {0} within {1}".format(form.Bounds, desk))
    if form.WindowState != FormWindowState.Normal:
        place.append(u"window state {0}".format(form.WindowState))
    if form.ShowInTaskbar:
        place.append(u"in the taskbar")
    try:
        quiet_show = form.ShowWithoutActivation
    except Exception:
        quiet_show = form.get_ShowWithoutActivation()
    if quiet_show is not True:
        place.append(u"ShowWithoutActivation is {0}".format(quiet_show))
    if form.IsHandleCreated and not u.GetWindow(ctypes.c_void_p(form.Handle.ToInt64()), 4):
        place.append(u"no owner window, so in Alt+Tab")          # GW_OWNER
    if form.IsHandleCreated and not fb_gui.has_no_activate(form.Handle.ToInt64()):
        place.append(u"no WS_EX_NOACTIVATE")
    if form.ContainsFocus or Form.ActiveForm is not None:
        focus.append(u"the window has the focus")
    hwnd = u.GetForegroundWindow()
    if hwnd:
        owner = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == System.Diagnostics.Process.GetCurrentProcess().Id:
            text = ctypes.create_unicode_buffer(200)
            u.GetWindowTextW(ctypes.c_void_p(hwnd), text, 200)
            focus.append(u"foreground window {0!r} is of Mecway".format(text.value))
    return place, focus


class ScreenGuard(object):
    """The hard rules on a window, at moments the caller names. Also what the
    focus trap refused since the last check: each attempt is a FAIL (refused,
    so the run stays valid), with the frames that made it."""

    def __init__(self, window, report):
        self.window = window
        self.report = report
        self.count = 0
        self.broken = False
        self.attempts = 0
        self.active = []            # changes of form.ActiveControl: (moment, type)

    def _trap(self, moment, place):
        trap = focus_trap.current()
        if trap is None or not trap.live():
            place.append(u"focus trap not live on the window thread")
            return
        for attempt in trap.new_attempts():
            self.attempts += 1
            if self.attempts <= 8:
                self.report.check(u"no attempt to activate or focus the window", False,
                                  focus_trap.describe(attempt))
        form = self.window.form
        control = form.ActiveControl if not form.IsDisposed else None
        name = type(control).__name__ if control is not None else None
        if (self.active[-1][1] if self.active else None) != name:
            self.active.append((moment, name))

    def check(self, moment):
        """False when a rule is broken; that is reported once."""
        if self.broken:
            return False
        self.count += 1
        place, focus = screen_rules(self.window)
        self._trap(moment, place)
        if focus:
            INVALID.append(u"{0}: {1}; active control {2}".format(
                moment, u"; ".join(focus), self.active[-3:]))
        if place or focus:
            self.broken = True
            self.report.check(u"window off the desktop and never active", False,
                              u"{0}: {1}".format(moment, u"; ".join(place + focus)))
            return False
        return True

    def done(self):
        if not self.broken:
            self.report.check(u"window off the desktop and never active, {0} checks".format(
                self.count), True)
        if not self.attempts:
            self.report.check(u"focus trap: no attempt to activate or focus", True)


class MessageMw(object):
    """The real mw, but mw.message records: it would open a dialog of Mecway
    on the screen."""

    def __init__(self, mw):
        self._mw = mw
        self.messages = []

    def __getattr__(self, name):
        return getattr(self._mw, name)

    def message(self, text):
        self.messages.append(text)


class SelectingMw(object):
    """The real mw, with a selection: a script cannot set one."""

    def __init__(self, mw, selected, nodes=()):
        self._mw = mw
        self.selected = list(selected)
        self.picked = list(nodes)
        self.alive = True

    def __getattr__(self, name):
        if not self.alive:
            raise RuntimeError("model closed")
        return getattr(self._mw, name)

    def selected_elements(self):
        if not self.alive:
            raise RuntimeError("model closed")
        return list(self.selected)

    def selected_nodes(self):
        if not self.alive:
            raise RuntimeError("model closed")
        return list(self.picked)


LABEL_PAIRS = (("step_label", "step_combo"), ("unit_label", "unit_combo"),
               ("axes_label", "radio_section"), ("mode_label", "mode_combo"),
               ("folder_label", "folder_combo"), ("run_title", "run_combo"),
               ("arrow_title", "arrow_combo"), ("point_title", "point_boxes"))


def label_overlaps(w):
    """Labels whose box or text reaches into the field next to them, on the
    same row: [(label, its right edge, end of its text, left edge of the field)]."""
    measure = w.F.TextRenderer.MeasureText
    bad = []
    for name, field_name in LABEL_PAIRS:
        label = getattr(w, name)
        field = getattr(w, field_name)
        if field_name == "point_boxes":
            field = field[0]
        if not (label.Top < field.Bottom and field.Top < label.Bottom):
            bad.append((name, u"not on the row of " + field_name))
            continue
        text_end = label.Left + measure(label.Text, label.Font).Width
        if label.Right > field.Left or text_end > field.Left:
            bad.append((name, label.Right, text_end, field.Left))
    return bad


def check_labels(w, r, moment):
    bad = label_overlaps(w)
    r.check(u"{0}: no label overlaps its field".format(moment), not bad, bad)


def snap(window, folder, name):
    """The window as a PNG; DrawToBitmap needs no screen."""
    D = window.D
    form = window.form
    bmp = D.Bitmap(form.Width, form.Height)
    try:
        form.DrawToBitmap(bmp, D.Rectangle(0, 0, form.Width, form.Height))
        bmp.Save(os.path.join(folder, name + ".png"))
    finally:
        bmp.Dispose()


class Script(object):
    """Steps on the window thread, one per timer tick; a step that returns
    False is asked again. Ends by closing the window."""

    def __init__(self, window, steps, report, limit=120.0):
        self.window = window
        self.steps = list(steps)
        self.report = report
        self.deadline = time.time() + limit
        self.current = None
        self.ticks = 0
        self.guard = ScreenGuard(window, report)
        self.guard.check(u"when shown")
        F = window.F
        self.timer = F.Timer()
        self.timer.Interval = 100
        self.timer.Tick += self.tick
        self.timer.Start()

    def tick(self, sender, args):
        try:
            self.ticks += 1
            if not self.guard.check(u"tick {0}, after step {1}".format(self.ticks, self.current)):
                self.finish()
                return
            if time.time() > self.deadline:
                self.report.check("window script in time", False, self.current)
                self.finish()
                return
            if not self.steps:
                self.finish()
                return
            fn = self.steps[0]
            self.current = fn.__name__
            trap = focus_trap.current()
            if trap is not None:
                trap.moment = u"step " + self.current
            if fn() is not False:
                self.steps.pop(0)
        except Exception:
            self.report.check("step " + str(self.current), False, traceback.format_exc())
            self.finish()

    def finish(self):
        self.timer.Stop()
        self.guard.check(u"at the end, step {0}".format(self.current))
        self.guard.done()
        self.steps = []
        self.window.form.Close()


def solved_disp(mw, solution):
    """Displacements of the solved block by place, so a stand-in result belongs
    to the open solution. Script thread."""
    out = {}
    for n in mw.all_nodes():
        p = mw.node(n)
        out[(round(p.x, 7), round(p.y, 7), round(p.z, 7))] = (
            solution.node_value("displx", n), solution.node_value("disply", n),
            solution.node_value("displz", n))
    return out


def run(mw, solution, report, png, model_folder, plan_mesh, selection, size=(1180, 780),
        job_polls=3):
    """One session of the window on a solved block."""
    box = {}
    mw2 = SelectingMw(mw, selection)
    real_start = fb_aster.start
    disp = solved_disp(mw, solution)

    def like_solution(p, rank):
        return disp[(round(p[0], 7), round(p[1], 7), round(p[2], 7))]

    def fake_start(man, folder, plan, mesh, exe, scratch=None):
        box["started"] = (man["run_id"], folder, exe)
        shift = None if box.get("wrong_loads") else like_solution
        job = sup.FakeJob(sup.make_result(plan, mesh, shift=shift), polls=job_polls)
        box["job"] = job
        return job

    def ready(window):
        steps = session_steps(window, box, mw2, solution, report, png)
        box["script"] = Script(window, steps, report)

    fb_aster.start = fake_start
    try:
        fb_gui.run_window(mw2, solution, quiet_options(size=size, on_ready=ready))
    finally:
        fb_aster.start = real_start
    return box


def real_run(mw, solution, report, png, selection, expect, solved=False):
    """The whole chain: real manifest, fingerprint and Code-Aster, statics as the
    reference, two cuts. expect: {x of a cut: ((Fx, Fy, Fz), (Mx, My, Mz))} about
    the neutral point, in N and N.m. solved: the model holds results the bridge
    wrote back, so arrows must go in."""
    r = report
    mw2 = SelectingMw(mw, selection)
    box = {}

    def steps(w):
        def wait_result():
            if w.phase is not None or not (w.model.cuts or w.status_error):
                return False
            r.check("follow-up run without an error", not w.status_error, w.status)
            r.check("run found by fingerprint", w.chosen_run() is not None, w.run_label.Text)
            box["seconds"] = w.model.result["seconds"] if w.model.result else None

        def compare():
            if not w.model.cuts:
                return
            r.check("in equilibrium", w.model.equilibrium()[0] == "ok", w.banner_text.Text)
            known = not any(c == "solution_unknown" for _, c, _ in w.model.warnings)
            if hasattr(fb_aster, "check_solution"):
                r.check("run checked against the open solution", known == solved,
                        w.warning_box.Text)
            r.check("two cuts", len(w.model.cuts) == 2)
            w.radio_global.Checked = True
            for cut in w.model.cuts:
                x = cut["geo"]["centroid"][0]
                key = min(expect, key=lambda k: abs(k - x))
                f, m = expect[key]
                values = w.model.components(cut)
                for i in range(3):
                    r.close("cut x={0} F{1}".format(key, i), values[i], f[i], 1e-8)
                    r.close("cut x={0} M{1}".format(key, i), values[3 + i], m[i], 1e-8)
            cut = w.model.cuts[0]
            base = w.model.components(cut)[4]
            shown = w.model.point_shown(cut)
            w.model.set_point_shown((shown[0], shown[1] + 10.0, shown[2]), cut)
            w.model.set_point_shown((shown[0], shown[1], shown[2] + 10.0), cut)
            r.check("negative control: a wrong point is seen",
                    abs(w.model.components(cut)[4] - base) > 0.5,
                    w.model.components(cut)[4] - base)
            w.model.set_neutral(cut)
            w.radio_section.Checked = True
            big = max(w.model.cuts, key=lambda c: c["geo"]["centroid"][0])
            r.close("N is tension at the far cut", w.model.components(big)[0],
                    expect[max(expect)][0][0], 1e-8)
            snap(w, png, "real_en")
            w.lang = "nl"
            w.render()
            snap(w, png, "real_nl")
            size = w.form.ClientSize
            w.form.ClientSize = w.D.Size(w.px(960), w.px(660))
            w._layout()
            snap(w, png, "real_nl_small")
            w.form.ClientSize = size
            w._layout()
            w.lang = "en"
            w.render()

        def arrows_without_solution():
            w.on_arrows()

        def arrows_refused():
            if w.asks:
                return False
            box["arrow_text"] = w.arrow_text
            if not solved:
                r.check("no solution in a model that was not solved",
                        u"No solution" in w.arrow_text, w.arrow_text)
                return
            r.check("arrows on a solution of the bridge",
                    u"legend in Mecway is right" in w.arrow_text, w.arrow_text)
            nid = sorted(w.own["externalforcex"])[0]
            r.close("value in that solution", solution.node_value("externalforcex", nid),
                    w.own["externalforcex"][nid], 1e-9)

        def stop_real():
            w.on_compute()
            box["t"] = time.time()

        def stop_real_running():
            if w.phase != "run":
                return False
            if time.time() - box["t"] < 1.0:
                return False
            job = w.job
            w.on_stop()
            r.check("stopped", w.phase is None)
            box["job"] = job

        def stop_real_done():
            if not os.path.exists(box["job"].work):
                r.check("own folder gone after Stop", True)
                return
            if time.time() - box["t"] > 40:
                r.check("own folder gone after Stop", False, box["job"].work)
                return
            return False
        return [wait_result, compare, arrows_without_solution, arrows_refused, stop_real,
                stop_real_running, stop_real_done]

    def ready(window):
        box["script"] = Script(window, steps(window), report, limit=240.0)

    fb_gui.run_window(mw2, solution, quiet_options(on_ready=ready))
    return box


def phase4(mw, solution, report, png):
    """The window with shell, beam, truss and mixed cuts made by hand (the core
    of phase 4 may not be there yet): table, axes texts, sign and drawing, in
    both languages and two sizes. Nothing is computed: the models go in as a
    finished computation would put them."""
    r = report
    cases = [("strip", sup.shell_case(warnings=["drilling", "node_contact"])),
             ("strips", sup.shell_case(across=2)),
             ("beam", sup.beam_case()),
             ("beam_general", sup.beam_case(section={"cara": ["A"], "vale": [2e-4]})),
             ("truss", sup.beam_case(model_name="BARRE")),
             ("mixed", sup.mixed_case())]

    def steps(w):
        out = []

        def first():
            if w.phase is not None:
                return False
            r.check("mode choice usable, elements first",
                    w.mode_combo.Enabled and w.mode_combo.SelectedIndex == 0 and
                    not w.side_button.Enabled)
        out.append(first)
        for name, model in cases:
            def show(name=name, model=model):
                w._install(model)
                heads = [w.table.Columns[i].Text for i in range(w.table.Columns.Count)]
                r.check(name + ": columns", len(heads) == 8 + int(model.axes_column()), heads)
                r.check(name + ": radio names the axes",
                        w.radio_section.Text == model.radio_text(), w.radio_section.Text)
                r.check(name + ": note shown", w.axes_note.Text == model.axes_note())
                r.check(name + ": sign shown", w.sign_label.Text == model.sign_text())
                note = w.axes_note
                r.check(name + ": note not cut off", note.Bottom <= w.table.Top,
                        (note.Bottom, w.table.Top))
                sign = w.sign_label
                r.check(name + ": sign above the warnings", sign.Bottom <= w.warning_box.Top,
                        (sign.Bottom, w.warning_box.Top))
                right = max(c.Right for c in (w.radio_section, w.radio_global))
                r.check(name + ": radios inside the left side", right <= w.left.ClientSize.Width,
                        (right, w.left.ClientSize.Width))
                snap(w, png, "p4_" + name + "_en")
                img = fb_gui.draw_cut(w.view, w.map, w.picture.ClientSize.Width,
                                      w.picture.ClientSize.Height)
                img.Save(os.path.join(png, "p4_" + name + "_drawing.png"))
                img.Dispose()
            out.append(show)

        def second_cut():
            w.table.Items[1].Selected = True
            r.check("note follows the cut", u"Cut 2" in w.axes_note.Text, w.axes_note.Text)
            w.table.Items[0].Selected = True

        def dutch_small():
            w._install(cases[0][1])
            w.lang = "nl"
            w.render()
            w.form.ClientSize = w.D.Size(w.px(960), w.px(660))
            w._layout()
            r.check("Dutch note", u"Snede 1" in w.axes_note.Text, w.axes_note.Text)
            right = max(c.Right for c in (w.radio_section, w.radio_global))
            r.check("small: radios inside", right <= w.left.ClientSize.Width,
                    (right, w.left.ClientSize.Width))
            r.check("small: sign above the warnings",
                    w.sign_label.Bottom <= w.warning_box.Top)
            check_labels(w, r, "phase 4, smallest size, Dutch")
            snap(w, png, "p4_strip_nl_small")
            w._install(cases[-1][1])
            right = max(c.Right for c in (w.radio_section, w.radio_global))
            r.check("small, mixed: radios inside", right <= w.left.ClientSize.Width,
                    (right, w.left.ClientSize.Width))
            r.check("small, mixed: sign above the warnings",
                    w.sign_label.Bottom <= w.warning_box.Top)
            r.check("small: selection text inside the bar",
                    w.selection_label.Right <= w.selection_label.Parent.ClientSize.Width,
                    (w.selection_label.Right, w.selection_label.Parent.ClientSize.Width))
            snap(w, png, "p4_mixed_nl_small")

        def global_axes():
            w.radio_global.Checked = True
            r.check("global: Fx in the table", w.table.Columns[2].Text.startswith(u"Fx"),
                    w.table.Columns[2].Text)
            snap(w, png, "p4_mixed_nl_global")
            w.radio_section.Checked = True
        out += [second_cut, dutch_small, global_axes]
        return out

    def ready(window):
        Script(window, steps(window), r)

    fb_gui.run_window(mw, solution, quiet_options(on_ready=ready))


def entry_point(mw, solution, report, png, selection, path):
    """Scripts/MecwayFreebody.py itself: one start with the window quiet, and a
    second start while it is open. The forward step would take the focus, so a
    stand-in records it."""
    r = report
    real_run_window = fb_gui.run_window
    real_activate = fb_gui.activate_existing
    box = {}

    def second_start(window):
        guard = ScreenGuard(window, r)
        guard.check(u"first start shown")
        try:
            execfile(path, {"mw": quiet_mw, "solution": solution, "__name__": "second"})
            r.check("second start brings the window forward", box.get("forward"))
        except Exception:
            r.check("second start", False, traceback.format_exc())
        guard.check(u"after the second start")
        guard.done()
        window.form.Close()

    def quiet(mw_, solution_):
        box["started"] = True
        r.check("solution reaches the window", solution_ is solution)
        real_run_window(mw_, solution_, quiet_options(on_ready=second_start))

    def forward():
        box["forward"] = True
        return True
    quiet_mw = MessageMw(mw)
    fb_gui.run_window = quiet
    fb_gui.activate_existing = forward
    try:
        execfile(path, {"mw": quiet_mw, "solution": solution, "__name__": "first"})
    finally:
        fb_gui.run_window = real_run_window
        fb_gui.activate_existing = real_activate
    r.check("entry point opened the window", box.get("started"))
    r.check("no message of Mecway", not quiet_mw.messages, quiet_mw.messages[:2])
    token = fb_gui.claim_instance()
    r.check("instance free again after closing", token not in (None, True), token)
    fb_gui.release_instance(token)


def reopened(mw, solution, report, png, selection, model):
    """A model that is opened again while the panel is open, as the bridge does
    when it loads results. Mecway closes the window then (measured: with reason
    UserClosing, also in a hidden run). It must end cleanly and let go of a job."""
    r = report
    mw2 = SelectingMw(mw, selection)
    box = {}
    real_start = fb_aster.start

    def stand_in(man, folder, plan, mesh, exe, scratch=None):
        return sup.FakeJob(None, polls=100000)

    def steps(w):
        def running():
            if w.phase != "run":
                return False
            box["job"] = w.job
            w.caller.post(lambda: mw.open(model, "m"))

        def wait_for_close():
            return False
        return [running, wait_for_close]

    def ready(window):
        box["window"] = window
        box["script"] = Script(window, steps(window), report, limit=60.0)

    fb_aster.start = stand_in
    try:
        fb_gui.run_window(mw2, solution, quiet_options(on_ready=ready))
    finally:
        fb_aster.start = real_start
    r.check("run_window came back", True)
    box["script"].guard.done()          # Mecway closed it: no finish of the script
    r.check("Mecway closed the window", box["window"].close_reason is not None)
    r.check("the job was stopped", box["job"].stopped)
    box["reason"] = box["window"].close_reason
    return box


def node_cut(mw, solution, report, png, nodes):
    """A cut by nodes on a plane in the real window, on the solved block: the
    full section at x = 0.08 at both sides (a stop after Other side leaves the
    old table grey), then the upper half, a partial section, arrows on its
    nodes, a grey table after another selection or mode, and refusals. The
    run is stood in for by test_gui_support.start_hook, with the prepare hook
    and the real link_nodes and judge_rest. nodes: {"full", "top", "bent"} node ids."""
    r = report
    mw2 = SelectingMw(mw, [], nodes["full"])
    box = {}
    real_start = fb_aster.start
    disp = solved_disp(mw, solution)

    def like_solution(p, rank):
        return disp[(round(p[0], 7), round(p[1], 7), round(p[2], 7))]

    def steps(w):
        def idle():
            if w.phase is not None:
                return False
            r.check("no element selection: nothing computed", not w.model.cuts)
            r.check("mode choice usable, elements first",
                    w.mode_combo.Enabled and w.mode_combo.SelectedIndex == 0)
            r.check("other side off for elements", not w.side_button.Enabled)
            w.mode_combo.SelectedIndex = 1
            r.check("mode nodes", w.cut_mode == "nodes" and w.side_button.Enabled)
            r.check("selection line counts nodes",
                    w.selection_label.Text == u"{0} nodes selected  ·  side +".format(
                        len(nodes["full"])), w.selection_label.Text)
            r.check("mode stored", fb_gui.settings().get("cut_mode") == "nodes")
            w.on_compute()

        def full_done():
            if w.phase is not None:
                return False
            model = w.model
            r.check("full: computed", bool(model.cuts) and not w.status_error, w.status)
            if not model.cuts:
                return
            cut = model.nodecut
            r.check("full: a node cut, not partial", cut is not None and not cut["partial"])
            r.check("full: filtered through the hook",
                    box.get("prepare") is not None and box["job"].prepared == 1 and
                    "nodecut" in model.result and
                    len(model.result["nodes"]) == len(cut["keep"]))
            r.check("full: row names the side", w.table.Items[0].Text == u"1  ·  side +",
                    w.table.Items[0].Text)
            r.check("full: sign says opposite", u"exactly opposite" in w.sign_label.Text,
                    w.sign_label.Text)
            r.check("full: equilibrium shown", model.equilibrium()[0] == "ok",
                    w.banner_text.Text)
            r.check("full: plane in the drawing", (w.view or {}).get("plane") is not None)
            model.axes = "global"
            box["plus"] = list(model.components(model.cuts[0]))
            model.axes = "section"
            snap(w, png, "nodes_full_en")
            img = fb_gui.draw_cut(w.view, w.map, w.picture.ClientSize.Width,
                                  w.picture.ClientSize.Height)
            img.Save(os.path.join(png, "nodes_full_drawing.png"))
            img.Dispose()
            # the user's case: one resultant of a full node section; the first
            # write in this solution, so it keeps the true values
            r.check("no earlier arrows in this window", not w.own.get("sizes"), w.own)
            w.arrow_combo.SelectedIndex = 1
            w.on_arrows()

        def full_resultant_done():
            if w.asks:
                return False
            model = w.model
            text = w.arrow_text
            r.check("resultant: written", u"stands on node" in text, text)
            moment = w.own.get("reactionmomx") or {}
            written = set(w.own.get("externalforcex") or {})
            r.check("resultant: one node for force and moment",
                    len(written) == 1 and set(moment) == written, (sorted(written), sorted(moment)))
            if len(written) != 1:
                return
            nid = list(written)[0]
            box["resultant_node"] = nid
            p = model.mesh["nodes"][nid]
            r.check("resultant: on the centre node of the section",
                    abs(p[1]) < 1e-9 and abs(p[2]) < 1e-9, p)
            r.check("resultant: the text says the node is inside the solid",
                    u"Cut 1: node {0} lies inside the solid".format(nid) in text, text)
            s = model.sum6(model.cuts[0])
            fields = fb_mecway.FIELDS_FORCE + fb_mecway.FIELDS_MOMENT
            for k, field in enumerate(fields):
                value = solution.node_value(field, nid)
                r.close(u"resultant: {0} in Mecway is what the panel wrote".format(field),
                        value, w.own[field][nid], 1e-9)
                # the first write in this solution keeps the true values
                r.close(u"resultant: {0} is the sum of the cut".format(field), value, s[k], 1e-6)
            others = [n for n in nodes["full"] if n != nid and
                      any(solution.node_value(f, n) is not None for f in fields)]
            r.check("resultant: no value on another cut node", not others, others[:5])
            w.lang = "nl"
            w.render()
            r.check("resultant: Dutch text says inside",
                    u"ligt binnen in het volume" in w.arrow_text, w.arrow_text)
            w.lang = "en"
            w.render()
            snap(w, png, "nodes_full_resultant_en")
            w.arrow_combo.SelectedIndex = 0
            w.on_arrows()

        def full_per_node_done():
            if w.asks:
                return False
            nid = box.get("resultant_node")
            r.check("per node after the resultant: the old moment is removed",
                    u"reaction moment is zero here: the earlier arrows of this panel are "
                    u"removed" in w.arrow_text, w.arrow_text)
            r.check("per node after the resultant: no moment left in Mecway",
                    nid is not None and all(solution.node_value(f, nid) is None
                                            for f in fb_mecway.FIELDS_MOMENT + ("reactionmommag",)))
            r.check("per node: force on every cut node",
                    set(w.own.get("externalforcex") or {}) == set(w.model.nodecut["keep"]))
            w.on_side()
            w.on_stop()
            r.check("other side stopped: the table of side + is grey", w.outdated and
                    u"side −" in w.selection_label.Text, w.selection_label.Text)
            w.on_compute()

        def other_done():
            if w.phase is not None:
                return False
            model = w.model
            r.check("other side: computed", bool(model.cuts) and not w.status_error, w.status)
            if not model.cuts:
                return
            r.check("other side: row", w.table.Items[0].Text == u"1  ·  side −",
                    w.table.Items[0].Text)
            r.check("other side: line", u"side −" in w.selection_label.Text,
                    w.selection_label.Text)
            model.axes = "global"
            minus = model.components(model.cuts[0])
            model.axes = "section"
            for k in range(6):
                r.close("other side opposite {0}".format(k), minus[k], -box["plus"][k], 1e-9)
            r.check("other side: normal toward the viewer", w.view["plane"]["toward"])
            r.check("other side: not grey", not w.outdated)
            snap(w, png, "nodes_other_en")
            mw2.picked = list(nodes["top"])
            w.on_side()

        def partial_done():
            if w.phase is not None:
                return False
            model = w.model
            r.check("partial: computed", bool(model.cuts) and not w.status_error, w.status)
            if not model.cuts:
                return
            r.check("partial: through the hook", box.get("prepare") is not None and
                    box["job"].prepared == 1)
            r.check("partial: on_cut judged after the filter",
                    model.result["on_cut"][model.rank].get("valid") is not False)
            r.check("partial: banner", w.banner_title.Text == fb_gui.tx("eq_partial", "en"),
                    w.banner_title.Text)
            r.check("partial: rule 7 in the banner", u"close no body" in w.banner_text.Text and
                    u"edge nodes" in w.banner_text.Text, w.banner_text.Text)
            r.check("partial: warning", u"Partial section" in w.warning_box.Text,
                    w.warning_box.Text)
            r.check("partial: not grey", not w.outdated)
            r.check("partial: drawing says so",
                    u"partial section" in w.view["plane"]["text"], w.view["plane"]["text"])
            snap(w, png, "nodes_partial_en")
            w.lang = "nl"
            w.render()
            r.check("Dutch: mode kept", w.mode_combo.SelectedIndex == 1 and
                    w.side_button.Text == u"Andere kant")
            r.check("Dutch: banner", w.banner_title.Text.startswith(u"Deeldoorsnede"),
                    w.banner_title.Text)
            r.check("Dutch: row", w.table.Items[0].Text == u"1  ·  kant +", w.table.Items[0].Text)
            size = w.form.ClientSize
            w.form.ClientSize = w.D.Size(w.px(960), w.px(660))
            w._layout()
            r.check("small: selection text inside the bar",
                    w.selection_label.Right <= w.selection_label.Parent.ClientSize.Width)
            r.check("small: side button left of the selection text",
                    w.side_button.Right <= w.selection_label.Left)
            check_labels(w, r, "node cut, smallest size, Dutch")
            snap(w, png, "nodes_partial_nl_small")
            w.form.ClientSize = size
            w.lang = "en"
            w.render()
            w.arrow_combo.SelectedIndex = 0
            w.on_arrows()

        def arrows_done():
            if w.asks:
                return False
            r.check("arrows written", u"external force" in w.arrow_text, w.arrow_text)
            keep = set(w.model.nodecut["keep"])
            written = set(w.own.get("externalforcex") or {})
            r.check("arrows on the nodes of the cut only", written and written <= keep,
                    sorted(written - keep)[:5])
            off = [n for n in nodes["full"] if n not in keep]
            r.check("no arrow on the lower half",
                    off and all(solution.node_value("externalforcex", n) is None for n in off))
            mw2.picked = list(nodes["full"])
            w._ask_selection()

        def grey_after_other_nodes():
            box["poll"] = box.get("poll", 0) + 1
            if not w.outdated and box["poll"] < 30:
                w._ask_selection()
                return False
            r.check("other nodes: table grey", w.outdated and w.outdated_label.Visible)
            mw2.picked = list(nodes["top"])
            w._ask_selection()

        def back_again():
            box["back"] = box.get("back", 0) + 1
            if w.outdated and box["back"] < 30:
                w._ask_selection()
                return False
            r.check("same nodes: table back", not w.outdated)
            w.mode_combo.SelectedIndex = 0
            r.check("elements mode: table of nodes grey", w.outdated)
            r.check("elements mode: other side off", not w.side_button.Enabled)
            w.mode_combo.SelectedIndex = 1
            r.check("nodes mode again: not grey", not w.outdated)
            mw2.picked = list(nodes["bent"])
            w.on_compute()

        def bent_done():
            if w.phase is not None:
                return False
            r.check("not planar: refused in words",
                    w.status_error and u"do not lie in one plane" in w.status, w.status)
            r.check("not planar: old table grey", w.outdated)
            mw2.picked = []
            w.on_compute()

        def empty_done():
            if w.phase is not None:
                return False
            r.check("no nodes: asks for nodes",
                    u"Select the nodes of a planar section" in w.status, w.status)
            snap(w, png, "nodes_refused_en")
        return [idle, full_done, full_resultant_done, full_per_node_done, other_done,
                partial_done, arrows_done,
                grey_after_other_nodes, back_again, bent_done, empty_done]

    def ready(window):
        box["script"] = Script(window, steps(window), r, limit=150.0)

    fb_aster.start = sup.start_hook(box, like_solution, polls=2)
    try:
        fb_gui.run_window(mw2, solution, quiet_options(on_ready=ready))
    finally:
        fb_aster.start = real_start
    return box


class _Navigating(object):
    """What the browser element hands to Navigating: the address and Cancel."""

    def __init__(self, url):
        import System
        self.Url = System.Uri(url)
        self.Cancel = False


def _notice(lang):
    import fb_docs
    return fb_docs.TRADEMARK_NOTICE[0 if lang == "nl" else 1]


def docs_tab(mw, solution, report, png):
    """The tab Documentation in the real window: it opens, shows a document,
    follows links and the language, and the panel tab keeps the layout it had.
    The viewer is the text box: the browser element made the test window the
    foreground window (measured), so tests never create it. Links go through the
    handler of Navigating with the addresses the browser element gives (about:,
    about:blank#); a web address goes to a stand-in, never to a browser."""
    r = report
    opened = []
    box = {}

    def steps(w):
        D = w.D

        def layout():
            out = {}
            for name in ("body", "left", "right", "banner", "table", "sign_label",
                         "warning_box", "arrow_label", "picture", "point_hint", "node_button",
                         "selection_label", "run_combo", "status_label"):
                c = getattr(w, name)
                out[name] = (c.Left, c.Top, c.Width, c.Height)
            out["columns"] = tuple(w.table.Columns[i].Width for i in range(w.table.Columns.Count))
            return out

        def shown(text):
            return w.doc_view is not None and text in w.doc_view.Text

        def idle():
            if w.phase is not None:
                return False
            nc = w.form.Size - w.form.ClientSize
            r.check("docs: body at the default size as without tabs",
                    (w.body.Width, w.body.Height) == (w.px(1180), w.px(780) - w.chrome_h),
                    (w.body.Size, w.px(1180), w.px(780) - w.chrome_h))
            r.check("docs: two tabs, the panel first", w.tabs.TabCount == 2 and
                    w.tabs.SelectedIndex == 0 and w.tab == "panel" and
                    w.tabs.TabPages[0].Text == u"Forces on the cut" and
                    w.tabs.TabPages[1].Text == u"Documentation",
                    [w.tabs.TabPages[i].Text for i in range(w.tabs.TabCount)])
            r.check("docs: page built only when opened", w.doc_view is None)
            w.form.Size = w.form.MinimumSize
            box["nc"] = (nc.Width, nc.Height)

        def smallest():
            ncw, nch = box["nc"]
            want = (w.px(960) - ncw, w.px(660) - nch - w.chrome_h)
            r.check("docs: body at the smallest window as without tabs",
                    (w.body.Width, w.body.Height) == want, (w.body.Size, want))
            box["before"] = layout()
            snap(w, png, "docs_panel_before")
            r.check("docs: no focus before the tab opens", not w.form.ContainsFocus)
            w.show_tab("docs")

        def guide():
            r.check("docs: tab open on the guide", w.tab == "docs" and
                    w.doc_list.Items.Count == 2 and w.doc_list.SelectedIndex == 0 and
                    w.doc_rel == u"en/MecwayFreebody.md" and shown(u"What it does"),
                    (w.tab, w.doc_rel))
            r.check("docs: no browser element in a test", w.doc_browser is None)
            r.check("docs: text without tags", u"<td>" not in w.doc_view.Text and
                    u"**" not in w.doc_view.Text)
            r.check("docs: trademark notice", w.doc_notice.Text == _notice("en"))
            r.check("docs: an anchor stays in the document",
                    w.doc_link(u"about:blank#limits") and w.doc_rel == u"en/MecwayFreebody.md")
            snap(w, png, "docs_guide_en")
            w.doc_list.SelectedIndex = 1
            r.check("docs: README from the list", w.doc_rel == u"../README.md" and
                    shown(u"Installation"), w.doc_rel)

        def links():
            for url, rel in ((u"about:docs/design/contract.md", u"design/contract.md"),
                             # from design/contract.md, as that one is open now
                             (u"about:../en/MecwayFreebody.md#limits", u"en/MecwayFreebody.md")):
                args = _Navigating(url)
                w._on_doc_navigating(None, args)
                r.check(u"docs: {0} opens in the tab".format(url),
                        args.Cancel and w.doc_rel == rel, (args.Cancel, w.doc_rel))
            r.check("docs: the guide by a link is selected in the list",
                    w.doc_list.SelectedIndex == 0)          # the guide is in the list
            w._show_doc(u"design/contract.md")
            r.check("docs: outside the list nothing selected", w.doc_list.SelectedIndex == -1)
            args = _Navigating(u"about:../../README.md")
            w._on_doc_navigating(None, args)
            r.check("docs: back to the README, selected", args.Cancel and
                    w.doc_rel == u"../README.md" and w.doc_list.SelectedIndex == 1, w.doc_rel)
            args = _Navigating(u"https://mecway.com/")
            w._on_doc_navigating(None, args)
            r.check("docs: web address to the stand-in, not loaded here",
                    args.Cancel and opened == [u"https://mecway.com/"], opened)
            args = _Navigating(u"about:LICENSE")
            w._on_doc_navigating(None, args)
            r.check("docs: a link that does not open says so",
                    args.Cancel and u"does not open here" in w.status and
                    w.doc_rel == u"../README.md", w.status)
            args = _Navigating(u"about:blank")
            w._on_doc_navigating(None, args)
            r.check("docs: the page itself loads", not args.Cancel)
            args = _Navigating(u"https://mecway.com/")
            w._on_doc_new_window(None, args)
            r.check("docs: no new window", args.Cancel)
            w.doc_list.SelectedIndex = 0
            w.lang = "nl"
            w.render()

        def dutch():
            r.check("docs: Dutch keeps the tab and the document",
                    w.tab == "docs" and w.tabs.SelectedIndex == 1 and
                    w.doc_rel == u"MecwayFreebody.md" and w.doc_list.SelectedIndex == 0 and
                    shown(u"Wat het doet"), (w.tab, w.doc_rel))
            r.check("docs: Dutch tab titles",
                    [w.tabs.TabPages[i].Text for i in range(2)] ==
                    [u"Krachten op de snede", u"Documentatie"],
                    [w.tabs.TabPages[i].Text for i in range(2)])
            r.check("docs: Dutch list", w.doc_list.Items[0] == u"Handleiding")
            r.check("docs: Dutch notice", w.doc_notice.Text == _notice("nl"))
            snap(w, png, "docs_guide_nl")
            w._show_doc(u"nothing_here.md")
            r.check("docs: a missing document says so", shown(u"Document niet gevonden"),
                    w.doc_view.Text[:200])
            w.lang = "en"
            w.render()
            r.check("docs: missing document kept over a render", w.doc_rel == u"nothing_here.md"
                    and shown(u"Document not found") and w.doc_list.SelectedIndex == -1)
            w.doc_list.SelectedIndex = 0
            # bigger while the documentation is open: the panel fits when shown again
            w.form.ClientSize = D.Size(w.px(1300), w.px(900))

        def back():
            r.check("docs: no focus on the documentation tab", not w.form.ContainsFocus)
            w.show_tab("panel")

        def panel_again():
            r.check("docs: back to the panel", w.tab == "panel" and w.tabs.SelectedIndex == 0)
            dw, dh = w.tab_border
            want = (w.form.ClientSize.Width - dw, w.form.ClientSize.Height - w.chrome_h - dh)
            # show_tab builds anew; a click on the tab (the user's way) is not
            # made here: that would focus the window
            r.check("docs: panel fits a size set on the other tab",
                    (w.body.Width, w.body.Height) == want and
                    w.right.Right == w.body.ClientSize.Width, (w.body.Size, want))
            w.form.Size = w.form.MinimumSize

        def same_layout():
            after = layout()
            diff = [k for k in after if after[k] != box["before"][k]]
            r.check("docs: panel keeps its layout", not diff,
                    [(k, box["before"][k], after[k]) for k in diff])
            r.check("docs: selection text inside the bar",
                    w.selection_label.Right <= w.selection_label.Parent.ClientSize.Width and
                    w.run_combo.Right <= w.run_combo.Parent.ClientSize.Width,
                    (w.selection_label.Right, w.selection_label.Parent.ClientSize.Width))
            snap(w, png, "docs_panel_after")
            r.check("docs: no web address opened by itself", opened == [u"https://mecway.com/"])
        return [idle, smallest, guide, links, dutch, back, panel_again, same_layout]

    def ready(window):
        box["script"] = Script(window, steps(window), r, limit=120.0)

    options = quiet_options(open_web=opened.append, doc_browser=False, on_ready=ready)
    fb_gui.run_window(mw, solution, options)
    return box


def all_controls(control):
    out = []
    for child in control.Controls:
        out.append(child)
        out.extend(all_controls(child))
    return out


def session_steps(w, box, mw2, solution, report, png):
    r = report

    def wait_auto_result():
        if w.phase is not None or not w.model.cuts:
            return False
        r.check("start with a selection computes", box.get("started") is not None)
        r.check("two cuts in the table", w.table.Items.Count == 2, w.table.Items.Count)
        r.check("banner green", w.model.equilibrium()[0] == "ok")
        r.check("run shown", u"20261107" in w.run_label.Text, w.run_label.Text)

    def first_image():
        check_labels(w, r, "default size, English")
        snap(w, png, "large_en")
        w.form.ClientSize = w.D.Size(w.px(960), w.px(660))

    def small_image():
        w._layout()
        check_labels(w, r, "smallest size, English")
        w.lang = "nl"
        w.render()
        check_labels(w, r, "smallest size, Dutch")
        w.lang = "en"
        w.render()
        snap(w, png, "small_en")
        w.form.ClientSize = w.D.Size(1500, 1000)

    def very_large_image():
        w._layout()
        snap(w, png, "xlarge_en")
        w.form.ClientSize = w.D.Size(1180, 780)

    def switch_axes():
        w.radio_global.Checked = True
        r.check("axes switch: table in Fx", w.table.Columns[2].Text.startswith(u"Fx"),
                w.table.Columns[2].Text)
        w.radio_section.Checked = True
        r.check("axes switch back", w.table.Columns[2].Text.startswith(u"N "))
        w.unit_combo.SelectedIndex = 1
        r.check("unit", u"kN" in w.table.Columns[2].Text)
        w.unit_combo.SelectedIndex = 0

    def type_point():
        before = w.table.Items[0].SubItems[7].Text
        t0 = time.time()
        w.point_boxes[1].Text = u"3,5"
        r.check("typed comma point", abs(w.model.cut()["point"][1][1] - 0.0035) < 1e-12)
        r.check("instant", time.time() - t0 < 1.0)
        r.check("table follows", w.table.Items[0].SubItems[7].Text != before)
        w.point_boxes[1].Text = u"x"
        r.check("bad number says so", w.status_error)
        w.point_boxes[1].Text = u"3,5"

    def drag_point():
        px, py = fb_gui.to_pixel(w.map, w.view["point"][0], w.view["point"][1])
        w.on_mouse_down(px + 3, py)
        r.check("grabbed", w.drag)
        w._drag_to(px + 20, py - 30)
        w.on_mouse_up(px + 20, py - 30)
        r.check("released", not w.drag)
        shown = w.model.point_shown()
        r.check("point moved", abs(shown[1] - 3.5) > 0.01, shown)
        r.check("fields follow", w.point_boxes[1].Text != u"3,5", w.point_boxes[1].Text)
        snap(w, png, "dragged_en")

    def presets():
        w.on_neutral()
        r.check("neutral", w.model.cut()["point"] == fb_gui.NEUTRAL_POINT)
        w.node_box.Text = u"99999"
        w.on_node()
        r.check("unknown node refused", w.status_error, w.status)
        nid = w.model.cut()["group"]["nodes"][0]
        w.node_box.Text = u"{0}".format(nid)
        w.on_node()
        r.check("typed node", w.model.cut()["node"] == nid)
        w.node_box.Text = u""
        w.on_neutral()

    def node_nearest():
        w.on_node()         # empty box, nothing selected: nearest cut node
        box["asked"] = True

    def node_nearest_done():
        if w.asks:
            return False
        r.check("nearest cut node", w.model.cut()["node"] is not None)
        w.on_neutral()

    def choose_cut():
        w.table.Items[1].Selected = True
        r.check("cut list selects", w.model.index == 1, w.model.index)
        w.table.Items[0].Selected = True

    def step_choice():
        n = w.step_combo.Items.Count
        r.check("steps listed", n == 2, n)
        r.check("last step first", w.step_combo.SelectedIndex == n - 1)
        before = w.table.Items[0].SubItems[2].Text
        w.step_combo.SelectedIndex = 0
        r.check("step changes the table", w.table.Items[0].SubItems[2].Text != before)
        w.step_combo.SelectedIndex = n - 1

    def copying():
        text = w.table_text()
        dec = fb_gui.separators("en")[0]
        r.check("decimal sign of Windows", dec in text, text[:200])
        path = os.path.join(png, "table.csv")
        w.save_csv(path)
        with open(path, "rb") as f:
            data = f.read()
        r.check("CSV has a BOM", data[:3] == b"\xef\xbb\xbf" or data[:1] == u"﻿",
                repr(data[:4]))
        r.check("CSV has the list separator", fb_gui.separators("en")[1].encode("ascii") in data)
        os.remove(path)
        # Never the user's clipboard: the panel's own hook is replaced
        copied = []
        w._clip_text = copied.append
        w._clip_image = copied.append
        w.on_copy()
        r.check("table copied", len(copied) == 1 and u"	" in copied[0], w.status)
        w.on_copy_image()
        r.check("drawing copied", len(copied) == 2, w.status)

    def arrows_force():
        w.arrow_combo.SelectedIndex = 0
        w.on_arrows()

    def arrows_force_done():
        if w.asks:
            return False
        r.check("arrows written", u"external force" in w.arrow_text, w.arrow_text)
        r.check("first write: the legend is right", u"legend in Mecway is right" in w.arrow_text,
                w.arrow_text)
        w.lang = "nl"
        w.render()
        r.check("first write in Dutch: the legend is right",
                u"legenda in Mecway klopt" in w.arrow_text, w.arrow_text)
        w.lang = "en"
        w.render()
        r.check("window kept the values", "externalforcex" in w.own)
        nid = sorted(w.own["externalforcex"])[0]
        value = solution.node_value("externalforcex", nid)
        r.check("value in the real solution", value is not None and
                abs(value - w.own["externalforcex"][nid]) < 1e-12, value)
        w.arrow_combo.SelectedIndex = 1
        w.model.set_point_shown((0.0, 0.3, 0.4))
        w.on_arrows()

    def arrows_result_done():
        if w.asks:
            return False
        r.check("resultant names its node", u"stands on node" in w.arrow_text, w.arrow_text)
        r.check("second write keeps the length", u"keep the length of the first" in w.arrow_text,
                w.arrow_text)
        w.model.set_neutral()
        snap(w, png, "arrows_en")

    def dutch():
        w.lang = "nl"
        w.render()
        r.check("Dutch", w.compute_button.Text == u"Bereken")
        r.check("table still there", w.table.Items.Count == 2)
        check_labels(w, r, "default size, Dutch")
        # the last write was the resultant, a second write: it keeps the length
        r.check("arrow text follows the language",
                u"houden de lengte van de eerste keer" in w.arrow_text, w.arrow_text)
        snap(w, png, "large_nl")

    def english():
        w.lang = "en"
        w.render()

    def tie():
        rank = w.model.rank
        rest = {"sum": (0.0, 0.0, 2690.0, 0.0, 0.0, 0.0), "largest": 900.0, "count": 3,
                "cut_largest": 10.0, "where": [(0.1, 0.0, 0.02)]}
        keep = w.model.result["rest"][rank]
        w.model.result["rest"][rank] = rest
        w._refresh()
        snap(w, png, "tie_en")
        r.check("red banner", u"NOT" in w.banner_title.Text)
        w.model.result["rest"][rank] = keep
        w._refresh()

    def compute_again():
        w.on_compute()

    def running():
        if w.phase != "run":
            return False
        r.check("stop is on while running", w.stop_button.Enabled and not w.compute_button.Enabled)
        snap(w, png, "running_en")

    def compute_again_done():
        if w.phase is not None:
            return False
        r.check("second result", w.table.Items.Count == 2)

    def failing_job():
        real = fb_aster.start

        def bad(man, folder, plan, mesh, exe, scratch=None):
            fb_aster.start = real
            return sup.FakeJob(None, polls=1, code="run", text="exit code 1: boom")
        fb_aster.start = bad
        w.on_compute()

    def failing_job_done():
        if w.phase is not None:
            return False
        r.check("a failed run is a text", w.status_error and u"boom" in w.status, w.status)
        r.check("the old result stays", w.table.Items.Count == 2)

    def stopping():
        w.failed_run = False
        w.on_compute()

    def stopping_running():
        if w.phase != "run":
            return False
        job = w.job
        w.on_stop()
        r.check("stop reaches the job", job.stopped)
        r.check("window free again", w.phase is None and w.compute_button.Enabled)

    def descriptors():
        """What Windows Forms asks of a control when a click goes wrong: an
        IronPython subclass must be able to answer."""
        from System.ComponentModel import TypeDescriptor
        failed = []
        controls = all_controls(w.form) + [w.form]
        for control in controls:
            try:
                TypeDescriptor.GetProperties(control)
            except Exception as e:
                failed.append(u"{0}: {1}".format(type(control).__name__, e))
        r.check("TypeDescriptor on all {0} controls".format(len(controls)), not failed,
                failed[:3])

    def throwing_invoke():
        def boom():
            raise ValueError("thrown on the message loop")
        w._set_status(u"")
        w.form.BeginInvoke(w.F.MethodInvoker(boom))

    def throwing_seen():
        box["throw_wait"] = box.get("throw_wait", 0) + 1
        if u"thrown on the message loop" not in w.status and box["throw_wait"] < 30:
            return False
        r.check("a throw on the message loop reaches the status",
                u"thrown on the message loop" in w.status, w.status)

    def other_selection():
        keep = mw2.selected
        box["keep_sel"] = keep
        mw2.selected = keep[:-1]
        w._ask_selection()

    def other_selection_done():
        box["poll_wait"] = box.get("poll_wait", 0) + 1
        if not w.outdated and box["poll_wait"] < 30:
            w._ask_selection()          # the poll may have left before the change
            return False
        r.check("other selection: table grey", w.outdated and w.outdated_label.Visible)
        r.check("the line says so", u"earlier selection" in w.outdated_label.Text)
        snap(w, png, "outdated_en")
        mw2.selected = box["keep_sel"]
        w._ask_selection()

    def same_selection_again():
        box["poll_back"] = box.get("poll_back", 0) + 1
        if w.outdated and box["poll_back"] < 30:
            w._ask_selection()
            return False
        r.check("same selection: table back", not w.outdated)

    def wrong_loads():
        box["wrong_loads"] = True
        w.on_compute()

    def wrong_loads_done():
        if w.phase is not None:
            return False
        box["wrong_loads"] = False
        stale = hasattr(fb_aster, "check_solution")
        if stale:
            r.check("a run of other loads is refused", u"does not belong" in w.status, w.status)
            r.check("the old table is grey", w.outdated)
        snap(w, png, "stale_en")
        w.on_compute()

    def wrong_loads_cleared():
        if w.phase is not None:
            return False
        r.check("a good run clears the grey", not w.outdated and not w.status_error, w.status)

    def fail_stops_job():
        real = fb_aster.start

        def slow(man, folder, plan, mesh, exe, scratch=None):
            fb_aster.start = real
            job = sup.FakeJob(None, polls=100000)
            box["slow"] = job
            return job
        fb_aster.start = slow
        w.on_compute()

    def fail_stops_job_running():
        if w.phase != "run":
            return False
        w._fail("error", u"forced")
        r.check("a failure stops the run first", box["slow"].stopped)
        r.check("the table goes grey after a failed run", w.outdated)
        w.on_compute()

    def fail_clear():
        if w.phase is not None:
            return False

    def closed_model():
        mw2.alive = False
        w.on_compute()

    def closed_model_done():
        if w.phase is not None:
            return False
        r.check("closed model is a text", w.status_error and u"No model" in w.status, w.status)
        w._ask_selection()

    def closed_model_poll():
        if w.selection_busy:
            return False
        r.check("selection line says so", u"No model" in w.selection_label.Text,
                w.selection_label.Text)
        snap(w, png, "nomodel_en")
        r.check("drawing still answers", w.model.view() is not None)
        w.on_neutral()
        mw2.alive = True

    def empty_selection():
        keep = mw2.selected
        mw2.selected = []
        box["keep"] = keep
        w.on_compute()

    def empty_selection_done():
        if w.phase is not None:
            return False
        r.check("empty selection refused", u"Select elements" in w.status, w.status)
        mw2.selected = box["keep"]

    def bad_handler():
        def boom():
            raise ValueError("guarded")
        w._guard(boom)(None, None)
        r.check("a handler error stays in the window", u"guarded" in w.status, w.status)

    def inactive_render():
        """A panel the user has used, now behind Mecway: it still has an active
        control. A render (language, tab) disposes it; Windows Forms would then
        focus the next control and activate the window (the trap refuses and
        reports that)."""
        trap = focus_trap.current()
        before = len(trap.attempts)
        w.form.ActiveControl = w.compute_button
        r.check("active control set without the focus",
                w.form.ActiveControl is w.compute_button and not w.form.ContainsFocus)
        w.render()
        r.check("a render of an inactive panel tries no focus", len(trap.attempts) == before,
                [focus_trap.describe(a) for a in trap.attempts[before:]])
        r.check("  and forgets the old control", w.form.ActiveControl is None,
                type(w.form.ActiveControl).__name__)

    def focus_check():
        import ctypes
        import System
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        owner = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        pid = System.Diagnostics.Process.GetCurrentProcess().Id
        r.check("foreground window is not ours", owner.value != pid, owner.value)
        r.check("window never active", not w.form.ContainsFocus)

    return [wait_auto_result, first_image, small_image, very_large_image, switch_axes,
            type_point, drag_point, presets, node_nearest, node_nearest_done, choose_cut,
            step_choice, copying, arrows_force, arrows_force_done, arrows_result_done,
            dutch, english, tie, compute_again, running, compute_again_done, descriptors,
            throwing_invoke, throwing_seen, other_selection,
            other_selection_done, same_selection_again, wrong_loads, wrong_loads_done,
            wrong_loads_cleared, fail_stops_job, fail_stops_job_running, fail_clear,
            failing_job, failing_job_done, stopping, stopping_running, closed_model,
            closed_model_done, closed_model_poll, empty_selection, empty_selection_done,
            bad_handler, inactive_render, focus_check]
