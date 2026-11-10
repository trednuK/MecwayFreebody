# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_aster_shells_e2e.py
# Phase 4 with real Code-Aster: shells (DKT, COQUE_3D), beams (POU_D_E,
# POU_D_T, line3, truss) and a block with a shell, through the real bridge code
# without Mecway, against exact statics with two cuts. fb_core and fb_aster as
# the panel will call them; the numbers of the reference come from the model
# only (loads, volumes, areas), never from fb_core.
#
# Bases: python -B tests/test_aster_shells_e2e.py build [tags]. The bridge is
# found in FB_BRIDGE or as MecwayAsterBridge next to this checkout or one above
# it (only read; no bytecode there); the bases go to FB_SHELLS or WorkDir\shells
# of this checkout. Code-Aster runs with one cpu and without a window.
#
# Schema 2: until the bridge writes it, the build step adds it to the manifest
# of the bridge from the bridge's own model data and its own functions (beam
# axes by bridge_mesh._mecway_v_axis and the half cells of _cell_names), and
# marks it "schema2_by": "test". The test of the bridge's own schema 2 is
# skipped until a base has it.
# Run: python -B -m unittest tests.test_aster_shells_e2e -v

import io
import json
import math
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
import fb_aster
import fb_core

EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4",
                   "bin", "run_aster.bat")
VERSION = "17.4"
RUN_ID = "20261109_120000"
CREATE_NO_WINDOW = 0x08000000
BAR = 1e-8                 # E7: up to 4e-10 on shells, 1e-11 on beams
BAR_DRILL = 5e-2           # E7: drilling stiffness, up to 4e-2
RHO = 7850.0
E_STEEL = 210e9
REPORT = {}


# ---- where things are ---------------------------------------------------------------------
def _ancestors():
    here = ROOT
    while True:
        yield here
        up = os.path.dirname(here)
        if up == here:
            return
        here = up


def bridge_folder():
    found = os.environ.get("FB_BRIDGE")
    if found:
        return found
    for here in _ancestors():
        path = os.path.join(os.path.dirname(here), "MecwayAsterBridge")
        if os.path.isfile(os.path.join(path, "Scripts", "bridge_manifest.py")):
            return path
    return None


def work_folder():
    found = os.environ.get("FB_SHELLS")
    if found:
        return found
    for here in _ancestors():
        path = os.path.join(here, "WorkDir", "shells")
        if os.path.isdir(path):
            return path
    return os.path.join(ROOT, "WorkDir", "shells")


# ---- vectors --------------------------------------------------------------------------------
def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(s, a):
    return tuple(s * x for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    return mul(1.0 / norm(a), a)


def rotation():
    """A fixed turn about three axes, as E7."""
    a, b, c = .5, -.7, 1.1
    rx = ((1, 0, 0), (0, math.cos(a), -math.sin(a)), (0, math.sin(a), math.cos(a)))
    ry = ((math.cos(b), 0, math.sin(b)), (0, 1, 0), (-math.sin(b), 0, math.cos(b)))
    rz = ((math.cos(c), -math.sin(c), 0), (math.sin(c), math.cos(c), 0), (0, 0, 1))

    def mat(p, q):
        return tuple(tuple(sum(p[i][k] * q[k][j] for k in range(3)) for j in range(3))
                     for i in range(3))
    return mat(rz, mat(ry, rx))


R = rotation()


def turn(p):
    return tuple(sum(R[i][k] * p[k] for k in range(3)) for i in range(3))


# ---- models ----------------------------------------------------------------------------------
class Model(object):
    """Mesh, regions (0 root, 1 selection, 2 tip), materials, loads."""

    def __init__(self, tag):
        self.tag = tag
        self.keys = {}
        self.xyz = []
        self.elements = {}
        self.component = {}
        self.region = {}
        self.truss = set()
        self.materials = {}
        self.comp_mat = {}
        self.nodesets = {}
        self.fixed = []
        self.displacements = []          # (nodeset, direction)
        self.forces = []                 # (nodeset of one node, F)
        self.moments = []                # (nodeset of one node, M)
        self.offsets = []                # (element set, w)
        self.gravity = (3.0, -4.0, -8.0)
        self.general = {}
        self.length = 1.0                # for the error measure

    def node(self, p):
        k = tuple(int(round(c * 1e9)) for c in p)
        if k not in self.keys:
            self.xyz.append(tuple(float(c) for c in p))
            self.keys[k] = len(self.xyz)
        return self.keys[k]

    def add(self, shape, points, comp, region):
        eid = len(self.elements) + 1
        self.elements[eid] = (shape, [self.node(p) for p in points])
        self.component[eid] = comp
        self.region[eid] = region
        return eid

    def at(self, name, p):
        """A node set of the one node at p."""
        self.nodesets[name] = [self.keys[tuple(int(round(c * 1e9)) for c in p)]]
        return name

    def mesh(self):
        mesh = {"nodes": dict((i + 1, p) for i, p in enumerate(self.xyz)),
                "elements": dict(self.elements), "component": dict(self.component)}
        # as the panel gives them: the nodal moments with their direction
        mesh["moments"] = dict((self.nodesets[name][0], m) for name, m in self.moments)
        return mesh

    def selection(self):
        return sorted(e for e, r in self.region.items() if r == 1)

    def write(self, path):
        text = ['<?xml version="1.0" encoding="utf-8"?>', '<liml version="34">',
                '  <analysis type="S30" />']
        for i, p in enumerate(self.xyz):
            text.append('  <node nid="%d" x="%r" y="%r" z="%r" />' % (i + 1, p[0], p[1], p[2]))
        for comp in sorted(self.comp_mat):
            text.append('  <elset name="%s" material="%s" colorrgb="00C800">' % (
                comp, self.comp_mat[comp]))
            for eid in sorted(self.elements):
                if self.component[eid] == comp:
                    shape, nids = self.elements[eid]
                    extra = ' truss="true"' if eid in self.truss else ''
                    text.append('    <elem eid="%d" shape="%s" nodes="%s"%s />' % (
                        eid, shape, " ".join(str(n) for n in nids), extra))
            text.append('  </elset>')
        for name, mat in sorted(self.materials.items()):
            geo = ""
            if "thickness" in mat:
                geo = '<geometric type="Plate" thickness="%r m" />' % mat["thickness"]
            elif "rect" in mat:
                geo = '<geometric type="RectBar" recta="%r m" rectb="%r m" />' % mat["rect"]
            text.append('  <mat name="%s">%s<mechanical type="Isotropic" youngsmodulus="%d Pa" '
                        'poissonratio="0.3" /><density type="Simple" density="%r kg/m&#179;" />'
                        '</mat>' % (name, geo, int(mat["E"]), mat["rho"]))
        for name, nodes in sorted(self.nodesets.items()):
            text.append('  <nodeselection name="%s">' % name + "".join(
                '<node nid="%d" />' % n for n in nodes) + '</nodeselection>')
        for name, eids, w in self.offsets:
            text.append('  <elementselection name="%s">' % name + "".join(
                '<element eid="%d" />' % e for e in eids) + '</elementselection>')
            text.append('  <offset selection="%s"><u>0 m</u><v>0 m</v><w>%r m</w></offset>' % (
                name, float(w)))
        for name in self.fixed:
            text.append('  <fixed selection="%s" />' % name)
        for name, d in self.displacements:
            text.append('  <displacement selection="%s"><value>0 m</value><x>%d</x><y>%d</y>'
                        '<z>%d</z></displacement>' % ((name,) + tuple(d)))
        for name, f in self.forces:
            text.append('  <force selection="%s"><x>%r N</x><y>%r N</y><z>%r N</z></force>' % (
                (name,) + tuple(float(v) for v in f)))
        for name, m in self.moments:
            text.append('  <moment selection="%s"><x>%r N.m</x><y>%r N.m</y><z>%r N.m</z>'
                        '</moment>' % ((name,) + tuple(float(v) for v in m)))
        if self.gravity is not None:
            text.append('  <gravity><x>%r m/s&#178;</x><y>%r m/s&#178;</y><z>%r m/s&#178;</z>'
                        '</gravity>' % tuple(float(v) for v in self.gravity))
        for name, unit_ in (("displacement", "m"), ("stress", "Pa"), ("reaction force", "N")):
            text.append('  <fieldvariable name="%s" displayunit="%s" expanded="true" />' % (
                name, unit_))
        text.append('</liml>')
        with io.open(path, "w", encoding="ascii", newline="\n") as f:
            f.write(u"\n".join(text))


def _region(i, n):
    return 0 if i < n // 4 else (1 if i < 3 * n // 4 else 2)


def strip(tag, shape, where, nx=20, ny=4, length=0.2, width=0.04, t=0.002, moment=None):
    """A cantilever plate of shells, mapped by where(x, y); fixed at x = 0, a
    tip force and moment on the tip corner, gravity."""
    m = Model(tag)
    m.materials["Plate"] = {"E": E_STEEL, "rho": RHO, "thickness": t}
    m.comp_mat["Shell"] = "Plate"
    dx = length / nx
    dy = width / ny
    for i in range(nx):
        for j in range(ny):
            c = [(i * dx, j * dy), ((i + 1) * dx, j * dy), ((i + 1) * dx, (j + 1) * dy),
                 (i * dx, (j + 1) * dy)]
            if shape in ("quad4", "quad8"):
                parts = [c]
            else:
                parts = [[c[0], c[1], c[2]], [c[0], c[2], c[3]]]
            for corners in parts:
                pts = []
                for k in range(len(corners)):
                    pts.append(where(*corners[k]))
                    if shape in ("quad8", "tri6"):
                        q = corners[(k + 1) % len(corners)]
                        pts.append(where((corners[k][0] + q[0]) / 2, (corners[k][1] + q[1]) / 2))
                m.add(shape, pts, "Shell", _region(i, nx))
    m.nodesets["ROOT"] = sorted(set(m.keys[tuple(int(round(c * 1e9)) for c in where(0.0, j * dy / 2))]
                                    for j in range(2 * ny + 1)
                                    if tuple(int(round(c * 1e9)) for c in where(0.0, j * dy / 2))
                                    in m.keys))
    m.fixed.append("ROOT")
    tip = where(length, 0.0)
    m.at("TIP", tip)
    m.forces.append(("TIP", (300.0, 200.0, -100.0)))
    if moment is not None:
        m.moments.append(("TIP", moment))
    m.length = length
    return m


def flat(x, y):
    return turn((x, y, 0.0))


def fold(x, y, x0=0.1, a=math.radians(60)):
    if x <= x0:
        return turn((x, y, 0.0))
    return turn((x0 + (x - x0) * math.cos(a), y, (x - x0) * math.sin(a)))


def in_plane_moment(where, length, ny_width=0.04):
    """A tip moment without a part about the shell normal there."""
    a = where(length, 0.0)
    w = unit(cross(sub(where(length, ny_width), a), sub(a, where(length - 1e-4, 0.0))))
    mt = (2.0, 3.0, -1.0)
    return sub(mt, mul(dot(mt, w), w))


def normal_moment(where, length, ny_width=0.04):
    a = where(length, 0.0)
    w = unit(cross(sub(a, where(length - 1e-4, 0.0)), sub(where(length, ny_width), a)))
    return mul(2.0, w)


def i_beam(tag, nx=12, length=0.6, h=0.1, bw=0.05, tf=0.004, tw=0.003):
    """A cantilever I of DKT shells along x: flanges at y = +-h/2, web at z = 0."""
    m = Model(tag)
    m.materials["Flange"] = {"E": E_STEEL, "rho": RHO, "thickness": tf}
    m.materials["Web"] = {"E": E_STEEL, "rho": RHO, "thickness": tw}
    m.comp_mat = {"F": "Flange", "W": "Web"}
    dx = length / nx
    for i in range(nx):
        x0 = i * dx
        x1 = x0 + dx
        r = _region(i, nx)
        for y in (h / 2, -h / 2):
            for z0, z1 in ((-bw / 2, 0.0), (0.0, bw / 2)):
                m.add("quad4", [turn(p) for p in ((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1))],
                      "F", r)
        for y0, y1 in ((-h / 2, 0.0), (0.0, h / 2)):
            m.add("quad4", [turn(p) for p in ((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0))],
                  "W", r)
    m.nodesets["ROOT"] = sorted(n for p, n in zip(m.xyz, range(1, len(m.xyz) + 1))
                                if abs(dot(sub(p, turn((0, 0, 0))), turn((1, 0, 0)))) < 1e-12)
    m.fixed.append("ROOT")
    m.at("TIP", turn((length, h / 2, 0.0)))
    m.forces.append(("TIP", (100.0, 300.0, -200.0)))
    m.length = length
    return m


def beam_line(tag, model, points, shape="line2", reverse=False, truss=False):
    """A cantilever of beams along a polyline, fixed at the first point, a tip
    force and moment at the last, gravity. reverse: every element runs from
    the tip towards the root."""
    m = Model(tag)
    m.materials["Bar"] = {"E": E_STEEL, "rho": RHO, "rect": (0.02, 0.04)}
    m.comp_mat["Beam"] = "Bar"
    n = len(points) - 1
    for i in range(n):
        p, q = points[i], points[i + 1]
        pts = [p, q] if shape == "line2" else [p, tuple((a + b) / 2 for a, b in zip(p, q)), q]
        if shape == "line3" and len(points[i]) == 4:
            pass
        if reverse:
            pts = pts[::-1]
        e = m.add(shape, [tuple(v[:3]) for v in pts], "Beam", _region(i, n))
        if truss:
            m.truss.add(e)
    m.at("ROOT", points[0])
    m.fixed.append("ROOT")
    m.at("TIP", points[-1])
    if truss:
        m.forces.append(("TIP", (500.0, 0.0, 0.0)))
        m.gravity = (-9.81, 0.0, 0.0)
        m.nodesets["ALL"] = list(range(1, len(m.xyz) + 1))
        m.displacements += [("ALL", (0, 1, 0)), ("ALL", (0, 0, 1))]
    else:
        m.forces.append(("TIP", (300.0, 200.0, -100.0)))
        m.moments.append(("TIP", (2.0, 3.0, -1.0)))
    m.length = sum(norm(sub(points[i + 1], points[i])) for i in range(n))
    m.general["elem_beam"] = model
    return m


def offset_strip(tag, e=0.003):
    """A DKT plate with an element offset e along w on every element, no
    gravity: the bridge gives it as EXCENTREMENT."""
    m = strip(tag, "quad4", flat, moment=in_plane_moment(flat, 0.2))
    m.gravity = None
    m.offsets.append(("OFF", sorted(m.elements), e))
    m.offset = e
    return m


def frame_points(n=20, length=0.2):
    return [fold(i * length / n, 0.0) for i in range(n + 1)]


def arc_points(n=10, radius=0.2):
    """A quarter circle, with the midside nodes on it: line3 gets them from
    beam_line halfway on the chord, so the points here are the corners and the
    midsides alternate."""
    return [turn((radius * math.sin(a), 0.0, radius * (1 - math.cos(a))))
            for a in [math.pi / 2 * i / n for i in range(n + 1)]]


def curved_line3(tag, n=10, radius=0.2):
    m = Model(tag)
    m.materials["Bar"] = {"E": E_STEEL, "rho": RHO, "rect": (0.02, 0.04)}
    m.comp_mat["Beam"] = "Bar"
    pts = [turn((radius * math.sin(a), 0.0, radius * (1 - math.cos(a))))
           for a in [math.pi / 2 * i / (2 * n) for i in range(2 * n + 1)]]
    for i in range(n):
        m.add("line3", [pts[2 * i], pts[2 * i + 1], pts[2 * i + 2]], "Beam", _region(i, n))
    m.at("ROOT", pts[0])
    m.fixed.append("ROOT")
    m.at("TIP", pts[-1])
    m.forces.append(("TIP", (300.0, 200.0, -100.0)))
    m.moments.append(("TIP", (2.0, 3.0, -1.0)))
    m.length = radius * math.pi / 2
    m.general["elem_beam"] = "POU_D_E"
    return m


def block_with_fin(tag, nx=8, length=0.2, b=0.02, h=0.04, fin=0.02, t=0.002):
    """A hex20 bar with a quad8 plate standing on its top edge y = 0."""
    m = Model(tag)
    m.materials["Steel"] = {"E": E_STEEL, "rho": RHO}
    m.materials["Plate"] = {"E": E_STEEL, "rho": RHO, "thickness": t}
    m.comp_mat = {"Block": "Steel", "Fin": "Plate"}
    corners = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))
    edges = fb_core._HEX_EDGES
    dx = length / nx
    for i in range(nx):
        for k in range(2):
            low = (i * dx, 0.0, k * h / 2)
            size = (dx, b, h / 2)
            c = [tuple(low[q] + u[q] * size[q] for q in range(3)) for u in corners]
            pts = c + [tuple((c[a][q] + c[bb][q]) / 2 for q in range(3)) for a, bb in edges]
            m.add("hex20", [turn(p) for p in pts], "Block", _region(i, nx))
        x0 = i * dx
        x1 = x0 + dx
        pts = [(x0, 0, h), ((x0 + x1) / 2, 0, h), (x1, 0, h), (x1, 0, h + fin / 2), (x1, 0, h + fin),
               ((x0 + x1) / 2, 0, h + fin), (x0, 0, h + fin), (x0, 0, h + fin / 2)]
        m.add("quad8", [turn(p) for p in pts], "Fin", _region(i, nx))
    m.nodesets["ROOT"] = sorted(n for p, n in zip(m.xyz, range(1, len(m.xyz) + 1))
                                if abs(dot(sub(p, turn((0, 0, 0))), turn((1, 0, 0)))) < 1e-12)
    m.fixed.append("ROOT")
    m.at("TIP", turn((length, b, 0.0)))
    m.forces.append(("TIP", (2000.0, 500.0, -1000.0)))
    m.at("TIPF", turn((length, 0.0, h + fin)))
    m.forces.append(("TIPF", (0.0, 100.0, 0.0)))
    m.length = length
    return m


MODELS = {
    "s_dkt": lambda t: strip(t, "quad4", flat, moment=in_plane_moment(flat, 0.2)),
    "s_tri": lambda t: strip(t, "tri3", flat, moment=in_plane_moment(flat, 0.2)),
    "s_c3d": lambda t: strip(t, "quad8", flat, nx=12, ny=2, moment=in_plane_moment(flat, 0.2)),
    "s_fold": lambda t: strip(t, "quad4", fold, moment=in_plane_moment(fold, 0.2)),
    "s_drill": lambda t: strip(t, "quad4", flat, moment=normal_moment(flat, 0.2)),
    # the fold beyond the second cut, in the tip
    "s_foldtip": lambda t: strip(t, "quad4", lambda x, y: fold(x, y, x0=0.17),
                                 moment=in_plane_moment(lambda x, y: fold(x, y, x0=0.17), 0.2)),
    "s_i": i_beam,
    "s_exc": lambda t: offset_strip(t),
    "b_e": lambda t: beam_line(t, "POU_D_E", frame_points()),
    "b_t": lambda t: beam_line(t, "POU_D_T", frame_points(), reverse=True),
    "b_l3": curved_line3,
    "b_truss": lambda t: beam_line(t, "POU_D_E", [(0.02 * i, 0.0, 0.0) for i in range(11)],
                                   truss=True),
    "m_block": block_with_fin,
}
# Cases whose numbers the drilling stiffness spoils (E7), with the warning
DRILLING = ("s_fold", "s_drill", "s_i")


# ---- exact statics ---------------------------------------------------------------------------------
def _polygon(points):
    """Area and centroid of a flat polygon (triangle fan)."""
    area = 0.0
    centre = (0.0, 0.0, 0.0)
    for i in range(1, len(points) - 1):
        a = norm(cross(sub(points[i], points[0]), sub(points[i + 1], points[0]))) / 2
        c = mul(1.0 / 3, add(add(points[0], points[i]), points[i + 1]))
        area += a
        centre = add(centre, mul(a, c))
    return area, mul(1.0 / area, centre)


def element_weight(model, eid):
    """(gravity force, its point) of an element: straight edges, flat faces."""
    shape, nids = model.elements[eid]
    p = [model.xyz[n - 1] for n in nids]
    mat = model.materials[model.comp_mat[model.component[eid]]]
    g = model.gravity
    if shape in ("quad4", "tri3"):
        area, c = _polygon(p)
        mass = RHO * mat["thickness"] * area
    elif shape in ("quad8", "tri6"):
        area, c = _polygon(p[0::2])
        mass = RHO * mat["thickness"] * area
    elif shape in ("line2", "line3"):
        a, b = p[0], p[-1]
        if shape == "line3":
            # two straight halves, as the bridge splits them
            l1 = norm(sub(p[1], a))
            l2 = norm(sub(b, p[1]))
            c = mul(1.0 / (l1 + l2), add(mul(l1, mul(0.5, add(a, p[1]))), mul(l2, mul(0.5, add(p[1], b)))))
            length = l1 + l2
        else:
            c = mul(0.5, add(a, b))
            length = norm(sub(b, a))
        rect = mat["rect"]
        mass = RHO * rect[0] * rect[1] * length
    else:                                   # hex20 box, turned
        corners = p[:8]
        c = mul(1.0 / 8, tuple(sum(q[k] for q in corners) for k in range(3)))
        volume = abs(dot(sub(corners[1], corners[0]),
                         cross(sub(corners[3], corners[0]), sub(corners[4], corners[0]))))
        mass = RHO * volume
    return mul(mass, g), c


def statics(model, regions, point):
    """(F, M about point) of all loads on the elements of these regions, and
    the nodal loads on nodes only those elements have."""
    own = set()
    others = set()
    f = (0.0, 0.0, 0.0)
    m = (0.0, 0.0, 0.0)
    for e, r in model.region.items():
        (own if r in regions else others).update(model.elements[e][1])
        if r in regions and model.gravity is not None:
            w, c = element_weight(model, e)
            f = add(f, w)
            m = add(m, cross(sub(c, point), w))
    for name, force in model.forces:
        n = model.nodesets[name][0]
        if n in own and n not in others:
            f = add(f, force)
            m = add(m, cross(sub(model.xyz[n - 1], point), force))
    for name, moment in model.moments:
        n = model.nodesets[name][0]
        if n in own and n not in others:
            m = add(m, moment)
    return f, m


# ---- building the bases -------------------------------------------------------------------------
def _schema2(md, man, bridge_mesh, mecway_name):
    """Schema 2 fields from the bridge's own model data (see the header)."""
    components = {}
    mods = md.get("elset_modelisations", {})
    sections = md.get("beam_sections", {})
    for elset, mod in mods.items():
        name = mecway_name(md, elset)
        if name.endswith("_TRUSS"):
            name = name[:-len("_TRUSS")]
        info = {"model": mod, "has_warping": mod == "POU_D_TG"}
        sec = sections.get(elset) or sections.get(name)
        if sec:
            info["section"] = {"cara": list(sec.get("cara", ())), "vale": list(sec.get("vale", ())),
                               "shape": sec.get("aster_section")}
        components[name] = info
    nodes = md.get("mesh_nodes", {})
    split = md.get("line3_split", ())
    orient = md.get("beam_orientations", {})
    axes = {}
    v_axis = {}
    elsets = {}
    for eid, shape, enodes, elset in md.get("mesh_elements", []):
        elsets[eid] = mecway_name(md, elset)
        mod = mods.get(elset) or mods.get(mecway_name(md, elset))
        if shape not in ("line2", "line3") or not (mod or "").startswith("POU_"):
            continue
        names = bridge_mesh._cell_names(eid, eid in split)
        if shape == "line3" and eid in split:
            halves = ((enodes[0], enodes[1]), (enodes[1], enodes[2]))
        else:
            halves = ((enodes[0], enodes[-1]),)
        for name, (a, b) in zip(names, halves):
            u = unit(sub(nodes[b], nodes[a]))
            v = bridge_mesh._mecway_v_axis(nodes[a], nodes[b], orient.get(eid))
            axes[name] = [list(u), list(v), list(cross(u, v))]
        v_axis[eid] = list(bridge_mesh._mecway_v_axis(nodes[enodes[0]], nodes[enodes[-1]],
                                                       orient.get(eid)))
    not_shared = man.get("not_shared") or []
    man.update({"schema": 2, "components": components, "coef_rigi_drz": None,
                "beam_axes": axes, "excentrement": {},
                "not_shared": dict((k, {"origin": "bridge"}) for k in not_shared),
                "schema2_by": "test"})
    return {"v_axis": v_axis, "mods": dict((mecway_name(md, k), v) for k, v in mods.items()),
            "line3_split": sorted(split)}


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
    u.CONFIG_BRIDGE["analyses"]["lin_static_3d"].update(cfg.get("settings", {}))
    u.CONFIG_BRIDGE["active_analysis"] = "lin_static_3d"
    u.set_run_log(RUN_ID, model)
    from bridge_from_liml import extract_aster_data_from_liml
    import bridge_mesh
    from bridge_to_aster import generate_AsterSolver_files
    from bridge_failure import mecway_name
    import bridge_manifest
    md = extract_aster_data_from_liml(model)
    mail = os.path.join(work, u.run_name(".mail"))
    if not (md and bridge_mesh.write_mesh(mail, md)):
        sys.exit("mesh failed")
    exp = generate_AsterSolver_files(work, md, mail, u.run_name(".resu"))
    if not exp:
        sys.exit("generate failed: see the log")
    with open(os.path.join(work, u.run_name("_console.txt")), "w") as f:
        rc = subprocess.call([u.exe_aster_path(), exp], stdout=f, stderr=subprocess.STDOUT,
                             timeout=1800, creationflags=CREATE_NO_WINDOW)
    print("run_aster exit", rc)
    print("manifest", bridge_manifest.finish_run(work, md, exp, rc == 0))
    names = [n for n in os.listdir(work) if n.endswith(fb_aster.MANIFEST_SUFFIX)]
    if not names:
        return
    path = os.path.join(work, names[0])
    with io.open(path, encoding="utf-8") as f:
        man = json.load(f)
    derived_man = dict(man)
    extra = _schema2(md, derived_man, bridge_mesh, mecway_name)
    if man.get("schema") == 2:
        # the bridge has schema 2 itself: keep it, the derived one aside
        extra["derived"] = derived_man
    else:
        man = derived_man
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(man, indent=1, sort_keys=True))
    with io.open(os.path.join(work, "test_axes.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(extra, indent=1, sort_keys=True))


def build(tags):
    bridge = bridge_folder()
    if not bridge:
        sys.exit("no bridge: set FB_BRIDGE")
    work = os.path.abspath(work_folder())
    if not os.path.isdir(work):
        os.makedirs(work)
    temp = os.path.join(work, "tmp")
    if not os.path.isdir(temp):
        os.makedirs(temp)
    for tag in tags:
        model = MODELS[tag](tag)
        liml = os.path.join(work, tag + ".liml")
        model.write(liml)
        general = dict(model.general, keep_base=True, keep_base_runs=1, ncpus=1)
        cfg_path = os.path.join(work, tag + "_cfg.json")
        with open(cfg_path, "w") as f:
            json.dump({"general": general, "settings": {}}, f)
        env = dict(os.environ, TEMP=temp, TMP=temp, PYTHONDONTWRITEBYTECODE="1")
        t0 = time.time()
        r = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--one", bridge,
                            os.path.join(work, tag), liml, cfg_path], env=env,
                           capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        runs = fb_aster.find_runs(os.path.join(work, tag), None)
        print("%-8s %-7s %5.0f s %5d elements %s" % (
            tag, "ok" if runs else "NO BASE", time.time() - t0, len(model.elements),
            r.stdout.strip()[-50:].replace("\n", " ")))
        if not runs:
            print(r.stderr[-600:])
        sys.stdout.flush()


# ---- the tests -------------------------------------------------------------------------------------
def available(tag):
    folder = os.path.join(work_folder(), tag)
    return (os.path.isfile(EXE) and os.path.isdir(folder) and
            bool(fb_aster.find_runs(folder, None)) and
            os.path.isfile(os.path.join(folder, "test_axes.json")))


class Case(object):
    def __init__(self, tag):
        self.tag = tag
        self.model = MODELS[tag](tag)
        self.mesh = self.model.mesh()
        self.folder = os.path.join(work_folder(), tag)
        fingerprint = fb_aster.mesh_fingerprint(self.mesh["nodes"], list(self.mesh["elements"]))
        runs = fb_aster.find_runs(self.folder, fingerprint)
        if not runs:
            raise unittest.SkipTest("the base of {0} is of another mesh".format(tag))
        self.man = runs[0]
        with io.open(os.path.join(self.folder, "test_axes.json"), encoding="utf-8") as f:
            self.extra = json.load(f)
        self.chosen = self.model.selection()
        self.plan = fb_core.plan_cuts(self.mesh, self.chosen)
        self.props = fb_aster.manifest_props(self.man, self.mesh, self.chosen)
        for e in self.chosen:
            mat = self.model.materials[self.model.comp_mat[self.model.component[e]]]
            self.props[e]["E"] = mat["E"]
            if "thickness" in mat:
                self.props[e]["thickness"] = mat["thickness"]

    def run(self):
        scratch = tempfile.mkdtemp(prefix="fbsh_")
        try:
            job = fb_aster.start(self.man, self.folder, self.plan, self.mesh, EXE, scratch)
            t0 = time.time()
            while job.poll() is None:
                if time.time() - t0 > 900:
                    job.stop()
                    raise AssertionError("timeout")
                time.sleep(0.2)
            if not job.poll():
                raise AssertionError(job.error())
            return job.result()
        finally:
            shutil.rmtree(scratch, True)

    def side(self, group):
        """Region 0 or 2: the side of the rest this cut belongs to."""
        nodes = set(group["nodes"])
        for e, r in self.model.region.items():
            if r != 1 and not nodes.isdisjoint(self.model.elements[e][1]):
                return r
        return None

    def outward(self, group):
        """The outward normal of a cut from the model alone: from the middle
        of the selected nodes next to the cut towards the cut, for a beam
        from its neighbour node to the cut node."""
        nodes = set(group["nodes"])
        xyz = self.mesh["nodes"]
        inner = []
        for e in self.chosen:
            nids = self.model.elements[e][1]
            if not nodes.isdisjoint(nids):
                shape = self.model.elements[e][0]
                if shape == "line2":
                    inner += [n for n in nids if n not in nodes]
                elif shape == "line3":
                    inner.append(nids[1])
                else:
                    inner += [n for n in nids if n not in nodes]
        a = mul(1.0 / len(inner), tuple(sum(xyz[n][k] for n in inner) for k in range(3)))
        b = mul(1.0 / len(nodes), tuple(sum(xyz[n][k] for n in nodes) for k in range(3)))
        d = sub(b, a)
        if group["kind"] == "shell":
            # in the shell plane, perpendicular to the edge
            e = [q for q in self.plan["inside"] if not nodes.isdisjoint(self.model.elements[q][1])][0]
            nids = self.model.elements[e][1]
            pts = [xyz[n] for n in nids]
            corners = pts[0::2] if len(pts) in (6, 8) else pts
            if len(corners) == 4:
                w = unit(cross(sub(corners[2], corners[0]), sub(corners[3], corners[1])))
            else:
                w = unit(cross(sub(corners[1], corners[0]), sub(corners[2], corners[0])))
            edge = sub(xyz[group["nodes"][-1]], xyz[group["nodes"][0]])
            d = sub(d, mul(dot(d, w), w))
            if norm(edge) > 0:
                t = unit(edge)
                d = sub(d, mul(dot(d, t), t))
        return unit(d)


def measure(case, result, rank=None):
    """Per cut: errors against the statics, local checks, the numbers."""
    rank = rank if rank is not None else result["steps"][-1]["rank"]
    per = fb_core.assign_nodes(case.plan, case.mesh, result)
    where = fb_core.positions(result, rank)
    forces = result["forces"][rank]
    out = []
    length = case.model.length
    for g in case.plan["groups"]:
        geo = fb_core.section_geometry(case.mesh, g, case.props)
        point = geo["centroid"]
        idx = per[g["id"]]
        got = fb_core.resultant([where[i] for i in idx], [forces[i] for i in idx], point)
        side = case.side(g)
        if side == 2:
            f, m = statics(case.model, (2,), point)
        else:
            f, m = statics(case.model, (1, 2), point)
            f = mul(-1.0, f)
            m = mul(-1.0, m)
        df = norm(sub(got[:3], f))
        dm = norm(sub(got[3:], m))
        ef = df / max(norm(f), norm(m) / length)
        em = dm / max(norm(m), norm(f) * length)
        n_out = case.outward(g)
        local = fb_core.to_axes(got, geo["axes"])
        out.append({"group": g, "geo": geo, "got": got, "exact": f + m, "eF": ef, "eM": em,
                    "N": local[0], "N_exact": dot(f, n_out), "local": local, "side": side,
                    "normal_dot": dot(geo["axes"][0], n_out)})
    return out


def report(text):
    sys.stderr.write(text + "\n")


class _Base(unittest.TestCase):
    tag = None

    @classmethod
    def setUpClass(cls):
        if not available(cls.tag):
            raise unittest.SkipTest("no base of {0}: build it (see the header)".format(cls.tag))
        cls.case = Case(cls.tag)
        cls.result = cls.case.run()
        cls.cuts = measure(cls.case, cls.result)
        worst = max(max(c["eF"], c["eM"]) for c in cls.cuts)
        REPORT[cls.tag] = worst
        rest = cls.result["rest"][cls.result["steps"][-1]["rank"]]
        report("{0}: eF {1} eM {2}, rest count {3}, drilling {4}, warnings {5}".format(
            cls.tag, ["%.1e" % c["eF"] for c in cls.cuts], ["%.1e" % c["eM"] for c in cls.cuts],
            rest["count"], cls.result.get("drilling"), cls.case.plan["warnings"]))

    def check_numbers(self, bar=BAR):
        self.assertEqual(len(self.cuts), 2)
        self.assertEqual(sorted(c["side"] for c in self.cuts), [0, 2])
        for c in self.cuts:
            self.assertTrue(c["eF"] < bar and c["eM"] < bar, (c["eF"], c["eM"]))

    def check_local(self):
        """N and the normal from the model, not from fb_core: tension positive."""
        for c in self.cuts:
            if c["group"]["kind"] == "mixed":
                continue
            self.assertTrue(c["normal_dot"] > 1 - 1e-6, c["normal_dot"])
            scale = max(norm(c["exact"][:3]), 1e-9)
            self.assertTrue(abs(c["N"] - c["N_exact"]) <= 1e-7 * scale, (c["N"], c["N_exact"]))

    def check_clean_rest(self):
        rank = self.result["steps"][-1]["rank"]
        self.assertEqual(self.result["rest"][rank]["count"], 0, self.result["rest"][rank])
        self.assertEqual(self.result["on_cut"][rank]["count"], 0)


class ShellDKT(_Base):
    tag = "s_dkt"

    def test_numbers(self):
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()
        self.assertEqual(self.case.plan["warnings"], [])
        self.assertEqual(self.result["drilling"], [])
        self.assertTrue(self.result["coef_rigi_drz"] is None)
        for c in self.cuts:
            self.assertEqual(c["group"]["kind"], "shell")
            self.assertTrue(c["geo"]["planar"])

    def test_wrong_normal_is_caught(self):
        # negative control: the normal turned round gives N of the other sign
        for c in self.cuts:
            if abs(c["N_exact"]) > 1.0:
                self.assertTrue(abs(-c["N"] - c["N_exact"]) > 1.0)

    def test_without_rotations_the_moment_is_wrong(self):
        # negative control (E7: 48 %): sum DX..DZ only
        rank = self.result["steps"][-1]["rank"]
        per = fb_core.assign_nodes(self.case.plan, self.case.mesh, self.result)
        where = fb_core.positions(self.result, rank)
        for c in self.cuts:
            idx = per[c["group"]["id"]]
            forces = [tuple(self.result["forces"][rank][i][:3]) + (0.0, 0.0, 0.0) for i in idx]
            got = fb_core.resultant([where[i] for i in idx], forces, c["geo"]["centroid"])
            dm = norm(sub(got[3:], c["exact"][3:]))
            self.assertTrue(dm / max(norm(c["exact"][3:]), 1e-12) > 1e-3)


class ShellTri(_Base):
    tag = "s_tri"

    def test_numbers(self):
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()


class ShellCoque3D(_Base):
    tag = "s_c3d"

    def test_numbers(self):
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()
        self.assertTrue(self.case.man["extra_nodes"])
        # QUAD8_9: the centre nodes are never cut nodes
        count = sum(len(g["nodes"]) for g in self.case.plan["groups"])
        self.assertEqual(len(self.result["nodes"]), count)


class ShellFold(_Base):
    tag = "s_fold"

    def test_warning_and_numbers(self):
        self.assertTrue("drilling" in self.case.plan["warnings"])
        self.assertEqual(self.result["drilling"], ["not_coplanar"])
        self.check_numbers(BAR_DRILL)
        for c in self.cuts:
            self.assertTrue(c["eF"] < BAR)


class ShellDrill(_Base):
    tag = "s_drill"

    def test_warning(self):
        # a moment about the normal of a flat plate, at the tip beyond the
        # cut: both cuts are off (E7: 3e-2), so the warning is there
        self.assertEqual(self.case.plan["drilling"], ["nodal_moment"])
        self.assertEqual(self.result["drilling"], ["nodal_moment"])
        self.check_numbers(BAR_DRILL)
        self.assertTrue(max(c["eM"] for c in self.cuts) > 1e-3)

    def test_no_warning_without_the_moment(self):
        # negative control: the same plate without a nodal moment
        mesh = dict(self.case.mesh, moments={})
        self.assertEqual(fb_core.plan_cuts(mesh, self.case.chosen)["drilling"], [])


class ShellFoldInTheTip(_Base):
    tag = "s_foldtip"

    def test_warning_and_numbers(self):
        # the fold lies beyond the cut and still spoils both cuts
        self.assertEqual(self.case.plan["drilling"], ["not_coplanar"])
        self.check_numbers(BAR_DRILL)
        self.assertTrue(max(c["eM"] for c in self.cuts) > 1e-6)


class ShellI(_Base):
    tag = "s_i"

    def test_section_and_numbers(self):
        self.assertTrue("drilling" in self.case.plan["warnings"])
        for c in self.cuts:
            geo = c["geo"]
            self.assertTrue(geo["planar"])
            self.assertEqual(len(geo["strips"]), 6)
            h, bw, tf, tw = 0.1, 0.05, 0.004, 0.003
            strong = tw * h ** 3 / 12 + 2 * bw * tf * (h / 2) ** 2
            weak = 2 * tf * bw ** 3 / 12
            self.assertTrue(abs(geo["inertia"][0] - strong) < 1e-15, geo["inertia"])
            self.assertTrue(abs(geo["inertia"][1] - weak) < 1e-15, geo["inertia"])
            self.assertTrue(abs(abs(dot(geo["axes"][1], turn((0, 0, 1)))) - 1) < 1e-9)
        self.check_numbers(BAR_DRILL)
        self.check_local()


class ShellOffset(_Base):
    tag = "s_exc"

    def test_offset_of_the_run(self):
        # By equilibrium the resultant of the rest on the selection does not
        # depend on e, so no chain test can see the sign of the shift: what
        # is testable is the value of EXCENTREMENT the bridge wrote and the
        # midline at +e along the normal of the node order, Code-Aster's own
        # convention. Do not try to strengthen this.
        self.check_numbers()
        self.check_local()
        e = self.case.model.offset
        exc = self.case.man.get("excentrement") or {}
        self.assertEqual(sorted(int(k) for k in exc), sorted(self.case.model.elements))
        self.assertTrue(all(abs(float(v) - e) < 1e-15 for v in exc.values()), exc)
        xyz = self.case.mesh["nodes"]
        for c in self.cuts:
            # the midline at +e along the normal of the node order (bridge)
            e1 = c["geo"]["strips"][0]["eid"]
            p = [xyz[n] for n in self.case.model.elements[e1][1]]
            w = unit(cross(sub(p[2], p[0]), sub(p[3], p[1])))
            nodes = c["group"]["nodes"]
            middle = mul(1.0 / len(nodes), tuple(sum(xyz[n][k] for n in nodes) for k in range(3)))
            self.assertTrue(norm(sub(c["geo"]["centroid"], add(middle, mul(e, w)))) < 1e-12)


class _Beams(_Base):
    def check_beam_axes(self):
        """Vy along Mecway's V at both ends; Mz along +W at node 2, -W at node 1
        (contract); V from the bridge's own rule."""
        v_axis = self.case.extra["v_axis"]
        for c in self.cuts:
            beam = c["geo"]["beams"][0]
            e = beam["eid"]
            nids = self.case.model.elements[e][1]
            xyz = self.case.mesh["nodes"]
            u = unit(sub(xyz[nids[-1]], xyz[nids[0]]))
            v = tuple(v_axis[str(e)])
            w = cross(u, v)
            f = c["exact"][:3]
            m = c["exact"][3:]
            sign = 1.0 if beam["end"] == 2 else -1.0
            scale = max(norm(f), norm(m) / self.case.model.length)
            if self.case.elements_straight:
                self.assertTrue(abs(c["local"][1] - dot(f, v)) <= 1e-7 * scale)
                self.assertTrue(abs(c["local"][5] - sign * dot(m, w)) <= 1e-7 * scale *
                                self.case.model.length)


class BeamEuler(_Beams):
    tag = "b_e"

    def test_numbers(self):
        self.case.elements_straight = True
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()
        self.assertEqual(sorted(c["geo"]["beams"][0]["end"] for c in self.cuts), [1, 2])
        self.check_beam_axes()

    def test_wrong_mirror_is_caught(self):
        # negative control: the axes of node 2 at node 1 give the wrong sign
        for c in self.cuts:
            beam = c["geo"]["beams"][0]
            if beam["end"] != 1:
                continue
            axes = self.case.props[beam["eid"]]["beam_axes"]["M"]
            wrong = fb_core.to_axes(c["got"], axes)
            self.assertTrue(abs(wrong[0] + c["N_exact"]) < 1e-6 * max(1.0, abs(c["N_exact"])))
            self.assertTrue(abs(c["N_exact"]) > 1.0)


class BeamTimoshenkoReversed(_Beams):
    tag = "b_t"

    def test_numbers(self):
        self.case.elements_straight = True
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()
        # every element runs tip to root: the cut at the root side is node 2
        self.assertEqual(sorted(c["geo"]["beams"][0]["end"] for c in self.cuts), [1, 2])
        self.check_beam_axes()
        self.assertEqual(self.case.extra["mods"]["Beam"], "POU_D_T")


class BeamLine3(_Beams):
    tag = "b_l3"

    def test_numbers(self):
        self.case.elements_straight = False
        self.check_numbers()
        self.check_local()
        self.check_clean_rest()
        cells = sorted(c["geo"]["beams"][0]["cell"] for c in self.cuts)
        self.assertEqual(cells, ["H", "M"])

    def test_swapped_halves_are_caught(self):
        # negative control: the other half cell gives another normal
        for c in self.cuts:
            beam = c["geo"]["beams"][0]
            cells = self.case.props[beam["eid"]]["beam_axes"]
            other = cells["H" if beam["cell"] == "M" else "M"]
            x = other[0] if beam["end"] == 2 else mul(-1.0, other[0])
            self.assertTrue(dot(x, self.case.outward(c["group"])) < 1 - 1e-4)


class Truss(_Base):
    tag = "b_truss"

    def test_numbers(self):
        self.check_numbers()
        self.check_local()
        for c in self.cuts:
            self.assertTrue(c["geo"]["only_n"])
            self.assertTrue(c["geo"]["beams"][0]["truss"])
        self.assertEqual(self.case.extra["mods"]["Beam"], "BARRE")


class BlockWithShell(_Base):
    tag = "m_block"

    def test_numbers(self):
        self.assertTrue("mixed_cut" in self.case.plan["warnings"])
        self.assertTrue("drilling" in self.case.plan["warnings"])
        for c in self.cuts:
            self.assertEqual(c["group"]["kind"], "mixed")
            self.assertEqual(c["geo"]["axes"], fb_core.GLOBAL_AXES)
        self.check_numbers(BAR_DRILL)
        for c in self.cuts:
            self.assertTrue(c["eF"] < BAR, c["eF"])

    def test_schema_1_is_refused(self):
        man = dict(self.case.man, schema=1, not_shared=[])
        self.assertRaises(fb_core.Refused, fb_aster.check_plan, man, self.case.plan, self.case.mesh)


class BridgeSchema2(unittest.TestCase):
    """The schema 2 of the bridge itself against the one derived here."""

    def test_same_as_derived(self):
        tags = [t for t in MODELS if available(t)]
        own = []
        for tag in tags:
            with io.open(os.path.join(work_folder(), tag, "test_axes.json"), encoding="utf-8") as f:
                extra = json.load(f)
            if extra.get("derived"):
                own.append((tag, extra["derived"]))
        if not own:
            raise unittest.SkipTest("the bridge does not write schema 2 yet")
        for tag, derived in own:
            man = fb_aster.find_runs(os.path.join(work_folder(), tag), None)[0]
            self.assertEqual(man["schema"], 2)
            for name, info in derived["components"].items():
                self.assertEqual(man["components"][name]["model"], info["model"], (tag, name))
            for cell, axes in derived["beam_axes"].items():
                got = man["beam_axes"][cell]
                for a, b in zip(got, axes):
                    self.assertTrue(norm(sub(a, b)) < 1e-9, (tag, cell))


def tearDownModule():
    if REPORT:
        report("worst per case: " + ", ".join("%s %.1e" % (k, v) for k, v in sorted(REPORT.items())))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        run_bridge(*sys.argv[2:6])
    elif len(sys.argv) > 1 and sys.argv[1] == "build":
        build(sys.argv[2:] or sorted(MODELS))
    else:
        unittest.main()
