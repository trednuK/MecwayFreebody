# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_core_ipy.py
# The core in Mecway's own IronPython: the unit tests, the speed, a real
# follow-up run on a self-made model, and the face tables against Mecway. One
# controlled run of a hidden mecway.exe <model> script <file>, only on request:
#   FB_RUN_MECWAY=1 python -m unittest tests.test_core_ipy
# Never starts when Mecway is already running. Watches the windows of its own
# process and kills only that process, on a dialog or a timeout.

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, HERE)
import test_aster_e2e as e2e

MECWAY = os.environ.get("FB_MECWAY", r"C:\Program Files\Mecway\mecway.exe")
WANTED = os.environ.get("FB_RUN_MECWAY") == "1"
TIMEOUT = 900.0
DIALOG_SECONDS = 5.0


def visible_windows(pid):
    """Titles of the visible top-level windows of a process. Read only."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(handle, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(handle):
            title = ctypes.create_unicode_buffer(200)
            user32.GetWindowTextW(handle, title, 200)
            found.append(title.value)
        return True
    user32.EnumWindows(callback_type(callback), 0)
    return found


def console_windows():
    """Handles of visible console windows on the desktop. Read only."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(handle, _):
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(handle, name, 64)
        if user32.IsWindowVisible(handle) and name.value in (
                "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
            found.add(handle)
        return True
    user32.EnumWindows(callback_type(callback), 0)
    return found


def mecway_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mecway.exe"], capture_output=True,
                         text=True).stdout
    return "mecway.exe" in out.lower()


def kill(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def run_hidden(model, script, cfg_path):
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    env = dict(os.environ, FB_IPY_CFG=cfg_path)
    process = subprocess.Popen([MECWAY, model, "script", script], env=env, startupinfo=info)
    t0 = time.time()
    seen = None
    consoles = console_windows()
    new_consoles = set()
    while process.poll() is None:
        new_consoles |= console_windows() - consoles
        windows = visible_windows(process.pid)
        if windows:
            seen = seen or time.time()
            if time.time() - seen > DIALOG_SECONDS:
                kill(process.pid)
                raise RuntimeError("window of Mecway: {0!r}".format(windows))
        else:
            seen = None
        if time.time() - t0 > TIMEOUT:
            kill(process.pid)
            raise RuntimeError("timeout")
        time.sleep(0.25)
    return time.time() - t0, len(new_consoles)


@unittest.skipUnless(WANTED and e2e.available("c_nl") and e2e.available("c_lin") and
                     os.path.isfile(MECWAY), "only on request, with bases and Mecway")
class InMecway(unittest.TestCase):
    def test_all(self):
        self.assertFalse(mecway_running(), "Mecway is running: not now")
        work = tempfile.mkdtemp(prefix="fbipy_")
        self.addCleanup(shutil.rmtree, work, True)
        case = e2e.Case("c_nl")
        # The same model in Mecway, the same base in strange folders
        model = os.path.join(work, "model.liml")
        shutil.copy(os.path.join(e2e.find_case("c_lin"), "c_lin.liml"), model)
        folders = {}
        for key, name in (("latin", u"sp\u00e4tie m\u00e9t"), ("greek", u"griek \u03a9 \u0416 run")):
            folder = os.path.join(work, name)
            os.makedirs(folder)
            shutil.copytree(os.path.join(case.folder, case.man["base"]),
                            os.path.join(folder, case.man["base"]))
            for n in os.listdir(case.folder):
                if n.endswith("_manifest.json"):
                    shutil.copy(os.path.join(case.folder, n), folder)
            folders[key] = folder
        # The numbers of the same run in CPython
        job = case.run()
        self.assertTrue(job.poll(), job.error())
        import fb_core
        result = job.result()
        per = fb_core.assign_nodes(case.plan, case.mesh, result)
        want = {}
        for rank in result["forces"]:
            pos = fb_core.positions(result, rank)
            for g in case.plan["groups"]:
                idx = per[g["id"]]
                want["{0}_{1}".format(rank, g["id"])] = fb_core.resultant(
                    [pos[i] for i in idx], [result["forces"][rank][i] for i in idx],
                    case.geo[g["id"]]["centroid"])
        out = os.path.join(work, "out.json")
        cfg = {"out": out, "tests": HERE, "scripts": os.path.join(ROOT, "Scripts"),
               "exe": e2e.EXE, "version": e2e.VERSION, "fingerprint": case.man["fingerprint"],
               "folders": folders, "select": [0.05 - 1e-9, 0.15],
               "save_as": os.path.join(work, "saved.liml")}
        cfg_path = os.path.join(work, "cfg.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        script = os.path.join(work, "inner.py")
        shutil.copy(os.path.join(HERE, "ipy_inner.py"), script)
        compile(open(script, encoding="utf-8").read(), script, "exec")
        seconds, consoles = run_hidden(model, script, cfg_path)
        self.assertTrue(os.path.isfile(out), "no result of the script")
        with open(out) as f:
            d = json.load(f)
        keep = os.environ.get("FB_IPY_REPORT")
        if keep:
            shutil.copy(out, keep)
        sys.stderr.write("Mecway run: {0:.0f} s, new console windows: {1}\n".format(seconds, consoles))
        self.assertEqual(consoles, 0)
        errors = dict((k, v) for k, v in d.items() if k.endswith("_error"))
        self.assertEqual(errors, {})
        self.assertTrue(d.get("done"))
        unit = d["unit"]
        sys.stderr.write(json.dumps(unit["speed"], sort_keys=True, indent=0) + "\n")
        sys.stderr.write("{0}\n".format(d["environment"]))
        for name in ("test_core", "test_aster"):
            self.assertEqual((unit[name]["failures"], unit[name]["errors"]), (0, 0),
                             json.dumps(unit[name]["detail"], indent=0))
        self.assertEqual(d["fingerprint"]["got"], d["fingerprint"]["want"])
        for key in folders:
            run = d["run_" + key]
            self.assertFalse(run.get("error") or run.get("refused"), str(run))
            self.assertFalse(run["left_behind"])
            self.assertEqual(run["stale"], [None, "stale"])
            self.assertEqual(sorted(run["sums"]), sorted(want))
            for name, values in run["sums"].items():
                for a, b in zip(values, want[name]):
                    self.assertTrue(abs(a - b) <= 1e-7 * max(1.0, abs(b)), (name, a, b))
        self.assertEqual(d["faces"]["wrong"], [], str(d["faces"]))
        self.assertTrue(d["faces"]["checked"] >= 38)


if __name__ == "__main__":
    unittest.main()
