# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_nodecut.py
# Unit tests of Scripts/fb_nodecut.py with exact values, on small self-made
# meshes. No Mecway, no Code-Aster, no numpy: the same file also runs in
# Mecway's IronPython. Run: python -m unittest discover -s tests -p "test_nodecut.py"

import math
import os
import sys
import time
import unittest

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # Mecway's script engine
    HERE = os.environ.get("FB_TESTS", ".")
sys.path.insert(0, os.path.join(HERE, "..", "Scripts"))
import fb_core
import fb_nodecut
from fb_core import Refused

CORNERS = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
           (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
HEX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7),
             (4, 5), (5, 6), (6, 7), (7, 4))
TET_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
TET_SPLIT = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6),
             (0, 5, 1, 6))
# Seconds of the speed test, for the report of a run in IronPython
SPEED = {}


class Mesh(object):
    """A self-made mesh of unit cells, node numbers merged by position."""

    def __init__(self, turn=None):
        self.mesh = {"nodes": {}, "elements": {}}
        self.keys = {}
        self.turn = turn
        self.cells = {}

    def node(self, p):
        key = tuple(int(math.floor(c * 1e9 + 0.5)) for c in p)
        if key not in self.keys:
            nid = len(self.keys) + 1
            self.keys[key] = nid
            q = tuple(float(c) for c in p)
            self.mesh["nodes"][nid] = self.turn(q) if self.turn else q
        return self.keys[key]

    def at(self, p):
        return self.keys[tuple(int(math.floor(c * 1e9 + 0.5)) for c in p)]

    def element(self, shape, nids):
        eid = len(self.mesh["elements"]) + 1
        self.mesh["elements"][eid] = (shape, list(nids))
        return eid

    def solid(self, shape, corners, pairs=None):
        nids = [self.node(p) for p in corners]
        for a, b in pairs or ():
            nids.append(self.node([(corners[a][k] + corners[b][k]) / 2.0 for k in range(3)]))
        return self.element(shape, nids)

    def cell(self, shape, i, j, k):
        c = [(i + q[0], j + q[1], k + q[2]) for q in CORNERS]
        if shape in ("hex8", "hex20"):
            out = [self.solid(shape, c, HEX_EDGES if shape == "hex20" else None)]
        else:
            out = [self.solid(shape, [c[t] for t in tet], TET_EDGES if shape == "tet10" else None)
                   for tet in TET_SPLIT]
        self.cells[(i, j, k)] = out
        return out

    def where(self, test):
        """Elements of the cells (i, j, k) for which test is True."""
        return sorted(e for key, v in self.cells.items() if test(*key) for e in v)

    def nodes_where(self, test):
        """Nodes whose position (before turning) passes test(x, y, z)."""
        out = []
        for key, nid in self.keys.items():
            if test(*[c / 1e9 for c in key]):
                out.append(nid)
        return sorted(out)


def bar(shape="hex8", nx=4, ny=2, nz=1, turn=None):
    m = Mesh(turn)
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                m.cell(shape, i, j, k)
    return m


def close(a, b, tol=1e-12):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def nodes_of(mesh, eids):
    out = set()
    for e in eids:
        out.update(mesh["elements"][e][1])
    return out


class Case(unittest.TestCase):
    def refused(self, code, *args, **kwargs):
        try:
            fb_nodecut.plan_from_nodes(*args, **kwargs)
        except Refused as error:
            self.assertEqual(error.code, code, str(error))
            return error
        self.fail("not refused, wanted " + code)

    def close(self, a, b, tol=1e-12):
        self.assertTrue(close(a, b, tol), "{0!r} is not {1!r}".format(a, b))


class TestPlane(Case):
    def test_eigen3(self):
        a = [[4.0, 1.0, 0.5], [1.0, 3.0, -0.25], [0.5, -0.25, 1.0]]
        pairs = fb_nodecut._eigen3(a)
        self.assertTrue(pairs[0][0] <= pairs[1][0] <= pairs[2][0])
        self.close(sum(v for v, _ in pairs), 8.0, 1e-12)
        for value, x in pairs:
            ax = [sum(a[i][j] * x[j] for j in range(3)) for i in range(3)]
            self.close(ax, [value * c for c in x], 1e-12)
            self.close(sum(c * c for c in x), 1.0, 1e-12)

    def test_plane_of_a_cross_section(self):
        m = bar()
        cut = fb_nodecut.plan_from_nodes(m.mesh, m.nodes_where(lambda x, y, z: x == 2))
        plane = cut["plane"]
        self.assertEqual(plane["normal"], (1.0, 0.0, 0.0))
        self.close(plane["point"], (2.0, 1.0, 0.5))
        self.assertEqual(plane["distance"], 0.0)
        self.close(plane["tolerance"], 1e-6 * math.sqrt(1.25))

    def test_tilted_plane_has_a_fixed_sign(self):
        # The bar turned about z by 30 degrees: the plane x = 2 turns with it
        c = math.cos(math.radians(30))
        s = math.sin(math.radians(30))
        turn = lambda p: (c * p[0] - s * p[1], s * p[0] + c * p[1], p[2])
        m = bar(turn=turn)
        ids = m.nodes_where(lambda x, y, z: x == 2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids)
        self.close(cut["plane"]["normal"], (c, s, 0.0), 1e-12)
        back = fb_nodecut.plan_from_nodes(m.mesh, list(reversed(ids)) + ids[:2])
        self.assertEqual(back["plane"], cut["plane"])
        self.assertFalse(cut["partial"])
        self.assertEqual(cut["elements"], m.where(lambda i, j, k: i >= 2))
        # Turned 150 degrees the normal of the fit points the other way: the
        # sign fix keeps the side of the largest component positive
        c2 = math.cos(math.radians(150))
        s2 = math.sin(math.radians(150))
        m2 = bar(turn=lambda p: (c2 * p[0] - s2 * p[1], s2 * p[0] + c2 * p[1], p[2]))
        cut2 = fb_nodecut.plan_from_nodes(m2.mesh, m2.nodes_where(lambda x, y, z: x == 2))
        self.close(cut2["plane"]["normal"], (-c2, -s2, 0.0), 1e-12)
        self.assertEqual(cut2["elements"], m2.where(lambda i, j, k: i < 2))


class TestRefusals(Case):
    def test_side_is_one_or_minus_one(self):
        m = bar()
        self.assertRaises(ValueError, fb_nodecut.plan_from_nodes, m.mesh,
                          m.nodes_where(lambda x, y, z: x == 2), 0)

    def test_unknown_node(self):
        m = bar()
        self.refused("unknown_node", m.mesh, m.nodes_where(lambda x, y, z: x == 2) + [999])

    def test_too_few_nodes(self):
        m = bar()
        for ids in ([], [1], [1, 2], [1, 1, 2]):
            self.refused("nodes_collinear", m.mesh, ids)

    def test_nodes_on_one_line(self):
        m = bar(nx=4, ny=2, nz=1)
        self.refused("nodes_collinear", m.mesh,
                     m.nodes_where(lambda x, y, z: x == 2 and z == 0))
        # one node a hair off the line is still on it
        ids = m.nodes_where(lambda x, y, z: x == 2 and z == 0)
        p = m.mesh["nodes"][ids[1]]
        m.mesh["nodes"][ids[1]] = (p[0], p[1], p[2] + 1e-7)
        self.refused("nodes_collinear", m.mesh, ids)

    def test_nodes_without_solid(self):
        m = bar()
        lone = m.node((9.0, 9.0, 9.0))
        shell = m.element("quad4", [m.node((5.0, 0, 0)), m.node((6.0, 0, 0)),
                                    m.node((6.0, 1, 0)), m.node((5.0, 1, 0))])
        ids = m.nodes_where(lambda x, y, z: x == 2)
        error = self.refused("nodes_without_solid", m.mesh, ids + [lone])
        self.assertTrue(str(lone) in error.detail)
        self.refused("nodes_without_solid", m.mesh, ids + [m.mesh["elements"][shell][1][0]])

    def test_shell_on_a_selected_node(self):
        m = bar()
        a, b, c, d = [m.at(p) for p in ((2, 0, 1), (3, 0, 1), (3, 1, 1), (2, 1, 1))]
        m.element("quad4", [a, b, c, d])
        self.refused("shell_or_beam", m.mesh, m.nodes_where(lambda x, y, z: x == 2))

    def test_not_planar(self):
        m = bar(nx=4, ny=2, nz=1)
        ids = m.nodes_where(lambda x, y, z: x == 2) + [m.at((3, 0, 0))]
        error = self.refused("nodes_not_planar", m.mesh, ids)
        self.assertTrue("from the plane" in error.detail)
        # a node 1e-3 of the size off is not on the plane either
        ids = m.nodes_where(lambda x, y, z: x == 2)
        p = m.mesh["nodes"][ids[0]]
        m.mesh["nodes"][ids[0]] = (p[0] + 1e-3, p[1], p[2])
        self.refused("nodes_not_planar", m.mesh, ids)

    def test_within_the_tolerance_is_on_the_plane(self):
        m = bar(nx=4, ny=2, nz=1)
        ids = m.nodes_where(lambda x, y, z: x == 2)
        p = m.mesh["nodes"][ids[0]]
        m.mesh["nodes"][ids[0]] = (p[0] + 1e-8, p[1], p[2])
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids)
        self.assertFalse(cut["partial"])
        self.assertTrue(0 < cut["plane"]["distance"] < cut["plane"]["tolerance"])

    def test_plane_through_elements(self):
        # The midside nodes in the middle of hex20 elements: x = 2.5
        m = bar("hex20", nx=4, ny=2, nz=1)
        ids = m.nodes_where(lambda x, y, z: x == 2.5)
        self.assertEqual(len(ids), 6)
        for side in (1, -1):
            error = self.refused("plane_through_elements", m.mesh, ids, side)
            self.assertTrue(error.detail.startswith("2 elements"), error.detail)

    def test_side_empty_and_no_cut(self):
        m = bar(nx=2, ny=2, nz=1)
        top = m.nodes_where(lambda x, y, z: z == 1)
        self.refused("side_empty", m.mesh, top, 1)
        # Inward from a free face: the whole block, and nothing outside
        self.refused("no_cut", m.mesh, top, -1)


class TestFull(Case):
    def test_cross_section_of_a_bar_both_sides(self):
        m = bar("hex8", nx=4, ny=2, nz=1)
        ids = m.nodes_where(lambda x, y, z: x == 2)
        up = fb_nodecut.plan_from_nodes(m.mesh, ids, 1)
        down = fb_nodecut.plan_from_nodes(m.mesh, ids, -1)
        for cut, eids in ((up, m.where(lambda i, j, k: i >= 2)),
                          (down, m.where(lambda i, j, k: i < 2))):
            self.assertFalse(cut["partial"])
            self.assertTrue(cut["rest_valid"])
            self.assertEqual(cut["warnings"], [])
            self.assertEqual(cut["elements"], eids)
            self.assertEqual(cut["plan"], fb_core.plan_cuts(m.mesh, eids))
            self.assertEqual(cut["keep"], ids)
            self.assertEqual(cut["not_cut"], [])
            self.assertEqual(cut["leak"], None)
            # 6 corners and the midpoints of 7 edges in the plane
            self.assertEqual(len(cut["keep_points"]), 13)
            self.assertTrue((2.0, 0.5, 0.0) in cut["keep_points"])
            self.assertTrue((2.0, 1.0, 0.5) in cut["keep_points"])
        self.assertEqual(up["normal"], (-1.0, 0.0, 0.0))
        self.assertEqual(down["normal"], (1.0, 0.0, 0.0))
        self.assertEqual(up["side"], 1)
        self.assertEqual(sorted(up["layer"]), m.where(lambda i, j, k: i == 2))
        g_up = fb_core.section_geometry(m.mesh, up["plan"]["groups"][0])
        g_down = fb_core.section_geometry(m.mesh, down["plan"]["groups"][0])
        self.close(g_up["normal"], up["normal"])
        self.close(g_down["normal"], down["normal"])
        self.close(g_up["area"], 2.0)
        self.close(g_up["area"], g_down["area"])
        self.close(g_up["centroid"], (2.0, 1.0, 0.5))
        self.close(g_up["centroid"], g_down["centroid"])

    def test_hex20_corners_only_take_the_midsides(self):
        m = bar("hex20", nx=4, ny=2, nz=1)
        plane = m.nodes_where(lambda x, y, z: x == 2)
        corners = m.nodes_where(lambda x, y, z: x == 2 and y == int(y) and z == int(z))
        self.assertEqual((len(plane), len(corners)), (13, 6))
        for ids in (corners, plane):
            cut = fb_nodecut.plan_from_nodes(m.mesh, ids)
            self.assertFalse(cut["partial"])
            self.assertEqual(cut["keep"], plane)
            # quadratic: midside nodes by number, no extra midpoints
            self.assertEqual(len(cut["keep_points"]), 13)
            self.assertEqual(cut["elements"], m.where(lambda i, j, k: i >= 2))
            self.assertEqual(cut["plan"], fb_core.plan_cuts(m.mesh, cut["elements"]))

    def test_tet10_cut_on_element_faces(self):
        m = bar("tet10", nx=3, ny=1, nz=1)
        ids = m.nodes_where(lambda x, y, z: x == 1 and y == int(y) and z == int(z))
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids, -1)
        self.assertFalse(cut["partial"])
        self.assertEqual(cut["elements"], m.where(lambda i, j, k: i == 0))
        # 4 corners, 5 midsides (4 sides and the diagonal)
        self.assertEqual(cut["keep"], m.nodes_where(lambda x, y, z: x == 1))
        self.assertEqual(len(cut["keep"]), 9)
        geo = fb_core.section_geometry(m.mesh, cut["plan"]["groups"][0])
        self.close(geo["area"], 1.0)
        self.close(geo["normal"], (1.0, 0.0, 0.0))

    def test_extra_selected_node_not_shared_stays_full(self):
        # An L: a foot of three cells along x and a leg on the first one. The
        # plane z = 1 cuts the leg off; the node (2, 0, 1) on the top of the
        # foot is selected too, but nothing above shares it.
        m = Mesh()
        for i in range(3):
            m.cell("hex8", i, 0, 0)
        for k in (1, 2):
            m.cell("hex8", 0, 0, k)
        leg = m.nodes_where(lambda x, y, z: z == 1 and x <= 1)
        extra = m.at((2, 0, 1))
        up = fb_nodecut.plan_from_nodes(m.mesh, leg + [extra], 1)
        self.assertFalse(up["partial"])
        self.assertEqual(up["elements"], m.where(lambda i, j, k: k >= 1))
        self.assertEqual(up["keep"], leg)
        self.assertEqual(up["not_cut"], [extra])
        self.assertEqual(up["warnings"], ["selected_not_cut"])
        self.assertEqual(up["plan"], fb_core.plan_cuts(m.mesh, up["elements"]))
        down = fb_nodecut.plan_from_nodes(m.mesh, leg + [extra], -1)
        self.assertFalse(down["partial"])
        self.assertEqual(down["elements"], m.where(lambda i, j, k: k == 0))
        self.assertEqual(down["keep"], leg)


class TestPartial(Case):
    def test_upper_half_of_a_cross_section(self):
        m = bar("hex8", nx=4, ny=2, nz=2)
        half = m.nodes_where(lambda x, y, z: x == 2 and z >= 1)
        self.assertEqual(len(half), 6)
        cut = fb_nodecut.plan_from_nodes(m.mesh, half, 1)
        self.assertTrue(cut["partial"])
        self.assertFalse(cut["rest_valid"])
        self.assertEqual(cut["warnings"], ["partial_section"])
        self.assertEqual(cut["plan"]["warnings"], [])
        layer = m.where(lambda i, j, k: i == 2)
        self.assertEqual(cut["elements"], layer)
        self.assertEqual(cut["layer"], layer)
        plan = cut["plan"]
        self.assertEqual(plan["inside"], layer)
        self.assertEqual(plan["outside"], sorted(e for e in m.mesh["elements"] if e not in layer))
        # Only the selected nodes: never the back of the layer at x = 3, nor
        # the nodes of the plane below z = 1
        self.assertEqual(plan["cut_nodes"], half)
        self.assertEqual(cut["keep"], half)
        self.assertEqual(len(plan["groups"]), 1)
        group = plan["groups"][0]
        self.assertEqual(group["nodes"], half)
        self.assertEqual(sorted(e for e, f in group["faces"]),
                         m.where(lambda i, j, k: i == 2 and k == 1))
        self.assertTrue(cut["leak"] is not None)
        # 6 corners, 7 edges between selected nodes: 4 along y, 3 along z
        self.assertEqual(len(cut["keep_points"]), 13)
        geo = fb_core.section_geometry(m.mesh, group)
        self.close(geo["area"], 2.0)
        self.close(geo["centroid"], (2.0, 1.0, 1.5))
        self.close(geo["normal"], (-1.0, 0.0, 0.0))
        other = fb_nodecut.plan_from_nodes(m.mesh, half, -1)
        self.assertTrue(other["partial"])
        self.assertEqual(other["elements"], m.where(lambda i, j, k: i == 1))
        self.assertEqual(other["keep"], half)
        geo2 = fb_core.section_geometry(m.mesh, other["plan"]["groups"][0])
        self.close(geo2["normal"], (1.0, 0.0, 0.0))
        self.close(geo2["centroid"], geo["centroid"])

    def test_hex20_partial_takes_only_midsides_between_selected_corners(self):
        m = bar("hex20", nx=4, ny=2, nz=2)
        corners = m.nodes_where(lambda x, y, z: x == 2 and z >= 1 and y == int(y) and z == int(z))
        cut = fb_nodecut.plan_from_nodes(m.mesh, corners, 1)
        self.assertTrue(cut["partial"])
        # 6 corners, 7 midsides between them; not the midsides at z = 0.5
        want = m.nodes_where(lambda x, y, z: x == 2 and z >= 1)
        self.assertEqual(len(want), 13)
        self.assertEqual(cut["keep"], want)
        self.assertEqual(len(cut["keep_points"]), 13)
        self.assertEqual(cut["plan"]["warnings"], [])

    def test_selected_midside_with_one_corner_unselected(self):
        # The user also picks the midside node at (2, 1, 0.5), whose lower
        # corner is not selected: it is a cut node of its own, and the cells
        # below join the layer. plan_cuts says edge_contact.
        m = bar("hex20", nx=4, ny=2, nz=2)
        corners = m.nodes_where(lambda x, y, z: x == 2 and z >= 1 and y == int(y) and z == int(z))
        extra = m.at((2, 1, 0.5))
        cut = fb_nodecut.plan_from_nodes(m.mesh, corners + [extra], 1)
        self.assertTrue(cut["partial"])
        self.assertEqual(cut["elements"], m.where(lambda i, j, k: i == 2))
        self.assertEqual(cut["keep"], sorted(m.nodes_where(
            lambda x, y, z: x == 2 and z >= 1) + [extra]))
        self.assertEqual(cut["plan"]["warnings"], ["edge_contact"])

    def test_ring_cut_once_is_partial_from_both_sides(self):
        # A square ring of 4 x 4 cells around a hole of 2 x 2, cut once at
        # x = 1 in its lower side: the growth runs round and comes back.
        m = Mesh()
        for i in range(4):
            for j in range(4):
                if not (1 <= i <= 2 and 1 <= j <= 2):
                    m.cell("hex8", i, j, 0)
        ids = m.nodes_where(lambda x, y, z: x == 1 and y <= 1)
        self.assertEqual(len(ids), 4)
        # the layer: every cell at the side with a selected node, also the
        # corner cell (0, 1) that touches the plane at y = 1 only
        for side, layer in ((1, [(1, 0)]), (-1, [(0, 0), (0, 1)])):
            cut = fb_nodecut.plan_from_nodes(m.mesh, ids, side)
            self.assertTrue(cut["partial"])
            self.assertEqual(cut["elements"], m.where(lambda i, j, k: (i, j) in layer))
            self.assertEqual(cut["keep"], ids)
            self.assertEqual(cut["plan"]["warnings"], [])

    def test_wedges(self):
        # Each cell two wedge6, the plane x = 2 on their quadrilateral faces
        m = Mesh()
        for i in range(4):
            c = [(i + q[0], q[1], q[2]) for q in CORNERS]
            for t in ((0, 1, 2, 4, 5, 6), (0, 2, 3, 4, 6, 7)):
                m.solid("wedge6", [c[q] for q in t])
        ids = m.nodes_where(lambda x, y, z: x == 2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids, 1)
        self.assertFalse(cut["partial"])
        self.assertEqual(cut["elements"], [5, 6, 7, 8])
        self.assertEqual(cut["plan"], fb_core.plan_cuts(m.mesh, [5, 6, 7, 8]))
        # 4 corners and 4 sides: the diagonals lie in the faces z = 0 and 1
        self.assertEqual(len(cut["keep_points"]), 8)
        half = fb_nodecut.plan_from_nodes(m.mesh, ids, -1)
        self.assertEqual(half["elements"], [1, 2, 3, 4])

    def test_u_shape_both_sides(self):
        # A U in x-z: a base of five cells, legs of three cells at both ends.
        # The plane z = 2 cuts the left leg. From the end of that leg it is a
        # free body; from the base the growth runs up the right leg past the
        # plane: a partial section, the layer below the plane.
        m = Mesh()
        for i in range(5):
            m.cell("hex8", i, 0, 0)
        for k in (1, 2, 3):
            m.cell("hex8", 0, 0, k)
            m.cell("hex8", 4, 0, k)
        ids = m.nodes_where(lambda x, y, z: z == 2 and x <= 1)
        self.assertEqual(len(ids), 4)
        end = fb_nodecut.plan_from_nodes(m.mesh, ids, 1)
        base = fb_nodecut.plan_from_nodes(m.mesh, ids, -1)
        self.assertFalse(end["partial"])
        self.assertEqual(end["elements"], m.where(lambda i, j, k: i == 0 and k >= 2))
        self.assertTrue(base["partial"])
        self.assertEqual(base["elements"], m.where(lambda i, j, k: i == 0 and k == 1))
        self.assertEqual(base["warnings"], ["partial_section"])
        self.assertEqual(end["keep"], ids)
        self.assertEqual(base["keep"], ids)
        self.assertEqual(sorted(end["keep_points"]), sorted(base["keep_points"]))
        g_end = fb_core.section_geometry(m.mesh, end["plan"]["groups"][0])
        g_base = fb_core.section_geometry(m.mesh, base["plan"]["groups"][0])
        self.close(g_end["area"], 1.0)
        self.close(g_base["area"], 1.0)
        self.close(g_end["centroid"], (0.5, 0.5, 2.0))
        self.close(g_base["centroid"], g_end["centroid"])
        self.close(g_end["normal"], (0.0, 0.0, -1.0))
        self.close(g_base["normal"], (0.0, 0.0, 1.0))
        for cut, want in ((end, (0.0, 0.0, -1.0)), (base, (0.0, 0.0, 1.0))):
            self.assertEqual(cut["normal"], want)
            # no -0.0: the sign of a zero shows in text and in atan2
            self.assertEqual([math.copysign(1.0, c) for c in cut["normal"][:2]], [1.0, 1.0])

    def test_partial_selected_node_not_shared(self):
        # Two columns of cells side by side, the right one a cell higher. The
        # plane x = 1, nodes from z = 1 up: the growth leaks under z = 1, so a
        # partial section. The nodes at z = 3 only the right column touches:
        # they carry nothing through the plane and drop out.
        m = Mesh()
        for i in range(2):
            for k in range(2):
                m.cell("hex8", i, 0, k)
        m.cell("hex8", 1, 0, 2)
        ids = m.nodes_where(lambda x, y, z: x == 1 and z >= 1)
        self.assertEqual(len(ids), 6)
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids, 1)
        self.assertTrue(cut["partial"])
        self.assertEqual(cut["elements"], m.where(lambda i, j, k: i == 1))
        self.assertEqual(cut["not_cut"], m.nodes_where(lambda x, y, z: x == 1 and z == 3))
        self.assertEqual(cut["warnings"], ["partial_section", "selected_not_cut"])
        self.assertEqual(cut["keep"], m.nodes_where(lambda x, y, z: x == 1 and 1 <= z <= 2))


# ---- the filter ---------------------------------------------------------------------
def fake_run(mesh, inside, line_quad=False, ranks=(0, 1, 2)):
    """A result as fb_aster.decode_result gives it, for the selection inside:
    the cut nodes as the run finds them (nodes of the selection and of the
    rest, in Code-Aster's order), with LINE_QUAD the midsides of the shared
    edges added. Each force and displacement is a function of the position, so
    a force that moves to another node shows."""
    elements = mesh["elements"]
    chosen = set(inside)
    shared = nodes_of(mesh, chosen) & nodes_of(mesh, [e for e in elements if e not in chosen])
    points = [mesh["nodes"][n] for n in sorted(shared, reverse=True)]
    if line_quad:
        edges = set()
        for e in elements:
            shape, nids = elements[e]
            for a, b, m in fb_core._EDGE_LOCAL[shape]:
                if nids[a] in shared and nids[b] in shared:
                    edges.add(tuple(sorted((nids[a], nids[b]))))
        rest_edges = set()
        for e in elements:
            if e in chosen:
                continue
            shape, nids = elements[e]
            for a, b, m in fb_core._EDGE_LOCAL[shape]:
                rest_edges.add(tuple(sorted((nids[a], nids[b]))))
        for a, b in sorted(edges):
            inside_edge = any(set((a, b)) <= set(elements[e][1]) for e in chosen)
            if inside_edge and (a, b) in rest_edges:
                pa = mesh["nodes"][a]
                pb = mesh["nodes"][b]
                points.append(tuple((pa[k] + pb[k]) / 2.0 for k in range(3)))
    nodes = [{"index": 100 + i, "xyz": p, "large": i % 2 == 0} for i, p in enumerate(points)]
    forces = {}
    disp = {}
    on_cut = {}
    rest = {}
    for r in ranks:
        forces[r] = [force(p, r) for p in points]
        disp[r] = [tuple(c * 1e-3 * (r + 1) for c in p) for p in points]
        on_cut[r] = {"totals": [tuple(-c for c in force(p, r)) for p in points]}
        rest[r] = {"sum": (0.0,) * 6, "largest": 0.0, "cut_largest": 1.0, "top": [],
                   "tolerance": None, "count": 0, "where": []}
    return {"steps": [{"rank": r, "time": float(r)} for r in ranks], "nodes": nodes,
            "forces": forces, "disp": disp, "rest": rest, "on_cut": on_cut,
            "large": True, "extra_nodes": line_quad, "warnings": [], "seconds": 1.0}


def force(p, rank):
    return (p[0] + 10 * p[1] + 100 * p[2] + 1000 * rank, 2.0 * p[0], -p[2], 0.0, 0.0, p[1])


class TestShellsElsewhere(Case):
    """A shell or beam refuses only on a selected node (contract, cut by
    nodes): a full section is the element selection of its body, a partial
    one the layer of solids at the nodes."""

    def plate_on_top(self, m, x0, x1, z):
        return m.element("quad4", [m.at(p) for p in ((x0, 0, z), (x1, 0, z), (x1, 1, z),
                                                     (x0, 1, z))])

    def test_shell_and_beam_in_the_free_body(self):
        m = bar()
        shell = self.plate_on_top(m, 3, 4, 1)
        beam = m.element("line2", [m.at((4, 0, 0)), m.node((5.0, 0.0, 0.0))])
        ids = m.nodes_where(lambda x, y, z: x == 2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, ids, 1)
        self.assertFalse(cut["partial"])
        body = sorted(m.where(lambda i, j, k: i >= 2) + [shell, beam])
        self.assertEqual(cut["elements"], body)
        # the same plan as a selection of those elements
        self.assertEqual(cut["plan"], fb_core.plan_cuts(m.mesh, body))
        self.assertEqual(sorted(cut["keep"]), ids)
        self.assertTrue("drilling" in cut["plan"]["warnings"])
        self.assertEqual(cut["plan"]["drilling"], ["other_element"])
        # the other side holds neither
        other = fb_nodecut.plan_from_nodes(m.mesh, ids, -1)
        self.assertEqual(other["elements"], m.where(lambda i, j, k: i < 2))
        self.assertEqual(other["plan"], fb_core.plan_cuts(m.mesh, other["elements"]))
        # a filtered result of the full section loses no node
        result = {"nodes": [{"xyz": m.mesh["nodes"][n]} for n in ids],
                  "forces": {1: [(0.0,) * 6] * len(ids)}, "disp": {1: [(0.0,) * 3] * len(ids)},
                  "on_cut": {}, "rest": {}, "warnings": []}
        self.assertEqual(fb_nodecut.filter_result(result, cut)["nodecut"]["dropped"], 0)

    def test_shell_on_a_selected_node_still_refuses(self):
        m = bar()
        self.plate_on_top(m, 2, 3, 1)
        self.refused("shell_or_beam", m.mesh, m.nodes_where(lambda x, y, z: x == 2))
        m = bar()
        m.element("line2", [m.at((2, 0, 0)), m.node((1.5, -1.0, 0.0))])
        self.refused("shell_or_beam", m.mesh, m.nodes_where(lambda x, y, z: x == 2))

    def test_partial_section_judges_drilling_on_the_whole_model(self):
        m = bar("hex8", nx=4, ny=2, nz=2)
        half = m.nodes_where(lambda x, y, z: x == 2 and z >= 1)
        top = self.plate_on_top(m, 3, 4, 2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, half, 1)
        self.assertTrue(cut["partial"])
        self.assertEqual(cut["elements"], m.where(lambda i, j, k: i == 2))
        # one flat shell, not at the layer: nothing to warn
        self.assertEqual(cut["plan"]["drilling"], [])
        self.assertFalse("drilling" in cut["plan"]["warnings"])
        # a moment about its normal, anywhere in the model, does warn
        corner = m.mesh["elements"][top][1][2]
        m.mesh["moments"] = {corner: (0.0, 0.0, 1.0)}
        cut = fb_nodecut.plan_from_nodes(m.mesh, half, 1)
        self.assertEqual(cut["plan"]["drilling"], ["nodal_moment"])
        self.assertTrue("drilling" in cut["plan"]["warnings"])
        m.mesh["moments"] = {corner: (1.0, 0.0, 0.0)}
        self.assertEqual(fb_nodecut.plan_from_nodes(m.mesh, half, 1)["plan"]["drilling"], [])
        del m.mesh["moments"]
        # a fold: a second shell on the end face
        m.element("quad4", [m.at(p) for p in ((4, 0, 1), (4, 1, 1), (4, 1, 2), (4, 0, 2))])
        cut = fb_nodecut.plan_from_nodes(m.mesh, half, 1)
        self.assertEqual(cut["plan"]["drilling"], ["not_coplanar"])
        self.assertEqual(cut["plan"]["warnings"], ["drilling"])
        self.assertEqual(cut["warnings"], ["partial_section"])


class TestFilter(Case):
    def check_kept(self, result, cut, ranks):
        """Every kept force and displacement is the one of its node."""
        for i, record in enumerate(result["nodes"]):
            p = record["xyz"]
            for r in ranks:
                self.assertEqual(result["forces"][r][i], force(p, r))
                self.assertEqual(result["disp"][r][i], tuple(c * 1e-3 * (r + 1) for c in p))
                self.assertEqual(result["on_cut"][r]["totals"][i],
                                 tuple(-c for c in force(p, r)))

    def test_hex20_partial_keeps_forces_at_their_node(self):
        m = bar("hex20", nx=4, ny=2, nz=2)
        corners = m.nodes_where(lambda x, y, z: x == 2 and z >= 1 and y == int(y) and z == int(z))
        cut = fb_nodecut.plan_from_nodes(m.mesh, corners, 1)
        result = fake_run(m.mesh, cut["elements"])
        # back nodes at x = 3 and the rest of the plane at x = 2 are in the run
        before = len(result["nodes"])
        self.assertEqual(before, 21 + 21)
        whole = result
        result = fb_nodecut.filter_result(whole, cut)
        # the result of the run stays as it was
        self.assertEqual(len(whole["nodes"]), before)
        self.assertEqual(len(whole["forces"][1]), before)
        self.assertFalse("valid" in whole["rest"][1] or "nodecut" in whole)
        self.assertEqual(whole["warnings"], [])
        keep = result["nodecut"]["kept"]
        self.assertEqual(len(keep), 13)
        self.assertEqual(sorted(r["xyz"] for r in result["nodes"]),
                         sorted(m.mesh["nodes"][n] for n in cut["keep"]))
        self.assertEqual([r["index"] for r in result["nodes"]], [100 + i for i in keep])
        self.check_kept(result, cut, (0, 1, 2))
        self.assertEqual(result["large"], any(r["large"] for r in result["nodes"]))
        for r in (0, 1, 2):
            self.assertFalse(result["rest"][r]["valid"])
            self.assertFalse("valid" in result["on_cut"][r])
        self.assertEqual(result["warnings"], ["partial_section"])
        self.assertEqual(result["nodecut"], {"partial": True, "rest_valid": False, "dropped": 29,
                                             "kept": keep})
        # The reduced plan fits the filtered result exactly
        per = fb_core.assign_nodes(cut["plan"], m.mesh, result)
        self.assertEqual(sorted(per[1]), list(range(13)))
        # A second filter changes nothing
        result = fb_nodecut.filter_result(result, cut, m.mesh)
        self.assertEqual(result["nodecut"]["kept"], list(range(13)))
        self.assertEqual(result["warnings"], ["partial_section"])

    def test_hex8_line_quad_keeps_the_midsides_of_the_cut(self):
        m = bar("hex8", nx=4, ny=2, nz=2)
        half = m.nodes_where(lambda x, y, z: x == 2 and z >= 1)
        cut = fb_nodecut.plan_from_nodes(m.mesh, half, 1)
        result = fake_run(m.mesh, cut["elements"], line_quad=True)
        result = fb_nodecut.filter_result(result, cut)
        self.assertEqual(len(result["nodes"]), 13)
        mids = [r["xyz"] for r in result["nodes"]
                if r["xyz"] not in [m.mesh["nodes"][n] for n in half]]
        self.assertEqual(len(mids), 7)
        self.assertTrue((2.0, 0.5, 2.0) in mids and (2.0, 1.0, 1.5) in mids)
        self.assertTrue((2.0, 0.5, 1.0) in mids)
        self.assertFalse((2.0, 1.0, 0.5) in mids)
        self.check_kept(result, cut, (0, 1, 2))
        per = fb_core.assign_nodes(cut["plan"], m.mesh, result)
        self.assertEqual(sorted(per[1]), list(range(13)))

    def test_hex8_line_quad_without_a_kept_edge(self):
        """Review point: no edge with both corners kept, so no midside node
        survives the filter. Then the plan has no faces either, and
        assign_nodes does not miss them."""
        m = bar("hex8", nx=4, ny=2, nz=2)
        spread = m.nodes_where(lambda x, y, z: x == 2 and (y, z) in ((0, 0), (2, 0), (0, 2)))
        cut = fb_nodecut.plan_from_nodes(m.mesh, spread, 1)
        self.assertTrue(cut["partial"])
        self.assertFalse(any(g["faces"] for g in cut["plan"]["groups"]))
        result = fb_nodecut.filter_result(fake_run(m.mesh, cut["elements"], line_quad=True), cut)
        self.assertEqual(len(result["nodes"]), 3)
        per = fb_core.assign_nodes(cut["plan"], m.mesh, result)
        self.assertEqual(sorted(i for v in per.values() for i in v), [0, 1, 2])

    def test_full_section_loses_nothing(self):
        m = bar("hex8", nx=4, ny=2, nz=1)
        cut = fb_nodecut.plan_from_nodes(m.mesh, m.nodes_where(lambda x, y, z: x == 2))
        result = fake_run(m.mesh, cut["elements"], line_quad=True)
        self.assertEqual(len(result["nodes"]), 13)
        result = fb_nodecut.filter_result(result, cut)
        self.assertEqual(result["nodecut"], {"partial": False, "rest_valid": True, "dropped": 0,
                                             "kept": list(range(13))})
        self.assertFalse("valid" in result["rest"][1])
        self.assertEqual(result["warnings"], [])
        # a node in the result that is no node of this cut: refused
        result["nodes"][3] = dict(result["nodes"][3], xyz=(2.0, 0.25, 0.0))
        try:
            result = fb_nodecut.filter_result(result, cut)
        except Refused as error:
            self.assertEqual(error.code, "node_mismatch")
        else:
            self.fail("not refused")

    def test_judged_on_cut_is_marked(self):
        m = bar("hex8", nx=4, ny=2, nz=2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, m.nodes_where(lambda x, y, z: x == 2 and z >= 1))
        result = fake_run(m.mesh, cut["elements"], ranks=(1,))
        result["on_cut"][1] = {"sum": (0.0,) * 6, "largest": 0.0, "count": 0, "where": [],
                               "tolerance": 1e-9, "cuts": {}}
        result = fb_nodecut.filter_result(result, cut)
        self.assertFalse(result["on_cut"][1]["valid"])
        self.assertFalse(result["rest"][1]["valid"])

    def test_arrays_that_do_not_fit_are_refused(self):
        m = bar("hex8", nx=4, ny=2, nz=2)
        cut = fb_nodecut.plan_from_nodes(m.mesh, m.nodes_where(lambda x, y, z: x == 2 and z >= 1))
        for key in ("forces", "disp", "totals"):
            result = fake_run(m.mesh, cut["elements"])
            if key == "totals":
                result["on_cut"][1]["totals"].pop()
            else:
                result[key][2].pop()
            self.assertRaises(ValueError, fb_nodecut.filter_result, result, cut)


class TestSpeed(unittest.TestCase):
    def test_about_2000_hex20(self):
        m = bar("hex20", nx=20, ny=10, nz=10)
        self.assertEqual(len(m.mesh["elements"]), 2000)
        full = m.nodes_where(lambda x, y, z: x == 10)
        half = m.nodes_where(lambda x, y, z: x == 10 and z >= 5)
        t0 = time.time()
        a = fb_nodecut.plan_from_nodes(m.mesh, full, 1)
        t1 = time.time()
        b = fb_nodecut.plan_from_nodes(m.mesh, half, -1)
        t2 = time.time()
        result = fake_run(m.mesh, b["elements"], ranks=(1,))
        t3 = time.time()
        result = fb_nodecut.filter_result(result, b)
        t4 = time.time()
        self.assertFalse(a["partial"])
        self.assertEqual(len(a["elements"]), 1000)
        self.assertTrue(b["partial"])
        self.assertEqual(len(b["elements"]), 60)
        self.assertEqual(len(result["nodes"]), len(b["keep"]))
        SPEED.update(full=t1 - t0, partial=t2 - t1, filter=t4 - t3,
                     elements=len(m.mesh["elements"]))
        self.assertTrue(t2 - t0 < 20, str(SPEED))


if __name__ == "__main__":
    unittest.main()
