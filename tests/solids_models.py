# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# solids_models.py
# The self-made models of test_solids_e2e.py, their .liml, and the exact statics
# they are measured against. Nothing here looks at a result of Code-Aster.
#   Model        mesh, selections, loads, materials; write() gives the .liml
#   MODELS       {tag: function that builds a Model}
#   Reference    what the loads do to a set of elements
#   components() the parts of the rest, and what lies behind a cut
#
# The statics reference uses no number of fb_core: positions come from the mesh,
# volumes from shape functions, loaded faces are flat polygons.

import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "research", "experiments"))
import fb_core
import fb_lib

L, B, H = .2, .02, .04
NX, NY, NZ = 12, 2, 4
RHO = 7850.0
GRAVITY = (0.0, 0.0, -9.81)
F_TIP = (2000., 500., -1000.)
F_SIDE = (0., 0., -300.)
STEEL = {"E": 210e9, "nu": 0.3, "rho": RHO}
ALU = {"E": 70e9, "nu": 0.33, "rho": 2700.0}
ORDER = {"hex": ("hex8", "hex20"), "wedge": ("wedge6", "wedge15"),
         "tet": ("tet4", "tet10"), "pyr": ("pyr5", "pyr13")}
# Corners of a cell in the order of a hex
UNIT = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))


class Model(object):
    def __init__(self, tag, warp=None):
        self.tag = tag
        self.warp = warp or (lambda p: tuple(p))
        self.key = {}
        self.xyz = []
        self.ref = []
        self.elements = {}
        self.component = {}
        self.cells = {}
        self.faces = {}
        self.nodesets = {}
        self.fixed = []
        self.loads = []
        self.gravity = GRAVITY
        self.materials = {"Steel": STEEL}
        self.comp_mat = {"P": "Steel"}
        self.extra = ""
        self.steps = None
        self.general = {}
        self.settings = {}
        self.chosen = []

    # ---- mesh -------------------------------------------------------------------
    def node(self, p, part=0):
        k = (part, int(round(p[0] * 1e9)), int(round(p[1] * 1e9)), int(round(p[2] * 1e9)))
        if k not in self.key:
            self.ref.append(tuple(float(v) for v in p))
            self.xyz.append(tuple(float(v) for v in self.warp(p)))
            self.key[k] = len(self.xyz)
        return self.key[k]

    def add(self, shape, corners, comp="P", part=0):
        """An element from its corners; midside nodes halfway in the reference
        shape, so a warp bends the edges."""
        faces, edges, count, quadratic = fb_core._FAMILIES[shape]
        points = [np.array(c, float) for c in corners]
        if quadratic:
            points += [(points[a] + points[b]) / 2 for a, b in edges]
        eid = len(self.elements) + 1
        self.elements[eid] = (shape, [self.node(p, part) for p in points])
        self.component[eid] = comp
        return eid

    def cell(self, ijk, kind, order, d, comp="P", part=0, origin=(0, 0, 0)):
        """One cell of the grid as elements. kind: hex, tet, wz (wedges along
        z), wx (wedges along x), pyr, or trans (pyramid on the face x = low,
        tets on the other faces, diagonals as the tets of the next cell)."""
        low = np.array(origin, float) + np.array(ijk, float) * np.array(d, float)
        c = [low + np.array(u, float) * d for u in UNIT]
        out = []

        def tet(v):
            a = np.array([v[1] - v[0], v[2] - v[0], v[3] - v[0]])
            if np.linalg.det(a) < 0:
                v = [v[0], v[2], v[1], v[3]]
            out.append(self.add(ORDER["tet"][order], v, comp, part))

        def wedge(v):
            out.append(self.add(ORDER["wedge"][order], v, comp, part))

        def pyramid(face, apex):
            a, b, e, f = [c[q] for q in face]
            out.append(self.add(ORDER["pyr"][order], [a, f, e, b, apex], comp, part))
        if kind == "hex":
            out.append(self.add(ORDER["hex"][order], c, comp, part))
        elif kind == "tet":
            for t in fb_lib.TET_SPLIT:
                tet([c[q] for q in t])
        elif kind == "wz":
            wedge([c[q] for q in (0, 1, 2, 4, 5, 6)])
            wedge([c[q] for q in (0, 2, 3, 4, 6, 7)])
        elif kind == "wx":
            wedge([c[q] for q in (0, 3, 7, 1, 2, 6)])
            wedge([c[q] for q in (0, 7, 4, 1, 6, 5)])
        elif kind == "pyr":
            centre = low + np.array(d, float) / 2
            for face in fb_core._HEX_FACES:
                pyramid(face, centre)
        elif kind == "trans":
            centre = low + np.array(d, float) / 2
            for face in fb_core._HEX_FACES:
                if set(face) == set((0, 3, 4, 7)):
                    pyramid(face, centre)
                    continue
                # The diagonal through corner 0 or 6: the one of the tets
                corner = 0 if 0 in face else 6
                n = list(face)
                i = n.index(corner)
                a, b, e, f = n[i:] + n[:i]
                tet([c[q] for q in (a, b, e)] + [centre])
                tet([c[q] for q in (a, e, f)] + [centre])
        else:
            raise ValueError(kind)
        self.cells[tuple(ijk)] = out
        return out

    def free_faces(self):
        """[(eid, faceid, corner nodes)] of the faces on one element only."""
        seen = {}
        for eid, (shape, nids) in self.elements.items():
            for i, face in enumerate(fb_core._FAMILIES[shape][0]):
                corners = [nids[k] for k in face]
                seen.setdefault(tuple(sorted(corners)), []).append((eid, i + 1, corners))
        return [v[0] for v in seen.values() if len(v) == 1]

    def pick(self, where):
        """Free faces whose centre in the reference shape satisfies where."""
        out = []
        for eid, faceid, corners in self.free_faces():
            if where(np.mean([self.ref[n - 1] for n in corners], axis=0)):
                out.append((eid, faceid))
        return sorted(out)

    def mesh(self):
        return {"nodes": dict((i + 1, p) for i, p in enumerate(self.xyz)),
                "elements": dict(self.elements), "component": dict(self.component)}

    def props(self):
        return dict((e, {"E": self.materials[self.comp_mat[c]]["E"]})
                    for e, c in self.component.items())

    def fixed_nodes(self):
        out = set()
        for name in self.fixed:
            if name in self.nodesets:
                out.update(self.nodesets[name])
            else:
                for eid, faceid in self.faces[name]:
                    shape, nids = self.elements[eid]
                    out.update(nids[k] for k in fb_core.face_local_nodes(shape, faceid))
        return out

    # ---- .liml ----------------------------------------------------------------------
    def write(self, path):
        text = ['<?xml version="1.0" encoding="utf-8"?>', '<liml version="34">']
        if self.steps:
            text.append('  <analysis type="L30" />')
            text.append('  <timesteps timeperiod="1 s" stepsize="%s s" />' % self.steps)
        else:
            text.append('  <analysis type="S30" />')
        for i, p in enumerate(self.xyz):
            text.append('  <node nid="%d" x="%r" y="%r" z="%r" />' % (i + 1, p[0], p[1], p[2]))
        for comp in sorted(self.comp_mat):
            text.append('  <elset name="%s" material="%s" colorrgb="00C800">' % (
                comp, self.comp_mat[comp]))
            for eid in sorted(self.elements):
                if self.component[eid] == comp:
                    shape, nids = self.elements[eid]
                    text.append('    <elem eid="%d" shape="%s" nodes="%s" />' % (
                        eid, shape, " ".join(str(n) for n in nids)))
            text.append('  </elset>')
        for name, mat in self.materials.items():
            plastic = ""
            if mat.get("yield"):
                plastic = ('<plastic type="BilinearIsotropic" yieldstrength="%d Pa" '
                           'tangentmodulus="%d Pa" />' % (mat["yield"], mat["tangent"]))
            text.append('  <mat name="%s"><mechanical type="Isotropic" youngsmodulus="%d Pa" '
                        'poissonratio="%r" />%s<density type="Simple" density="%r kg/m&#179;" />'
                        '</mat>' % (name, int(mat["E"]), mat["nu"], plastic, mat["rho"]))
        for name, faces in sorted(self.faces.items()):
            text.append('  <faceselection name="%s">' % name + "".join(
                '<face eid="%d" faceid="%d" />' % f for f in faces) + '</faceselection>')
        for name, nodes in sorted(self.nodesets.items()):
            text.append('  <nodeselection name="%s">' % name + "".join(
                '<node nid="%d" />' % n for n in nodes) + '</nodeselection>')
        for name in self.fixed:
            text.append('  <fixed selection="%s" />' % name)
        for load in self.loads:
            if load[0] == "force":
                text.append('  <force selection="%s"><x>%r N</x><y>%r N</y><z>%r N</z></force>' % (
                    load[1], float(load[2][0]), float(load[2][1]), float(load[2][2])))
            else:
                text.append('  <surfacepressure selection="%s"><normal>%r Pa</normal>'
                            '</surfacepressure>' % (load[1], float(load[2])))
        if self.gravity is not None:
            text.append('  <gravity><x>%r m/s&#178;</x><y>%r m/s&#178;</y><z>%r m/s&#178;</z>'
                        '</gravity>' % tuple(float(v) for v in self.gravity))
        if self.extra:
            text.append(self.extra)
        for name, unit in (("displacement", "m"), ("stress", "Pa"), ("reaction force", "N")):
            text.append('  <fieldvariable name="%s" displayunit="%s" expanded="true" />' % (name, unit))
        text.append('</liml>')
        with io.open(path, "w", encoding="ascii", newline="\n") as f:
            f.write(u"\n".join(text))


# ---- statics --------------------------------------------------------------------------------
def _points(shape):
    """(natural point, weight) for one element; shapes without shape functions
    in fb_lib go as a collapsed hex: see _COLLAPSED."""
    if shape.startswith("hex"):
        return fb_lib.gauss_hex(4)
    if shape.startswith("tet"):
        return fb_lib.gauss_tet()
    return fb_lib.gauss_hex(5)


# Straight sided wedges and pyramids as a hex with coinciding corners: the same
# region, and the Jacobian stays a polynomial
_COLLAPSED = {"wedge": (0, 1, 2, 2, 3, 4, 5, 5), "pyr": (0, 1, 2, 3, 4, 4, 4, 4)}


def element_points(model, eid, u=None):
    """[(volume weight, point in the deformed shape)] of an element."""
    shape, nids = model.elements[eid]
    x = np.array([model.xyz[n - 1] for n in nids])
    d = np.zeros_like(x) if u is None else np.array([u[n - 1] for n in nids])
    out = []
    if shape.startswith("wedge") or shape.startswith("pyr"):
        if u is not None:
            raise ValueError("no large displacements on " + shape)
        c = x[list(_COLLAPSED[shape[:5] if shape[0] == "w" else "pyr"])]
        for q, w in _points(shape):
            n, dn = fb_lib.sf_hex8(*q)
            out.append((abs(np.linalg.det(c.T @ dn)) * w, n @ c))
        return out
    sf = fb_lib.SF[shape]
    for q, w in _points(shape):
        n, dn = sf(*q)
        out.append((abs(np.linalg.det(x.T @ dn)) * w, n @ (x + d)))
    return out


def polygon(points):
    """Area vector and centre of a flat polygon."""
    p = np.array(points)
    vector = np.zeros(3)
    first = np.zeros(3)
    for i in range(1, len(p) - 1):
        a = np.cross(p[i] - p[0], p[i + 1] - p[0]) / 2
        vector += a
        first += np.linalg.norm(a) * (p[0] + p[i] + p[i + 1]) / 3
    size = np.linalg.norm(vector)
    return vector, first / size


class Reference(object):
    """The loads of a model as (force, point) per element."""

    def __init__(self, model, u=None, gravity=True):
        self.model = model
        self.u = u
        self.items = {}
        self.gravity = gravity and model.gravity is not None
        self.g = np.array(model.gravity if model.gravity is not None else (0., 0., 0.))
        for load in model.loads:
            self._load(load)

    def _face(self, eid, faceid):
        """Outward area vector and centre of a flat face."""
        m = self.model
        shape, nids = m.elements[eid]
        corners = [nids[k] for k in fb_core._FAMILIES[shape][0][faceid - 1]]
        v, c = polygon([m.xyz[n - 1] for n in corners])
        middle = np.mean([m.xyz[n - 1] for n in nids[:fb_core._FAMILIES[shape][2]]], axis=0)
        if np.dot(c - middle, v) < 0:
            v = -v
        return v, c

    def _deformed(self, eid, faceid, outward):
        """[(area vector on x + u, area of the point undeformed, x + u)] of a
        flat-born face of a hex20, at its quadrature points."""
        m = self.model
        shape, nids = m.elements[eid]
        x = np.array([m.xyz[n - 1] for n in nids])
        u = np.array([self.u[n - 1] for n in nids])
        out = []
        for p, w, dxi, de in fb_lib.face_points(shape, faceid - 1):
            n, dn = fb_lib.SF[shape](*p)
            j0 = x.T @ dn
            j1 = (x + u).T @ dn
            vector = np.cross(j1 @ dxi, j1 @ de) * w
            sense = 1.0 if np.dot(np.cross(j0 @ dxi, j0 @ de), outward) > 0 else -1.0
            out.append((sense * vector, np.linalg.norm(np.cross(j0 @ dxi, j0 @ de)) * w,
                        n @ (x + u)))
        return out

    def _load(self, load):
        m = self.model
        kind, name, value = load
        if name in m.nodesets:
            nids = m.nodesets[name]
            for n in nids:
                self.items.setdefault(("node", n), []).append(
                    (np.array(value, float) / len(nids), np.array(m.xyz[n - 1])))
            return
        faces = m.faces[name]
        rows = [(e, f) + self._face(e, f) for e, f in faces]
        area = sum(np.linalg.norm(r[2]) for r in rows)
        for e, f, v, c in rows:
            items = self.items.setdefault(e, [])
            if self.u is not None:
                for vector, a, x in self._deformed(e, f, v):
                    q = np.array(value, float) * a / area if kind == "force" else -value * vector
                    items.append((q, x))
            elif kind == "force":
                items.append((np.array(value, float) * np.linalg.norm(v) / area, c))
            else:
                items.append((-value * v, c))

    def of(self, eids, point, nodes=()):
        """(force, moment about point) of the loads on these elements, gravity
        included, and on these loaded nodes."""
        m = self.model
        point = np.array(point, float)
        f = np.zeros(3)
        c = np.zeros(3)
        for e in eids:
            if self.gravity:
                rho = m.materials[m.comp_mat[m.component[e]]]["rho"]
                for w, x in element_points(m, e, self.u):
                    q = rho * self.g * w
                    f += q
                    c += np.cross(x - point, q)
            for q, x in self.items.get(e, ()):
                f += q
                c += np.cross(x - point, q)
        for n in nodes:
            for q, x in self.items.get(("node", n), ()):
                f += q
                c += np.cross(x - point, q)
        return f, c


def components(model, eids):
    """[(elements, nodes)] of the connected parts of a set of elements."""
    up = {}

    def find(a):
        up.setdefault(a, a)
        while up[a] != a:
            up[a] = up[up[a]]
            a = up[a]
        return a
    for e in eids:
        nids = model.elements[e][1]
        for n in nids[1:]:
            up[find(n)] = find(nids[0])
    parts = {}
    for e in eids:
        parts.setdefault(find(model.elements[e][1][0]), []).append(e)
    out = []
    for es in parts.values():
        nodes = set()
        for e in es:
            nodes.update(model.elements[e][1])
        out.append((es, nodes))
    return out


def behind(model, plan):
    """
    {group id: ("own" or "others", elements)}: "own": the part of the rest
    behind the cut is free, the rest does to the selection what the loads do to
    that part. "others": that part holds the supports, the rest does to the
    selection minus the loads on all else. Only for a part that touches one
    cut and a cut that touches one part: anything else has no statics per cut.
    """
    parts = components(model, plan["outside"])
    fixed = model.fixed_nodes()
    out = {}
    for g in plan["groups"]:
        nodes = set(g["nodes"])
        touching = [p for p in parts if p[1] & nodes]
        if len(touching) != 1:
            return None
        part = touching[0]
        if sum(1 for h in plan["groups"] if part[1] & set(h["nodes"])) != 1:
            return None
        if part[1] & fixed:
            if fixed - part[1]:
                return None
            out[g["id"]] = ("others", [e for e in model.elements if e not in set(part[0])])
        else:
            out[g["id"]] = ("own", part[0])
    return out


# ---- the models -----------------------------------------------------------------------------
def bar(tag, kinds, order, warp=None, general=None, size=(NX, NY, NZ), comp=None,
        loads=True, length=(L, B, H)):
    """Bar in x, clamped at x = 0, a force on the tip, a force on the selection
    next to the first cut, gravity; selection: the middle half."""
    m = Model(tag, warp)
    nx, ny, nz = size
    d = (length[0] / nx, length[1] / ny, length[2] / nz)
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                kind = kinds(i, j, k) if callable(kinds) else kinds
                m.cell((i, j, k), kind, order, d, comp(i, j, k) if comp else "P")
    m.chosen = [q for (i, j, k), es in m.cells.items() if nx // 4 <= i < 3 * nx // 4 for q in es]
    m.size = size
    m.d = d
    m.dims = length
    eps = 1e-9
    if loads:
        m.faces["CLAMP"] = m.pick(lambda c: abs(c[0]) < eps)
        m.fixed = ["CLAMP"]
        m.faces["TIP"] = m.pick(lambda c: abs(c[0] - length[0]) < eps)
        m.faces["SIDE"] = m.pick(lambda c: abs(c[2] - length[2]) < eps and
                                 nx // 4 * d[0] < c[0] < (nx // 4 + 2) * d[0])
        m.loads = [("force", "TIP", F_TIP), ("force", "SIDE", F_SIDE)]
    if general:
        m.general.update(general)
    return m


def layers_mixed(i, j, k):
    # hex | pyramids and tets | tets | wedges along x: the first cut lies between
    # hex and pyramid bases, the second between tets and wedges
    if i < NX // 4:
        return "hex"
    if i == NX // 4:
        return "trans"
    return "tet" if i < 3 * NX // 4 else "wx"


def bump(p):
    """Inside the bar only: the outer faces stay where they are."""
    s = np.sin(np.pi * p[0] / L) * np.sin(np.pi * p[1] / B) * np.sin(np.pi * p[2] / H)
    return (p[0] + .3 * L / NX * s, p[1] + .3 * B / NY * s, p[2] - .3 * H / NZ * s)


ALPHA = 0.6


def trapezoid(p):
    """Section with width B (1 + ALPHA (z/H - 1/2)): a trapezoid of area B H."""
    return (p[0], p[1] * (1 + ALPHA * (p[2] / H - .5)), p[2])


SHEAR = (.5, .25)


def sheared(p):
    """Planes x = const become oblique: a planar cut with a general normal."""
    return (p[0] + SHEAR[0] * (p[1] - B / 2) + SHEAR[1] * (p[2] - H / 2), p[1], p[2])


def block_on_edges(tag, order, general=None):
    """A free block S that touches the rest in one line of nodes and one other
    node, nothing else: no cut face, and still stable."""
    m = Model(tag)
    d = (L / NX, B / NY, H / NZ)
    block = [(i, j, k) for i in range(2, 6) for j in (0, 1) for k in (0, 1)]
    rest = ([(i, j, 3) for i in range(1, 7) for j in range(4)] +
            [(1, 0, 2), (1, 1, 2), (6, 2, 2)])
    for c in block + rest:
        m.cell(c, "hex", order, d)
    m.chosen = [q for c in block for q in m.cells[c]]
    top = 4 * d[2]
    m.faces["CLAMP"] = m.pick(lambda c: abs(c[2] - top) < 1e-9)
    m.fixed = ["CLAMP"]
    m.faces["BELOW"] = m.pick(lambda c: abs(c[2]) < 1e-9)
    m.loads = [("force", "BELOW", (100., -50., -200.))]
    if general:
        m.general.update(general)
    return m


def two_materials(tag):
    m = bar(tag, "hex", 1, comp=lambda i, j, k: "B" if k < NZ // 2 else "T")
    m.materials = {"Steel": STEEL, "Alu": ALU}
    m.comp_mat = {"B": "Steel", "T": "Alu"}
    return m


def strip_support(tag, x0, x1, order=1):
    """Held only by a strip at the bottom: both ends free."""
    m = bar(tag, "hex", order)
    m.fixed = ["STRIP"]
    del m.faces["CLAMP"]
    m.faces["STRIP"] = m.pick(lambda c: abs(c[2]) < 1e-9 and x0 < c[0] < x1)
    return m


def line_support(tag):
    """The clamp, and a support on one line of nodes in the plane of a cut."""
    m = bar(tag, "hex", 1)
    x = L / 2
    m.nodesets["LINE"] = [i + 1 for i, p in enumerate(m.xyz)
                          if abs(p[0] - x) < 1e-9 and abs(p[2]) < 1e-9]
    m.fixed = ["CLAMP", "LINE"]
    m.chosen = [q for (i, j, k), es in m.cells.items() if NX // 2 <= i < 3 * NX // 4 for q in es]
    return m


def nodal(tag):
    """Forces on single nodes: one off the cuts inside the selection, one on a
    cut. The selection has both."""
    m = bar(tag, "hex", 1)
    d = m.d
    mid = (L / 2, 0.0, H)
    cut = (NX // 4 * d[0], 0.0, H)
    m.nodesets["N_IN"] = [m.key[(0,) + tuple(int(round(v * 1e9)) for v in mid)]]
    m.nodesets["N_CUT"] = [m.key[(0,) + tuple(int(round(v * 1e9)) for v in cut)]]
    m.loads += [("force", "N_IN", (30., 40., -50.)), ("force", "N_CUT", (-20., 10., 60.))]
    return m


def pressure(tag, steps=None, load=4e6):
    """A pressure on a flat free face of the selection next to the first cut,
    and one on the rest."""
    m = bar(tag, "hex", 1, size=(12, 2, 4))
    d = m.d
    m.faces["P_IN"] = m.pick(lambda c: abs(c[1]) < 1e-9 and
                             NX // 4 * d[0] < c[0] < (NX // 4 + 2) * d[0])
    m.faces["P_OUT"] = m.pick(lambda c: abs(c[1]) < 1e-9 and c[0] > 10 * d[0])
    m.loads += [("pressure", "P_IN", load), ("pressure", "P_OUT", load)]
    if steps:
        m.steps = steps
        m.materials = {"Steel": dict(STEEL, **{"yield": 250e6, "tangent": 2e9})}
        m.loads[0] = ("force", "TIP", (0., 0., -12000.))
        m.loads[1] = ("force", "SIDE", (0., 0., -300.))
    return m


def tied(tag):
    """Two parts with their own nodes at x = L/2, not matching, and a tie."""
    m = Model(tag)
    d = (L / NX, B / NY, H / NZ)
    for i in range(NX // 2):
        for j in range(NY):
            for k in range(NZ):
                m.cell((i, j, k), "hex", 1, d)
    d2 = (d[0], B / NY, H / 3)
    start = len(m.elements)
    for i in range(NX // 2):
        for j in range(NY):
            for k in range(3):
                m.cell((NX // 2 + i, j, k), "hex", 1, d2, part=1)
    m.part_two = [e for e in m.elements if e > start]
    m.d = d
    m.size = (NX, NY, NZ)
    m.dims = (L, B, H)
    right = set(m.part_two)
    m.faces["CLAMP"] = m.pick(lambda c: abs(c[0]) < 1e-9)
    m.fixed = ["CLAMP"]
    m.faces["TIP"] = m.pick(lambda c: abs(c[0] - L) < 1e-9)
    m.faces["T_A"] = [f for f in m.pick(lambda c: abs(c[0] - L / 2) < 1e-9) if f[0] not in right]
    m.faces["T_B"] = [f for f in m.pick(lambda c: abs(c[0] - L / 2) < 1e-9) if f[0] in right]
    m.loads = [("force", "TIP", F_TIP)]
    m.extra = ('  <contact2 selectionmaster="T_A" selectionslave="T_B" type="bondedtie" '
               'selfcontact="false"><tolerance>0.001 m</tolerance><stiffnessfactor>1'
               '</stiffnessfactor><normalstiffness>0 Pa/m</normalstiffness>'
               '<tangentialstiffness>0 Pa/m</tangentialstiffness><frictioncoefficient>0'
               '</frictioncoefficient></contact2>')
    return m


def big(tag, steps=None):
    """About 20 000 hex20."""
    m = bar(tag, "hex", 1, size=(100, 10, 20))
    m.settings = {"memory_limit": 12000}
    m.general["ncpus"] = 4
    if steps:
        m.steps = steps
        m.materials = {"Steel": dict(STEEL, **{"yield": 250e6, "tangent": 2e9})}
        m.loads = [("force", "TIP", (0., 0., -12000.)), ("force", "SIDE", F_SIDE)]
    return m


LQ = {"elem_hex8": "LINE_QUAD"}
MODELS = {
    "a_hex8": lambda t: bar(t, "hex", 0),
    "a_hex20": lambda t: bar(t, "hex", 1),
    "a_tet4": lambda t: bar(t, "tet", 0),
    "a_tet10": lambda t: bar(t, "tet", 1),
    "a_w6z": lambda t: bar(t, "wz", 0),
    "a_w6x": lambda t: bar(t, "wx", 0),
    "a_w15z": lambda t: bar(t, "wz", 1),
    "a_w15x": lambda t: bar(t, "wx", 1),
    "a_pyr5": lambda t: bar(t, "pyr", 0),
    "a_pyr13": lambda t: bar(t, "pyr", 1),
    "b_hw": lambda t: bar(t, lambda i, j, k: "hex" if 3 <= i < 9 else "wz", 0),
    "b_mix": lambda t: bar(t, layers_mixed, 0),
    "b_mix2": lambda t: bar(t, layers_mixed, 1),
    "b_mixlq": lambda t: bar(t, layers_mixed, 0, general=LQ),
    "c_lq": lambda t: bar(t, "hex", 0, general=LQ),
    "d_hex8": lambda t: bar(t, "hex", 0, bump),
    "d_hex20": lambda t: bar(t, "hex", 1, bump),
    "d_tet10": lambda t: bar(t, "tet", 1, bump),
    "d_trap": lambda t: bar(t, "hex", 1, trapezoid),
    "d_obl": lambda t: bar(t, "hex", 1, sheared),
    "d_oblw": lambda t: bar(t, "wx", 1, sheared),
    "e_hex8": lambda t: block_on_edges(t, 0),
    "e_hex20": lambda t: block_on_edges(t, 1),
    "e_lq": lambda t: block_on_edges(t, 0, LQ),
    "f_two": two_materials,
    "g_strip": lambda t: strip_support(t, .4 * L, .6 * L),
    "g_line": line_support,
    "g_tie": tied,
    "g_nodal": nodal,
    "g_press": pressure,
    "n_press": lambda t: pressure(t, steps=.25, load=4e5),
    "k_lin": big,
    "k_nl": lambda t: big(t, steps=.25),
}
NEEDS_POST = ("g_line", "g_strip", "n_press", "k_nl")


def settings_json(model):
    general = dict({"ncpus": 2}, keep_base=True, keep_base_runs=2, **model.general)
    return json.dumps({"general": general, "settings": model.settings})
