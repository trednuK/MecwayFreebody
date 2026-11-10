# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# solids_build.py
# Makes the bases of test_solids_e2e.py through the real bridge code, without
# Mecway: .liml, bridge with keep_base, Code-Aster, manifest. The bridge is only
# read: no bytecode there, and Code-Aster's temporary folder stays in the work
# folder too.
#   python -B tests/solids_build.py <bridge folder> <work folder> [tags]
# Without tags: all models but the two large ones. Base of a tag: <work>\<tag>,
# next to <work>\<tag>.liml.

import io
import json
import os
import shutil
import subprocess
import sys
import time

CREATE_NO_WINDOW = 0x08000000
RUN_ID = "20261107_120000"
ASTER_TIMEOUT = 5400

POST_COMM = r"""POURSUITE(LANG='EN')
import numpy as fb_np


def fb_field(field, count):
    simple = field.toSimpleFieldOnNodes()
    values, mask = simple.toNumpy()
    names = list(simple.getComponents())
    out = fb_np.zeros((count, 3))
    for i, name in enumerate(("DX", "DY", "DZ")):
        if name in names:
            q = names.index(name)
            out[:, i] = fb_np.where(mask[:, q], values[:, q], 0.0)
    return out


FBM = res.getMesh()
fb_count = FBM.getNumberOfNodes()
fb_rs = CALC_CHAMP(RESULTAT=res, FORCE='REAC_NODA')
fb_arrays = {"xyz": fb_np.asarray(FBM.getCoordinates().getValues(), dtype=float).reshape(-1, 3)}
for fb_k in [int(k) for k in res.getIndexes()]:
    fb_arrays["U_%d" % fb_k] = fb_field(res.getField("DEPL", fb_k), fb_count)
    fb_arrays["R_%d" % fb_k] = fb_field(fb_rs.getField("REAC_NODA", fb_k), fb_count)
with open("fort.34", "wb") as fb_f:
    fb_np.savez(fb_f, **fb_arrays)
FIN()
"""


def run_bridge(bridge, work, liml, cfg_path):
    """In a process of its own: the settings of the bridge are module globals."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.join(bridge, "Scripts"))
    with io.open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    model = os.path.join(work, os.path.basename(liml))
    shutil.copy(liml, model)
    import bridge_utils as u
    u.CONFIG_BRIDGE["work_dir"] = work
    u.CONFIG_BRIDGE["language"] = "en"
    u.CONFIG_BRIDGE.update(cfg["general"])
    analysis = cfg["analysis"]
    u.CONFIG_BRIDGE["analyses"][analysis].update(cfg["settings"])
    u.CONFIG_BRIDGE["active_analysis"] = analysis
    u.set_run_log(RUN_ID, model)
    from bridge_from_liml import extract_aster_data_from_liml
    from bridge_mesh import write_mesh
    from bridge_to_aster import generate_AsterSolver_files
    import bridge_manifest
    md = extract_aster_data_from_liml(model)
    mail = os.path.join(work, u.run_name(".mail"))
    if not (md and write_mesh(mail, md)):
        sys.exit("mesh failed")
    exp = generate_AsterSolver_files(work, md, mail, u.run_name(".resu"))
    if not exp:
        sys.exit("generate failed: see the log")
    with open(os.path.join(work, u.run_name("_console.txt")), "w") as f:
        rc = subprocess.call([u.exe_aster_path(), exp], stdout=f, stderr=subprocess.STDOUT,
                             timeout=ASTER_TIMEOUT, creationflags=CREATE_NO_WINDOW)
    print("run_aster exit", rc)
    print("manifest", bridge_manifest.finish_run(work, md, exp, rc == 0))


def post(exe, folder, man, temp):
    """All nodes of a base: displacement and reaction per rank, in post.npz."""
    work = os.path.join(folder, "post")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    with open(os.path.join(work, "post.comm"), "w", newline="\n") as f:
        f.write(POST_COMM)
    lines = ["P actions make_etude", "P time_limit 3000",
             "P memory_limit %d" % max(man.get("memory_limit") or 2048, 2048),
             "P mpi_nbcpu 1", "P ncpus 2", "P no-mpi true", "F comm post.comm D 1",
             "F mess post.mess R 6", "F libr post.npz R 34",
             "R base %s D 0" % os.path.join(folder, man["base"])]
    with open(os.path.join(work, "post.export"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    env = dict(os.environ, TEMP=temp, TMP=temp)
    with open(os.path.join(work, "console.txt"), "w") as f:
        rc = subprocess.call('cmd /c ""{0}" post.export"'.format(exe), cwd=work, env=env, stdout=f,
                             stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
    done = os.path.join(work, "post.npz")
    if rc != 0 or not os.path.isfile(done):
        print("post failed", rc)
        return False
    shutil.move(done, os.path.join(folder, "post.npz"))
    shutil.rmtree(work, True)
    return True


def build(bridge, work, tag, exe):
    import fb_aster
    import solids_models as sm
    model = sm.MODELS[tag](tag)
    os.makedirs(work, exist_ok=True)
    liml = os.path.join(work, tag + ".liml")
    model.write(liml)
    cfg = json.loads(sm.settings_json(model))
    cfg["analysis"] = "nonlin_static_3d" if model.steps else "lin_static_3d"
    cfg_path = os.path.join(work, tag + "_cfg.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    temp = os.path.join(work, "tmp")
    os.makedirs(temp, exist_ok=True)
    env = dict(os.environ, TEMP=temp, TMP=temp, PYTHONDONTWRITEBYTECODE="1")
    folder = os.path.join(work, tag)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--one", bridge, folder,
                        liml, cfg_path], env=env, capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    seconds = time.time() - t0
    runs = fb_aster.find_runs(folder, None)
    state = "ok" if runs else "NO BASE"
    size = 0
    if runs:
        base = os.path.join(folder, runs[0]["base"])
        size = sum(os.path.getsize(os.path.join(base, n)) for n in os.listdir(base)) / 1e6
    print("%-8s %-7s %6.0f s, %6d elements, base %.0f MB %s" % (
        tag, state, seconds, len(model.elements), size, r.stdout.strip()[-60:].replace("\n", " ")))
    if not runs:
        print(r.stderr[-400:])
    elif tag in sm.NEEDS_POST:
        t0 = time.time()
        print("  post", post(exe, folder, runs[0], temp), "%.0f s" % (time.time() - t0))
    sys.stdout.flush()


def main():
    if sys.argv[1] == "--one":
        run_bridge(*sys.argv[2:6])
        return
    sys.dont_write_bytecode = True
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import solids_models as sm
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4", "bin",
                       "run_aster.bat")
    bridge, work = sys.argv[1:3]
    tags = sys.argv[3:] or [t for t in sorted(sm.MODELS) if not t.startswith("k_")]
    for tag in tags:
        build(bridge, os.path.abspath(work), tag, exe)


if __name__ == "__main__":
    main()
