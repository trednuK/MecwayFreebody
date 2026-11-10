# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_figures.py
# The images of the panel in the user guide (docs/images/window_*_{nl,en}.png),
# with numbered markers at the place of the real controls. Mecway's IronPython,
# without Mecway:
#
#   powershell -ExecutionPolicy Bypass -File tools/run_ipy.ps1 \
#       -Script tools/fb_figures.py -ScriptArgs <repo>,<folder>[,raw]
#
# The window is the real one (fb_gui._Window) on fakes of mw and the solution
# (tests/test_gui_support.py) and a small bar of its own (tests/test_gui_model.py,
# hex20, 200 x 20 x 40 mm). The cut and the panel's sums are the real ones; only
# the follow-up run of Code-Aster is stood in for: its nodal forces are the
# statics of a cantilever with a tip load, spread over the cut nodes so that
# their sums are the exact section forces. No measurement.
#
# Rules (see tests/test_gui_window.py): the form is never shown (no Show, no
# Application.Run) and lies beyond the whole virtual desktop; it gets its
# handles and draws itself with DrawToBitmap. A tab is chosen before there are
# handles (as fb_gui.show_tab does), never through SelectedIndex on a control
# with a handle. No clipboard. After every scene the focus rules are checked; a
# broken rule stops the run. Before an image is saved, every text of the window
# is checked for private paths. The settings go to a file of their own, so the
# user's Scripts/fb_settings.json is not touched (checked).
#
# Which numbers each image carries: tools/fb_marks.py (also read by
# tests/test_gui_docs.py, which compares them with the tables in the guides).

import os
import re
import shutil
import sys
import tempfile
import traceback

REPO = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else None
for _sub in ("tests", "Scripts", "tools"):
    if REPO and os.path.join(REPO, _sub) not in sys.path:
        sys.path.insert(0, os.path.join(REPO, _sub))

import clr  # noqa: E402
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System  # noqa: E402
import System.Drawing as D  # noqa: E402
import System.Windows.Forms as F  # noqa: E402

# As Mecway: themed controls and labels drawn with GDI (before the first
# control of this process). With GDI+ text, wrapped labels lost spaces in the
# images (measured).
F.Application.EnableVisualStyles()
F.Application.SetCompatibleTextRenderingDefault(False)

import fb_marks  # noqa: E402

# What the images show: a model path and a run folder that belong to no one
MODEL_PATH = u"C:\\Models\\bar.liml"
RUN_FOLDER = u"C:\\Models"
RUN_ID = u"20261107_120000"
SECONDS = 2.4
LENGTH = 0.2                     # the bar of test_gui_model
TIP_LOAD = (2000.0, 150.0, -500.0)   # N, at the end x = LENGTH, full at t = 1
X_CUT = 0.08                     # the plane of the cut by nodes
# (as in tests/test_gui_all.py; [/] keeps that check off this line)
PRIVATE = re.compile(r"[A-Za-z]:\\Users\\|[/]Users[/]|@[a-z0-9.-]+\.[a-z]{2,}|\\AppData\\|"
                     r"\\Temp\\", re.I)
_SPAN = 6000


class RuleBroken(Exception):
    pass


# ---------------------------------------------------------------- stand-in run
def _section_nodes(mesh, x):
    used = set(n for _, nids in mesh["elements"].values() for n in nids)
    return [n for n in used if abs(mesh["nodes"][n][0] - x) < 1e-9]


def section_force(x, side, scale):
    """The force and moment of the rest on a free body at side of the plane x
    (1: the body lies at smaller x, the rest is the part beyond x with the tip
    load), about the centroid (x, 0, 0) of the bar, global axes."""
    p = tuple(side * scale * c for c in TIP_LOAD)
    arm = LENGTH - x
    return p, (0.0, -arm * p[2], arm * p[1])


def node_forces(mesh, nids, inside, scale):
    """Nodal forces whose sums over each full section are the section force:
    an even share, a linear part for the bending moments and a turning part for
    the torque. A node gets the side of the selection: the mean x of inside."""
    used = set(n for e in inside for n in mesh["elements"][e][1])
    mean_x = sum(mesh["nodes"][n][0] for n in used) / float(len(used))
    out = []
    sections = {}
    for nid in nids:
        x, y, z = mesh["nodes"][nid]
        key = round(x, 9)
        if key not in sections:
            all_n = _section_nodes(mesh, x)
            syy = sum(mesh["nodes"][q][1] ** 2 for q in all_n)
            szz = sum(mesh["nodes"][q][2] ** 2 for q in all_n)
            sections[key] = (len(all_n), syy, szz)
        n, syy, szz = sections[key]
        f, m = section_force(x, 1.0 if mean_x < x else -1.0, scale)
        polar = syy + szz
        out.append((f[0] / n + m[1] * z / szz - m[2] * y / syy,
                    f[1] / n - m[0] * z / polar,
                    f[2] / n + m[0] * y / polar, 0.0, 0.0, 0.0))
    return out


def stand_in_start(sup, times=(0.5, 1.0)):
    """fb_aster.start for plan_and_start: a HookJob (the prepare hook, then the
    real link_nodes and judge_rest) on the statics above, one step per time."""
    def start(man, folder, plan, mesh, exe, scratch=None, timeout=None, memory=None,
              prepare=None):
        nodes = [{"index": i, "xyz": tuple(mesh["nodes"][n]), "large": False, "nid": n}
                 for i, n in enumerate(plan["cut_nodes"])]
        forces, disp, rest, on_cut = {}, {}, {}, {}
        ranks = list(range(1, len(times) + 1))
        for r, t in zip(ranks, times):
            forces[r] = node_forces(mesh, plan["cut_nodes"], plan["inside"], t)
            disp[r] = [(0.0, 0.0, 0.0) for _ in nodes]
            rest[r] = {"sum": (0.0,) * 6, "largest": 0.0, "cut_largest": 10.0, "count": 0,
                       "where": [], "tolerance": 1e-6, "top": []}
            on_cut[r] = {"totals": [(0.0,) * 6 for _ in nodes]}
        raw = {"steps": [{"rank": r, "time": t} for r, t in zip(ranks, times)],
               "nodes": nodes, "forces": forces, "disp": disp, "rest": rest,
               "on_cut": on_cut, "large": False, "extra_nodes": False, "warnings": [],
               "seconds": SECONDS}
        return sup.HookJob(raw, prepare, polls=0, plan=plan, mesh=mesh)
    return start


# ---------------------------------------------------------------- the window
def offscreen_location():
    """Beyond the bottom-right of the whole virtual desktop (as
    tests/test_gui_window.py), or beyond its top-left if that is too far."""
    v = F.SystemInformation.VirtualScreen
    x, y = v.Right + 2000, v.Bottom + 2000
    if x + _SPAN > 30000 or y + _SPAN > 30000:
        x, y = v.Left - 2000 - _SPAN, v.Top - 2000 - _SPAN
    return (x, y)


def _user32():
    import ctypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    return ctypes, u


def check_rules(form, moment):
    """The hard rules: never shown, off the desktop, no focus, the foreground
    window not of this process."""
    ctypes, u = _user32()
    problems = []
    if form.Visible:
        problems.append(u"the form is visible")
    if form.Bounds.IntersectsWith(F.SystemInformation.VirtualScreen):
        problems.append(u"the form lies on the desktop")
    if form.ContainsFocus or F.Form.ActiveForm is not None:
        problems.append(u"the form has the focus")
    hwnd = u.GetForegroundWindow()
    if hwnd:
        owner = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == System.Diagnostics.Process.GetCurrentProcess().Id:
            problems.append(u"the foreground window is of this process")
    if problems:
        raise RuleBroken(u"{0}: {1}".format(moment, u"; ".join(problems)))


def handles(control):
    """Real window handles, without showing anything."""
    control.Handle
    for child in control.Controls:
        handles(child)


def all_controls(control):
    out = []
    for child in control.Controls:
        out.append(child)
        out.extend(all_controls(child))
    return out


def texts(w):
    """Every text the window holds, for the private check: controls, items,
    tooltips and the texts of the drawing."""
    out = [w.form.Text]
    view = w.view or {}
    out.extend(u"{0}".format(view.get(k) or u"") for k in ("title", "about", "real"))
    out.append(u"{0}".format((view.get("plane") or {}).get("text") or u""))
    for c in all_controls(w.form):
        out.append(u"{0}".format(c.Text))
        try:
            out.append(u"{0}".format(w.tips.GetToolTip(c)))
        except Exception:
            pass
        if isinstance(c, (F.ComboBox, F.ListBox)):
            out.extend(u"{0}".format(item) for item in c.Items)
        if isinstance(c, F.ListView):
            out.extend(c.Columns[i].Text for i in range(c.Columns.Count))
            for item in c.Items:
                out.extend(item.SubItems[i].Text for i in range(item.SubItems.Count))
    return out


def check_private(w):
    temp = os.path.normcase(tempfile.gettempdir())
    user = os.environ.get("USERNAME")
    named = re.compile(r"\b" + re.escape(user) + r"\b", re.I) if user else None
    for text in texts(w):
        low = os.path.normcase(text)
        if PRIVATE.search(text) or temp in low or (named and named.search(text)):
            raise RuleBroken(u"private text in the window: {0!r}".format(text[:120]))


class Scene(object):
    """One window in one language on the fakes, never shown."""

    def __init__(self, ctx, lang, mode="elements", arrow_mode="nodes", tab="panel"):
        self.ctx = ctx
        gui, sup = ctx["gui"], ctx["sup"]
        gui._CACHE["settings"] = dict(gui._DEFAULTS)
        gui._CACHE["settings"].update({"language": lang, "cut_mode": mode,
                                       "arrow_mode": arrow_mode, "unit": "N",
                                       "axes": "section", "folder": "auto"})
        m = ctx["m"]
        self.mw = sup.FakeMw(m, path=MODEL_PATH)
        self.solution = sup.FakeSolution(m, times=(0.5, 1.0))
        self.w = gui._Window(self.mw, self.solution, gui._MwCaller(True),
                             {"no_activate": True, "location": offscreen_location(),
                              "doc_browser": False, "open_web": lambda url: None})
        w = self.w
        if tab != "panel":
            # before any handle, as show_tab does: no focus
            w.tab = tab
            w.render()
        handles(w.form)
        F.Application.DoEvents()
        check_rules(w.form, u"after the handles")

    def result(self, ids, side=1):
        """Select ids, compute through plan_and_start and the stand-in, and put
        the result in the window as a finished computation does."""
        ctx, w = self.ctx, self.w
        gui, sup, mesh = ctx["gui"], ctx["sup"], ctx["mesh"]
        mode = w.cut_mode
        if mode == "nodes":
            self.mw.selected_node_list = list(ids)
        else:
            self.mw.selected = list(ids)
        w.side = side
        selection = ctx["mecway"].read_selection(self.mw, self.solution)
        w.last = {"path": MODEL_PATH, "selection": selection, "mode": mode, "side": side,
                  "mesh": mesh}
        w.subtitle.Text = MODEL_PATH
        w._set_selection_text(selection)
        # the run as the scan finds it: manifest and base on disk (in the work
        # folder), checked by fb_aster.refuse and shown by the panel itself; in
        # its line only the work folder becomes the neutral one
        man = dict(ctx["man"])
        man["_folder"] = ctx["runs"]
        w.scan = {"runs": [man], "folders": [ctx["runs"]], "other": 0,
                  "bridge": {"exe": u"run_aster.bat", "problems": []},
                  "version": man["aster_version"], "fingerprint": man["fingerprint"]}
        w._fill_runs()
        if w.run_refusal is not None:
            raise RuleBroken(u"the run is refused: {0}".format(w.run_refusal))
        line = w.run_label.Text
        if ctx["runs"] not in line:
            raise RuleBroken(u"the run line does not name its folder: {0}".format(line))
        w.run_label.Text = line.replace(ctx["runs"], RUN_FOLDER)
        aster = ctx["aster"]
        real = aster.start
        aster.start = stand_in_start(sup)
        try:
            plan, geos, job, cut = gui.plan_and_start(mesh, ids, mode, side, None, man,
                                                      RUN_FOLDER, u"run_aster.bat")
        finally:
            aster.start = real
        result = job.result()
        per = ctx["core"].assign_nodes(plan, mesh, result)
        model = gui.PanelModel()
        model.unit, model.axes, model.lang = w.model.unit, w.model.axes, w.lang
        model.load(mesh, plan, geos, result, per, man, RUN_FOLDER, nodecut=cut)
        w._install(model)
        handles(w.form)
        F.Application.DoEvents()
        if w.status_error:
            raise RuleBroken(u"the window reports an error: {0}".format(w.status))
        return model

    def close(self):
        w = self.w
        w.timer.Stop()
        w.form.Dispose()


# ---------------------------------------------------------------- capture
MARGIN = 40
DISC = 24
MARK_COLOUR = (196, 60, 0)


def capture(w):
    """The form as a bitmap, with the text a never-shown form leaves out: that
    of the combo boxes (drawn by their native part; measured: text boxes, list
    boxes and the list view do draw), with their own font at their own place."""
    from System.Drawing.Imaging import PixelFormat
    form = w.form
    F.Application.DoEvents()
    bmp = D.Bitmap(form.Width, form.Height, PixelFormat.Format32bppArgb)
    form.DrawToBitmap(bmp, D.Rectangle(0, 0, form.Width, form.Height))
    g = D.Graphics.FromImage(bmp)
    try:
        for c in all_controls(form):
            if isinstance(c, F.ComboBox) and _shown(c):
                _text_in(g, w, c, c.Text, D.Rectangle(4, 1, c.Width - 26, c.Height - 2),
                         F.TextFormatFlags.VerticalCenter | F.TextFormatFlags.EndEllipsis |
                         F.TextFormatFlags.NoPrefix)
    finally:
        g.Dispose()
    return bmp


_GET_STATE = None


def _own_visible(c):
    """The control's own Visible setting: on a form that is never shown,
    Control.Visible is False for everything."""
    global _GET_STATE
    if _GET_STATE is None:
        from System.Reflection import BindingFlags
        _GET_STATE = clr.GetClrType(F.Control).GetMethod(
            "GetState", BindingFlags.NonPublic | BindingFlags.Instance)
    return bool(_GET_STATE.Invoke(c, System.Array[System.Object]([2])))   # STATE_VISIBLE


def _shown(c):
    """False for a control that is hidden itself or within its parents, or
    on a tab page that is not the open one."""
    p = c
    while p is not None:
        if not _own_visible(p) and not isinstance(p, F.Form):
            return False
        if isinstance(p, F.TabPage) and p.Parent is not None and \
                p.Parent.SelectedTab is not p:
            return False
        p = p.Parent
    return True


def _text_in(g, w, c, text, rect, flags):
    from System.Drawing.Text import TextRenderingHint
    at = corner(w, c)
    r = D.RectangleF(float(at[0] + rect.X), float(at[1] + rect.Y), float(rect.Width),
                     float(rect.Height))
    colour = c.ForeColor if c.Enabled else D.SystemColors.GrayText
    g.SetClip(D.Rectangle(at[0], at[1], c.Width, c.Height))
    # GDI+ with grey smoothing: GDI text on a 32-bit bitmap comes out too dark
    g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit
    form = D.StringFormat()
    form.LineAlignment = D.StringAlignment.Center
    form.Trimming = D.StringTrimming.EllipsisCharacter
    form.FormatFlags = D.StringFormatFlags.NoWrap
    brush = D.SolidBrush(colour)
    g.DrawString(text, c.Font, brush, r, form)
    brush.Dispose()
    g.ResetClip()


def text_width(text, font, gdi=True):
    """Width in pixels of a text as a label (GDI) or the drawing (GDI+) draws it."""
    if gdi:
        return F.TextRenderer.MeasureText(text, font).Width
    bmp = D.Bitmap(1, 1)
    g = D.Graphics.FromImage(bmp)
    try:
        return int(g.MeasureString(text, font).Width)
    finally:
        g.Dispose()
        bmp.Dispose()


def corner(w, control):
    """Top left of a control in the bitmap of the form."""
    p = control.PointToScreen(D.Point(0, 0))
    return p.X - w.form.Left, p.Y - w.form.Top


class Marks(object):
    """Numbered discs on a capture, after tools/gui_cap.py of
    MecwayAdvancedBeamAnalysis: the form between two white margins, each disc
    where the real control is, so the numbers follow the layout."""

    def __init__(self, w, name):
        self.w = w
        self.name = name
        self.items = {}

    def _put(self, key, spot, target):
        number = fb_marks.number(self.name, key)
        self.items[key] = (number, spot, target)

    def place(self, control):
        x, y = corner(self.w, control)
        return x + MARGIN, y

    def left(self, key, control, dy=0, dx=0):
        """In the left margin, level with a control (its middle, moved by dy);
        the line ends at its left edge (moved by dx)."""
        x, y = self.place(control)
        y += control.Height // 2 + dy
        self._put(key, (MARGIN // 2, y), (x + 2 + dx, y))

    def right_at(self, key, control, x, y):
        """In the right margin, with a line to pixel x, y of a control."""
        cx, cy = self.place(control)
        self._put(key, (self.w.form.Width + MARGIN + MARGIN // 2, cy + int(y)),
                  (cx + int(x), cy + int(y)))

    def above(self, key, control, gap=20):
        """Above the middle of a control, with a short line down to it (for the
        top row of the bar: the tab row above it is empty there)."""
        x, y = self.place(control)
        self._put(key, (x + control.Width // 2, y - gap), (x + control.Width // 2, y))

    def before(self, key, control, gap=16):
        """A disc just left of a control, level with its middle, no line."""
        x, y = self.place(control)
        self._put(key, (x - gap, y + control.Height // 2), None)

    def after(self, key, control, gap=16):
        """A disc just right of a control, level with its middle, no line."""
        x, y = self.place(control)
        self._put(key, (x + control.Width + gap, y + control.Height // 2), None)

    def right(self, key, control, dy=0, end=None):
        """In the right margin, level with a control; the line ends at its right
        edge (or at end, pixels from its left)."""
        x, y = self.place(control)
        y += control.Height // 2 + dy
        stop = x + (control.Width - 2 if end is None else end)
        self._put(key, (self.w.form.Width + MARGIN + MARGIN // 2, y), (stop, y))

    def at(self, key, control, x, y, dx, dy):
        """A disc dx, dy from pixel x, y of a control, with a line to that pixel
        (none when dx and dy are 0: the disc stands on it)."""
        cx, cy = self.place(control)
        target = (cx + int(x), cy + int(y))
        spot = (target[0] + int(dx), target[1] + int(dy))
        self._put(key, spot, target if (dx or dy) else None)

    def save(self, path):
        from System.Drawing.Drawing2D import SmoothingMode
        from System.Drawing.Imaging import ImageFormat, PixelFormat
        missing = [k for k in fb_marks.keys(self.name) if k not in self.items]
        if missing:
            raise RuleBroken(u"{0}: no marker for {1}".format(self.name, missing))
        shot = capture(self.w)
        out = D.Bitmap(shot.Width + 2 * MARGIN, shot.Height, PixelFormat.Format24bppRgb)
        g = D.Graphics.FromImage(out)
        g.Clear(D.Color.White)
        g.DrawImage(shot, MARGIN, 0, shot.Width, shot.Height)
        shot.Dispose()
        g.SmoothingMode = SmoothingMode.AntiAlias
        colour = D.Color.FromArgb(*MARK_COLOUR)
        pen = D.Pen(colour, 1.6)
        brush = D.SolidBrush(colour)
        ring = D.Pen(D.Color.White, 2.0)
        font = D.Font("Segoe UI", 10.0, D.FontStyle.Bold)
        centre = D.StringFormat()
        centre.Alignment = D.StringAlignment.Center
        centre.LineAlignment = D.StringAlignment.Center
        items = sorted(self.items.values())
        for number, spot, target in items:
            if target:
                g.DrawLine(pen, spot[0], spot[1], target[0], target[1])
                g.FillEllipse(brush, target[0] - 2, target[1] - 2, 5, 5)
        for number, spot, target in items:
            r = D.Rectangle(spot[0] - DISC // 2, spot[1] - DISC // 2, DISC, DISC)
            g.FillEllipse(brush, r)
            g.DrawEllipse(ring, r)
            g.DrawString(str(number), font, D.Brushes.White, D.RectangleF(
                float(r.X), float(r.Y) + 0.5, float(DISC), float(DISC)), centre)
        g.Dispose()
        out.Save(path, ImageFormat.Png)
        out.Dispose()


def save_raw(w, path):
    from System.Drawing.Imaging import ImageFormat
    bmp = capture(w)
    bmp.Save(path, ImageFormat.Png)
    bmp.Dispose()


# ---------------------------------------------------------------- the scenes
def button(w, text):
    """The button with this text (the language and footer buttons have no name)."""
    for c in all_controls(w.form):
        if isinstance(c, F.Button) and c.Text == text:
            return c
    raise RuleBroken(u"no button {0!r}".format(text))


def mark_tabs(m, w):
    """In the empty tab row, right of the two tabs."""
    tab = w.tabs.GetTabRect(1)
    m.at("tabs", w.tabs, tab.Right + 22, tab.Y + tab.Height // 2, 0, 0)


def mark_drawing(m, w, keys):
    """Title, chosen point, plane line and the line under the drawing, at the
    places draw_cut gives them (title at 8, 6; plane line at 26; about at the
    bottom - 40)."""
    pic, view = w.picture, w.view
    bold = D.Font("Segoe UI", 9.0, D.FontStyle.Bold)
    font = D.Font("Segoe UI", 8.5)
    if "drawing" in keys:
        m.right_at("drawing", pic, 14 + text_width(view["title"], bold, False), 15)
    if "plane" in keys:
        m.right_at("plane", pic, 34 + text_width(view["plane"]["text"], font, False), 36)
    if "about" in keys:
        m.right_at("about", pic, 14 + text_width(view["about"], font, False),
                   pic.Height - 31)
    if "point" in keys:
        import fb_gui
        x, y = fb_gui.to_pixel(w.map, view["point"][0], view["point"][1])
        m.at("point", pic, x, y, -96, -64)


def scene_elements(ctx, lang, path, raw=False):
    """The panel tab: a slice of the bar selected (elements 9 to 12, x = 80 to
    120 mm), two cuts."""
    s = Scene(ctx, lang)
    try:
        w = s.w
        s.result(ctx["sup"].selected_slice())
        check_rules(w.form, u"elements, result")
        check_private(w)
        if raw:
            return save_raw(w, path)
        m = Marks(w, "window_elements")
        mark_tabs(m, w)
        m.right("language", button(w, u"EN"))
        m.left("compute", w.compute_button)
        m.above("mode", w.mode_combo)
        m.right("selection", w.selection_label,
                end=text_width(w.selection_label.Text, w.selection_label.Font) + 6)
        m.left("folder", w.folder_combo, dx=-68)
        m.right("run", w.run_combo)
        m.left("run_line", w.run_label)
        m.left("banner", w.banner)
        m.left("view", w.step_label)
        m.left("axes_note", w.axes_note)
        m.left("table", w.table)
        m.left("sign", w.sign_label)
        m.left("warnings", w.warning_box)
        m.left("arrows", w.arrow_title)
        mark_drawing(m, w, ("drawing", "point", "about"))
        m.right("point_boxes", w.point_hint,
                end=text_width(w.point_hint.Text, w.point_hint.Font) + 6)
        m.before("neutral", w.neutral_button)
        m.right("node", w.node_button)
        m.left("status", w.status_label)
        m.before("copy", button(w, w.t("copy")))
        m.right("close", button(w, w.t("close")))
        m.save(path)
    finally:
        s.close()


def scene_nodes(ctx, lang, path, raw=False):
    """Cut by nodes on a plane: the half y >= 0 of the section at x = 80 mm
    (10 x 40 mm, so its principal axes are y and z), the free body at side -
    (after Other side): a partial section."""
    s = Scene(ctx, lang, mode="nodes")
    try:
        w = s.w
        half = ctx["sup"].nodes_at(ctx["mesh"], X_CUT, lambda y, z: y > -1e-9)
        model = s.result(half, side=-1)
        if not (model.nodecut and model.nodecut["partial"]):
            raise RuleBroken(u"the cut by nodes is no partial section")
        check_rules(w.form, u"nodes, result")
        check_private(w)
        if raw:
            return save_raw(w, path)
        m = Marks(w, "window_nodes")
        m.above("mode", w.mode_combo)
        m.above("side", w.side_button)
        m.right("selection", w.selection_label,
                end=text_width(w.selection_label.Text, w.selection_label.Font) + 6)
        m.left("banner", w.banner)
        # the row of the cut, under the head of the table
        m.left("table", w.table, dy=-w.table.Height // 2 + 34)
        m.left("sign", w.sign_label, dy=w.sign_label.Height // 4)
        m.left("warnings", w.warning_box, dy=-w.warning_box.Height // 4)
        mark_drawing(m, w, ("plane",))
        m.save(path)
    finally:
        s.close()


def scene_arrows(ctx, lang, path, raw=False):
    """Step 1 of 2 chosen and one resultant per cut written as arrows."""
    s = Scene(ctx, lang, arrow_mode="resultant")
    try:
        w = s.w
        s.result(ctx["sup"].selected_slice())
        w.step_combo.SelectedIndex = 0
        w.on_arrows()
        w._tick_asks()
        F.Application.DoEvents()
        if not w.arrow_text or w.status_error or w.model.rank != 1:
            raise RuleBroken(u"arrows not written: {0} {1}".format(w.arrow_text, w.status))
        check_rules(w.form, u"arrows")
        check_private(w)
        if raw:
            return save_raw(w, path)
        m = Marks(w, "window_arrows")
        m.left("step", w.step_label)
        m.left("table", w.table, dy=-w.table.Height // 2 + 42)
        m.left("arrow_mode", w.arrow_title)
        m.after("write", w.arrow_button)
        m.left("report", w.arrow_label, dy=-w.arrow_label.Height // 2 + 10)
        m.save(path)
    finally:
        s.close()


def scene_docs(ctx, lang, path, raw=False):
    """The tab Documentation on the guide, as the text view shows it: the
    browser element is not made here (MSHTML can take the focus, measured in
    tests/test_gui_window.py)."""
    s = Scene(ctx, lang, tab="docs")
    try:
        w = s.w
        if w.tabs.SelectedIndex != 1 or w.doc_view is None:
            raise RuleBroken(u"the tab Documentation is not open")
        check_rules(w.form, u"docs")
        check_private(w)
        if raw:
            return save_raw(w, path)
        m = Marks(w, "window_docs")
        mark_tabs(m, w)
        m.left("list", w.doc_list, dy=-w.doc_list.Height // 2 + w.doc_list.ItemHeight // 2)
        m.right("viewer", w.doc_view, dy=-w.doc_view.Height // 4)
        m.left("notice", w.doc_notice)
        m.right("language", button(w, u"EN"))
        m.save(path)
    finally:
        s.close()


SCENES = (("window_elements", scene_elements), ("window_nodes", scene_nodes),
          ("window_arrows", scene_arrows), ("window_docs", scene_docs))


def context(repo, folder):
    import fb_aster
    import fb_core
    import fb_gui
    import fb_mecway
    import test_gui_support as sup
    fb_gui.ui_scale = lambda: 1.0
    fb_gui.SETTINGS_PATH = os.path.join(folder, "settings.json")
    fb_gui._CACHE["settings"] = dict(fb_gui._DEFAULTS)
    logged = []
    fb_gui.log = logged.append
    m, mesh = sup.make_mesh("hex20")
    fingerprint = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
    man = sup.manifest(fingerprint, run_id=RUN_ID, model=u"bar")
    runs = os.path.join(folder, "runs")
    sup.write_run(runs, man)
    return {"gui": fb_gui, "sup": sup, "aster": fb_aster, "core": fb_core,
            "mecway": fb_mecway, "m": m, "mesh": mesh, "man": man, "log": logged,
            "runs": runs}


def _settings_state(repo):
    path = os.path.join(repo, "Scripts", "fb_settings.json")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return (os.path.getmtime(path), f.read())


def main():
    repo, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    raw = len(sys.argv) > 3 and sys.argv[3] == "raw"
    if not os.path.isdir(out):
        os.makedirs(out)
    before = _settings_state(repo)
    work = tempfile.mkdtemp(prefix="fb_figures_")
    code = 0
    try:
        ctx = context(repo, work)
        for lang in ("nl", "en"):
            for name, scene in SCENES:
                path = os.path.join(out, u"{0}_{1}.png".format(name, lang))
                scene(ctx, lang, path, raw)
                print(u"{0}: {1} bytes".format(os.path.basename(path), os.path.getsize(path)))
        if ctx["log"]:
            print(u"log of the panel:")
            for line in ctx["log"]:
                print(u"  " + u"{0}".format(line)[:300])
    except RuleBroken as e:
        print(u"STOPPED: {0}".format(e))
        code = 3
    except Exception:
        print(traceback.format_exc())
        code = 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if _settings_state(repo) != before:
        print(u"FAIL: Scripts/fb_settings.json changed")
        code = code or 4
    sys.exit(code)


if sys.argv and os.path.basename(sys.argv[0]) == "fb_figures.py":
    main()
