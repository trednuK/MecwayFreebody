# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_nodecut.py
# Responsibility: a cut given by a set of nodes on a plane instead of a
# selection of elements (docs/design/knopensnede-plan.md, the rules after the
# review are binding). Turns the nodes into an element selection and a plan for
# the same follow-up run, and filters the result of that run down to the nodes
# of the cut. Knows neither Mecway nor Code-Aster.
#   plan_from_nodes()  plane, side, checks, growth, full or partial, the plan
#   filter_result()    keep only the cut nodes in all parallel arrays of a result
#
# cut = plan_from_nodes(mesh, node_ids, side=1)
# cut == {
#   "partial": bool,          # False: a real free body, everything as with an
#                             # element selection; True: the knots close no body,
#                             # the free body is the layer at the chosen side
#   "rest_valid": bool,       # not partial: the equilibrium check "rest" means
#                             # something; for a partial section it does not
#   "elements": [eid],        # element selection of the follow-up run: the grown
#                             # body (full) or the layer (partial); == plan["inside"]
#   "plan": plan,             # as fb_core.plan_cuts gives it, for fb_aster.start,
#                             # fb_core.section_geometry and fb_core.assign_nodes;
#                             # partial: the reduced plan (cut nodes only from the
#                             # selection, never the back of the layer), with
#                             # "drilling" judged on the whole mesh
#   "keep": [nid],            # Mecway nodes the sum runs over; == plan["cut_nodes"]
#   "keep_points": [(x, y, z)],   # their positions, plus the midpoints of edges of
#                             # linear elements with both corners selected: where a
#                             # run with LINE_QUAD adds a midside node of the cut
#   "side": 1 or -1,          # 1: the free body lies where plane["normal"] points
#   "normal": (nx, ny, nz),   # outward from the free body: -side * plane normal,
#                             # the "normal" section_geometry gives for its cut
#   "plane": {"point": (x, y, z),      # mean of the selected nodes
#             "normal": (nx, ny, nz),  # least squares normal, largest component > 0
#             "tolerance": tol,        # [m] "on the plane", in every check
#             "distance": d},          # largest distance of a selected node
#   "selected": [nid],        # the selected nodes, sorted, without doubles
#   "not_cut": [nid],         # selected nodes the rest does not share: no force
#   "layer": [eid],           # elements at the chosen side with a selected node
#   "leak": eid or None,      # partial: the first element the growth found at
#                             # the other side
#   "warnings": [code],       # "partial_section", "selected_not_cut"; warnings
#                             # of the plan stay in plan["warnings"]
# }
#
# Refusals (fb_core.Refused, .code): "unknown_node"; "nodes_collinear" (fewer
# than three nodes, or all on one line); "nodes_without_solid" (a node on no
# volume element); "nodes_not_planar"; "shell_or_beam" (a shell or beam on a
# selected node: the cut runs through solids only); "plane_through_elements" (an
# element on a selected node with nodes strictly at both sides); "side_empty"
# (no element at the chosen side on a selected node); "no_cut" (the rest shares
# no selected node); and the refusals of plan_cuts for the grown body. Checked in
# this order; the first that applies is given.
#
# Shells and beams elsewhere: a full section hands the grown body to plan_cuts,
# exactly as an element selection of that body, so shells and beams in it
# count as there (phase 4). A partial section is the layer at the selected
# nodes, which holds solids only, since a shell or beam there refuses.
#
# Full or partial: the growth from the layer never crosses a selected node or a
# midside node between two selected corners. It is partial when it reaches an
# element with a node strictly at the other side (a U seen from its base, a ring
# cut once). The subset rule of the plan then holds by construction; it stays as
# a check.
#
# filter_result(result, cut[, mesh]): see its docstring. Run before
# fb_aster.judge_rest (a hook in Job.result()), "on_cut" stays valid; after it,
# "on_cut" of a step that lost nodes is marked {"valid": False}.
#
# Lengths in metres. Compatible with IronPython 2.7.9 (Mecway) and CPython 3.
# Pure Python: no numpy.

import math

import fb_core
from fb_core import Refused

# "On the plane": this far from the plane, relative to the largest distance of a
# selected node to their mean. One tolerance for the plane, the line and the
# sides of the elements.
PLANE_TOL = 1e-6
# A node of a run and a point of the cut are the same within this [m], as in
# fb_core.assign_nodes.
SAME_POINT = 1e-8
_SOLIDS = frozenset(fb_core.SOLID_SHAPES)


# ---- small linear algebra ------------------------------------------------------------
def _eigen3(a):
    """Eigenvalues and unit eigenvectors of a symmetric 3x3 matrix, by Jacobi
    rotations: [(value, (x, y, z))], smallest value first."""
    a = [list(row) for row in a]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(60):
        off = a[0][1] ** 2 + a[0][2] ** 2 + a[1][2] ** 2
        diag = a[0][0] ** 2 + a[1][1] ** 2 + a[2][2] ** 2
        if off == 0.0 or off <= 1e-30 * diag:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p][q]
            if apq == 0.0:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * apq)
            t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(3):
                akp = a[k][p]
                akq = a[k][q]
                a[k][p] = c * akp - s * akq
                a[k][q] = s * akp + c * akq
            for k in range(3):
                apk = a[p][k]
                aqk = a[q][k]
                a[p][k] = c * apk - s * aqk
                a[q][k] = s * apk + c * aqk
            a[p][q] = a[q][p] = 0.0
            for k in range(3):
                vkp = v[k][p]
                vkq = v[k][q]
                v[k][p] = c * vkp - s * vkq
                v[k][q] = s * vkp + c * vkq
    out = []
    for i in range(3):
        x = (v[0][i], v[1][i], v[2][i])
        size = math.sqrt(x[0] * x[0] + x[1] * x[1] + x[2] * x[2])
        out.append((a[i][i], (x[0] / size, x[1] / size, x[2] / size)))
    out.sort(key=lambda item: item[0])
    return out


def _fit_plane(points):
    """{"point", "normal", "tolerance", "distance"} of the least squares plane.
    Refused with nodes_collinear or nodes_not_planar."""
    n = float(len(points))
    c = tuple(sum(p[k] for p in points) / n for k in range(3))
    rel = [(p[0] - c[0], p[1] - c[1], p[2] - c[2]) for p in points]
    radius = max(math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) for d in rel)
    if radius == 0.0:
        raise Refused("nodes_collinear", "all nodes at one point")
    tol = PLANE_TOL * radius
    m = [[0.0] * 3 for _ in range(3)]
    for d in rel:
        for i in range(3):
            for j in range(3):
                m[i][j] += d[i] * d[j]
    (_, normal), _, (_, line) = _eigen3(m)
    off_line = 0.0
    for d in rel:
        t = d[0] * line[0] + d[1] * line[1] + d[2] * line[2]
        e = (d[0] - t * line[0], d[1] - t * line[1], d[2] - t * line[2])
        off_line = max(off_line, math.sqrt(e[0] * e[0] + e[1] * e[1] + e[2] * e[2]))
    if off_line <= tol:
        raise Refused("nodes_collinear", "the nodes lie on one line")
    normal = fb_core._sign_fixed(normal)
    distance = max(abs(d[0] * normal[0] + d[1] * normal[1] + d[2] * normal[2]) for d in rel)
    if distance > tol:
        raise Refused("nodes_not_planar", "a node lies {0} m from the plane, more than "
                      "{1} m".format(fb_core.number_text(distance, digits=3),
                                     fb_core.number_text(tol, digits=3)))
    return {"point": c, "normal": normal, "tolerance": tol, "distance": distance}


# ---- the mesh around the nodes ---------------------------------------------------------
def _by_node(elements):
    """{nid: [eid]} over all elements."""
    out = {}
    for e, (shape, nids) in elements.items():
        for n in nids:
            out.setdefault(n, []).append(e)
    for n in out:
        out[n].sort()
    return out


def _short(items):
    items = sorted(items)
    text = ", ".join(str(i) for i in items[:10])
    return text + (", ..." if len(items) > 10 else "")


class _Sides(object):
    """Signed distances to the plane, per node, computed once."""

    def __init__(self, nodes, plane):
        self.nodes = nodes
        self.c = plane["point"]
        self.n = plane["normal"]
        self.tol = plane["tolerance"]
        self.cache = {}

    def of(self, nids):
        """(any node strictly at +normal, any node strictly at -normal)."""
        pos = neg = False
        cache = self.cache
        tol = self.tol
        for nid in nids:
            d = cache.get(nid)
            if d is None:
                p = self.nodes[nid]
                c = self.c
                n = self.n
                d = (p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1] + (p[2] - c[2]) * n[2]
                cache[nid] = d
            if d > tol:
                pos = True
            elif d < -tol:
                neg = True
        return pos, neg


def _cut_edges(mesh, eids, chosen):
    """(midside nodes of the mesh, midpoints) of the edges with both corners in
    chosen: quadratic elements by node number, linear ones by the midpoint."""
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    mids = set()
    points = {}
    for e in eids:
        shape, nids = elements[e]
        for a, b, m in fb_core._EDGE_LOCAL[shape]:
            na = nids[a]
            nb = nids[b]
            if na in chosen and nb in chosen:
                if m is not None:
                    mids.add(nids[m])
                else:
                    pa = nodes[na]
                    pb = nodes[nb]
                    key = (na, nb) if na < nb else (nb, na)
                    points[key] = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0,
                                   (pa[2] + pb[2]) / 2.0)
    return mids, points


def _grow(elements, by_node, layer, blocked, other_side):
    """The elements reached from the layer over shared nodes, never over a
    blocked node. (body, None), or (None, eid) of the first element found at
    the other side."""
    seen = set(layer)
    stack = sorted(layer, reverse=True)
    while stack:
        e = stack.pop()
        for n in elements[e][1]:
            if n in blocked:
                continue
            for f in by_node[n]:
                if f in seen:
                    continue
                seen.add(f)
                if other_side(f):
                    return None, f
                stack.append(f)
    return seen, None


def _reduced_plan(mesh, layer, blocked, by_node):
    """The plan of a partial section: plan_cuts of the layer against the
    elements outside it that touch the cut, with every other node of those
    elements renamed, so the back of the layer is no cut. The groups, faces and
    warnings follow the rules of plan_cuts. "outside" is all of the rest."""
    elements = mesh["elements"]
    in_layer = set(layer)
    near = set()
    for n in blocked:
        for f in by_node.get(n, ()):
            if f not in in_layer:
                near.add(f)
    nodes = dict(mesh["nodes"])
    fresh = {}
    top = [max(nodes) if nodes else 0]
    sub = {}
    for e in layer:
        sub[e] = elements[e]
    for f in near:
        shape, nids = elements[f]
        renamed = []
        for n in nids:
            if n in blocked:
                renamed.append(n)
                continue
            new = fresh.get(n)
            if new is None:
                top[0] += 1
                new = top[0]
                fresh[n] = new
                nodes[new] = mesh["nodes"][n]
            renamed.append(new)
        sub[f] = (shape, renamed)
    part = {"nodes": nodes, "elements": sub}
    for key in ("component", "moments", "moment_nodes", "coupled_nodes"):
        if key in mesh:
            part[key] = mesh[key]
    plan = fb_core.plan_cuts(part, layer)
    plan["outside"] = sorted(e for e in elements if e not in in_layer)
    # The drilling warning looks at every shell of the model (contract, as
    # built), and the part holds none: judge it on the whole mesh
    drilling = fb_core._drilling(mesh, list(layer), sorted(near))
    plan["drilling"] = drilling
    warnings = [w for w in plan["warnings"] if w != "drilling"]
    if drilling:
        warnings.append("drilling")
    plan["warnings"] = warnings
    return plan


def plan_from_nodes(mesh, node_ids, side=1):
    """
    The cut through a set of nodes on a plane, at one side of it. See the
    header for what it returns and refuses. side: 1 is the side the normal of
    the plane points to (its largest component positive), -1 the other side.
    """
    if side not in (1, -1):
        raise ValueError("side must be 1 or -1, not {0!r}".format(side))
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    selected = sorted(set(node_ids))
    unknown = [n for n in selected if n not in nodes]
    if unknown:
        raise Refused("unknown_node", _short(unknown))
    if len(selected) < 3:
        raise Refused("nodes_collinear", "{0} nodes; a plane needs three".format(len(selected)))
    by_node = _by_node(elements)
    without = [n for n in selected
               if not any(elements[e][0] in _SOLIDS for e in by_node.get(n, ()))]
    if without:
        raise Refused("nodes_without_solid", "{0} nodes on no volume element: {1}".format(
            len(without), _short(without)))
    plane = _fit_plane([nodes[n] for n in selected])
    chosen = set(selected)
    touching = sorted(set(e for n in selected for e in by_node[n]))
    other = [e for e in touching if elements[e][0] not in _SOLIDS]
    if other:
        raise Refused("shell_or_beam", "{0} shell or beam elements on the nodes: {1}".format(
            len(other), _short(other)))
    sides = _Sides(nodes, plane)
    through = []
    layer = []
    for e in touching:
        pos, neg = sides.of(elements[e][1])
        if pos and neg:
            through.append(e)
        elif (pos if side == 1 else neg):
            layer.append(e)
    if through:
        raise Refused("plane_through_elements", "{0} elements cross the plane: {1}".format(
            len(through), _short(through)))
    if not layer:
        raise Refused("side_empty", "no element at this side of the nodes")

    mids, midpoints = _cut_edges(mesh, touching, chosen)
    blocked = chosen | mids

    def other_side(f):
        pos, neg = sides.of(elements[f][1])
        return neg if side == 1 else pos

    body, leak = _grow(elements, by_node, layer, blocked, other_side)
    partial = True
    plan = None
    if body is not None:
        plan = fb_core.plan_cuts(mesh, sorted(body))
        # Rule 5. The growth crossed every node that is not blocked, so this
        # holds by construction: a check, not a second criterion.
        partial = not blocked.issuperset(plan["cut_nodes"])
    if partial:
        plan = _reduced_plan(mesh, layer, blocked, by_node)
    if not plan["cut_nodes"]:
        raise Refused("no_cut", "the rest of the model shares none of the nodes")
    keep = plan["cut_nodes"]
    kept = set(keep)
    points = [nodes[n] for n in keep]
    for (a, b) in sorted(midpoints):
        if a in kept and b in kept:
            points.append(midpoints[(a, b)])
    not_cut = sorted(chosen - kept)
    warnings = []
    if partial:
        warnings.append("partial_section")
    if not_cut:
        warnings.append("selected_not_cut")
    n = plane["normal"]
    return {"partial": partial, "rest_valid": not partial, "elements": list(plan["inside"]),
            "plan": plan, "keep": list(keep), "keep_points": points, "side": side,
            "normal": (0.0 - side * n[0], 0.0 - side * n[1], 0.0 - side * n[2]),
            "plane": plane,
            "selected": selected, "not_cut": not_cut, "layer": layer, "leak": leak,
            "warnings": warnings}


# ---- the result of the run ----------------------------------------------------------
class _PointSet(object):
    """Points, and whether a point is one of them within SAME_POINT."""

    def __init__(self, points):
        self.size = SAME_POINT * 4
        self.cells = {}
        for p in points:
            self.cells.setdefault(self._key(p), []).append(p)

    def _key(self, p):
        s = self.size
        return (int(math.floor(p[0] / s)), int(math.floor(p[1] / s)),
                int(math.floor(p[2] / s)))

    def has(self, p):
        i, j, k = self._key(p)
        tol = SAME_POINT * SAME_POINT
        for a in (i - 1, i, i + 1):
            for b in (j - 1, j, j + 1):
                for c in (k - 1, k, k + 1):
                    for q in self.cells.get((a, b, c), ()):
                        if ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 +
                                (q[2] - p[2]) ** 2) <= tol:
                            return True
        return False


def filter_result(result, cut, mesh=None):
    """
    A copy of a result of fb_aster (Job.result() or decode_result()) with only
    the nodes of the cut; the result itself is not changed. Every array
    parallel to result["nodes"] is filtered with the same indices, per step:
    "forces", "disp" and the "totals" of "on_cut", so a force never moves to
    another node. A partial section: "rest" of every step gets "valid": False
    and "warnings" gets "partial_section". A step of "on_cut" that was judged
    already (no "totals") and lost nodes gets "valid": False. "nodecut" holds
    the flags for the panel and "kept", the indices kept in the old numbering.
    A full section loses no node; if it would, Refused("node_mismatch").
    mesh is not needed: the positions are in cut["keep_points"].
    """
    records = result["nodes"]
    count = len(records)
    for key in ("forces", "disp"):
        for rank, rows in result[key].items():
            if len(rows) != count:
                raise ValueError("{0} of step {1}: {2} rows for {3} nodes".format(
                    key, rank, len(rows), count))
    for rank, entry in result.get("on_cut", {}).items():
        if "totals" in entry and len(entry["totals"]) != count:
            raise ValueError("on_cut of step {0}: {1} rows for {2} nodes".format(
                rank, len(entry["totals"]), count))
    points = _PointSet(cut["keep_points"])
    keep = [i for i, record in enumerate(records) if points.has(record["xyz"])]
    dropped = count - len(keep)
    if dropped and not cut["partial"]:
        kept = set(keep)
        first = [records[i]["xyz"] for i in range(count) if i not in kept][:3]
        raise Refused("node_mismatch", "{0} nodes of a full section are no cut node, "
                      "at {1}".format(dropped, first))
    out = dict(result)
    out["nodes"] = [dict(records[i]) for i in keep]
    for key in ("forces", "disp"):
        out[key] = dict((rank, [rows[i] for i in keep]) for rank, rows in result[key].items())
    on_cut = {}
    for rank, entry in result.get("on_cut", {}).items():
        entry = dict(entry)
        if "totals" in entry:
            totals = entry["totals"]
            entry["totals"] = [totals[i] for i in keep]
        elif dropped:
            entry["valid"] = False
        on_cut[rank] = entry
    out["on_cut"] = on_cut
    rest = {}
    for rank, entry in result.get("rest", {}).items():
        entry = dict(entry)
        if cut["partial"]:
            entry["valid"] = False
        rest[rank] = entry
    out["rest"] = rest
    out["large"] = any(bool(r.get("large")) for r in out["nodes"])
    warnings = list(result.get("warnings", []))
    if cut["partial"] and "partial_section" not in warnings:
        warnings.append("partial_section")
    out["warnings"] = warnings
    out["nodecut"] = {"partial": cut["partial"], "rest_valid": cut["rest_valid"],
                      "dropped": dropped, "kept": keep}
    return out
