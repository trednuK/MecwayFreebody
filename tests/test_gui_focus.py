# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_focus.py
# A tripwire for focus in Mecway's IronPython: a WH_CBT hook on the thread of
# the test window. Windows asks it before it activates a window of that thread
# (HCBT_ACTIVATE) and before it gives one the keyboard focus (HCBT_SETFOCUS);
# the trap writes the attempt down, with the Windows Forms frames that made it,
# and refuses it, so the window neither becomes active nor the foreground
# window. Only for this thread (hMod NULL, own thread id), never global.
# proof(): before the real window parts, on a small window of its own, that
# the hook is live, that its answer blocks, and that it catches the known ways
# to steal the focus (a tab chosen in code; the active control disposed).

import traceback

WH_CBT = 5
HCBT_CREATEWND, HCBT_ACTIVATE, HCBT_SETFOCUS = 3, 5, 9
NAMES = {HCBT_ACTIVATE: "activate", HCBT_SETFOCUS: "setfocus"}
PROBE_TITLE = u"MecwayFreebody probe"
_LOOP = ("PeekMessage", "GetMessage", "WaitMessage", "MsgWaitForMultipleObjects")

_STATE = {"current": None, "unreported": []}


def _api():
    """ctypes and the functions of the hook, set up once: the function type of
    the callback and the argtypes that name it stay the same objects."""
    if "api" not in _STATE:
        import ctypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p)
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, proc, ctypes.c_void_p, ctypes.c_uint32]
        u.SetWindowsHookExW.restype = ctypes.c_void_p
        u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                     ctypes.c_void_p]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        u.GetWindowThreadProcessId.restype = ctypes.c_uint32
        k.GetCurrentThreadId.restype = ctypes.c_uint32
        _STATE["api"] = (ctypes, u, k, proc)
    return _STATE["api"]

def winforms_frames(stack):
    """The Windows Forms frames of a managed stack, innermost first, without
    file names."""
    out = []
    for line in stack.splitlines():
        at = line.find("System.Windows.Forms.")     # after "at " in any language
        if at < 0:
            continue
        out.append(line[at + len("System.Windows.Forms."):].split(" in ")[0].strip())
    return out


def origin(frames):
    """"code" when a Windows Forms call made the attempt, "system" when it came
    in while the thread waited for messages (Windows itself)."""
    if frames and any(word in frames[0] for word in _LOOP):
        return "system"
    return "code" if frames else "system"


class FocusTrap(object):
    """The CBT hook of one thread. attempts: dicts with kind, class, origin,
    moment, frames. Refuses every activation and focus while installed."""

    def __init__(self):
        self.attempts = []
        self.counts = {}
        self.errors = []
        self.block_create = False
        self.blocked_create = 0
        self.moment = u""
        self.handle = None
        self.thread = None
        self.reported = 0
        self._cb = None

    def install(self):
        ctypes, u, k, proc = _api()
        self._ctypes, self._u = ctypes, u
        self._cb = proc(self._proc)         # kept: the hook calls it for the thread's life
        self.thread = k.GetCurrentThreadId()
        self.handle = u.SetWindowsHookExW(WH_CBT, self._cb, None, self.thread)
        if not self.handle:
            raise RuntimeError("no CBT hook on thread {0}".format(self.thread))
        return self

    def uninstall(self):
        if self.handle:
            self._u.UnhookWindowsHookEx(self.handle)
            self.handle = None

    def live(self):
        return bool(self.handle) and self.counts.get(HCBT_CREATEWND, 0) > 0

    def _proc(self, code, wparam, lparam):
        # Inside a call of Windows: never raise, pump or touch a control here.
        refuse = False
        try:
            self.counts[code] = self.counts.get(code, 0) + 1
            if code in NAMES and wparam:
                refuse = True
                self._note(code, wparam)
            elif code == HCBT_CREATEWND and self.block_create:
                self.blocked_create += 1
                refuse = True
        except Exception:
            refuse = refuse or code in NAMES
            try:
                self.errors.append(traceback.format_exc()[-300:])
            except Exception:
                pass
        if refuse:
            return 1
        try:
            return self._u.CallNextHookEx(None, code, wparam, lparam)
        except Exception:
            return 0

    def _note(self, code, hwnd):
        import System
        name = self._ctypes.create_unicode_buffer(128)
        self._u.GetClassNameW(self._ctypes.c_void_p(hwnd), name, 128)
        frames = winforms_frames(System.Environment.StackTrace)
        self.attempts.append({"kind": NAMES[code], "class": name.value,
                              "origin": origin(frames), "moment": self.moment,
                              "frames": frames[:12]})

    def new_attempts(self):
        """Attempts not yet handed out by this call."""
        out = self.attempts[self.reported:]
        self.reported = len(self.attempts)
        return out


def describe(attempt):
    return u"{0} of {1} ({2}) at {3}: {4}".format(
        attempt["kind"], attempt["class"], attempt["origin"], attempt["moment"],
        u" <- ".join(attempt["frames"][:6]) or u"no Windows Forms frames")


def current():
    """The trap of the newest test window."""
    return _STATE["current"]


def on_thread():
    """run_window's option on_thread: a trap on the window thread before any
    control. When the window is gone, what was never reported goes to
    unreported(); the hook is removed."""
    trap = FocusTrap().install()
    _STATE["current"] = trap

    def after():
        trap.uninstall()
        _STATE["unreported"].extend(trap.new_attempts())
        if trap.errors:
            _STATE["unreported"].append({"kind": "error", "class": u"", "origin": "trap",
                                         "moment": u"hook", "frames": trap.errors[:2]})
    return after


def unreported():
    return list(_STATE["unreported"])


# ---------------- the proof, on a window of its own ----------------
def proof(report, location, limit=60.0):
    """The trap on a small off-screen window in this hidden Mecway. Stops at
    the first step that does not hold, before any step that would take the
    focus without the trap."""
    import clr
    clr.AddReference("System.Windows.Forms")
    from System.Threading import Thread, ThreadStart, ApartmentState
    done = {}

    def body():
        try:
            _proof_window(report, location, done)
        except Exception:
            report.check("trap proof", False, traceback.format_exc())
        done["end"] = True

    thread = Thread(ThreadStart(body))
    thread.SetApartmentState(ApartmentState.STA)
    thread.IsBackground = True
    thread.Start()
    if not thread.Join(int(limit * 1000)):
        report.check("trap proof in time", False, done.get("step"))
        form = done.get("form")
        if form is not None and not form.IsDisposed:
            from System.Windows.Forms import MethodInvoker
            form.BeginInvoke(MethodInvoker(form.Close))     # its thread ends, the hook goes
            thread.Join(5000)
    return done


def _proof_window(report, location, done):
    import fb_gui
    import test_gui_window as tw
    D, F = fb_gui._forms()
    r = report
    trap = FocusTrap().install()
    try:
        form = fb_gui.quiet_form_class()()
        form.ShowInTaskbar = False
        form.Text = PROBE_TITLE
        done["form"] = form
        form.StartPosition = F.FormStartPosition.Manual
        form.Location = D.Point(*location)
        form.Size = D.Size(420, 300)
        first = F.Button()
        first.Text = u"first"
        first.Location = D.Point(10, 10)
        form.Controls.Add(first)
        tabs = F.TabControl()
        tabs.Location = D.Point(10, 50)
        tabs.Size = D.Size(380, 200)
        for i in range(2):
            page = F.TabPage()
            page.Text = u"page {0}".format(i)
            button = F.Button()
            button.Text = u"button {0}".format(i)
            page.Controls.Add(button)
            tabs.TabPages.Add(page)
        form.Controls.Add(tabs)
        holder = type("Holder", (object,), {})()
        holder.form = form

        def quiet(moment):
            """No focus, no foreground, still off the desktop."""
            place, focus = tw.screen_rules(holder)      # also WS_EX_NOACTIVATE
            if focus:
                tw.INVALID.append(u"probe, {0}: {1}".format(moment, u"; ".join(focus)))
            return r.check(u"probe quiet: " + moment, not (place or focus), place + focus)

        def live():
            ctypes, u, _k, _proc = _api()
            owner = ctypes.c_ulong(0)
            thread = u.GetWindowThreadProcessId(ctypes.c_void_p(form.Handle.ToInt64()),
                                                ctypes.byref(owner))
            ok = r.check("hook on the thread of the window", thread == trap.thread,
                         (thread, trap.thread))
            ok = r.check("hook live on this thread (windows created)", trap.live(),
                         trap.counts) and ok
            ok = r.check("no attempt before any step", not trap.attempts,
                         [describe(a) for a in trap.attempts]) and ok
            return quiet(u"shown") and ok

        def blocks():
            """The answer 1 refuses: a hidden top-level window of our own
            cannot be made. Never shown, harmless."""
            native = F.NativeWindow()
            params = F.CreateParams()
            params.Caption = u"probe, refused"
            failed = False
            trap.block_create = True
            try:
                native.CreateHandle(params)
            except Exception:
                failed = True
            finally:
                trap.block_create = False
            if not failed:
                native.DestroyHandle()
            return r.check("the hook's answer refuses (CreateWindowEx failed)",
                           failed and trap.blocked_create == 1, trap.blocked_create)

        def active_without_focus():
            n = len(trap.attempts)
            form.ActiveControl = first
            ok = r.check("ActiveControl set on an inactive form, no attempt",
                         form.ActiveControl is first and len(trap.attempts) == n,
                         [describe(a) for a in trap.attempts[n:]])
            box["n"] = n
            return quiet(u"active control set") and ok

        def dispose_active():
            n = box["n"]
            first.Dispose()
            new = trap.attempts[n:]
            text = u" ".join(u" ".join(a["frames"]) for a in new)
            ok = r.check("disposing the active control: attempt caught",
                         bool(new) and ("AfterControlRemoved" in text or
                                        "FocusActiveControlInternal" in text),
                         [describe(a) for a in new])
            ok = r.check("  made by code", all(a["origin"] == "code" for a in new),
                         [a["origin"] for a in new]) and ok
            return quiet(u"active control disposed") and ok

        def cleared_first():
            other = F.Button()
            other.Location = D.Point(120, 10)
            form.Controls.Add(other)
            form.ActiveControl = other
            form.ActiveControl = None
            n = len(trap.attempts)
            other.Dispose()
            ok = r.check("cleared first, then disposed: no attempt", len(trap.attempts) == n,
                         [describe(a) for a in trap.attempts[n:]])
            return quiet(u"cleared and disposed") and ok

        def tab_in_code():
            if not quiet(u"before the tab"):
                return False
            n = len(trap.attempts)
            tabs.SelectedIndex = 1          # focus: the known cause, under the trap
            new = trap.attempts[n:]
            text = u" ".join(u" ".join(a["frames"]) for a in new)
            ok = r.check("tab chosen in code: attempt caught", bool(new) and "TabControl" in text,
                         [describe(a) for a in new])
            return quiet(u"tab chosen") and ok

        box = {}
        steps = [live, blocks, active_without_focus, dispose_active, cleared_first,
                 tab_in_code]
        timer = F.Timer()
        timer.Interval = 150

        def tick(sender, args):
            try:
                if steps:
                    step = steps.pop(0)
                    done["step"] = step.__name__
                    trap.moment = step.__name__
                    if step() is not False:
                        return
                    r.check("probe stopped at " + step.__name__, False, u"")
                timer.Stop()
                form.Close()
            except Exception:
                r.check("probe step", False, traceback.format_exc())
                timer.Stop()
                form.Close()

        def shown(sender, args):
            timer.Start()
        timer.Tick += tick
        form.Shown += shown
        F.Application.Run(form)
        r.check("no error in the hook", not trap.errors, trap.errors[:2])
        done["attempts"] = [describe(a) for a in trap.attempts]
        done["counts"] = dict((str(k), v) for k, v in trap.counts.items())
    finally:
        trap.uninstall()
