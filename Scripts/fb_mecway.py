# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_mecway.py
# Responsibility: everything that touches mw and solution, plus finding the
# bridge on this PC. mw and solution exist only in the main script: they come
# in as arguments, and every function that uses them runs on the script thread
# (fb_gui hands them over; see _MwCaller there).
#   read_selection()    what is selected in Mecway: elements and nodes
#   read_mesh_steps()   mesh of the contract and the input of the fingerprint,
#                       in chunks so that Mecway keeps answering
#   read_props()        E per element, thickness of shells
#   read_moments_steps()  nodal moments for the drilling warning: from the
#                       saved .liml, nodes through the API
#   arrow_steps()       the arrows: fields in the solution
#   find_bridge()       work folder and Code-Aster launcher of the bridge
#
# Functions ending in _steps are generators: every yield hands the thread back
# to Mecway. They write their outcome in the dict `out`.
#
# Measured in Mecway 35 (self-made block, hidden run):
#   node_value on a known field that is empty gives None, on an unknown name it
#   raises; a value of None in set_variable leaves that node empty; the list
#   must hold exactly one value per node of the solution; a saved file holds the
#   new fields.
#   Loads: mw has no call that lists loads or constraints (load_property needs
#   a load name, and none can be listed), so the loads come from the saved
#   .liml. There a moment is <moment selection="S"> with <x>, <y>, <z> in the
#   unit as typed ("0.002 kN.m"), a time-dependent component as several
#   <x time="..."> lines; a solved file repeats the loads in the model copy
#   inside <solution>. mw.named_selection gives ints for a node selection and
#   FaceId items (element_id, face_number) for a face selection; face_nodes of
#   face 3 of a line2 is its node 2.
#
# Compatible with IronPython 2.7.9 (Mecway) and CPython 3 (tests with a fake
# mw). No clr here.

import glob
import io
import math
import os
import re

import fb_core

FIELDS_FORCE = ("externalforcex", "externalforcey", "externalforcez")
FIELDS_MOMENT = ("reactionmomx", "reactionmomy", "reactionmomz")
# Largest arrow when no size is given. The panel writes the first arrows of a
# solution with their true values; later writes keep that length, because
# Mecway's legend and arrow length do not follow a second write (measured).
ARROW_SIZE = 1.0
SHELL_SHAPES = ("tri3", "tri6", "quad4", "quad8", "quad9", "tri7")
LINE_SHAPES = ("line2", "line3")
CHUNK = 4000
READ_BLOCK = 1 << 20            # characters of the .liml per read
_LBF = 4.4482216152605
_KIP = 1000.0 * _LBF
_IN = 0.0254
_FT = 0.3048
# Moment units to N.m, written without separators ("kN.m" -> "kNm"); case
# counts (MN.m and mN.m)
MOMENT_UNITS = {"Nm": 1.0, "kNm": 1e3, "MNm": 1e6, "mNm": 1e-3, "Nmm": 1e-3,
                "kNmm": 1.0, "Ncm": 1e-2, "kNcm": 10.0, "lbfin": _LBF * _IN, "inlbf": _LBF * _IN,
                "lbfft": _LBF * _FT, "ftlbf": _LBF * _FT, "kipin": _KIP * _IN,
                "inkip": _KIP * _IN, "kipft": _KIP * _FT, "ftkip": _KIP * _FT}
_PARALLEL = 1e-9                # |a x b| <= this |a||b|: one direction
_CHECKED_NODES = 2000
_SAME_POSITION = 1e-9           # m, between model and solution
_SAME_VALUE = 1e-9              # relative, a value we wrote ourselves


class MeshChanged(Exception):
    """The mesh changed while it was being read."""


def ints(values):
    return [int(v) for v in values]


# ---- reading --------------------------------------------------------------------
def model_path(mw):
    """Path of the open model, "" for a model that was never saved."""
    path = mw.file_name()
    return u"{0}".format(path) if path else u""


def _selected(mw, solution, name):
    """The ids of mw.<name>(), else of the solution's: in the result view a
    selection may live on the solution (not verified)."""
    try:
        ids = ints(getattr(mw, name)())
    except Exception:
        ids = []
    if not ids and solution is not None:
        try:
            ids = ints(getattr(solution, name)())
        except Exception:
            ids = []
    return ids


def read_selection(mw, solution=None):
    """{"elements": [eid], "node_ids": [nid], "nodes": n, "faces": n}: the
    selected elements (a cut by elements) and nodes (a cut by nodes on a plane,
    fb_nodecut); "nodes" is len(node_ids). A model without a selection of its
    own looks at the solution's."""
    elements = ints(mw.selected_elements())
    if not elements and solution is not None:
        try:
            elements = ints(solution.selected_elements())
        except Exception:
            elements = []
    node_ids = _selected(mw, solution, "selected_nodes")
    out = {"elements": elements, "node_ids": node_ids, "nodes": len(node_ids), "faces": 0}
    try:
        out["faces"] = len(list(mw.selected_faces()))
    except Exception:
        pass
    return out


def selected_nodes(mw):
    return ints(mw.selected_nodes())


def read_mesh_steps(mw, out, chunk=CHUNK):
    """out["mesh"]: the mesh of the contract. Mecway answers between chunks, so
    the counts are compared at the end: an edit in between is not read as a
    mesh."""
    node_ids = ints(mw.all_nodes())
    element_ids = ints(mw.all_elements())
    yield
    nodes = {}
    for i, nid in enumerate(node_ids):
        p = mw.node(nid)
        nodes[nid] = (float(p.x), float(p.y), float(p.z))
        if (i + 1) % chunk == 0:
            yield
    elements = {}
    component = {}
    for i, eid in enumerate(element_ids):
        elements[eid] = (str(mw.element_shape(eid)), ints(mw.nodes(eid)))
        component[eid] = u"{0}".format(mw.element_component(eid))
        if (i + 1) % chunk == 0:
            yield
    if (ints(mw.all_nodes()) != node_ids or
            ints(mw.all_elements()) != element_ids):
        raise MeshChanged("the mesh changed while it was read")
    out["mesh"] = {"nodes": nodes, "elements": elements, "component": component}


def _thickness(mw, material):
    """Shell thickness of a material in m, or None. Thickness lives in the
    material (geometric group, type Plate), so it is one per component."""
    try:
        kind = mw.material_type(material, "geometric")
    except Exception:
        kind = None
    if kind is not None and u"{0}".format(kind) != "Plate":
        return None
    try:
        value = float(mw.material_property(material, "thickness"))
    except Exception:
        return None
    return value if value > 0 and value == value and value != float("inf") else None


def read_props(mw, mesh, missing=None):
    """({eid: {"E": value, "thickness": t}}, [components without a readable
    E]). E of an isotropic material; any other gives no value. Thickness only
    for elements with a shell shape. missing (a dict, optional) gets
    "thickness": [shell components without a readable thickness]. Sections of
    beams are not read here: the manifest holds what Code-Aster used."""
    shells = set()
    for eid, name in mesh["component"].items():
        if mesh["elements"][eid][0] in SHELL_SHAPES:
            shells.add(name)
    known = {}
    thick = {}
    unknown = []
    no_thickness = []
    for name in sorted(set(mesh["component"].values())):
        try:
            material = mw.material(name)
        except Exception:
            unknown.append(name)
            if name in shells:
                no_thickness.append(name)
            continue
        try:
            if mw.material_type(material, "mechanical") != "Isotropic":
                raise ValueError(material)
            known[name] = float(mw.material_property(material, "youngsmodulus"))
        except Exception:
            unknown.append(name)
        if name in shells:
            t = _thickness(mw, material)
            if t is None:
                no_thickness.append(name)
            else:
                thick[name] = t
    props = {}
    for eid, name in mesh["component"].items():
        entry = {}
        if name in known:
            entry["E"] = known[name]
        if name in thick and mesh["elements"][eid][0] in SHELL_SHAPES:
            entry["thickness"] = thick[name]
        if entry:
            props[eid] = entry
    if missing is not None:
        missing["thickness"] = no_thickness
    return props, unknown


# ---- nodal moments (drilling warning) ---------------------------------------------
# Only the loads that give Code-Aster a moment on a node count: the bridge
# turns a moment on one node or one beam end into FORCE_NODALE MX/MY/MZ, a
# moment on faces into forces, and drops a moment on more than one node. A
# prescribed rotation (noderotation) that is not zero becomes DDL_IMPO, no
# force; it turns the node all the same, so it counts with its axis, on every
# node of its selection (a precaution, not measured).
_TAGS = re.compile(r"<(moment|noderotation|nodeselection|elementselection|faceselection)"
                   r"[\s/>]")
_KINDS = {"nodeselection": "node", "elementselection": "element", "faceselection": "face"}
_CHILD = re.compile(r"<(x|y|z|value)\b([^>]*)>([^<]*)</\1\s*>")
_TIME = re.compile(r"\btime\s*=\s*\"([^\"]*)\"")
_SELECTION = re.compile(r"\bselection\s*=\s*\"([^\"]*)\"")
_NAME = re.compile(r"\bname\s*=\s*\"([^\"]*)\"")
_ENTITY = re.compile(r"&(#x[0-9a-fA-F]+|#[0-9]+|lt|gt|quot|apos|amp);")
_ENTITIES = {"lt": u"<", "gt": u">", "quot": u"\"", "apos": u"'", "amp": u"&"}
_LONGEST = 4 << 20             # an open element longer than this: not a .liml


def _unescape(text):
    def one(m):
        code = m.group(1)
        if code.startswith("#x"):
            return unichr_(int(code[2:], 16))
        if code.startswith("#"):
            return unichr_(int(code[1:]))
        return _ENTITIES[code]
    return _ENTITY.sub(one, text)


try:
    unichr_ = unichr             # noqa: F821  (Python 2)
except NameError:
    unichr_ = chr


def _model_pieces(f, size=READ_BLOCK):
    """The text of a .liml outside <solution ...> ... </solution>, in pieces:
    a solved file holds a model copy there, and the results. <solutionfile>
    is not a solution."""
    open_tag, close_tag = u"<solution", u"</solution>"
    pending = u""
    inside = False
    while True:
        block = f.read(size)
        text = pending + block
        pending = u""
        out = []
        pos = 0
        while pos < len(text):
            if inside:
                k = text.find(close_tag, pos)
                if k < 0:
                    if block:
                        pending = text[max(pos, len(text) - len(close_tag) + 1):]
                    pos = len(text)
                    break
                inside = False
                pos = k + len(close_tag)
                continue
            k = text.find(open_tag, pos)
            if k < 0:
                cut = max(pos, len(text) - len(open_tag)) if block else len(text)
                out.append(text[pos:cut])
                pending = text[cut:]
                break
            end = text.find(u">", k)
            if end < 0:
                out.append(text[pos:k])
                if block:
                    pending = text[k:]
                break
            after = text[k + len(open_tag)]
            if after in u" \t\r\n>/":
                out.append(text[pos:k])
                inside = text[end - 1] != u"/"
                pos = end + 1
            else:
                out.append(text[pos:k + 1])
                pos = k + 1
        yield u"".join(out)
        if not block:
            return


def liml_items(pieces):
    """Generator over pieces of the model text (see _model_pieces): None after
    each piece (a moment to hand back the thread), and per item one of
    ("kind", selection name, "node" | "element" | "face"), ("moment", text of
    the element), ("noderotation", text of the element). Raises ValueError for
    an element that does not end, also at the end of the file."""
    buf = u""
    for piece in pieces:
        buf += piece
        pos = 0
        while True:
            m = _TAGS.search(buf, pos)
            if m is None:
                buf = buf[max(pos, len(buf) - 24):]
                break
            tag = m.group(1)
            end = buf.find(u">", m.start())
            if end < 0:
                buf = buf[m.start():]
                break
            if tag in _KINDS:
                name = _NAME.search(buf, m.start(), end)
                if name:
                    yield ("kind", _unescape(name.group(1)), _KINDS[tag])
                pos = end + 1
                continue
            if buf[end - 1] == u"/":
                yield (tag, buf[m.start():end + 1])
                pos = end + 1
                continue
            close = buf.find(u"</" + tag, end)
            stop = buf.find(u">", close) if close >= 0 else -1
            if stop < 0:
                buf = buf[m.start():]
                break
            yield (tag, buf[m.start():stop + 1])
            pos = stop + 1
        if len(buf) > _LONGEST:
            raise ValueError("an element of the .liml does not end")
        yield None
    if _TAGS.search(buf):
        raise ValueError("the .liml ends inside an element")


def _number(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _moment_value(text):
    """N.m of "0.002 kN.m", or None."""
    parts = text.split(None, 1)
    if not parts:
        return None
    value = _number(parts[0])
    if value is None:
        return None
    unit = parts[1] if len(parts) > 1 else u""
    for sep in (u".", u"·", u"*", u" ", u"-"):
        unit = unit.replace(sep, u"")
    factor = MOMENT_UNITS.get(unit)
    return None if factor is None else value * factor


def _children(text):
    """{"x": [(time or None, text)], ...} of an element.
    Another attribute than time (a formula?) gives the text "?": no number."""
    out = {}
    for m in _CHILD.finditer(text):
        attrs = m.group(2)
        t = _TIME.search(attrs)
        rest = _TIME.sub(u"", attrs).strip()
        value = u"?" if rest else m.group(3).strip()
        out.setdefault(m.group(1), []).append((t.group(1) if t else None, value))
    return out


def _cross_size(a, b):
    c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.sqrt(c[0] ** 2 + c[1] ** 2 + c[2] ** 2)


def _size(a):
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _one_direction(vectors):
    """The largest vector if all lie on one line, else None."""
    big = max(vectors, key=_size)
    for v in vectors:
        if _cross_size(v, big) > _PARALLEL * _size(v) * _size(big):
            return None
    return big


def moment_vector(text):
    """(vector in N.m or None, steady) of a <moment> element: None when the
    direction cannot be told (a formula, an unknown unit, a missing component,
    time histories on other time points). steady False: the value changes in
    time; a history whose vectors all lie on one line keeps its largest."""
    comps = _children(text)
    rows = [comps.get(k) or [] for k in ("x", "y", "z")]
    if not all(rows):
        return None, True
    if all(len(r) == 1 and r[0][0] is None for r in rows):
        v = tuple(_moment_value(r[0][1]) for r in rows)
        return (None if None in v else v), True
    times = None
    for r in rows:
        if len(r) > 1 or r[0][0] is not None:
            stamps = [t for t, _ in r]
            if None in stamps or (times is not None and stamps != times):
                return None, False
            times = stamps
    vectors = []
    for i in range(len(times)):
        v = []
        for r in rows:
            v.append(_moment_value(r[i][1] if len(r) > 1 or r[0][0] is not None else r[0][1]))
        if None in v:
            return None, False
        vectors.append(tuple(v))
    return _one_direction(vectors), False


def rotation_vector(text):
    """The axis of a <noderotation> element whose value is not zero, None when
    it cannot be told, "zero" for a rotation held at zero (a support)."""
    comps = _children(text)
    values = [_number((v.split(None, 1) or [u""])[0]) for _, v in comps.get("value") or []]
    if not values or None in values:
        return None
    if all(v == 0.0 for v in values):
        return "zero"
    axis = []
    for k in ("x", "y", "z"):
        row = comps.get(k) or []
        value = _number(row[0][1]) if len(row) == 1 else None
        if value is None:
            return None
        axis.append(value)
    return tuple(axis)


def _selection_attr(text):
    m = _SELECTION.search(text[:text.find(u">") + 1])
    return _unescape(m.group(1)) if m else None


def _members(mw, mesh, name, kind):
    """(node ids, all items on line elements) of a named selection, through
    the API; FaceId items give their face nodes."""
    nodes = set()
    on_lines = True
    elements = mesh["elements"]
    for item in mw.named_selection(name):
        if hasattr(item, "element_id"):
            eid = int(item.element_id)
            if eid not in elements or elements[eid][0] not in LINE_SHAPES:
                on_lines = False
            nodes.update(ints(mw.face_nodes(item)))
        elif kind == "element":
            eid = int(item)
            on_lines = False
            if eid in elements:
                nodes.update(elements[eid][1])
        else:
            nodes.add(int(item))
    return nodes, on_lines


def read_moments_steps(mw, mesh, out, chunk=CHUNK, size=READ_BLOCK):
    """
    Nodal moments for fb_core's drilling warning: mesh["moments"] {nid: (mx,
    my, mz)} and mesh["moment_nodes"] [nid] (a moment whose direction cannot
    be told). out["unread"]: None, a code ("not_saved", "not_liml",
    "unreadable") or [selection names the API does not know]; what was not
    read is not in the mesh. Reads the saved .liml (not the open model: mw
    lists no loads), every moment and non-zero rotation of the model, also
    one suppressed in a configuration. Mirrors the bridge: a moment on one
    node or one beam end; on more nodes, or on faces, none.
    """
    mesh["moments"] = {}
    mesh["moment_nodes"] = []
    out["unread"] = None
    path = model_path(mw)
    if not path:
        out["unread"] = "not_saved"
        return
    if not path.lower().endswith(".liml"):
        out["unread"] = "not_liml"
        return
    kinds = {}
    found = []
    try:
        with io.open(path, encoding="utf-8-sig", errors="replace") as f:
            for item in liml_items(_model_pieces(f, size)):
                if item is None:
                    yield
                elif item[0] == "kind":
                    kinds.setdefault(item[1], item[2])
                else:
                    found.append(item)
    except Exception:
        # a warning feature never stops the panel: say it could not be read
        out["unread"] = "unreadable"
        return
    per_node = {}
    unknown = []
    for i, (tag, text) in enumerate(found):
        name = _selection_attr(text)
        if not name:
            continue                # a load without a selection acts nowhere
        kind = kinds.get(name)
        if tag == "moment":
            if kind == "element":
                continue
            vector, steady = moment_vector(text)
        else:
            # an axis, not a moment: never added to another entry
            vector, steady = rotation_vector(text), False
            if vector == "zero":
                continue
        try:
            nodes, on_lines = _members(mw, mesh, name, kind)
        except Exception:
            unknown.append(name)
            continue
        if tag == "moment" and (len(nodes) != 1 or not on_lines):
            continue
        for nid in nodes:
            per_node.setdefault(nid, []).append((vector, steady))
        if (i + 1) % chunk == 0:
            yield
    moments = {}
    bare = []
    for nid, entries in per_node.items():
        if any(v is None for v, _ in entries) or (
                len(entries) > 1 and not all(s for _, s in entries)):
            bare.append(nid)
            continue
        moments[nid] = tuple(sum(v[k] for v, _ in entries) for k in range(3))
    mesh["moments"] = moments
    mesh["moment_nodes"] = sorted(bare)
    if unknown:
        out["unread"] = sorted(set(unknown))


# ---- arrows: what goes where ------------------------------------------------------
def _distance2(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def _key(p):
    return (int(math.floor(p[0] * 1e7 + 0.5)), int(math.floor(p[1] * 1e7 + 0.5)),
            int(math.floor(p[2] * 1e7 + 0.5)))


def nearest_node(mesh, nids, point):
    """(node, distance) of the node of nids nearest to point."""
    nodes = mesh["nodes"]
    best = None
    best_d = None
    for nid in nids:
        d = _distance2(nodes[nid], point)
        if best is None or d < best_d:
            best, best_d = nid, d
    return best, math.sqrt(best_d)


def result_to_nodes(mesh, nids, points):
    """For each point of a result the Mecway node it is, or the nearest one
    for a midside node the run added: ([nid], number of added nodes)."""
    nodes = mesh["nodes"]
    table = dict((_key(nodes[n]), n) for n in nids)
    out = []
    added = 0
    for p in points:
        nid = table.get(_key(p))
        if nid is None:
            nid, distance = nearest_node(mesh, nids, p)
            if distance > 1e-7:
                added += 1
        out.append(nid)
    return out, added


def per_node_values(mesh, cuts):
    """Forces per Mecway cut node. cuts: [{"nodes": [nid], "points": [(x, y,
    z)], "forces": [six values]}], points of the undeformed mesh. Returns
    ({nid: six values}, number of added midside nodes that went onto a
    neighbour)."""
    values = {}
    lumped = 0
    for cut in cuts:
        targets, added = result_to_nodes(mesh, cut["nodes"], cut["points"])
        lumped += added
        for nid, force in zip(targets, cut["forces"]):
            old = values.get(nid, (0.0,) * 6)
            values[nid] = tuple(old[i] + force[i] for i in range(6))
    return values, lumped


def outside_nodes(mesh, nids):
    """The nodes of nids on the outside of the mesh: on an element that is no
    solid (a shell, a beam), or on a face of a solid that no other element
    shares. A node inside a solid has none of these: Mecway draws the outside
    over it. Faces are compared by their corner nodes (a conforming mesh); a
    node on no element counts as outside. One pass over the mesh."""
    wanted = set(nids)
    holders = dict((n, []) for n in wanted)
    elements = mesh["elements"]
    for eid, (shape, enodes) in elements.items():
        for n in enodes:
            if n in wanted:
                holders[n].append(eid)
    out = set()
    for n in wanted:
        if not holders[n]:
            out.add(n)
            continue
        count = {}
        for eid in holders[n]:
            shape, enodes = elements[eid]
            if shape not in fb_core.SOLID_SHAPES:
                count = None
                break
            quadratic = fb_core._FAMILIES[shape][3]
            for local in fb_core._FACE_LOCAL[shape]:
                ids = [enodes[i] for i in local]
                if n in ids:
                    key = frozenset(ids[:len(ids) // 2] if quadratic else ids)
                    count[key] = count.get(key, 0) + 1
        if count is None or any(c == 1 for c in count.values()):
            out.add(n)
    return out


def resultant_values(mesh, cuts):
    """One arrow per cut, on the cut node nearest its point. cuts: [{"id",
    "nodes", "point": (x, y, z), "sum6": six values about that point}]. Returns
    ({nid: six values}, [{"cut", "node", "distance", "inside"}]); "inside":
    the node lies inside a solid, where Mecway's outside can hide the arrow."""
    values = {}
    places = []
    for cut in cuts:
        nid, distance = nearest_node(mesh, cut["nodes"], cut["point"])
        old = values.get(nid, (0.0,) * 6)
        values[nid] = tuple(old[i] + cut["sum6"][i] for i in range(6))
        places.append({"cut": cut["id"], "node": nid, "distance": distance})
    outside = outside_nodes(mesh, [p["node"] for p in places])
    for place in places:
        place["inside"] = place["node"] not in outside
    return values, places


def solution_step(solution, time=None):
    """The step number node_value and set_variable need: a solution with time
    steps refuses a call without one (measured). None: no time steps. time
    None: the last step, else the step nearest to that time."""
    try:
        steps = list(solution.time_steps())
    except Exception:
        return None
    if not steps:
        return None
    if time is None:
        return steps[-1]
    return min(steps, key=lambda k: abs(solution.time(k) - time))


def step_matches(solution, step, time):
    """False if the solution has no step at this time: the bridge can store
    other steps than the run has, and an arrow must not land in another one."""
    if step is None or time is None:
        return True
    try:
        times = [solution.time(k) for k in solution.time_steps()]
        return abs(solution.time(step) - time) <= 1e-6 * max(max(times) - min(times), 1e-12)
    except Exception:
        return False


def solution_disp_steps(solution, nids, out, chunk=CHUNK, time=None):
    """out["values"]: {nid: (ux, uy, uz)} of the solution open in Mecway, in the
    step at time (None: the last step); a node without a value is left out,
    and no values at all when the solution has no step at that time."""
    values = {}
    if solution is not None:
        step = solution_step(solution, time)
        if not step_matches(solution, step, time):
            out["values"] = values
            return
        for i, nid in enumerate(nids):
            row = [_value(solution, name, nid, step)
                   for name in ("displx", "disply", "displz")]
            if None not in row:
                values[nid] = tuple(float(v) for v in row)
            if (i + 1) % chunk == 0:
                yield
    out["values"] = values


def scale_values(values, size=ARROW_SIZE, sizes=None):
    """(values scaled to a largest vector of size, {"force", "moment": largest
    true value}). Forces and moments each have their own factor; sizes:
    another size for "force" or "moment"."""
    big_f = big_m = 0.0
    for v in values.values():
        big_f = max(big_f, math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2))
        big_m = max(big_m, math.sqrt(v[3] ** 2 + v[4] ** 2 + v[5] ** 2))
    sizes = sizes or {}
    k_f = sizes.get("force", size) / big_f if big_f > 0 else 0.0
    k_m = sizes.get("moment", size) / big_m if big_m > 0 else 0.0
    scaled = {}
    for nid, v in values.items():
        scaled[nid] = (v[0] * k_f, v[1] * k_f, v[2] * k_f,
                       v[3] * k_m, v[4] * k_m, v[5] * k_m)
    return scaled, {"force": big_f, "moment": big_m}


# ---- arrows: the solution ----------------------------------------------------------
def check_solution(mw, solution, nids):
    """None, or why the fields cannot be written: "no_solution", "stale",
    "mesh_differs", "numbering"."""
    if solution is None:
        return "no_solution"
    try:
        ids = ints(solution.all_nodes())
    except Exception:
        return "stale"
    if not ids:
        return "no_solution"
    # One value per node, by position: only numbers 1..n say which is which
    if sorted(ids) != list(range(1, len(ids) + 1)):
        return "numbering"
    known = set(ids)
    nids = list(nids)
    # every node must be there (a write puts node n at place n - 1); the
    # positions of a sample only, they cost a call each
    if any(nid not in known for nid in nids):
        return "mesh_differs"
    step = max(1, len(nids) // _CHECKED_NODES)
    try:
        for nid in nids[::step]:
            p = mw.node(nid)
            q = solution.node(nid)
            if _distance2((p.x, p.y, p.z), (q.x, q.y, q.z)) > _SAME_POSITION ** 2:
                return "mesh_differs"
    except Exception:
        return "stale"
    return None


def _value(solution, field, nid, step=None):
    """A name Mecway does not know is an empty field."""
    try:
        if step is None:
            return solution.node_value(field, nid)
        return solution.node_value(field, nid, time_step=step)
    except Exception:
        return None


def _same(a, b):
    return abs(a - b) <= _SAME_VALUE * max(abs(a), abs(b), 1e-12)


def field_state_steps(solution, field, ids, mine, out, chunk=CHUNK, step=None):
    """out[field]: "free", "own" (all its values are what this panel wrote) or
    "foreign". Every node is looked at: a field from CalculiX can be zero
    nearly everywhere, and after a new solve an old "own" no longer holds."""
    state = "free"
    for i, nid in enumerate(ids):
        value = _value(solution, field, nid, step)
        if value is not None:
            ours = mine.get(nid)
            if ours is None or not _same(ours, value):
                state = "foreign"
                break
            state = "own"
        if (i + 1) % chunk == 0:
            yield
    out[field] = state


def _set(solution, field, array, step):
    if step is None:
        solution.set_variable(field, array)
    else:
        solution.set_variable(field, array, time_step=step)


def _write_group(solution, fields, magnitude, offset, scaled, count, own, step=None):
    """The three fields of a vector and its magnitude (Mecway fills that one
    only from the first field it gets); what was written goes in own."""
    for k, field in enumerate(fields):
        array = [None] * count
        mine = {}
        for nid, v in scaled.items():
            array[nid - 1] = v[offset + k]
            mine[nid] = v[offset + k]
        _set(solution, field, array, step)
        own[field] = mine
    array = [None] * count
    for nid, v in scaled.items():
        array[nid - 1] = math.sqrt(v[offset] ** 2 + v[offset + 1] ** 2 +
                                   v[offset + 2] ** 2)
    _set(solution, magnitude, array, step)


def _clear_group(solution, fields, magnitude, count, own, step=None):
    """Empty the three fields of a vector and its magnitude: the arrows this
    panel wrote there earlier go."""
    for field in fields:
        _set(solution, field, [None] * count, step)
        own[field] = {}
    _set(solution, magnitude, [None] * count, step)


def arrow_steps(mw, solution, values, own, out, chunk=CHUNK, time=None):
    """
    Write the arrows, in the step nearest to time. values: {nid: six true
    values}. own: {field: {nid: value}} of earlier writes, kept by the caller;
    a vector with a field that
    already holds something else is skipped; so is a vector that is zero.
    A zero vector whose fields hold earlier arrows of this panel (none
    foreign) is cleared, so no old arrow stays next to the new ones (a solid
    has no nodal moments: per node after a resultant).
    out: "refused" (a code of check_solution), or "written", "cleared"
    (["force" or "moment"]), "skipped" ([("force" or "moment", reason)],
    reason "zero", "exists" or "clear_failed") and "largest".
    """
    out.update({"written": [], "skipped": [], "cleared": [], "refused": None})
    problem = check_solution(mw, solution, list(values))
    if problem:
        out["refused"] = problem
        return
    yield
    ids = sorted(ints(solution.all_nodes()))
    # The first write in a solution keeps its true values: Mecway's legend and
    # arrow length are fixed by it (measured). Later writes keep that length.
    largest = scale_values(values)[1]
    # The size of an earlier write, else this one's own; it is kept only once
    # the vector is really written
    sizes = dict(own.get("sizes") or {})
    for name in ("force", "moment"):
        if largest[name] > 0:
            sizes.setdefault(name, largest[name])
    scaled = scale_values(values, sizes=sizes)[0]
    out["largest"] = largest
    out["sizes"] = dict(sizes)
    step = solution_step(solution, time)
    if not step_matches(solution, step, time):
        out["refused"] = "no_step"
        return
    states = {}
    for field in FIELDS_FORCE + FIELDS_MOMENT:
        for _ in field_state_steps(solution, field, ids, own.get(field) or {},
                                   states, chunk, step):
            yield
    for name, fields, magnitude, offset in (
            ("force", FIELDS_FORCE, "externalforcemag", 0),
            ("moment", FIELDS_MOMENT, "reactionmommag", 3)):
        mine = [states[f] for f in fields]
        if largest[name] <= 0:
            if "foreign" not in mine and "own" in mine:
                try:
                    _clear_group(solution, fields, magnitude, len(ids), own, step)
                    out["cleared"].append(name)
                except Exception:
                    out["skipped"].append((name, "clear_failed"))
            else:
                out["skipped"].append((name, "zero"))
        elif any(states[f] == "foreign" for f in fields):
            out["skipped"].append((name, "exists"))
        else:
            _write_group(solution, fields, magnitude, offset, scaled, len(ids), own,
                         step)
            own.setdefault("sizes", {}).setdefault(name, sizes[name])
            out["written"].append(name)
        yield
    if out["written"] or out["cleared"]:
        # Show the solution: arrows do not exist in the model view
        try:
            mw.set_solution_active()
        except Exception:
            pass
        try:
            mw.display()
        except Exception:
            pass


# ---- the bridge --------------------------------------------------------------------
_SETTING = r'^\s*"{0}"\s*:\s*([rRuU]*)(["\'])(.*?)\2'
_FLAG = r'^\s*"{0}"\s*:\s*(True|False)'
_BRIDGE_FILE = "bridge_utils.py"
_ENTRY = re.compile(r"[^<>\"\r\n]*MecwayAsterBridgeMain\.py", re.I)


def model_stem(path):
    """The model name in file names of the bridge (its model_stem)."""
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    return stem or "model"


def _read_text(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _expand(path):
    return os.path.expandvars(os.path.expanduser(path))


def _script_dirs_of_mecway():
    """Bridge folders in Mecway's own list of scripts (Tools > Scripts)."""
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        return []
    pattern = os.path.join(root, "Mecway_Limited", "*", "*", "user.config")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    found = []
    for path in files:
        try:
            for entry in _ENTRY.findall(_read_text(path)):
                found.append(os.path.dirname(entry.strip()))
        except (IOError, OSError):
            pass
    return found


def read_bridge_settings(path):
    """{"work_dir", "beside_model", "exe"} from the bridge_utils.py at path (the
    bridge keeps its settings in that file). None for what is not found there."""
    text = _read_text(path)
    out = {}
    for key, name in (("work_dir", "work_dir"), ("exe", "exe_aster")):
        m = re.search(_SETTING.format(name), text, re.M)
        value = None
        if m:
            value = m.group(3)
            if "r" not in m.group(1).lower():
                value = value.replace("\\\\", "\\")
        out[key] = value
    m = re.search(_FLAG.format("work_dir_beside_model"), text, re.M)
    out["beside_model"] = (m.group(1) == "True") if m else None
    return out


def find_bridge(scripts_dir, model=u"", settings=None):
    """
    What the panel needs from the bridge: {"scripts", "work_dir", "exe",
    "problems"}. Looks in the setting "bridge_scripts", Mecway's list of
    scripts, and the folder next to this repository. What cannot be found or
    read stays None with a code in "problems" ("no_bridge", "unreadable",
    "no_aster"), so the panel can say so and a chosen folder still works.
    "exe_aster" in the settings wins over the bridge's own.
    """
    settings = settings or {}
    wanted = [settings.get("bridge_scripts")] + _script_dirs_of_mecway()
    wanted.append(os.path.join(os.path.dirname(os.path.dirname(scripts_dir)),
                               "MecwayAsterBridge", "Scripts"))
    out = {"scripts": None, "work_dir": None, "exe": None, "problems": []}
    values = None
    for folder in wanted:
        path = os.path.join(_expand(folder), _BRIDGE_FILE) if folder else None
        if path and os.path.isfile(path):
            out["scripts"] = os.path.dirname(path)
            try:
                values = read_bridge_settings(path)
            except (IOError, OSError, ValueError):
                values = {}
            break
    if out["scripts"] is None:
        out["problems"].append("no_bridge")
    elif values.get("work_dir") is None or values.get("exe") is None:
        out["problems"].append("unreadable")
    if values and values.get("work_dir") is not None:
        if values.get("beside_model") and model:
            out["work_dir"] = beside_model_folder(model)
        elif values["work_dir"]:
            out["work_dir"] = _expand(values["work_dir"])
        else:
            out["work_dir"] = os.path.join(os.path.dirname(out["scripts"]),
                                           "WorkDir")
    exe = settings.get("exe_aster") or (values or {}).get("exe")
    if exe:
        out["exe"] = _expand(exe)
    if not out["exe"] or not os.path.isfile(out["exe"]):
        if out["exe"] or out["scripts"]:
            out["problems"].append("no_aster")
    return out


def beside_model_folder(model):
    """The bridge's own folder next to a model: <model>_aster."""
    return os.path.join(os.path.dirname(os.path.abspath(model)),
                        model_stem(model) + "_aster")


def run_folders(model, bridge, choice="auto", other=u""):
    """The folders to look for runs in, for a choice of the panel: "auto",
    "model", "bridge" or "other"."""
    near = []
    if model and os.path.dirname(model):
        near = [os.path.dirname(os.path.abspath(model)),
                beside_model_folder(model)]
    work = [bridge["work_dir"]] if bridge and bridge.get("work_dir") else []
    chosen = {"auto": near + work, "model": near, "bridge": work,
              "other": [other] if other else []}.get(choice, [])
    out = []
    for folder in chosen:
        if folder not in out:
            out.append(folder)
    return out
