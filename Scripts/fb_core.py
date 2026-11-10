# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_core.py
# Responsibility: what a cut through a model is, and everything computed from
# a list of forces per cut node. Knows neither Mecway nor Code-Aster; the
# interfaces are in docs/design/contract.md.
#   plan_cuts()         cut nodes, cut entities (solid faces, shell edges, beam
#                       ends) and groups of a selection, with the warnings
#   section_geometry()  area, centroid, normal, axes, outline; strips of
#                       shells and points of beams
#   shell_edge()        an edge of a shell with its directions n, t, w
#   assign_nodes()      nodes of a result per group, strict
#   link_nodes()        nodes of a result to Mecway's node numbers and groups
#   positions()         the shape to sum on: x, or x + u where the selected
#                       elements computed with large displacements
#   mixed_shape()       True if the nodes of a cut do not agree on that shape
#   resultant(), shift(), to_axes()  the statics
#   table_text()        text for the clipboard and CSV
#
# A refusal is an exception: Refused, with .code and .detail. A cut with a
# remark goes on, with a code in "warnings".
#
# Lengths in metres, forces in N, moments in N.m. Element node order and face
# numbers are those of the .liml.
#
# Compatible with IronPython 2.7.9 (Mecway) and CPython 3 (tests). Pure
# Python: no numpy.

import math

# The version of MecwayFreebody, the one place for it (CHANGELOG.md); the
# panel shows it in its header and in the copied table.
VERSION = "V2026.1"

try:
    _INTEGERS = (int, long)
except NameError:                       # Python 3
    _INTEGERS = (int,)

# ---- what the shapes look like -----------------------------------------------
# Faces as corner indices, outward normal; face i has faceid i + 1.
_HEX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7))
_WEDGE_FACES = ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5))
_TET_FACES = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2))
_PYR_FACES = ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 3, 2, 1))
# Midside nodes in the order of the node list, as corner pairs.
_HEX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7),
              (4, 5), (5, 6), (6, 7), (7, 4))
_WEDGE_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 4), (2, 5), (3, 4), (4, 5),
                (5, 3))
_TET_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
_PYR_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4))
_FAMILIES = {
    "hex8": (_HEX_FACES, _HEX_EDGES, 8, False),
    "hex20": (_HEX_FACES, _HEX_EDGES, 8, True),
    "wedge6": (_WEDGE_FACES, _WEDGE_EDGES, 6, False),
    "wedge15": (_WEDGE_FACES, _WEDGE_EDGES, 6, True),
    "tet4": (_TET_FACES, _TET_EDGES, 4, False),
    "tet10": (_TET_FACES, _TET_EDGES, 4, True),
    "pyr5": (_PYR_FACES, _PYR_EDGES, 5, False),
    "pyr13": (_PYR_FACES, _PYR_EDGES, 5, True),
}
SOLID_SHAPES = tuple(sorted(_FAMILIES))
SHELL_BEAM_SHAPES = ("line2", "line3", "tri3", "tri6", "quad4", "quad8")
# Shells in the node order of the .liml: positions of the corners in the node
# list, and of the midside node of edge k (corner k to corner k + 1), which
# has faceid k + 1. quad8 and tri6 alternate corner and midside.
_SHELLS = {
    "tri3": ((0, 1, 2), None),
    "tri6": ((0, 2, 4), (1, 3, 5)),
    "quad4": ((0, 1, 2, 3), None),
    "quad8": ((0, 2, 4, 6), (1, 3, 5, 7)),
}
# Lines: positions of node 1, node 2 and the midside node.
_LINES = {"line2": (0, 1, None), "line3": (0, 2, 1)}
SHELL_SHAPES = tuple(sorted(_SHELLS))
LINE_SHAPES = tuple(sorted(_LINES))
# Natural coordinates of the corners of a shell, and the order of the node
# list that the shape functions below expect (corners, then midsides).
_SHELL_NATURAL = {3: ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
                  4: ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))}
_SHELL_SF_ORDER = {"tri3": (0, 1, 2), "tri6": (0, 2, 4, 1, 3, 5),
                   "quad4": (0, 1, 2, 3), "quad8": (0, 2, 4, 6, 1, 3, 5, 7)}
# Models of Code-Aster that carry only an axial force
TRUSS_MODELS = ("BARRE", "CABLE")


def element_kind(shape):
    """"solid", "shell", "beam" (any line element) or None."""
    if shape in _FAMILIES:
        return "solid"
    if shape in _SHELLS:
        return "shell"
    if shape in _LINES:
        return "beam"
    return None

# Global axes: what a non-planar cut gets.
GLOBAL_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

# A cut is planar if the area vector is this close to the area ...
_PLANAR_ANGLE = 1e-8
# ... and the rms distance to the plane this small, relative to sqrt(area).
_PLANAR_DIST = 1e-6
# Below this area vector, relative to the area, a cut has no normal.
_NO_NORMAL = 1e-9
# Two principal values this close (relative) count as equal: a circle or a
# square. The axes then follow the global axes, not rounding noise.
_ROUND_SECTION = 1e-9
# A component this much below the largest one does not decide the sign.
_SIGN_TIE = 1e-9
# Coordinates of Mecway and Code-Aster are the same node within this [m].
_SAME_POINT = 1e-8
# A curved edge in the outline: points per edge, and when an edge is curved.
_OUTLINE_STEPS = 4
_CURVED = 1e-6
# Shells lie in one plane if every node is this close to it, relative to the
# extent of those shells; strips and their directions likewise.
_COPLANAR = 1e-6
# Two unit vectors with a dot product this close to 1 are one direction.
_PARALLEL = 1e-9


class Refused(Exception):
    """A clear refusal instead of a wrong number. code: a short word."""

    def __init__(self, code, detail=""):
        Exception.__init__(self, "{0}: {1}".format(code, detail))
        self.code = code
        self.detail = detail


# ---- element tables --------------------------------------------------------------
def _build_local():
    """{shape: [local node indices of each face, corners then midsides]} and
    {shape: [(corner a, corner b, local midside or None) of each edge]}."""
    faces = {}
    edges = {}
    for shape, (corner_faces, pairs, ncorner, quadratic) in _FAMILIES.items():
        mid = {}
        if quadratic:
            for i, (a, b) in enumerate(pairs):
                mid[(a, b)] = mid[(b, a)] = ncorner + i
        out = []
        for corners in corner_faces:
            n = len(corners)
            local = list(corners)
            if quadratic:
                local += [mid[(corners[i], corners[(i + 1) % n])]
                          for i in range(n)]
            out.append(tuple(local))
        faces[shape] = out
        edges[shape] = [(a, b, mid.get((a, b))) for a, b in pairs]
    return faces, edges


_FACE_LOCAL, _EDGE_LOCAL = _build_local()


def face_local_nodes(shape, faceid):
    """Local node indices of a face of a solid: corners, then midsides."""
    return _FACE_LOCAL[shape][faceid - 1]


def _sf_quad4(r, s):
    return ([(1 - r) * (1 - s) / 4, (1 + r) * (1 - s) / 4,
             (1 + r) * (1 + s) / 4, (1 - r) * (1 + s) / 4],
            [-(1 - s) / 4, (1 - s) / 4, (1 + s) / 4, -(1 + s) / 4],
            [-(1 - r) / 4, -(1 + r) / 4, (1 + r) / 4, (1 - r) / 4])


def _sf_quad8(r, s):
    n = []
    dr = []
    ds = []
    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        n.append((1 + a * r) * (1 + b * s) * (a * r + b * s - 1) / 4)
        dr.append(a * (1 + b * s) * (2 * a * r + b * s) / 4)
        ds.append(b * (1 + a * r) * (a * r + 2 * b * s) / 4)
    for a, b in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        if a == 0:
            n.append((1 - r * r) * (1 + b * s) / 2)
            dr.append(-r * (1 + b * s))
            ds.append(b * (1 - r * r) / 2)
        else:
            n.append((1 + a * r) * (1 - s * s) / 2)
            dr.append(a * (1 - s * s) / 2)
            ds.append(-s * (1 + a * r))
    return n, dr, ds


def _sf_tri3(r, s):
    return [1 - r - s, r, s], [-1.0, 1.0, 0.0], [-1.0, 0.0, 1.0]


def _sf_tri6(r, s):
    l0 = 1 - r - s
    return ([l0 * (2 * l0 - 1), r * (2 * r - 1), s * (2 * s - 1),
             4 * l0 * r, 4 * r * s, 4 * s * l0],
            [1 - 4 * l0, 4 * r - 1, 0.0, 4 * (l0 - r), 4 * s, -4 * s],
            [1 - 4 * l0, 0.0, 4 * s - 1, -4 * r, 4 * r, 4 * (l0 - s)])


_G3 = ((-0.7745966692414834, 5.0 / 9), (0.0, 8.0 / 9),
       (0.7745966692414834, 5.0 / 9))
_G4 = ((-0.8611363115940526, 0.34785484513745385),
       (-0.3399810435848563, 0.6521451548625461),
       (0.3399810435848563, 0.6521451548625461),
       (0.8611363115940526, 0.34785484513745385))


def _rule(sf, points):
    """Quadrature table of a face: [(N, dN/dr, dN/ds, weight)]."""
    out = []
    for r, s, w in points:
        n, dr, ds = sf(r, s)
        out.append((n, dr, ds, w))
    return out


def _rule_collapsed():
    """Triangle: Gauss rule on the square, collapsed. Exact to degree 6."""
    points = []
    for a, wa in _G4:
        for b, wb in _G4:
            u = (a + 1) / 2
            v = (b + 1) / 2
            points.append((u, v * (1 - u), wa * wb / 4 * (1 - u)))
    return points


# Exact for x x' det(J) on a flat face, with curved edges too: on a quad8 that
# polynomial has degree 7 per direction.
_FACE_RULES = {
    4: _rule(_sf_quad4, [(a, b, wa * wb) for a, wa in _G3 for b, wb in _G3]),
    8: _rule(_sf_quad8, [(a, b, wa * wb) for a, wa in _G4 for b, wb in _G4]),
    3: _rule(_sf_tri3, [(1.0 / 6, 1.0 / 6, 1.0 / 6), (2.0 / 3, 1.0 / 6, 1.0 / 6),
                        (1.0 / 6, 2.0 / 3, 1.0 / 6)]),
    6: _rule(_sf_tri6, _rule_collapsed()),
}


# ---- vectors --------------------------------------------------------------------
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    size = math.sqrt(_dot(a, a))
    return (a[0] / size, a[1] / size, a[2] / size)


# ---- plan --------------------------------------------------------------------------
class _Union(object):
    """Union-find on node numbers."""

    def __init__(self, items):
        self.up = dict((i, i) for i in items)

    def find(self, a):
        up = self.up
        root = a
        while up[root] != root:
            root = up[root]
        while up[a] != root:
            up[a], a = root, up[a]
        return root

    def join(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            # The smallest number stays root: the outcome does not depend on
            # the order of the elements.
            if ra < rb:
                self.up[rb] = ra
            else:
                self.up[ra] = rb


def _check_selection(elements, chosen):
    if not chosen:
        raise Refused("empty", "no elements selected")
    unknown = sorted(e for e in chosen if e not in elements)
    if unknown:
        raise Refused("unknown_element", str(unknown[:10]))
    bad = sorted(e for e in chosen if element_kind(elements[e][0]) is None)
    if bad:
        shapes = sorted(set(elements[e][0] for e in bad))
        raise Refused("shape", "{0} elements of shape {1}".format(
            len(bad), ", ".join(shapes)))


def _near_cut(elements, eids, cut):
    """The elements of eids with a cut node."""
    return [e for e in eids if not cut.isdisjoint(elements[e][1])]


def _edges_of(shape, nids):
    """[(corner, corner, midside or None)] of an element: the edges of a
    solid, the edges of a shell, the line of a beam."""
    if shape in _FAMILIES:
        return [(nids[a], nids[b], nids[m] if m is not None else None)
                for a, b, m in _EDGE_LOCAL[shape]]
    if shape in _SHELLS:
        corners, mids = _SHELLS[shape]
        n = len(corners)
        return [(nids[corners[k]], nids[corners[(k + 1) % n]],
                 nids[mids[k]] if mids else None) for k in range(n)]
    if shape in _LINES:
        a, b, m = _LINES[shape]
        return [(nids[a], nids[b], nids[m] if m is not None else None)]
    return []


def _corners(shape, nids):
    """Corner nodes of a shell or the end nodes of a line."""
    if shape in _SHELLS:
        return [nids[k] for k in _SHELLS[shape][0]]
    a, b, m = _LINES[shape]
    return [nids[a], nids[b]]


def _key(a, b):
    return (a, b) if a < b else (b, a)


def _plane_fit(points):
    """(normal, centre, extent) of a point set: the normal from Newell's sum
    of the polygon in its given order, extent the diagonal of the box."""
    nx = ny = nz = 0.0
    count = len(points)
    for i in range(count):
        p = points[i]
        q = points[(i + 1) % count]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    centre = tuple(sum(p[k] for p in points) / float(count) for k in range(3))
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    extent = math.sqrt(sum((high[k] - low[k]) ** 2 for k in range(3)))
    size = math.sqrt(nx * nx + ny * ny + nz * nz)
    normal = (nx / size, ny / size, nz / size) if size > 0 else None
    return normal, centre, extent


def _coplanar(mesh, shells):
    """True if all nodes of these shells lie in one plane: the plane of the
    first shell, its mean normal, within _COPLANAR of the extent of all."""
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    first = shells[0]
    shape, nids = elements[first]
    normal, centre, _ = _plane_fit([nodes[n] for n in _corners(shape, nids)])
    if normal is None:
        return False
    every = set()
    for e in shells:
        every.update(elements[e][1])
    points = [nodes[n] for n in every]
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    extent = math.sqrt(sum((high[k] - low[k]) ** 2 for k in range(3)))
    limit = _COPLANAR * extent
    for p in points:
        d = ((p[0] - centre[0]) * normal[0] + (p[1] - centre[1]) * normal[1] +
             (p[2] - centre[2]) * normal[2])
        if abs(d) > limit:
            return False
    return True


def _normal_moment(mesh, shells):
    """True if a nodal moment on a shell node has a part about the normal of
    a shell there (measured: an in-plane moment is clean, 3e-11; one about
    the normal 2.7e-2). mesh["moments"] {nid: (mx, my, mz)} is judged by
    direction; mesh["moment_nodes"] [nid] without one counts as such."""
    elements = mesh["elements"]
    nodes = mesh["nodes"]
    vectors = mesh.get("moments") or {}
    bare = set(mesh.get("moment_nodes") or ()) - set(vectors)
    if not vectors and not bare:
        return False
    for e in shells:
        shape, nids = elements[e]
        if not bare.isdisjoint(nids):
            return True
        hit = [n for n in nids if n in vectors]
        if not hit:
            continue
        normal = _plane_fit([nodes[n] for n in _corners(shape, nids)])[0]
        for n in hit:
            m = vectors[n]
            size = math.sqrt(_dot(m, m))
            if size > 0 and (normal is None or abs(_dot(m, normal)) > _COPLANAR * size):
                return True
    return False


def _drilling(mesh, inside, near_out):
    """Criteria of the drilling warning (contract, Phase 4): the fictitious
    drilling stiffness of shells takes moment the cut nodes do not see. It
    acts as a spring to the ground on every shell node, so a fold or a moment
    about the normal anywhere on the load path spoils a cut: measured with
    the fold and with the moment beyond the cut (test_aster_shells_e2e,
    3.6e-5 and 2.7e-2). Those two look at every shell of the model; other
    elements and couplings at the shells in or around the selection."""
    elements = mesh["elements"]
    every = [e for e in sorted(elements) if elements[e][0] in _SHELLS]
    if not every:
        return []
    sel_shells = [e for e in inside if elements[e][0] in _SHELLS]
    around = [e for e in near_out if elements[e][0] in _SHELLS]
    shell_nodes = set()
    for e in sel_shells + around:
        shell_nodes.update(elements[e][1])
    out = []
    if not _coplanar(mesh, every):
        out.append("not_coplanar")
    if _normal_moment(mesh, every):
        out.append("nodal_moment")
    for e, (shape, nids) in elements.items():
        if shape not in _SHELLS and not shell_nodes.isdisjoint(nids):
            out.append("other_element")
            break
    coupled = set(mesh.get("coupled_nodes") or ())
    if not coupled.isdisjoint(shell_nodes):
        out.append("coupling")
    return out


def plan_cuts(mesh, selected_eids):
    """
    What the rest of the model holds on to. See the contract. Refused for an
    empty selection, unknown elements or shapes that are no solid, shell or
    line. Entities per kind: solid faces with a solid neighbour outside,
    shell edges with a shell neighbour outside, beam end nodes that an
    element outside shares. Optional keys of mesh for the drilling warning:
    "moment_nodes" (nodes with a nodal moment) and "coupled_nodes".
    """
    elements = mesh["elements"]
    chosen = set(selected_eids)
    _check_selection(elements, chosen)
    inside = sorted(chosen)
    outside = sorted(e for e in elements if e not in chosen)

    in_nodes = set()
    for e in inside:
        in_nodes.update(elements[e][1])
    out_nodes = set()
    for e in outside:
        out_nodes.update(elements[e][1])
    cut = in_nodes & out_nodes
    warnings = []
    if not cut:
        warnings.append("no_cut")
        return {"inside": inside, "outside": outside, "cut_nodes": [],
                "groups": [], "warnings": warnings, "drilling": []}

    near_in = _near_cut(elements, inside, cut)
    near_out = _near_cut(elements, outside, cut)

    # The outside: solid faces, shell edges and all edges with every corner a
    # cut node, the kinds that touch each cut node, and skin shells on them
    out_faces = set()
    out_face_sets = {}              # cut node: [corner sets of outside solid faces]
    out_shell_edges = set()
    out_edges = set()
    out_kinds = {}
    out_shells = []
    for e in near_out:
        shape, nids = elements[e]
        kind = element_kind(shape)
        for n in nids:
            if n in cut:
                out_kinds.setdefault(n, set()).add(kind)
        if shape in _FAMILIES:
            for face in _FAMILIES[shape][0]:
                key = [nids[i] for i in face]
                corners = frozenset(key)
                for n in key:
                    if n in cut:
                        out_face_sets.setdefault(n, []).append(corners)
                if cut.issuperset(key):
                    key.sort()
                    out_faces.add(tuple(key))
        for a, b, m in _edges_of(shape, nids):
            if a in cut and b in cut:
                out_edges.add(_key(a, b))
                if kind == "shell":
                    out_shell_edges.add(_key(a, b))
        if kind == "shell":
            corners = _corners(shape, nids)
            if cut.issuperset(corners):
                out_shells.append(frozenset(corners))

    def on_one_face(corners, face_sets):
        """True if all corners lie on one face of face_sets (by node)."""
        for face in face_sets.get(corners[0], ()):
            if face.issuperset(corners):
                return True
        return False

    union = _Union(cut)
    entities = []
    faces = []
    on_entity = set()
    in_kinds = {}
    unshared = False
    skin = False
    in_face_sets = {}               # cut node: corner sets of selected solid faces
    for e in near_in:
        shape, nids = elements[e]
        kind = element_kind(shape)
        for n in nids:
            if n in cut:
                in_kinds.setdefault(n, set()).add(kind)
        if kind == "solid":
            for i, face in enumerate(_FAMILIES[shape][0]):
                key = [nids[k] for k in face]
                corners = frozenset(key)
                for n in key:
                    if n in cut:
                        in_face_sets.setdefault(n, []).append(corners)
                if not cut.issuperset(key):
                    continue
                key.sort()
                if tuple(key) not in out_faces:
                    continue
                faces.append((e, i + 1))
                entities.append(("face", e, i + 1))
                local = [nids[k] for k in _FACE_LOCAL[shape][i]]
                first = local[0]
                for n in local:
                    if n in cut:
                        union.join(first, n)
                        on_entity.add(n)
                    else:
                        unshared = True
        elif kind == "shell":
            corners = _corners(shape, nids)
            if cut.issuperset(corners) and on_one_face(corners, out_face_sets):
                # glued to a face of the rest: its edges with a shell
                # neighbour still cut, the rest is a node contact
                skin = True
            for k, (a, b, m) in enumerate(_edges_of(shape, nids)):
                if a not in cut or b not in cut or _key(a, b) not in out_shell_edges:
                    continue
                entities.append(("edge", e, k + 1))
                for n in (a, b, m):
                    if n is None:
                        continue
                    if n in cut:
                        union.join(a, n)
                        on_entity.add(n)
                    else:
                        unshared = True
        else:
            for n in _corners(shape, nids):
                if n in cut:
                    entities.append(("end", e, n))
                    on_entity.add(n)
    # An outside shell lying on a selected solid face: a boundary as well
    for corners in out_shells:
        if on_one_face(sorted(corners), in_face_sets):
            skin = True
    if unshared:
        warnings.append("midside_not_shared")
    if skin:
        warnings.append("skin_shell")

    # Edges, after all entities: a contact along an edge has no entity, and a
    # run may add a midside node on an edge that both sides have, so both ends
    # are one group. Two cuts with entities that only an edge joins are one
    # group for that reason too, but that needs saying: it is the sum of both.
    with_entities = set(union.find(n) for n in on_entity)
    merged = [False]

    def join_edge(a, b):
        ra = union.find(a)
        rb = union.find(b)
        if ra == rb:
            return
        if ra in with_entities and rb in with_entities:
            merged[0] = True
        union.join(a, b)
        if ra in with_entities or rb in with_entities:
            with_entities.add(union.find(a))

    for e in near_in:
        shape, nids = elements[e]
        for a, b, mid in _edges_of(shape, nids):
            if a in cut and b in cut and _key(a, b) in out_edges:
                join_edge(a, b)
            if mid in cut:
                if a in cut:
                    join_edge(a, mid)
                if b in cut:
                    join_edge(b, mid)
    if merged[0]:
        warnings.append("edge_merge")

    loose = [n for n in sorted(cut) if n not in on_entity]
    if loose:
        lines_or_shells = False
        for n in loose:
            kinds = in_kinds.get(n, set()) | out_kinds.get(n, set())
            if kinds - set(["solid"]):
                lines_or_shells = True
                break
        warnings.append("node_contact" if lines_or_shells else "edge_contact")

    by_root = {}
    for n in sorted(cut):
        by_root.setdefault(union.find(n), []).append(n)
    entity_root = {}
    for item in sorted(entities):
        kind, e, ref = item
        shape, nids = elements[e]
        if kind == "face":
            node = nids[_FACE_LOCAL[shape][ref - 1][0]]
        elif kind == "edge":
            node = _edges_of(shape, nids)[ref - 1][0]
        else:
            node = ref
        entity_root.setdefault(union.find(node), []).append(item)
    groups = []
    mixed = False
    along = False
    names = {"face": "solid", "edge": "shell", "end": "beam"}
    for i, root in enumerate(sorted(by_root, key=lambda r: by_root[r][0])):
        items = entity_root.get(root, [])
        kinds = set(names[item[0]] for item in items)
        if not kinds:
            for n in by_root[root]:
                kinds.update(in_kinds.get(n, ()))
        if len(kinds) > 1:
            kind = "mixed"
            if len(set(names[item[0]] for item in items)) > 1:
                mixed = True
        else:
            kind = kinds.pop() if kinds else "solid"
        ends = {}
        for item in items:
            if item[0] == "end":
                ends[item[1]] = ends.get(item[1], 0) + 1
        if any(count > 1 for count in ends.values()):
            along = True
        groups.append({"id": i + 1, "nodes": by_root[root], "entities": items,
                       "faces": [(e, f) for kind_, e, f in items if kind_ == "face"],
                       "kind": kind})
    if along:
        warnings.append("beam_along_cut")
    if mixed:
        warnings.append("mixed_cut")
    drilling = _drilling(mesh, inside, near_out)
    if drilling:
        warnings.append("drilling")
    return {"inside": inside, "outside": outside, "cut_nodes": sorted(cut),
            "groups": groups, "warnings": warnings, "drilling": drilling}


# ---- geometry ----------------------------------------------------------------------
def _entities(group):
    """The entities of a group; a group of phase 3 has faces only."""
    found = group.get("entities")
    if found is None:
        found = [("face", e, f) for e, f in group.get("faces", ())]
    return found


def _weights(group, props):
    """{eid: weight, mean 1} of the entities, or {} for a plain sum, with the
    warning when props are incomplete."""
    if not props:
        return {}, []
    values = {}
    for kind, e, ref in _entities(group):
        value = props.get(e, {}).get("E")
        if value is None or value <= 0:
            return {}, ["E_missing"]
        values[e] = float(value)
    if not values:
        return {}, []
    mean = sum(values.values()) / len(values)
    return dict((e, v / mean) for e, v in values.items()), []


def _integrate(mesh, group, weights):
    """Area integrals over the faces of a group, in global coordinates. Each
    face turned outward from its element, also an element inside out."""
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    area = area_w = 0.0
    sx = sy = sz = 0.0
    sxx = syy = szz = sxy = syz = szx = 0.0
    vx = vy = vz = 0.0
    flipped = set()
    for e, faceid in group["faces"]:
        shape, nids = elements[e]
        local = _FACE_LOCAL[shape][faceid - 1]
        pts = [nodes[nids[k]] for k in local]
        w_e = weights.get(e, 1.0) if weights else 1.0
        rule = _FACE_RULES[len(local)]
        n_pts = range(len(local))
        # area vector of this face and the moments before the sign is known
        ax = ay = az = 0.0
        for sf, dr, ds, w in rule:
            x = y = z = t1x = t1y = t1z = t2x = t2y = t2z = 0.0
            for i in n_pts:
                p = pts[i]
                px = p[0]
                py = p[1]
                pz = p[2]
                c = sf[i]
                x += c * px
                y += c * py
                z += c * pz
                c = dr[i]
                t1x += c * px
                t1y += c * py
                t1z += c * pz
                c = ds[i]
                t2x += c * px
                t2y += c * py
                t2z += c * pz
            nx = t1y * t2z - t1z * t2y
            ny = t1z * t2x - t1x * t2z
            nz = t1x * t2y - t1y * t2x
            da = math.sqrt(nx * nx + ny * ny + nz * nz) * w
            ax += nx * w
            ay += ny * w
            az += nz * w
            area += da
            da *= w_e
            area_w += da
            sx += da * x
            sy += da * y
            sz += da * z
            sxx += da * x * x
            syy += da * y * y
            szz += da * z * z
            sxy += da * x * y
            syz += da * y * z
            szx += da * z * x
        # Outward: away from the middle of the element
        ncorner = _FAMILIES[shape][2]
        mx = my = mz = 0.0
        for k in range(ncorner):
            p = nodes[nids[k]]
            mx += p[0]
            my += p[1]
            mz += p[2]
        nface = len(_FAMILIES[shape][0][faceid - 1])
        fx = fy = fz = 0.0
        for k in local[:nface]:
            p = nodes[nids[k]]
            fx += p[0]
            fy += p[1]
            fz += p[2]
        d = ((fx / nface - mx / ncorner) * ax +
             (fy / nface - my / ncorner) * ay +
             (fz / nface - mz / ncorner) * az)
        if d < 0:
            flipped.add((e, faceid))
            ax = -ax
            ay = -ay
            az = -az
        vx += ax
        vy += ay
        vz += az
    return {"area": area, "area_w": area_w, "first": (sx, sy, sz),
            "second": (sxx, syy, szz, sxy, syz, szx), "vector": (vx, vy, vz),
            "flipped": flipped}


def _central(values, centroid):
    """Second moments about the centroid, as a function of a direction pair."""
    sxx, syy, szz, sxy, syz, szx = values["second"]
    a = values["area_w"]
    cx, cy, cz = centroid
    xx = sxx - a * cx * cx
    yy = syy - a * cy * cy
    zz = szz - a * cz * cz
    xy = sxy - a * cx * cy
    yz = syz - a * cy * cz
    zx = szx - a * cz * cx

    def moment(u, v):
        return (u[0] * (xx * v[0] + xy * v[1] + zx * v[2]) +
                u[1] * (xy * v[0] + yy * v[1] + yz * v[2]) +
                u[2] * (zx * v[0] + yz * v[1] + zz * v[2]))
    return moment


def _sign_fixed(a):
    """Direction with its largest component positive: no flips between runs.
    With a tie the first of the tied components decides."""
    top = max(abs(c) for c in a)
    for c in a:
        if abs(c) >= top * (1 - _SIGN_TIE):
            return a if c > 0 else (-a[0], -a[1], -a[2])
    return a


def _in_plane(normal):
    """Unit vector in the plane: the global axis furthest from the normal,
    projected on the plane."""
    sizes = [abs(c) for c in normal]
    low = min(sizes)
    i = 0
    while sizes[i] > low * (1 + _SIGN_TIE) + 1e-300:
        i += 1
    axis = [0.0, 0.0, 0.0]
    axis[i] = 1.0
    d = _dot(axis, normal)
    return _unit((axis[0] - d * normal[0], axis[1] - d * normal[1],
                  axis[2] - d * normal[2]))


def _principal(normal, moment):
    """(a, b, Ia, Ib): right handed with the normal; a is the axis with the
    larger second moment, so a section stands the same way on every cut."""
    e1 = _in_plane(normal)
    e2 = _cross(normal, e1)
    i11 = moment(e1, e1)
    i22 = moment(e2, e2)
    i12 = moment(e1, e2)
    spread = 0.5 * (i11 - i22)
    radius = math.sqrt(spread * spread + i12 * i12)
    middle = 0.5 * (i11 + i22)
    if radius <= _ROUND_SECTION * abs(middle):
        a = _sign_fixed(e1)
    else:
        # the direction of the largest spread is b
        t = 0.5 * math.atan2(i12, spread)
        c = math.cos(t)
        s = math.sin(t)
        b = (c * e1[0] + s * e2[0], c * e1[1] + s * e2[1], c * e1[2] + s * e2[2])
        a = _sign_fixed(_cross(b, normal))
    b = _cross(normal, a)
    return a, b, moment(b, b), moment(a, a)


def _edge_points(nodes, nids, local, i, turned=False):
    """Points of edge i of a face, from its corner up to the next corner (not
    included), or the other way if turned. A curved edge gets _OUTLINE_STEPS
    pieces."""
    nface = len(local) // 2 if len(local) in (6, 8) else len(local)
    p0 = nodes[nids[local[i]]]
    p1 = nodes[nids[local[(i + 1) % nface]]]
    if turned:
        p0, p1 = p1, p0
    if len(local) == nface:
        return [p0]
    pm = nodes[nids[local[nface + i]]]
    d = [pm[k] - (p0[k] + p1[k]) / 2 for k in range(3)]
    size = sum((p1[k] - p0[k]) ** 2 for k in range(3))
    if _dot(d, d) <= size * _CURVED * _CURVED:
        return [p0]
    out = []
    for step in range(_OUTLINE_STEPS):
        t = float(step) / _OUTLINE_STEPS
        n0 = (1 - t) * (1 - 2 * t)
        n1 = t * (2 * t - 1)
        nm = 4 * t * (1 - t)
        out.append(tuple(n0 * p0[k] + n1 * p1[k] + nm * pm[k] for k in range(3)))
    return out


def _outline(mesh, group, centroid, axes, flipped):
    """Closed loops of the free edges of the faces, in (a, b) about the
    centroid. Holes are loops of their own. flipped: faces of elements inside
    out, whose edges run the other way, as in _integrate."""
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    edges = {}
    for e, faceid in group["faces"]:
        shape, nids = elements[e]
        local = _FACE_LOCAL[shape][faceid - 1]
        nface = len(_FAMILIES[shape][0][faceid - 1])
        for i in range(nface):
            n0 = nids[local[i]]
            n1 = nids[local[(i + 1) % nface]]
            turned = (e, faceid) in flipped
            if turned:
                n0, n1 = n1, n0
            key = (n0, n1) if n0 < n1 else (n1, n0)
            if key in edges:
                edges[key] = None
            else:
                edges[key] = (n0, n1, nids, local, i, turned)
    starts = {}
    for key in sorted(edges):
        item = edges[key]
        if item is not None:
            starts.setdefault(item[0], []).append(item)
    _, a, b = axes
    loops = []
    for first in sorted(starts):
        while starts[first]:
            points = []
            node = first
            while starts.get(node):
                item = starts[node].pop()
                points += _edge_points(nodes, item[2], item[3], item[4], item[5])
                node = item[1]
                if node == first:
                    break
            loop = []
            for p in points:
                d = (p[0] - centroid[0], p[1] - centroid[1], p[2] - centroid[2])
                loop.append((_dot(d, a), _dot(d, b)))
            loops.append(loop)
    return loops


# Gauss-Legendre, 10 points on [-1, 1]: the length of a curved edge
_G10 = ((-0.9739065285171717, 0.0666713443086881), (-0.8650633666889845, 0.1494513491505806),
        (-0.6794095682990244, 0.2190863625159820), (-0.4333953941292472, 0.2692667193099963),
        (-0.1488743389816312, 0.2955242247147529), (0.1488743389816312, 0.2955242247147529),
        (0.4333953941292472, 0.2692667193099963), (0.6794095682990244, 0.2190863625159820),
        (0.8650633666889845, 0.1494513491505806), (0.9739065285171717, 0.0666713443086881))
_SHELL_SF = {3: _sf_tri3, 4: _sf_quad4, 6: _sf_tri6, 8: _sf_quad8}
# A curved edge in this many pieces of _G10: 1e-13 on the length of a parabola
# whose midside node stands half the chord off it
_CURVED_PIECES = 8


class _Sums(object):
    """Integrals of a section: plain area, weighted area, first and second
    moments, area vector. Faces, strips and beam points add to the same."""

    def __init__(self, faces):
        self.area = faces["area"]
        self.area_w = faces["area_w"]
        self.first = list(faces["first"])
        self.second = list(faces["second"])
        self.vector = list(faces["vector"])

    def add(self, x, da, da_w, direction):
        """A piece of area da (weighted da_w) at x, area vector along direction."""
        self.area += da
        self.area_w += da_w
        f = self.first
        f[0] += da_w * x[0]
        f[1] += da_w * x[1]
        f[2] += da_w * x[2]
        q = self.second
        q[0] += da_w * x[0] * x[0]
        q[1] += da_w * x[1] * x[1]
        q[2] += da_w * x[2] * x[2]
        q[3] += da_w * x[0] * x[1]
        q[4] += da_w * x[1] * x[2]
        q[5] += da_w * x[2] * x[0]
        v = self.vector
        v[0] += da * direction[0]
        v[1] += da * direction[1]
        v[2] += da * direction[2]

    def values(self):
        return {"area": self.area, "area_w": self.area_w, "first": tuple(self.first),
                "second": tuple(self.second), "vector": tuple(self.vector)}


def shell_edge(mesh, eid, faceid):
    """
    The edge faceid (1..4) of a shell: (p0, p1, pm or None, n, t, w). w is the
    shell normal from the node order (shape functions at the middle of the
    edge), n lies in the shell plane, perpendicular to the edge and out of the
    element, t = w x n. p0 and p1 are corner k and k + 1, pm the midside node.
    """
    nodes = mesh["nodes"]
    shape, nids = mesh["elements"][eid]
    corners, mids = _SHELLS[shape]
    count = len(corners)
    k = faceid - 1
    p0 = nodes[nids[corners[k]]]
    p1 = nodes[nids[corners[(k + 1) % count]]]
    pm = nodes[nids[mids[k]]] if mids else None
    pts = [nodes[nids[i]] for i in _SHELL_SF_ORDER[shape]]
    natural = _SHELL_NATURAL[count]
    r = (natural[k][0] + natural[(k + 1) % count][0]) / 2.0
    s = (natural[k][1] + natural[(k + 1) % count][1]) / 2.0
    centre = (0.0, 0.0) if count == 4 else (1.0 / 3, 1.0 / 3)
    n_, dr, ds = _SHELL_SF[len(pts)](r, s)
    t1 = [sum(dr[i] * pts[i][c] for i in range(len(pts))) for c in range(3)]
    t2 = [sum(ds[i] * pts[i][c] for i in range(len(pts))) for c in range(3)]
    w = _unit(_cross(t1, t2))
    inward = [t1[c] * (centre[0] - r) + t2[c] * (centre[1] - s) for c in range(3)]
    tangent = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    n = _unit(_cross(tangent, w))
    if _dot(n, inward) > 0:
        n = (-n[0], -n[1], -n[2])
    return p0, p1, pm, n, _cross(w, n), w


def _edge_at(p0, p1, pm, s):
    """Point and derivative of an edge at s in [-1, 1]."""
    if pm is None:
        x = [(1 - s) / 2 * p0[c] + (1 + s) / 2 * p1[c] for c in range(3)]
        d = [(p1[c] - p0[c]) / 2 for c in range(3)]
        return x, d
    a = s * (s - 1) / 2
    b = s * (s + 1) / 2
    m = 1 - s * s
    x = [a * p0[c] + b * p1[c] + m * pm[c] for c in range(3)]
    d = [(s - 0.5) * p0[c] + (s + 0.5) * p1[c] - 2 * s * pm[c] for c in range(3)]
    return x, d


def _strips(mesh, items, props, weights, sums):
    """Strips t x L of the shell edges, added to sums. (strips, missing t):
    without the thickness of every strip all count with t = 1."""
    out = []
    missing = False
    for kind, e, faceid in items:
        value = props.get(e, {}).get("thickness") if props else None
        if value is None or not value > 0:
            missing = True
    for kind, e, faceid in items:
        p = props.get(e, {}) if props else {}
        t = 1.0 if missing else float(p["thickness"])
        offset = float(p.get("offset") or 0.0)
        w_e = weights.get(e, 1.0) if weights else 1.0
        p0, p1, pm, n, tdir, w = shell_edge(mesh, e, faceid)
        shift = (offset * w[0], offset * w[1], offset * w[2])
        # |x'| of a curved edge is no polynomial: Gauss on pieces of it
        pieces = 1
        if pm is not None:
            bend = [pm[c] - (p0[c] + p1[c]) / 2 for c in range(3)]
            chord = sum((p1[c] - p0[c]) ** 2 for c in range(3))
            if _dot(bend, bend) > chord * _CURVED * _CURVED:
                pieces = _CURVED_PIECES
        length = 0.0
        for piece in range(pieces):
            low = -1.0 + 2.0 * piece / pieces
            half = 1.0 / pieces
            for u, g in _G10:
                s = low + half * (u + 1.0)
                x, d = _edge_at(p0, p1, pm, s)
                dl = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) * g * half
                length += dl
                x = (x[0] + shift[0], x[1] + shift[1], x[2] + shift[2])
                sums.add(x, t * dl, t * dl * w_e, n)
        moved = [tuple(q[c] + shift[c] for c in range(3)) for q in
                 ((p0, pm, p1) if pm is not None else (p0, p1))]
        out.append({"eid": e, "faceid": faceid, "a": moved[0], "b": moved[-1],
                    "points": moved, "t": None if missing else t, "w": w, "n": n,
                    "edge": tdir, "offset": offset, "length": length,
                    "large": bool(p.get("large"))})
    return out, missing


def _section_at(section, end):
    """The section values at node 1 or 2: a tapered section has "end2"."""
    if not section:
        return {}
    if end == 2 and section.get("end2"):
        merged = dict(section)
        merged.update(section["end2"])
        return merged
    return section


def _axes_ok(local):
    """Three rows of three finite numbers, or None."""
    try:
        rows = [tuple(float(c) for c in row) for row in local]
    except (TypeError, ValueError):
        return None
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        return None
    if any(c != c or c - c != 0 for row in rows for c in row):
        return None
    return rows


def _beams(mesh, items, props, weights, sums, warnings):
    """Beam points at the cut ends, added to sums. (beams, missing A):
    without the area of every beam all count with A = 1."""
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    out = []
    found = []
    missing = False
    for kind, e, nid in items:
        shape, nids = elements[e]
        a, b, m = _LINES[shape]
        end = 1 if nids[a] == nid else 2
        p = props.get(e, {}) if props else {}
        section = _section_at(p.get("section"), end)
        if section.get("A") is None or not section["A"] > 0:
            missing = True
        found.append((e, nid, shape, nids, a, b, m, end, p, section))
    for e, nid, shape, nids, a, b, m, end, p, section in found:
        model = p.get("model")
        truss = bool(p.get("truss")) or model in TRUSS_MODELS
        cells = p.get("beam_axes") or {}
        cell = "H" if end == 2 and cells.get("H") else "M"
        local = None if truss else _axes_ok(cells.get(cell))
        if not local:
            if not truss and "beam_axes_missing" not in warnings:
                warnings.append("beam_axes_missing")
            # x along the (half) element from node 1 towards node 2
            if m is None:
                q0, q1 = nodes[nids[a]], nodes[nids[b]]
            elif end == 1:
                q0, q1 = nodes[nids[a]], nodes[nids[m]]
            else:
                q0, q1 = nodes[nids[m]], nodes[nids[b]]
            x = _unit((q1[0] - q0[0], q1[1] - q0[1], q1[2] - q0[2]))
            y = _in_plane(x)
            local = (x, y, _cross(x, y))
        x, y, z = [tuple(float(c) for c in v) for v in local]
        if end == 1:
            axes = ((-x[0], -x[1], -x[2]), y, (-z[0], -z[1], -z[2]))
        else:
            axes = (x, y, z)
        area = 1.0 if missing else float(section["A"])
        w_e = weights.get(e, 1.0) if weights else 1.0
        sums.add(nodes[nid], area, area * w_e, axes[0])
        out.append({"node": nid, "eid": e, "end": end, "cell": cell,
                    "A": None if missing else area, "axes": axes, "model": model,
                    "truss": truss, "section": section, "large": bool(p.get("large"))})
    return out, missing


def _flat_strips(strips, extent):
    """True if the strips lie on one straight line in one plane: all n and w
    parallel, all points on that line."""
    n0 = strips[0]["n"]
    w0 = strips[0]["w"]
    for strip in strips:
        if (_dot(strip["n"], n0) < 1 - _PARALLEL or
                abs(_dot(strip["w"], w0)) < 1 - _PARALLEL):
            return False
    origin = strips[0]["a"]
    limit = _COPLANAR * extent
    for strip in strips:
        for p in strip["points"]:
            d = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
            if abs(_dot(d, n0)) > limit or abs(_dot(d, w0)) > limit:
                return False
    return True


def _strip_outline(strips, centroid, axes):
    """Each strip as a thin rectangle t x L in (a, b) about the centroid."""
    _, a, b = axes
    loops = []
    for strip in strips:
        half = (strip["t"] or 0.0) / 2
        w = strip["w"]
        pts = strip["points"]
        if len(pts) == 3:
            line = []
            for step in range(_OUTLINE_STEPS + 1):
                s = -1 + 2.0 * step / _OUTLINE_STEPS
                line.append(_edge_at(pts[0], pts[2], pts[1], s)[0])
        else:
            line = list(pts)
        side = [tuple(q[c] + half * w[c] for c in range(3)) for q in line]
        back = [tuple(q[c] - half * w[c] for c in range(3)) for q in reversed(line)]
        loop = []
        for p in side + back:
            d = (p[0] - centroid[0], p[1] - centroid[1], p[2] - centroid[2])
            loop.append((_dot(d, a), _dot(d, b)))
        loops.append(loop)
    return loops


def _extent(points):
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    return math.sqrt(sum((high[k] - low[k]) ** 2 for k in range(3)))


def section_geometry(mesh, group, props=None):
    """
    Area, centroid and axes of the entities of a group; see the contract.
    Faces are integrated with their shape functions, so curved edges count;
    strips (shell edges, t x L on the midline) along their quadratic edges,
    thin-walled; beams are points with their section area. Also: "inertia"
    (Ia, Ib) about the axes a and b, "strips", "beams", "only_n" and
    "warnings". props per element: "E", "thickness", "section", "model",
    "beam_axes", "offset", "large" (fb_aster.manifest_props gives those of
    the run). "area" is None when a thickness or a section is missing.
    "axes_kind": how the axes were chosen, "section" (principal axes),
    "strip" (n, t, w), "beam", "truss" or "global".
    """
    entities = _entities(group)
    face_items = [(e, f) for kind, e, f in entities if kind == "face"]
    edge_items = [item for item in entities if item[0] == "edge"]
    end_items = [item for item in entities if item[0] == "end"]
    weights, warnings = _weights(group, props)
    warnings = list(warnings)
    faces = _integrate(mesh, {"faces": face_items}, weights)
    sums = _Sums(faces)
    strips, no_t = _strips(mesh, edge_items, props, weights, sums)
    beams, no_a = _beams(mesh, end_items, props, weights, sums, warnings)
    if no_t:
        warnings.append("thickness_missing")
    if no_a:
        warnings.append("section_missing")
    values = sums.values()
    values["flipped"] = faces["flipped"]
    area = values["area"]
    only_n = bool(beams) and not face_items and not strips and all(
        q["truss"] for q in beams)
    if area <= 0:
        # Contact through an edge or a corner: nothing to integrate
        pts = [mesh["nodes"][n] for n in group["nodes"]]
        n = float(len(pts))
        middle = tuple(sum(p[k] for p in pts) / n for k in range(3))
        return {"area": 0.0, "centroid": middle, "planar": False,
                "normal": (0.0, 0.0, 0.0), "axes": GLOBAL_AXES, "outline": [],
                "inertia": (0.0, 0.0), "warnings": warnings, "strips": strips,
                "beams": beams, "only_n": False, "axes_kind": "global"}
    a_w = values["area_w"]
    sum1 = values["first"]
    centroid = (sum1[0] / a_w, sum1[1] / a_w, sum1[2] / a_w)
    moment = _central(values, centroid)
    vector = values["vector"]
    size = math.sqrt(_dot(vector, vector))
    if size > area * _NO_NORMAL:
        normal = (vector[0] / size, vector[1] / size, vector[2] / size)
    else:
        # Opposite faces cancel: N and V mean nothing on such a cut
        normal = (0.0, 0.0, 0.0)
        warnings.append("no_normal")
    kinds = len([1 for q in (face_items, strips, beams) if q])
    planar = False
    axes = None
    outline = []
    inertia = None
    kind_of_axes = "global"
    if any(q["large"] for q in strips + beams):
        warnings.append("large_axes")          # local axes turn with the run
    elif kinds > 1:
        pass                                   # mixed: global
    elif beams:
        if len(beams) == 1:
            axes = beams[0]["axes"]
            normal = axes[0]
            planar = True
            kind_of_axes = "truss" if beams[0]["truss"] else "beam"
            section = beams[0]["section"]
            inertia = (float(section.get("IY") or 0.0), float(section.get("IZ") or 0.0))
    elif strips:
        extent = _extent([p for strip in strips for p in strip["points"]])
        if len(strips) == 1 or _flat_strips(strips, extent):
            # w with a fixed sign, so the axes do not follow the node order
            # of the element that happens to be first; t = w x n
            first = strips[0]
            w = _sign_fixed(first["w"])
            axes = (first["n"], _cross(w, first["n"]), w)
            normal = first["n"]
            planar = True
            kind_of_axes = "strip"
        elif size >= area * (1 - _PLANAR_ANGLE):
            distance = math.sqrt(max(moment(normal, normal), 0.0) / a_w)
            if distance <= _PLANAR_DIST * extent:
                a, b, ia, ib = _principal(normal, moment)
                axes = (normal, a, b)
                inertia = (ia, ib)
                planar = True
                kind_of_axes = "section"
        if planar:
            outline = _strip_outline(strips, centroid, axes)
    elif size >= area * (1 - _PLANAR_ANGLE):
        distance = math.sqrt(max(moment(normal, normal), 0.0) / a_w)
        if distance <= _PLANAR_DIST * math.sqrt(area):
            a, b, ia, ib = _principal(normal, moment)
            axes = (normal, a, b)
            inertia = (ia, ib)
            planar = True
            kind_of_axes = "section"
            outline = _outline(mesh, {"faces": face_items}, centroid, axes,
                               values["flipped"])
    if axes is None:
        axes = GLOBAL_AXES
        planar = False
        kind_of_axes = "global"
        inertia = (moment(GLOBAL_AXES[2], GLOBAL_AXES[2]),
                   moment(GLOBAL_AXES[1], GLOBAL_AXES[1]))
    elif inertia is None:
        inertia = (moment(axes[2], axes[2]), moment(axes[1], axes[1]))
    return {"area": None if (no_t or no_a) else area, "centroid": centroid,
            "planar": planar, "normal": normal, "axes": axes, "outline": outline,
            "inertia": inertia, "warnings": warnings, "strips": strips,
            "beams": beams, "only_n": only_n, "axes_kind": kind_of_axes}


# ---- nodes of a result per group -----------------------------------------------------
class _Grid(object):
    """Nearest point in a set of points on surfaces: a uniform grid."""

    def __init__(self, items):
        """items: [((x, y, z), data)]."""
        low = [min(p[k] for p, _ in items) for k in range(3)]
        high = [max(p[k] for p, _ in items) for k in range(3)]
        extent = max(high[k] - low[k] for k in range(3))
        cells = max(int(math.sqrt(len(items))), 1)
        self.size = (extent / cells) if extent > 0 else 1.0
        self.low = low
        self.span = int(extent / self.size) + 2
        self.cells = {}
        for item in items:
            self.cells.setdefault(self._key(item[0]), []).append(item)

    def _key(self, p):
        s = self.size
        low = self.low
        return (int(math.floor((p[0] - low[0]) / s)),
                int(math.floor((p[1] - low[1]) / s)),
                int(math.floor((p[2] - low[2]) / s)))

    def nearest(self, p):
        """(distance squared, data) of the nearest point."""
        ci, cj, ck = self._key(p)
        best = None
        best_data = None
        cells = self.cells
        ring = 0
        # A point just outside the set can be further off than the set is wide
        while ring <= self.span + max(abs(ci), abs(cj), abs(ck)):
            if best is not None and ((ring - 1) * self.size) ** 2 > best:
                break
            for i in range(ci - ring, ci + ring + 1):
                on_i = abs(i - ci) == ring
                for j in range(cj - ring, cj + ring + 1):
                    if on_i or abs(j - cj) == ring:
                        ks = range(ck - ring, ck + ring + 1)
                    else:
                        ks = (ck - ring, ck + ring)
                    for k in ks:
                        for q, data in cells.get((i, j, k), ()):
                            d = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 +
                                 (q[2] - p[2]) ** 2)
                            if best is None or d < best:
                                best = d
                                best_data = data
            ring += 1
        return best, best_data


def _match(plan, mesh, result):
    """For each node of a result: (the same node as in Mecway, group id,
    nearest Mecway node)."""
    nodes = mesh["nodes"]
    items = []
    for group in plan["groups"]:
        for n in group["nodes"]:
            items.append((nodes[n], (group["id"], n)))
    grid = _Grid(items)
    tol = _SAME_POINT * _SAME_POINT
    out = []
    for record in result["nodes"]:
        distance, (group_id, nid) = grid.nearest(record["xyz"])
        out.append((distance <= tol, group_id, nid))
    return out


def link_nodes(plan, mesh, result):
    """
    Sets record["nid"] on the nodes of a result: the node number in Mecway, by
    position; None for a midside node the run added. Returns the indices per
    group id; unlike assign_nodes it never refuses.
    """
    out = dict((group["id"], []) for group in plan["groups"])
    if plan["groups"]:
        for i, (same, group_id, nid) in enumerate(_match(plan, mesh, result)):
            result["nodes"][i]["nid"] = nid if same else None
            out[group_id].append(i)
    return out


def assign_nodes(plan, mesh, result):
    """
    {group id: [index in result["nodes"]]}. A node of the result is the same
    node as a node of the plan, or a midside node the run added: that one goes
    to the nearest node of a group. Refused ("node_mismatch") if a cut node of
    the plan is not in the result, or if a run that added no nodes
    (result["extra_nodes"] False) reports a node the plan does not know: a sum
    over these nodes would be wrong.
    """
    out = dict((group["id"], []) for group in plan["groups"])
    count = sum(len(group["nodes"]) for group in plan["groups"])
    if not count:
        if result["nodes"]:
            raise Refused("node_mismatch", "the plan has no cut nodes")
        return out
    extra_nodes = result.get("extra_nodes")
    found = set()
    extra = 0
    for i, (same, group_id, nid) in enumerate(_match(plan, mesh, result)):
        if same:
            found.add(nid)
        else:
            extra += 1
            if extra_nodes is False:
                raise Refused("node_mismatch", "node {0} of the result, at {1}, "
                              "is no cut node".format(i, result["nodes"][i]["xyz"]))
        out[group_id].append(i)
    if len(found) != count:
        raise Refused("node_mismatch", "{0} of {1} cut nodes missing in the "
                      "result".format(count - len(found), count))
    # QUAD8_9 and TRIA6_7 of COQUE_3D add centre nodes, which are never shared:
    # with quadratic shells in the mesh a run adds nodes but maybe none on a
    # cut. Linear shells do not block LINE_QUAD of the bridge (it makes the
    # solids quadratic too when every non-solid is a LINE_QUAD shell), so the
    # check stays for them.
    centres = any(shape in ("quad8", "tri6") for shape, n_ in mesh["elements"].values())
    if (extra_nodes and not extra and not centres and
            any(g.get("faces") for g in plan["groups"])):
        raise Refused("node_mismatch", "no midside nodes in a result of a run "
                      "that added nodes to the mesh")
    return out


def positions(result, rank):
    """
    Where the forces of a rank act, in the order of result["nodes"]: the list
    to take the nodes of a group from for resultant(). x + u for a node with
    "large" set (all selected elements on it computed with large
    displacements), else x.
    """
    out = []
    for record, u in zip(result["nodes"], result["disp"][rank]):
        x = record["xyz"]
        if record.get("large"):
            out.append((x[0] + u[0], x[1] + u[1], x[2] + u[2]))
        else:
            out.append(x)
    return out


def mixed_shape(result, indices):
    """True if some nodes of a cut (indices in result["nodes"]) are summed on
    x and others on x + u: selected components with and without large
    displacements meet there. The panel warns."""
    flags = set(bool(result["nodes"][i].get("large")) for i in indices)
    return len(flags) > 1


# ---- statics --------------------------------------------------------------------------
def resultant(xyz_list, forces6_list, point):
    """(Fx, Fy, Fz, Mx, My, Mz) about point, in global axes."""
    if len(xyz_list) != len(forces6_list):
        raise ValueError("{0} positions, {1} forces".format(
            len(xyz_list), len(forces6_list)))
    fx = fy = fz = mx = my = mz = 0.0
    px, py, pz = point
    for x, f in zip(xyz_list, forces6_list):
        rx = x[0] - px
        ry = x[1] - py
        rz = x[2] - pz
        f0 = f[0]
        f1 = f[1]
        f2 = f[2]
        fx += f0
        fy += f1
        fz += f2
        mx += ry * f2 - rz * f1 + f[3]
        my += rz * f0 - rx * f2 + f[4]
        mz += rx * f1 - ry * f0 + f[5]
    return (fx, fy, fz, mx, my, mz)


def shift(sum6, old_point, new_point):
    """The same forces about new_point: M_new = M_old + (old - new) x F."""
    d = (old_point[0] - new_point[0], old_point[1] - new_point[1],
         old_point[2] - new_point[2])
    m = _cross(d, sum6[:3])
    return (sum6[0], sum6[1], sum6[2], sum6[3] + m[0], sum6[4] + m[1],
            sum6[5] + m[2])


def to_axes(sum6, axes):
    """(N, Vy, Vz, T, My, Mz) on axes (normal, a, b): y is a, z is b."""
    n, a, b = axes
    f = sum6[:3]
    m = sum6[3:6]
    return (_dot(f, n), _dot(f, a), _dot(f, b),
            _dot(m, n), _dot(m, a), _dot(m, b))


# ---- text ------------------------------------------------------------------------------
def number_text(value, decimal=".", digits=7):
    """
    A number with digits significant digits, from integers only: the "g"
    format follows the Windows locale in IronPython, and repr(0.3) is not 0.3
    there. Exponent form outside 1e-4 .. 10^digits.
    """
    x = float(value)
    if x != x:
        return "nan"
    if x in (float("inf"), float("-inf")):
        return "inf" if x > 0 else "-inf"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    x = abs(x)
    exponent = int(math.floor(math.log10(x)))
    power = digits - 1 - exponent
    scaled = x * 10.0 ** power if power <= 300 else x * 1e300 * 10.0 ** (power - 300)
    mantissa = int(math.floor(scaled + 0.5))
    if mantissa >= 10 ** digits:
        mantissa //= 10
        exponent += 1
    text = str(mantissa).rstrip("L")
    if exponent < -4 or exponent >= digits:
        head = text[0]
        tail = text[1:].rstrip("0")
        body = head + (decimal + tail if tail else "")
        return "{0}{1}E{2}{3:02d}".format(sign, body, "-" if exponent < 0 else "+",
                                          abs(exponent))
    if exponent < 0:
        tail = ("0" * (-exponent - 1) + text).rstrip("0")
        return sign + "0" + decimal + tail
    whole = text[:exponent + 1]
    tail = text[exponent + 1:].rstrip("0")
    return sign + whole + (decimal + tail if tail else "")


def table_text(rows, decimal=",", digits=7):
    """Tab separated text, CRLF, for the clipboard and CSV. Rows of text,
    numbers and None (empty)."""
    lines = []
    for row in rows:
        cells = []
        for cell in row:
            if cell is None:
                cells.append("")
            elif isinstance(cell, bool):
                cells.append("yes" if cell else "no")
            elif isinstance(cell, float):
                cells.append(number_text(cell, decimal, digits))
            elif isinstance(cell, _INTEGERS):
                cells.append(str(cell))
            else:
                cells.append(cell)
        lines.append("\t".join(cells))
    return "\r\n".join(lines) + "\r\n"
