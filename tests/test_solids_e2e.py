# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_solids_e2e.py
# fb_aster and fb_core with real Code-Aster on every solid shape, against exact
# statics with two cuts: tet, wedge, pyramid, mixed and distorted meshes, a
# staircase selection, a selection that touches through an edge and a corner, two
# materials, supports and a tie in the selection, about 20 000 elements. Models
# and statics are in solids_models.py. A test without its base is skipped.
#
# Bases: python -B tests/solids_build.py <bridge> <folder> [tags]. A base takes
# 130 MB and 4 s, k_lin 0.6 GB and 70 s, k_nl 1.2 GB and 7 minutes; a follow-up run
# copies its base. The test looks in FB_SOLIDS (folders, separated by ;) and in
# WorkDir\solids of this checkout and of the checkouts above it. Run:
#   python -B -m unittest tests.test_solids_e2e -v
# In Mecway too, with the base k_lin or k_nl: FB_RUN_MECWAY=1, a hidden
# mecway.exe <model> script <file>; never while Mecway is open.
#

import json
import os
import shutil
import subprocess
import sys
import tempfile
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

EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4",
                   "bin", "run_aster.bat")
VERSION = "17.4"
MECWAY = os.environ.get("FB_MECWAY", r"C:\Program Files\Mecway\mecway.exe")
BAR = 1e-10               # as test_aster_e2e
BAR_STEP = 1e-5           # a step of a nonlinear run: RESI_GLOB_RELA 1e-5
BAR_REST = 1e-6           # N, off the cuts of a clean model
BIG_TIMEOUT = 1800.0
REPORT = {}


def candidates():
    out = [p for p in os.environ.get("FB_SOLIDS", "").split(";") if p]
    here = ROOT
    while True:
        out.append(os.path.join(here, "WorkDir", "solids"))
        up = os.path.dirname(here)
        if up == here:
            return out
        here = up


def find_case(tag):
    for root in candidates():
        folder = os.path.join(root, tag)
        if os.path.isdir(folder) and any(n.endswith("_manifest.json") for n in os.listdir(folder)):
            return root
    return None


def available(tag):
    return (sm is not None and os.path.isfile(EXE) and find_case(tag) is not None)


def needs(*tags):
    return unittest.skipUnless(all(available(t) for t in tags),
                               "no base of {0}, Code-Aster or numpy".format(" ".join(tags)))


CASES = {}
RUNS = {}


def case(tag):
    """(model, mesh, folder, manifest, scratch) of a base."""
    if tag not in CASES:
        root = find_case(tag)
        folder = os.path.join(root, tag)
        model = sm.MODELS[tag](tag)
        mesh = model.mesh()
        fp = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
        runs = fb_aster.find_runs(folder, fp)
        assert runs, "the base of {0} is of another mesh".format(tag)
        CASES[tag] = (model, mesh, folder, runs[0], os.path.join(root, "scratch"))
    return CASES[tag]


def wait(job, seconds=300.0):
    end = time.time() + seconds
    while job.poll() is None:
        if time.time() > end:
            job.stop()
            break
        time.sleep(0.02)
    return job


def follow(tag, chosen=None, name="middle", man=None, timeout=300.0):
    """(plan, result, per group) of one follow-up run, once per selection."""
    key = (tag, name)
    if key in RUNS:
        return RUNS[key]
    model, mesh, folder, manifest, scratch = case(tag)
    plan = fb_core.plan_cuts(mesh, model.chosen if chosen is None else chosen)
    job = wait(fb_aster.start(man or manifest, folder, plan, mesh, EXE, scratch,
                              timeout=timeout), timeout + 30)
    assert job.poll(), "{0}: {1}".format(tag, job.error())
    result = job.result()
    RUNS[key] = (plan, result, fb_core.assign_nodes(plan, mesh, result))
    return RUNS[key]


def past_the_refusal(tag):
    """The manifest without what it says about the tie: only to get at the numbers."""
    return dict(case(tag)[3], not_shared=[])


def post(tag):
    """All nodes of a base; the order of the model is checked."""
    model, mesh, folder, man, scratch = case(tag)
    with np.load(os.path.join(folder, "post.npz")) as z:
        out = dict((k, z[k]) for k in z.files)
    assert np.abs(out["xyz"][:len(model.xyz)] - np.array(model.xyz)).max() < 1e-9
    return out


def point_of(mesh, group):
    """The moment point: from the nodes only, not from fb_core's centroid."""
    return tuple(np.mean([mesh["nodes"][n] for n in group["nodes"]], axis=0))


def sum_of(result, per, gid, point, rank):
    pos = fb_core.positions(result, rank)
    idx = per[gid]
    return np.array(fb_core.resultant([pos[i] for i in idx],
                                      [result["forces"][rank][i] for i in idx], point))


def relative(s, fx, mx, length, load=0.0):
    """As E9, with the size of the model's loads as a floor: a cut that carries
    only some weight would measure the rounding of the large forces."""
    size = max(np.linalg.norm(fx), np.linalg.norm(mx) / length, load)
    return (float(np.linalg.norm(s[:3] - fx) / size),
            float(np.linalg.norm(s[3:] - mx) / (size * length)))


def errors(tag, plan, result, per, rank=1, ref=None, extra=None):
    """Worst (eF, eM) over the cuts, against the statics behind each cut."""
    model, mesh, folder, man, scratch = case(tag)
    ref = ref or sm.Reference(model)
    behind = sm.behind(model, plan)
    assert behind is not None, "no statics per cut"
    load = np.linalg.norm(ref.of(list(model.elements), (0.0, 0.0, 0.0))[0])
    worst = (0.0, 0.0)
    for g in plan["groups"]:
        point = point_of(mesh, g)
        how, eids = behind[g["id"]]
        fx, mx = ref.of(eids, point)
        if how == "others":
            fx, mx = -fx, -mx
        ef, em = relative(sum_of(result, per, g["id"], point, rank), fx, mx, sm.L, load)
        worst = (max(worst[0], ef), max(worst[1], em))
    return worst


def note(name, **values):
    REPORT[name] = values
    sys.stderr.write("{0}: {1}\n".format(name, " ".join(
        "{0}={1}".format(k, "{0:.2e}".format(v) if isinstance(v, float) else v)
        for k, v in sorted(values.items()))))


def tearDownModule():
    for root in candidates():
        if os.path.isdir(root) and os.environ.get("FB_SOLIDS_REPORT"):
            with open(os.environ["FB_SOLIDS_REPORT"], "a") as f:
                f.write(json.dumps(REPORT, sort_keys=True) + "\n")
            break


def stairs(model):
    """Both cuts jump in y and z: the cut is no plane."""
    nx, ny, nz = model.size
    out = []
    for (i, j, k), es in model.cells.items():
        low = nx // 4 + (k >= nz // 2) + (j >= ny // 2)
        high = 3 * nx // 4 + (k >= nz // 2) - (j >= ny // 2)
        if low <= i < high:
            out += es
    return out


def jagged(model):
    """Element by element along a slanted line: a cut with single tets in it."""
    out = []
    for e, (shape, nids) in model.elements.items():
        n = fb_core._FAMILIES[shape][2]
        c = np.mean([model.ref[q - 1] for q in nids[:n]], axis=0)
        if sm.L / 4 < c[0] + .4 * c[2] < 3 * sm.L / 4:
            out.append(e)
    return out


def layer(model, i):
    return [q for (a, b, c), es in model.cells.items() if a == i for q in es]


class Base(unittest.TestCase):
    def clean(self, tag, plan, result, per, name, bar=BAR, ref=None, rank=1, groups=2):
        self.assertEqual(len(plan["groups"]), groups)
        ef, em = errors(tag, plan, result, per, rank, ref)
        rest = result["rest"][rank]
        note(name, eF=ef, eM=em, rest=float(rest["largest"]), cut=float(rest["cut_largest"]),
             count=rest["count"], s=round(result["seconds"], 1), nodes=len(result["nodes"]),
             warn=",".join(plan["warnings"] + result["warnings"]))
        self.assertEqual(rest["count"], 0)
        self.assertTrue(rest["largest"] < BAR_REST, rest["largest"])
        self.assertTrue(ef < bar and em < bar, "eF {0:.1e} eM {1:.1e}".format(ef, em))


# ---- 1. shapes -------------------------------------------------------------------------------
class Shapes(Base):
    pass


def _shape_test(tag):
    @needs(tag)
    def test(self):
        plan, result, per = follow(tag)
        model = case(tag)[0]
        self.clean(tag, plan, result, per, tag)
        # hand: a rectangle of the bar, centred
        mesh = case(tag)[1]
        for g, x, n in zip(plan["groups"], (sm.L / 4, 3 * sm.L / 4), (-1.0, 1.0)):
            geo = fb_core.section_geometry(mesh, g)
            self.assertAlmostEqual(geo["area"] / (sm.B * sm.H), 1.0, 10)
            for a, b in zip(geo["centroid"], (x, sm.B / 2, sm.H / 2)):
                self.assertAlmostEqual(a, b, 10)
            self.assertTrue(geo["planar"])
            self.assertAlmostEqual(geo["normal"][0], n, 10)
    return test


SHAPE_TAGS = ("a_tet4", "a_tet10", "a_w6z", "a_w6x", "a_w15z", "a_w15x", "a_pyr5", "a_pyr13",
              "b_hw", "b_mix", "b_mix2", "b_mixlq")
for _t in SHAPE_TAGS:
    setattr(Shapes, "test_" + _t, _shape_test(_t))


class Controls(Base):
    """These tests can fail: what the safeguards see on the new shapes."""

    @needs("a_pyr13")
    def test_wrong_sign(self):
        plan, result, per = follow("a_pyr13")
        flipped = dict(result, forces={1: [tuple(-v for v in f) for f in result["forces"][1]]})
        ef, em = errors("a_pyr13", plan, flipped, per)
        note("control sign", eF=ef, eM=em)
        self.assertTrue(ef > 1.0)

    def missing_skin(self, tag):
        model, mesh, folder, man, scratch = case(tag)
        plan, result, per = follow(tag, name="no skin", man=dict(man, skin={}))
        ef, em = errors(tag, plan, result, per)
        rest = result["rest"][1]
        note("control skin " + tag, eF=ef, eM=em, count=rest["count"], rest=float(rest["largest"]))
        self.assertTrue(ef > 1e-3 and rest["count"] > 0 and rest["where"])

    @needs("a_w15z")
    def test_missing_skin_wedge(self):
        self.missing_skin("a_w15z")

    @needs("a_tet10")
    def test_missing_skin_tet(self):
        self.missing_skin("a_tet10")

    def missing_midsides(self, tag):
        plan, result, per = follow(tag)
        mesh = case(tag)[1]
        corners = set()
        for e in plan["inside"]:
            shape, nids = mesh["elements"][e]
            corners.update(nids[:fb_core._FAMILIES[shape][2]])
        where = set(tuple(np.round(mesh["nodes"][n], 9)) for n in corners)
        keep = [i for i, r in enumerate(result["nodes"]) if tuple(np.round(r["xyz"], 9)) in where]
        self.assertTrue(0 < len(keep) < len(result["nodes"]))
        self.assertRaises(Refused, fb_core.assign_nodes, plan, mesh,
                          dict(result, nodes=[result["nodes"][i] for i in keep]))
        kept = set(keep)
        ef, em = errors(tag, plan, result, dict((g, [i for i in idx if i in kept])
                                                for g, idx in per.items()))
        note("control midside " + tag, eF=ef, eM=em)
        self.assertTrue(ef > 0.1)

    @needs("a_tet10")
    def test_missing_midsides_tet(self):
        self.missing_midsides("a_tet10")

    @needs("a_pyr13")
    def test_missing_midsides_pyramid(self):
        self.missing_midsides("a_pyr13")

    @needs("a_w15x")
    def test_missing_midsides_wedge(self):
        self.missing_midsides("a_w15x")


class Linequad(Base):
    @needs("b_mixlq")
    def test_extra_nodes_on_triangles_and_quads(self):
        plan, result, per = follow("b_mixlq")
        self.assertTrue(result["extra_nodes"])
        self.assertTrue(len(result["nodes"]) > len(plan["cut_nodes"]))


class SmallSelections(Base):
    @needs("a_hex8")
    def test_one_layer_all_nodes_on_a_cut(self):
        # no node off the cuts: the check has nothing to look at, and must not break
        model = case("a_hex8")[0]
        plan, result, per = follow("a_hex8", layer(model, 6), "layer")
        self.clean("a_hex8", plan, result, per, "layer_hex8")

    @needs("a_hex20")
    def test_one_layer_quadratic(self):
        model = case("a_hex20")[0]
        plan, result, per = follow("a_hex20", layer(model, 6), "layer")
        self.clean("a_hex20", plan, result, per, "layer_hex20")


# ---- 1b. distorted ---------------------------------------------------------------------------
class Distorted(Base):
    def curved(self, tag):
        plan, result, per = follow(tag)
        self.clean(tag, plan, result, per, tag)
        for g in plan["groups"]:
            self.assertFalse(fb_core.section_geometry(case(tag)[1], g)["planar"])

    @needs("d_hex8")
    def test_hex8(self):
        self.curved("d_hex8")

    @needs("d_hex20")
    def test_hex20(self):
        self.curved("d_hex20")

    @needs("d_tet10")
    def test_tet10(self):
        self.curved("d_tet10")

    def planar(self, tag, area, centroids, normals):
        plan, result, per = follow(tag)
        self.clean(tag, plan, result, per, tag)
        mesh = case(tag)[1]
        for g, c, n in zip(plan["groups"], centroids, normals):
            geo = fb_core.section_geometry(mesh, g)
            self.assertTrue(geo["planar"])
            self.assertAlmostEqual(geo["area"] / area, 1.0, 9)
            for a, b in zip(geo["centroid"], c):
                self.assertAlmostEqual(a, b, 9)
            for a, b in zip(geo["normal"], n):
                self.assertAlmostEqual(a, b, 9)
            # the same cut in its own axes: N along the normal
            s = sum_of(result, per, g["id"], geo["centroid"], 1)
            local = fb_core.to_axes(tuple(s), geo["axes"])
            self.assertAlmostEqual(local[0], float(np.dot(s[:3], n)), 8)
            self.assertAlmostEqual(np.dot(geo["axes"][1], n), 0.0, 9)
            self.assertAlmostEqual(np.dot(geo["axes"][2], n), 0.0, 9)
            self.assertAlmostEqual(
                np.linalg.norm(local[:3]), np.linalg.norm(s[:3]), 7)

    @needs("d_trap")
    def test_trapezoid_section(self):
        a = sm.ALPHA
        yc = sm.B / 2 * (1 + a * a / 12)
        zc = sm.H / 2 + a * sm.H / 12
        self.planar("d_trap", sm.B * sm.H,
                    [(sm.L / 4, yc, zc), (3 * sm.L / 4, yc, zc)],
                    [(-1., 0., 0.), (1., 0., 0.)])

    @needs("d_obl")
    def test_oblique_plane(self):
        self.oblique("d_obl")

    @needs("d_oblw")
    def test_oblique_plane_wedges(self):
        self.oblique("d_oblw")

    def oblique(self, tag):
        a, b = sm.SHEAR
        size = np.sqrt(1 + a * a + b * b)
        n = np.array((1.0, -a, -b)) / size
        self.planar(tag, sm.B * sm.H * size,
                    [(sm.L / 4, sm.B / 2, sm.H / 2), (3 * sm.L / 4, sm.B / 2, sm.H / 2)],
                    [tuple(-n), tuple(n)])


# ---- 2. staircase, edge and corner ------------------------------------------------------------
class Staircase(Base):
    def stairs_on(self, tag):
        model = case(tag)[0]
        plan, result, per = follow(tag, stairs(model), "stairs")
        self.clean(tag, plan, result, per, "stairs " + tag)
        for g in plan["groups"]:
            geo = fb_core.section_geometry(case(tag)[1], g)
            self.assertFalse(geo["planar"])
            # bar section plus the steps: faces in x and steps in y, z
            self.assertTrue(geo["area"] > sm.B * sm.H)

    @needs("a_hex20")
    def test_hex20(self):
        self.stairs_on("a_hex20")

    @needs("a_tet10")
    def test_tet10(self):
        self.stairs_on("a_tet10")

    @needs("c_lq")
    def test_hex8_line_quad(self):
        self.stairs_on("c_lq")

    @needs("b_mix2")
    def test_mixed(self):
        self.stairs_on("b_mix2")

    def jag(self, tag):
        model = case(tag)[0]
        plan, result, per = follow(tag, jagged(model), "jag")
        self.clean(tag, plan, result, per, "jag " + tag)

    @needs("a_tet10")
    def test_jagged_tet10(self):
        self.jag("a_tet10")

    @needs("a_tet4")
    def test_jagged_tet4(self):
        self.jag("a_tet4")

    @needs("a_pyr13")
    def test_jagged_pyr13(self):
        self.jag("a_pyr13")

    @needs("a_w15x")
    def test_jagged_wedge15(self):
        self.jag("a_w15x")


class EdgeAndCorner(unittest.TestCase):
    def on(self, tag, nodes):
        model, mesh = case(tag)[:2]
        plan, result, per = follow(tag)
        self.assertEqual(len(plan["cut_nodes"]), nodes)
        self.assertTrue("edge_contact" in plan["warnings"])
        self.assertEqual(sum(len(g["faces"]) for g in plan["groups"]), 0)
        self.assertEqual(len(plan["groups"]), 2)
        for g in plan["groups"]:
            geo = fb_core.section_geometry(mesh, g)
            self.assertEqual(geo["area"], 0.0)
        # the sum of the groups against the loads on the block: determinate
        fx, mx = sm.Reference(model).of(plan["inside"], (0.0, 0.0, 0.0))
        s = sum(sum_of(result, per, g["id"], (0.0, 0.0, 0.0), 1) for g in plan["groups"])
        ef, em = relative(s, -fx, -mx, sm.L)
        rest = result["rest"][1]
        note("edge " + tag, eF=ef, eM=em, rest=float(rest["largest"]), count=rest["count"],
             cut=float(rest["cut_largest"]), nodes=len(result["nodes"]),
             groups=[len(g["nodes"]) for g in plan["groups"]])
        self.assertTrue(ef < BAR and em < BAR)
        self.assertEqual(rest["count"], 0)
        # relative to the forces at a corner a check passes easily: absolute too
        self.assertTrue(rest["largest"] < BAR_REST)

    @needs("e_hex8")
    def test_hex8(self):
        self.on("e_hex8", 4)

    @needs("e_hex20")
    def test_hex20(self):
        self.on("e_hex20", 6)

    @needs("e_lq")
    def test_line_quad(self):
        # the midside nodes of the line come from the run, not from the plan
        self.on("e_lq", 4)
        plan, result, per = follow("e_lq")
        self.assertEqual(len(result["nodes"]), 6)


# ---- 3. two materials -------------------------------------------------------------------------
class TwoMaterials(Base):
    @needs("f_two")
    def test_centroid_by_hand_forces_by_statics(self):
        model, mesh = case("f_two")[:2]
        plan, result, per = follow("f_two")
        self.clean("f_two", plan, result, per, "f_two")
        e1 = sm.STEEL["E"]
        e2 = sm.ALU["E"]
        zc = sm.H / 4 * (e1 + 3 * e2) / (e1 + e2)
        for g, x in zip(plan["groups"], (sm.L / 4, 3 * sm.L / 4)):
            geo = fb_core.section_geometry(mesh, g, model.props())
            self.assertEqual(geo["warnings"], [])
            for a, b in zip(geo["centroid"], (x, sm.B / 2, zc)):
                self.assertAlmostEqual(a, b, 11)
            self.assertAlmostEqual(geo["area"] / (sm.B * sm.H), 1.0, 11)
            plain = fb_core.section_geometry(mesh, g)
            self.assertAlmostEqual(plain["centroid"][2], sm.H / 2, 11)
            note("centroid f_two group %d" % g["id"], z=float(geo["centroid"][2]), hand=zc)

    @needs("f_two")
    def test_props_of_one_material_only(self):
        model, mesh = case("f_two")[:2]
        plan = fb_core.plan_cuts(mesh, model.chosen)
        props = dict((e, p) for e, p in model.props().items() if model.component[e] == "B")
        geo = fb_core.section_geometry(mesh, plan["groups"][0], props)
        self.assertEqual(geo["warnings"], ["E_missing"])
        self.assertAlmostEqual(geo["centroid"][2], sm.H / 2, 11)


# ---- 5. what the cut does not see -------------------------------------------------------------
ORIGIN = (0.0, 0.0, 0.0)


class Supports(unittest.TestCase):
    @needs("f_two")
    def test_selection_with_the_clamp(self):
        # The skin cells of a fixed face are in the mesh and in manifest["skin"],
        # not in the model: CALC_CHAMP would stop on them (MODELISA6_96).
        model, mesh, folder, man, scratch = case("f_two")
        chosen = [q for (i, j, k), es in model.cells.items() if i < 3 for q in es]
        plan = fb_core.plan_cuts(mesh, chosen)
        job = wait(fb_aster.start(man, folder, plan, mesh, EXE, scratch))
        self.assertTrue(job.poll(), job.error())
        result = job.result()
        per = fb_core.assign_nodes(plan, mesh, result)
        # the clamp is in the selection: off the cuts, so in rest, by statics
        self.assertEqual(len(plan["groups"]), 1)
        self.assertTrue(result["rest"][1]["count"] > 0)
        self.assertEqual(result["on_cut"][1]["count"], 0)
        ref = sm.Reference(model)
        fx, mx = ref.of(list(model.elements), ORIGIN)
        rest = result["rest"][1]
        er = relative(np.array(rest["sum"]), -fx, -mx, sm.L)
        note("clamp in the selection", erest_F=er[0], erest_M=er[1], count=rest["count"])
        self.assertTrue(er[0] < BAR and er[1] < BAR)

    @needs("g_strip")
    def test_selection_holds_the_support(self):
        # both ends free: every cut by statics, the support by the sum of all loads
        model, mesh = case("g_strip")[:2]
        plan, result, per = follow("g_strip")
        ef, em = errors("g_strip", plan, result, per)
        rest = result["rest"][1]
        fx, mx = sm.Reference(model).of(list(model.elements), ORIGIN)
        er, emr = relative(np.array(rest["sum"]), -fx, -mx, sm.L)
        note("support inside", eF=ef, eM=em, rest_F=[round(v, 3) for v in rest["sum"][:3]],
             statics=[round(float(v), 3) for v in -fx], erest_F=er, erest_M=emr,
             count=rest["count"], largest=float(rest["largest"]), cut=float(rest["cut_largest"]))
        self.assertTrue(ef < BAR and em < BAR)
        self.assertTrue(er < BAR and emr < BAR)
        self.assertTrue(rest["count"] > 0)
        strip = [mesh["nodes"][n] for n in model.fixed_nodes()]
        for w in rest["where"]:
            self.assertTrue(min(np.linalg.norm(np.array(w) - p) for p in strip) < 1e-9)

    @needs("g_strip")
    def test_cut_through_the_support(self):
        model, mesh = case("g_strip")[:2]
        chosen = [q for (i, j, k), es in model.cells.items() if 6 <= i < 9 for q in es]
        plan, result, per = follow("g_strip", chosen, "half")
        other = [e for e in model.elements if e not in set(chosen)]
        plan2, result2, per2 = follow("g_strip", other, "other half")
        rest = result["rest"][1]
        ref = sm.Reference(model)
        fx, mx = ref.of(plan["inside"], ORIGIN)
        total = sum(sum_of(result, per, g["id"], ORIGIN, 1) for g in plan["groups"])
        # the selection in equilibrium: what is on its cuts, the rest of it, the loads
        e_all = relative(total + np.array(rest["sum"]), -fx, -mx, sm.L)
        # the second cut is free: statics
        tip_group = [g for g in plan["groups"] if mesh["nodes"][g["nodes"][0]][0] > .14][0]
        tip_part = [e for e in other if np.mean([mesh["nodes"][n][0] for n in mesh["elements"][e][1]]) > .14]
        fy, my = ref.of(tip_part, ORIGIN)
        e_tip = relative(sum_of(result, per, tip_group["id"], ORIGIN, 1), fy, my, sm.L)
        # the first cut: at a node on the support the reaction of that node is
        # in the sum of both sides together
        z = post("g_strip")
        reaction = z["R_1"]
        fixed = model.fixed_nodes()
        on_both = [n for n in plan["cut_nodes"] if n in fixed]
        by_xyz = dict((tuple(np.round(r["xyz"], 9)), i) for i, r in enumerate(result["nodes"]))
        by_xyz2 = dict((tuple(np.round(r["xyz"], 9)), i) for i, r in enumerate(result2["nodes"]))
        worst = 0.0
        hidden = np.zeros(3)
        for n in on_both:
            key = tuple(np.round(mesh["nodes"][n], 9))
            both = (np.array(result["forces"][1][by_xyz[key]][:3]) +
                    np.array(result2["forces"][1][by_xyz2[key]][:3]))
            worst = max(worst, float(np.linalg.norm(both - reaction[n - 1])))
            hidden += reaction[n - 1]
        cut = [g for g in plan["groups"] if g is not tip_group][0]
        section = sum_of(result, per, cut["id"], ORIGIN, 1)
        self.assertTrue(e_tip[0] < BAR and e_tip[1] < BAR)
        note("cut through support", identity_F=e_all[0], identity_M=e_all[1], on_both=len(on_both),
             free_cut_eF=e_tip[0], free_cut_eM=e_tip[1],
             count=rest["count"], largest=float(rest["largest"]),
             cut=float(rest["cut_largest"]), node_reaction_error=worst,
             reaction_on_cut=[round(float(v), 2) for v in hidden],
             cut_sum=[round(float(v), 2) for v in section[:3]],
             rest_sum=[round(v, 2) for v in rest["sum"][:3]])
        self.assertTrue(e_all[0] < BAR and e_all[1] < BAR)
        self.assertTrue(worst < 1e-6)
        self.assertTrue(rest["count"] > 0, "the rest check must show the support")
        # the same reaction, now seen by the run itself
        shown = result["on_cut"][1]
        self.assertEqual(shown["count"], len(on_both))
        self.assertTrue(np.linalg.norm(np.array(shown["sum"][:3]) - hidden) < 1e-6)
        self.assertEqual(shown["cuts"][cut["id"]]["count"], len(on_both))
        self.assertEqual(shown["cuts"][tip_group["id"]]["count"], 0)

    @needs("g_line")
    def test_measure_support_on_the_cut_nodes_only(self):
        # what is measured: the check of the selection holds, the force of the
        # support stands in the sum of the cut
        model, mesh = case("g_line")[:2]
        plan, result, per = follow("g_line")
        z = post("g_line")
        line = model.nodesets["LINE"]
        reaction = sum(z["R_1"][n - 1] for n in line)
        ref = sm.Reference(model)
        fx, mx = ref.of(plan["inside"], ORIGIN)
        total = sum(sum_of(result, per, g["id"], ORIGIN, 1) for g in plan["groups"])
        e = relative(total + np.array(result["rest"][1]["sum"]), -fx, -mx, sm.L)
        rest = result["rest"][1]
        cut = [g for g in plan["groups"] if set(line) <= set(g["nodes"])][0]
        section = sum_of(result, per, cut["id"], ORIGIN, 1)
        note("support on cut only", identity_F=e[0], identity_M=e[1], count=rest["count"],
             largest=float(rest["largest"]), cut=float(rest["cut_largest"]),
             reaction=[round(float(v), 2) for v in reaction],
             cut_sum=[round(float(v), 2) for v in section[:3]],
             warnings=result["warnings"] + plan["warnings"])
        self.assertTrue(e[0] < BAR and e[1] < BAR)
        self.assertTrue(np.linalg.norm(reaction) > 10.0)

    @needs("g_line")
    def test_support_on_the_cut_nodes_is_shown(self):
        # The sum agrees with statics of the other side, and holds the force of
        # a support on its nodes. rest looks only at nodes off the cuts; on_cut
        # looks at the force over all sides of each cut node.
        model, mesh = case("g_line")[:2]
        plan, result, per = follow("g_line")
        z = post("g_line")
        line = model.nodesets["LINE"]
        reaction = sum(z["R_1"][n - 1] for n in line)
        shown = result["on_cut"][1]
        note("support on cut shown", count=shown["count"], largest=float(shown["largest"]),
             tolerance=float(shown["tolerance"]), F=[round(v, 2) for v in shown["sum"][:3]],
             reaction=[round(float(v), 2) for v in reaction])
        self.assertEqual(shown["count"], len(line))
        self.assertTrue(np.linalg.norm(np.array(shown["sum"][:3]) - reaction) < 1e-6)
        cut = [g for g in plan["groups"] if set(line) <= set(g["nodes"])][0]
        self.assertEqual(shown["cuts"][cut["id"]]["count"], len(line))
        for g in plan["groups"]:
            if g is not cut:
                self.assertEqual(shown["cuts"][g["id"]]["count"], 0)
        spots = [mesh["nodes"][n] for n in line]
        for w in shown["where"]:
            self.assertTrue(min(np.linalg.norm(np.array(w) - p) for p in spots) < 1e-9)


class Tie(unittest.TestCase):
    def clear(self):
        # past the refusal, and past the skin of the tie faces
        return past_the_refusal("g_tie")

    @needs("g_tie")
    def test_refused_by_the_manifest(self):
        model, mesh, folder, man, scratch = case("g_tie")
        self.assertEqual(man["not_shared"], ["bonded"])
        self.assertEqual(fb_aster.refuse(man, VERSION, folder=folder), "not_shared")
        plan = fb_core.plan_cuts(mesh, model.part_two)
        with self.assertRaises(Refused) as caught:
            fb_aster.start(man, folder, plan, mesh, EXE, scratch)
        self.assertEqual(caught.exception.code, "not_shared")

    @needs("g_tie")
    def test_tie_next_to_the_selection(self):
        # without the refusal: one cut in the part, the tie on the other side
        model, mesh = case("g_tie")[:2]
        chosen = [q for (i, j, k), es in model.cells.items() if 6 <= i < 9 for q in es]
        plan, result, per = follow("g_tie", chosen, "beside", man=self.clear())
        self.assertEqual(len(plan["groups"]), 1)
        ref = sm.Reference(model)
        rest = result["rest"][1]
        fx, mx = ref.of(list(model.part_two), ORIGIN)
        er = relative(np.array(rest["sum"]), -fx, -mx, sm.L)
        ef, em = errors("g_tie", plan, result, per, ref=ref)
        note("tie beside", eF=ef, eM=em, erest_F=er[0], erest_M=er[1], count=rest["count"],
             largest=float(rest["largest"]), cut=float(rest["cut_largest"]),
             rest_F=[round(v, 2) for v in rest["sum"][:3]],
             statics=[round(float(v), 2) for v in -fx],
             where_x=sorted(set(round(p[0], 6) for p in rest["where"])))
        self.assertTrue(rest["count"] > 0)
        self.assertEqual(set(round(p[0], 9) for p in rest["where"]), set([round(sm.L / 2, 9)]))
        self.assertTrue(er[0] < 1e-7 and er[1] < 1e-7)

    @needs("g_tie")
    def test_tie_inside_the_selection(self):
        # two cuts by statics; the tie balances itself: the sum says nothing,
        # count and largest do
        model, mesh = case("g_tie")[:2]
        chosen = [q for (i, j, k), es in model.cells.items() if 3 <= i < 9 for q in es]
        plan, result, per = follow("g_tie", chosen, "across", man=self.clear())
        ef, em = errors("g_tie", plan, result, per)
        rest = result["rest"][1]
        note("tie inside", eF=ef, eM=em, count=rest["count"], largest=float(rest["largest"]),
             cut=float(rest["cut_largest"]), rest_F=[round(v, 6) for v in rest["sum"][:3]])
        self.assertTrue(ef < 1e-7 and em < 1e-7)
        self.assertTrue(rest["count"] > 0)


class Nodal(unittest.TestCase):
    @needs("g_nodal")
    def test_force_on_a_node_counts_on_the_selection(self):
        # measured: REAC_NODA takes a force on a node of the selection off at
        # that node, also on a cut. So rest does not show it, and it stays out
        # of the cut sum: a load on the selection, whichever side it was meant.
        model, mesh = case("g_nodal")[:2]
        plan, result, per = follow("g_nodal")
        ref = sm.Reference(model)
        rest = result["rest"][1]
        nodes = model.nodesets["N_IN"] + model.nodesets["N_CUT"]
        behind = sm.behind(model, plan)
        worst = (0.0, 0.0)
        for g in plan["groups"]:
            point = point_of(mesh, g)
            how, eids = behind[g["id"]]
            fx, mx = ref.of(eids, point, nodes if how == "others" else [])
            if how == "others":
                fx, mx = -fx, -mx
            e = relative(sum_of(result, per, g["id"], point, 1), fx, mx, sm.L)
            worst = (max(worst[0], e[0]), max(worst[1], e[1]))
        note("nodal force", eF=worst[0], eM=worst[1], count=rest["count"],
             largest=float(rest["largest"]))
        self.assertTrue(worst[0] < BAR and worst[1] < BAR)
        self.assertEqual(rest["count"], 0)


class Pressure(Base):
    @needs("g_press")
    def test_linear(self):
        plan, result, per = follow("g_press")
        self.clean("g_press", plan, result, per, "g_press")

    @needs("n_press")
    def test_nonlinear_follower(self):
        model = case("n_press")[0]
        plan, result, per = follow("n_press")
        z = post("n_press")
        self.assertTrue(result["large"])
        self.assertEqual([s["rank"] for s in result["steps"]], [0, 1, 2, 3, 4])
        for rank in (1, 2, 3, 4):
            u = z["U_%d" % rank][:len(model.xyz)]
            ef, em = errors("n_press", plan, result, per, rank, sm.Reference(model, u=u))
            note("n_press rank %d" % rank, eF=ef, eM=em, count=result["rest"][rank]["count"],
                 rest=float(result["rest"][rank]["largest"]), u=float(np.abs(u).max()))
            self.assertEqual(result["rest"][rank]["count"], 0)
            self.assertTrue(ef < BAR_STEP and em < BAR_STEP)


# ---- 4. about 20 000 elements -----------------------------------------------------------------
class Large(unittest.TestCase):
    def run_one(self, tag, ranks):
        model, mesh = case(tag)[:2]
        t0 = time.time()
        plan = fb_core.plan_cuts(mesh, model.chosen)
        t1 = time.time()
        p, result, per = follow(tag, timeout=BIG_TIMEOUT)
        z = post(tag) if model.steps else None
        for rank in ranks:
            u = z["U_%d" % rank][:len(model.xyz)] if model.steps else None
            ref = sm.Reference(model, u=u)
            ef, em = errors(tag, plan, result, per, rank, ref)
            rest = result["rest"][rank]
            note("%s rank %d" % (tag, rank), eF=ef, eM=em, rest=float(rest["largest"]),
                 count=rest["count"], fb_aster_s=round(result["seconds"], 1),
                 plan_s=round(t1 - t0, 2), elements=len(mesh["elements"]),
                 cut_nodes=len(result["nodes"]))
            self.assertEqual(rest["count"], 0)
            self.assertTrue(ef < BAR_STEP and em < BAR_STEP)

    @needs("k_lin")
    def test_linear(self):
        self.run_one("k_lin", [1])

    @needs("k_nl")
    def test_nonlinear(self):
        self.run_one("k_nl", [1, 2, 3, 4])


def mecway_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mecway.exe"], capture_output=True,
                         text=True).stdout
    return "mecway.exe" in out.lower()


def big_tags():
    """The large bases on this PC, or those of FB_IPY_TAGS: two bases and the
    temporary copy of a follow-up run together take over 3 GB."""
    wanted = os.environ.get("FB_IPY_TAGS", "k_lin k_nl").split()
    return [t for t in wanted if available(t)]


@unittest.skipUnless(os.environ.get("FB_RUN_MECWAY") == "1" and os.path.isfile(MECWAY) and
                     big_tags(), "only on request, with a base")
class InMecway(unittest.TestCase):
    def test_read_in_ironpython(self):
        import test_core_ipy as ipy
        self.assertFalse(mecway_running(), "Mecway is running: not now")
        tags = big_tags()
        # Same mesh for both: Mecway opens the linear model
        model = sm.MODELS["k_lin"]("k_lin")
        mesh = model.mesh()
        work = tempfile.mkdtemp(prefix="fbk_", dir=find_case(tags[0]))
        self.addCleanup(shutil.rmtree, work, True)
        out = os.path.join(work, "out.json")
        chosen = os.path.join(work, "chosen.json")
        with open(chosen, "w") as f:
            json.dump(model.chosen, f)
        cfg = {"out": out, "scripts": os.path.join(ROOT, "Scripts"), "exe": EXE, "version": VERSION,
               "chosen": chosen, "scratch": work, "limit": BIG_TIMEOUT,
               "folders": dict((t, case(t)[2]) for t in tags)}
        cfg_path = os.path.join(work, "cfg.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        script = os.path.join(work, "inner.py")
        shutil.copy(os.path.join(HERE, "ipy_solids.py"), script)
        model_path = os.path.join(work, "k_lin.liml")
        model.write(model_path)
        ipy.TIMEOUT = 2 * BIG_TIMEOUT
        seconds, consoles = ipy.run_hidden(model_path, script, cfg_path)
        self.assertTrue(os.path.isfile(out), "no result of the script")
        with open(out) as f:
            d = json.load(f)
        keep = os.environ.get("FB_IPY_REPORT")
        if keep:
            shutil.copy(out, keep)
        note("mecway", seconds=round(seconds, 1), consoles=consoles,
             mesh=dict((k, v) for k, v in d.get("mesh", {}).items() if k != "fingerprint"))
        self.assertEqual(consoles, 0)
        self.assertEqual(dict((k, v) for k, v in d.items() if k.endswith("_error")), {})
        self.assertTrue(d.get("done"))
        self.assertEqual(d["mesh"]["fingerprint"], case(tags[0])[3]["fingerprint"])
        for tag in tags:
            run = d["run_" + tag]
            note("ironpython " + tag, **dict((k, v) for k, v in run.items() if k != "sums"))
            plan, result, per = follow(tag, timeout=BIG_TIMEOUT)
            self.assertTrue(run["sums"])
            for name, values in run["sums"].items():
                rank, gid = [int(q) for q in name.split("_")]
                point = point_of(mesh, [g for g in plan["groups"] if g["id"] == gid][0])
                want = sum_of(result, per, gid, point, rank)
                for a, b in zip(values, want):
                    self.assertTrue(abs(a - b) <= 1e-6 * max(1.0, abs(b)), (name, a, b))


if __name__ == "__main__":
    unittest.main()
