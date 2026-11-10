# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_model.py
# Self-made block models for the panel tests: a steel bar clamped at x = 0
# with a force on the end at x = L. Writes the .liml and a JSON with the nodes
# and elements as they were written, so a test in Mecway can compare what the
# API gives back. CPython 3 and IronPython 2.7, no numpy.

import io
import json

HEX_CORNERS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
               (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
# Mecway order of hex20: corners, then bottom, vertical and top midsides
HEX_MIDS = [(0, -1, -1), (1, 0, -1), (0, 1, -1), (-1, 0, -1),
            (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
            (0, -1, 1), (1, 0, 1), (0, 1, 1), (-1, 0, 1)]
# Tets of a cell around the diagonal 0-6, each with a positive volume
TET_SPLIT = [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
             (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]
TET_EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
FACE_X_LOW = 6      # 1-based face of a hex at x = lowest
FACE_X_HIGH = 4     # 1-based face of a hex at x = highest


class Mesh(object):
    def __init__(self):
        self.ids = {}
        self.xyz = {}
        self.elements = {}

    def node(self, x, y, z):
        key = (int(round(x * 1e9)), int(round(y * 1e9)), int(round(z * 1e9)))
        if key not in self.ids:
            nid = len(self.ids) + 1
            self.ids[key] = nid
            self.xyz[nid] = (x, y, z)
        return self.ids[key]


def _point(o, d, q):
    return tuple(o[i] + d[i] * (q[i] + 1) / 2.0 for i in range(3))


def _middle(a, b):
    return tuple((a[i] + b[i]) / 2.0 for i in range(3))


def _volume6(p):
    a = [p[1][i] - p[0][i] for i in range(3)]
    b = [p[2][i] - p[0][i] for i in range(3)]
    c = [p[3][i] - p[0][i] for i in range(3)]
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) -
            a[1] * (b[0] * c[2] - b[2] * c[0]) +
            a[2] * (b[0] * c[1] - b[1] * c[0]))


def block(shape, length=0.2, width=0.02, height=0.04, cells=(5, 2, 2)):
    """Mesh of the bar in hex8, hex20, tet4 or tet10, and the faces at both
    ends as [(eid, 1-based face)] (hex only: tets get node loads)."""
    m = Mesh()
    d = (length / cells[0], width / cells[1], height / cells[2])
    low, high = [], []
    eid = 0
    for i in range(cells[0]):
        for j in range(cells[1]):
            for k in range(cells[2]):
                o = (i * d[0], j * d[1] - width / 2.0, k * d[2] - height / 2.0)
                corners = [_point(o, d, q) for q in HEX_CORNERS]
                if shape.startswith("hex"):
                    pts = list(corners)
                    if shape == "hex20":
                        pts += [_point(o, d, q) for q in HEX_MIDS]
                    eid += 1
                    m.elements[eid] = (shape, [m.node(*p) for p in pts])
                    if i == 0:
                        low.append((eid, FACE_X_LOW))
                    if i == cells[0] - 1:
                        high.append((eid, FACE_X_HIGH))
                    continue
                for tet in TET_SPLIT:
                    v = [corners[t] for t in tet]
                    if _volume6(v) < 0:
                        v[1], v[2] = v[2], v[1]
                    pts = list(v)
                    if shape == "tet10":
                        pts += [_middle(v[a], v[b]) for a, b in TET_EDGES]
                    eid += 1
                    m.elements[eid] = (shape, [m.node(*p) for p in pts])
    return m, low, high


def _num(v):
    """Fixed point: a float in a file never goes through the g format."""
    return "%.12f" % v


def write_liml(path, m, low=None, high=None, force=(0.0, 0.0, -1000.0),
               fields=("displacement", "stress", "reaction force"), json_path=None):
    lines = [u'<?xml version="1.0" encoding="utf-8"?>', u'<liml version="34">',
             u'  <analysis type="S30" />']
    for nid in sorted(m.xyz):
        x, y, z = m.xyz[nid]
        lines.append(u'  <node nid="{0}" x="{1}" y="{2}" z="{3}" />'.format(
            nid, _num(x), _num(y), _num(z)))
    lines.append(u'  <elset name="Bar" material="Steel" colorrgb="00C800">')
    for eid in sorted(m.elements):
        shape, nodes = m.elements[eid]
        lines.append(u'    <elem eid="{0}" shape="{1}" nodes="{2}" />'.format(
            eid, shape, u" ".join(str(n) for n in nodes)))
    lines.append(u'  </elset>')
    lines.append(u'  <mat name="Steel"><mechanical type="Isotropic" '
                 u'youngsmodulus="210000000000 Pa" poissonratio="0.3" /></mat>')
    if low:
        lines.append(u'  <faceselection name="CLAMP">' + u"".join(
            u'<face eid="{0}" faceid="{1}" />'.format(e, f) for e, f in low) +
            u'</faceselection>')
        lines.append(u'  <fixed selection="CLAMP" />')
    if high:
        lines.append(u'  <faceselection name="END">' + u"".join(
            u'<face eid="{0}" faceid="{1}" />'.format(e, f) for e, f in high) +
            u'</faceselection>')
        lines.append(u'  <force selection="END"><x>{0} N</x><y>{1} N</y>'
                     u'<z>{2} N</z></force>'.format(*[_num(v) for v in force]))
    for field in fields:
        unit = {"stress": "Pa", "displacement": "m"}.get(field, "N")
        lines.append(u'  <fieldvariable name="{0}" displayunit="{1}" '
                     u'expanded="true" />'.format(field, unit))
    lines.append(u'</liml>')
    with io.open(path, "w", encoding="utf-8", newline=u"\n") as f:
        f.write(u"\n".join(lines))
    if json_path:
        data = {"nodes": dict((str(k), list(v)) for k, v in m.xyz.items()),
                "elements": dict((str(k), [v[0], v[1]])
                                 for k, v in m.elements.items())}
        with io.open(json_path, "w", encoding="utf-8") as f:
            f.write(u"{0}".format(json.dumps(data)))


# ---- shells and beams (phase 4) ----------------------------------------------------
def plate(length=0.3, width=0.1, cells=(3, 1), beam_along=False):
    """A flat plate of quad4 in the plane z = 0, x from 0 to length; element
    eid = i * cells[1] + j + 1. beam_along: line2 beams on the edge y = 0 as
    well, eids after the shells. Returns (mesh, {eid: component})."""
    m = Mesh()
    dx, dy = length / cells[0], width / cells[1]
    component = {}
    eid = 0
    for i in range(cells[0]):
        for j in range(cells[1]):
            x, y = i * dx, j * dy
            eid += 1
            m.elements[eid] = ("quad4", [m.node(x, y, 0.0), m.node(x + dx, y, 0.0),
                                         m.node(x + dx, y + dy, 0.0),
                                         m.node(x, y + dy, 0.0)])
            component[eid] = u"Plate"
    if beam_along:
        for i in range(cells[0]):
            eid += 1
            m.elements[eid] = ("line2", [m.node(i * dx, 0.0, 0.0),
                                         m.node((i + 1) * dx, 0.0, 0.0)])
            component[eid] = u"Rib"
    return m, component


def frame_bar(length=0.3, cells=3, name=u"Beam"):
    """Line2 beams along x from 0 to length; eid i + 1 runs from node i + 1 to
    i + 2."""
    m = Mesh()
    d = length / cells
    for i in range(cells):
        m.elements[i + 1] = ("line2", [m.node(i * d, 0.0, 0.0),
                                       m.node((i + 1) * d, 0.0, 0.0)])
    return m, dict((e, name) for e in m.elements)


SHELL_MATERIAL = (u'  <mat name="Plate5"><geometric type="Plate" thickness="0.005 m" />'
                  u'<mechanical type="Isotropic" youngsmodulus="210000000000 Pa" '
                  u'poissonratio="0.3" /></mat>')
BEAM_MATERIAL = (u'  <mat name="Rect"><geometric type="RectBar" recta="0.02 m" rectb="0.01 m" />'
                 u'<mechanical type="Isotropic" youngsmodulus="70000000000 Pa" '
                 u'poissonratio="0.3" /></mat>')


def _at(m, x, y):
    return m.ids[(int(round(x * 1e9)), int(round(y * 1e9)), 0)]


def shell_loads(m):
    """Moment loads on the plate of write_shell_liml, as Mecway saves them:
    (liml lines, {selection: node ids or [(eid, faceid)]}, the moments
    fb_mecway should find {nid: (mx, my, mz)} in N.m). A moment about the
    normal in kN.m, one in the plane, one on a beam end in N.mm, a rotation
    about the normal; and what is no nodal moment: two nodes, a shell face, a
    rotation held at zero."""
    tip, mid = _at(m, 0.3, 0.1), _at(m, 0.2, 0.1)
    beam_end, turned, root = _at(m, 0.3, 0.0), _at(m, 0.1, 0.1), _at(m, 0.0, 0.0)
    rib_end = [e for e, (s, n) in m.elements.items() if s == "line2" and n[1] == beam_end][0]
    members = {u"MN1": [tip], u"MIN": [mid], u"MN2": [tip, mid], u"ROT": [turned],
               u"HOLD": [root], u"BE": [(rib_end, 3)], u"PF": [(1, 1)]}
    lines = []
    for name in (u"MN1", u"MIN", u"MN2", u"ROT", u"HOLD"):
        lines.append(u'  <nodeselection name="{0}" direct="true">'.format(name))
        lines += [u'    <node nid="{0}" />'.format(n) for n in members[name]]
        lines.append(u'  </nodeselection>')
    for name in (u"BE", u"PF"):
        lines.append(u'  <faceselection name="{0}">'.format(name))
        lines += [u'    <face eid="{0}" faceid="{1}" />'.format(e, f) for e, f in members[name]]
        lines.append(u'  </faceselection>')

    def moment(name, unit, x, y, z):
        return [u'  <moment selection="{0}">'.format(name),
                u'    <x>{0} {1}</x>'.format(x, unit), u'    <y>{0} {1}</y>'.format(y, unit),
                u'    <z>{0} {1}</z>'.format(z, unit), u'  </moment>']
    lines += moment(u"MN1", u"kN.m", 0, 0, 0.002)
    lines += moment(u"MIN", u"N.m", 3, 0, 0)
    lines += moment(u"MN2", u"N.m", 0, 0, 7)
    lines += moment(u"BE", u"N.mm", 0, 500, 0)
    lines += moment(u"PF", u"N.m", 0, 0, 4)
    for name, value in ((u"ROT", u"0.01 rad"), (u"HOLD", u"0 rad")):
        lines += [u'  <noderotation selection="{0}">'.format(name),
                  u'    <value>{0}</value>'.format(value), u'    <x>0</x>', u'    <y>0</y>',
                  u'    <z>1</z>', u'  </noderotation>']
    expected = {tip: (0.0, 0.0, 2.0), mid: (3.0, 0.0, 0.0), beam_end: (0.0, 0.5, 0.0),
                turned: (0.0, 0.0, 1.0)}
    return lines, members, expected


def write_shell_liml(path, loads=False):
    """A plate of 3 x 1 quad4 with a Plate material t = 5 mm and a line2 rib of
    a RectBar on its edge: only to read back through Mecway's API (not
    solved). loads: the moment loads of shell_loads."""
    m, component = plate(beam_along=True)
    lines = [u'<?xml version="1.0" encoding="utf-8"?>', u'<liml version="34">',
             u'  <analysis type="S30" />']
    for nid in sorted(m.xyz):
        x, y, z = m.xyz[nid]
        lines.append(u'  <node nid="{0}" x="{1}" y="{2}" z="{3}" />'.format(
            nid, _num(x), _num(y), _num(z)))
    for name, material in ((u"Plate", u"Plate5"), (u"Rib", u"Rect")):
        lines.append(u'  <elset name="{0}" material="{1}" colorrgb="00C800">'.format(
            name, material))
        for eid in sorted(m.elements):
            if component[eid] == name:
                shape, nodes = m.elements[eid]
                lines.append(u'    <elem eid="{0}" shape="{1}" nodes="{2}" />'.format(
                    eid, shape, u" ".join(str(n) for n in nodes)))
        lines.append(u'  </elset>')
    lines += [SHELL_MATERIAL, BEAM_MATERIAL]
    if loads:
        lines += shell_loads(m)[0]
    lines.append(u'</liml>')
    with io.open(path, "w", encoding="utf-8", newline=u"\n") as f:
        f.write(u"\n".join(lines))
    return m, component
