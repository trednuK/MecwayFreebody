# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_all.py
# All panel tests, CPython 3: the logic here, then a hidden Mecway per part on
# self-made models in WorkDir/gui_test. The images of the window stay there, for
# a look; `--clean` removes that folder afterwards. Run it in the background: a
# hidden Mecway starts several times.
#   python tests/test_gui_all.py [logic compile real mesh trap window entry reopen nodes
#   shells real_run docs] [--clean]
# FB_CORE_DIR: folder of fb_core.py and fb_aster.py while they are not merged.

import io
import os
import re
import shutil
import subprocess
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, TESTS)
import test_gui_model as models  # noqa: E402
import test_gui_runner as runner  # noqa: E402

WORK = os.path.join(ROOT, "WorkDir", "gui_test")
MAIN = os.path.join(TESTS, "test_gui_mecway_main.py")
SHAPES = ("hex20", "tet10")
SOURCES = ("MecwayFreebody.py", "fb_mecway.py", "fb_gui.py", "fb_nodecut.py", "fb_docs.py")
from test_gui_focus import PROBE_TITLE  # noqa: E402
# Calls that focus or activate a window. In the panel they are allowed only on a
# line that says why with "# focus:" (the user started the script); in the tests
# only under the focus trap, on such a line too.
FOCUS_CALLS = re.compile(r"\.Focus\(|\.Select\(\)|SelectNextControl|SetForegroundWindow|"
                         r"SetActiveWindow|BringToFront|SelectTab\(|\.Activate\(|"
                         r"AttachThreadInput|RecreateHandle|ShowWindow\(|"
                         r"ShowDialog\(|SelectedTab\s*=(?!=)|tabs\.SelectedIndex\s*=(?!=)")


def focus_hits(text):
    """Lines with a focus call and no "# focus:" reason."""
    return [line.strip() for line in text.splitlines()
            if FOCUS_CALLS.search(line) and "# focus:" not in line]
PRIVATE = re.compile(r"[A-Za-z]:\\Users\\|/Users/|@[a-z0-9.-]+\.[a-z]{2,}", re.I)


def summary(name, result):
    lines = result.get("lines", [])
    watch = result.get("watch")
    if watch:
        print("{0}: runner {1} polls, at most {2} visible window(s), all off the desktop, "
              "foreground never ours".format(name, watch["polls"], watch["most_windows"]))
    bad = [line for line in lines if not line.startswith("OK")]
    print("{0}: {1} checks, {2} failed".format(name, len(lines), result.get("failed")))
    for line in bad:
        print("  " + line)
    return len(bad)


def run_logic():
    """The logic in CPython."""
    code = subprocess.call([sys.executable, os.path.join(TESTS, "test_gui_logic.py")])
    print("logic in CPython: exit {0}".format(code))
    return 1 if code else 0


def check_source():
    """Source rules that a compiler does not see."""
    failed = 0
    for name in SOURCES:
        with io.open(os.path.join(ROOT, "Scripts", name), encoding="utf-8") as f:
            text = f.read()
        for what, pattern in (("private path or address", PRIVATE),
                              ("mw.open", re.compile(r"\bmw\.open\b(?!\s*\.)")),
                              ("message box", re.compile(r"MessageBox\.")),
                              ("f-string", re.compile(r"(?<![\w*\"'])[fF][\"']")),
                              ("nonlocal", re.compile(r"^\s*nonlocal\b", re.M)),
                              ("g format", re.compile(r"%[.0-9]*g\b|:[.0-9]*g\}"))):
            hits = [m for m in pattern.finditer(text)]
            if what == "mw.open":
                hits = [h for h in hits if "never" not in text[max(0, h.start() - 40):h.start()]]
            if hits:
                failed += 1
                print("  FAIL {0}: {1}: {2!r}".format(name, what, hits[0].group(0)))
        if "Mozilla Public" not in text:
            failed += 1
            print("  FAIL {0}: licence header".format(name))
        hits = focus_hits(text)
        if hits:
            failed += 1
            print("  FAIL {0}: focus call without a reason: {1!r}".format(name, hits[0]))
    # Tests never touch the user's clipboard, focus or input; a focus call only
    # in the proof of the focus trap, which refuses it
    for name in sorted(os.listdir(os.path.join(ROOT, "tests"))):
        if not (name.startswith("test_gui") and name.endswith(".py")):
            continue
        with io.open(os.path.join(ROOT, "tests", name), encoding="utf-8") as f:
            text = f.read()
        if name == "test_gui_all.py":
            continue
        for what, pattern in (("clipboard", re.compile(r"Clipboard\.")),
                              ("input", re.compile(r"SendInput|keybd_event|mouse_event"))):
            hit = pattern.search(text)
            if hit:
                failed += 1
                print("  FAIL tests/{0}: {1}: {2!r}".format(name, what, hit.group(0)))
        hits = (focus_hits(text) if name == "test_gui_focus.py" else
                [line.strip() for line in text.splitlines() if FOCUS_CALLS.search(line)])
        if hits:
            failed += 1
            print("  FAIL tests/{0}: focus: {1!r}".format(name, hits[0]))
    # The tool that makes the images of the guide: the same rules as the tests
    tools = os.path.join(ROOT, "tools")
    for name in sorted(os.listdir(tools)) if os.path.isdir(tools) else []:
        if not name.endswith((".py", ".ps1")):
            continue
        with io.open(os.path.join(tools, name), encoding="utf-8") as f:
            text = f.read()
        for what, pattern in (("private path or address", PRIVATE),
                              ("clipboard", re.compile(r"Clipboard\.")),
                              ("focus", re.compile(r"SetForegroundWindow|\.Activate\(|\.Focus\(|"
                                                   r"BringToFront|\.Show\(|ShowDialog|"
                                                   r"Application\.Run\(|"
                                                   r"tabs\.SelectedIndex\s*=(?!=)|SelectTab\(")),
                              ("input", re.compile(r"SendInput|keybd_event|mouse_event"))):
            hit = pattern.search(text)
            if hit:
                failed += 1
                print("  FAIL tools/{0}: {1}: {2!r}".format(name, what, hit.group(0)))
        if "Mozilla Public" not in text:
            failed += 1
            print("  FAIL tools/{0}: licence header".format(name))
    print("source rules: {0} failed".format(failed))
    return failed


def env_base():
    env = {"FB_ROOT": ROOT, "PYTHONDONTWRITEBYTECODE": "1"}
    core = os.environ.get("FB_CORE_DIR")
    if core:
        env["FB_CORE_DIR"] = core
    return env


def window_env():
    """Folders and environment of the window parts: images, runs, a stand-in for
    Code-Aster."""
    png = os.path.join(WORK, "png")
    runs = os.path.join(WORK, "runs")
    exe = os.path.join(WORK, "17.4", "bin", "run_aster.bat")
    for folder in (png, runs, os.path.dirname(exe)):
        if not os.path.isdir(folder):
            os.makedirs(folder)
    with io.open(exe, "w", encoding="ascii") as f:
        f.write(u"rem stand-in\n")
    select = " ".join(str(e) for e in range(9, 13))
    return {"FB_PNG": png, "FB_RUNS": runs, "FB_EXE": exe, "FB_SELECT": select}


def in_mecway(model, test, extra=None, timeout=240, allowed=()):
    env = env_base()
    env["FB_TEST"] = test
    env.update(extra or {})
    result = os.path.join(WORK, "r_{0}.json".format(test))
    return runner.run_script(model, MAIN, result, env, timeout, allowed)


def models_ready():
    """A solved block per shape; returns {shape: (solved path, json path)}."""
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    out = {}
    for shape in SHAPES:
        m, low, high = models.block(shape, cells=(5, 2, 2))
        base = os.path.join(WORK, shape + ".liml")
        data = base + ".json"
        if shape.startswith("hex"):
            models.write_liml(base, m, low, high, json_path=data)
        else:
            models.write_liml(base, m, json_path=data)
        out[shape] = (base, data)
    solved = os.path.join(WORK, "hex20_solved.liml")
    r = in_mecway(out["hex20"][0], "solve", {"FB_SOLVED": solved})
    if summary("solve", r) or not os.path.isfile(solved):
        raise RuntimeError("no solved model")
    out["hex20"] = (solved, out["hex20"][1])
    return out


def real_run():
    """The panel with real Code-Aster, on the base of E9's model c_lin (the
    folder of that model in FB_E2E). Skipped without it."""
    root = os.environ.get("FB_E2E")
    model = os.path.join(root or "", "c_lin.liml")
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4",
                       "bin", "run_aster.bat")
    if not (root and os.path.isfile(model) and os.path.isfile(exe)):
        print("real run: skipped (FB_E2E or Code-Aster missing)")
        return 0
    png = os.path.join(WORK, "png_run")
    if not os.path.isdir(png):
        os.makedirs(png)
    env = {"FB_PNG": png, "FB_RUNS": os.path.join(root, "c_lin"), "FB_EXE": exe}
    panel = ("MecwayFreebody",)
    result = in_mecway(model, "real_run", env, timeout=400, allowed=panel)
    print("real run: follow-up {0} s".format(result.get("seconds")))
    failed = summary("real run, no solution", result)
    solved = solved_by_bridge(model, os.path.join(root, "c_lin"))
    if not solved:
        print("arrows on a solution of the bridge: skipped (FB_BRIDGE)")
        return failed
    env["FB_SOLVED_MODEL"] = "1"
    result = in_mecway(solved, "real_run", env, timeout=400, allowed=panel)
    print("  arrows: {0}".format(result.get("arrow_text")))
    return failed + summary("real run, solution of the bridge", result)


def shells():
    """Phase 4: shell thickness through the real mw on a self-made plate with a
    rib, then the window with shell, beam and mixed cuts made by hand. The
    images go to WorkDir/gui_test/png_shells."""
    folder = os.path.join(WORK, "shells")
    png = os.path.join(WORK, "png_shells")
    runs = os.path.join(folder, "runs")
    exe = os.path.join(folder, "17.4", "bin", "run_aster.bat")
    for path in (png, runs, os.path.dirname(exe)):
        if not os.path.isdir(path):
            os.makedirs(path)
    with io.open(exe, "w", encoding="ascii") as f:
        f.write(u"rem stand-in\n")
    model = os.path.join(folder, "plate.liml")
    models.write_shell_liml(model, loads=True)
    env = {"FB_PNG": png, "FB_RUNS": runs, "FB_EXE": exe}
    result = in_mecway(model, "shells", env, allowed=("MecwayFreebody",))
    print("  Mecway: geometric type {0}, thickness {1}".format(
        result.get("geometric"), result.get("thickness_raw")))
    print("  moments read: {0}".format(result.get("moments")))
    return summary("shells", result)


def solved_by_bridge(model, run_folder):
    """A copy of the model with the results of its run in it, as the bridge
    writes them back. FB_BRIDGE: the Scripts folder of the bridge."""
    bridge = os.environ.get("FB_BRIDGE")
    names = [n for n in os.listdir(run_folder) if n.endswith("_results.xml")]
    if not bridge or not names:
        return None
    out = os.path.join(WORK, "solved", "c_lin.liml")
    os.makedirs(os.path.dirname(out))
    env = {"FB_BRIDGE": bridge, "FB_SOLVED": out,
           "FB_FRAGMENT": os.path.join(run_folder, names[0])}
    summary("splice", in_mecway(model, "splice", env))
    return out if os.path.isfile(out) else None


def main():
    words = [a for a in sys.argv[1:] if not a.startswith("--")]
    parts = words or ["logic", "compile", "real", "mesh", "window", "entry", "reopen", "nodes",
                      "shells", "real_run", "docs"]
    failed = check_source()
    if "logic" in parts:
        failed += run_logic()
    ready = models_ready()
    if "logic" in parts:
        failed += summary("logic in IronPython", in_mecway(ready["hex20"][0], "logic"))
    if "compile" in parts:
        failed += summary("compile", in_mecway(ready["hex20"][0], "compile"))
    if "real" in parts:
        # hex20: one slice of a 5-cell bar, cut of 20 x 40 mm; the tet10 model
        # has no solution, so only what reads the mesh runs on it
        select = " ".join(str(e) for e in range(9, 13))
        env = {"FB_EXPECT": ready["hex20"][1], "FB_SELECT": select, "FB_AREA": "0.0008",
               "FB_SAVED": os.path.join(WORK, "hex20_saved.liml")}
        failed += summary("real mw", in_mecway(ready["hex20"][0], "real", env))
        with io.open(env["FB_SAVED"], encoding="utf-8", errors="replace") as f:
            saved = set(re.findall(r'<nodevariable name="([^"]+)"', f.read()))
        missing = {"externalforcex", "reactionmomz"} - saved
        print("fields in the saved file: {0}".format("all there" if not missing else missing))
        failed += len(missing)
    if "mesh" in parts:
        # tet10: 6 elements per cell, 4 cells in a slice; no load, not solved
        select = " ".join(str(e) for e in range(2 * 24 + 1, 3 * 24 + 1))
        env = {"FB_EXPECT": ready["tet10"][1], "FB_SELECT": select, "FB_AREA": "0.0008"}
        failed += summary("tet10 mesh", in_mecway(ready["tet10"][0], "mesh", env))
    windows = ("window", "entry", "reopen", "nodes", "shells", "real_run", "docs")
    if "trap" in parts or any(p in parts for p in windows):
        # first the focus trap on a window of its own: without a proof that it
        # catches and refuses, no window part runs
        trap = in_mecway(ready["hex20"][0], "trap", window_env(),
                         allowed=(PROBE_TITLE,))
        if summary("focus trap", trap):
            print("STOPPED: the focus trap is not proven; no window part runs")
            return 1 + failed
    if any(p in parts for p in ("window", "entry", "reopen", "nodes")):
        env = window_env()
        panel = ("MecwayFreebody",)
        for part in ("window", "entry", "reopen", "nodes"):
            if part in parts:
                result = in_mecway(ready["hex20"][0], part, env, allowed=panel)
                failed += summary(part, result)
                if part == "reopen":
                    print("  mw.open closes the window: {0}".format(result.get("reason")))
    if "shells" in parts:
        failed += shells()
    if "real_run" in parts:
        failed += real_run()
    if "docs" in parts:
        # last: the browser element of the tab is the newest piece in the window
        failed += summary("docs", in_mecway(ready["hex20"][0], "docs", window_env(),
                                            allowed=("MecwayFreebody",)))
    if "--clean" in sys.argv:
        shutil.rmtree(WORK)
    print("TOTAL FAILED: {0}".format(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (runner.InvalidRun, runner.WindowOnScreen) as e:
        # a hard rule broken: stop the whole set, nothing after this counts
        print("STOPPED, RUN INVALID: {0}".format(e))
        sys.exit(3)
