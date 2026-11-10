# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# ipy_inner.py
# Runs inside Mecway's IronPython: started by test_core_ipy.py through a hidden
# mecway.exe <model> script <this file>. It never talks to the screen. Each step
# is caught and written to the JSON of the configuration, so the run always
# ends. Configuration: path in the environment variable FB_IPY_CFG.

import json
import os
import sys
import time
import traceback

CFG = json.load(open(os.environ["FB_IPY_CFG"]))
OUT = {}


def save():
    text = json.dumps(OUT, sort_keys=True, indent=1)
    with open(CFG["out"], "w") as f:
        f.write(text)


def step(name, fn):
    t0 = time.time()
    try:
        OUT[name] = fn()
    except BaseException:
        OUT[name + "_error"] = traceback.format_exc().encode("ascii", "replace").decode("ascii")
    OUT[name + "_seconds"] = time.time() - t0
    save()


def environment():
    return {"version": sys.version, "repr": repr(0.3), "g": "%g" % 0.5, "e": "%.3e" % 0.5,
            "mecway": str(mw.version())}


def unit_tests():
    import unittest
    try:
        from StringIO import StringIO
    except ImportError:
        from io import StringIO
    sys.path.insert(0, CFG["tests"])
    sys.path.insert(0, CFG["scripts"])
    os.environ["FB_TESTS"] = CFG["tests"]
    import test_core
    import test_aster
    out = {}
    for module in (test_core, test_aster):
        stream = StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        out[module.__name__] = {
            "run": result.testsRun, "failures": len(result.failures),
            "errors": len(result.errors), "skipped": len(getattr(result, "skipped", ())),
            "detail": [(str(t), s.encode("ascii", "replace").decode("ascii")[-900:])
                       for t, s in (result.failures + result.errors)[:12]]}
    out["speed"] = test_core.SPEED
    return out


def read_mesh():
    """The mesh as the panel will read it, through Mecway's API."""
    nodes = {}
    for n in mw.all_nodes():
        p = mw.node(n)
        nodes[int(n)] = (float(p.x), float(p.y), float(p.z)) if hasattr(p, "x") else tuple(float(v) for v in p)
    elements = {}
    component = {}
    for e in mw.all_elements():
        elements[int(e)] = (str(mw.element_shape(e)), [int(q) for q in mw.nodes(e)])
        component[int(e)] = mw.element_component(e)
    return {"nodes": nodes, "elements": elements, "component": component}


MESH = {}


def fingerprint():
    import fb_aster
    MESH.update(read_mesh())
    got = fb_aster.mesh_fingerprint(MESH["nodes"], list(MESH["elements"]))
    return {"got": got, "want": CFG["fingerprint"], "nodes": len(MESH["nodes"]),
            "elements": len(MESH["elements"]),
            "components": sorted(set(MESH["component"].values()))}


def real_run(folder):
    """A follow-up run from IronPython; the sums per cut and step."""
    import fb_aster
    import fb_core
    runs = fb_aster.find_runs(folder, CFG["fingerprint"])
    man = runs[0]
    reason = fb_aster.refuse(man, CFG["version"])
    if reason:
        return {"refused": reason}
    xmin = CFG["select"][0]
    xmax = CFG["select"][1]
    chosen = []
    for e, (shape, nids) in MESH["elements"].items():
        x = sum(MESH["nodes"][n][0] for n in nids) / len(nids)
        if xmin < x < xmax:
            chosen.append(e)
    plan = fb_core.plan_cuts(MESH, chosen)
    t0 = time.time()
    job = fb_aster.start(man, folder, plan, MESH, CFG["exe"], folder)
    started = time.time() - t0
    work = job.work
    while job.poll() is None:
        if time.time() - t0 > 180:
            job.stop()
        time.sleep(0.05)
    if not job.poll():
        return {"error": job.error().encode("ascii", "replace").decode("ascii")}
    t1 = time.time()
    result = job.result()
    t2 = time.time()
    per = fb_core.assign_nodes(plan, MESH, result)
    sums = {}
    for rank in result["forces"]:
        pos = fb_core.positions(result, rank)
        for group in plan["groups"]:
            geo = fb_core.section_geometry(MESH, group)
            idx = per[group["id"]]
            s = fb_core.resultant([pos[i] for i in idx],
                                  [result["forces"][rank][i] for i in idx], geo["centroid"])
            sums["{0}_{1}".format(rank, group["id"])] = list(s)
    # the check of a stale base, on the numbers of the run itself
    last = result["steps"][-1]["rank"]
    values = dict((r["nid"], u) for r, u in zip(result["nodes"], result["disp"][last]))
    stale = [fb_aster.check_solution(result, None, values),
             fb_aster.check_solution(result, None, dict((n, (0.1, 0.2, 0.3)) for n in values))]
    end = time.time() + 20
    while os.path.exists(work) and time.time() < end:
        time.sleep(0.1)
    return {"sums": sums, "start_seconds": started, "seconds": result["seconds"],
            "decode_seconds": t2 - t1, "left_behind": os.path.exists(work), "stale": stale,
            "cut_nodes": len(result["nodes"]), "rest": result["rest"][4]["largest"]}


def face_tables():
    """The tables of fb_core against Mecway itself, for all eight shapes."""
    import fb_core
    import test_core
    b = test_core.Builder()
    wrong = []
    notes = []
    checked = 0
    made = {}
    for i, shape in enumerate(fb_core.SOLID_SHAPES):
        made[shape] = test_core.fill_cell(b, shape, (10.0 + 2 * i, 0.0, 0.0), (1.0, 1.0, 1.0))[0]
    ids = {}
    for n, p in b.mesh["nodes"].items():
        ids[n] = int(mw.new_node(Vector(p[0], p[1], p[2])))
    component = sorted(set(MESH["component"].values()))[0]
    for shape, e in made.items():
        nids = [ids[n] for n in b.mesh["elements"][e][1]]
        eid = int(mw.new_element(shape, nids, component))
        if str(mw.element_shape(eid)) != shape:
            wrong.append((shape, "shape", str(mw.element_shape(eid))))
        try:
            if float(mw.volume(eid)) <= 0:
                wrong.append((shape, "volume"))
        except Exception as e_volume:
            notes.append("volume: {0}".format(type(e_volume).__name__))
        got_nodes = [int(q) for q in mw.nodes(eid)]
        if got_nodes != nids:
            wrong.append((shape, "node order"))
        for f in range(1, len(fb_core._FAMILIES[shape][0]) + 1):
            local = fb_core.face_local_nodes(shape, f)
            want = set(nids[i] for i in local)
            got = set(int(q) for q in mw.face_nodes(FaceId(eid, f)))
            checked += 1
            if got != want:
                # a linear description of a quadratic face also tells something
                corners = set(nids[i] for i in fb_core._FAMILIES[shape][0][f - 1])
                wrong.append((shape, f, sorted(got), sorted(want), got == corners))
    return {"checked": checked, "wrong": wrong[:20], "notes": sorted(set(notes))}


def finish():
    mw.save_as(CFG["save_as"])
    return True


step("environment", environment)
step("unit", unit_tests)
step("fingerprint", fingerprint)
for key, folder in sorted(CFG["folders"].items()):
    step("run_" + key, lambda folder=folder: real_run(folder))
step("faces", face_tables)
step("finish", finish)
OUT["done"] = True
save()
