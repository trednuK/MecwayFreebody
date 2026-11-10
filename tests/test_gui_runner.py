# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_runner.py
# Runs a script in a hidden Mecway: `mecway.exe <model> script <file>`, CPython
# 3. Checks every file before Mecway starts, watches the visible windows of its
# own process tree and kills only that tree. It does not touch any other Mecway.
# Scripts get their input through environment variables and write a JSON
# result; a run without that file counts as failed.
#
# Hard rules, checked on every poll (0.1 s) and once more after the run:
# - no visible window of the tree may touch the virtual desktop (all monitors);
#   such a window kills the tree at once (WindowOnScreen);
# - the foreground window may never belong to the tree or to this process;
#   that makes the run INVALID (InvalidRun): the caller must stop the whole set.
# Limits: a window that lives shorter than one poll is not seen; a crash dialog
# of the Windows error service (WerFault) is not in the tree; Windows itself may
# move an off-screen window onto a monitor on a display change.

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import time

MECWAY = os.environ.get("FB_MECWAY", r"C:\Program Files\Mecway\mecway.exe")
POLL = 0.1
CREATE_NO_WINDOW = 0x08000000
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _dpi_aware():
    """Physical pixels for both the window rectangles and the desktop, before
    any other user32 call caches scaled metrics. Only this process."""
    try:
        _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        _user32.SetProcessDPIAware()
    except AttributeError:
        pass


_dpi_aware()
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]


class WindowOnScreen(RuntimeError):
    """A window of the tree stood on the visible desktop."""


class InvalidRun(RuntimeError):
    """The foreground window belonged to the tree or to this process: the
    whole test set is invalid and must stop."""


class _Entry(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _processes():
    """{pid: parent pid} of all processes (a Toolhelp snapshot); {} without one."""
    _kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = _kernel32.CreateToolhelp32Snapshot(2, 0)        # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return {}
    out = {}
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        ok = _kernel32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = _kernel32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(ctypes.c_void_p(snap))
    return out


def ancestors(pid):
    """The parent chain of pid, nearest first."""
    parent_of = _processes()
    out = []
    while pid in parent_of and parent_of[pid] not in out and parent_of[pid] != pid:
        pid = parent_of[pid]
        out.append(pid)
    return out


def tree(pid):
    """pid and all its descendants (a Toolhelp snapshot)."""
    parent_of = _processes()
    if not parent_of:
        return {pid}
    parents = {}
    for child, parent in parent_of.items():
        parents.setdefault(parent, []).append(child)
    out, todo = set(), [pid]
    while todo:
        p = todo.pop()
        if p not in out:
            out.add(p)
            todo.extend(c for c in parents.get(p, ()) if c != p)
    return out


def desktop():
    """The virtual desktop, all monitors: (left, top, right, bottom)."""
    left, top = _user32.GetSystemMetrics(76), _user32.GetSystemMetrics(77)
    return (left, top, left + _user32.GetSystemMetrics(78),
            top + _user32.GetSystemMetrics(79))


def intersects(rect, area):
    return rect[0] < area[2] and area[0] < rect[2] and rect[1] < area[3] and area[1] < rect[3]


def own_windows(pids):
    """(title, rect, pid) of the visible top-level windows of these processes."""
    pids = {pids} if isinstance(pids, int) else set(pids)
    found = []

    def visit(hwnd, _):
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and _user32.IsWindowVisible(hwnd):
            text = ctypes.create_unicode_buffer(200)
            _user32.GetWindowTextW(hwnd, text, 200)
            r = wt.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((text.value, (r.left, r.top, r.right, r.bottom), owner.value))
        return True
    _user32.EnumWindows(_ENUM(visit), 0)
    return found


def foreground():
    """(pid, title) of the foreground window; (None, u"") without one."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None, u""
    owner = wt.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    text = ctypes.create_unicode_buffer(200)
    _user32.GetWindowTextW(hwnd, text, 200)
    return owner.value, text.value


def _kill(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


def _check_foreground(pids, moment, history=None):
    pid, title = foreground()
    if pid is not None and (pid in pids or pid == os.getpid()):
        if history is not None:
            history.sample(pids)
        raise InvalidRun(u"INVALID: foreground window {0!r} (pid {1}) {2}{3}".format(
            title, pid, moment, u"; " + history.text() if history is not None else u""))


class ForegroundLog(object):
    """The foreground window over the run, without the titles of other
    programs: (seconds, kind, hwnd), kind "tree", "runner", "ancestor" or
    "other", the last HISTORY changes. On an invalid run it says which of the
    earlier foreground windows still exist: one that is gone points to Windows
    activating the next window when the foreground window closed."""
    HISTORY = 20

    def __init__(self):
        _kernel32.GetConsoleWindow.restype = wt.HWND
        _user32.IsWindow.argtypes = [wt.HWND]
        self.started = time.time()
        self.above = set(ancestors(os.getpid()))
        self.changes = []
        hwnd = _user32.GetForegroundWindow()
        self.start = self._kind(hwnd, set())
        console = _kernel32.GetConsoleWindow()
        self.start_console = bool(console) and console == hwnd

    def _kind(self, hwnd, pids):
        if not hwnd:
            return "none"
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids:
            return "tree"
        if owner.value == os.getpid():
            return "runner"
        return "ancestor" if owner.value in self.above else "other"

    def sample(self, pids):
        hwnd = _user32.GetForegroundWindow()
        value = hwnd or 0
        if not self.changes or self.changes[-1][2] != value:
            self.changes.append((round(time.time() - self.started, 1), self._kind(hwnd, pids),
                                 value))
            del self.changes[:-self.HISTORY]

    def text(self):
        rows = [u"{0} s {1}{2}".format(t, kind, u"" if not hwnd or _user32.IsWindow(hwnd)
                                        else u" (gone now)")
                for t, kind, hwnd in self.changes]
        return u"at the start: {0}{1}; foreground since: {2}".format(
            self.start, u", the runner's console" if self.start_console else u"",
            u", ".join(rows))


def run_script(model, script, result, env=None, timeout=120, allowed=()):
    """Run script on model in a hidden Mecway; returns the JSON in result, with
    "watch": what the runner saw. allowed: titles of windows that may be
    visible off-screen (the panel's own test window). Raises WindowOnScreen,
    InvalidRun, or RuntimeError on a dialog, a timeout or a missing result."""
    for path in (MECWAY, model, script):
        if not os.path.isfile(path) or not os.path.isabs(path):
            raise RuntimeError("missing or relative: {0}".format(path))
    if os.path.exists(result):
        os.remove(result)
    full = dict(os.environ)
    full["FB_RESULT"] = result
    full.update(env or {})
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    _check_foreground(set(), "before the start")
    history = ForegroundLog()
    proc = subprocess.Popen([MECWAY, model, "script", script], env=full,
                            startupinfo=info)
    started = time.time()
    seen = None
    watch = {"polls": 0, "most_windows": 0, "titles": []}
    pids = {proc.pid}
    try:
        while proc.poll() is None:
            pids = tree(proc.pid)       # now: a dead child's number may be reused
            history.sample(pids)
            area = desktop()
            windows = own_windows(pids)
            watch["polls"] += 1
            watch["most_windows"] = max(watch["most_windows"], len(windows))
            for title, rect, pid in windows:
                if title not in watch["titles"]:
                    watch["titles"].append(title)
                if intersects(rect, area):
                    raise WindowOnScreen(u"window on the screen after {0:.1f} s: {1!r} {2} "
                                         u"pid {3}, desktop {4}".format(
                                             time.time() - started, title, rect, pid, area))
            _check_foreground(pids, u"after {0:.1f} s".format(time.time() - started), history)
            other = [t for t, _, _ in windows if t not in allowed]
            if other:
                seen = seen or time.time()
                if time.time() - seen > 5:
                    raise RuntimeError("window of Mecway: {0!r}".format(other))
            if time.time() - started > timeout:
                raise RuntimeError("timeout after {0} s".format(timeout))
            time.sleep(POLL)
    finally:
        if proc.poll() is None:
            _kill(proc.pid)
    _check_foreground(pids, "after the run", history)
    if not os.path.isfile(result):
        raise RuntimeError("no result file from {0}".format(script))
    with open(result, encoding="utf-8") as f:
        out = json.load(f)
    if out.get("invalid"):
        raise InvalidRun(u"INVALID inside Mecway: {0}; {1}".format(out["invalid"], history.text()))
    out["watch"] = watch
    return out
