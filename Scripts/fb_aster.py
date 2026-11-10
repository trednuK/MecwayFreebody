# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_aster.py
# Responsibility: the short follow-up run on a Code-Aster base that the bridge
# kept: which runs there are, whether one can be used, starting it, and reading
# the forces on the cut nodes. The interfaces are in docs/design/contract.md,
# the measurements behind the run in docs/research (E8, E9).
#   find_runs()   manifests of a folder for one mesh, newest first
#   refuse()      None, or the reason a run cannot be used (REFUSE)
#   check_plan()  a selection against the run: refusals and warnings of
#                 shells, beams and connections (schema 2)
#   manifest_props()  what the run gave Code-Aster per element: model,
#                 section, beam axes per (half) cell, offset, large
#   start()       returns at once with a Job
#   Job           poll(), result(), error(), code(), stop()
#   check_solution()  whether the base is the run of the open solution
#
# The base is only read: "R base <folder> D 0". Everything else lives in an own
# folder per run under the scratch folder, also the temporary folder of
# run_aster (a follow-up run takes as much disk as the base), so that a stopped
# run leaves nothing behind. Only that own folder is removed.
#
# The numbers come back as JSON, with the values of a rank as one text of
# numbers: the panel reads it in IronPython, where a list of a million floats
# through json would take minutes.
#
# Compatible with IronPython 2.7.9 (Mecway) and CPython 3 (tests). No numpy
# here; the .comm text runs in the Python of Code-Aster, which has it.

import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

import fb_core
from fb_core import Refused

REFUSE = ("solver", "version", "fingerprint", "not_shared", "no_base", "schema",
          "deformation", "offset", "schema_old", "beam_warping", "beam_large_rotation",
          "not_shared_on_cut", "launcher_version", "run_version")

# Schema 1: solids only. Schema 2 (phase 4): shells, beams, mixed cuts.
SCHEMAS = (1, 2)
SCHEMA = 2
# Models of the components in schema 2
MODELS = ("DKT", "DST", "COQUE_3D", "POU_D_E", "POU_D_T", "POU_D_TG", "POU_D_T_GD",
          "BARRE", "CABLE", "3D")
# COEF_RIGI_DRZ when the manifest says null: Code-Aster's own default
DRZ_DEFAULT = 1e-5
SOLVERS = ("MECA_STATIQUE", "STAT_NON_LINE")
MANIFEST_SUFFIX = "_manifest.json"
SMALL = "PETIT"
MIXED = "MIXED"
LINEAR = "MECA_STATIQUE"
_TEXT = (type(""), type(u""))
# Keys a manifest of schema 1 cannot do without; "aster_version" must be there
# too, but may be null (refuse: run_version)
_REQUIRED = ("base", "cells", "concepts", "deformation",
             "fingerprint", "skin", "solver")
TIMEOUT = 1800.0
MEMORY_MB = 2048
# run_aster stops itself this long after our own timeout at the latest
_TIME_MARGIN = 120
# A node of the selection off the cuts counts in "rest" above the largest of:
# this fraction of the smallest resultant of the cuts, so that a light cut does
# not hide behind a heavy one; what the solver leaves as a residual, relative to
# the largest nodal force on the cuts (nonlinear: the convergence criterion, 1e-5
# by default in the bridge; measured 2e-7, linear 2e-12); and FLOOR, in N.
REST_TOL = 1e-4
REST_NOISE = {"MECA_STATIQUE": 1e-10, "STAT_NON_LINE": 1e-5}
REST_FLOOR = 1e-9
# Nodes of the rest that come back per step, largest first; with count
REST_TOP = 200
REST_WHERE = 20
# Displacements of a base and of the open solution differ by this much at most,
# relative to the largest one: more than single precision, less than a load step.
STALE_TOL = 1e-5
_CREATE_NO_WINDOW = 0x08000000
_CONCEPT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,23}\Z")
_FINGERPRINT_RE = re.compile(r'"fingerprint"\s*:\s*"([0-9a-f]+)"')
_MESSAGE_RE = re.compile(r"<(?:F|S|E|EXCEPTION)>")
# A version folder of the launcher, as the bridge reads it
_DOTTED_RE = re.compile(r"^\d+\.\d+(?:\.\d+)*$")

COMM = r"""POURSUITE(LANG='EN')
# Written by MecwayFreebody: forces of the rest of the model on the selection.
import json as fb_json
import numpy as fb_np


def fb_field(field, count):
    '''(nodes, 6) array of a nodal field; what a node does not have is 0.'''
    simple = field.toSimpleFieldOnNodes()
    values, mask = simple.toNumpy()
    names = list(simple.getComponents())
    out = fb_np.zeros((count, 6))
    for i, name in enumerate(("DX", "DY", "DZ", "DRX", "DRY", "DRZ")):
        if name in names:
            q = names.index(name)
            out[:, i] = fb_np.where(mask[:, q], values[:, q], 0.0)
    return out


def fb_text(values):
    return " ".join([repr(float(v)) for v in fb_np.asarray(values).ravel()])


with open("fort.32") as fb_f:
    fb_sel = fb_json.load(fb_f)
fb_res = @RESULT@
FBM = fb_res.getMesh()
# Skin cells of a fixed face are in the mesh, not in the model, and CALC_CHAMP
# stops on them (MODELISA6_96). Each list of the descriptor ends with a type.
fb_in_model = set()
for fb_list in fb_res.getModel().getFiniteElementDescriptor().getListOfGroupsOfElements():
    fb_in_model.update(fb_list[:-1])
# A selected cell is always in the model. If not, the list above does not mean
# what is assumed here, and dropping skin cells would give a wrong force.
if [i for i in fb_sel["FBZS"] if i not in fb_in_model]:
    raise ValueError("FB: selected cell not in the model descriptor")
fb_sel["FBZK"] = [i for i in fb_sel["FBZK"] if i in fb_in_model]
for fb_key in ("FBZS", "FBZR", "FBZK", "FBZL", "FBZP"):
    if fb_sel[fb_key]:
        FBM.setGroupOfCells(fb_key, [i - 1 for i in fb_sel[fb_key]])
fb_groups = [_F(NOM="FBNS", GROUP_MA="FBZS"), _F(NOM="FBNR", GROUP_MA="FBZR"),
             _F(NOM="FBNC", INTERSEC=("FBNS", "FBNR"))]
fb_mixed = bool(fb_sel["FBZL"]) and bool(fb_sel["FBZP"])
if fb_mixed:
    fb_groups += [_F(NOM="FBNL", GROUP_MA="FBZL"), _F(NOM="FBNP", GROUP_MA="FBZP")]
FBM = DEFI_GROUP(reuse=FBM, MAILLAGE=FBM, CREA_GROUP_NO=tuple(fb_groups))
fb_rs = CALC_CHAMP(RESULTAT=fb_res, GROUP_MA="FBZK", FORCE="REAC_NODA")
# Over the whole model: zero on a free node, the force of a support or coupling
# on any other. A new concept, whether or not the base has this field already.
fb_all_sides = CALC_CHAMP(RESULTAT=fb_res, FORCE="REAC_NODA")
fb_ranks = [int(k) for k in fb_res.getIndexes()]
fb_acc = fb_res.getAccessParameters()
fb_times = dict(zip(fb_acc["NUME_ORDRE"], fb_acc["INST"])) if "INST" in fb_acc else {}
fb_count = FBM.getNumberOfNodes()
fb_x = fb_np.asarray(FBM.getCoordinates().getValues(), dtype=float).reshape(-1, 3)
fb_cut = fb_np.array(sorted(int(i) for i in FBM.getNodes("FBNC")), dtype=int)
fb_all = fb_np.array(sorted(int(i) for i in FBM.getNodes("FBNS")), dtype=int)
fb_off = fb_np.setdiff1d(fb_all, fb_cut)
if not len(fb_cut):
    raise ValueError("FB: the selection has no cut nodes in the base")
# The lever of a nodal moment: the largest distance from the cut to a node of
# the selection, at least the extent of the cut, so never 0 (a one-layer
# selection, a beam cut at one node). In blocks: no n_sel x n_cut array at once.
# A scale for |m|, not a result: at most about 2000 cut nodes for it, so the
# time stays small on a large cut (the distance comes out a little larger).
fb_xc = fb_x[fb_cut][::max(1, len(fb_cut) // 2000)]
fb_xs = fb_x[fb_all]
fb_rows = max(1, 1000000 // len(fb_xc))
fb_far = 0.0
for fb_i in range(0, len(fb_xs), fb_rows):
    fb_d = ((fb_xs[fb_i:fb_i + fb_rows, None, :] - fb_xc[None, :, :]) ** 2).sum(axis=2)
    fb_far = max(fb_far, float(fb_d.min(axis=1).max()))
fb_lever = max(float(fb_np.sqrt(fb_far)),
               float(fb_np.sqrt(((fb_xc.max(axis=0) - fb_xc.min(axis=0)) ** 2).sum())))
if not fb_lever > 0:
    fb_lever = float(fb_np.sqrt(((fb_xs.max(axis=0) - fb_xs.min(axis=0)) ** 2).sum()))
if not fb_lever > 0:
    fb_lever = 1.0
# x + u only where every selected element on the node has large displacements
fb_large = fb_np.zeros(fb_count, dtype=bool)
if fb_mixed:
    fb_large[[int(i) for i in FBM.getNodes("FBNL")]] = True
    fb_large[[int(i) for i in FBM.getNodes("FBNP")]] = False
elif fb_sel["FBZL"]:
    fb_large[fb_all] = True
fb_out = {"format": 2, "ranks": fb_ranks, "lever": fb_lever,
          "times": [fb_times.get(k) for k in fb_ranks],
          "index": [int(i) for i in fb_cut], "xyz": fb_text(fb_x[fb_cut]),
          "large": [int(i) for i in fb_large[fb_cut]],
          "forces": {}, "disp": {}, "rest": {}, "total": {}}
for fb_k in fb_ranks:
    fb_r = fb_field(fb_rs.getField("REAC_NODA", fb_k), fb_count)
    fb_u = fb_field(fb_res.getField("DEPL", fb_k), fb_count)
    fb_pos = fb_x + fb_np.where(fb_large[:, None], fb_u[:, :3], 0.0)
    fb_out["forces"][str(fb_k)] = fb_text(fb_r[fb_cut])
    fb_out["disp"][str(fb_k)] = fb_text(fb_u[fb_cut, :3])
    fb_out["total"][str(fb_k)] = fb_text(
        fb_field(fb_all_sides.getField("REAC_NODA", fb_k), fb_count)[fb_cut])
    fb_loose = fb_r[fb_off]
    # force-equivalents: |F|, or a nodal moment (DRX..DRZ only) over the lever
    fb_size = fb_np.maximum(fb_np.sqrt((fb_loose[:, :3] ** 2).sum(axis=1)),
                            fb_np.sqrt((fb_loose[:, 3:] ** 2).sum(axis=1)) / fb_lever)
    fb_on_cut = float(fb_np.sqrt((fb_r[fb_cut, :3] ** 2).sum(axis=1)).max())
    fb_on_cut_m = float(fb_np.sqrt((fb_r[fb_cut, 3:] ** 2).sum(axis=1)).max())
    fb_sum = fb_np.concatenate((fb_loose[:, :3].sum(axis=0),
                                fb_np.cross(fb_pos[fb_off], fb_loose[:, :3]).sum(axis=0) +
                                fb_loose[:, 3:].sum(axis=0)))
    # the panel judges these: it knows which node belongs to which cut
    fb_out["rest"][str(fb_k)] = {
        "sum": [float(v) for v in fb_sum],
        "largest": float(fb_size.max()) if len(fb_size) else 0.0,
        "cut_largest": fb_on_cut, "cut_largest_moment": fb_on_cut_m,
        "top": [[float(fb_size[i])] + [float(v) for v in fb_x[fb_off[i]]]
                for i in fb_np.argsort(-fb_size)[:@REST_TOP@]]}
fb_out["done"] = True
with open("fort.33", "w") as fb_f:
    fb_json.dump(fb_out, fb_f)
FIN()
"""


# ---- manifests ----------------------------------------------------------------------
def _nano(value):
    """Coordinate in nm as an integer. Not through a format: "g" follows the
    Windows locale in IronPython, and round() differs between 2.7 and 3."""
    return int(math.floor(float(value) * 1e9 + 0.5))


def mesh_fingerprint(nodes, element_ids):
    """Hash of a model: node numbers, coordinates to 1 nm, element numbers.
    The same function as in the bridge (bridge_manifest.py)."""
    h = hashlib.sha256()
    for nid in sorted(nodes):
        xyz = nodes[nid]
        h.update("{0} {1} {2} {3}\n".format(
            int(nid), _nano(xyz[0]), _nano(xyz[1]), _nano(xyz[2])).encode("ascii"))
    for eid in sorted(element_ids):
        h.update("E{0}\n".format(int(eid)).encode("ascii"))
    return h.hexdigest()


def _read_text(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def find_runs(folder, fingerprint):
    """
    Manifests in folder with this fingerprint, newest first; every fingerprint
    with None. Each with "_folder" added. A file that cannot be read is no
    run. A manifest can be many MB: only those of this mesh are parsed.
    """
    try:
        names = os.listdir(folder)
    except (IOError, OSError):
        return []
    found = []
    for name in names:
        if not name.endswith(MANIFEST_SUFFIX):
            continue
        path = os.path.join(folder, name)
        try:
            text = _read_text(path)
            if fingerprint is not None:
                m = _FINGERPRINT_RE.search(text)
                if not m or m.group(1) != fingerprint:
                    continue
            man = json.loads(text)
            stamp = os.path.getmtime(path)
        except (IOError, OSError, ValueError):
            continue
        if isinstance(man, dict):
            man["_folder"] = folder
            run_id = man.get("run_id")
            found.append((run_id if isinstance(run_id, _TEXT) else "", stamp, name, man))
    found.sort(key=lambda item: item[:3], reverse=True)
    return [item[3] for item in found]


def _version_key(text):
    """'17.4', '17.4.0' and '17.04.00' are one version; None if it is none."""
    try:
        parts = [int(p) for p in str(text).strip().split(".")]
    except (TypeError, ValueError):
        return None
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or None


def version_from_launcher(path):
    """Version from ...\\<version>\\bin\\run_aster.bat, None for another path.
    As the bridge (bridge_version.aster_version_from_launcher): only a dotted
    number directly above bin."""
    parts = [p for p in re.split(r"[\\/]+", path or "") if p]
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower() == "bin":
            folder = parts[i - 1].strip()
            return folder if _DOTTED_RE.match(folder) else None
    return None


def _base_ok(folder, name):
    path = os.path.join(folder, name)
    return os.path.isdir(path) and bool(os.listdir(path))


def _concept_ok(concepts):
    """The name of the result: it goes into the .comm."""
    name = concepts.get("result") if isinstance(concepts, dict) else None
    return isinstance(name, _TEXT) and bool(_CONCEPT_RE.match(name))


def _bare_name(name):
    """A name in a manifest may not lead out of the folder."""
    try:
        return (bool(name) and not re.search(r"[\\/:]", name) and
                name not in (".", ".."))
    except TypeError:
        return False


def refuse(man, version, fingerprint=None, folder=None):
    """
    None, or the code from REFUSE why this run cannot be used. version: of the
    Code-Aster to run with. fingerprint and folder are optional: without them
    those checks use what find_runs left, or are skipped. man None: no run.
    """
    if not man:
        return "no_base"
    schema = man.get("schema")
    if schema not in SCHEMAS or isinstance(schema, bool):
        return "schema"
    for key in _REQUIRED:
        if man.get(key) is None:
            return "schema"
    if "aster_version" not in man:
        return "schema"
    if ("extra_nodes" not in man or not _bare_name(man["base"]) or
            not _concept_ok(man["concepts"])):
        return "schema"
    not_shared = man.get("not_shared")
    if schema == 2 and (not isinstance(man.get("components"), dict) or
                        not isinstance(not_shared or {}, dict) or
                        not isinstance(man.get("beam_axes") or {}, dict) or
                        not isinstance(man.get("excentrement") or {}, dict)):
        return "schema"
    if schema == 1 and not isinstance(not_shared or [], list):
        return "schema"
    if man["solver"] not in SOLVERS:
        return "solver"
    # A launcher of ours without a version in its path refuses every run: name
    # that setting first, not the run. null in the manifest: the bridge read
    # the version neither from the .mess nor from the path of its launcher.
    wanted = _version_key(version)
    if wanted is None:
        return "launcher_version"
    if man["aster_version"] is None:
        return "run_version"
    known = _version_key(man["aster_version"])
    if known is None or known != wanted:
        return "version"
    if fingerprint is not None and man["fingerprint"] != fingerprint:
        return "fingerprint"
    # Schema 1 names kinds only: refuse them all. Schema 2 names the nodes,
    # and check_plan() judges them against the selection.
    if schema == 1 and not_shared:
        return "offset" if "offset" in not_shared else "not_shared"
    where = folder if folder is not None else man.get("_folder")
    if where is not None and not _base_ok(where, man["base"]):
        return "no_base"
    return None


def split_deformation(man, mesh, eids):
    """
    (elements with large displacements, elements without), from what each
    component really computed with. A linear run is small everywhere, whatever
    the table says. An empty table: the run has one value. Refused if the table
    does not know a component, or if a component is MIXED: then its elements
    have no one shape to sum on.
    """
    if man.get("solver") == LINEAR:
        return [], list(eids)
    table = man.get("deformation_by_component") or {}
    if not table:
        general = man.get("deformation", SMALL)
        if general == MIXED:
            raise Refused("deformation", "the run has no one deformation")
        return ([], list(eids)) if general == SMALL else (list(eids), [])
    components = mesh.get("component")
    if not components:
        raise Refused("deformation", "the mesh has no components")
    large = []
    small = []
    for e in eids:
        value = table.get(components.get(e))
        if value is None or value == MIXED:
            raise Refused("deformation", "element {0}, component {1}: {2}".format(
                e, components.get(e), value))
        (small if value == SMALL else large).append(e)
    return large, small


# ---- schema 2: shells and beams --------------------------------------------------------
_SHELL_MODELS = ("DKT", "DST", "COQUE_3D")
_LINE_MODELS = ("POU_D_E", "POU_D_T", "POU_D_TG", "POU_D_T_GD", "BARRE", "CABLE")


def _form(man, component):
    """What a component computed with: PETIT for a linear run."""
    if man.get("solver") == LINEAR:
        return SMALL
    table = man.get("deformation_by_component") or {}
    if not table:
        return man.get("deformation", SMALL)
    return table.get(component)


def _rect(hy, hz, epy, epz):
    """A, IY, IZ, JX of a rectangle HY x HZ, hollow with walls EPY, EPZ. JX of
    a solid one by the series formula, of a tube by Bredt (approximate)."""
    a = hy * hz
    iy = hy * hz ** 3 / 12
    iz = hz * hy ** 3 / 12
    big = max(hy, hz)
    small = min(hy, hz)
    jx = big * small ** 3 * (1.0 / 3 - 0.21 * small / big * (1 - small ** 4 / (12 * big ** 4)))
    if epy and epz and 2 * epy < hy and 2 * epz < hz:
        iy_ = hy - 2 * epy
        iz_ = hz - 2 * epz
        a -= iy_ * iz_
        iy -= iy_ * iz_ ** 3 / 12
        iz -= iz_ * iy_ ** 3 / 12
        by = hy - epy
        bz = hz - epz
        jx = 4 * (by * bz) ** 2 / (2 * bz / epy + 2 * by / epz)
    return a, iy, iz, jx


def _section_end(values, suffix, shape):
    def get(key):
        v = values.get(key + suffix)
        return values.get(key) if v is None else v
    if get("A") is not None:
        return {"A": get("A"), "IY": get("IY"), "IZ": get("IZ"), "JX": get("JX"),
                "shape": shape}
    cable = get("AIRE") if get("AIRE") is not None else get("SECTION")
    if cable is not None:                            # CABLE
        return {"A": cable, "IY": None, "IZ": None, "JX": None, "shape": shape}
    hy = get("HY") or get("H")
    hz = get("HZ") or get("H")
    if hy and hz:
        a, iy, iz, jx = _rect(hy, hz, get("EPY") or get("EP"), get("EPZ") or get("EP"))
        return {"A": a, "IY": iy, "IZ": iz, "JX": jx, "shape": shape}
    r = get("R")
    if r:
        ep = get("EP")
        ri = r - ep if ep and ep < r else 0.0
        i = math.pi / 4 * (r ** 4 - ri ** 4)
        return {"A": math.pi * (r * r - ri * ri), "IY": i, "IZ": i, "JX": 2 * i,
                "shape": shape}
    return {"A": None, "IY": None, "IZ": None, "JX": None, "shape": shape}


_MEMBERS = {}


def _component(man, name, eid):
    """What the manifest says of the component of element eid: the truss
    part of a component that mixes beams and trusses for its trusses."""
    info = (man.get("components") or {}).get(name)
    if not isinstance(info, dict):
        return None
    part = info.get("truss_part")
    if isinstance(part, dict):
        # once per truss part; the part is kept with it, so its id stays its own
        known = _MEMBERS.get(id(part))
        if known is None or known[0] is not part:
            try:
                members = set(int(e) for e in part.get("elements") or ())
            except (TypeError, ValueError):
                members = set()
            if len(_MEMBERS) > 64:
                _MEMBERS.clear()
            known = _MEMBERS[id(part)] = (part, members)
        if eid in known[1]:
            return part
    return info


def section_values(section):
    """{"A", "IY", "IZ", "JX", "shape"} from cara/vale as Code-Aster got them
    (GENERALE, RECTANGLE, CERCLE, the SECTION of a cable). A tapered section
    (A1/A2, HY1/HY2, ...) also has "end2" with the values at node 2. A is None
    if the section cannot be read."""
    if not isinstance(section, dict):
        return {"A": None, "IY": None, "IZ": None, "JX": None, "shape": None}
    shape = section.get("shape")
    try:
        cara = [str(c).upper() for c in section.get("cara") or []]
        vale = [float(v) for v in section.get("vale") or []]
    except (TypeError, ValueError):
        cara = vale = []
    if len(cara) != len(vale):
        cara = vale = []
    values = dict(zip(cara, vale))
    out = _section_end(values, "1", shape)
    if [c for c in cara if c.endswith("2") and c[:-1] + "1" in values]:
        out["end2"] = _section_end(values, "2", shape)
    return out


def manifest_props(man, mesh, eids):
    """
    {eid: {"model", "truss", "section", "beam_axes", "offset", "large"}}: what
    the run gave Code-Aster and Mecway does not know (schema 2). The panel adds
    "E" and "thickness" from Mecway and passes it all to section_geometry.
    beam_axes per (half) cell: {"M": (x, y, z), "H": (x, y, z)}; offset is the
    EXCENTREMENT along the shell normal of the node order; large: the element
    computed with large displacements.
    """
    names = mesh.get("component") or {}
    axes = man.get("beam_axes") or {}
    offsets = man.get("excentrement") or {}
    out = {}
    for e in eids:
        name = names.get(e)
        info = _component(man, name, e) or {}
        model = info.get("model")
        p = {"model": model, "truss": model in fb_core.TRUSS_MODELS}
        if info.get("section"):
            p["section"] = section_values(info["section"])
        cells = {}
        for prefix in ("M", "H"):
            v = fb_core._axes_ok(axes.get("{0}{1}".format(prefix, e)) or ())
            if v:
                cells[prefix] = tuple(v)
        if cells:
            p["beam_axes"] = cells
        offset = offsets.get(str(e), offsets.get(e))
        if offset:
            p["offset"] = float(offset)
        form = _form(man, name)
        # a component the table does not know: assume large (global axes);
        # check_plan() and start() refuse it
        p["large"] = form != SMALL
        out[e] = p
    return out


def _node_sets(nodes):
    """A list of node numbers, or a list of such lists: the sets of nodes."""
    if not nodes:
        return []
    if isinstance(nodes[0], (list, tuple)):
        return [set(int(n) for n in s) for s in nodes]
    return [set(int(n) for n in nodes)]


def check_plan(man, plan, mesh):
    """
    {"warnings": [code], "drilling": [criterion]} of a selection with this
    run, or Refused: schema_old (shells or beams with a schema 1 run), schema
    (a component the manifest does not know), beam_warping, beam_large_rotation,
    offset, not_shared_on_cut, not_shared (a connection without nodes). A
    connection of not_shared that touches a cut node with all its nodes in the
    selection gives relation_on_cut; one elsewhere not_shared.
    """
    elements = mesh["elements"]
    inside = plan["inside"]
    special = [e for e in inside
               if fb_core.element_kind(elements[e][0]) in ("shell", "beam")]
    if man.get("schema") == 1:
        if special:
            raise Refused("schema_old", "the bridge of this run knows no shells or beams")
        return {"warnings": [], "drilling": []}
    names = mesh.get("component") or {}
    for e in special:
        name = names.get(e)
        info = _component(man, name, e)
        if info is None:
            raise Refused("schema", "element {0}: component {1} is not in the manifest".format(
                e, name))
        model = info.get("model")
        kind = fb_core.element_kind(elements[e][0])
        allowed = _SHELL_MODELS if kind == "shell" else _LINE_MODELS
        if model not in allowed:
            # a spring, a plane model, Q4G, ...: not measured
            raise Refused("shape", "element {0}, component {1}: model {2}".format(
                e, name, model))
        if _form(man, name) in (None, MIXED):
            raise Refused("deformation", "element {0}, component {1}: {2}".format(
                e, name, _form(man, name)))
        if model == "POU_D_TG" or info.get("has_warping"):
            raise Refused("beam_warping", "element {0}: a beam with warping".format(e))
        if model == "POU_D_T_GD" or (model.startswith("POU_") and
                                     _form(man, name) == "GROT_GDEP"):
            raise Refused("beam_large_rotation",
                          "element {0}: a beam with large rotations".format(e))
    in_nodes = set()
    shell_nodes = set()
    for e in inside:
        in_nodes.update(elements[e][1])
        if elements[e][0] in fb_core.SHELL_SHAPES:
            shell_nodes.update(elements[e][1])
    cut = set(plan["cut_nodes"])
    for e in plan["outside"]:
        shape, nids = elements[e]
        if shape in fb_core.SHELL_SHAPES and not cut.isdisjoint(nids):
            shell_nodes.update(nids)
    warnings = []
    drilling = []
    not_shared = man.get("not_shared") or {}
    for kind in sorted(not_shared):
        entry = not_shared[kind]
        # per connection where the bridge gives it, else one set for the kind
        nodes = None
        if isinstance(entry, dict):
            nodes = entry.get("groups")
            if (not isinstance(nodes, list) or not nodes or
                    not isinstance(nodes[0], list)):
                nodes = entry.get("nodes")
        if not isinstance(nodes, list):
            raise Refused("not_shared", "{0}: no nodes in the manifest".format(kind))
        try:
            sets = _node_sets(nodes)
        except (TypeError, ValueError):
            raise Refused("not_shared", "{0}: nodes cannot be read".format(kind))
        for s in sets:
            if kind == "offset" and not s.isdisjoint(in_nodes):
                raise Refused("offset", "an offset with own nodes in the selection")
            if not s.isdisjoint(cut):
                if not s.issubset(in_nodes):
                    raise Refused("not_shared_on_cut", "{0} on a cut node".format(kind))
                if "relation_on_cut" not in warnings:
                    warnings.append("relation_on_cut")
            elif "not_shared" not in warnings:
                warnings.append("not_shared")
            if not s.isdisjoint(shell_nodes) and "coupling" not in drilling:
                drilling.append("coupling")
    if drilling and "drilling" not in plan.get("warnings", ()):
        warnings.append("drilling")
    return {"warnings": warnings, "drilling": drilling}


# ---- files of a run ------------------------------------------------------------------
def _cell_positions(man):
    return dict((name, i + 1) for i, name in enumerate(man["cells"]))


def _cells_of(positions, eid):
    """File positions of the cells of an element."""
    first = positions.get("M{0}".format(eid))
    if first is None:
        raise Refused("schema", "element {0} is not in the manifest".format(eid))
    second = positions.get("H{0}".format(eid))
    return [first] if second is None else [first, second]


def build_selection(man, plan, mesh):
    """
    (text of sel.json, warnings). Groups by position in the mesh file. The
    rest holds the elements outside the selection, so a skin cell in the cut
    plane cannot enter by accident. Numbers only: no float, no locale.
    """
    inside = plan["inside"]
    chosen = set(inside)
    positions = _cell_positions(man)
    large, small = split_deformation(man, mesh, inside)
    warnings = []
    if large and small:
        warnings.append("mixed_deformation")
    cells = {"FBZS": [], "FBZR": [], "FBZL": [], "FBZP": []}
    for e in inside:
        cells["FBZS"] += _cells_of(positions, e)
    for e in plan["outside"]:
        cells["FBZR"] += _cells_of(positions, e)
    for e in large:
        cells["FBZL"] += _cells_of(positions, e)
    for e in small:
        cells["FBZP"] += _cells_of(positions, e)
    skin = []
    on_cut = False
    for name in sorted(man["skin"]):
        parents = [int(p[0]) for p in man["skin"][name]]
        selected = [e for e in parents if e in chosen]
        if not selected:
            continue
        if len(selected) != len(parents):
            on_cut = True
        if name not in positions:
            raise Refused("schema", "skin cell {0} is not in the manifest".format(name))
        skin.append(positions[name])
    cells["FBZK"] = cells["FBZS"] + skin
    if on_cut:
        warnings.append("skin_on_cut")
    parts = ['"{0}": [{1}]'.format(key, ",".join([str(i) for i in cells[key]]))
             for key in sorted(cells)]
    return "{" + ", ".join(parts) + "}", warnings


def comm_text(man):
    """The .comm of the follow-up run."""
    text = COMM.replace("@RESULT@", man["concepts"]["result"])
    return text.replace("@REST_TOP@", str(REST_TOP))


def _ansi(text):
    """text in the ANSI code page, or None if it does not fit. run_aster reads
    the .export with the default encoding of its Python."""
    try:
        data = text.encode("mbcs")
        return data if data.decode("mbcs") == text else None
    except LookupError:
        return text.encode("utf-8")        # not Windows: tests only
    except UnicodeError:
        return None


def _short_path(path):
    """The 8.3 name of a path, or None."""
    try:
        import ctypes
        api = ctypes.windll.kernel32.GetShortPathNameW
        api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        api.restype = ctypes.c_uint
        buf = ctypes.create_unicode_buffer(1024)
        size = api(path, buf, 1024)
        return buf.value if 0 < size < 1024 else None
    except Exception:
        return None


def usable_path(path):
    """A name for path that Code-Aster can handle: run_aster reads and writes
    paths in the ANSI code page. A name outside it goes through its 8.3 name.
    Refused ("path") if that does not exist either."""
    if _ansi(path) is not None:
        return path
    short = _short_path(path)
    if short and _ansi(short) is not None:
        return short
    raise Refused("path", "this folder name cannot be given to Code-Aster")


def export_path(path):
    """path as bytes for the .export, unquoted: run_aster joins what stands
    between the type and the D with spaces, single ones only."""
    data = _ansi(usable_path(path))
    if b"  " in data or data.strip() != data:
        raise Refused("path", "Code-Aster reads no double or outer spaces")
    return data


def export_bytes(base_path, seconds, memory):
    lines = ["P actions make_etude", "P time_limit {0}".format(int(seconds)),
             "P memory_limit {0}".format(int(memory)), "P mpi_nbcpu 1", "P ncpus 1",
             "P no-mpi true", "F comm run.comm D 1", "F mess run.mess R 6",
             "F libr sel.json D 32", "F libr result.json R 33"]
    text = "\n".join(lines) + "\n"
    return text.encode("ascii") + b"R base " + export_path(base_path) + b" D 0\n"


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _check_finite(values, what):
    for v in values:
        if v != v or v - v != 0:
            raise ValueError("{0} is not finite".format(what))


def decode_result(text, extra_nodes, warnings, seconds):
    """The result of the contract from the JSON of the run. "rest" and "on_cut"
    are only final after judge_rest()."""
    d = json.loads(text)
    ranks = d["ranks"]
    xyz = [float(v) for v in d["xyz"].split()]
    count = len(d["index"])
    if len(xyz) != 3 * count or len(d["large"]) != count:
        raise ValueError("cut nodes do not fit")
    _check_finite(xyz, "a position")
    nodes = [{"index": d["index"][i], "large": bool(d["large"][i]),
              "xyz": (xyz[3 * i], xyz[3 * i + 1], xyz[3 * i + 2])}
             for i in range(count)]
    forces = {}
    disp = {}
    rest = {}
    on_cut = {}
    for k in ranks:
        f = [float(v) for v in d["forces"][str(k)].split()]
        u = [float(v) for v in d["disp"][str(k)].split()]
        total = [float(v) for v in d["total"][str(k)].split()]
        if len(f) != 6 * count or len(u) != 3 * count or len(total) != 6 * count:
            raise ValueError("step {0} is not complete".format(k))
        _check_finite(total, "a force over all sides of step {0}".format(k))
        _check_finite(f, "a force of step {0}".format(k))
        _check_finite(u, "a displacement of step {0}".format(k))
        forces[k] = [tuple(f[6 * i:6 * i + 6]) for i in range(count)]
        disp[k] = [tuple(u[3 * i:3 * i + 3]) for i in range(count)]
        on_cut[k] = {"totals": [tuple(total[6 * i:6 * i + 6]) for i in range(count)]}
        r = d["rest"][str(k)]
        rest[k] = {"sum": tuple(r["sum"]), "largest": r["largest"],
                   "cut_largest": r["cut_largest"],
                   "cut_largest_moment": r.get("cut_largest_moment", 0.0), "top": r["top"],
                   "tolerance": None, "count": len(r["top"]),
                   "where": [tuple(q[1:4]) for q in r["top"][:REST_WHERE]]}
    lever = d.get("lever")
    if lever is not None:
        _check_finite((lever,), "the lever")
    if lever is None or not lever > 0:
        # a result of format 1: the extent of the cut nodes
        lever = 0.0
        if nodes:
            lever = math.sqrt(sum((max(n["xyz"][c] for n in nodes) -
                                   min(n["xyz"][c] for n in nodes)) ** 2 for c in range(3)))
        lever = lever if lever > 0 else 1.0
    return {"steps": [{"rank": k, "time": t} for k, t in zip(ranks, d["times"])],
            "nodes": nodes, "forces": forces, "disp": disp, "rest": rest, "on_cut": on_cut,
            "large": any(d["large"]), "extra_nodes": extra_nodes, "lever": float(lever),
            "warnings": warnings, "seconds": seconds}


def _size(f, lever):
    """A nodal force and moment as one force: max(|F|, |m| / lever)."""
    return max(math.sqrt(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]),
               math.sqrt(f[3] * f[3] + f[4] * f[4] + f[5] * f[5]) / lever)


def _judge_nodes(indices, totals, where, xyz, tol, lever):
    """What stands on these cut nodes: sum about the origin and nodes above
    tol, a nodal moment m counting as |m| / lever."""
    sizes = []
    for i in indices:
        sizes.append((_size(totals[i], lever), i))
    sizes.sort(reverse=True)
    hot = [i for size, i in sizes if size > tol]
    return {"sum": fb_core.resultant([where[i] for i in indices],
                                     [totals[i] for i in indices], (0.0, 0.0, 0.0)),
            "largest": sizes[0][0] if sizes else 0.0, "count": len(hot),
            "where": [xyz[i] for i in hot[:REST_WHERE]]}


def _judge_on_cut(result, rank, per_group, tol):
    """result["on_cut"][rank] from the force over all sides of each cut node."""
    entry = result["on_cut"][rank]
    totals = entry.pop("totals")
    where = fb_core.positions(result, rank)
    xyz = [record["xyz"] for record in result["nodes"]]
    lever = result.get("lever") or 1.0
    entry.update(_judge_nodes(range(len(totals)), totals, where, xyz, tol, lever))
    entry["tolerance"] = tol
    entry["cuts"] = dict((gid, _judge_nodes(indices, totals, where, xyz, tol, lever))
                         for gid, indices in per_group.items())


def judge_rest(result, per_group, noise):
    """
    Fill "tolerance", "count" and "where" of result["rest"], and result["on_cut"]
    with the same tolerance: see REST_TOL. It follows the smallest resultant of
    the cuts of that step, max(|F|, |M| / L) with M about the middle of its
    nodes and L result["lever"]; the noise of the solver counts on the largest
    nodal force and moment of the cuts likewise. per_group: {group id: [index]},
    noise: REST_NOISE of the solver. The count of "rest" stops at REST_TOP.
    """
    lever = result.get("lever") or 1.0
    for rank, rest in result["rest"].items():
        forces = result["forces"][rank]
        where = fb_core.positions(result, rank)
        smallest = None
        for indices in per_group.values():
            if not indices:
                continue
            pts = [where[i] for i in indices]
            middle = tuple(sum(p[c] for p in pts) / len(pts) for c in range(3))
            total = fb_core.resultant(pts, [forces[i] for i in indices], middle)
            size = _size(total, lever)
            if smallest is None or size < smallest:
                smallest = size
        largest = max(rest["cut_largest"], rest.get("cut_largest_moment", 0.0) / lever)
        tol = max(REST_TOL * (smallest or 0.0), noise * largest, REST_FLOOR)
        top = rest.pop("top", [])
        rest["tolerance"] = tol
        if rest.get("valid") is False:
            # a partial section (fb_nodecut): the rest is no equilibrium here
            rest["count"] = None
            rest["where"] = []
            _judge_on_cut(result, rank, per_group, tol)
            continue
        hot = [q for q in top if q[0] > tol]
        rest["count"] = len(hot)
        rest["where"] = [tuple(q[1:4]) for q in hot[:REST_WHERE]]
        _judge_on_cut(result, rank, per_group, tol)


def check_solution(result, rank, values, tol=STALE_TOL):
    """
    Whether this base is the run of the open solution: the same mesh with other
    loads has the same fingerprint, and would give old numbers without a word.
    values: {Mecway node: (ux, uy, uz)} from the active solution, for the same
    step; rank None is the last step of the result, to compare with the last step
    of the solution. Needs record["nid"], which Job.result() sets. Returns None
    if they agree within tol of the largest displacement, "stale" if they do not,
    "unknown" if it cannot be told: no such step, nodes without a value, or
    nothing that moved.
    """
    if rank is None:
        rank = result["steps"][-1]["rank"] if result["steps"] else None
    if rank not in result["disp"] or not values:
        return "unknown"
    worst = largest = 0.0
    seen = 0
    for record, u in zip(result["nodes"], result["disp"][rank]):
        nid = record.get("nid")
        if nid is None:
            continue                      # a midside node Mecway does not know
        v = values.get(nid)
        if v is None:
            return "unknown"
        try:
            _check_finite(v, "a value")
        except ValueError:
            return "unknown"
        seen += 1
        worst = max(worst, (u[0] - v[0]) ** 2 + (u[1] - v[1]) ** 2 + (u[2] - v[2]) ** 2)
        largest = max(largest, u[0] ** 2 + u[1] ** 2 + u[2] ** 2,
                      v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if not seen or largest == 0:
        return "unknown"
    return None if math.sqrt(worst) <= tol * math.sqrt(largest) else "stale"


def _complete(data):
    """The run wrote its whole result: the marker stands at the end."""
    return data[-40:].rstrip().endswith(b'"done": true}')


def _messages(mess_path, console_path):
    """The errors of a run, in short: for job.error()."""
    tail = []
    for path in (mess_path, console_path):
        try:
            text = _read_bytes(path).decode("utf-8", "replace")
        except (IOError, OSError):
            continue
        rows = [r.strip(" !|\t\r") for r in text.splitlines()]
        lines = [r for r in rows if _MESSAGE_RE.search(r)][:6]
        if lines:
            return " / ".join(lines)
        # no error lines: the tail of the first file with text, the .mess first
        tail = tail or [r for r in rows if r][-3:]
    return " / ".join(tail)


# ---- the job -----------------------------------------------------------------------------
class Job(object):
    """A follow-up run in the background; see start()."""

    def __init__(self, man, folder, plan, mesh, exe, work, timeout, memory, checked=None,
                 prepare=None):
        self._checked = checked or {"warnings": [], "drilling": []}
        self._prepare = prepare
        self._man = man
        self._folder = folder
        self._plan = plan
        self._mesh = mesh
        self._exe = exe
        self.work = work               # own folder of this run, removed at the end
        self._timeout = timeout
        self._memory = memory
        self._lock = threading.Lock()
        self._state = None
        self._error = None
        self._code = None
        self._process = None
        self._cancel = False
        self._data = None
        self._result = None
        self._warnings = []
        self._t0 = time.time()
        self._seconds = None
        self._deadline = self._t0 + timeout
        self._thread = threading.Thread(target=self._launch)
        self._thread.daemon = True

    def _launch(self):
        """Background: the checks over the whole mesh, the files, the process."""
        try:
            if mesh_fingerprint(self._mesh["nodes"], list(self._mesh["elements"]))                     != self._man["fingerprint"]:
                raise Refused("fingerprint", "the model is not the one of this run")
            text, warnings = build_selection(self._man, self._plan, self._mesh)
            self._warnings = warnings + [w for w in self._checked["warnings"]
                                         if w not in warnings]
            base = os.path.join(self._folder, self._man["base"])
            export = export_bytes(base, self._timeout + _TIME_MARGIN, self._memory)
            work = usable_path(self.work)
            temp = os.path.join(work, "tmp")
            os.makedirs(temp)
            _write(os.path.join(work, "sel.json"), text.encode("ascii"))
            _write(os.path.join(work, "run.comm"),
                   comm_text(self._man).encode("ascii"))
            _write(os.path.join(work, "run.export"), export)
            env = dict(os.environ)
            env["TEMP"] = env["TMP"] = temp
            command = 'cmd /c ""{0}" run.export > run.console 2>&1"'.format(self._exe)
            with self._lock:
                if self._state is None:
                    self._process = subprocess.Popen(
                        command, cwd=work, env=env,
                        creationflags=_CREATE_NO_WINDOW)
        except Refused as e:
            self._finish_locked(e.code, e.detail)
        except Exception as e:
            self._finish_locked("start", "{0}".format(e))
        with self._lock:
            # A stop during the preparation: the files came after its clean-up
            if self._state is not None and self._process is None:
                self._clean()

    def _finish_locked(self, code, text):
        with self._lock:
            self._finish(code, text)

    def _finish(self, code, text):
        """The end of a run that went wrong, or was stopped. Lock held."""
        if self._state is None:
            self._state = False
            self._code = code
            self._error = text
            self._seconds = time.time() - self._t0
            self._clean()

    def _clean(self):
        """Remove the own folder; files of killed processes can stay locked
        for a moment."""
        shutil.rmtree(self.work, True)
        if os.path.exists(self.work):
            t = threading.Thread(target=self._clean_later)
            t.daemon = True
            t.start()

    def _clean_later(self):
        for _ in range(120):
            time.sleep(0.5)
            shutil.rmtree(self.work, True)
            if not os.path.exists(self.work):
                return

    def _kill(self):
        """taskkill on the process this job started, with its children: its
        own tree, by number. Never by program name."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            killer = subprocess.Popen(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW)
            killer.communicate()
            for _ in range(40):
                if process.poll() is not None:
                    break
                time.sleep(0.05)
        except (IOError, OSError, ValueError):
            pass

    def _collect(self, exit_code):
        """The process has ended: take what it left, then clear the folder."""
        self._seconds = time.time() - self._t0
        path = os.path.join(self.work, "result.json")
        data = None
        if exit_code == 0 and os.path.isfile(path):
            data = _read_bytes(path)
        if data is not None and _complete(data):
            self._data = data
            self._state = True
            self._clean()
            return
        text = _messages(os.path.join(self.work, "run.mess"),
                         os.path.join(self.work, "run.console"))
        self._finish("run", "exit code {0}: {1}".format(exit_code, text))

    def poll(self):
        """None while running, else True or False. Never waits."""
        with self._lock:
            if self._state is None:
                if time.time() > self._deadline:
                    self._kill()
                    self._finish("timeout", "no result after {0:d} s".format(
                        int(self._timeout)))
                elif self._process is not None:
                    exit_code = self._process.poll()
                    if exit_code is not None:
                        self._collect(exit_code)
            return self._state

    def error(self):
        """What went wrong, as text; None if nothing did."""
        with self._lock:
            return None if self._error is None else "{0}: {1}".format(
                self._code, self._error)

    def code(self):
        """Why it went wrong, a short word: a code from REFUSE, or start, run,
        timeout, stopped."""
        with self._lock:
            return self._code

    def result(self):
        """The result of the contract. ValueError if the run left something
        that does not add up."""
        if self.poll() is not True:
            raise ValueError("no result: {0}".format(self.error()))
        with self._lock:
            if self._result is None:
                result = decode_result(
                    self._data.decode("ascii"), bool(self._man.get("extra_nodes")),
                    self._warnings, self._seconds)
                if self._prepare:
                    # e.g. fb_nodecut.filter_result: before the nodes are
                    # linked and judged; it may raise Refused("node_mismatch")
                    result = self._prepare(result)
                per_group = fb_core.link_nodes(self._plan, self._mesh, result)
                judge_rest(result, per_group,
                           REST_NOISE.get(self._man.get("solver"), REST_NOISE["STAT_NON_LINE"]))
                # None: Code-Aster's default, DRZ_DEFAULT; the panel says which
                result["coef_rigi_drz"] = self._man.get("coef_rigi_drz")
                result["drilling"] = sorted(set(self._plan.get("drilling") or []) |
                                            set(self._checked["drilling"]))
                self._result = result
                self._data = None
            return self._result

    def stop(self):
        """Kill this run, with its children. Nothing else."""
        with self._lock:
            if self._state is None:
                self._kill()
                self._finish("stopped", "stopped")


def start(man, folder, plan, mesh, exe, scratch=None, timeout=TIMEOUT, memory=None,
          prepare=None):
    """
    Start the run and return a Job at once; the work over the whole mesh
    happens in the background. scratch: folder under which the run gets an own
    new folder. Refused for what is known without looking at the mesh; a
    refusal that needs the mesh (fingerprint) ends the job: poll() False, with
    job.code(). prepare: a function result -> result that Job.result() applies
    right after reading the run, before link_nodes and judge_rest (the node
    cut: fb_nodecut.filter_result); a rest step with "valid" False is then not
    judged as an equilibrium (count None).
    """
    if man is None or man.get("schema") not in SCHEMAS:
        raise Refused("schema", "unknown manifest")
    # A launcher that does not tell its version is a version we do not know
    reason = refuse(man, version_from_launcher(exe), folder=folder)
    if reason:
        # the detail goes into the text of the panel (fb_gui.reason_text)
        detail = {"version": man.get("aster_version"), "launcher_version": exe}.get(
            reason, "this run cannot be used")
        raise Refused(reason, u"{0}".format(detail))
    if not plan["cut_nodes"]:
        raise Refused("no_cut", "the selection has no cut")
    if not os.path.isfile(exe):
        raise Refused("no_aster", "the Code-Aster launcher was not found")
    split_deformation(man, mesh, plan["inside"])
    checked = check_plan(man, plan, mesh)
    parent = scratch or tempfile.gettempdir()
    if not os.path.isdir(parent):
        os.makedirs(parent)
    work = tempfile.mkdtemp(prefix="fb_", dir=parent)
    limit = max(memory or man.get("memory_limit") or MEMORY_MB, MEMORY_MB)
    job = Job(man, folder, plan, mesh, exe, work, float(timeout), limit, checked, prepare)
    job._thread.start()
    return job
