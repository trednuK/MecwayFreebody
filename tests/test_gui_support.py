# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_support.py
# What the panel tests share: finding the scripts, a fake mw and solution, a
# self-made cut with a made-up follow-up result, and a job that stands in for
# Code-Aster. CPython 3 and IronPython 2.7. fb_core and fb_aster are the real
# ones from Scripts/; FB_CORE_DIR can hold newer ones. Only the run of Code-Aster
# is stood in for, here in tests/.

import io
import json
import math
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
SCRIPTS = os.path.join(ROOT, "Scripts")
for folder in (TESTS, SCRIPTS, os.environ.get("FB_CORE_DIR")):
    if folder and folder not in sys.path:
        sys.path.insert(0, folder)

import test_gui_model as models  # noqa: E402


class Report(object):
    """Lines of OK and FAIL; a test run ends with its count."""

    def __init__(self):
        self.lines = []
        self.failed = 0

    def check(self, name, ok, detail=u""):
        self.lines.append(u"{0}  {1}{2}".format(
            "OK  " if ok else "FAIL", name,
            u"" if ok else u"  [{0}]".format(detail)))
        if not ok:
            self.failed += 1
        return ok

    def close(self, name, a, b, tol=1e-9):
        ok = abs(a - b) <= tol * max(abs(a), abs(b), 1.0)
        return self.check(name, ok, u"{0} != {1}".format(a, b))

    def run(self, namespace):
        import traceback
        for key in sorted(namespace):
            if key.startswith("test_") and callable(namespace[key]):
                try:
                    namespace[key](self)
                except Exception:
                    self.check(key, False, traceback.format_exc())


# ---- a fake Mecway --------------------------------------------------------------
class Vec(object):
    def __init__(self, xyz):
        self.x, self.y, self.z = xyz


class FakeMw(object):
    """The calls the panel makes, on a mesh of test_gui_model."""

    def __init__(self, m, selected=(), path=u"C:\\models\\bar.liml", component=None):
        self.m = m
        self.selected = list(selected)
        self.selected_node_list = []
        self.path = path
        self.component = component or {}
        self.calls = 0
        self.closed = False
        self.displayed = 0

    def _touch(self):
        self.calls += 1
        if self.closed:
            raise RuntimeError("no model open")

    def file_name(self):
        self._touch()
        return self.path

    def all_nodes(self):
        self._touch()
        return sorted(self.m.xyz)

    def all_elements(self):
        self._touch()
        return sorted(self.m.elements)

    def node(self, nid):
        self._touch()
        return Vec(self.m.xyz[nid])

    def nodes(self, eid):
        self._touch()
        return self.m.elements[eid][1]

    def element_shape(self, eid):
        self._touch()
        return self.m.elements[eid][0]

    def element_component(self, eid):
        self._touch()
        return self.component.get(eid, "Bar")

    def selected_elements(self):
        self._touch()
        return list(self.selected)

    def selected_nodes(self):
        self._touch()
        return list(self.selected_node_list)

    def selected_faces(self):
        self._touch()
        return []

    def material(self, name):
        if name == "Odd":
            raise RuntimeError("no material")
        return "Steel" if name == "Bar" else name

    def material_type(self, material, group):
        if group == "geometric":
            # thickness of a shell lives in the material, type Plate
            return "Plate" if material.startswith(("Plate", "Comp")) else "None"
        return "Orthotropic" if material in ("Wood", "Composite") else "Isotropic"

    def material_property(self, material, prop):
        if prop == "thickness":
            if material == "PlateBad":
                raise RuntimeError("no thickness")
            return 0.005 if material != "Composite" else 0.002
        return 210e9 if material == "Steel" else 70e9

    def set_solution_active(self):
        pass

    def display(self):
        self.displayed += 1


class FakeSolution(object):
    """Fields by name, with Mecway's measured behaviour."""
    KNOWN = ("externalforcex", "externalforcey", "externalforcez", "reactionmomx",
             "reactionmomy", "reactionmomz")

    def __init__(self, m, times=()):
        self.m = m
        self.fields = {}
        self.times = list(times)
        self.written_in = []

    def time_steps(self):
        return list(range(len(self.times)))

    def time(self, k):
        return self.times[k]

    def all_nodes(self):
        return sorted(self.m.xyz)

    def node(self, nid):
        return Vec(self.m.xyz[nid])

    def node_value(self, name, nid, time_step=None):
        # As Mecway: a solution with time steps refuses a call without one
        if self.times and time_step is None:
            raise Exception("Solution data is in modes or time steps.")
        if name not in self.fields:
            if name in self.KNOWN:
                return None
            raise Exception('Solution variable name "{0}" does not exist.'.format(name))
        return self.fields[name][nid - 1]

    def set_variable(self, name, values, time_step=None):
        if self.times and time_step is None:
            raise Exception("Solution data is in modes or time steps.")
        self.written_in.append(time_step)
        if len(values) != len(self.m.xyz):
            raise Exception("wrong length")
        self.fields[name] = list(values)


# ---- a cut with a made-up result ---------------------------------------------------
def selected_slice(cells=(5, 2, 2), i=2):
    """Elements of slice i of the bar: two cuts, at both sides of the slice."""
    per = cells[1] * cells[2]
    return list(range(i * per + 1, (i + 1) * per + 1))


def make_mesh(shape="hex20", component=None, m=None):
    m = m or models.block(shape)[0]
    mesh = {"nodes": dict(m.xyz), "elements": dict(m.elements),
            "component": dict((e, (component or {}).get(e, u"Bar")) for e in m.elements)}
    return m, mesh


def nodal_force(k, p, rank):
    """A made-up force at a cut node: the same on all nodes of cut 1, opposite
    on cut 2, with a share that varies over the section."""
    s = 1.0 if k == 1 else -1.0
    a = 1.0 + 5.0 * p[1] + 2.0 * p[2]
    return (s * 3.0 * rank * a, s * 2.0 * rank, -s * 7.0 * rank, 0.0, 0.0, 0.0)


def make_result(plan, mesh, ranks=(1, 2), rest=None, large=False, shift=None,
                extra=None):
    """A result of the contract. shift(p, rank): displacement at a node."""
    nodes = []
    owner = {}
    for group in plan["groups"]:
        for n in group["nodes"]:
            owner[len(nodes)] = group["id"]
            nodes.append({"index": len(nodes), "xyz": tuple(mesh["nodes"][n]),
                          "large": large, "nid": n})
    for p, gid in (extra or []):
        owner[len(nodes)] = gid
        nodes.append({"index": len(nodes), "xyz": p, "large": large})
    forces = {}
    disp = {}
    rests = {}
    for r in ranks:
        forces[r] = [nodal_force(owner[i], n["xyz"], r or 1) for i, n in enumerate(nodes)]
        disp[r] = [tuple(shift(n["xyz"], r)) if shift else (0.0, 0.0, 0.0)
                   for n in nodes]
        rests[r] = rest or {"sum": (0.0,) * 6, "largest": 1e-9, "cut_largest": 10.0,
                            "count": 0, "where": []}
    return {"steps": [{"rank": r, "time": float(r) / len(ranks)} for r in ranks],
            "nodes": nodes, "forces": forces, "disp": disp, "rest": rests,
            "large": large, "extra_nodes": bool(extra), "warnings": [], "seconds": 1.5}


class FakeJob(object):
    """Stands in for fb_aster.Job: running for some polls, then the result."""

    def __init__(self, value, polls=3, code=None, text=None):
        self.value = value
        self.polls = polls
        self.failure = code
        self.text = text
        self.stopped = False

    def poll(self):
        if self.stopped:
            return False
        if self.polls > 0:
            self.polls -= 1
            return None
        return self.failure is None

    def result(self):
        return self.value

    def error(self):
        return self.text

    def code(self):
        return "stopped" if self.stopped else self.failure

    def stop(self):
        self.stopped = True


def manifest(fingerprint, run_id="20261107_120000", cells=(), **extra):
    """A manifest of schema 1 that passes fb_aster.refuse."""
    man = {"schema": 1, "run_id": run_id, "model": "bar", "analysis": "lin_static_3d",
           "configuration": None, "solver": "MECA_STATIQUE", "aster_version": "17.4",
           "memory_limit": 2048, "base": "bar_{0}_base".format(run_id),
           "fingerprint": fingerprint, "deformation": "PETIT",
           "concepts": {"result": "res"}, "cells": list(cells), "skin": {},
           "not_shared": [], "line_quad": False, "extra_nodes": False}
    man.update(extra)
    return man


def write_run(folder, man):
    """A run on disk: manifest and a base folder that is not empty."""
    base = os.path.join(folder, man["base"])
    if not os.path.isdir(base):
        os.makedirs(base)
    with io.open(os.path.join(base, "glob.1"), "w", encoding="utf-8") as f:
        f.write(u"base")
    path = os.path.join(folder, "bar_{0}_manifest.json".format(man["run_id"]))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"{0}".format(json.dumps(man)))


def rotate(v, angle, axis):
    """v turned by angle about the unit vector axis (Rodrigues)."""
    c, s = math.cos(angle), math.sin(angle)
    d = axis[0] * v[0] + axis[1] * v[1] + axis[2] * v[2]
    x = (axis[1] * v[2] - axis[2] * v[1], axis[2] * v[0] - axis[0] * v[2],
         axis[0] * v[1] - axis[1] * v[0])
    return tuple(c * v[k] + s * x[k] + (1 - c) * d * axis[k] for k in range(3))


def rigid_rotation(angle, centre, axis=(0.0, 0.0, 1.0)):
    """shift(p, rank) of a rotation about an axis through centre, rank 2 only."""
    def shift(p, rank):
        if rank == 1:
            return (0.0, 0.0, 0.0)
        d = tuple(p[k] - centre[k] for k in range(3))
        q = rotate(d, angle, axis)
        return tuple(centre[k] + q[k] - p[k] for k in range(3))
    return shift


# ---- shells and beams: plans and geometry by hand (phase 4) --------------------------
# What the core of phase 4 gives by the contract, written out by hand, so the
# panel can be tested before that core is there.
THICKNESS = 0.005
BEAM_AREA = 2e-4
W_PLATE = (0.0, 0.0, 1.0)
GLOBAL = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
BEAM_X1 = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))   # cut at node 1: mirrored
BEAM_X2 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))     # cut at node 2


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _mesh_of(m, component):
    return {"nodes": dict(m.xyz), "elements": dict(m.elements),
            "component": dict(component)}


def _nodes_at_x(mesh, x, nids=None):
    out = [n for n, p in mesh["nodes"].items() if abs(p[0] - x) < 1e-12 and
           (nids is None or n in nids)]
    return sorted(out, key=lambda n: mesh["nodes"][n][1])


def _strip_group(mesh, gid, x, eids, outward):
    """A cut through the edges at x of the shell elements eids."""
    n = (outward, 0.0, 0.0)
    nids = set()
    for e in eids:
        nids.update(mesh["elements"][e][1])
    nodes = _nodes_at_x(mesh, x, nids)
    strips = []
    entities = []
    for e in eids:
        ys = sorted(mesh["nodes"][q][1] for q in mesh["elements"][e][1]
                    if abs(mesh["nodes"][q][0] - x) < 1e-12)
        strips.append({"a": (x, ys[0], 0.0), "b": (x, ys[-1], 0.0), "t": THICKNESS,
                       "w": W_PLATE, "offset": 0.0})
        entities.append(("edge", e, 4 if outward < 0 else 2))
    length = sum(s["b"][1] - s["a"][1] for s in strips)
    y0 = min(s["a"][1] for s in strips)
    if len(strips) == 1:
        axes = (n, cross(W_PLATE, n), W_PLATE)
    else:
        a = (0.0, 1.0, 0.0)
        axes = (n, a, cross(n, a))
    group = {"id": gid, "nodes": nodes, "entities": entities, "faces": [],
             "kind": "shell"}
    geo = {"area": THICKNESS * length, "centroid": (x, y0 + length / 2.0, 0.0),
           "planar": True, "normal": n, "axes": axes, "outline": [],
           "inertia": (0.0, 0.0), "warnings": [], "strips": strips, "beams": []}
    return group, geo


def load_case(mesh, plan, geos, man, large=False, shift=None, ranks=(1, 2)):
    """A PanelModel on a plan and geometry by hand, with a made-up result."""
    import fb_gui
    result = make_result(plan, mesh, ranks=ranks, large=large, shift=shift)
    per = {}
    i = 0
    for group in plan["groups"]:
        per[group["id"]] = list(range(i, i + len(group["nodes"])))
        i += len(group["nodes"])
    model = fb_gui.PanelModel()
    model.load(mesh, plan, geos, result, per, man, u"folder")
    return model


def shell_case(across=1, large=False, shift=None, warnings=(), coef=None):
    """Plate of 3 x across quad4, the middle column selected: cuts at x = 0.1
    (outward -x) and x = 0.2 (outward +x). across 1: one strip per cut."""
    m, component = models.plate(cells=(3, across))
    mesh = _mesh_of(m, component)
    eids = list(range(across + 1, 2 * across + 1))
    g1, geo1 = _strip_group(mesh, 1, 0.1, eids, -1.0)
    g2, geo2 = _strip_group(mesh, 2, 0.2, eids, 1.0)
    plan = {"inside": eids, "outside": [e for e in mesh["elements"] if e not in eids],
            "cut_nodes": g1["nodes"] + g2["nodes"], "groups": [g1, g2],
            "warnings": list(warnings)}
    man = manifest("x", schema=2, coef_rigi_drz=coef,
                   components={u"Plate": {"model": "DKT", "has_warping": False}})
    return load_case(mesh, plan, {1: geo1, 2: geo2}, man, large, shift)


def beam_case(model_name="POU_D_E", section=None, large=False, shift=None):
    """Three line2 beams along x, the middle one selected: a cut at its node 1
    (x = 0.1, axes mirrored) and at its node 2 (x = 0.2)."""
    m, component = models.frame_bar()
    mesh = _mesh_of(m, component)
    groups, geos = [], {}
    for gid, x, axes in ((1, 0.1, BEAM_X1), (2, 0.2, BEAM_X2)):
        nid = _nodes_at_x(mesh, x)[0]
        groups.append({"id": gid, "nodes": [nid], "entities": [("end", 2, nid)],
                       "faces": [], "kind": "beam"})
        geos[gid] = {"area": BEAM_AREA, "centroid": mesh["nodes"][nid], "planar": True,
                     "normal": axes[0], "axes": axes, "outline": [], "inertia": (0.0, 0.0),
                     "warnings": [], "strips": [],
                     "beams": [{"node": nid, "A": BEAM_AREA, "axes": axes}]}
    plan = {"inside": [2], "outside": [1, 3], "cut_nodes": [g["nodes"][0] for g in groups],
            "groups": groups, "warnings": []}
    if section is None:
        section = {"cara": ["HY", "HZ"], "vale": [0.02, 0.01], "shape": "RECTANGLE"}
    man = manifest("x", schema=2, components={
        u"Beam": {"model": model_name, "has_warping": False, "section": section}})
    return load_case(mesh, plan, geos, man, large, shift)


def mixed_case():
    """The plate of 3 x 1 with a rib of beams on its edge y = 0; the middle
    shell and its rib selected. Each cut holds a strip and a beam end: mixed,
    global axes."""
    m, component = models.plate(cells=(3, 1), beam_along=True)
    mesh = _mesh_of(m, component)
    inside = [2, 5]
    groups, geos = [], {}
    for gid, x, outward in ((1, 0.1, -1.0), (2, 0.2, 1.0)):
        group, geo = _strip_group(mesh, gid, x, [2], outward)
        rib = _nodes_at_x(mesh, x)[0]
        axes = BEAM_X1 if outward < 0 else BEAM_X2
        group["entities"].append(("end", 5, rib))
        group["kind"] = "mixed"
        area = geo["area"] + BEAM_AREA
        cy = geo["centroid"][1] * geo["area"] / area
        geo.update({"area": area, "centroid": (x, cy, 0.0), "axes": GLOBAL,
                    "beams": [{"node": rib, "A": BEAM_AREA, "axes": axes}]})
        groups.append(group)
        geos[gid] = geo
    plan = {"inside": inside, "outside": [e for e in mesh["elements"] if e not in inside],
            "cut_nodes": groups[0]["nodes"] + groups[1]["nodes"], "groups": groups,
            "warnings": ["mixed_cut"]}
    man = manifest("x", schema=2, components={
        u"Plate": {"model": "DKT", "has_warping": False},
        u"Rib": {"model": "POU_D_T", "has_warping": False,
                 "section": {"cara": ["R"], "vale": [0.008], "shape": "CERCLE"}}})
    return load_case(mesh, plan, geos, man)


# ---- a cut by nodes on a plane (fb_nodecut) ------------------------------------------
# A follow-up run stood in for as Code-Aster gives it: the nodes the selection
# shares with the rest, with a made-up force that turns over with the side of
# the selection, so the two sides of a plane are opposite by construction.
def nodes_at(mesh, x, test=None, tol=1e-9):
    """Nodes on the plane x of the bar of test_gui_model, of elements only;
    test(y, z) picks a part of the section."""
    used = set(n for _, nids in mesh["elements"].values() for n in nids)
    return sorted(n for n, p in mesh["nodes"].items()
                  if n in used and abs(p[0] - x) < tol and (test is None or test(p[1], p[2])))


def run_force(p, s, rank=1):
    """The force of the rest on a selection at side s (+1: larger x) of p."""
    return (s * rank * (3.0 + 50.0 * p[1]), s * rank * 2.0, s * rank * (-7.0 + 100.0 * p[2]),
            0.0, 0.0, 0.0)


def follow_up(mesh, inside, shift=None, ranks=(1, 2), judged=True):
    """The result of a run on the selection inside, as fb_aster gives it:
    judged (Job.result()), or as decode_result leaves it ("totals" in on_cut),
    for the prepare hook. A node gets the force of the side of inside."""
    import fb_core
    plan = fb_core.plan_cuts(mesh, inside)
    used = set(n for e in inside for n in mesh["elements"][e][1])
    mean_x = sum(mesh["nodes"][n][0] for n in used) / float(len(used))
    nodes = [{"index": i, "xyz": tuple(mesh["nodes"][n]), "large": False, "nid": n}
             for i, n in enumerate(plan["cut_nodes"])]
    forces, disp, rest, on_cut = {}, {}, {}, {}
    for r in ranks:
        forces[r] = [run_force(q["xyz"], 1.0 if mean_x > q["xyz"][0] else -1.0, r)
                     for q in nodes]
        disp[r] = [tuple(shift(q["xyz"], r)) if shift else (0.0, 0.0, 0.0) for q in nodes]
        rest[r] = {"sum": (0.0,) * 6, "largest": 1e-9, "cut_largest": 10.0, "count": 0,
                   "where": [], "tolerance": 1e-6, "top": []}
        on_cut[r] = {"totals": [(0.0,) * 6 for _ in nodes]}
    result = {"steps": [{"rank": r, "time": float(r) / len(ranks)} for r in ranks],
              "nodes": nodes, "forces": forces, "disp": disp, "rest": rest,
              "on_cut": on_cut, "large": False, "extra_nodes": False, "warnings": [],
              "seconds": 1.5}
    return judge(result) if judged else result


def judge(result, plan=None, mesh=None):
    """What Job.result() does after decode_result (and prepare): the real
    fb_core.link_nodes and fb_aster.judge_rest. Without a plan, link_nodes is
    left out and every node is its own cut."""
    import fb_aster
    import fb_core
    if plan is not None:
        per = fb_core.link_nodes(plan, mesh, result)
    else:
        per = {1: list(range(len(result["nodes"])))}
    fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
    return result


class HookJob(FakeJob):
    """fb_aster's Job with the prepare hook, around a stand-in run: prepare on
    the result as decoded, then link_nodes and judge_rest as Job.result()."""

    def __init__(self, raw, prepare=None, polls=3, plan=None, mesh=None):
        FakeJob.__init__(self, None, polls)
        self.raw = raw
        self.prepare = prepare
        self.prepared = 0
        self.plan = plan
        self.mesh = mesh

    def result(self):
        if self.value is None:
            result = self.raw
            if self.prepare is not None:
                self.prepared += 1
                result = self.prepare(result)
            self.value = judge(result, self.plan, self.mesh)
        return self.value


def start_hook(box, shift=None, polls=3):
    """fb_aster.start with the prepare hook of the contract, the run stood in
    for by follow_up."""
    def start(man, folder, plan, mesh, exe, scratch=None, timeout=None, memory=None,
              prepare=None):
        box["plan"] = plan
        box["prepare"] = prepare
        box["job"] = HookJob(follow_up(mesh, plan["inside"], shift, judged=False), prepare,
                             polls, plan, mesh)
        return box["job"]
    return start
