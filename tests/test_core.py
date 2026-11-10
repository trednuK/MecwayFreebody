# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_core.py
# Unit tests of Scripts/fb_core.py with exact values. No Mecway, no Code-Aster,
# no numpy: the same file also runs in Mecway's IronPython (test_core_ipy.py).
# Run: python -m unittest discover -s tests

import math
import os
import random
import sys
import time
import unittest

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # Mecway's script engine
    HERE = os.environ.get("FB_TESTS", ".")
sys.path.insert(0, os.path.join(HERE, "..", "Scripts"))
import fb_core
from fb_core import Refused

HEX_CORNERS = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
               (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
HEX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7))
HEX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7),
             (4, 5), (5, 6), (6, 7), (7, 4))
WEDGE_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 4), (2, 5), (3, 4), (4, 5),
               (5, 3))
TET_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
PYR_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4))
TET_SPLIT = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6),
             (0, 5, 1, 6))


class Builder(object):
    """A self-made mesh, with node numbers merged by position."""

    def __init__(self):
        self.mesh = {"nodes": {}, "elements": {}}
        self.keys = {}

    def node(self, p):
        key = tuple(int(math.floor(c * 1e9 + 0.5)) for c in p)
        if key not in self.keys:
            nid = len(self.keys) + 1
            self.keys[key] = nid
            self.mesh["nodes"][nid] = tuple(float(c) for c in p)
        return self.keys[key]

    def element(self, shape, nids):
        eid = len(self.mesh["elements"]) + 1
        self.mesh["elements"][eid] = (shape, list(nids))
        return eid

    def solid(self, shape, corners, pairs=None):
        """An element from corner positions, midsides straight if pairs."""
        nids = [self.node(p) for p in corners]
        if pairs:
            for a, b in pairs:
                mid = [(corners[a][k] + corners[b][k]) / 2.0 for k in range(3)]
                nids.append(self.node(mid))
        return self.element(shape, nids)


def _det(a, b, c):
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) +
            a[2] * (b[0] * c[1] - b[1] * c[0]))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def fill_cell(b, shape, x0, d):
    """Fill the box from x0 with size d with elements of one shape, conformal
    with the next box. Returns their numbers."""
    c = [tuple(x0[k] + q[k] * d[k] for k in range(3)) for q in HEX_CORNERS]
    if shape == "hex8":
        return [b.solid("hex8", c)]
    if shape == "hex20":
        return [b.solid("hex20", c, HEX_EDGES)]
    if shape in ("wedge6", "wedge15"):
        pairs = WEDGE_EDGES if shape == "wedge15" else None
        return [b.solid(shape, [c[i] for i in t], pairs)
                for t in ((0, 1, 2, 4, 5, 6), (0, 2, 3, 4, 6, 7))]
    if shape in ("tet4", "tet10"):
        pairs = TET_EDGES if shape == "tet10" else None
        out = []
        for t in TET_SPLIT:
            v = [c[i] for i in t]
            if _det(_sub(v[1], v[0]), _sub(v[2], v[0]), _sub(v[3], v[0])) < 0:
                v[1], v[2] = v[2], v[1]
            out.append(b.solid(shape, v, pairs))
        return out
    pairs = PYR_EDGES if shape == "pyr13" else None
    mid = tuple(x0[k] + d[k] / 2.0 for k in range(3))
    out = []
    for face in HEX_FACES:
        # the base seen from the apex runs the other way than the outward face
        out.append(b.solid(shape, [c[i] for i in reversed(face)] + [mid], pairs))
    return out


def bar(shape, nx=4, ny=1, nz=1, size=(4.0, 2.0, 1.0)):
    """A bar along x, cut in cells; {(i, j, k): [eid]}."""
    b = Builder()
    d = (size[0] / nx, size[1] / ny, size[2] / nz)
    cells = {}
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                cells[(i, j, k)] = fill_cell(b, shape, (i * d[0], j * d[1], k * d[2]), d)
    return b, cells


def eids(cells, test):
    return [e for key, v in cells.items() if test(*key) for e in v]


HEX20_STEPS = ((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0), (0, 0, 2), (2, 0, 2), (2, 2, 2),
               (0, 2, 2), (1, 0, 0), (2, 1, 0), (1, 2, 0), (0, 1, 0), (0, 0, 1), (2, 0, 1),
               (2, 2, 1), (0, 2, 1), (1, 0, 2), (2, 1, 2), (1, 2, 2), (0, 1, 2))
# Seconds of the speed tests, for the report of the run in IronPython
SPEED = {}


def grid_hex20(nx, ny, nz, h):
    """A block of hex20; elements numbered layer by layer in z."""
    ids = {}
    nodes = {}
    elements = {}
    eid = 0
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                eid += 1
                nids = []
                for a, b, c in HEX20_STEPS:
                    key = (2 * i + a, 2 * j + b, 2 * k + c)
                    nid = ids.get(key)
                    if nid is None:
                        nid = len(ids) + 1
                        ids[key] = nid
                        nodes[nid] = (key[0] * h / 2, key[1] * h / 2, key[2] * h / 2)
                    nids.append(nid)
                elements[eid] = ("hex20", nids)
    return {"nodes": nodes, "elements": elements}


class TestSpeed(unittest.TestCase):
    def test_selection_of_20000_hex20(self):
        nx = 28
        mesh = grid_hex20(nx, nx, 28, 0.01)
        chosen = [e for e in mesh["elements"] if nx * nx < e <= 27 * nx * nx][:20000]
        t0 = time.time()
        plan = fb_core.plan_cuts(mesh, chosen)
        t1 = time.time()
        self.assertEqual(len(chosen), 20000)
        geos = [fb_core.section_geometry(mesh, g) for g in plan["groups"]]
        t2 = time.time()
        records = [{"index": n, "xyz": mesh["nodes"][n]} for n in plan["cut_nodes"]]
        result = {"nodes": records, "extra_nodes": False}
        per = fb_core.assign_nodes(plan, mesh, result)
        t3 = time.time()
        forces = [(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)] * len(records)
        xyz = [r["xyz"] for r in records]
        for g in plan["groups"]:
            idx = per[g["id"]]
            fb_core.resultant([xyz[i] for i in idx], [forces[i] for i in idx], (0.0, 0.0, 0.0))
        t4 = time.time()
        SPEED.update(plan_cuts=t1 - t0, section_geometry=t2 - t1, assign_nodes=t3 - t2,
                     resultant=t4 - t3, cut_nodes=len(records),
                     cut_faces=sum(len(g["faces"]) for g in plan["groups"]),
                     groups=len(plan["groups"]), elements=len(mesh["elements"]))
        self.assertTrue(abs(sum(g["area"] for g in geos) - 2 * (0.28 * 0.28)) < 1.0)
        self.assertTrue(t4 - t0 < 60, str(SPEED))


class Close(unittest.TestCase):
    def close(self, a, b, tol=1e-12):
        if isinstance(a, (tuple, list)):
            self.assertEqual(len(a), len(b))
            for x, y in zip(a, b):
                self.close(x, y, tol)
        else:
            self.assertTrue(abs(a - b) <= tol, "{0!r} is not {1!r}".format(a, b))


class TestPlan(Close):
    def test_middle_of_a_bar(self):
        b = Builder()
        for i in range(3):
            fill_cell(b, "hex8", (float(i), 0.0, 0.0), (1.0, 1.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, [2])
        self.assertEqual(plan["inside"], [2])
        self.assertEqual(plan["outside"], [1, 3])
        self.assertEqual(len(plan["cut_nodes"]), 8)
        self.assertEqual(plan["warnings"], [])
        self.assertEqual(len(plan["groups"]), 2)
        first, second = plan["groups"]
        self.assertEqual((first["id"], second["id"]), (1, 2))
        # hex: face 6 is x low (3 0 4 7), face 4 is x high (1 2 6 5)
        self.assertEqual(first["faces"], [(2, 6)])
        self.assertEqual(second["faces"], [(2, 4)])
        self.assertEqual(first["kind"], "solid")
        x = b.mesh["nodes"]
        self.assertTrue(all(x[n][0] == 1.0 for n in first["nodes"]))
        self.assertTrue(all(x[n][0] == 2.0 for n in second["nodes"]))

    def test_every_shape_two_cuts(self):
        counts = {"hex8": 9, "hex20": 21, "wedge6": 9, "wedge15": 21, "tet4": 9,
                  "tet10": 25, "pyr5": 9, "pyr13": 21}
        for shape, count in counts.items():
            b, cells = bar(shape, 4, 2, 2)
            plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: i in (1, 2)))
            self.assertEqual(len(plan["groups"]), 2, shape)
            self.assertEqual(plan["warnings"], [], shape)
            for group in plan["groups"]:
                self.assertEqual(len(group["nodes"]), count, shape)
                self.assertTrue(group["faces"], shape)
            self.assertEqual(sorted(plan["cut_nodes"]),
                             sorted(plan["groups"][0]["nodes"] + plan["groups"][1]["nodes"]))

    def test_midside_nodes_are_cut_nodes(self):
        b, cells = bar("hex20", 3)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        self.assertEqual(sum(len(g["nodes"]) for g in plan["groups"]), 16)

    def test_groups_sharing_nodes_are_one(self):
        # L of two cuts around a corner: a step in the selection
        b, cells = bar("hex8", 2, 2, 1, (2.0, 2.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(len(plan["groups"][0]["faces"]), 2)

    def test_one_element_thick_selection_keeps_two_cuts(self):
        b, cells = bar("hex20", 3)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        self.assertEqual(len(plan["groups"]), 2)

    def test_corner_contact_is_its_own_group_with_warning(self):
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        c = [(p[0] + 1, p[1] + 1, p[2] + 1) for p in HEX_CORNERS]
        d = b.solid("hex8", c)
        plan = fb_core.plan_cuts(b.mesh, [a])
        self.assertEqual(plan["warnings"], ["edge_contact"])
        self.assertEqual(len(plan["cut_nodes"]), 1)
        self.assertEqual(plan["groups"][0]["faces"], [])
        self.assertEqual(plan["outside"], [d])

    def test_edge_contact_nodes_join_each_other(self):
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        c = [(p[0] + 1, p[1] + 1, p[2]) for p in HEX_CORNERS]
        b.solid("hex8", c)
        plan = fb_core.plan_cuts(b.mesh, [a])
        self.assertEqual(plan["warnings"], ["edge_contact"])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(len(plan["groups"][0]["nodes"]), 2)

    def test_edge_contact_joins_the_group_it_touches(self):
        # a block on its neighbour, and a third block touching along an edge
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        b.solid("hex8", [(p[0] - 1, p[1], p[2]) for p in HEX_CORNERS])
        b.solid("hex8", [(p[0] + 1, p[1] + 1, p[2]) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, [a])
        self.assertEqual(plan["warnings"], ["edge_contact"])
        self.assertEqual(len(plan["cut_nodes"]), 6)
        self.assertEqual(len(plan["groups"]), 2)
        self.assertEqual(sorted(len(g["nodes"]) for g in plan["groups"]), [2, 4])

    def test_edge_contact_next_to_a_cut_joins_it(self):
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        b.solid("hex8", [(p[0] - 1, p[1], p[2]) for p in HEX_CORNERS])
        b.solid("hex8", [(p[0], p[1] + 1, p[2] + 1) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, [a])
        # the edge at y = z = 1 runs from the cut at x = 0 to the node at x = 1
        self.assertEqual(plan["warnings"], ["edge_contact"])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(len(plan["groups"][0]["nodes"]), 5)

    def edge_bridge(self):
        """Bar of three, the middle selected, and an element outside on one
        edge along the middle one."""
        b, cells = bar("hex8", 3, 1, 1, (3.0, 1.0, 1.0))
        b.solid("hex8", [(p[0] + 1, p[1] + 1, p[2] + 1) for p in HEX_CORNERS])
        return b, fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])

    def test_opposite_cuts_joined_by_an_edge(self):
        b, plan = self.edge_bridge()
        self.assertEqual(plan["warnings"], ["edge_merge"])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(len(plan["groups"][0]["nodes"]), 8)
        self.assertEqual(sorted(f for e, f in plan["groups"][0]["faces"]), [4, 6])

    def test_no_edge_merge_without_the_bridge(self):
        b, cells = bar("hex8", 3, 1, 1, (3.0, 1.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        self.assertEqual(plan["warnings"], [])
        self.assertEqual(len(plan["groups"]), 2)

    def test_edge_merge_does_not_depend_on_the_order(self):
        b, plan = self.edge_bridge()
        keys = sorted(b.mesh["elements"], reverse=True)
        turned = {"nodes": b.mesh["nodes"], "elements": dict(
            (len(keys) + 1 - e, b.mesh["elements"][e]) for e in keys)}
        again = fb_core.plan_cuts(turned, [len(keys) + 1 - 2])
        self.assertEqual(again["warnings"], ["edge_merge"])

    def test_no_edge_merge_for_a_contact_next_to_a_cut(self):
        # the off-face node has no cut faces of its own: only edge_contact
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        b.solid("hex8", [(p[0] - 1, p[1], p[2]) for p in HEX_CORNERS])
        b.solid("hex8", [(p[0], p[1] + 1, p[2] + 1) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, [a])
        self.assertEqual(plan["warnings"], ["edge_contact"])

    def test_no_cut(self):
        b, cells = bar("hex8", 2)
        plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: True))
        self.assertEqual(plan["warnings"], ["no_cut"])
        self.assertEqual(plan["groups"], [])
        self.assertEqual(plan["cut_nodes"], [])

    def test_order_does_not_matter(self):
        b, cells = bar("tet10", 4, 2, 2)
        chosen = eids(cells, lambda i, j, k: i in (1, 2))
        first = fb_core.plan_cuts(b.mesh, chosen)
        random.Random(1).shuffle(chosen)
        self.assertEqual(fb_core.plan_cuts(b.mesh, chosen), first)

    def test_quadratic_next_to_linear(self):
        b = Builder()
        a = b.solid("hex20", HEX_CORNERS, HEX_EDGES)
        b.solid("hex8", [(p[0] + 1, p[1], p[2]) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, [a])
        self.assertEqual(plan["warnings"], ["midside_not_shared"])
        self.assertEqual(len(plan["cut_nodes"]), 4)

    def test_refusals(self):
        b, cells = bar("hex8", 2)
        n = b.mesh["elements"][1][1]
        shell = b.element("quad4", n[:4])
        beam = b.element("line2", n[:2])
        odd = b.element("hex27", n)
        point = b.element("point1", n[:1])
        for chosen, code in (([], "empty"), ([99], "unknown_element"), ([odd], "shape"),
                             ([1, point], "shape")):
            try:
                fb_core.plan_cuts(b.mesh, chosen)
            except Refused as e:
                self.assertEqual(e.code, code)
            else:
                self.fail("no refusal for {0}".format(chosen))
        # Phase 4: shells and beams are no refusal
        fb_core.plan_cuts(b.mesh, [1, shell])
        fb_core.plan_cuts(b.mesh, [beam])

    def test_shell_outside_on_a_selected_face(self):
        # Phase 4: a skin shell, not a cut; its nodes are a node contact
        b, cells = bar("hex8", 2)
        b.element("quad4", b.mesh["elements"][1][1][:4])
        plan = fb_core.plan_cuts(b.mesh, [1])
        self.assertTrue("skin_shell" in plan["warnings"])
        self.assertTrue("node_contact" in plan["warnings"])
        self.assertFalse("edge_contact" in plan["warnings"])


def section_of(shape, nx=4, ny=2, nz=2, size=(4.0, 2.0, 1.0), at=2):
    b, cells = bar(shape, nx, ny, nz, size)
    plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: i < at))
    return b, plan


def quad8_block(edit=None):
    """Two hex20 side by side, cut at x = 1. edit(builder) moves nodes."""
    b, cells = bar("hex20", 2, 1, 1, (2.0, 1.0, 1.0))
    if edit:
        edit(b)
    return b, fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])


class TestGeometry(Close):
    def test_flat_section_of_every_shape(self):
        for shape in fb_core.SOLID_SHAPES:
            b, plan = section_of(shape)
            self.assertEqual(len(plan["groups"]), 1, shape)
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            self.close(g["area"], 2.0)
            self.close(g["centroid"], (2.0, 1.0, 0.5))
            self.assertTrue(g["planar"], shape)
            self.close(g["normal"], (1.0, 0.0, 0.0))
            # 2 wide in y, 1 high in z: the larger second moment is about z
            self.close(g["axes"][1], (0.0, 0.0, 1.0))
            self.close(g["axes"][2], (0.0, -1.0, 0.0))
            self.close(g["inertia"], (8.0 / 12, 2.0 / 12), 1e-11)

    def test_normal_is_outward_from_the_selection(self):
        b, cells = bar("hex8", 3)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        low = fb_core.section_geometry(b.mesh, plan["groups"][0])
        high = fb_core.section_geometry(b.mesh, plan["groups"][1])
        self.close(low["normal"], (-1.0, 0.0, 0.0))
        self.close(high["normal"], (1.0, 0.0, 0.0))

    def test_normal_of_an_element_inside_out(self):
        b, cells = bar("hex8", 2)
        shape, n = b.mesh["elements"][1]
        b.mesh["elements"][1] = (shape, n[4:] + n[:4])
        plan = fb_core.plan_cuts(b.mesh, [1])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(g["normal"], (1.0, 0.0, 0.0))

    def test_opposite_cut_stays_right_handed(self):
        b, cells = bar("hex8", 3)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(g["axes"][1], (0.0, 0.0, 1.0))
        self.close(g["axes"][2], (0.0, 1.0, 0.0))

    def test_quad8_with_a_curved_edge_is_exact(self):
        # top edge of the section, z = 1 + d(y), parabola with height s
        s = 0.3

        def edit(b):
            nid = [n for n, p in b.mesh["nodes"].items()
                   if p == (1.0, 0.5, 1.0)][0]
            b.mesh["nodes"][nid] = (1.0, 0.5, 1.0 + s)
        b, plan = quad8_block(edit)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        area = 1 + 2 * s / 3
        first = 0.5 + 2 * s / 3 + 4 * s * s / 15
        second = (1 + 2 * s + 8 * s * s / 5 + 16 * s ** 3 / 35) / 3
        self.close(g["area"], area)
        self.close(g["centroid"], (1.0, 0.5, first / area))
        self.assertTrue(g["planar"])
        izz = second - first * first / area
        # int (y - .5)^2 (1 + d(y)) dy
        iyy = 1.0 / 12 + s / 30
        self.close(sorted(g["inertia"]), sorted((izz, iyy)), 1e-11)
        # negative control: straight sides miss the cap
        self.assertTrue(abs(area - 1.0) > 0.1)

    def test_tri6_with_a_curved_edge_is_exact(self):
        for shape in ("tet10", "wedge15", "pyr13"):
            # a cap of 2/3 chord x height on one edge of a triangular face
            b = Builder()
            if shape == "wedge15":
                top = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1)]
                c1 = [tuple(float(v) for v in p) for p in top]
                c2 = [(p[0], p[1], p[2] - 1.0) for p in c1]
                a = b.solid("wedge15", c1, WEDGE_EDGES)
                b.solid("wedge15", c2, WEDGE_EDGES)
                chord = 2.0 ** 0.5
                base = 0.5
                mid = (0.5, 0.5, 1.0 - 1.0)
            elif shape == "tet10":
                p = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)]
                q = [p[0], p[2], p[1], (0.0, 0.0, -1.0)]
                a = b.solid("tet10", p, TET_EDGES)
                b.solid("tet10", q, TET_EDGES)
                chord = 2.0 ** 0.5
                base = 0.5
                mid = (0.5, 0.5, 0.0)
            else:
                # tri6 faces of two pyramids against each other, plane y = 0
                p = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
                     (0.5, 0.5, 1.0)]
                q = [(1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, -1.0, 0.0), (1.0, -1.0, 0.0),
                     (0.5, 0.0, 1.0)]
                p[4] = (0.5, 0.0, 1.0)
                a = b.solid("pyr13", p, PYR_EDGES)
                b.solid("pyr13", q, PYR_EDGES)
                chord = 1.0
                base = 0.5
                mid = (0.5, 0.0, 0.0)
            height = 0.2
            direction = (1 / 2.0 ** 0.5, 1 / 2.0 ** 0.5, 0.0)
            if shape == "pyr13":
                direction = (0.0, 0.0, -1.0)
            nid = [n for n, x in b.mesh["nodes"].items() if x == mid][0]
            b.mesh["nodes"][nid] = tuple(mid[k] + height * direction[k] for k in range(3))
            plan = fb_core.plan_cuts(b.mesh, [a])
            faces = plan["groups"][0]["faces"]
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            self.assertEqual(len(faces), 1, shape)
            self.close(g["area"], base + 2.0 / 3 * chord * height, 1e-12)
            self.assertTrue(g["planar"], shape)

    def test_ring_of_hex20_is_exact(self):
        # parabolic arcs: polygon + 2/3 chord x height per segment, both circles
        n = 16
        ri, ro = 1.0, 2.0
        b = Builder()
        first = []
        for layer in (0, 1):
            for i in range(n):
                t0 = 2 * math.pi * i / n
                t1 = 2 * math.pi * (i + 1) / n
                tm = (t0 + t1) / 2

                def at(r, t, z):
                    return (r * math.cos(t), r * math.sin(t), float(z))
                z0, z1 = layer, layer + 1
                c = [at(ri, t0, z0), at(ro, t0, z0), at(ro, t1, z0), at(ri, t1, z0),
                     at(ri, t0, z1), at(ro, t0, z1), at(ro, t1, z1), at(ri, t1, z1)]
                nids = [b.node(p) for p in c]
                rm = (ri + ro) / 2
                mids = [at(rm, t0, z0), at(ro, tm, z0), at(rm, t1, z0), at(ri, tm, z0),
                        at(ri, t0, z0 + .5), at(ro, t0, z0 + .5), at(ro, t1, z0 + .5),
                        at(ri, t1, z0 + .5),
                        at(rm, t0, z1), at(ro, tm, z1), at(rm, t1, z1), at(ri, tm, z1)]
                nids += [b.node(p) for p in mids]
                e = b.element("hex20", nids)
                if layer == 0:
                    first.append(e)
        plan = fb_core.plan_cuts(b.mesh, first)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])

        def disc(r):
            half = math.pi / n
            polygon = n * r * r * math.sin(2 * half) / 2
            return polygon + n * 2.0 / 3 * (2 * r * math.sin(half)) * (r * (1 - math.cos(half)))
        self.close(g["area"], disc(ro) - disc(ri), 1e-11)
        self.close(g["centroid"], (0.0, 0.0, 1.0), 1e-11)
        self.close(g["normal"], (0.0, 0.0, 1.0))
        # negative control: straight sides are visibly off
        half = math.pi / n
        straight = n * math.sin(2 * half) / 2 * (ro * ro - ri * ri)
        self.assertTrue(abs(g["area"] - straight) > 0.02)
        self.assertTrue(abs(g["area"] / (math.pi * 3) - 1) < 2e-4)
        # a round section: the axes follow the global axes, not noise
        self.close(g["axes"][1], (1.0, 0.0, 0.0))
        self.close(g["axes"][2], (0.0, 1.0, 0.0))
        self.assertEqual(len(g["outline"]), 2)

    def test_warped_surface_against_fine_quadrature(self):
        # a dome on one hex20 face: the area is not a polynomial
        def edit(b):
            for n, p in b.mesh["nodes"].items():
                if p[0] == 1.0:
                    u = 2 * p[1] - 1
                    v = 2 * p[2] - 1
                    b.mesh["nodes"][n] = (1.0 + 0.2 * (1 - u * u) + 0.1 * v * v, p[1], p[2])
        b, plan = quad8_block(edit)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertFalse(g["planar"])
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)
        self.assertEqual(g["outline"], [])
        shape, nids = b.mesh["elements"][1]
        local = fb_core.face_local_nodes(shape, plan["groups"][0]["faces"][0][1])
        pts = [b.mesh["nodes"][nids[i]] for i in local]
        steps = 300
        area = 0.0
        for i in range(steps):
            for j in range(steps):
                r = -1 + (2 * i + 1.0) / steps
                s = -1 + (2 * j + 1.0) / steps
                n, dr, ds = fb_core._sf_quad8(r, s)
                t1 = [sum(c * p[k] for c, p in zip(dr, pts)) for k in range(3)]
                t2 = [sum(c * p[k] for c, p in zip(ds, pts)) for k in range(3)]
                v = fb_core._cross(t1, t2)
                area += math.sqrt(fb_core._dot(v, v)) * (2.0 / steps) ** 2
        self.close(g["area"], area, 2e-5)
        self.assertTrue(g["area"] > 1.02)

    def test_step_is_not_planar(self):
        b, cells = bar("hex8", 2, 2, 1, (2.0, 2.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertFalse(g["planar"])
        self.close(g["area"], 2.0)
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)
        self.close(g["centroid"], (0.75, 0.75, 0.5))

    def test_opposite_faces_have_no_normal(self):
        b, cells = bar("hex8", 3, 1, 1, (3.0, 1.0, 1.0))
        b.solid("hex8", [(p[0] + 1, p[1] + 1, p[2] + 1) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertFalse(g["planar"])
        self.assertEqual(g["normal"], (0.0, 0.0, 0.0))
        self.assertTrue("no_normal" in g["warnings"])
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)
        self.close(g["area"], 2.0)

    def test_ordinary_cut_has_a_normal_without_warning(self):
        b, plan = section_of("hex8")
        self.assertEqual(fb_core.section_geometry(b.mesh, plan["groups"][0])["warnings"], [])

    def test_small_kink_is_not_planar(self):
        def edit(b):
            for n, p in b.mesh["nodes"].items():
                if p[0] == 1.0 and p[1] == 0.5:
                    b.mesh["nodes"][n] = (1.0 + 1e-3, p[1], p[2])
        b, cells = bar("hex8", 2, 2, 1, (2.0, 1.0, 1.0))
        edit(b)
        plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: i == 0))
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertFalse(g["planar"])

    def test_pyramid_lateral_faces(self):
        # one pyramid out of a cube: four triangles, non-planar, exact area
        b = Builder()
        ids = fill_cell(b, "pyr5", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, ids[:1])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(sorted(f for e, f in plan["groups"][0]["faces"]), [1, 2, 3, 4])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(g["area"], 4 * 0.5 * (0.5 ** 0.5))
        self.assertFalse(g["planar"])

    def test_weighted_centroid_two_materials(self):
        b, cells = bar("hex8", 2, 2, 1, (2.0, 2.0, 1.0))
        chosen = eids(cells, lambda i, j, k: i == 0)
        plan = fb_core.plan_cuts(b.mesh, chosen)
        lower, upper = cells[(0, 0, 0)][0], cells[(0, 1, 0)][0]
        props = {lower: {"E": 100e9}, upper: {"E": 300e9}}
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], props)
        self.close(g["centroid"], (1.0, 1.25, 0.5))
        self.close(g["area"], 2.0)
        plain = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(plain["centroid"], (1.0, 1.0, 0.5))
        same = fb_core.section_geometry(b.mesh, plan["groups"][0],
                                        {lower: {"E": 7.0}, upper: {"E": 7.0}})
        self.close(same["centroid"], plain["centroid"])

    def test_weighted_axes_turn_with_the_stiffness(self):
        # L from two rectangles, the one with E twice the other: exact tensor
        b = Builder()
        c1 = fill_cell(b, "hex8", (0.0, 0.0, 0.0), (1.0, 3.0, 1.0))
        c2 = fill_cell(b, "hex8", (1.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        e1 = fill_cell(b, "hex8", (0.0, 0.0, 1.0), (1.0, 3.0, 1.0))
        e2 = fill_cell(b, "hex8", (1.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        # conformal enough: only the shared face matters here, so tie by hand
        n1 = set(b.mesh["elements"][e1[0]][1])
        plan = fb_core.plan_cuts(b.mesh, c1 + c2)
        self.assertTrue(n1)
        self.assertEqual(sum(len(g["faces"]) for g in plan["groups"]), 2)
        group = plan["groups"][0]
        self.assertEqual(len(plan["groups"]), 1)
        w = {c1[0]: 2.0, c2[0]: 1.0}
        g = fb_core.section_geometry(b.mesh, group, dict((k, {"E": v}) for k, v in w.items()))
        # (w, area, cy of x, cy of y, width x, width y)
        parts = [(2.0, 3.0, 0.5, 1.5, 1.0, 3.0), (1.0, 1.0, 1.5, 0.5, 1.0, 1.0)]
        total = sum(p[0] * p[1] for p in parts)
        cx = sum(p[0] * p[1] * p[2] for p in parts) / total
        cy = sum(p[0] * p[1] * p[3] for p in parts) / total
        self.close(g["centroid"][:2], (cx, cy))
        ixx = sum(p[0] * (p[1] * p[4] ** 2 / 12 + p[1] * (p[2] - cx) ** 2) for p in parts)
        iyy = sum(p[0] * (p[1] * p[5] ** 2 / 12 + p[1] * (p[3] - cy) ** 2) for p in parts)
        ixy = sum(p[0] * p[1] * (p[2] - cx) * (p[3] - cy) for p in parts)
        moment = lambda u: (ixx * u[0] * u[0] + 2 * ixy * u[0] * u[1] + iyy * u[1] * u[1])
        a, b_axis = g["axes"][1], g["axes"][2]
        # principal: no product, and b is the direction of the largest spread
        self.close(ixx * a[0] * b_axis[0] + ixy * (a[0] * b_axis[1] + a[1] * b_axis[0]) +
                   iyy * a[1] * b_axis[1], 0.0, 1e-12)
        self.assertTrue(moment(b_axis) > moment(a))
        self.close(_det(*g["axes"]), 1.0)

    def test_incomplete_props_fall_back_with_a_warning(self):
        b, cells = bar("hex8", 2, 2, 1, (2.0, 2.0, 1.0))
        chosen = eids(cells, lambda i, j, k: i == 0)
        plan = fb_core.plan_cuts(b.mesh, chosen)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], {chosen[0]: {"E": 1.0}})
        self.assertEqual(g["warnings"], ["E_missing"])
        self.close(g["centroid"], (1.0, 1.0, 0.5))

    def test_group_without_faces(self):
        b = Builder()
        a = b.solid("hex8", HEX_CORNERS)
        b.solid("hex8", [(p[0] + 1, p[1] + 1, p[2]) for p in HEX_CORNERS])
        plan = fb_core.plan_cuts(b.mesh, [a])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertEqual(g["area"], 0.0)
        self.close(g["centroid"], (1.0, 1.0, 0.5))
        self.assertFalse(g["planar"])


def rotation(axis, angle):
    """Rotation matrix (Rodrigues)."""
    n = fb_core._unit(axis)
    c = math.cos(angle)
    s = math.sin(angle)
    x, y, z = n
    return ((c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s),
            (y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s),
            (z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)))


def turned(r, p):
    return tuple(r[i][0] * p[0] + r[i][1] * p[1] + r[i][2] * p[2] for i in range(3))


class TestAxes(Close):
    def test_turned_rectangle(self):
        for axis, angle in (((1, 0, 0), 0.4), ((1, 2, 3), 1.1), ((0, 1, 0), 2.3),
                            ((-1, 1, 0.5), 4.0), ((0, 0, 1), math.pi / 2)):
            b, plan = section_of("hex20")
            r = rotation(axis, angle)
            for n in list(b.mesh["nodes"]):
                b.mesh["nodes"][n] = turned(r, b.mesh["nodes"][n])
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            self.assertTrue(g["planar"])
            self.close(g["area"], 2.0, 1e-11)
            self.close(g["normal"], turned(r, (1.0, 0.0, 0.0)), 1e-12)
            self.close(_det(*g["axes"]), 1.0)
            # a along the short side of the section (turned z, up to the sign)
            self.close(abs(fb_core._dot(g["axes"][1], turned(r, (0.0, 0.0, 1.0)))), 1.0, 1e-10)
            self.close(abs(fb_core._dot(g["axes"][2], turned(r, (0.0, 1.0, 0.0)))), 1.0, 1e-10)
            self.close(g["inertia"], (8.0 / 12, 2.0 / 12), 1e-10)
            a = g["axes"][1]
            big = max(a, key=abs)
            self.assertTrue(big > 0)

    def test_no_sign_flips_between_runs(self):
        b, cells = bar("tet10", 3, 2, 3, (3.0, 2.0, 3.5))
        r = rotation((1, 2, 3), 0.7)
        for n in list(b.mesh["nodes"]):
            b.mesh["nodes"][n] = turned(r, b.mesh["nodes"][n])
        chosen = eids(cells, lambda i, j, k: i < 2)
        plan = fb_core.plan_cuts(b.mesh, chosen)
        group = plan["groups"][0]
        first = fb_core.section_geometry(b.mesh, group)
        again = fb_core.section_geometry(b.mesh, group)
        self.assertEqual(first, again)
        rng = random.Random(2)
        for _ in range(5):
            faces = list(group["faces"])
            rng.shuffle(faces)
            g = fb_core.section_geometry(b.mesh, dict(group, faces=faces))
            self.close(g["axes"], first["axes"], 1e-11)

    def test_axis_at_45_degrees_keeps_its_sign(self):
        for angle in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4):
            b, plan = section_of("hex8")
            r = rotation((1, 0, 0), angle)
            for n in list(b.mesh["nodes"]):
                b.mesh["nodes"][n] = turned(r, b.mesh["nodes"][n])
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            a = g["axes"][1]
            self.assertTrue(a[1] > 0, str(a))

    def test_square_follows_the_global_axes(self):
        b, plan = section_of("hex8", 2, 1, 1, (2.0, 1.0, 1.0), 1)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(g["axes"][1], (0.0, 1.0, 0.0))
        self.close(g["axes"][2], (0.0, 0.0, 1.0))

    def test_tilted_normal_is_unit_and_axes_orthogonal(self):
        b, plan = section_of("wedge15")
        r = rotation((3, -1, 2), 0.9)
        for n in list(b.mesh["nodes"]):
            b.mesh["nodes"][n] = turned(r, b.mesh["nodes"][n])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        n, a, c = g["axes"]
        for u in (n, a, c):
            self.close(fb_core._dot(u, u), 1.0)
        for u, v in ((n, a), (n, c), (a, c)):
            self.close(fb_core._dot(u, v), 0.0)


class TestOutline(Close):
    def test_rectangle(self):
        b, plan = section_of("hex8", 4, 2, 2)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertEqual(len(g["outline"]), 1)
        loop = g["outline"][0]
        self.assertEqual(len(loop), 8)
        self.close(max(p[0] for p in loop), 0.5)
        self.close(min(p[0] for p in loop), -0.5)
        self.close(max(p[1] for p in loop), 1.0)
        self.close(min(p[1] for p in loop), -1.0)

    def test_closed_area_of_the_loop(self):
        for shape in ("hex20", "tet10", "wedge6"):
            b, plan = section_of(shape, 4, 3, 2)
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            loop = g["outline"][0]
            shoelace = 0.0
            for i in range(len(loop)):
                u0, v0 = loop[i]
                u1, v1 = loop[(i + 1) % len(loop)]
                shoelace += u0 * v1 - u1 * v0
            self.close(abs(shoelace) / 2, g["area"], 1e-11)

    def test_element_inside_out_keeps_the_loop_closed(self):
        for shape in ("hex8", "hex20"):
            b, cells = bar(shape, 2, 2, 2, (2.0, 2.0, 2.0))
            plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: i == 0))
            clean = fb_core.section_geometry(b.mesh, plan["groups"][0])
            # one element of the section inside out: top and bottom swapped
            e = cells[(0, 0, 0)][0]
            name, n = b.mesh["elements"][e]
            turned = n[4:8] + n[:4]
            if shape == "hex20":
                turned += n[16:20] + n[12:16] + n[8:12]
            b.mesh["elements"][e] = (name, turned)
            plan = fb_core.plan_cuts(b.mesh, eids(cells, lambda i, j, k: i == 0))
            g = fb_core.section_geometry(b.mesh, plan["groups"][0])
            self.close(g["area"], clean["area"])
            self.close(g["normal"], (1.0, 0.0, 0.0))
            self.assertEqual(len(g["outline"]), 1, shape)
            loop = g["outline"][0]
            self.assertEqual(len(loop), len(clean["outline"][0]), shape)
            shoelace = 0.0
            for i in range(len(loop)):
                u0, v0 = loop[i]
                u1, v1 = loop[(i + 1) % len(loop)]
                shoelace += u0 * v1 - u1 * v0
            self.close(abs(shoelace) / 2, g["area"], 1e-12)

    def test_element_inside_out_with_a_curved_edge(self):
        s = 0.3
        b, cells = bar("hex20", 2, 1, 1, (2.0, 1.0, 1.0))
        nid = [n for n, p in b.mesh["nodes"].items() if p == (1.0, 0.5, 1.0)][0]
        b.mesh["nodes"][nid] = (1.0, 0.5, 1.0 + s)
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])
        clean = fb_core.section_geometry(b.mesh, plan["groups"][0])
        e = cells[(0, 0, 0)][0]
        name, n = b.mesh["elements"][e]
        b.mesh["elements"][e] = (name, n[4:8] + n[:4] + n[16:20] + n[12:16] + n[8:12])
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(sorted((round(u, 9), round(v, 9)) for u, v in g["outline"][0]),
                   sorted((round(u, 9), round(v, 9)) for u, v in clean["outline"][0]), 1e-8)

    def test_hole_gives_a_second_loop(self):
        b, cells = bar("hex8", 2, 3, 3, (2.0, 3.0, 3.0))
        chosen = eids(cells, lambda i, j, k: i == 0)
        del b.mesh["elements"][cells[(1, 1, 1)][0]]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.close(g["area"], 8.0)
        self.assertEqual(sorted(len(q) for q in g["outline"]), [4, 12])

    def test_curved_edge_follows_the_parabola(self):
        s = 0.3

        def edit(b):
            nid = [n for n, p in b.mesh["nodes"].items() if p == (1.0, 0.5, 1.0)][0]
            b.mesh["nodes"][nid] = (1.0, 0.5, 1.0 + s)
        b, plan = quad8_block(edit)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        cz = g["centroid"][2]
        loop = g["outline"][0]
        self.assertEqual(len(loop), 3 + 4)
        top = max(p[1] if abs(g["axes"][2][2]) > 0.5 else p[0] for p in loop)
        self.close(abs(top), 1.0 + s - cz, 1e-12)

    def test_non_planar_has_no_outline(self):
        b, cells = bar("hex8", 2, 2, 1, (2.0, 2.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0])
        self.assertEqual(g["outline"], [])


class TestAssign(Close):
    def setUp(self):
        b, cells = bar("hex8", 3)
        self.mesh = b.mesh
        self.plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])

    def records(self, extra=()):
        out = []
        for n in self.plan["cut_nodes"]:
            out.append({"index": n - 1, "xyz": self.mesh["nodes"][n]})
        for p in extra:
            out.append({"index": 9999, "xyz": p})
        return out

    def test_every_node_in_its_group(self):
        result = {"nodes": self.records(), "extra_nodes": False}
        per = fb_core.assign_nodes(self.plan, self.mesh, result)
        self.assertEqual(sorted(per), [1, 2])
        for group in self.plan["groups"]:
            want = sorted(self.mesh["nodes"][n] for n in group["nodes"])
            got = sorted(result["nodes"][i]["xyz"] for i in per[group["id"]])
            self.assertEqual(want, got)

    def test_midside_nodes_go_to_the_nearest_group(self):
        x = self.mesh["nodes"][self.plan["groups"][1]["nodes"][0]][0]
        mids = [(x, 1.0, 0.0), (x, 1.0, 1.0), (x, 0.0, 0.5), (x, 2.0, 0.5)]
        result = {"nodes": self.records(mids), "extra_nodes": True}
        per = fb_core.assign_nodes(self.plan, self.mesh, result)
        self.assertEqual(len(per[1]), 4)
        self.assertEqual(len(per[2]), 8)

    def test_link_gives_mecway_numbers(self):
        x = self.mesh["nodes"][self.plan["groups"][1]["nodes"][0]][0]
        result = {"nodes": self.records([(x, 1.0, 0.0)]), "extra_nodes": True}
        per = fb_core.link_nodes(self.plan, self.mesh, result)
        for record, n in zip(result["nodes"], self.plan["cut_nodes"]):
            self.assertEqual(record["nid"], n)
        self.assertTrue(result["nodes"][-1]["nid"] is None)
        self.assertEqual(sorted(len(v) for v in per.values()), [4, 5])

    def test_link_never_refuses(self):
        result = {"nodes": self.records([(1.0, 1.0, 0.0)])[2:], "extra_nodes": False}
        per = fb_core.link_nodes(self.plan, self.mesh, result)
        self.assertEqual(sum(len(v) for v in per.values()), len(result["nodes"]))

    def test_coordinates_a_little_off_are_the_same_node(self):
        result = {"nodes": self.records(), "extra_nodes": False}
        for r in result["nodes"]:
            r["xyz"] = tuple(c + 2e-9 for c in r["xyz"])
        per = fb_core.assign_nodes(self.plan, self.mesh, result)
        self.assertEqual(len(per[1]) + len(per[2]), 8)

    def test_missing_node_is_refused(self):
        result = {"nodes": self.records()[:-1], "extra_nodes": False}
        self.assertRaises(Refused, fb_core.assign_nodes, self.plan, self.mesh, result)

    def test_stray_node_is_refused_when_the_run_added_none(self):
        result = {"nodes": self.records([(1.0, 1.0, 0.0)]), "extra_nodes": False}
        self.assertRaises(Refused, fb_core.assign_nodes, self.plan, self.mesh, result)

    def test_no_midside_nodes_after_extra_nodes_is_refused(self):
        result = {"nodes": self.records(), "extra_nodes": True}
        self.assertRaises(Refused, fb_core.assign_nodes, self.plan, self.mesh, result)

    def test_far_point_is_still_found(self):
        grid = fb_core._Grid([((0.0, 0.0, 0.0), "a"), ((1.0, 0.0, 0.0), "b")])
        self.assertEqual(grid.nearest((50.0, 3.0, -2.0))[1], "b")
        self.close(grid.nearest((-3.0, 0.0, 0.0))[0], 9.0)

    def test_grid_agrees_with_brute_force(self):
        rng = random.Random(3)
        items = [((rng.random(), rng.random(), 0.0), i) for i in range(400)]
        grid = fb_core._Grid(items)
        for _ in range(300):
            p = (rng.uniform(-.2, 1.2), rng.uniform(-.2, 1.2), rng.uniform(-.1, .1))
            d = [((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2, i)
                 for q, i in items]
            self.assertEqual(grid.nearest(p), min(d))


class TestStatics(Close):
    def test_resultant_of_two_forces(self):
        xyz = [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
        f = [(0.0, 10.0, 0.0, 0.0, 0.0, 0.0), (3.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
        self.close(fb_core.resultant(xyz, f, (0.0, 0.0, 0.0)),
                   (3.0, 10.0, 0.0, 0.0, 0.0, 10.0 - 6.0))

    def test_nodal_moments_count(self):
        s = fb_core.resultant([(5.0, 0.0, 0.0)], [(0.0, 0.0, 0.0, 1.0, 2.0, 3.0)],
                              (0.0, 0.0, 0.0))
        self.close(s, (0.0, 0.0, 0.0, 1.0, 2.0, 3.0))

    def test_mismatch_is_an_error(self):
        self.assertRaises(ValueError, fb_core.resultant, [(0.0, 0.0, 0.0)], [], (0, 0, 0))

    def test_shift_equals_a_new_sum(self):
        rng = random.Random(4)
        xyz = [(rng.random(), rng.random(), rng.random()) for _ in range(30)]
        f = [tuple(rng.uniform(-5, 5) for _ in range(6)) for _ in range(30)]
        p = (0.3, -0.2, 0.9)
        q = (-1.0, 4.0, 2.0)
        self.close(fb_core.shift(fb_core.resultant(xyz, f, p), p, q),
                   fb_core.resultant(xyz, f, q), 1e-11)

    def test_shift_there_and_back(self):
        s = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
        p = (1.0, 0.0, 0.0)
        q = (0.0, 1.0, 2.0)
        self.close(fb_core.shift(fb_core.shift(s, p, q), q, p), s)

    def test_to_axes(self):
        axes = ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        self.close(fb_core.to_axes((1.0, 2.0, 3.0, 4.0, 5.0, 6.0), axes),
                   (3.0, 1.0, 2.0, 6.0, 4.0, 5.0))

    def test_tension_is_positive_on_both_cuts(self):
        # A bar along x pulled with 100 N: on the middle part the left part pulls
        # to -x and the right part to +x, whatever the code thinks of normals.
        b, cells = bar("hex8", 3, 1, 1, (3.0, 1.0, 1.0))
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        by_x = {1.0: (-25.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2.0: (25.0, 0.0, 0.0, 0.0, 0.0, 0.0)}
        seen = set()
        for group in plan["groups"]:
            g = fb_core.section_geometry(b.mesh, group)
            xyz = [b.mesh["nodes"][n] for n in group["nodes"]]
            self.assertEqual(len(set(p[0] for p in xyz)), 1)
            seen.add(xyz[0][0])
            s = fb_core.resultant(xyz, [by_x[xyz[0][0]]] * 4, g["centroid"])
            self.close(s, (by_x[xyz[0][0]][0] * 4, 0.0, 0.0, 0.0, 0.0, 0.0))
            self.close(fb_core.to_axes(s, g["axes"]), (100.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            pushed = tuple(-c for c in by_x[xyz[0][0]])
            s = fb_core.resultant(xyz, [pushed] * 4, g["centroid"])
            self.close(fb_core.to_axes(s, g["axes"])[0], -100.0)
        self.assertEqual(seen, set([1.0, 2.0]))

    def test_bending_stress_gives_the_moment(self):
        # sigma = k z on a hex20 section: consistent nodal forces of a quad8
        b, plan = section_of("hex20", 2, 1, 1, (2.0, 1.0, 2.0), 1)
        group = plan["groups"][0]
        g = fb_core.section_geometry(b.mesh, group)
        e, faceid = group["faces"][0]
        shape, nids = b.mesh["elements"][e]
        local = fb_core.face_local_nodes(shape, faceid)
        forces = dict((nids[i], [0.0] * 6) for i in local)
        cz = g["centroid"][2]
        pts = [b.mesh["nodes"][nids[i]] for i in local]
        k = 6.0
        for n, dr, ds, w in fb_core._FACE_RULES[8]:
            t1 = [sum(c * p[q] for c, p in zip(dr, pts)) for q in range(3)]
            t2 = [sum(c * p[q] for c, p in zip(ds, pts)) for q in range(3)]
            v = fb_core._cross(t1, t2)
            da = math.sqrt(fb_core._dot(v, v)) * w
            z = sum(c * p[2] for c, p in zip(n, pts))
            for c, i in zip(n, local):
                forces[nids[i]][0] += c * k * (z - cz) * da
        xyz = [b.mesh["nodes"][n] for n in forces]
        s = fb_core.resultant(xyz, list(forces.values()), g["centroid"])
        local6 = fb_core.to_axes(s, g["axes"])
        # N 0, moment k I about the strong axis; here b = z, a = y
        self.close(local6[0], 0.0, 1e-12)
        self.close(local6[4], k * 2.0 ** 3 * 1.0 / 12, 1e-11)
        # negative control: the midside nodes carry most of it
        corners = [xyz[i] for i, n in enumerate(forces) if n in nids[:8]]
        fc = [forces[n] for n in forces if n in nids[:8]]
        wrong = fb_core.to_axes(fb_core.resultant(corners, fc, g["centroid"]), g["axes"])
        self.assertTrue(abs(wrong[4] - local6[4]) > 0.5 * abs(local6[4]))


class TestPositions(Close):
    def setUp(self):
        self.result = {
            "nodes": [{"index": 0, "xyz": (1.0, 0.0, 0.0), "large": True},
                      {"index": 1, "xyz": (2.0, 0.0, 0.0), "large": False}],
            "disp": {3: [(0.5, 0.0, 0.0), (0.25, 0.0, 0.0)]}}

    def test_each_node_on_its_own_shape(self):
        self.assertEqual(fb_core.positions(self.result, 3),
                         [(1.5, 0.0, 0.0), (2.0, 0.0, 0.0)])

    def test_mixed_cut(self):
        self.assertTrue(fb_core.mixed_shape(self.result, [0, 1]))
        self.assertFalse(fb_core.mixed_shape(self.result, [0]))

    def test_x_plus_u_changes_the_moment(self):
        r = {"nodes": [{"index": 0, "xyz": (0.0, 1.0, 0.0), "large": True}],
             "disp": {1: [(0.0, 1.0, 0.0)]}}
        f = [(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
        on_x = fb_core.resultant([r["nodes"][0]["xyz"]], f, (0.0, 0.0, 0.0))
        on_u = fb_core.resultant(fb_core.positions(r, 1), f, (0.0, 0.0, 0.0))
        self.assertEqual((on_x[5], on_u[5]), (-1.0, -2.0))


class TestText(unittest.TestCase):
    def test_numbers(self):
        for value, text in ((0.3, "0.3"), (1.0, "1"), (-2.5, "-2.5"), (1234.5678, "1234.568"),
                            (1234567.0, "1234567"), (12345678.0, "1.234568E+07"),
                            (0.001, "0.001"), (0.00012345, "0.00012345"),
                            (0.000012345, "1.2345E-05"), (0.0, "0"), (9.99999999, "10"),
                            (-1e-20, "-1E-20"), (1e300, "1E+300"), (2.0e-300, "2E-300"),
                            (float("nan"), "nan"), (float("inf"), "inf")):
            self.assertEqual(fb_core.number_text(value), text)

    def test_decimal_comma(self):
        self.assertEqual(fb_core.number_text(0.1, ","), "0,1")
        self.assertEqual(fb_core.number_text(1.5e12, ","), "1,5E+12")

    def test_digits(self):
        self.assertEqual(fb_core.number_text(1.23456789, ".", 3), "1.23")

    def test_table(self):
        text = fb_core.table_text([["N", "Mz"], ["cut 1", 1200.5], [None, -0.25], [3, True]])
        self.assertEqual(text, "N\tMz\r\ncut 1\t1200,5\r\n\t-0,25\r\n3\tyes\r\n")

    def test_table_big_integer(self):
        big = 10 ** 30
        self.assertEqual(fb_core.table_text([[big]]), "1" + "0" * 30 + "\r\n")

    def test_table_decimal_point(self):
        self.assertEqual(fb_core.table_text([[0.5]], decimal="."), "0.5\r\n")


class TestFaces(unittest.TestCase):
    def test_tables_of_the_liml(self):
        self.assertEqual(fb_core.face_local_nodes("hex20", 1),
                         (0, 3, 2, 1, 11, 10, 9, 8))
        self.assertEqual(fb_core.face_local_nodes("hex20", 3),
                         (0, 1, 5, 4, 8, 13, 16, 12))
        self.assertEqual(fb_core.face_local_nodes("wedge15", 5),
                         (2, 0, 3, 5, 8, 9, 14, 11))
        self.assertEqual(fb_core.face_local_nodes("tet10", 4), (0, 3, 2, 7, 9, 6))
        self.assertEqual(fb_core.face_local_nodes("pyr13", 2), (1, 2, 4, 6, 11, 10))
        self.assertEqual(fb_core.face_local_nodes("pyr13", 5),
                         (0, 3, 2, 1, 8, 7, 6, 5))
        self.assertEqual(fb_core.face_local_nodes("pyr5", 4), (3, 0, 4))

    def test_faces_point_outward(self):
        for shape in fb_core.SOLID_SHAPES:
            b = Builder()
            first = fill_cell(b, shape, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))[0]
            s, nids = b.mesh["elements"][first]
            ncorner = fb_core._FAMILIES[s][2]
            mid = [sum(b.mesh["nodes"][n][k] for n in nids[:ncorner]) / ncorner
                   for k in range(3)]
            for f in range(1, len(fb_core._FAMILIES[s][0]) + 1):
                local = fb_core.face_local_nodes(s, f)
                pts = [b.mesh["nodes"][nids[i]] for i in local]
                area = (0.0, 0.0, 0.0)
                for n, dr, ds, w in fb_core._FACE_RULES[len(local)]:
                    t1 = [sum(c * p[q] for c, p in zip(dr, pts)) for q in range(3)]
                    t2 = [sum(c * p[q] for c, p in zip(ds, pts)) for q in range(3)]
                    v = fb_core._cross(t1, t2)
                    area = tuple(area[q] + v[q] * w for q in range(3))
                centre = [sum(p[q] for p in pts) / len(pts) for q in range(3)]
                self.assertTrue(fb_core._dot(area, _sub(centre, mid)) > 0, (s, f))


# ---- phase 4: shells, beams and mixed cuts -------------------------------------------------
X_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def plate(shape="quad4", nx=3, ny=1, size=(3.0, 1.0), points=None, flip=()):
    """A plate in z = 0 along x of shells of one shape, numbered by column.
    points(x, y) maps the plate; elements in flip get the other node order.
    Returns (builder, {(i, j): [eid]})."""
    b = Builder()
    where = points or (lambda x, y: (x, y, 0.0))
    dx = size[0] / nx
    dy = size[1] / ny
    cells = {}
    for i in range(nx):
        for j in range(ny):
            c = [(i * dx, j * dy), ((i + 1) * dx, j * dy), ((i + 1) * dx, (j + 1) * dy),
                 (i * dx, (j + 1) * dy)]
            out = []
            if shape in ("quad4", "quad8"):
                groups = [c]
            else:
                groups = [[c[0], c[1], c[2]], [c[0], c[2], c[3]]]
            for corners in groups:
                if (i, j) in flip:
                    corners = list(reversed(corners))
                nids = []
                count = len(corners)
                for k in range(count):
                    nids.append(b.node(where(*corners[k])))
                    if shape in ("quad8", "tri6"):
                        m = [(corners[k][q] + corners[(k + 1) % count][q]) / 2.0 for q in range(2)]
                        nids.append(b.node(where(*m)))
                out.append(b.element(shape, nids))
            cells[(i, j)] = out
    return b, cells


def line(b, points, shape="line2"):
    """Beams along a polyline; line3 with the midside node halfway."""
    out = []
    for p, q in zip(points[:-1], points[1:]):
        if shape == "line3":
            m = tuple((p[k] + q[k]) / 2.0 for k in range(3))
            out.append(b.element("line3", [b.node(p), b.node(m), b.node(q)]))
        else:
            out.append(b.element("line2", [b.node(p), b.node(q)]))
    return out


class TestShellPlan(Close):
    def test_plate_middle_column(self):
        b, cells = plate()
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        self.assertEqual(plan["warnings"], [])
        self.assertEqual(plan["drilling"], [])
        first, second = plan["groups"]
        # quad4 nodes (1,0) (2,0) (2,1) (1,1): edge 4 is 3-0 at x = 1, edge 2 at x = 2
        self.assertEqual(first["entities"], [("edge", 2, 4)])
        self.assertEqual(second["entities"], [("edge", 2, 2)])
        self.assertEqual((first["kind"], second["kind"]), ("shell", "shell"))
        self.assertEqual(first["faces"], [])
        self.assertEqual(len(first["nodes"]), 2)

    def test_every_shell_shape(self):
        for shape, count in (("quad4", 3), ("quad8", 5), ("tri3", 3), ("tri6", 5)):
            b, cells = plate(shape, 3, 2)
            plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)] + cells[(1, 1)])
            self.assertEqual(plan["warnings"], [], shape)
            self.assertEqual(len(plan["groups"]), 2, shape)
            for g in plan["groups"]:
                self.assertEqual(len(g["nodes"]), count, shape)
                self.assertEqual(len(g["entities"]), 2, shape)
                self.assertEqual(g["kind"], "shell")

    def test_edge_numbers_of_quad8_and_tri6(self):
        # each faceid names the corners k, k + 1 and the midside between them
        for shape in ("quad8", "tri6", "quad4", "tri3"):
            b, cells = plate(shape, 1, 1)
            e = cells[(0, 0)][0]
            nids = b.mesh["elements"][e][1]
            corners = fb_core._SHELLS[shape][0]
            for k in range(len(corners)):
                p0, p1, pm, n, t, w = fb_core.shell_edge(b.mesh, e, k + 1)
                self.close(p0, b.mesh["nodes"][nids[corners[k]]])
                self.close(p1, b.mesh["nodes"][nids[corners[(k + 1) % len(corners)]]])
                if pm is not None:
                    self.close(pm, tuple((p0[q] + p1[q]) / 2 for q in range(3)))

    def test_quad8_next_to_quad4(self):
        b = Builder()
        q8 = b.element("quad8", [b.node(p) for p in ((0, 0, 0), (.5, 0, 0), (1, 0, 0), (1, .5, 0),
                                                     (1, 1, 0), (.5, 1, 0), (0, 1, 0), (0, .5, 0))])
        b.element("quad4", [b.node(p) for p in ((1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0))])
        plan = fb_core.plan_cuts(b.mesh, [q8])
        self.assertEqual(plan["warnings"], ["midside_not_shared"])
        self.assertEqual(plan["groups"][0]["entities"], [("edge", q8, 2)])

    def test_shell_standing_on_a_block(self):
        # a plate on the top face of a hex, along one of its edges: no shell
        # neighbour, so no entity, and a node contact
        b = Builder()
        block = b.solid("hex8", HEX_CORNERS)
        fin = b.element("quad4", [b.node(p) for p in ((0, 0, 1), (1, 0, 1), (1, 0, 2), (0, 0, 2))])
        plan = fb_core.plan_cuts(b.mesh, [fin])
        self.assertTrue("node_contact" in plan["warnings"])
        self.assertFalse("edge_contact" in plan["warnings"])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(plan["groups"][0]["entities"], [])
        self.assertEqual(plan["groups"][0]["kind"], "shell")
        self.assertEqual(len(plan["groups"][0]["nodes"]), 2)
        self.assertEqual(plan["drilling"], ["other_element"])
        # the block itself: its top face has no solid neighbour either
        plan = fb_core.plan_cuts(b.mesh, [block])
        self.assertTrue("node_contact" in plan["warnings"])

    def test_skin_shell_on_an_outside_block(self):
        b = Builder()
        b.solid("hex8", HEX_CORNERS)
        skin = b.element("quad4", [b.node(p) for p in ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))])
        plan = fb_core.plan_cuts(b.mesh, [skin])
        self.assertTrue("skin_shell" in plan["warnings"])
        self.assertEqual(plan["groups"][0]["entities"], [])
        # two triangles cover the face: each is a skin shell too
        b = Builder()
        b.solid("hex8", HEX_CORNERS)
        t1 = b.element("tri3", [b.node(p) for p in ((0, 0, 1), (1, 0, 1), (1, 1, 1))])
        b.element("tri3", [b.node(p) for p in ((0, 0, 1), (1, 1, 1), (0, 1, 1))])
        plan = fb_core.plan_cuts(b.mesh, [t1])
        self.assertTrue("skin_shell" in plan["warnings"])
        # the second triangle is a shell neighbour over the diagonal: a real
        # cut between the two, the rest of the nodes a node contact
        self.assertEqual(sum(len(g["entities"]) for g in plan["groups"]), 1)
        self.assertTrue("node_contact" in plan["warnings"])

    def test_skin_shell_that_goes_on_as_a_plate(self):
        # a plate glued on the block and continuing past it: its edge to the
        # next plate is a strip
        b = Builder()
        b.solid("hex8", HEX_CORNERS)
        skin = b.element("quad4", [b.node(p) for p in ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))])
        b.element("quad4", [b.node(p) for p in ((1, 0, 1), (2, 0, 1), (2, 1, 1), (1, 1, 1))])
        plan = fb_core.plan_cuts(b.mesh, [skin])
        self.assertTrue("skin_shell" in plan["warnings"])
        self.assertEqual([g["entities"] for g in plan["groups"]], [[("edge", skin, 2)]])

    def test_no_skin_shell_for_a_plate_on_part_of_a_face(self):
        # negative: a plate with one corner off the face is no skin shell
        b = Builder()
        b.solid("hex8", HEX_CORNERS)
        fin = b.element("quad4", [b.node(p) for p in ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 2, 1))])
        plan = fb_core.plan_cuts(b.mesh, [fin])
        self.assertFalse("skin_shell" in plan["warnings"])

    def test_plate_edge_next_to_an_outside_beam(self):
        b, cells = plate("quad4", 1, 1)
        line(b, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0)])
        self.assertTrue("node_contact" in plan["warnings"])
        self.assertEqual(plan["groups"][0]["entities"], [])
        self.assertTrue("other_element" in plan["drilling"])

    def test_order_does_not_matter(self):
        b, cells = plate("tri6", 4, 2)
        chosen = [e for (i, j), v in cells.items() if i in (1, 2) for e in v]
        first = fb_core.plan_cuts(b.mesh, chosen)
        random.Random(3).shuffle(chosen)
        self.assertEqual(fb_core.plan_cuts(b.mesh, chosen), first)


class TestBeamPlan(Close):
    def test_middle_of_a_line(self):
        b = Builder()
        es = line(b, [(float(i), 0.0, 0.0) for i in range(4)])
        plan = fb_core.plan_cuts(b.mesh, [es[1]])
        self.assertEqual(plan["warnings"], [])
        first, second = plan["groups"]
        n1, n2 = b.mesh["elements"][es[1]][1]
        self.assertEqual(first["entities"], [("end", es[1], n1)])
        self.assertEqual(second["entities"], [("end", es[1], n2)])
        self.assertEqual((first["kind"], second["kind"]), ("beam", "beam"))

    def test_line3_ends_and_midside(self):
        b = Builder()
        es = line(b, [(float(i), 0.0, 0.0) for i in range(3)], "line3")
        plan = fb_core.plan_cuts(b.mesh, [es[0]])
        nids = b.mesh["elements"][es[0]][1]
        self.assertEqual(plan["groups"][0]["entities"], [("end", es[0], nids[2])])
        # something outside on the midside node: a node contact
        b.element("line2", [nids[1], b.node((0.5, 1.0, 0.0))])
        plan = fb_core.plan_cuts(b.mesh, [es[0]])
        self.assertTrue("node_contact" in plan["warnings"])

    def test_beam_along_a_cut(self):
        b, cells = bar("hex8", 2, 1, 1, (2.0, 1.0, 1.0))
        beam = line(b, [(1.0, 0.0, 0.0), (1.0, 1.0, 0.0)])[0]
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)] + [beam])
        self.assertTrue("beam_along_cut" in plan["warnings"])
        self.assertTrue("mixed_cut" in plan["warnings"])
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(plan["groups"][0]["kind"], "mixed")

    def test_one_beam_between_two_cuts_is_not_along(self):
        b = Builder()
        es = line(b, [(float(i), 0.0, 0.0) for i in range(3)])
        b.element("line2", [b.mesh["elements"][es[0]][1][0], b.node((0.0, 1.0, 0.0))])
        plan = fb_core.plan_cuts(b.mesh, [es[0]])
        self.assertFalse("beam_along_cut" in plan["warnings"])
        self.assertEqual(len(plan["groups"]), 2)

    def test_beam_ending_on_a_solid_cut_is_mixed(self):
        b, cells = bar("hex8", 2, 1, 1, (2.0, 1.0, 1.0))
        beam = line(b, [(1.0, 1.0, 1.0), (0.5, 2.0, 1.0)])[0]
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0, 0)] + [beam])
        self.assertEqual(plan["warnings"], ["mixed_cut"])
        self.assertEqual(plan["groups"][0]["kind"], "mixed")
        kinds = sorted(item[0] for item in plan["groups"][0]["entities"])
        self.assertEqual(kinds, ["end", "face"])


class TestDrilling(Close):
    def test_flat_plate_none(self):
        b, cells = plate("quad8", 3, 2)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)] + cells[(1, 1)])
        self.assertEqual(plan["drilling"], [])
        self.assertFalse("drilling" in plan["warnings"])

    def test_folded_plate(self):
        def fold(x, y):
            return (x, y, 0.0) if x <= 2.0 else (2.0, y, x - 2.0)
        b, cells = plate("quad4", 3, 1, points=fold)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        self.assertEqual(plan["drilling"], ["not_coplanar"])
        self.assertTrue("drilling" in plan["warnings"])

    def test_turned_flat_plate_is_coplanar(self):
        r = rotation((1.0, 2.0, 3.0), 0.7)
        b, cells = plate("tri6", 3, 2, points=lambda x, y: turned(r, (x, y, 0.0)))
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)] + cells[(1, 1)])
        self.assertEqual(plan["drilling"], [])

    def test_moment_and_coupling(self):
        b, cells = plate("quad4", 3, 1)
        own = b.mesh["elements"][cells[(1, 0)][0]][1]
        b.mesh["moment_nodes"] = [own[0]]
        b.mesh["coupled_nodes"] = [own[1]]
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        self.assertEqual(plan["drilling"], ["nodal_moment", "coupling"])
        # a moment beyond the cut spoils it as well (measured, 2.7e-2)
        far = b.mesh["elements"][cells[(2, 0)][0]][1]
        b.mesh["moment_nodes"] = [n for n in far if n not in own]
        b.mesh["coupled_nodes"] = []
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0)])["drilling"], ["nodal_moment"])
        # a moment or a coupling on a beam node, off the shells: no reason
        beam = line(b, [(5.0, 0.0, 0.0), (6.0, 0.0, 0.0)])[0]
        b.mesh["moment_nodes"] = [b.mesh["elements"][beam][1][1]]
        b.mesh["coupled_nodes"] = [b.mesh["elements"][beam][1][1]]
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0)])["drilling"], [])

    def test_moment_by_direction(self):
        # measured: an in-plane moment is clean, one about the normal is not
        b, cells = plate("quad4", 3, 1)
        tip = b.mesh["elements"][cells[(2, 0)][0]][1][1]
        b.mesh["moments"] = {tip: (2.0, 3.0, 0.0)}
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0)])["drilling"], [])
        b.mesh["moments"] = {tip: (2.0, 3.0, 1e-3)}
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0)])["drilling"], ["nodal_moment"])
        # a node without a direction counts
        b.mesh["moments"] = {}
        b.mesh["moment_nodes"] = [tip]
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0)])["drilling"], ["nodal_moment"])

    def test_fold_beyond_the_cut(self):
        # measured: a fold in the tip spoils both cuts (3.6e-5)
        def fold(x, y):
            return (x, y, 0.0) if x <= 2.5 else (2.5, y, x - 2.5)
        b, cells = plate("quad4", 3, 1, points=fold)
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0)])
        self.assertEqual(plan["drilling"], ["not_coplanar"])
        # a solid selection in a model with flat shells only: nothing
        b, cells = bar("hex8", 3)
        b.element("quad4", [b.node(p) for p in ((5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0))])
        self.assertEqual(fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])["drilling"], [])

    def test_beam_on_a_shell_node(self):
        b, cells = plate("quad4", 3, 1)
        line(b, [(1.0, 1.0, 0.0), (1.0, 1.0, 1.0)])
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        self.assertEqual(plan["drilling"], ["other_element"])


def strip_props(eids, t, e=210e9, offset=None):
    out = {}
    for eid in eids:
        out[eid] = {"E": e, "thickness": t}
        if offset is not None:
            out[eid]["offset"] = offset
    return out


def i_section(h=0.2, bw=0.1, tf=0.01, tw=0.006, tf_top=None, r=None, e_web=None):
    """An I of shells along x, three columns of length 1; flanges at y = +-h/2
    over z in (-bw/2, bw/2), web at z = 0. r: rotation of the whole. Returns
    (mesh, plan of the middle column, props)."""
    b = Builder()
    move = (lambda p: turned(r, p)) if r else (lambda p: p)
    props = {}
    top = tf if tf_top is None else tf_top
    for i in range(3):
        x0 = float(i)
        x1 = x0 + 1.0
        chosen = []
        quads = []
        for y, t in ((h / 2, top), (-h / 2, tf)):
            for z0, z1 in ((-bw / 2, 0.0), (0.0, bw / 2)):
                quads.append(([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], t, 210e9))
        for y0, y1 in ((-h / 2, 0.0), (0.0, h / 2)):
            quads.append(([(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)], tw,
                          e_web or 210e9))
        for corners, t, e in quads:
            eid = b.element("quad4", [b.node(move(p)) for p in corners])
            props[eid] = {"E": e, "thickness": t}
            chosen.append(eid)
        if i == 1:
            middle = chosen
    return b.mesh, fb_core.plan_cuts(b.mesh, middle), props


class TestStrips(Close):
    def test_one_strip(self):
        b, cells = plate("quad4", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(cells[(1, 0)], 0.01))
        self.close(g["area"], 0.01)
        self.close(g["centroid"], (2.0, 0.5, 0.0))
        self.assertTrue(g["planar"])
        n, t, w = g["axes"]
        self.close(n, (1.0, 0.0, 0.0))
        self.close(w, (0.0, 0.0, 1.0))
        self.close(t, fb_core._cross(w, n))
        self.close(g["inertia"], (0.0, 0.01 / 12))
        strip = g["strips"][0]
        self.close(strip["length"], 1.0)
        self.assertEqual(strip["t"], 0.01)
        self.assertEqual(g["warnings"], [])
        self.assertEqual(len(g["outline"]), 1)
        self.close(sorted(u for u, v in g["outline"][0]), [-0.5, -0.5, 0.5, 0.5])
        self.close(sorted(v for u, v in g["outline"][0]), [-0.005, -0.005, 0.005, 0.005])
        # the other cut: n is out of the selected element, -x
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], strip_props(cells[(1, 0)], 0.01))
        self.close(g["axes"][0], (-1.0, 0.0, 0.0))
        self.close(g["axes"][1], (0.0, -1.0, 0.0))

    def test_node_order_does_not_turn_the_axes(self):
        # the axes have a fixed sign of w; the strip keeps the normal of its
        # node order (for the offset)
        b, cells = plate("quad4", 3, 1, flip=[(1, 0)])
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(cells[(1, 0)], 0.01))
        self.close(g["axes"], ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.close(g["strips"][0]["w"], (0.0, 0.0, -1.0))
        self.assertEqual(g["axes_kind"], "strip")
        # mixed orientation in a flat set: the same axes
        b, cells = plate("quad4", 3, 2, size=(3.0, 2.0), flip=[(1, 0)])
        chosen = cells[(1, 0)] + cells[(1, 1)]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(chosen, 0.01))
        self.close(g["axes"], ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

    def test_outward_normal_by_geometry(self):
        # n against the direction from the element's centroid to the middle of
        # the edge, not from fb_core: every shape, both cuts, turned
        r = rotation((1.0, -2.0, 0.5), 0.9)
        for shape in ("quad4", "quad8", "tri3", "tri6"):
            for flip in ([], [(1, 0)]):
                b, cells = plate(shape, 3, 1, points=lambda x, y: turned(r, (x, y, 0.0)), flip=flip)
                plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
                for g in plan["groups"]:
                    for kind, e, faceid in g["entities"]:
                        nids = b.mesh["elements"][e][1]
                        pts = [b.mesh["nodes"][n] for n in nids]
                        centre = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
                        edge = [b.mesh["nodes"][n] for n in nids if n in g["nodes"]]
                        mid = [sum(p[k] for p in edge) / len(edge) for k in range(3)]
                        out = fb_core._unit(_sub(mid, centre))
                        n = fb_core.shell_edge(b.mesh, e, faceid)[3]
                        self.assertTrue(fb_core._dot(n, out) > 0.3, (shape, flip, e, faceid))

    def test_zero_thickness_is_missing(self):
        b, cells = plate("quad4", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(cells[(1, 0)], 0.0))
        self.assertTrue("thickness_missing" in g["warnings"])
        self.assertTrue(g["area"] is None)
        self.assertEqual(g["axes_kind"], "strip")

    def test_tension_is_positive(self):
        # the rest pulls the selection out along n at both cuts
        b, cells = plate("quad8", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        props = strip_props(cells[(1, 0)], 0.01)
        for g in plan["groups"]:
            geo = fb_core.section_geometry(b.mesh, g, props)
            n = geo["axes"][0]
            xyz = [b.mesh["nodes"][q] for q in g["nodes"]]
            forces = [(100.0 * n[0], 0.0, 0.0, 0.0, 0.0, 0.0)] * len(xyz)
            local = fb_core.to_axes(fb_core.resultant(xyz, forces, geo["centroid"]), geo["axes"])
            self.close(local, (100.0 * len(xyz), 0.0, 0.0, 0.0, 0.0, 0.0), 1e-9)

    def test_offset_moves_the_midline(self):
        b, cells = plate("quad4", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        g = fb_core.section_geometry(b.mesh, plan["groups"][1],
                                     strip_props(cells[(1, 0)], 0.01, offset=0.003))
        self.close(g["centroid"], (2.0, 0.5, 0.003))
        self.assertEqual(g["strips"][0]["offset"], 0.003)
        flipped, cells = plate("quad4", 3, 1, flip=[(1, 0)])
        plan = fb_core.plan_cuts(flipped.mesh, cells[(1, 0)])
        g = fb_core.section_geometry(flipped.mesh, plan["groups"][1],
                                     strip_props(cells[(1, 0)], 0.01, offset=0.003))
        # along the normal of the node order
        self.close(g["centroid"], (2.0, 0.5, -0.003))

    def test_curved_edge_of_quad8(self):
        # edge 2 of the selected quad8 is the parabola x = 1 + 0.5 (1 - s^2)
        b = Builder()
        pts = ((0, 0, 0), (.5, 0, 0), (1, 0, 0), (1.5, .5, 0), (1, 1, 0), (.5, 1, 0), (0, 1, 0),
               (0, .5, 0))
        q = b.element("quad8", [b.node(p) for p in pts])
        b.element("quad8", [b.node(p) for p in ((1, 0, 0), (2, 0, 0), (3, 0, 0), (3, .5, 0),
                                                (3, 1, 0), (2, 1, 0), (1, 1, 0), (1.5, .5, 0))])
        plan = fb_core.plan_cuts(b.mesh, [q])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], {q: {"thickness": 0.02}})
        # x'(s) = (-s, 0.5): |x'| = sqrt(s^2 + 1/4); L = int_-1^1 = sqrt(5)/2 + asinh(2)/4
        exact = math.sqrt(5.0) / 2 + math.log(2.0 + math.sqrt(5.0)) / 4
        self.close(g["strips"][0]["length"], exact, 1e-13)
        self.close(g["area"], 0.02 * exact, 1e-14)
        # centroid by a fine Simpson rule
        steps = 20000
        total = moment = 0.0
        for i in range(steps + 1):
            s = -1 + 2.0 * i / steps
            wgt = 1 if i in (0, steps) else (4 if i % 2 else 2)
            jac = math.sqrt(s * s + 0.25)
            total += wgt * jac
            moment += wgt * jac * (1 + 0.5 * (1 - s * s))
        self.close(g["centroid"][0], moment / total, 1e-11)
        self.close(g["centroid"][1], 0.5, 1e-12)
        self.assertFalse(g["planar"] and len(g["strips"]) > 1)
        self.close(g["axes"][0][2], 0.0)        # n at the middle of the edge
        self.close(g["axes"][0], (1.0, 0.0, 0.0))
        self.assertEqual(len(g["outline"][0]), 2 * (fb_core._OUTLINE_STEPS + 1))

    def test_flat_plate_cut_across_two_elements_keeps_n_t_w(self):
        b, cells = plate("quad4", 3, 2, size=(3.0, 2.0))
        chosen = cells[(1, 0)] + cells[(1, 1)]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(chosen, 0.01))
        self.close(g["axes"], ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        self.close(g["inertia"], (0.0, 0.01 * 2.0 ** 3 / 12), 1e-15)
        self.close(g["area"], 0.02)
        self.close(g["centroid"], (2.0, 1.0, 0.0))
        self.assertEqual(len(g["outline"]), 2)

    def test_thin_walled_i(self):
        h, bw, tf, tw = 0.2, 0.1, 0.01, 0.006
        mesh, plan, props = i_section(h, bw, tf, tw)
        # flanges and web are not in one plane: the drilling warning
        self.assertEqual(plan["warnings"], ["drilling"])
        self.assertEqual(plan["drilling"], ["not_coplanar"])
        self.assertEqual(len(plan["groups"]), 2)
        g = fb_core.section_geometry(mesh, plan["groups"][1], props)
        self.assertEqual(len(g["strips"]), 6)
        self.close(g["area"], 2 * bw * tf + h * tw, 1e-15)
        self.close(g["centroid"], (2.0, 0.0, 0.0), 1e-15)
        strong = tw * h ** 3 / 12 + 2 * bw * tf * (h / 2) ** 2
        weak = 2 * tf * bw ** 3 / 12
        self.close(g["inertia"], (strong, weak), 1e-17)
        self.assertTrue(g["planar"])
        n, a, b_ = g["axes"]
        self.close(n, (1.0, 0.0, 0.0))
        self.close(a, (0.0, 0.0, 1.0))           # bending about z is the strong axis
        self.close(b_, fb_core._cross(n, a))
        self.assertEqual(len(g["outline"]), 6)
        self.assertEqual(g["axes_kind"], "section")

    def test_thin_walled_i_turned(self):
        r = rotation((0.3, -1.0, 2.0), 1.1)
        h, bw, tf, tw = 0.2, 0.1, 0.01, 0.006
        mesh, plan, props = i_section(h, bw, tf, tw, r=r)
        g = fb_core.section_geometry(mesh, plan["groups"][1], props)
        strong = tw * h ** 3 / 12 + 2 * bw * tf * (h / 2) ** 2
        weak = 2 * tf * bw ** 3 / 12
        self.close(g["inertia"], (strong, weak), 1e-15)
        self.close(g["axes"][0], turned(r, (1.0, 0.0, 0.0)), 1e-12)
        a = g["axes"][1]
        z = turned(r, (0.0, 0.0, 1.0))
        self.close(abs(fb_core._dot(a, z)), 1.0, 1e-12)
        self.close(g["centroid"], turned(r, (2.0, 0.0, 0.0)), 1e-12)

    def test_unequal_flanges_and_two_materials(self):
        h, bw, tf, tw = 0.2, 0.1, 0.01, 0.006
        mesh, plan, props = i_section(h, bw, tf, tw, tf_top=0.02)
        g = fb_core.section_geometry(mesh, plan["groups"][1], props)
        area = bw * 0.02 + bw * tf + h * tw
        self.close(g["centroid"][1], (bw * 0.02 - bw * tf) * h / 2 / area, 1e-15)
        # a web of aluminium: E weighted
        mesh, plan, props = i_section(h, bw, tf, tw, tf_top=0.02, e_web=70e9)
        g = fb_core.section_geometry(mesh, plan["groups"][1], props)
        wa = (bw * 0.02 + bw * tf) * 210e9 + h * tw * 70e9
        self.close(g["centroid"][1], (bw * 0.02 - bw * tf) * h / 2 * 210e9 / wa, 1e-15)
        self.close(g["area"], area, 1e-15)

    def test_missing_thickness(self):
        mesh, plan, props = i_section()
        del props[plan["inside"][0]]["thickness"]
        g = fb_core.section_geometry(mesh, plan["groups"][1], props)
        self.assertTrue("thickness_missing" in g["warnings"])
        self.assertTrue(g["area"] is None)
        self.assertTrue(all(s["t"] is None for s in g["strips"]))
        # all strips then count alike: the plain centroid of the lines
        self.close(g["centroid"], (2.0, 0.0, 0.0), 1e-15)

    def test_large_displacements_give_global_axes(self):
        b, cells = plate("quad4", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        props = strip_props(cells[(1, 0)], 0.01)
        props[cells[(1, 0)][0]]["large"] = True
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], props)
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)
        self.assertFalse(g["planar"])
        self.assertTrue("large_axes" in g["warnings"])

    def test_an_l_of_strips(self):
        def fold(x, y):
            return (x, y, 0.0) if y <= 1.0 else (x, 1.0, y - 1.0)
        b, cells = plate("quad4", 3, 2, size=(3.0, 2.0), points=fold)
        chosen = cells[(1, 0)] + cells[(1, 1)]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        g = fb_core.section_geometry(b.mesh, plan["groups"][1], strip_props(chosen, 0.01))
        # both strips lie in the plane x = 2: an equal L, legs 1, principal axes
        self.assertTrue(g["planar"])
        self.close(g["axes"][0], (1.0, 0.0, 0.0))
        self.close(g["centroid"], (2.0, 0.75, 0.25), 1e-15)
        self.close(g["inertia"], (0.01 / 3, 0.01 / 12), 1e-16)
        r = math.sqrt(0.5)
        self.close(g["axes"][1], (0.0, r, -r), 1e-12)

    def test_a_staircase_cut_gets_global_axes(self):
        # a flat plate, cut along x = 2, y = 1 and x = 1: strips with other n
        b, cells = plate("quad4", 3, 2, size=(3.0, 2.0))
        chosen = cells[(0, 0)] + cells[(0, 1)] + cells[(1, 0)]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(plan["warnings"], [])
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], strip_props(chosen, 0.01))
        self.assertFalse(g["planar"])
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)


class TestBeams(Close):
    def setUp(self):
        self.b = Builder()
        self.es = line(self.b, [(float(i), 0.0, 0.0) for i in range(4)])
        self.plan = fb_core.plan_cuts(self.b.mesh, [self.es[1]])
        # Code-Aster axes of the beam: x along it, y and z turned about x
        c = math.cos(0.3)
        s = math.sin(0.3)
        self.local = ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))
        self.props = {self.es[1]: {"E": 210e9, "model": "POU_D_E",
                                   "section": {"A": 8e-4, "IY": 2e-8, "IZ": 3e-8, "JX": 4e-8},
                                   "beam_axes": {"M": self.local}}}

    def geo(self, i, props=None):
        return fb_core.section_geometry(self.b.mesh, self.plan["groups"][i],
                                        self.props if props is None else props)

    def test_signs_at_node_1_and_node_2(self):
        x, y, z = self.local
        at1 = self.geo(0)
        at2 = self.geo(1)
        self.assertEqual(at1["beams"][0]["end"], 1)
        self.assertEqual(at2["beams"][0]["end"], 2)
        self.close(at2["axes"], (x, y, z))
        self.close(at1["axes"], ((-1.0, 0.0, 0.0), y, (-z[0], -z[1], -z[2])))
        for g in (at1, at2):
            n, a, b_ = g["axes"]
            self.close(fb_core._cross(n, a), b_)
            self.assertTrue(g["planar"])
            self.close(g["area"], 8e-4)
            self.close(g["inertia"], (2e-8, 3e-8))
            self.assertEqual(g["axes_kind"], "beam")
            self.assertEqual(g["warnings"], [])
        self.close(at1["centroid"], (1.0, 0.0, 0.0))
        self.close(at2["centroid"], (2.0, 0.0, 0.0))

    def test_tension_shear_and_moment(self):
        # tension: the rest pulls at node 2 along +x, at node 1 along -x
        x, y, z = self.local
        at1 = self.geo(0)
        at2 = self.geo(1)
        p1 = (1.0, 0.0, 0.0)
        p2 = (2.0, 0.0, 0.0)
        f = fb_core.to_axes(fb_core.resultant([p2], [(5.0, 0.0, 0.0, 0.0, 0.0, 0.0)], p2), at2["axes"])
        self.close(f[0], 5.0)
        f = fb_core.to_axes(fb_core.resultant([p1], [(-5.0, 0.0, 0.0, 0.0, 0.0, 0.0)], p1), at1["axes"])
        self.close(f[0], 5.0)
        # a force along local y counts +Vy at both ends (y kept); a moment
        # about local z flips at node 1
        load = (3 * y[0], 3 * y[1], 3 * y[2], 7 * z[0], 7 * z[1], 7 * z[2])
        f2 = fb_core.to_axes(fb_core.resultant([p2], [load], p2), at2["axes"])
        f1 = fb_core.to_axes(fb_core.resultant([p1], [load], p1), at1["axes"])
        self.close(f2, (0.0, 3.0, 0.0, 0.0, 0.0, 7.0), 1e-12)
        self.close(f1, (0.0, 3.0, 0.0, 0.0, 0.0, -7.0), 1e-12)

    def test_wrong_mirror_is_caught(self):
        # negative control: the axes of node 2 at node 1 give the wrong N
        at1 = self.geo(0)
        p1 = (1.0, 0.0, 0.0)
        wrong = fb_core.to_axes(fb_core.resultant([p1], [(-5.0, 0.0, 0.0, 0.0, 0.0, 0.0)], p1),
                                self.local)
        self.close(wrong[0], -5.0)
        self.assertNotEqual(at1["axes"], self.local)

    def test_line3_halves(self):
        b = Builder()
        es = line(b, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], "line3")
        b.mesh["nodes"][b.mesh["elements"][es[1]][1][1]] = (1.5, 0.2, 0.0)   # bent
        plan = fb_core.plan_cuts(b.mesh, [es[1]])
        m = ((0.9, 0.4, 0.0), (-0.4, 0.9, 0.0), (0.0, 0.0, 1.0))
        hh = ((0.9, -0.4, 0.0), (0.4, 0.9, 0.0), (0.0, 0.0, 1.0))
        props = {es[1]: {"model": "POU_D_T", "section": {"A": 1e-4},
                         "beam_axes": {"M": m, "H": hh}}}
        at1 = fb_core.section_geometry(b.mesh, plan["groups"][0], props)
        self.assertEqual(at1["beams"][0]["cell"], "M")
        self.close(at1["axes"][0], (-0.9, -0.4, 0.0))
        b.element("line2", [b.mesh["elements"][es[1]][1][2], b.node((3.0, 0.0, 0.0))])
        plan = fb_core.plan_cuts(b.mesh, [es[1]])
        at2 = fb_core.section_geometry(b.mesh, plan["groups"][1], props)
        self.assertEqual(at2["beams"][0]["cell"], "H")
        self.close(at2["axes"], hh)

    def test_truss_only_n(self):
        props = {self.es[1]: {"E": 1.0, "model": "BARRE", "section": {"A": 1e-4}}}
        g = self.geo(1, props)
        self.assertTrue(g["only_n"])
        self.assertEqual(g["axes_kind"], "truss")
        self.assertTrue(g["beams"][0]["truss"])
        self.close(g["axes"][0], (1.0, 0.0, 0.0))
        n, a, b_ = g["axes"]
        self.close(fb_core._cross(n, a), b_)
        self.assertEqual(g["warnings"], [])
        g = self.geo(0, props)
        self.close(g["axes"][0], (-1.0, 0.0, 0.0))

    def test_no_axes_of_the_run(self):
        props = {self.es[1]: {"model": "POU_D_E", "section": {"A": 1e-4}}}
        g = self.geo(1, props)
        self.assertTrue("beam_axes_missing" in g["warnings"])
        self.close(g["axes"][0], (1.0, 0.0, 0.0))

    def test_missing_section(self):
        g = self.geo(1, {self.es[1]: {"model": "POU_D_E", "beam_axes": {"M": self.local}}})
        self.assertTrue("section_missing" in g["warnings"])
        self.assertTrue(g["area"] is None)

    def test_tapered_section(self):
        props = {self.es[1]: {"model": "POU_D_E", "beam_axes": {"M": self.local},
                              "section": {"A": 1e-4, "end2": {"A": 3e-4}}}}
        self.close(self.geo(0, props)["area"], 1e-4)
        self.close(self.geo(1, props)["area"], 3e-4)

    def test_large_and_several(self):
        props = dict(self.props)
        props[self.es[1]] = dict(props[self.es[1]], large=True)
        g = self.geo(1, props)
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)
        self.assertTrue("large_axes" in g["warnings"])
        # two beams of the selection on one cut node: global
        b = Builder()
        es = line(b, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        b.element("line2", [b.mesh["elements"][es[0]][1][1], b.node((2.0, 0.0, 0.0))])
        plan = fb_core.plan_cuts(b.mesh, es)
        self.assertEqual(len(plan["groups"]), 1)
        props = dict((e, {"section": {"A": 1e-4}, "beam_axes": {"M": X_AXES}}) for e in es)
        g = fb_core.section_geometry(b.mesh, plan["groups"][0], props)
        self.assertEqual(g["axes"], fb_core.GLOBAL_AXES)


class TestMixed(Close):
    def test_block_with_a_plate(self):
        # hex20 bar of two along x; a quad8 plate standing on its top edge y = 0,
        # sharing the top edge nodes. Cut at x = 1.
        b, cells = bar("hex20", 2, 1, 1, (2.0, 1.0, 1.0))
        plates = []
        for x0 in (0.0, 1.0):
            pts = [(x0, 0, 1), (x0 + .5, 0, 1), (x0 + 1, 0, 1), (x0 + 1, 0, 1.5), (x0 + 1, 0, 2),
                   (x0 + .5, 0, 2), (x0, 0, 2), (x0, 0, 1.5)]
            plates.append(b.element("quad8", [b.node(p) for p in pts]))
        chosen = cells[(0, 0, 0)] + [plates[0]]
        plan = fb_core.plan_cuts(b.mesh, chosen)
        self.assertTrue("mixed_cut" in plan["warnings"])
        self.assertEqual(len(plan["groups"]), 1)
        g = plan["groups"][0]
        self.assertEqual(g["kind"], "mixed")
        self.assertEqual(sorted(item[0] for item in g["entities"]), ["edge", "face"])
        props = {}
        for e in chosen:
            props[e] = {"E": 210e9}
        props[plates[0]]["thickness"] = 0.1
        geo = fb_core.section_geometry(b.mesh, g, props)
        self.assertEqual(geo["axes"], fb_core.GLOBAL_AXES)
        self.assertFalse(geo["planar"])
        self.assertEqual(geo["axes_kind"], "global")
        # centroid: face 1 x 1 at z = 0.5 and strip 0.1 x 1 at z = 1.5
        self.close(geo["area"], 1.1, 1e-12)
        self.close(geo["centroid"], (1.0, 0.5 / 1.1, (0.5 + 0.1 * 1.5) / 1.1), 1e-12)
        self.close(geo["normal"], (1.0, 0.0, 0.0), 1e-12)
        self.assertTrue("drilling" in plan["warnings"])

    def test_beam_and_shell_on_one_node(self):
        b, cells = plate("quad4", 2, 1, size=(2.0, 1.0))
        beam = line(b, [(1.0, 0.0, 0.0), (1.0, -1.0, 0.0)])[0]
        plan = fb_core.plan_cuts(b.mesh, cells[(0, 0)] + [beam])
        self.assertTrue("mixed_cut" in plan["warnings"])
        self.assertEqual(plan["groups"][0]["kind"], "mixed")


class TestAssignShells(Close):
    def test_centre_nodes_of_coque_3d_are_no_mismatch(self):
        # a run with QUAD8_9 has extra nodes, none of them on a cut
        b, cells = plate("quad8", 3, 1)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0)])
        records = [{"index": n, "xyz": b.mesh["nodes"][n]} for n in plan["cut_nodes"]]
        per = fb_core.assign_nodes(plan, b.mesh, {"nodes": records, "extra_nodes": True})
        self.assertEqual(sorted(len(v) for v in per.values()), [3, 3])

    def test_solids_still_need_their_midside_nodes(self):
        b, cells = bar("hex8", 3)
        plan = fb_core.plan_cuts(b.mesh, cells[(1, 0, 0)])
        records = [{"index": n, "xyz": b.mesh["nodes"][n]} for n in plan["cut_nodes"]]
        self.assertRaises(Refused, fb_core.assign_nodes, plan, b.mesh,
                          {"nodes": records, "extra_nodes": True})
        # a linear shell next to it does not block LINE_QUAD of the bridge:
        # the solid cut still needs its midside nodes
        b.element("quad4", [b.node(p) for p in ((5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0))])
        self.assertRaises(Refused, fb_core.assign_nodes, plan, b.mesh,
                          {"nodes": records, "extra_nodes": True})


class TestSpeedShells(unittest.TestCase):
    def test_2000_shells_and_beams(self):
        b, cells = plate("quad8", 40, 25, size=(4.0, 2.5))
        stiff = []
        for j in range(26):
            stiff += line(b, [(float(i) / 10, j * 0.1, 0.0) for i in range(41)])
        chosen = [e for (i, j), v in cells.items() if 10 <= i < 30 for e in v]
        chosen += [e for e in stiff if b.mesh["nodes"][b.mesh["elements"][e][1][0]][0] >= 1.0 and
                   b.mesh["nodes"][b.mesh["elements"][e][1][1]][0] <= 3.0]
        t0 = time.time()
        plan = fb_core.plan_cuts(b.mesh, chosen)
        props = dict((e, {"E": 210e9, "thickness": 0.01, "section": {"A": 1e-4},
                          "beam_axes": {"M": X_AXES}}) for e in chosen)
        geos = [fb_core.section_geometry(b.mesh, g, props) for g in plan["groups"]]
        seconds = time.time() - t0
        SPEED.update(shells_beams=seconds, shells_beams_elements=len(b.mesh["elements"]))
        self.assertTrue(len(b.mesh["elements"]) >= 1000)
        self.assertEqual(len(plan["groups"]), 2)
        self.assertEqual([g["kind"] for g in plan["groups"]], ["mixed", "mixed"])
        self.assertTrue(abs(geos[0]["area"] - (2.5 * 0.01 + 26 * 1e-4)) < 1e-12)
        self.assertTrue(seconds < 20, seconds)


if __name__ == "__main__":
    unittest.main()
