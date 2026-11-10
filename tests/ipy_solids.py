# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# ipy_solids.py
# Runs inside Mecway's IronPython: started by test_solids_e2e.py through a hidden
# mecway.exe <model> script <this file>. A follow-up run on about 20 000 elements
# as the panel will do it, with the time of every part. Never talks to the screen;
# each step is caught and written to the JSON of the configuration, so the run
# always ends. Configuration: path in the environment variable FB_IPY_CFG.

import json
import os
import sys
import time
import traceback

CFG = json.load(open(os.environ["FB_IPY_CFG"]))
OUT = {}
sys.path.insert(0, CFG["scripts"])


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


MESH = {}


def read_mesh():
    import fb_aster
    nodes = {}
    t0 = time.time()
    for n in mw.all_nodes():
        p = mw.node(n)
        nodes[int(n)] = (float(p.x), float(p.y), float(p.z)) if hasattr(p, "x") else tuple(float(v) for v in p)
    elements = {}
    component = {}
    for e in mw.all_elements():
        elements[int(e)] = (str(mw.element_shape(e)), [int(q) for q in mw.nodes(e)])
        component[int(e)] = mw.element_component(e)
    MESH.update({"nodes": nodes, "elements": elements, "component": component})
    t1 = time.time()
    got = fb_aster.mesh_fingerprint(nodes, list(elements))
    return {"nodes": len(nodes), "elements": len(elements), "fingerprint": got,
            "read_seconds": t1 - t0, "fingerprint_seconds": time.time() - t1,
            "components": sorted(set(component.values())), "version": str(mw.version())}


def real_run(folder):
    """The panel's order of work, with times."""
    import fb_aster
    import fb_core
    with open(CFG["chosen"]) as f:
        chosen = json.load(f)
    t0 = time.time()
    fp = fb_aster.mesh_fingerprint(MESH["nodes"], list(MESH["elements"]))
    man = fb_aster.find_runs(folder, fp)[0]
    t1 = time.time()
    reason = fb_aster.refuse(man, CFG["version"])
    if reason:
        return {"refused": reason}
    plan = fb_core.plan_cuts(MESH, chosen)
    t2 = time.time()
    job = fb_aster.start(man, folder, plan, MESH, CFG["exe"], CFG["scratch"], timeout=CFG["limit"])
    started = time.time() - t2
    work = job.work
    while job.poll() is None:
        time.sleep(0.05)
    t3 = time.time()
    if not job.poll():
        return {"error": job.error().encode("ascii", "replace").decode("ascii")}
    result = job.result()
    t4 = time.time()
    per = fb_core.assign_nodes(plan, MESH, result)
    t5 = time.time()
    sums = {}
    for rank in result["forces"]:
        if rank == 0:
            continue
        pos = fb_core.positions(result, rank)
        for group in plan["groups"]:
            n = float(len(group["nodes"]))
            nodes = [MESH["nodes"][q] for q in group["nodes"]]
            point = tuple(sum(p[k] for p in nodes) / n for k in range(3))
            idx = per[group["id"]]
            s = fb_core.resultant([pos[i] for i in idx],
                                  [result["forces"][rank][i] for i in idx], point)
            sums["{0}_{1}".format(rank, group["id"])] = list(s)
    t6 = time.time()
    geo = [fb_core.section_geometry(MESH, g) for g in plan["groups"]]
    t7 = time.time()
    end = time.time() + 20
    while os.path.exists(work) and time.time() < end:
        time.sleep(0.1)
    return {"sums": sums, "manifest_seconds": t1 - t0, "plan_seconds": t2 - t1,
            "start_seconds": started, "run_seconds": t3 - t2, "aster_seconds": result["seconds"],
            "decode_seconds": t4 - t3, "assign_seconds": t5 - t4, "sum_seconds": t6 - t5,
            "geometry_seconds": t7 - t6, "total_seconds": t7 - t0,
            "left_behind": os.path.exists(work), "cut_nodes": len(result["nodes"]),
            "ranks": len(result["forces"]), "area": geo[0]["area"]}


def finish():
    mw.save_as(CFG["out"] + ".liml")
    return True


step("mesh", read_mesh)
for key, folder in sorted(CFG["folders"].items()):
    step("run_" + key, lambda folder=folder: real_run(folder))
step("finish", finish)
OUT["done"] = True
save()
