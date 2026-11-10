# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_nodecut_e2e.py
# The cut through a set of nodes on a plane (docs/design/knopensnede-plan.md),
# written before fb_nodecut exists. Self-made models, the real bridge code and
# Code-Aster, no Mecway. The references come from this file only:
#   full section     exact statics of the free side (solids_models.Reference)
#   partial section  REAC_NODA of the whole element layer next to the plane, from
#                    a run of our own on the base (post.npz), summed over the
#                    selected nodes and the midside nodes between them
# A test is skipped when fb_nodecut, numpy, Code-Aster or its base is missing.
# The classes Reference* check the references themselves and need no fb_nodecut.
#
# The interface this file assumes (one place: node_cut and filtered below):
#   cut = fb_nodecut.plan_from_nodes(mesh, node_ids, side=1)   # Refused(code) else
#   cut["elements"]    [eid]   the selection; side=-1 gives the other side
#   cut["keep"]        [nid]   nodes of Mecway in the sum: the selected nodes and
#                              the midside nodes of edges with both corners selected
#   cut["partial"]     bool    partial section: only the layer at the plane
#   cut["rest_valid"]  bool    False for a partial section
#   cut["warnings"]    [code]  "partial_section" for a partial section
#   cut["normal"]      (n)     unit, pointing away from the chosen side
#   cut["plan"]        plan    as fb_core.plan_cuts, for fb_aster.start, assign_nodes
#                              and section_geometry; inside == elements
#   fb_nodecut.filter_result(result, cut[, mesh])   the result with only the nodes
#                              of the cut, all parallel series per step together
#
# Bases (six, about 40 s and 0.8 GB in all, Code-Aster on 1 cpu; the tests take 2 minutes):
#   python -B tests/test_nodecut_e2e.py build <bridge folder> [work folder] [tags]
# Default work folder WorkDir\nodecut of this checkout. The test looks in
# FB_NODECUT (folders, separated by ;) and in WorkDir\nodecut of this checkout and
# of the checkouts above it. Run:
#   python -B -m unittest tests.test_nodecut_e2e -v

import inspect
import json
import os
import random
import shutil
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
import fb_aster
import fb_core
from fb_core import Refused

try:
    import numpy as np
    import solids_models as sm
except (ImportError, AttributeError):  # no numpy, or no Windows for the research library
    np = None
    sm = None

try:
    import fb_nodecut
except ImportError:
    fb_nodecut = None

EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4",
                   "bin", "run_aster.bat")
CREATE_NO_WINDOW = 0x08000000
BAR = 1e-10            # against statics, as test_aster_e2e
BAR_STEP = 1e-5        # a step of a nonlinear run: RESI_GLOB_RELA 1e-5
BAR_SAME = 1e-9        # two CALC_CHAMP on the same base, other groups: rounding only
BAR_REST = 1e-6        # N, off the cut of a clean model
EPS = 1e-9             # m: on the plane, same point


# ---- the interface ---------------------------------------------------------------------------
PLAN_FUNCTION = "plan_from_nodes"
FILTER_FUNCTION = "filter_result"


def node_cut(mesh, nids, side=1):
    return getattr(fb_nodecut, PLAN_FUNCTION)(mesh, list(nids), side)


def filtered(result, cut, mesh):
    f = getattr(fb_nodecut, FILTER_FUNCTION)
    try:
        count = len(inspect.signature(f).parameters)
    except (TypeError, ValueError):
        count = 2
    return f(result, cut, mesh) if count >= 3 else f(result, cut)


# ---- models ----------------------------------------------------------------------------------
L, B, H = (.2, .02, .04) if sm is None else (sm.L, sm.B, sm.H)
DX, DZ = L / 12, H / 4                      # cells of solids_models.bar
U_D = (.02, .01, .02)                       # cells of the U
U_SIZE = (6, 3, 8)
U_CUT = 5                                   # the cut of the left leg: z = 5 dz


def with_layers(m, plus, minus):
    m.layers = {"LP": plus, "LM": minus}
    return m


def bar(tag, kind, order, general=None):
    """solids_models.bar: 12 x 2 x 4 cells, clamp at x = 0, tip and side load,
    gravity. Layers next to x = L/2."""
    m = sm.bar(tag, kind, order, general=general)
    col = lambda i: [q for (a, b, c), es in m.cells.items() if a == i for q in es]
    return with_layers(m, col(6), col(5))


def bar_nl(tag):
    """As bar hex20, plastic and on x + u, four steps."""
    m = bar(tag, "hex", 1)
    m.steps = .25
    m.materials = {"Steel": dict(sm.STEEL, **{"yield": 250e6, "tangent": 2e9})}
    m.loads = [("force", "TIP", (0., 0., -12000.)), ("force", "SIDE", (0., 0., -300.))]
    return m


def u_shape(tag):
    """A U standing on its base: base 6 x 3 x 2 cells, legs of 2 x 3 x 6 cells at
    both ends, clamped below, a force on top of each leg, gravity. The cut goes
    through the left leg at z = 5 dz; the right leg crosses that plane too."""
    m = sm.Model(tag)
    nx, ny, nz = U_SIZE
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                if k < 2 or i < 2 or i >= nx - 2:
                    m.cell((i, j, k), "hex", 1, U_D)
    top = nz * U_D[2]
    m.faces["CLAMP"] = m.pick(lambda c: abs(c[2]) < EPS)
    m.fixed = ["CLAMP"]
    m.faces["TOP_A"] = m.pick(lambda c: abs(c[2] - top) < EPS and c[0] < 2 * U_D[0])
    m.faces["TOP_B"] = m.pick(lambda c: abs(c[2] - top) < EPS and c[0] > (nx - 2) * U_D[0])
    m.loads = [("force", "TOP_A", (300., 200., -500.)), ("force", "TOP_B", (-100., 50., 400.))]
    leg = lambda k: [q for (a, b, c), es in m.cells.items() if a < 2 and c == k for q in es]
    return with_layers(m, leg(U_CUT), leg(U_CUT - 1))


def step(tag):
    """A bar whose left half is 1.5 H high: the plane x = L/2 holds the step face,
    a free face of the left half only. Clamp at x = 0, loads on the right half."""
    m = sm.Model(tag)
    d = (DX, B / 2, DZ)
    for i in range(12):
        for j in range(2):
            for k in range(6 if i < 6 else 4):
                m.cell((i, j, k), "hex", 1, d)
    m.faces["CLAMP"] = m.pick(lambda c: abs(c[0]) < EPS)
    m.fixed = ["CLAMP"]
    m.faces["TIP"] = m.pick(lambda c: abs(c[0] - L) < EPS)
    m.faces["SIDE"] = m.pick(lambda c: abs(c[2] - H) < EPS and 7 * DX < c[0] < 9 * DX)
    m.loads = [("force", "TIP", sm.F_TIP), ("force", "SIDE", sm.F_SIDE)]
    m.layers = {}
    return m


MODELS = {
    "n_hex20": lambda t: bar(t, "hex", 1),
    "n_lq": lambda t: bar(t, "hex", 0, general={"elem_hex8": "LINE_QUAD"}),
    "n_tet10": lambda t: bar(t, "tet", 1),
    "n_nl": bar_nl,
    "n_u": u_shape,
    "n_step": step,
}
MODEL_CACHE = {}


def model(tag):
    if tag not in MODEL_CACHE:
        m = MODELS[tag](tag)
        MODEL_CACHE[tag] = (m, m.mesh())
    return MODEL_CACHE[tag]


# ---- selections: what the user picks, as node ids ----------------------------------------------
def where(m, test):
    return [i + 1 for i, p in enumerate(m.ref) if test(np.array(p))]


def corners_only(m, nids):
    corner = set()
    for shape, nodes in m.elements.values():
        corner.update(nodes[:fb_core._FAMILIES[shape][2]])
    return [n for n in nids if n in corner]


def on_x(p, x=L / 2):
    return abs(p[0] - x) < EPS


def diagonal_distance(p):
    """The plane x/dx - z/dz = 2: along tet faces, through the hex cells."""
    return (p[0] / DX - p[2] / DZ - 2.0) * DX


SELECT = {
    "x": lambda m: where(m, on_x),
    "x_corners": lambda m: corners_only(m, where(m, on_x)),
    "upper": lambda m: where(m, lambda p: on_x(p) and p[2] > H / 2 - EPS),
    "upper_corners": lambda m: corners_only(m, where(m, lambda p: on_x(p) and p[2] > H / 2 - EPS)),
    "diagonal": lambda m: where(m, lambda p: abs(diagonal_distance(p)) < EPS),
    "leg": lambda m: where(m, lambda p: abs(p[2] - U_CUT * U_D[2]) < EPS and p[0] < 2 * U_D[0] + EPS),
}

# name: (model, selection, signed distance to the plane, what each side is,
#        layer of the reference per side). Side +1 is where the distance is positive.
SECTIONS = {
    "hex20_full": ("n_hex20", "x", lambda p: p[0] - L / 2, {1: "full", -1: "full"}, None),
    "hex20_full_corners": ("n_hex20", "x_corners", lambda p: p[0] - L / 2,
                           {1: "full", -1: "full"}, None),
    "lq_full": ("n_lq", "x", lambda p: p[0] - L / 2, {1: "full", -1: "full"}, None),
    "tet10_full": ("n_tet10", "x", lambda p: p[0] - L / 2, {1: "full", -1: "full"}, None),
    "tet10_diagonal": ("n_tet10", "diagonal", diagonal_distance, {1: "full", -1: "full"}, None),
    "step_full": ("n_step", "x", lambda p: p[0] - L / 2, {1: "full", -1: "full"}, None),
    "hex20_upper": ("n_hex20", "upper", lambda p: p[0] - L / 2,
                    {1: "partial", -1: "partial"}, {1: "LP", -1: "LM"}),
    "hex20_upper_corners": ("n_hex20", "upper_corners", lambda p: p[0] - L / 2,
                            {1: "partial", -1: "partial"}, {1: "LP", -1: "LM"}),
    "lq_upper": ("n_lq", "upper", lambda p: p[0] - L / 2,
                 {1: "partial", -1: "partial"}, {1: "LP", -1: "LM"}),
    "tet10_upper": ("n_tet10", "upper", lambda p: p[0] - L / 2,
                    {1: "partial", -1: "partial"}, {1: "LP", -1: "LM"}),
    "nl_upper": ("n_nl", "upper", lambda p: p[0] - L / 2,
                 {1: "partial", -1: "partial"}, {1: "LP", -1: "LM"}),
    "u_leg": ("n_u", "leg", lambda p: p[2] - U_CUT * U_D[2],
              {1: "full", -1: "partial"}, {1: "LP", -1: "LM"}),
}


def section(name):
    tag, how, dist, kinds, layers = SECTIONS[name]
    m, mesh = model(tag)
    return m, mesh, SELECT[how](m), dist, kinds, layers


# Refusals as data: (name, model, nodes, code). Nodes as a function of the model.
def _bent(m):
    """x = L/2 below the middle, z = H/2 on the right of it: two planes."""
    return where(m, lambda p: (on_x(p) and p[2] < H / 2 + EPS) or
                 (abs(p[2] - H / 2) < EPS and L / 2 - EPS < p[0] < L / 2 + 2 * DX + EPS))


REFUSALS = [
    ("off_plane_node", "n_hex20",
     lambda m: where(m, on_x) + where(m, lambda p: on_x(p, L / 2 + DX))[:1], "nodes_not_planar"),
    ("two_planes", "n_hex20", _bent, "nodes_not_planar"),
    ("midsides_in_cells_hex20", "n_hex20",
     lambda m: where(m, lambda p: on_x(p, L / 2 - DX / 2)), "plane_through_elements"),
    ("midsides_in_cells_tet10", "n_tet10",
     lambda m: where(m, lambda p: on_x(p, L / 2 - DX / 2)), "plane_through_elements"),
    ("diagonal_hex8", "n_lq", SELECT["diagonal"], "plane_through_elements"),
    ("diagonal_hex20", "n_hex20", lambda m: corners_only(m, SELECT["diagonal"](m)),
     "plane_through_elements"),
    ("one_line", "n_hex20",
     lambda m: where(m, lambda p: on_x(p) and abs(p[2] - H / 2) < EPS), "nodes_collinear"),
    ("two_nodes", "n_hex20", lambda m: where(m, on_x)[:2], "nodes_collinear"),
    ("empty", "n_hex20", lambda m: [], ("nodes_collinear", "empty")),
]


# ---- the reference: what the plan says, computed here ------------------------------------------
def centroid(m, eid):
    shape, nids = m.elements[eid]
    return np.mean([m.ref[n - 1] for n in nids[:fb_core._FAMILIES[shape][2]]], axis=0)


def geometric_side(m, eids, dist):
    """+1 or -1 if all these elements lie on one side, else 0."""
    signs = set(1 if dist(centroid(m, e)) > 0 else -1 for e in eids)
    return signs.pop() if len(signs) == 1 else 0


def nodes_of(m, eids):
    out = set()
    for e in eids:
        out.update(m.elements[e][1])
    return out


def side_elements(m, dist, sign):
    return sorted(e for e in m.elements if sign * dist(centroid(m, e)) > 0)


def grow(m, nids, dist, sign):
    """The elements reached from those on this side that touch a selected node,
    over nodes that are not selected (nor midside nodes between selected ones)."""
    blocked = expected_keep(m, nids, m.elements)
    by_node = {}
    for e, (shape, nodes) in m.elements.items():
        for n in nodes:
            by_node.setdefault(n, []).append(e)
    picked = set(nids)
    todo = [e for e in side_elements(m, dist, sign) if picked & set(m.elements[e][1])]
    seen = set(todo)
    while todo:
        for n in m.elements[todo.pop()][1]:
            if n not in blocked:
                for q in by_node[n]:
                    if q not in seen:
                        seen.add(q)
                        todo.append(q)
    return sorted(seen)


def expected_elements(m, nids, dist, sign, kind):
    """Full: the grown body, which must stay on its side. Partial: the elements
    on that side that touch a selected node."""
    if kind == "full":
        body = grow(m, nids, dist, sign)
        assert geometric_side(m, body, dist) == sign, "the reference body leaks"
        return body
    picked = set(nids)
    return [e for e in side_elements(m, dist, sign) if picked & set(m.elements[e][1])]


def edges_between(m, eids, nids):
    """[(eid, a, b, midside nid or None)] of the edges of these elements with
    both corners in nids."""
    picked = set(nids)
    out = []
    for e in eids:
        shape, nodes = m.elements[e]
        faces, edges, count, quadratic = fb_core._FAMILIES[shape]
        for k, (a, b) in enumerate(edges):
            if nodes[a] in picked and nodes[b] in picked:
                out.append((e, nodes[a], nodes[b], nodes[count + k] if quadratic else None))
    return out


def expected_keep(m, nids, eids):
    """Selected nodes and the midside nodes of the mesh between two of them."""
    return set(nids) | set(q for e, a, b, q in edges_between(m, eids, nids) if q)


def key(p):
    return tuple(int(round(v * 1e9)) for v in p)


def expected_points(m, nids, chosen, kind):
    """Where the summed nodes lie, as Code-Aster has them: for a full section the
    nodes the two sides share; midside nodes of LINE_QUAD as edge midpoints."""
    pick = set(nids)
    if kind == "full":
        others = [e for e in m.elements if e not in set(chosen)]
        pick &= nodes_of(m, chosen) & nodes_of(m, others)
        pick |= set(q for e, a, b, q in edges_between(m, chosen, pick) if q)
    else:
        pick = expected_keep(m, pick, chosen)
    out = set(key(m.xyz[n - 1]) for n in pick)
    for e, a, b, q in edges_between(m, chosen, pick):
        if q is None:
            out.add(key((np.array(m.xyz[a - 1]) + np.array(m.xyz[b - 1])) / 2))
    return out


def expected_faces(m, nids, chosen):
    """Faces of the chosen elements with all corners selected and an element of
    the other side behind them."""
    picked = set(nids)
    chosen = set(chosen)
    seen = {}
    for e, (shape, nodes) in m.elements.items():
        for i, face in enumerate(fb_core._FAMILIES[shape][0]):
            seen.setdefault(tuple(sorted(nodes[k] for k in face)), []).append((e, i + 1))
    out = set()
    for corners, owners in seen.items():
        if set(corners) <= picked and len(owners) == 2:
            mine = [o for o in owners if o[0] in chosen]
            if len(mine) == 1:
                out.add(mine[0])
    return out


def statics(m, chosen, point, u=None):
    """(F, M) of the rest on the chosen elements about point, by statics: the
    loads of whichever side holds no support."""
    ref = sm.Reference(m, u)
    chosen = set(chosen)
    others = [e for e in m.elements if e not in chosen]
    fixed = m.fixed_nodes()
    if not nodes_of(m, chosen) & fixed:
        f, c = ref.of(sorted(chosen), point)
        return -f, -c
    assert not nodes_of(m, others) & fixed, "both sides hold a support"
    return ref.of(others, point)


def load_size(m):
    return float(np.linalg.norm(sm.Reference(m).of(list(m.elements), (0., 0., 0.))[0]))


def relative(s, f, c, length, load=0.0):
    size = max(np.linalg.norm(f), np.linalg.norm(c) / length, load)
    s = np.asarray(s, float)
    return (float(np.linalg.norm(s[:3] - f) / size),
            float(np.linalg.norm(s[3:] - c) / (size * length)))


def size_of(m):
    p = np.array(m.ref)
    return float(np.linalg.norm(p.max(axis=0) - p.min(axis=0)))


def layer_sum(z, layer, rank, points, point, large):
    """(F, M) about point of the REAC_NODA of a whole layer at these points."""
    xyz = z["xyz"]
    at = dict((key(p), i) for i, p in enumerate(xyz))
    idx = [at[q] for q in points]
    r = z["R_%s_%d" % (layer, rank)][idx]
    x = xyz[idx] + (z["U_%d" % rank][idx] if large else 0.0)
    return r.sum(axis=0), np.cross(x - np.array(point), r).sum(axis=0)


# ---- bases ------------------------------------------------------------------------------------
def candidates():
    out = [p for p in os.environ.get("FB_NODECUT", "").split(";") if p]
    here = ROOT
    while True:
        out.append(os.path.join(here, "WorkDir", "nodecut"))
        up = os.path.dirname(here)
        if up == here:
            return out
        here = up


def find_case(tag):
    for root in candidates():
        folder = os.path.join(root, tag)
        if (os.path.isdir(folder) and os.path.isfile(os.path.join(folder, "post.npz")) and
                any(n.endswith("_manifest.json") for n in os.listdir(folder))):
            return folder
    return None


BASES = {}


def base(tag):
    """(folder, manifest, post arrays, scratch) of a base."""
    if tag not in BASES:
        m, mesh = model(tag)
        folder = find_case(tag)
        runs = fb_aster.find_runs(folder, fb_aster.mesh_fingerprint(mesh["nodes"],
                                                                    list(mesh["elements"])))
        assert runs, "the base of {0} is of another mesh".format(tag)
        with np.load(os.path.join(folder, "post.npz")) as z:
            arrays = dict((k, z[k]) for k in z.files)
        assert np.abs(arrays["xyz"][:len(m.xyz)] - np.array(m.xyz)).max() < EPS
        BASES[tag] = (folder, runs[0], arrays, os.path.join(os.path.dirname(folder), "scratch"))
    return BASES[tag]


def has_base(tag):
    return sm is not None and os.path.isfile(EXE) and find_case(tag) is not None


def needs_cut(*tags):
    ok = fb_nodecut is not None and sm is not None and all(has_base(t) for t in tags)
    why = "no fb_nodecut yet" if fb_nodecut is None else "no base of {0}, Code-Aster or numpy".format(
        " ".join(tags))
    return unittest.skipUnless(ok, why)


def needs_base(*tags):
    return unittest.skipUnless(all(has_base(t) for t in tags),
                               "no base of {0}, Code-Aster or numpy".format(" ".join(tags)))


needs_module = unittest.skipUnless(fb_nodecut is not None and sm is not None,
                                   "no fb_nodecut yet, or no numpy")


RUNS = {}


def follow(name, side):
    """(cut, result, filtered result, per group) of one follow-up run."""
    if (name, side) not in RUNS:
        m, mesh, nids, dist, kinds, layers = section(name)
        folder, man, z, scratch = base(SECTIONS[name][0])
        cut = node_cut(mesh, nids, side)
        job = fb_aster.start(man, folder, cut["plan"], mesh, EXE, scratch, timeout=600.0)
        end = time.time() + 660
        while job.poll() is None:
            if time.time() > end:
                job.stop()
                break
            time.sleep(0.05)
        assert job.poll(), "{0} {1}: {2} {3}".format(name, side, job.code(), job.error())
        result = job.result()
        less = filtered(result, cut, mesh)
        RUNS[(name, side)] = (cut, result, less, fb_core.assign_nodes(cut["plan"], mesh, less))
    return RUNS[(name, side)]


def total(result, per, rank, point):
    """The sum over all groups, and the number of nodes in it."""
    idx = sorted(i for g in per.values() for i in g)
    pos = fb_core.positions(result, rank)
    s = fb_core.resultant([pos[i] for i in idx], [result["forces"][rank][i] for i in idx], point)
    return np.array(s), idx


def report(text):
    sys.stderr.write(text + "\n")


# ---- 1. what fb_nodecut makes of the nodes, without Code-Aster ---------------------------------
@needs_module
class Selection(unittest.TestCase):
    def check(self, name):
        m, mesh, nids, dist, kinds, layers = section(name)
        seen = {}
        for side in (1, -1):
            cut = node_cut(mesh, nids, side)
            sign = geometric_side(m, cut["elements"], dist)
            self.assertNotEqual(sign, 0, "{0} {1}: elements on both sides".format(name, side))
            seen[side] = (sign, cut)
            kind = kinds[sign]
            want = expected_elements(m, nids, dist, sign, kind)
            self.assertEqual(sorted(cut["elements"]), want, "{0} side {1}".format(name, side))
            self.assertEqual(bool(cut["partial"]), kind == "partial", name)
            self.assertEqual(bool(cut["rest_valid"]), kind == "full", name)
            self.assertEqual("partial_section" in cut["warnings"], kind == "partial", name)
            plan = cut["plan"]
            self.assertEqual(sorted(plan["inside"]), want)
            self.assertEqual(sorted(plan["outside"]), sorted(set(m.elements) - set(want)))
            keep = set(cut["keep"])
            if kind == "partial":
                self.assertEqual(keep, expected_keep(m, nids, want), name)
                self.assertEqual(set(plan["cut_nodes"]), keep, name)
                faces = set(tuple(f) for g in plan["groups"] for f in g["faces"])
                self.assertEqual(faces, expected_faces(m, nids, want), name)
            else:
                shared = nodes_of(m, want) & nodes_of(m, set(m.elements) - set(want))
                self.assertTrue(shared <= keep <= expected_keep(m, nids, m.elements), name)
            n = np.array(cut["normal"], float)
            self.assertAlmostEqual(float(np.linalg.norm(n)), 1.0, 12)
            p0 = np.mean([m.ref[q - 1] for q in nids], axis=0)
            # the normal points away from the chosen side
            self.assertTrue(all(np.dot(centroid(m, e) - p0, n) < 0 for e in want), name)
        self.assertEqual(seen[1][0], -seen[-1][0], name + ": side -1 is not the other side")
        for a, b in zip(seen[1][1]["normal"], seen[-1][1]["normal"]):
            self.assertAlmostEqual(a, -b, 12)

    def test_full_section_hex20(self):
        self.check("hex20_full")

    def test_full_section_hex20_corners_only(self):
        # the midside nodes come from the mesh, also when the user left them out
        self.check("hex20_full_corners")
        a = node_cut(model("n_hex20")[1], section("hex20_full")[2], 1)
        b = node_cut(model("n_hex20")[1], section("hex20_full_corners")[2], 1)
        self.assertEqual(sorted(a["elements"]), sorted(b["elements"]))

    def test_full_section_line_quad(self):
        self.check("lq_full")

    def test_full_section_tet10(self):
        self.check("tet10_full")

    def test_oblique_section_on_tet_faces(self):
        self.check("tet10_diagonal")

    def test_unshared_selected_node_stays_full(self):
        # the step face lies in the plane, belongs to one side only, and is selected
        m, mesh, nids, dist, kinds, layers = section("step_full")
        self.assertTrue(len(set(nids) - (nodes_of(m, side_elements(m, dist, 1)))) > 0)
        self.check("step_full")

    def test_partial_section_hex20(self):
        self.check("hex20_upper")

    def test_partial_section_corners_only(self):
        self.check("hex20_upper_corners")
        a = node_cut(model("n_hex20")[1], section("hex20_upper")[2], -1)
        b = node_cut(model("n_hex20")[1], section("hex20_upper_corners")[2], -1)
        self.assertEqual(set(a["keep"]), set(b["keep"]))

    def test_partial_section_line_quad(self):
        self.check("lq_upper")

    def test_partial_section_tet10(self):
        self.check("tet10_upper")

    def test_u_full_from_the_end_partial_from_the_base(self):
        self.check("u_leg")

    def test_order_of_the_nodes_does_not_matter(self):
        for name in ("hex20_full", "tet10_diagonal", "hex20_upper", "u_leg"):
            m, mesh, nids, dist, kinds, layers = section(name)
            shuffled = list(nids)
            random.Random(7).shuffle(shuffled)
            for side in (1, -1):
                a = node_cut(mesh, nids, side)
                b = node_cut(mesh, shuffled, side)
                self.assertEqual(sorted(a["elements"]), sorted(b["elements"]), name)
                for p, q in zip(a["normal"], b["normal"]):
                    self.assertAlmostEqual(p, q, 12)

    def test_refusals(self):
        for name, tag, pick, code in REFUSALS:
            m, mesh = model(tag)
            nids = pick(m)
            for side in (1, -1):
                try:
                    node_cut(mesh, nids, side)
                except Refused as e:
                    self.assertTrue(e.code in (code if isinstance(code, tuple) else (code,)),
                                    "{0}: {1}".format(name, e.code))
                else:
                    self.fail("{0}: no refusal".format(name))

    def test_node_without_a_solid(self):
        m, mesh = model("n_hex20")
        nodes = dict(mesh["nodes"])
        lone = max(nodes) + 1
        nodes[lone] = (L / 2, B / 3, H / 3)
        nids = section("hex20_full")[2] + [lone]
        try:
            node_cut(dict(mesh, nodes=nodes), nids, 1)
        except Refused as e:
            self.assertEqual(e.code, "nodes_without_solid")
        else:
            self.fail("no refusal")


# ---- 2. the references themselves --------------------------------------------------------------
class ReferenceFixtures(unittest.TestCase):
    """The layer runs agree with statics: the partial references can be trusted."""

    def layer_against_statics(self, tag, rank=None, bar=BAR):
        m, mesh = model(tag)
        folder, man, z, scratch = base(tag)
        large = man["deformation"] != "PETIT"
        ranks = sorted(int(k[2:]) for k in z if k.startswith("U_"))
        rank = ranks[-1] if rank is None else rank
        if tag == "n_u":
            name, dist = "u_leg", SECTIONS["u_leg"][2]
        else:
            name, dist = "hex20_full", SECTIONS["hex20_full"][2]
        nids = SELECT[SECTIONS[name][1]](m)
        point = np.mean([m.xyz[n - 1] for n in nids], axis=0)
        u = z["U_%d" % rank][:len(m.xyz)] if large else None
        load = load_size(m)
        sums = {}
        body = grow(m, nids, dist, 1)
        rest = sorted(set(m.elements) - set(body))
        for sign, layer, chosen in ((1, "LP", body), (-1, "LM", rest)):
            points = expected_points(m, nids, chosen, "full")
            f, c = layer_sum(z, layer, rank, points, point, large)
            fx, cx = statics(m, chosen, point, u)
            ef, em = relative(np.concatenate([f, c]), fx, cx, size_of(m), load)
            report("reference %s %s rank %d: eF %.1e eM %.1e, %d nodes" % (
                tag, layer, rank, ef, em, len(points)))
            self.assertTrue(ef < bar and em < bar, "eF %.1e eM %.1e" % (ef, em))
            sums[sign] = (f, c)
        # the two layers balance node by node on the plane: free nodes
        at = dict((key(p), i) for i, p in enumerate(z["xyz"]))
        idx = [at[q] for q in expected_points(m, nids, body, "full")]
        both = z["R_LP_%d" % rank][idx] + z["R_LM_%d" % rank][idx]
        biggest = np.abs(z["R_LP_%d" % rank][idx]).max()
        self.assertTrue(np.abs(both).max() < 1e-8 * biggest + BAR_REST, np.abs(both).max())

    @needs_base("n_hex20")
    def test_hex20(self):
        self.layer_against_statics("n_hex20")

    @needs_base("n_lq")
    def test_line_quad(self):
        self.layer_against_statics("n_lq")

    @needs_base("n_tet10")
    def test_tet10(self):
        self.layer_against_statics("n_tet10")

    @needs_base("n_u")
    def test_u(self):
        self.layer_against_statics("n_u")

    @needs_base("n_nl")
    def test_nonlinear_last_step(self):
        self.layer_against_statics("n_nl", bar=BAR_STEP)

    @needs_base("n_lq")
    def test_line_quad_adds_midside_nodes(self):
        m, mesh = model("n_lq")
        z = base("n_lq")[2]
        self.assertTrue(len(z["xyz"]) > len(m.xyz))

    def test_no_load_on_a_layer(self):
        # a loaded face in a layer would need its skin cell in the reference run
        if sm is None:
            self.skipTest("no numpy")
        for tag in MODELS:
            m = model(tag)[0]
            layer = set(e for es in m.layers.values() for e in es)
            for kind, name, value in m.loads:
                self.assertFalse(layer & set(e for e, f in m.faces[name]), tag)


# ---- 3. full sections through the chain: statics ------------------------------------------------
class FullSection(unittest.TestCase):
    def run_both(self, name, bar=BAR):
        m, mesh, nids, dist, kinds, layers = section(name)
        point = tuple(np.mean([m.xyz[n - 1] for n in nids], axis=0))
        load = load_size(m)
        sums = {}
        for side in (1, -1):
            cut, result, less, per = follow(name, side)
            sign = geometric_side(m, cut["elements"], dist)
            if kinds[sign] != "full":
                continue
            self.assertFalse(cut["partial"])
            chosen = sorted(cut["elements"])
            got = set(key(r["xyz"]) for r in less["nodes"])
            self.assertEqual(got, expected_points(m, nids, chosen, "full"), name)
            s, idx = total(less, per, 1, point)
            self.assertEqual(len(idx), len(less["nodes"]))
            fx, cx = statics(m, chosen, point)
            ef, em = relative(s, fx, cx, size_of(m), load)
            free = not nodes_of(m, chosen) & m.fixed_nodes()
            rest = result["rest"][1]
            report("%s side %d: eF %.1e eM %.1e, %d nodes, rest %d (%.1e N)" % (
                name, side, ef, em, len(idx), rest["count"], rest["largest"]))
            self.assertTrue(ef < bar and em < bar, "eF %.1e eM %.1e" % (ef, em))
            if free:
                # a true free body: the equilibrium check stays valid
                self.assertTrue(cut["rest_valid"])
                self.assertEqual(rest["count"], 0)
                self.assertTrue(rest["largest"] < BAR_REST)
            sums[side] = s
        if len(sums) == 2:
            scale = max(np.abs(sums[1][:3]).max(), np.abs(sums[1][3:]).max() / size_of(m))
            self.assertTrue(np.abs(sums[1] + sums[-1]).max() < 1e-9 * scale * size_of(m),
                            "the two sides are not opposite")
        return sums

    @needs_cut("n_hex20")
    def test_hex20(self):
        self.run_both("hex20_full")

    @needs_cut("n_hex20")
    def test_hex20_corners_only(self):
        self.run_both("hex20_full_corners")

    @needs_cut("n_lq")
    def test_line_quad(self):
        self.run_both("lq_full")
        cut, result, less, per = follow("lq_full", 1)
        self.assertTrue(result["extra_nodes"])
        self.assertTrue(any(r["nid"] is None for r in less["nodes"]))

    @needs_cut("n_tet10")
    def test_tet10(self):
        self.run_both("tet10_full")

    @needs_cut("n_tet10")
    def test_tet10_oblique(self):
        self.run_both("tet10_diagonal")

    @needs_cut("n_step")
    def test_unshared_selected_node(self):
        self.run_both("step_full")


# ---- 4. partial sections: the layer reference ---------------------------------------------------
class PartialSection(unittest.TestCase):
    def run_both(self, name, ranks=None, bar=BAR_SAME):
        m, mesh, nids, dist, kinds, layers = section(name)
        folder, man, z, scratch = base(SECTIONS[name][0])
        point = tuple(np.mean([m.xyz[n - 1] for n in nids], axis=0))
        load = load_size(m)
        sums = {}
        for side in (1, -1):
            cut, result, less, per = follow(name, side)
            sign = geometric_side(m, cut["elements"], dist)
            if kinds[sign] != "partial":
                continue
            self.assertTrue(cut["partial"])
            self.assertFalse(cut["rest_valid"])
            self.assertTrue("partial_section" in cut["warnings"])
            chosen = sorted(cut["elements"])
            points = expected_points(m, nids, chosen, "partial")
            got = [key(r["xyz"]) for r in less["nodes"]]
            self.assertEqual(len(got), len(set(got)))
            self.assertEqual(set(got), points, name)
            # the run itself has the nodes behind the layer too: the filter took them out
            self.assertTrue(len(result["nodes"]) > len(less["nodes"]))
            at = dict((key(p), i) for i, p in enumerate(z["xyz"]))
            idx = [at[q] for q in got]
            steps = ranks or [s["rank"] for s in result["steps"]]
            for rank in steps:
                ref = z["R_%s_%d" % (layers[sign], rank)][idx]
                mine = np.array(less["forces"][rank])[:, :3]
                biggest = max(np.abs(ref).max(), 1e-30)
                # every force stays at its own node
                self.assertTrue(np.abs(mine - ref).max() < BAR_SAME * biggest + 1e-12,
                                "%s rank %d: %.1e of %.1e N" % (
                                    name, rank, np.abs(mine - ref).max(), biggest))
                disp = np.array(less["disp"][rank])
                self.assertTrue(np.abs(disp - z["U_%d" % rank][idx]).max() <
                                1e-9 * max(np.abs(z["U_%d" % rank]).max(), 1e-30))
                large = any(r["large"] for r in less["nodes"])
                f, c = layer_sum(z, layers[sign], rank, points, point, large)
                s, used = total(less, per, rank, point)
                self.assertEqual(sorted(used), list(range(len(less["nodes"]))))
                ef, em = relative(s, f, c, size_of(m), load)
                self.assertTrue(ef < bar and em < bar, "eF %.1e eM %.1e" % (ef, em))
                sums.setdefault(rank, {})[side] = s
            report("%s side %d: %d of %d nodes, %d steps, last eF %.1e eM %.1e" % (
                name, side, len(less["nodes"]), len(result["nodes"]), len(steps), ef, em))
        for rank, both in sums.items():
            if len(both) == 2 and not any(r["large"] for r in less["nodes"]):
                # the other side: the same nodes, the opposite force (free nodes)
                scale = max(np.abs(both[1][:3]).max(), np.abs(both[1][3:]).max() / size_of(m), load)
                self.assertTrue(np.abs(both[1] + both[-1]).max() < 1e-9 * scale * size_of(m))
        return sums

    @needs_cut("n_hex20")
    def test_hex20(self):
        self.run_both("hex20_upper")

    @needs_cut("n_hex20")
    def test_hex20_corners_only(self):
        self.run_both("hex20_upper_corners")

    @needs_cut("n_lq")
    def test_line_quad(self):
        self.run_both("lq_upper")
        cut, result, less, per = follow("lq_upper", 1)
        self.assertTrue(any(r["nid"] is None for r in less["nodes"]))

    @needs_cut("n_tet10")
    def test_tet10(self):
        self.run_both("tet10_upper")

    @needs_cut("n_nl")
    def test_nonlinear_back_nodes(self):
        # many steps, x + u, nodes behind the layer in the run: forces and
        # displacements stay with their node in every step
        sums = self.run_both("nl_upper", bar=BAR_SAME)
        cut, result, less, per = follow("nl_upper", 1)
        self.assertTrue(result["large"])
        self.assertTrue(len(sums) > 2)


# ---- 5. the U: full from the end, partial from the base -----------------------------------------
class UShape(unittest.TestCase):
    @needs_cut("n_u")
    def test_both_sides(self):
        full = FullSection("run_both").run_both("u_leg")
        part = PartialSection("run_both").run_both("u_leg")
        m = model("n_u")[0]
        self.assertEqual(len(full), 1)
        self.assertEqual(sorted(part), [1])
        a = list(full.values())[0]
        b = list(part[1].values())[0]
        scale = max(np.abs(a[:3]).max(), np.abs(a[3:]).max() / size_of(m))
        # the same nodes, the same force through the plane, from the other side
        self.assertTrue(np.abs(a + b).max() < 1e-9 * scale * size_of(m), np.abs(a + b).max())


# ---- building the bases -----------------------------------------------------------------------
POST_COMM = r"""POURSUITE(LANG='EN')
import json
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


FBM = @RESULT@.getMesh()
with open('fort.32') as fb_f:
    fb_sel = json.load(fb_f)
for fb_n in sorted(fb_sel):
    FBM.setGroupOfCells(str(fb_n), [i - 1 for i in fb_sel[fb_n]])
fb_count = FBM.getNumberOfNodes()
fb_ranks = [int(k) for k in @RESULT@.getIndexes()]
fb_arrays = {"xyz": fb_np.asarray(FBM.getCoordinates().getValues(), dtype=float).reshape(-1, 3),
             "ranks": fb_np.array(fb_ranks)}
for fb_k in fb_ranks:
    fb_arrays["U_%d" % fb_k] = fb_field(@RESULT@.getField("DEPL", fb_k), fb_count)
for fb_n in sorted(fb_sel):
    fb_rs = CALC_CHAMP(RESULTAT=@RESULT@, GROUP_MA=str(fb_n), FORCE='REAC_NODA')
    for fb_k in fb_ranks:
        fb_arrays["R_%s_%d" % (fb_n, fb_k)] = fb_field(fb_rs.getField("REAC_NODA", fb_k), fb_count)
with open("fort.34", "wb") as fb_f:
    fb_np.savez(fb_f, **fb_arrays)
FIN()
"""


def post(folder, man, m, temp):
    """REAC_NODA of each layer over all nodes, and U, per rank: post.npz."""
    work = os.path.join(folder, "post")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    pos = dict((n, i + 1) for i, n in enumerate(man["cells"]))
    sel = dict((name, [pos["M%d" % e] for e in eids]) for name, eids in m.layers.items())
    with open(os.path.join(work, "sel.json"), "w") as f:
        json.dump(sel, f)
    with open(os.path.join(work, "post.comm"), "w", newline="\n") as f:
        f.write(POST_COMM.replace("@RESULT@", man["concepts"]["result"]))
    lines = ["P actions make_etude", "P time_limit 1800",
             "P memory_limit %d" % max(man.get("memory_limit") or 2048, 2048),
             "P mpi_nbcpu 1", "P ncpus 1", "P no-mpi true", "F comm post.comm D 1",
             "F mess post.mess R 6", "F libr sel.json D 32", "F libr post.npz R 34",
             "R base %s D 0" % os.path.join(folder, man["base"])]
    with open(os.path.join(work, "post.export"), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    env = dict(os.environ, TEMP=temp, TMP=temp)
    with open(os.path.join(work, "console.txt"), "w") as f:
        rc = subprocess.call('cmd /c ""{0}" post.export"'.format(EXE), cwd=work, env=env,
                             stdout=f, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
    done = os.path.join(work, "post.npz")
    if rc != 0 or not os.path.isfile(done):
        return False
    shutil.move(done, os.path.join(folder, "post.npz"))
    shutil.rmtree(work, True)
    return True


def build(bridge, work, tag):
    """A base through solids_build.py --one (the real bridge code), then post."""
    m = model(tag)[0]
    if not os.path.isdir(work):
        os.makedirs(work)
    liml = os.path.join(work, tag + ".liml")
    m.write(liml)
    general = dict({"keep_base": True, "keep_base_runs": 2}, **m.general)
    general["ncpus"] = 1                        # the PC is shared
    cfg = {"general": general, "settings": m.settings,
           "analysis": "nonlin_static_3d" if m.steps else "lin_static_3d"}
    cfg_path = os.path.join(work, tag + "_cfg.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    temp = os.path.join(work, "tmp")
    if not os.path.isdir(temp):
        os.makedirs(temp)
    env = dict(os.environ, TEMP=temp, TMP=temp, PYTHONDONTWRITEBYTECODE="1")
    folder = os.path.join(work, tag)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-B", os.path.join(HERE, "solids_build.py"), "--one",
                        bridge, folder, liml, cfg_path], env=env, capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    runs = fb_aster.find_runs(folder, None) if os.path.isdir(folder) else []
    print("%-8s %-7s %5.0f s, %4d elements" % (tag, "ok" if runs else "NO BASE", time.time() - t0,
                                               len(m.elements)))
    if not runs:
        print(r.stdout[-400:], r.stderr[-400:])
        return
    t0 = time.time()
    print("  post", post(folder, runs[0], m, temp), "%.0f s" % (time.time() - t0))
    sys.stdout.flush()


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        sys.dont_write_bytecode = True
        where_to = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "WorkDir", "nodecut")
        for t in sys.argv[4:] or sorted(MODELS):
            build(sys.argv[2], os.path.abspath(where_to), t)
    else:
        unittest.main()
