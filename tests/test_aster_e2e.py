# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_aster_e2e.py
# The whole chain with real Code-Aster on the self-made models of experiment
# E9: fb_core and fb_aster on a base of the bridge, against the statics of
# docs/research/experiments/e9_chain.py, two cuts, every stored step. With one
# negative control per safeguard. Skipped when there is no base, no Code-Aster
# or no numpy.
#
# Bases: run e9_chain.py with FB_WORK set to a folder and FB_BRIDGE to the
# bridge, and with the same two variables "python tests/test_aster_e2e.py build
# [c_other] [c_nover]" (no tag: c_other). c_other: the mesh of c_lin with other
# loads, the test of a stale base. c_nover: c_lin once more, run by the bridge
# through a launcher of its own without <version>\bin in its path, so that the
# bridge writes "aster_version": null (the test of the version refusals).
# Code-Aster runs without a window: the bridge run with the cpus of the bridge
# settings, the follow-up run of e7_lib that writes post.npz with E7_NCPUS
# (default 1 by "build", 4 by e9_chain.py alone; the numbers do not depend on it).
# The test looks in FB_E2E (folders, separated by ;) and in the folders WorkDir\e2e
# and WorkDir\exp9b of this checkout and of the checkouts above it.
# Run: python -m unittest tests.test_aster_e2e -v

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "Scripts"))
import fb_aster
import fb_core
from fb_core import Refused

try:
    import numpy as np
except ImportError:
    np = None

EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "code_aster", "v2025", "17.4",
                   "bin", "run_aster.bat")
VERSION = "17.4"
# (shape, tip load, load next to the first cut), as e9_chain.case
CASES = {"c_lin": ("hex20", (2000., 500., -1000.), (0., 0., -300.)),
         "c_other": ("hex20", (2400., 600., -1200.), (0., 0., -360.)),
         "c_nover": ("hex20", (2000., 500., -1000.), (0., 0., -300.)),
         "c_lq": ("hex8", (2000., 500., -1000.), (0., 0., -300.)),
         "c_nl": ("hex20", (0., 0., -12000.), (0., 0., -300.))}
BAR = 1e-10                # the numbers of E9, with some room
# A step of a nonlinear run is as good as its convergence: RESI_GLOB_RELA 1e-5
BAR_STEP = 1e-5


def candidates():
    out = [p for p in os.environ.get("FB_E2E", "").split(";") if p]
    here = ROOT
    while True:
        out += [os.path.join(here, "WorkDir", n) for n in ("e2e", "exp9b")]
        up = os.path.dirname(here)
        if up == here:
            return out
        here = up


def find_case(tag):
    for root in candidates():
        folder = os.path.join(root, tag)
        if not (os.path.isfile(os.path.join(root, tag + ".liml")) and os.path.isdir(folder)):
            continue
        names = [n for n in os.listdir(folder) if n.endswith("_manifest.json")]
        if names and os.path.isfile(os.path.join(folder, "post.npz")):
            with open(os.path.join(folder, names[0]), "rb") as f:
                if b'"extra_nodes"' in f.read():
                    return root
    return None


def read_liml(path):
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    nodes = {}
    for a, b, c, d in re.findall(r'<node nid="(\d+)" x="([^"]+)" y="([^"]+)" z="([^"]+)"', text):
        nodes[int(a)] = (float(b), float(c), float(d))
    elements = {}
    for a, b, c in re.findall(r'<elem eid="(\d+)" shape="(\w+)" nodes="([^"]+)"', text):
        elements[int(a)] = (b, [int(q) for q in c.split()])
    return {"nodes": nodes, "elements": elements,
            "component": dict((e, "P") for e in elements)}


def load_statics():
    """The functions of e9_chain: importing it asks for two folders."""
    experiments = os.path.join(ROOT, "docs", "research", "experiments")
    if experiments not in sys.path:
        sys.path.insert(0, experiments)
    os.environ.setdefault("FB_WORK", tempfile.gettempdir())
    os.environ.setdefault("FB_BRIDGE", tempfile.gettempdir())
    # read by e7_lib on its first import: the cpus of its follow-up runs
    os.environ.setdefault("E7_NCPUS", "1")
    import e9_chain
    return e9_chain


def base_state(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        out[name] = (os.stat(path).st_mtime_ns, h.hexdigest())
    return out


class Case(object):
    """A model of E9, the selection of E9, and one follow-up run."""

    def __init__(self, tag):
        self.tag = tag
        self.root = find_case(tag)
        self.folder = os.path.join(self.root, tag)
        self.mesh = read_liml(os.path.join(self.root, tag + ".liml"))
        self.e9 = load_statics()
        fp = fb_aster.mesh_fingerprint(self.mesh["nodes"], list(self.mesh["elements"]))
        self.man = fb_aster.find_runs(self.folder, fp)[0]
        e = self.e9
        shape, self.f_tip, self.f_side = CASES[tag]
        self.m = e.Mesh()
        d = (e.L / e.NX, e.B / e.NY, e.H / e.NZ)
        cells = {}
        for i in range(e.NX):
            for j in range(e.NY):
                for k in range(e.NZ):
                    cells[(i, j, k)] = e.add_cell(self.m, (i * d[0], j * d[1], k * d[2]), d, shape)
        self.chosen = [q for (i, j, k), es in cells.items()
                       if e.NX // 4 <= i < 3 * e.NX // 4 for q in es]
        self.tip = e.boundary_faces(self.m, lambda c: abs(c[0] - e.L) < 1e-9)
        self.side = e.boundary_faces(
            self.m, lambda c: abs(c[2] - e.H) < 1e-9 and e.L / 4 < c[0] < e.L / 4 + 2 * d[0])
        self.plan = fb_core.plan_cuts(self.mesh, self.chosen)
        self.geo = dict((g["id"], fb_core.section_geometry(self.mesh, g))
                        for g in self.plan["groups"])
        with np.load(os.path.join(self.folder, "post.npz")) as z:
            self.displacement = dict((k, z[k]) for k in z.files if k.startswith("U_"))

    def run(self, man=None, mesh=None, scratch=None):
        job = fb_aster.start(man or self.man, self.folder, self.plan, mesh or self.mesh, EXE,
                             scratch, timeout=300.0)
        while job.poll() is None:
            time.sleep(0.05)
        return job

    def statics(self, group, rank, time_of_step, large=None):
        """(F, M) of the rest on the selection about the centroid, by statics."""
        e = self.e9
        geo = self.geo[group]
        xc = geo["centroid"][0]
        point = np.array(geo["centroid"])
        sign = -1.0 if xc < e.L / 2 else 1.0
        right = [q for q in self.m.elems
                 if np.mean([self.m.X(n)[0] for n in self.m.elems[q][1]]) > xc]
        loads = [(self.tip, self.f_tip)]
        if xc < e.L / 2:
            loads.append((self.side, self.f_side))
        u = self.displacement["U_%d" % rank][:, :3]
        if not (self.man["deformation"] != "PETIT" if large is None else large):
            u = 0 * u
        f, m = e.statics(self.m, right, loads, point, u)
        return sign * f, sign * m

    def errors(self, result, per, group, rank, on=None, forces=None):
        e = self.e9
        step = [s for s in result["steps"] if s["rank"] == rank][0]
        fx, mx = self.statics(group, rank, step["time"])
        idx = per[group]
        pos = on if on is not None else fb_core.positions(result, rank)
        f = forces if forces is not None else result["forces"][rank]
        s = fb_core.resultant([pos[i] for i in idx], [f[i] for i in idx],
                              self.geo[group]["centroid"])
        ef = np.linalg.norm(np.array(s[:3]) - fx) / max(np.linalg.norm(fx), np.linalg.norm(mx) / e.L)
        em = np.linalg.norm(np.array(s[3:]) - mx) / max(np.linalg.norm(mx), np.linalg.norm(fx) * e.L)
        return float(ef), float(em)


CACHE = {}


def good(tag):
    """(case, result, per group), one real run per model."""
    if tag not in CACHE:
        case = Case(tag)
        job = case.run()
        assert job.poll(), job.error()
        result = job.result()
        CACHE[tag] = (case, result, fb_core.assign_nodes(case.plan, case.mesh, result))
    return CACHE[tag]


def solution_of(case, rank):
    """{nid: (ux, uy, uz)} as a solution in Mecway has them: single precision,
    all nodes. The node numbers of these models are their positions + 1."""
    u = case.displacement["U_%d" % rank]
    return dict((i + 1, tuple(float(v) for v in np.float32(u[i, :3]))) for i in range(len(u)))


def available(tag):
    return np is not None and os.path.isfile(EXE) and find_case(tag) is not None


def report(text):
    sys.stderr.write(text + "\n")


@unittest.skipUnless(available("c_lin"), "no base of c_lin, Code-Aster or numpy")
class Linear(unittest.TestCase):
    def test_statics(self):
        case, result, per = good("c_lin")
        self.assertTrue(fb_aster.refuse(case.man, VERSION, folder=case.folder) is None)
        self.assertEqual(len(result["nodes"]), 242)
        self.assertEqual(result["warnings"], [])
        self.assertEqual([len(per[1]), len(per[2])], [121, 121])
        for g in (1, 2):
            ef, em = case.errors(result, per, g, 1)
            report("c_lin cut %d: eF %.1e eM %.1e, %.1f s" % (g, ef, em, result["seconds"]))
            self.assertTrue(ef < BAR and em < BAR)
        rest = result["rest"][1]
        report("c_lin rest %.1e N of %.0f N, on the cut %.1e N" % (
            rest["largest"], rest["cut_largest"], result["on_cut"][1]["largest"]))
        self.assertEqual(rest["count"], 0)
        self.assertEqual(result["on_cut"][1]["count"], 0)

    def test_tension_is_positive(self):
        # the tip pulls with 2000 N along x, both cuts feel that as tension
        case, result, per = good("c_lin")
        pos = fb_core.positions(result, 1)
        for g in (1, 2):
            idx = per[g]
            s = fb_core.resultant([pos[i] for i in idx], [result["forces"][1][i] for i in idx],
                                  case.geo[g]["centroid"])
            self.assertAlmostEqual(fb_core.to_axes(s, case.geo[g]["axes"])[0], 2000.0, 6)

    def test_section_of_the_cut(self):
        case, result, per = good("c_lin")
        g = case.geo[1]
        self.assertAlmostEqual(g["area"], 8e-4, 15)
        self.assertTrue(g["planar"])
        self.assertAlmostEqual(g["normal"][0], -1.0, 12)
        self.assertAlmostEqual(case.geo[2]["normal"][0], 1.0, 12)

    def test_shift_is_a_new_sum(self):
        case, result, per = good("c_lin")
        pos = fb_core.positions(result, 1)
        idx = per[1]
        c = case.geo[1]["centroid"]
        p = (0.01, 0.02, -0.03)
        a = fb_core.shift(fb_core.resultant([pos[i] for i in idx],
                                            [result["forces"][1][i] for i in idx], c), c, p)
        b = fb_core.resultant([pos[i] for i in idx], [result["forces"][1][i] for i in idx], p)
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, 8)

    def test_control_wrong_sign(self):
        case, result, per = good("c_lin")
        flipped = [tuple(-v for v in f) for f in result["forces"][1]]
        ef, em = case.errors(result, per, 1, 1, forces=flipped)
        report("control wrong sign: eF %.2f" % ef)
        self.assertTrue(ef > 1.0)

    def test_control_missing_skin_cell(self):
        case, result, per = good("c_lin")
        man = dict(case.man, skin={})
        job = case.run(man=man)
        self.assertTrue(job.poll(), job.error())
        bad = job.result()
        per2 = fb_core.assign_nodes(case.plan, case.mesh, bad)
        ef = max(case.errors(bad, per2, g, 1)[0] for g in (1, 2))
        em = max(case.errors(bad, per2, g, 1)[1] for g in (1, 2))
        rest = bad["rest"][1]
        report("control skin: eF %.1e eM %.1e, rest count %d, %.0f N" % (
            ef, em, rest["count"], rest["largest"]))
        # the safeguard: the equilibrium check sees what the sum no longer has
        self.assertTrue(rest["count"] > 0)
        self.assertTrue(rest["where"])
        self.assertTrue(ef > 1e-3)

    def test_control_missing_midside_nodes(self):
        case, result, per = good("c_lin")
        corners = set(n for e in case.chosen for n in case.mesh["elements"][e][1][:8])
        keep = [i for i, r in enumerate(result["nodes"])
                if tuple(r["xyz"]) in set(case.mesh["nodes"][n] for n in corners)
                or min(abs(r["xyz"][0] - case.mesh["nodes"][n][0]) +
                       abs(r["xyz"][1] - case.mesh["nodes"][n][1]) +
                       abs(r["xyz"][2] - case.mesh["nodes"][n][2]) for n in corners) < 1e-9]
        self.assertTrue(0 < len(keep) < len(result["nodes"]))
        cut = dict(result, nodes=[result["nodes"][i] for i in keep])
        # the safeguard
        self.assertRaises(Refused, fb_core.assign_nodes, case.plan, case.mesh, cut)
        # and what it protects against
        idx = [i for i in per[1] if i in set(keep)]
        ef, em = case.errors(result, {1: idx}, 1, 1)
        report("control midside: eF %.2f eM %.2f" % (ef, em))
        self.assertTrue(ef > 0.5)

    def test_control_fingerprint(self):
        case, result, per = good("c_lin")
        nodes = dict(case.mesh["nodes"])
        nodes[1] = (nodes[1][0] + 1e-6, nodes[1][1], nodes[1][2])
        job = case.run(mesh=dict(case.mesh, nodes=nodes))
        self.assertEqual(job.poll(), False)
        self.assertEqual(job.code(), "fingerprint")
        self.assertEqual(fb_aster.refuse(case.man, VERSION, fb_aster.mesh_fingerprint(
            nodes, list(case.mesh["elements"]))), "fingerprint")

    def test_stop_real_run(self):
        case = Case("c_lin")
        scratch = tempfile.mkdtemp(prefix="fbe_")
        job = fb_aster.start(case.man, case.folder, case.plan, case.mesh, EXE, scratch)
        work = job.work
        end = time.time() + 30
        while not os.path.isfile(os.path.join(work, "run.console")) and time.time() < end:
            time.sleep(0.02)
        time.sleep(0.7)
        job.stop()
        self.assertEqual(job.code(), "stopped")
        while os.path.exists(work) and time.time() < end:
            time.sleep(0.1)
        self.assertFalse(os.path.exists(work), "the run left its folder behind")
        os.rmdir(scratch)


@unittest.skipUnless(available("c_lq"), "no base of c_lq, Code-Aster or numpy")
class ExtraNodes(unittest.TestCase):
    def test_statics(self):
        case, result, per = good("c_lq")
        self.assertTrue(result["extra_nodes"])
        self.assertEqual(len(case.plan["cut_nodes"]), 90)
        self.assertEqual(len(result["nodes"]), 242)
        self.assertEqual([len(per[1]), len(per[2])], [121, 121])
        for g in (1, 2):
            ef, em = case.errors(result, per, g, 1)
            report("c_lq cut %d: eF %.1e eM %.1e" % (g, ef, em))
            self.assertTrue(ef < BAR and em < BAR)
        self.assertEqual(result["rest"][1]["count"], 0)

    def test_nodes_of_mecway_are_linked(self):
        case, result, per = good("c_lq")
        linked = [r["nid"] for r in result["nodes"] if r["nid"] is not None]
        self.assertEqual(sorted(linked), case.plan["cut_nodes"])
        self.assertTrue(fb_aster.check_solution(result, 1, solution_of(case, 1)) is None)

    def test_control_missing_midside_nodes(self):
        case, result, per = good("c_lq")
        known = set(case.mesh["nodes"][n] for n in case.plan["cut_nodes"])
        keep = [i for i, r in enumerate(result["nodes"]) if tuple(
            float("%.12f" % c) for c in r["xyz"]) in set(
            tuple(float("%.12f" % c) for c in p) for p in known)]
        self.assertEqual(len(keep), 90)
        cut = dict(result, nodes=[result["nodes"][i] for i in keep])
        self.assertRaises(Refused, fb_core.assign_nodes, case.plan, case.mesh, cut)
        ef, em = case.errors(result, {1: [i for i in per[1] if i in set(keep)]}, 1, 1)
        report("control c_lq midside: eF %.2f eM %.2f" % (ef, em))
        self.assertTrue(ef > 0.5)


@unittest.skipUnless(available("c_nl"), "no base of c_nl, Code-Aster or numpy")
class Nonlinear(unittest.TestCase):
    def test_statics_per_step(self):
        case, result, per = good("c_nl")
        self.assertEqual([s["rank"] for s in result["steps"]], [0, 1, 2, 3, 4])
        self.assertEqual([s["time"] for s in result["steps"]], [0.0, .25, .5, .75, 1.0])
        self.assertTrue(result["large"])
        self.assertTrue(all(r["large"] for r in result["nodes"]))
        for rank in (1, 2, 3, 4):
            for g in (1, 2):
                ef, em = case.errors(result, per, g, rank)
                report("c_nl rank %d cut %d: eF %.1e eM %.1e, rest %.1e N, u %.2f mm" % (
                    rank, g, ef, em, result["rest"][rank]["largest"], 1e3 * max(
                        abs(v) for u in result["disp"][rank] for v in u)))
                self.assertTrue(ef < BAR_STEP and em < BAR_STEP)
            self.assertEqual(result["rest"][rank]["count"], 0)
            self.assertEqual(result["on_cut"][rank]["count"], 0)
        for g in (1, 2):
            ef, em = case.errors(result, per, g, 4)
            self.assertTrue(ef < BAR and em < BAR, "%.1e %.1e" % (ef, em))

    def test_rank_zero_is_no_equilibrium_and_the_check_says_so(self):
        # the state before the first step: gravity on, no stress yet
        case, result, per = good("c_nl")
        self.assertTrue(result["rest"][0]["count"] > 0)

    def test_control_x_instead_of_x_plus_u(self):
        case, result, per = good("c_nl")
        rank = 4
        plain = [r["xyz"] for r in result["nodes"]]
        worst = max(case.errors(result, per, g, rank, on=plain)[1] for g in (1, 2))
        report("control x instead of x+u: eM %.1e" % worst)
        self.assertTrue(worst > 1e-5)

    def test_component_not_in_the_table(self):
        case, result, per = good("c_nl")
        for table in ({"Other": "PETIT"}, {"P": "MIXED"}):
            try:
                case.run(man=dict(case.man, deformation_by_component=table))
            except Refused as e:
                self.assertEqual(e.code, "deformation")
            else:
                self.fail("no refusal")

    def test_last_step_is_the_last_step_of_the_solution(self):
        case, result, per = good("c_nl")
        self.assertTrue(fb_aster.check_solution(result, None, solution_of(case, 4)) is None)

    def test_control_u_on_a_small_displacement_component(self):
        # the table of the manifest decides, not the general choice
        case, result, per = good("c_nl")
        man = dict(case.man, deformation_by_component={"P": "PETIT"})
        job = case.run(man=man)
        self.assertTrue(job.poll(), job.error())
        small = job.result()
        self.assertFalse(any(r["large"] for r in small["nodes"]))
        self.assertEqual(fb_core.positions(small, 4)[0], small["nodes"][0]["xyz"])

    def test_mixed_components_sum_per_node(self):
        # half of the selection on x + u: both cuts see one kind, with a warning
        case, result, per = good("c_nl")
        xs = dict((e, np.mean([case.mesh["nodes"][n][0]
                               for n in case.mesh["elements"][e][1]]))
                  for e in case.chosen)
        comp = dict(case.mesh["component"])
        for e, x in xs.items():
            comp[e] = "B" if x > 0.1 else "P"
        man = dict(case.man, deformation_by_component={"P": "GDEF_LOG", "B": "PETIT"})
        job = case.run(man=man, mesh=dict(case.mesh, component=comp))
        self.assertTrue(job.poll(), job.error())
        mixed = job.result()
        self.assertTrue("mixed_deformation" in mixed["warnings"])
        by_x = dict((r["xyz"][0] < 0.1, r["large"]) for r in mixed["nodes"])
        self.assertEqual(by_x, {True: True, False: False})
        per2 = fb_core.assign_nodes(case.plan, case.mesh, mixed)
        self.assertFalse(fb_core.mixed_shape(mixed, per2[1]))
        self.assertFalse(fb_core.mixed_shape(mixed, per2[2]))

    def test_base_stays_read_only(self):
        case = Case("c_nl")
        folder = os.path.join(case.folder, case.man["base"])
        before = base_state(folder)
        job = case.run()
        self.assertTrue(job.poll(), job.error())
        self.assertEqual(base_state(folder), before)


@unittest.skipUnless(available("c_lin") and available("c_other"),
                     "no bases of c_lin and c_other, Code-Aster or numpy")
class StaleBase(unittest.TestCase):
    """The same mesh, so the same fingerprint, and a run with other loads."""

    def test_same_fingerprint(self):
        self.assertEqual(good("c_other")[0].man["fingerprint"], good("c_lin")[0].man["fingerprint"])

    def test_own_solution(self):
        for tag in ("c_lin", "c_other"):
            case, result, per = good(tag)
            self.assertEqual(sorted(r["nid"] for r in result["nodes"]), case.plan["cut_nodes"])
            self.assertTrue(fb_aster.check_solution(result, 1, solution_of(case, 1)) is None, tag)

    def test_base_of_another_load(self):
        lin, lin_result, _ = good("c_lin")
        other, other_result, _ = good("c_other")
        worst = max(abs(a - b) for u, v in zip(lin_result["disp"][1], other_result["disp"][1])
                    for a, b in zip(u, v))
        report("stale base: disp differs %.2e m at 20%% more load" % worst)
        # c_other in the base, c_lin in Mecway, and the other way round
        self.assertEqual(fb_aster.check_solution(other_result, 1, solution_of(lin, 1)), "stale")
        self.assertEqual(fb_aster.check_solution(lin_result, 1, solution_of(other, 1)), "stale")

    def test_no_solution_values(self):
        lin, result, _ = good("c_lin")
        self.assertEqual(fb_aster.check_solution(result, 1, {}), "unknown")
        some = solution_of(lin, 1)
        del some[lin.plan["cut_nodes"][0]]
        self.assertEqual(fb_aster.check_solution(result, 1, some), "unknown")


def own_launcher(top, *folders):
    """A launcher of our own below top that only calls the real one: a path
    with <folders>\\run_aster.bat, for the version the path tells. The real one
    by %LOCALAPPDATA%, as EXE, so no path of the user is in the file."""
    folder = os.path.join(top, *folders)
    os.makedirs(folder)
    path = os.path.join(folder, "run_aster.bat")
    with open(path, "w", encoding="ascii") as f:
        f.write('@call "%LOCALAPPDATA%\\code_aster\\v2025\\17.4\\bin\\run_aster.bat" %*\n'
                '@exit /b %errorlevel%\n')
    return path


# The version in the header of a .mess, as the bridge reads it
# (bridge_version._MESS_VERSION_RE): "Version 17.4.0 ..."
MESS_VERSION_RE = re.compile(r"^[ \t]*Version[ \t]+(\d+\.\d+(?:\.\d+)*)\b", re.M)


class VersionRefusal(unittest.TestCase):
    """The version refusals of fb_aster.start on real runs of the bridge. The
    order of fb_aster.refuse: launcher_version, run_version, version, then
    fingerprint and no_base; start() refuses before no_cut and no_aster."""

    def scratch(self):
        folder = tempfile.mkdtemp(prefix="fbv_")
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def refused(self, case, man, exe, plan=None):
        scratch = self.scratch()
        with self.assertRaises(Refused) as caught:
            fb_aster.start(man, case.folder, plan or case.plan, case.mesh, exe, scratch)
        self.assertEqual(os.listdir(scratch), [])
        return caught.exception


@unittest.skipUnless(available("c_lin"), "no base of c_lin, Code-Aster or numpy")
class VersionsOfTheLauncher(VersionRefusal):
    def test_launcher_version(self):
        case = Case("c_lin")
        exe = own_launcher(self.scratch(), "aster", "bin")
        self.assertTrue(fb_aster.version_from_launcher(exe) is None)
        e = self.refused(case, case.man, exe)
        self.assertEqual((e.code, e.detail), ("launcher_version", exe))
        # before no_aster and no_cut
        missing = os.path.join(self.scratch(), "aster", "bin", "run_aster.bat")
        self.assertEqual(self.refused(case, case.man, missing).code, "launcher_version")
        empty = dict(case.plan, cut_nodes=[])
        self.assertEqual(self.refused(case, case.man, exe, empty).code, "launcher_version")

    def test_version(self):
        case = Case("c_lin")
        self.assertEqual(case.man["aster_version"], "17.4")
        e = self.refused(case, dict(case.man, aster_version="17.2"), EXE)
        self.assertEqual((e.code, e.detail), ("version", "17.2"))
        # the detail is the version of the run, also for another launcher
        exe = own_launcher(self.scratch(), "17.2", "bin")
        e = self.refused(case, case.man, exe)
        self.assertEqual((e.code, e.detail), ("version", "17.4"))


@unittest.skipUnless(available("c_lin") and available("c_nover"),
                     "no bases of c_lin and c_nover, Code-Aster or numpy")
class VersionsOfTheRun(VersionRefusal):
    """c_nover: a real run with a launcher without <version>\\bin, so the bridge
    wrote aster_version null (finish_run reads the path when it gets no version
    of the .mess; in Mecway the bridge passes the version of the .mess first)."""

    def test_the_bridge_wrote_no_version(self):
        case = Case("c_nover")
        self.assertTrue(case.man["aster_version"] is None)
        self.assertEqual(case.man["fingerprint"], Case("c_lin").man["fingerprint"])
        # the .mess of that run does tell it: null comes from the path alone
        mess = [n for n in os.listdir(case.folder)
                if n.endswith(".mess") and not n.startswith("post")]
        self.assertEqual(len(mess), 1, mess)
        with open(os.path.join(case.folder, mess[0]), "rb") as f:
            found = MESS_VERSION_RE.search(f.read(1 << 16).decode("utf-8", "replace"))
        self.assertTrue(found, "no version in the .mess")
        self.assertEqual(fb_aster._version_key(found.group(1)), (17, 4))

    def test_run_version(self):
        case = Case("c_nover")
        fp = fb_aster.mesh_fingerprint(case.mesh["nodes"], list(case.mesh["elements"]))
        # as the panel asks it, and as start() refuses
        self.assertEqual(fb_aster.refuse(case.man, fb_aster.version_from_launcher(EXE), fp,
                                         case.folder), "run_version")
        folder = os.path.join(case.folder, case.man["base"])
        before = base_state(folder)
        self.assertEqual(self.refused(case, case.man, EXE).code, "run_version")
        self.assertEqual(base_state(folder), before)

    def test_launcher_first(self):
        # both unknown: the launcher, which refuses every run, is named first
        case = Case("c_nover")
        exe = own_launcher(self.scratch(), "aster", "bin")
        e = self.refused(case, case.man, exe)
        self.assertEqual((e.code, e.detail), ("launcher_version", exe))

    def test_only_the_version_is_missing(self):
        # the same base with the version named: a good run, so the refusal
        # above is about the version, not about the base
        case = Case("c_nover")
        job = case.run(man=dict(case.man, aster_version="17.4"))
        self.assertTrue(job.poll(), job.error())
        result = job.result()
        per = fb_core.assign_nodes(case.plan, case.mesh, result)
        for g in (1, 2):
            ef, em = case.errors(result, per, g, 1)
            report("c_nover with version cut %d: eF %.1e eM %.1e" % (g, ef, em))
            self.assertTrue(ef < BAR and em < BAR)


BUILD = ("c_other", "c_nover")


def build(tags):
    """The bases of c_other and c_nover, as e9_chain.case; see the header."""
    wrong = [t for t in tags if t not in BUILD]
    missing = [v for v in ("FB_WORK", "FB_BRIDGE") if not os.environ.get(v)]
    if missing:
        sys.exit("set " + " and ".join(missing) + ": the work folder and the bridge")
    if wrong:
        sys.exit("build only {0}, not {1}".format(", ".join(BUILD), ", ".join(wrong)))
    e = load_statics()
    for tag in tags:
        shape, tip, side = CASES[tag]
        general = {}
        top = None
        if tag == "c_nover":
            top = tempfile.mkdtemp(prefix="fbl_")
            general["exe_aster"] = own_launcher(top, "aster", "bin")
        try:
            e.case(tag, shape, "lin_static_3d", {}, general, None, tip, side)
        finally:
            if top:
                shutil.rmtree(top, True)
        folder = os.path.join(e.wd, tag)
        names = [n for n in os.listdir(folder) if n.endswith("_manifest.json")]
        if len(names) != 1 or not os.path.isfile(os.path.join(folder, "post.npz")):
            sys.exit("{0}: no manifest or no post.npz".format(tag))
        with open(os.path.join(folder, names[0]), encoding="utf-8") as f:
            man = json.load(f)
        if not fb_aster._base_ok(folder, man["base"]):
            sys.exit("{0}: the base folder is empty".format(tag))
        if (man["aster_version"] is None) != (tag == "c_nover"):
            sys.exit("{0}: aster_version {1!r}".format(tag, man["aster_version"]))
        print("{0}: aster_version {1!r}".format(tag, man["aster_version"]))


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build(sys.argv[2:] or ["c_other"])
    else:
        unittest.main()
