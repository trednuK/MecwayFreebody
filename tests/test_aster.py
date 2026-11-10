# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_aster.py
# Unit tests of Scripts/fb_aster.py without Code-Aster and without numpy. The
# job runs against a fake launcher: a batch file that behaves as run_aster.
# The same file also runs in Mecway's IronPython (test_core_ipy.py).
# Run: python -m unittest discover -s tests

import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # Mecway's script engine
    HERE = os.environ.get("FB_TESTS", ".")
sys.path.insert(0, os.path.join(HERE, "..", "Scripts"))
sys.path.insert(0, HERE)
import fb_aster
import fb_core
from fb_core import Refused
from test_core import Builder, fill_cell

NON_ASCII = u"sp\u00e4tie m\u00e9t"      # inside the code page of the test PC


def tiny_model(shape="hex8"):
    """Three cells in a row; the middle one is selected. Numbers with gaps."""
    b = Builder()
    for i in range(3):
        fill_cell(b, shape, (float(i), 0.0, 0.0), (1.0, 1.0, 1.0))
    mesh = b.mesh
    mesh["component"] = dict((e, "P") for e in mesh["elements"])
    return mesh, fb_core.plan_cuts(mesh, [2])


def manifest(mesh, **changes):
    man = {"schema": 1, "run_id": "20261107_120000", "model": "m", "solver": "MECA_STATIQUE",
           "aster_version": "17.4", "memory_limit": 2048, "deformation": "PETIT",
           "deformation_by_component": {}, "base": "m_20261107_120000_base",
           "fingerprint": fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"])),
           "concepts": {"result": "res", "mesh": "mesh"},
           "cells": ["M1", "M2", "M3", "K1", "K2", "K3"],
           "skin": {"K1": [[1, 3]], "K2": [[2, 3]], "K3": [[2, 2], [3, 1]]},
           "not_shared": [], "extra_nodes": False}
    man.update(changes)
    return man


RESULT = {"format": 1, "ranks": [1], "times": [1.0], "index": [3, 7],
          "xyz": "0.1 0.2 0.3 1.0 2.0 3.0", "large": [0, 1],
          "forces": {"1": "1.0 2.0 3.0 0.0 0.0 0.0 -1.0 -2.0 -3.0 0.0 0.0 0.0"},
          "total": {"1": "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0"},
          "disp": {"1": "0.0 0.0 0.5 0.0 0.0 0.25"},
          "rest": {"1": {"sum": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "largest": 1e-9,
                         "cut_largest": 3.7, "top": [[1e-9, 2.0, 0.0, 0.0]]}}, "done": True}


def result_text(data=None):
    """JSON with the marker last, as the .comm writes it. The order of a dict
    differs in IronPython."""
    rest = dict(data or RESULT)
    rest.pop("done", None)
    return json.dumps(rest)[:-1] + ', "done": true}'


class Fingerprint(unittest.TestCase):
    def test_same_text_as_the_bridge(self):
        h = hashlib.sha256()
        h.update(b"1 0 1000000000 -1500000000\n2 300000000 0 0\nE7\nE9\n")
        got = fb_aster.mesh_fingerprint({2: (0.3, 0.0, 0.0), 1: (0.0, 1.0, -1.5)}, [9, 7])
        self.assertEqual(got, h.hexdigest())

    def test_a_moved_node_counts(self):
        a = fb_aster.mesh_fingerprint({1: (0.0, 0.0, 0.0)}, [1])
        b = fb_aster.mesh_fingerprint({1: (2e-9, 0.0, 0.0)}, [1])
        self.assertNotEqual(a, b)


class Files(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="fbt_")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def put(self, name, man):
        with io.open(os.path.join(self.folder, name + "_manifest.json"), "w",
                     encoding="utf-8") as f:
            text = json.dumps(man, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            f.write(text.decode("utf-8") if isinstance(text, bytes) else text)


class FindRuns(Files):
    def test_newest_first_of_this_mesh(self):
        mesh, plan = tiny_model()
        fp = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
        self.put("a", manifest(mesh, run_id="20261101_080000"))
        self.put("b", manifest(mesh, run_id="20261103_080000"))
        self.put("c", manifest(mesh, run_id="20261102_080000"))
        self.put("other", manifest(mesh, run_id="20261109_080000", fingerprint="abc123"))
        runs = fb_aster.find_runs(self.folder, fp)
        self.assertEqual([r["run_id"] for r in runs],
                         ["20261103_080000", "20261102_080000", "20261101_080000"])
        self.assertEqual(runs[0]["_folder"], self.folder)
        self.assertEqual(len(fb_aster.find_runs(self.folder, None)), 4)
        self.assertEqual(fb_aster.find_runs(self.folder, "0"), [])

    def test_broken_files_are_no_runs(self):
        with open(os.path.join(self.folder, "x_manifest.json"), "wb") as f:
            f.write(b'{"fingerprint":"abc"')
        with open(os.path.join(self.folder, "y_manifest.json"), "wb") as f:
            f.write(b"[1, 2]")
        with open(os.path.join(self.folder, "z.txt"), "wb") as f:
            f.write(b"{}")
        self.assertEqual(fb_aster.find_runs(self.folder, "abc"), [])
        self.assertEqual(fb_aster.find_runs(self.folder, None), [])

    def test_missing_folder(self):
        self.assertEqual(fb_aster.find_runs(os.path.join(self.folder, "no"), None), [])

    def test_large_foreign_manifest_is_not_parsed(self):
        # invalid JSON after the fingerprint: only a parser would notice
        text = '{"fingerprint":"aaa","cells":[' + '"M1",' * 200000 + 'oops'
        with open(os.path.join(self.folder, "big_manifest.json"), "wb") as f:
            f.write(text.encode("ascii"))
        t0 = time.time()
        self.assertEqual(fb_aster.find_runs(self.folder, "bbb"), [])
        self.assertTrue(time.time() - t0 < 5)

    def test_non_ascii_model_name(self):
        mesh, plan = tiny_model()
        self.put("n", manifest(mesh, model=NON_ASCII, base=NON_ASCII + "_base"))
        runs = fb_aster.find_runs(self.folder, None)
        self.assertEqual(runs[0]["model"], NON_ASCII)


class Refuse(Files):
    def setUp(self):
        Files.setUp(self)
        self.mesh, self.plan = tiny_model()
        os.makedirs(os.path.join(self.folder, "m_20261107_120000_base"))
        with open(os.path.join(self.folder, "m_20261107_120000_base", "glob.1"), "wb") as f:
            f.write(b"x")

    def code(self, **changes):
        return fb_aster.refuse(manifest(self.mesh, **changes), "17.4", folder=self.folder)

    def test_good_run(self):
        self.assertTrue(self.code() is None)

    def test_codes(self):
        self.assertEqual(self.code(schema=2), "schema")
        self.assertEqual(self.code(solver="MODE_ITER_SIMULT"), "solver")
        self.assertEqual(self.code(aster_version="16.9"), "version")
        self.assertEqual(self.code(not_shared=["contact"]), "not_shared")
        self.assertEqual(self.code(base="gone_base"), "no_base")
        self.assertEqual(fb_aster.refuse(None, "17.4"), "no_base")
        self.assertEqual(fb_aster.refuse({}, "17.4"), "no_base")

    def test_every_code_is_in_the_list(self):
        self.assertEqual(set(fb_aster.REFUSE),
                         set(("solver", "version", "fingerprint", "not_shared", "no_base",
                              "schema", "deformation", "offset", "schema_old", "beam_warping",
                              "beam_large_rotation", "not_shared_on_cut", "launcher_version",
                              "run_version")))

    def test_missing_keys(self):
        for key in ("cells", "skin", "base", "fingerprint", "deformation", "concepts",
                    "aster_version"):
            man = manifest(self.mesh)
            del man[key]
            self.assertEqual(fb_aster.refuse(man, "17.4"), "schema", key)
        man = manifest(self.mesh)
        del man["extra_nodes"]
        self.assertEqual(fb_aster.refuse(man, "17.4"), "schema")

    def test_a_manifest_cannot_lead_out_of_the_folder(self):
        for name in ("..", "..\\x", "a/b", "C:x"):
            self.assertEqual(self.code(base=name), "schema", name)
        man = manifest(self.mesh, concepts={"result": "res; import os"})
        self.assertEqual(fb_aster.refuse(man, "17.4"), "schema")

    def test_bad_concept_names(self):
        for concepts in ({"result": u"r\u00e9s"}, {"result": "res\n"}, {"result": None},
                         {"result": 3}, {}, ["res"], "res"):
            man = manifest(self.mesh, concepts=concepts)
            self.assertEqual(fb_aster.refuse(man, "17.4"), "schema", repr(concepts))

    def test_fingerprint(self):
        man = manifest(self.mesh)
        self.assertEqual(fb_aster.refuse(man, "17.4", "abc", self.folder), "fingerprint")
        self.assertTrue(fb_aster.refuse(man, "17.4", man["fingerprint"], self.folder) is None)

    def test_versions(self):
        self.assertTrue(self.code(aster_version="17.4.0") is None)
        self.assertTrue(self.code(aster_version="17.04.00") is None)
        self.assertEqual(self.code(aster_version="17.4.1"), "version")
        self.assertEqual(self.code(aster_version="abc"), "version")
        # a launcher that does not tell its version: the setting, not the run
        self.assertEqual(fb_aster.refuse(manifest(self.mesh), None), "launcher_version")
        self.assertEqual(fb_aster.refuse(manifest(self.mesh), "unknown"), "launcher_version")
        # the bridge could not tell the version of its run (null in the manifest)
        self.assertEqual(self.code(aster_version=None), "run_version")
        # both unknown: our own launcher setting first, it refuses every run
        self.assertEqual(fb_aster.refuse(manifest(self.mesh, aster_version=None), None),
                         "launcher_version")

    def test_empty_base_folder(self):
        os.makedirs(os.path.join(self.folder, "empty_base"))
        self.assertEqual(self.code(base="empty_base"), "no_base")

    def test_version_from_launcher(self):
        self.assertEqual(fb_aster.version_from_launcher(
            "C:\\x y\\code_aster\\v2025\\17.4\\bin\\run_aster.bat"), "17.4")
        self.assertTrue(fb_aster.version_from_launcher("C:\\tools\\run_aster.bat") is None)
        self.assertTrue(fb_aster.version_from_launcher(None) is None)
        # as the bridge: only a dotted number directly above bin
        self.assertEqual(fb_aster.version_from_launcher("C:/a/17.4.0/bin/run_aster.bat"),
                         "17.4.0")
        self.assertTrue(fb_aster.version_from_launcher("C:\\a\\17\\bin\\run_aster.bat") is None)
        self.assertTrue(fb_aster.version_from_launcher("C:\\a\\v17.4\\bin\\run_aster.bat")
                        is None)


class Deformation(unittest.TestCase):
    def setUp(self):
        self.mesh, self.plan = tiny_model()

    def test_linear_run_has_an_empty_table(self):
        man = manifest(self.mesh)
        self.assertEqual(fb_aster.split_deformation(man, self.mesh, [1, 2]), ([], [1, 2]))
        mesh = {"nodes": {}, "elements": {}}      # no components needed here
        self.assertEqual(fb_aster.split_deformation(man, mesh, [1]), ([], [1]))

    def test_table_decides(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                       deformation_by_component={"A": "GDEF_LOG", "B": "PETIT"})
        self.mesh["component"] = {1: "A", 2: "B", 3: "A"}
        self.assertEqual(fb_aster.split_deformation(man, self.mesh, [1, 2, 3]), ([1, 3], [2]))

    def test_table_beats_the_general_choice(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                       deformation_by_component={"P": "PETIT"})
        self.assertEqual(fb_aster.split_deformation(man, self.mesh, [1]), ([], [1]))

    def test_empty_table_with_large_general_choice(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP")
        self.assertEqual(fb_aster.split_deformation(man, self.mesh, [1]), ([1], []))

    def test_linear_is_small_whatever_the_table_says(self):
        man = manifest(self.mesh, deformation="GROT_GDEP",
                       deformation_by_component={"P": "GDEF_LOG", "Q": "MIXED"})
        self.assertEqual(fb_aster.split_deformation(man, self.mesh, [1, 2]), ([], [1, 2]))
        mesh = {"nodes": {}, "elements": {}}
        self.assertEqual(fb_aster.split_deformation(man, mesh, [1]), ([], [1]))

    def refused(self, man):
        try:
            fb_aster.split_deformation(man, self.mesh, [1])
        except Refused as e:
            return e.code
        return None

    def test_mixed_is_not_large(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                       deformation_by_component={"P": "MIXED"})
        self.assertEqual(self.refused(man), "deformation")

    def test_mixed_elsewhere_does_not_matter(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                       deformation_by_component={"P": "GDEF_LOG", "Q": "MIXED"})
        self.assertTrue(self.refused(man) is None)

    def test_mixed_as_the_general_choice(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="MIXED")
        self.assertEqual(self.refused(man), "deformation")

    def test_missing_component_is_refused(self):
        man = manifest(self.mesh, solver="STAT_NON_LINE",
                       deformation_by_component={"Q": "PETIT"})
        for mesh in (self.mesh, {"nodes": {}, "elements": {}}):
            try:
                fb_aster.split_deformation(man, mesh, [1])
            except Refused as e:
                self.assertEqual(e.code, "deformation")
            else:
                self.fail("no refusal")


class Selection(unittest.TestCase):
    def setUp(self):
        self.mesh, self.plan = tiny_model()

    def sel(self, man):
        text, warnings = fb_aster.build_selection(man, self.plan, self.mesh)
        return json.loads(text), warnings

    def test_positions_and_skin(self):
        d, warnings = self.sel(manifest(self.mesh))
        self.assertEqual(d["FBZS"], [2])
        self.assertEqual(d["FBZR"], [1, 3])
        # skin of the selection only; K1 belongs to the rest
        self.assertEqual(d["FBZK"], [2, 5, 6])
        self.assertEqual(d["FBZL"], [])
        self.assertEqual(d["FBZP"], [2])
        # K3 lies between the selection and the rest
        self.assertEqual(warnings, ["skin_on_cut"])

    def test_positions_follow_the_file_not_the_numbers(self):
        man = manifest(self.mesh, cells=["K1", "M3", "K2", "M1", "K3", "M2"])
        d, _ = self.sel(man)
        self.assertEqual(d["FBZS"], [6])
        self.assertEqual(d["FBZR"], [4, 2])
        self.assertEqual(d["FBZK"], [6, 3, 5])

    def test_split_line_has_a_second_cell(self):
        man = manifest(self.mesh, cells=["M1", "M2", "H2", "M3", "K1", "K2", "K3"])
        d, _ = self.sel(man)
        self.assertEqual(d["FBZS"], [2, 3])

    def test_element_missing_in_the_manifest(self):
        man = manifest(self.mesh, cells=["M1", "M3", "K1", "K2", "K3"])
        self.assertRaises(Refused, self.sel, man)

    def test_mixed_components(self):
        self.mesh["component"] = {1: "A", 2: "A", 3: "B"}
        b = Builder()
        for i in range(3):
            fill_cell(b, "hex8", (float(i), 0.0, 0.0), (1.0, 1.0, 1.0))
        self.plan = fb_core.plan_cuts(b.mesh, [2, 3])
        man = manifest(self.mesh, solver="STAT_NON_LINE", deformation="GDEF_LOG",
                       deformation_by_component={"A": "GDEF_LOG", "B": "PETIT"})
        d, warnings = self.sel(man)
        self.assertEqual(d["FBZL"], [2])
        self.assertEqual(d["FBZP"], [3])
        self.assertTrue("mixed_deformation" in warnings)


class RunFiles(unittest.TestCase):
    def test_comm(self):
        mesh, plan = tiny_model()
        text = fb_aster.comm_text(manifest(mesh, concepts={"result": "my_res"}))
        self.assertTrue(text.startswith("POURSUITE(LANG='EN')"))
        self.assertTrue(text.rstrip().endswith("FIN()"))
        self.assertTrue("fb_res = my_res\n" in text)
        self.assertFalse("@" in text)
        self.assertFalse("EXCIT" in text)
        self.assertFalse("POST_RELEVE_T" in text)
        self.assertTrue('FORCE="REAC_NODA"' in text)
        self.assertTrue('INTERSEC=("FBNS", "FBNR")' in text)
        self.assertTrue("getListOfGroupsOfElements" in text)
        self.assertEqual(text.count('FORCE="REAC_NODA"'), 2)
        self.assertFalse("numpy.save" in text)
        text.encode("ascii")

    def test_export(self):
        data = fb_aster.export_bytes("C:\\a b\\m_base", 1920, 4096).decode("ascii")
        lines = data.splitlines()
        self.assertTrue("R base C:\\a b\\m_base D 0" in lines)
        self.assertTrue("F libr sel.json D 32" in lines)
        self.assertTrue("F libr result.json R 33" in lines)
        self.assertTrue("P time_limit 1920" in lines)
        self.assertTrue("P memory_limit 4096" in lines)
        self.assertEqual([x for x in lines if x.startswith("R ")], ["R base C:\\a b\\m_base D 0"])
        self.assertFalse('"' in data)

    def test_non_ascii_path_in_the_code_page(self):
        path = u"C:\\" + NON_ASCII
        self.assertTrue(path.encode("mbcs") in fb_aster.export_bytes(path, 60, 2048))

    def test_path_outside_the_code_page(self):
        path = u"C:\\\u03a9\u0416"
        keep = fb_aster._short_path
        try:
            fb_aster._short_path = lambda p: u"C:\\WX~1"
            self.assertTrue(b"R base C:\\WX~1 D 0" in fb_aster.export_bytes(path, 60, 2048))
            fb_aster._short_path = lambda p: None
            self.assertRaises(Refused, fb_aster.export_bytes, path, 60, 2048)
        finally:
            fb_aster._short_path = keep

    def test_double_space_is_refused(self):
        self.assertRaises(Refused, fb_aster.export_path, "C:\\a  b")
        self.assertRaises(Refused, fb_aster.export_path, "C:\\a ")


class Decode(unittest.TestCase):
    def decode(self, d):
        return fb_aster.decode_result(json.dumps(d), False, ["w"], 2.5)

    def test_contract(self):
        r = self.decode(RESULT)
        self.assertEqual(r["steps"], [{"rank": 1, "time": 1.0}])
        self.assertEqual(r["nodes"], [{"index": 3, "xyz": (0.1, 0.2, 0.3), "large": False},
                                      {"index": 7, "xyz": (1.0, 2.0, 3.0), "large": True}])
        self.assertEqual(r["forces"][1][1], (-1.0, -2.0, -3.0, 0.0, 0.0, 0.0))
        self.assertEqual(r["disp"][1][0], (0.0, 0.0, 0.5))
        self.assertEqual(r["rest"][1]["sum"], (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(r["rest"][1]["largest"], 1e-9)
        self.assertEqual(len(r["on_cut"][1]["totals"]), 2)
        self.assertEqual(r["seconds"], 2.5)
        self.assertEqual(r["warnings"], ["w"])
        self.assertEqual(r["extra_nodes"], False)
        self.assertEqual(r["large"], True)
        self.assertEqual(fb_core.positions(r, 1)[1], (1.0, 2.0, 3.25))

    def changed(self, key, value):
        d = dict(RESULT)
        d[key] = value
        return d

    def test_short_step(self):
        self.assertRaises(ValueError, self.decode, self.changed("forces", {"1": "1.0 2.0"}))

    def test_short_disp(self):
        self.assertRaises(ValueError, self.decode, self.changed("disp", {"1": "1.0"}))

    def test_cut_nodes_that_do_not_fit(self):
        self.assertRaises(ValueError, self.decode, self.changed("xyz", "1.0"))

    def test_not_a_number(self):
        text = "nan 2.0 3.0 0.0 0.0 0.0 -1.0 -2.0 -3.0 0.0 0.0 0.0"
        self.assertRaises(ValueError, self.decode, self.changed("forces", {"1": text}))
        text = "inf 2.0 3.0 0.0 0.0 0.0 -1.0 -2.0 -3.0 0.0 0.0 0.0"
        self.assertRaises(ValueError, self.decode, self.changed("forces", {"1": text}))

    def test_displacement_not_a_number(self):
        for bad in ("nan", "inf", "-inf"):
            text = bad + " 0.0 0.5 0.0 0.0 0.25"
            self.assertRaises(ValueError, self.decode, self.changed("disp", {"1": text}))

    def test_total_not_a_number(self):
        text = "nan 2.0 3.0 0.0 0.0 0.0 -1.0 -2.0 -3.0 0.0 0.0 0.0"
        self.assertRaises(ValueError, self.decode, self.changed("total", {"1": text}))

    def test_short_total(self):
        self.assertRaises(ValueError, self.decode, self.changed("total", {"1": "1.0"}))

    def test_position_not_a_number(self):
        for bad in ("nan", "inf"):
            text = bad + " 0.2 0.3 1.0 2.0 3.0"
            self.assertRaises(ValueError, self.decode, self.changed("xyz", text))

    def test_complete_marker(self):
        text = result_text().encode("ascii")
        self.assertTrue(fb_aster._complete(text))
        self.assertFalse(fb_aster._complete(text[:-12]))


def two_cuts(heavy, light, top, largest=None):
    """A result with two cuts of four nodes each: forces heavy and light in
    total, and the nodes off the cuts in top."""
    forces = [(heavy / 4, 0.0, 0.0, 0.0, 0.0, 0.0)] * 4 + [(light / 4, 0.0, 0.0, 0.0, 0.0, 0.0)] * 4
    nodes = [{"xyz": (float(i), 0.0, 0.0), "large": False} for i in range(8)]
    result = {"forces": {1: forces}, "nodes": nodes, "disp": {1: [(0.0, 0.0, 0.0)] * 8},
              "on_cut": {1: {"totals": [(0.0,) * 6] * 8}}, "rest": {1: {
                  "sum": (0.0,) * 6, "largest": top[0][0] if top else 0.0, "cut_largest": heavy / 4,
                  "top": top, "tolerance": None, "count": len(top), "where": []}}}
    return result, {1: [0, 1, 2, 3], 2: [4, 5, 6, 7]}


class RestCheck(unittest.TestCase):
    SPRING = [[5.0, 0.1, 0.2, 0.3], [1e-9, 0.0, 0.0, 0.0]]

    def test_heavy_cut_does_not_hide_a_spring_at_the_light_cut(self):
        # 1 MN on one cut, 10 N on the other, a spring of 5 N off the cuts
        result, per = two_cuts(1e6, 10.0, self.SPRING)
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
        rest = result["rest"][1]
        self.assertEqual(rest["count"], 1)
        self.assertEqual(rest["where"], [(0.1, 0.2, 0.3)])
        self.assertTrue(abs(rest["tolerance"] - 1e-3) < 1e-12)
        self.assertFalse("top" in rest)
        # sum and largest stay
        self.assertEqual(rest["largest"], 5.0)
        self.assertEqual(rest["sum"], (0.0,) * 6)
        # what the rule on the largest nodal force would have said
        self.assertTrue(5.0 < float(fb_aster.REST_TOL) * rest["cut_largest"])

    def test_nonlinear_noise_sets_a_lower_limit(self):
        result, per = two_cuts(1e6, 10.0, self.SPRING)
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["STAT_NON_LINE"])
        self.assertTrue(abs(result["rest"][1]["tolerance"] - 2.5) < 1e-9)
        self.assertEqual(result["rest"][1]["count"], 1)
        result, per = two_cuts(1e6, 10.0, [[2.0, 0.0, 0.0, 0.0]])
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["STAT_NON_LINE"])
        self.assertEqual(result["rest"][1]["count"], 0)

    def test_clean_model(self):
        result, per = two_cuts(1000.0, 800.0, [[1e-9, 0.0, 0.0, 0.0]])
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
        self.assertEqual(result["rest"][1]["count"], 0)
        self.assertEqual(result["rest"][1]["where"], [])

    def test_a_cut_without_force(self):
        result, per = two_cuts(1000.0, 0.0, [[1e-3, 0.0, 0.0, 0.0]])
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
        self.assertEqual(result["rest"][1]["count"], 1)

    def test_no_force_anywhere(self):
        result, per = two_cuts(0.0, 0.0, [[1e-12, 0.0, 0.0, 0.0]])
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
        self.assertEqual(result["rest"][1]["count"], 0)


class OnCut(unittest.TestCase):
    def judged(self, totals, solver="MECA_STATIQUE", heavy=1000.0, light=800.0):
        result, per = two_cuts(heavy, light, [])
        for i, value in totals.items():
            result["on_cut"][1]["totals"][i] = value
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE[solver])
        return result["on_cut"][1]

    def setUp(self):
        self.zero = [(0.0,) * 6] * 8

    def test_free_nodes(self):
        r = self.judged({})
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["where"], [])
        self.assertEqual(r["sum"], (0.0,) * 6)
        self.assertEqual(r["cuts"][1]["count"], 0)

    def test_support_on_one_cut(self):
        # 40 N along y at x = 5 and 3 N at x = 6, both on the light cut
        r = self.judged({5: (0.0, 40.0, 0.0, 0.0, 0.0, 0.0), 6: (0.0, 3.0, 0.0, 0.0, 0.0, 0.0)})
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["largest"], 40.0)
        self.assertEqual(r["where"], [(5.0, 0.0, 0.0), (6.0, 0.0, 0.0)])
        self.assertEqual(r["sum"], (0.0, 43.0, 0.0, 0.0, 0.0, 218.0))
        self.assertEqual(r["cuts"][1]["count"], 0)
        self.assertEqual(r["cuts"][1]["sum"], (0.0,) * 6)
        self.assertEqual(r["cuts"][2]["count"], 2)
        self.assertEqual(r["cuts"][2]["sum"], r["sum"])
        self.assertEqual(r["cuts"][2]["where"], r["where"])

    def test_same_tolerance_as_the_rest(self):
        result, per = two_cuts(1e6, 10.0, [])
        result["on_cut"][1]["totals"][0] = (5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        result["on_cut"][1]["totals"][1] = (5e-4, 0.0, 0.0, 0.0, 0.0, 0.0)
        fb_aster.judge_rest(result, per, fb_aster.REST_NOISE["MECA_STATIQUE"])
        entry = result["on_cut"][1]
        self.assertEqual(entry["tolerance"], result["rest"][1]["tolerance"])
        self.assertEqual(entry["count"], 1)
        self.assertFalse("totals" in entry)

    def test_residual_of_a_nonlinear_run_is_no_support(self):
        r = self.judged({2: (1e-3, 0.0, 0.0, 0.0, 0.0, 0.0)}, "STAT_NON_LINE")
        self.assertEqual(r["count"], 0)

    def test_moment_on_the_shape_the_node_is_summed_on(self):
        result, per = two_cuts(1000.0, 800.0, [])
        result["nodes"][1]["large"] = True
        result["disp"][1] = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 6
        result["on_cut"][1]["totals"][1] = (0.0, 10.0, 0.0, 0.0, 0.0, 0.0)
        fb_aster.judge_rest(result, per, 0.0)
        self.assertEqual(result["on_cut"][1]["sum"][5], 20.0)
        # the place stays the node of the mesh
        self.assertEqual(result["on_cut"][1]["where"], [(1.0, 0.0, 0.0)])

    def test_job_gives_on_cut(self):
        d = fb_aster.decode_result(result_text(), False, [], 1.0)
        self.assertEqual(len(d["on_cut"][1]["totals"]), 2)


class CheckSolution(unittest.TestCase):
    def setUp(self):
        self.result = {
            "steps": [{"rank": 1, "time": 0.5}, {"rank": 2, "time": 1.0}],
            "nodes": [{"index": 0, "xyz": (0.0, 0.0, 0.0), "nid": 11},
                      {"index": 1, "xyz": (1.0, 0.0, 0.0), "nid": 12},
                      {"index": 2, "xyz": (0.5, 0.0, 0.0), "nid": None}],
            "disp": {1: [(0.0, 0.0, 1.0), (0.0, 0.5, 0.0), (9.0, 9.0, 9.0)],
                     2: [(0.0, 0.0, 2.0), (0.0, 1.0, 0.0), (9.0, 9.0, 9.0)]}}
        self.same = {11: (0.0, 0.0, 2.0), 12: (0.0, 1.0, 0.0), 13: (5.0, 5.0, 5.0)}

    def test_same(self):
        self.assertTrue(fb_aster.check_solution(self.result, 2, self.same) is None)

    def test_last_step_by_default(self):
        self.assertTrue(fb_aster.check_solution(self.result, None, self.same) is None)

    def test_midside_nodes_do_not_count(self):
        self.assertTrue(fb_aster.check_solution(self.result, 2, self.same, 1e-12) is None)

    def test_single_precision_is_the_same(self):
        values = dict((n, tuple(c * (1 + 6e-8) for c in u)) for n, u in self.same.items())
        self.assertTrue(fb_aster.check_solution(self.result, 2, values) is None)

    def test_other_load(self):
        self.assertEqual(fb_aster.check_solution(self.result, 1, self.same), "stale")
        small = dict((n, tuple(1.001 * c for c in u)) for n, u in self.same.items())
        self.assertEqual(fb_aster.check_solution(self.result, 2, small), "stale")

    def test_relative_to_the_largest_displacement(self):
        micro = dict(self.result, disp={2: [(0.0, 0.0, 2e-9), (0.0, 1e-9, 0.0), (0.0, 0.0, 0.0)]})
        other = {11: (0.0, 0.0, 4e-9), 12: (0.0, 2e-9, 0.0)}
        self.assertEqual(fb_aster.check_solution(micro, 2, other), "stale")

    def test_tolerance(self):
        values = dict(self.same)
        values[12] = (0.0, 1.0 + 1e-3, 0.0)
        self.assertEqual(fb_aster.check_solution(self.result, 2, values), "stale")
        self.assertTrue(fb_aster.check_solution(self.result, 2, values, 1e-2) is None)

    def test_unknown(self):
        check = fb_aster.check_solution
        self.assertEqual(check(self.result, 7, self.same), "unknown")
        self.assertEqual(check(self.result, 2, {}), "unknown")
        self.assertEqual(check(self.result, 2, None), "unknown")
        self.assertEqual(check(self.result, 2, {11: (0.0, 0.0, 2.0)}), "unknown")
        self.assertEqual(check(self.result, 2, {11: (0.0, 0.0, float("nan")),
                                                12: (0.0, 1.0, 0.0)}), "unknown")
        self.assertEqual(check(dict(self.result, steps=[]), None, self.same), "unknown")

    def test_unknown_without_a_link(self):
        for record in self.result["nodes"]:
            del record["nid"]
        self.assertEqual(fb_aster.check_solution(self.result, 2, self.same), "unknown")

    def test_nothing_moved(self):
        result = dict(self.result, disp={2: [(0.0, 0.0, 0.0)] * 3})
        values = {11: (0.0, 0.0, 0.0), 12: (0.0, 0.0, 0.0)}
        self.assertEqual(fb_aster.check_solution(result, 2, values), "unknown")


class Speed(Files):
    def test_big_files(self):
        import test_core
        count = 5000
        ranks = list(range(1, 41))
        row = " ".join(["-1234.5678901234567"] * (6 * count))
        row3 = " ".join(["0.0012345678901234567"] * (3 * count))
        d = {"format": 1, "ranks": ranks, "times": [float(k) for k in ranks],
             "index": list(range(count)), "xyz": row3, "large": [1] * count,
             "forces": dict((str(k), row) for k in ranks),
             "total": dict((str(k), row) for k in ranks),
             "disp": dict((str(k), row3) for k in ranks),
             "rest": dict((str(k), RESULT["rest"]["1"]) for k in ranks), "done": True}
        text = json.dumps(d)
        t0 = time.time()
        r = fb_aster.decode_result(text, False, [], 1.0)
        t1 = time.time()
        self.assertEqual(len(r["forces"]), 40)
        # a manifest of 500 000 cells
        mesh, plan = tiny_model()
        man = manifest(mesh, cells=["M{0}".format(i) for i in range(500000)])
        self.put("big", man)
        size = os.path.getsize(os.path.join(self.folder, "big_manifest.json"))
        t2 = time.time()
        self.assertEqual(fb_aster.find_runs(self.folder, "0"), [])
        t3 = time.time()
        runs = fb_aster.find_runs(self.folder, man["fingerprint"])
        t4 = time.time()
        positions = fb_aster._cell_positions(runs[0])
        t5 = time.time()
        fb_aster.mesh_fingerprint(dict((i, (0.1, 0.2, 0.3)) for i in range(1, 100001)),
                                  list(range(1, 25001)))
        t6 = time.time()
        self.assertEqual(len(positions), 500000)
        test_core.SPEED.update(
            decode_mb=len(text) / 1e6, decode=t1 - t0, manifest_mb=size / 1e6,
            find_runs_other=t3 - t2, find_runs_parse=t4 - t3, positions=t5 - t4,
            fingerprint_100k_nodes=t6 - t5)


# ---- the job, against a batch file ---------------------------------------------------
BAT = r"""@echo off
rem Stands in for run_aster.bat: does what the mode file next to it says.
set /p MODE=<"%~dp0mode.txt"
if "%MODE%"=="" exit /b 9
if not exist run.comm exit /b 8
if not exist sel.json exit /b 8
if not exist run.export exit /b 8
echo %TEMP%> temp_seen.txt
if "%MODE%"=="ok" goto ok
if "%MODE%"=="slow" goto slow
if "%MODE%"=="fail" goto fail
if "%MODE%"=="truncated" goto truncated
exit /b 7
:ok
copy /y "%~dp0result.txt" result.json > nul
exit /b 0
:truncated
copy /y "%~dp0short.txt" result.json > nul
exit /b 0
:fail
echo   ^<F^> ^<SUPERVIS^> an error of the fake run> run.mess
exit /b 1
:slow
ping -n 60 127.0.0.1 > nul
copy /y "%~dp0result.txt" result.json > nul
exit /b 0
"""


class FakeRun(Files):
    """A folder with a base, and a launcher in .../17.4/bin/."""
    place = ""

    def setUp(self):
        Files.setUp(self)
        self.root = os.path.join(self.folder, self.place) if self.place else self.folder
        self.bin = os.path.join(self.root, "aster x", "17.4", "bin")
        os.makedirs(self.bin)
        self.exe = os.path.join(self.bin, "run_aster.bat")
        with open(self.exe, "wb") as f:
            f.write(BAT.replace("\n", "\r\n").encode("ascii"))
        text = result_text()
        with open(os.path.join(self.bin, "result.txt"), "wb") as f:
            f.write(text.encode("ascii"))
        with open(os.path.join(self.bin, "short.txt"), "wb") as f:
            f.write(text[:-20].encode("ascii"))
        self.mesh, self.plan = tiny_model()
        self.man = manifest(self.mesh)
        self.runs = os.path.join(self.root, "runs here")
        os.makedirs(os.path.join(self.runs, self.man["base"]))
        with open(os.path.join(self.runs, self.man["base"], "glob.1"), "wb") as f:
            f.write(b"x")
        self.scratch = os.path.join(self.root, "scratch")

    def mode(self, name):
        with open(os.path.join(self.bin, "mode.txt"), "wb") as f:
            f.write(name.encode("ascii"))

    def start(self, **kw):
        return fb_aster.start(self.man, self.runs, self.plan, self.mesh, self.exe,
                              self.scratch, **kw)

    def wait(self, job, seconds=30.0):
        end = time.time() + seconds
        while job.poll() is None:
            self.assertTrue(time.time() < end, "the job does not end")
            time.sleep(0.02)
        return job.poll()

    def gone(self, path, seconds=20.0):
        end = time.time() + seconds
        while os.path.exists(path) and time.time() < end:
            time.sleep(0.05)
        self.assertFalse(os.path.exists(path))


class Job(FakeRun):
    def test_good_run(self):
        self.mode("ok")
        job = self.start()
        work = job.work
        self.assertTrue(self.wait(job))
        self.assertTrue(job.error() is None)
        self.assertTrue(job.code() is None)
        r = job.result()
        self.assertEqual(r["forces"][1][0], (1.0, 2.0, 3.0, 0.0, 0.0, 0.0))
        self.assertTrue(r["seconds"] > 0)
        self.assertEqual(r["warnings"], ["skin_on_cut"])
        self.gone(work)
        self.assertTrue(os.path.isdir(self.scratch))
        self.assertTrue(job.result() is r)
        job.stop()                               # after the end: nothing happens
        self.assertTrue(job.poll())

    def test_failed_run_says_why(self):
        self.mode("fail")
        job = self.start()
        work = job.work
        self.assertEqual(self.wait(job), False)
        self.assertEqual(job.code(), "run")
        self.assertTrue("an error of the fake run" in job.error())
        self.assertRaises(ValueError, job.result)
        self.gone(work)

    def test_half_a_result_is_no_result(self):
        self.mode("truncated")
        job = self.start()
        self.assertEqual(self.wait(job), False)
        self.assertEqual(job.code(), "run")

    def test_launcher_gone(self):
        os.remove(self.exe)
        try:
            self.start()
        except Refused as e:
            self.assertEqual(e.code, "no_aster")
        else:
            self.fail("no refusal")

    def test_returns_at_once_and_stop_ends_the_tree(self):
        self.mode("slow")
        before = self.pings()
        t0 = time.time()
        job = self.start()
        self.assertTrue(time.time() - t0 < 2.0, "start blocks")
        work = job.work
        self.assertTrue(job.poll() is None)
        end = time.time() + 20
        while not (self.pings() - before) and time.time() < end:
            time.sleep(0.05)
        mine = self.pings() - before
        self.assertTrue(mine, "no ping below the job")
        # A process of somebody else, same program, must survive
        other = subprocess.Popen(["ping", "-n", "30", "127.0.0.1"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=0x08000000)       # no console window
        try:
            job.stop()
            self.assertEqual(job.poll(), False)
            self.assertEqual(job.code(), "stopped")
            left = self.pings()
            self.assertFalse(mine & left, "the tree of the job lives on")
            self.assertTrue(other.pid in left, "another process was killed")
            self.gone(work)
        finally:
            subprocess.Popen(["taskkill", "/F", "/PID", str(other.pid)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=0x08000000).communicate()
            other.wait()

    def pings(self):
        """Numbers of the running ping processes."""
        path = os.path.join(self.folder, "tasks.txt")
        p = subprocess.Popen('cmd /c "tasklist /FI "IMAGENAME eq PING.EXE" /FO CSV /NH > tasks.txt"',
                             cwd=self.folder, creationflags=0x08000000)
        p.wait()
        with open(path, "rb") as f:
            out = f.read().decode("ascii", "replace")
        found = set()
        for line in out.splitlines():
            parts = line.split('","')
            if len(parts) > 1 and parts[1].isdigit():
                found.add(int(parts[1]))
        return found

    def test_timeout_kills_and_says_so(self):
        self.mode("slow")
        job = self.start(timeout=1.5)
        work = job.work
        self.assertEqual(self.wait(job, 15), False)
        self.assertEqual(job.code(), "timeout")
        self.gone(work)

    def test_fingerprint_mismatch_ends_the_job(self):
        self.mode("ok")
        self.mesh["nodes"][1] = (0.5, 0.0, 0.0)
        job = self.start()
        self.assertEqual(self.wait(job), False)
        self.assertEqual(job.code(), "fingerprint")
        self.assertTrue(job._process is None, "a process was started")

    def test_stop_before_the_process_leaves_nothing(self):
        self.mode("ok")
        entered = threading.Event()
        go_on = threading.Event()
        real = fb_aster.mesh_fingerprint

        def slow(nodes, element_ids):
            entered.set()
            go_on.wait(20)
            return real(nodes, element_ids)
        fb_aster.mesh_fingerprint = slow
        try:
            job = self.start()
            work = job.work
            self.assertTrue(entered.wait(10))
            job.stop()
            self.assertEqual(job.code(), "stopped")
            go_on.set()
            job._thread.join(20)
        finally:
            fb_aster.mesh_fingerprint = real
            go_on.set()
        self.assertTrue(job._process is None, "a process was started after the stop")
        self.gone(work)

    def test_launcher_that_does_not_tell_its_version(self):
        self.mode("ok")
        other = os.path.join(self.root, "tools")
        os.makedirs(other)
        exe = os.path.join(other, "run_aster.bat")
        shutil.copy(self.exe, exe)
        try:
            fb_aster.start(self.man, self.runs, self.plan, self.mesh, exe, self.scratch)
        except Refused as e:
            self.assertEqual(e.code, "launcher_version")
            self.assertEqual(e.detail, exe)
        else:
            self.fail("no refusal")

    def test_other_version_names_the_run_version(self):
        self.mode("ok")
        self.man["aster_version"] = "16.9"
        try:
            self.start()
        except Refused as e:
            self.assertEqual((e.code, e.detail), ("version", "16.9"))
        else:
            self.fail("no refusal")

    def test_refused_before_anything_starts(self):
        self.mode("ok")
        self.man["not_shared"] = ["contact"]
        self.assertRaises(Refused, self.start)
        self.man["not_shared"] = []
        self.man["aster_version"] = "16.9"
        self.assertRaises(Refused, self.start)
        self.assertFalse(os.path.isdir(self.scratch) and os.listdir(self.scratch))

    def test_missing_component_refused_at_start(self):
        self.mode("ok")
        self.man["solver"] = "STAT_NON_LINE"
        self.man["deformation_by_component"] = {"Q": "GDEF_LOG"}
        try:
            self.start()
        except Refused as e:
            self.assertEqual(e.code, "deformation")
        else:
            self.fail("no refusal")

    def test_no_cut_is_refused(self):
        self.mode("ok")
        self.plan = dict(self.plan, cut_nodes=[], groups=[])
        self.assertRaises(Refused, self.start)

    def test_only_the_own_folder_goes(self):
        self.mode("ok")
        os.makedirs(self.scratch)
        keep = os.path.join(self.scratch, "keep.txt")
        with open(keep, "wb") as f:
            f.write(b"x")
        self.assertTrue(self.wait(self.start()))
        self.assertTrue(os.path.isfile(keep))

    def test_temp_folder_of_the_run_is_its_own(self):
        self.mode("slow")
        job = self.start(timeout=2.0)
        seen = os.path.join(job.work, "temp_seen.txt")
        end = time.time() + 10
        while not os.path.isfile(seen) and time.time() < end:
            time.sleep(0.02)
        with open(seen, "r") as f:
            text = f.read()
        self.assertTrue(os.path.basename(job.work) in text)
        job.stop()

    def test_two_runs_side_by_side(self):
        self.mode("ok")
        jobs = [self.start(), self.start()]
        self.assertNotEqual(jobs[0].work, jobs[1].work)
        self.assertTrue(self.wait(jobs[0]))
        self.assertTrue(self.wait(jobs[1]))


class JobInStrangeFolder(FakeRun):
    """Spaces and non-ASCII characters in every path."""
    place = NON_ASCII

    def test_good_run(self):
        self.mode("ok")
        job = self.start()
        self.assertTrue(self.wait(job), job.error())
        self.assertEqual(len(job.result()["nodes"]), 2)

    def test_stop(self):
        self.mode("slow")
        job = self.start()
        work = job.work
        end = time.time() + 10
        while job._process is None and time.time() < end:
            time.sleep(0.02)
        job.stop()
        self.assertEqual(job.poll(), False)
        self.gone(work)


# ---- phase 4: schema 2, shells and beams --------------------------------------------------
def frame_model():
    """A plate of three quad4 (1..3) along x and a line of three line2 (4..6)
    along y from the far corner; components S (shells) and B (beams). The
    middle of each is selected."""
    b = Builder()
    for i in range(3):
        b.element("quad4", [b.node(p) for p in ((i, 0, 0), (i + 1, 0, 0), (i + 1, 1, 0), (i, 1, 0))])
    for j in range(3):
        b.element("line2", [b.node((5.0, float(j), 0.0)), b.node((5.0, float(j + 1), 0.0))])
    mesh = b.mesh
    mesh["component"] = {1: "S", 2: "S", 3: "S", 4: "B", 5: "B", 6: "B"}
    return mesh, fb_core.plan_cuts(mesh, [2, 5])


def manifest2(mesh, **changes):
    man = manifest(mesh, schema=2, cells=["M1", "M2", "M3", "M4", "M5", "M6"], skin={},
                   not_shared={}, coef_rigi_drz=None,
                   components={"S": {"model": "DKT", "has_warping": False},
                               "B": {"model": "POU_D_E", "has_warping": False,
                                     "section": {"cara": ["HY", "HZ"], "vale": [0.02, 0.04],
                                                 "shape": "RECTANGLE"}}},
                   beam_axes={"M5": [[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]},
                   excentrement={"2": 0.001})
    man.update(changes)
    return man


class Schema2(Files):
    def setUp(self):
        Files.setUp(self)
        self.mesh, self.plan = frame_model()
        os.makedirs(os.path.join(self.folder, "m_20261107_120000_base"))
        with open(os.path.join(self.folder, "m_20261107_120000_base", "glob.1"), "wb") as f:
            f.write(b"x")

    def code(self, **changes):
        return fb_aster.refuse(manifest2(self.mesh, **changes), "17.4", folder=self.folder)

    def test_good_run(self):
        self.assertTrue(self.code() is None)

    def test_schema_keys(self):
        self.assertEqual(self.code(components=None), "schema")
        self.assertEqual(self.code(not_shared=["contact"]), "schema")
        self.assertEqual(self.code(schema=3), "schema")
        self.assertEqual(self.code(schema=True), "schema")
        # schema 2 names nodes: refuse() leaves them to check_plan()
        self.assertTrue(self.code(not_shared={"constraint": {"nodes": [1], "origin": "user"}})
                        is None)

    def test_schema_1_offset(self):
        mesh, plan = tiny_model()
        man = manifest(mesh, not_shared=["offset", "contact"])
        self.assertEqual(fb_aster.refuse(man, "17.4"), "offset")
        man = manifest(mesh, not_shared="contact")
        self.assertEqual(fb_aster.refuse(man, "17.4"), "schema")

    def check(self, man, plan=None):
        return fb_aster.check_plan(man, plan or self.plan, self.mesh)

    def refused(self, man, plan=None):
        try:
            self.check(man, plan)
        except Refused as e:
            return e.code
        return None

    def test_schema_old(self):
        man = manifest(self.mesh)
        self.assertEqual(self.refused(man), "schema_old")
        # solids with schema 1 stay fine
        mesh, plan = tiny_model()
        self.assertEqual(fb_aster.check_plan(manifest(mesh), plan, mesh),
                         {"warnings": [], "drilling": []})

    def test_clean(self):
        self.assertEqual(self.check(manifest2(self.mesh)), {"warnings": [], "drilling": []})

    def test_components(self):
        man = manifest2(self.mesh)
        del man["components"]["B"]
        self.assertEqual(self.refused(man), "schema")
        man = manifest2(self.mesh)
        man["components"]["S"]["model"] = "POU_D_E"        # a shell as a beam
        self.assertEqual(self.refused(man), "shape")
        man = manifest2(self.mesh)
        man["components"]["B"]["model"] = "DIS_T"            # a spring: not measured
        self.assertEqual(self.refused(man), "shape")
        man = manifest2(self.mesh)
        man["components"]["S"]["model"] = "Q4G"
        self.assertEqual(self.refused(man), "shape")
        # a solid of 3D_SI is no reason
        mesh, plan = tiny_model()
        man = manifest(mesh, schema=2, components={"P": {"model": "3D_SI"}}, not_shared={})
        self.assertEqual(fb_aster.check_plan(man, plan, mesh), {"warnings": [], "drilling": []})

    def test_truss_part(self):
        # a component that mixes beams and trusses: the trusses from truss_part
        man = manifest2(self.mesh)
        man["components"]["B"]["truss_part"] = {
            "model": "BARRE", "has_warping": False, "elements": [5],
            "section": {"cara": ["A"], "vale": [3e-5], "shape": "GENERALE"}}
        man["components"]["B"]["model"] = "POU_D_TG"          # the beams only
        self.assertTrue(self.refused(man) is None)
        props = fb_aster.manifest_props(man, self.mesh, [5])
        self.assertEqual(props[5]["model"], "BARRE")
        self.assertTrue(props[5]["truss"])
        self.assertEqual(props[5]["section"]["A"], 3e-5)
        plan = fb_core.plan_cuts(self.mesh, [4])
        self.assertEqual(self.refused(man, plan), "beam_warping")

    def test_groups_per_connection(self):
        # the bridge gives nodes per kind and groups per connection: a
        # line3truss in the selection next to one elsewhere is no refusal
        cut = self.plan["cut_nodes"]
        beam = self.mesh["elements"][5][1]
        far = [n for n in self.mesh["elements"][6][1] if n not in cut]
        entry = {"nodes": sorted(set(beam + far)), "groups": [beam, far], "origin": "bridge"}
        man = manifest2(self.mesh, not_shared={"line3truss": entry})
        self.assertEqual(self.check(man)["warnings"], ["relation_on_cut", "not_shared"])
        # by the union alone it would be refused
        del entry["groups"]
        self.assertEqual(self.refused(man), "not_shared_on_cut")

    def test_beam_warping_and_large_rotation(self):
        man = manifest2(self.mesh)
        man["components"]["B"]["model"] = "POU_D_TG"
        self.assertEqual(self.refused(man), "beam_warping")
        man = manifest2(self.mesh)
        man["components"]["B"]["has_warping"] = True
        self.assertEqual(self.refused(man), "beam_warping")
        man = manifest2(self.mesh)
        man["components"]["B"]["model"] = "POU_D_T_GD"
        self.assertEqual(self.refused(man), "beam_large_rotation")
        man = manifest2(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                        deformation_by_component={"B": "GROT_GDEP", "S": "PETIT"})
        self.assertEqual(self.refused(man), "beam_large_rotation")
        # a linear run is small everywhere; a truss with GROT_GDEP is no refusal
        man = manifest2(self.mesh, deformation_by_component={"B": "GROT_GDEP"})
        self.assertTrue(self.refused(man) is None)
        man = manifest2(self.mesh, solver="STAT_NON_LINE",
                        deformation_by_component={"B": "GROT_GDEP", "S": "PETIT"})
        man["components"]["B"]["model"] = "CABLE"
        self.assertTrue(self.refused(man) is None)
        # a beam outside the selection does not matter
        plan = fb_core.plan_cuts(self.mesh, [2])
        man = manifest2(self.mesh)
        man["components"]["B"]["model"] = "POU_D_TG"
        self.assertTrue(self.refused(man, plan) is None)

    def ns(self, kind, nodes, origin="user"):
        return manifest2(self.mesh, not_shared={kind: {"nodes": nodes, "origin": origin}})

    def test_not_shared(self):
        cut = self.plan["cut_nodes"]
        own = self.mesh["elements"][2][1]
        far = [n for n in self.mesh["elements"][3][1] if n not in cut]
        inner = [n for n in own if n not in cut]
        self.assertEqual(inner, [])          # the middle quad has cut nodes only
        # a tie far from the cut: a warning
        # on shell nodes: the drilling warning too
        self.assertEqual(self.check(self.ns("bonded", far))["warnings"], ["not_shared", "drilling"])
        # on a cut node and outside: a refusal
        self.assertEqual(self.refused(self.ns("constraint", [cut[0], far[0]])),
                         "not_shared_on_cut")
        # a relation of the bridge wholly in the selection (line3truss): no refusal
        beam = self.mesh["elements"][5][1]
        self.assertEqual(self.check(self.ns("constraint", beam, "bridge"))["warnings"],
                         ["relation_on_cut"])
        # per connection: one far, one in the selection
        got = self.check(self.ns("constraint", [far[:2], beam]))
        self.assertEqual(got["warnings"], ["not_shared", "relation_on_cut", "drilling"])
        # no node list: refused, the reader cannot tell
        man = manifest2(self.mesh, not_shared={"contact": {"origin": "user"}})
        self.assertEqual(self.refused(man), "not_shared")
        man = manifest2(self.mesh, not_shared={"contact": {"nodes": "x"}})
        self.assertEqual(self.refused(man), "not_shared")
        man = manifest2(self.mesh, not_shared={"contact": {"nodes": [["a"]]}})
        self.assertEqual(self.refused(man), "not_shared")

    def test_offset(self):
        own = self.mesh["elements"][2][1]
        far = self.mesh["elements"][3][1]
        self.assertEqual(self.refused(self.ns("offset", own[:1])), "offset")
        far_only = [n for n in far if n not in self.plan["cut_nodes"]]
        self.assertEqual(self.check(self.ns("offset", far_only))["warnings"], ["not_shared", "drilling"])

    def test_coupling_on_a_shell_is_drilling(self):
        far = [n for n in self.mesh["elements"][3][1] if n not in self.plan["cut_nodes"]]
        got = self.check(self.ns("coupling", far))
        self.assertEqual(got["drilling"], ["coupling"])
        self.assertTrue("drilling" in got["warnings"])
        # a coupling on the beam only: no drilling
        beam_far = self.mesh["elements"][6][1][1:]
        self.assertEqual(self.check(self.ns("coupling", beam_far))["drilling"], [])

    def test_props(self):
        man = manifest2(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                        deformation_by_component={"S": "GREEN_LAGRANGE", "B": "PETIT"})
        props = fb_aster.manifest_props(man, self.mesh, [2, 5])
        self.assertEqual(props[2]["model"], "DKT")
        self.assertEqual(props[2]["offset"], 0.001)
        self.assertTrue(props[2]["large"])
        self.assertFalse(props[5]["large"])
        self.assertFalse(props[5]["truss"])
        self.assertEqual(props[5]["beam_axes"]["M"], ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0),
                                                      (0.0, 0.0, 1.0)))
        self.assertFalse("H" in props[5]["beam_axes"])
        self.assertTrue(abs(props[5]["section"]["A"] - 8e-4) < 1e-18)
        # with E from Mecway the geometry of the beam cut at node 2
        props[5]["E"] = 210e9
        groups = [g for g in self.plan["groups"] if g["kind"] == "beam"]
        geo = fb_core.section_geometry(self.mesh, groups[1], props)
        self.assertEqual(geo["beams"][0]["end"], 2)
        self.assertEqual(geo["axes"], ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertTrue(abs(geo["inertia"][0] - 0.02 * 0.04 ** 3 / 12) < 1e-20)
        # linear: nothing is large
        props = fb_aster.manifest_props(manifest2(self.mesh), self.mesh, [2, 5])
        self.assertFalse(props[2]["large"])


class Sections(unittest.TestCase):
    def close(self, a, b, tol=1e-15):
        self.assertTrue(abs(a - b) <= tol * max(1.0, abs(b)), (a, b))

    def test_rectangle(self):
        s = fb_aster.section_values({"cara": ["HY", "HZ"], "vale": [0.02, 0.04],
                                     "shape": "RECTANGLE"})
        self.close(s["A"], 8e-4)
        self.close(s["IY"], 0.02 * 0.04 ** 3 / 12)
        self.close(s["IZ"], 0.04 * 0.02 ** 3 / 12)
        # J of a 2:1 rectangle: 0.2287 a b^3 (Roark: 0.229)
        self.assertTrue(abs(s["JX"] / (0.04 * 0.02 ** 3) - 0.2287) < 1e-3)
        s = fb_aster.section_values({"cara": ["H"], "vale": [0.03]})
        self.close(s["A"], 9e-4)

    def test_tube_and_circle(self):
        s = fb_aster.section_values({"cara": ["HY", "HZ", "EP"], "vale": [0.1, 0.2, 0.01]})
        self.close(s["A"], 0.1 * 0.2 - 0.08 * 0.18)
        self.close(s["IY"], (0.1 * 0.2 ** 3 - 0.08 * 0.18 ** 3) / 12)
        s = fb_aster.section_values({"cara": ["R"], "vale": [0.05], "shape": "CERCLE"})
        self.close(s["A"], math.pi * 0.0025)
        self.close(s["IY"], math.pi / 4 * 0.05 ** 4)
        self.close(s["JX"], math.pi / 2 * 0.05 ** 4)
        s = fb_aster.section_values({"cara": ["R", "EP"], "vale": [0.05, 0.01]})
        self.close(s["A"], math.pi * (0.05 ** 2 - 0.04 ** 2))

    def test_general_cable_tapered(self):
        s = fb_aster.section_values({"cara": ["A", "IY", "IZ", "JX"],
                                     "vale": [1e-3, 2e-6, 3e-6, 4e-6], "shape": "GENERALE"})
        self.assertEqual((s["A"], s["IY"], s["IZ"], s["JX"]), (1e-3, 2e-6, 3e-6, 4e-6))
        self.assertFalse("end2" in s)
        s = fb_aster.section_values({"cara": ["AIRE"], "vale": [5e-5], "shape": None})
        self.assertEqual(s["A"], 5e-5)
        s = fb_aster.section_values({"cara": ["SECTION"], "vale": [5e-5]})
        self.assertEqual(s["A"], 5e-5)
        s = fb_aster.section_values({"cara": ["HY1", "HZ1", "HY2", "HZ2"],
                                     "vale": [0.02, 0.04, 0.01, 0.04]})
        self.close(s["A"], 8e-4)
        self.close(s["end2"]["A"], 4e-4)

    def test_bad(self):
        for bad in (None, {}, {"cara": ["HY"], "vale": []}, {"cara": ["A"], "vale": ["x"]},
                    {"cara": ["TOTO"], "vale": [1.0]}):
            self.assertTrue(fb_aster.section_values(bad)["A"] is None, repr(bad))


class Moments(unittest.TestCase):
    """rest and on_cut count moments with |m| / L (contract, Phase 4)."""

    def beam_cut(self, moment, top, lever=2.0, solver="MECA_STATIQUE"):
        # one cut node at the origin carrying a pure moment; L = 2
        result = {"forces": {1: [(0.0, 0.0, 0.0) + tuple(moment)]},
                  "nodes": [{"xyz": (0.0, 0.0, 0.0), "large": False}],
                  "disp": {1: [(0.0, 0.0, 0.0)]}, "lever": lever,
                  "on_cut": {1: {"totals": [(0.0,) * 6]}},
                  "rest": {1: {"sum": (0.0,) * 6, "largest": 0.0, "cut_largest": 0.0,
                               "cut_largest_moment": math.sqrt(sum(m * m for m in moment)),
                               "top": top, "tolerance": None, "count": 0, "where": []}}}
        fb_aster.judge_rest(result, {1: [0]}, fb_aster.REST_NOISE[solver])
        return result

    def test_pure_bending_has_a_tolerance(self):
        r = self.beam_cut((0.0, 0.0, 100.0), [])
        # 1e-4 x 100 N.m / 2 m, above the floor
        self.assertTrue(abs(r["rest"][1]["tolerance"] - 5e-3) < 1e-15)
        r = self.beam_cut((0.0, 0.0, 100.0), [], solver="STAT_NON_LINE")
        # the noise 1e-5 x 100 / 2 stays below it
        self.assertTrue(abs(r["rest"][1]["tolerance"] - 5e-3) < 1e-15)

    def test_noise_on_the_moments(self):
        # nonlinear: noise 1e-5 x max(F_max, M_max / L) beats 1e-4 x the cut
        result = {"forces": {1: [(0.0, 0.0, 0.0, 0.0, 0.0, 1.0)]},
                  "nodes": [{"xyz": (0.0, 0.0, 0.0), "large": False}],
                  "disp": {1: [(0.0, 0.0, 0.0)]}, "lever": 0.5,
                  "on_cut": {1: {"totals": [(0.0,) * 6]}},
                  "rest": {1: {"sum": (0.0,) * 6, "largest": 0.0, "cut_largest": 0.0,
                               "cut_largest_moment": 1000.0, "top": [], "tolerance": None,
                               "count": 0, "where": []}}}
        fb_aster.judge_rest(result, {1: [0]}, 1e-5)
        self.assertTrue(abs(result["rest"][1]["tolerance"] - 1e-5 * 1000.0 / 0.5) < 1e-15)

    def test_on_cut_counts_a_nodal_moment(self):
        result = {"forces": {1: [(10.0, 0.0, 0.0, 0.0, 0.0, 0.0)]},
                  "nodes": [{"xyz": (0.0, 0.0, 0.0), "large": False}],
                  "disp": {1: [(0.0, 0.0, 0.0)]}, "lever": 2.0,
                  "on_cut": {1: {"totals": [(0.0, 0.0, 0.0, 0.0, 6.0, 0.0)]}},
                  "rest": {1: {"sum": (0.0,) * 6, "largest": 0.0, "cut_largest": 10.0,
                               "top": [], "tolerance": None, "count": 0, "where": []}}}
        fb_aster.judge_rest(result, {1: [0]}, 1e-10)
        entry = result["on_cut"][1]
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["largest"], 3.0)
        self.assertEqual(entry["sum"], (0.0, 0.0, 0.0, 0.0, 6.0, 0.0))

    def test_lever_from_the_run(self):
        d = dict(RESULT, lever=0.25)
        r = fb_aster.decode_result(result_text(d), False, [], 1.0)
        self.assertEqual(r["lever"], 0.25)
        # a result of format 1: the extent of the cut nodes
        r = fb_aster.decode_result(result_text(), False, [], 1.0)
        self.assertTrue(abs(r["lever"] - math.sqrt(0.81 + 3.24 + 7.29)) < 1e-12)

    def test_comm_counts_moments(self):
        mesh, plan = tiny_model()
        text = fb_aster.comm_text(manifest(mesh))
        compile(text, "run.comm", "exec")
        self.assertTrue("fb_lever" in text and "cut_largest_moment" in text)
        self.assertTrue("DRX" in text and "DRZ" in text)
        # never one array of all selection nodes against all cut nodes
        self.assertTrue("fb_rows" in text)


class Prepare(FakeRun):
    """The hook of the node cut: prepare() between reading and judging."""

    def test_prepare_sees_the_result_first(self):
        self.mode("ok")
        seen = []

        def prepare(result):
            seen.append(len(result["nodes"]))
            out = dict(result)
            out["nodes"] = result["nodes"][:1]
            for key in ("forces", "disp"):
                out[key] = dict((k, v[:1]) for k, v in result[key].items())
            out["on_cut"] = dict((k, {"totals": v["totals"][:1]}) for k, v in result["on_cut"].items())
            out["rest"] = dict((k, dict(v, valid=False)) for k, v in result["rest"].items())
            return out
        job = self.start(prepare=prepare)
        self.assertTrue(self.wait(job))
        r = job.result()
        self.assertEqual(seen, [2])
        self.assertEqual(len(r["nodes"]), 1)
        # linked after the filter: the one node has its Mecway number
        self.assertTrue("nid" in r["nodes"][0])
        # a partial section: rest is no equilibrium, on_cut is judged
        self.assertTrue(r["rest"][1]["count"] is None)
        self.assertEqual(r["rest"][1]["where"], [])
        self.assertTrue(r["rest"][1]["tolerance"] > 0)
        self.assertEqual(r["on_cut"][1]["count"], 0)
        self.assertFalse("totals" in r["on_cut"][1])

    def test_a_refusal_of_prepare_comes_out_of_result(self):
        self.mode("ok")

        def prepare(result):
            raise Refused("node_mismatch", "a full section lost a node")
        job = self.start(prepare=prepare)
        self.assertTrue(self.wait(job))
        try:
            job.result()
        except Refused as e:
            self.assertEqual(e.code, "node_mismatch")
        else:
            self.fail("no refusal")


class ReviewFixes(Schema2):
    def test_empty_groups_fall_back_to_nodes(self):
        cut = self.plan["cut_nodes"]
        far = [n for n in self.mesh["elements"][3][1] if n not in cut]
        man = manifest2(self.mesh, not_shared={"constraint": {
            "nodes": [cut[0], far[0]], "groups": [], "origin": "user"}})
        self.assertEqual(self.refused(man), "not_shared_on_cut")

    def test_malformed_keys(self):
        self.assertEqual(self.code(beam_axes=[["M5"]]), "schema")
        self.assertEqual(self.code(excentrement=[1]), "schema")
        man = manifest2(self.mesh, beam_axes={"M5": [[1, 0, 0], [0, 1, 0]]})
        props = fb_aster.manifest_props(man, self.mesh, [5])
        self.assertFalse("beam_axes" in props[5])
        man = manifest2(self.mesh, beam_axes={"M5": [[1, 0, 0], [0, 1, 0], ["x", 0, 1]]})
        self.assertFalse("beam_axes" in fb_aster.manifest_props(man, self.mesh, [5])[5])

    def test_component_missing_in_the_table(self):
        man = manifest2(self.mesh, solver="STAT_NON_LINE", deformation="GROT_GDEP",
                        deformation_by_component={"S": "PETIT"})
        self.assertTrue(fb_aster.manifest_props(man, self.mesh, [5])[5]["large"])
        self.assertEqual(self.refused(man), "deformation")

    def test_lever_must_be_finite(self):
        d = dict(RESULT, lever=float("inf"))
        self.assertRaises(ValueError, fb_aster.decode_result, result_text(d), False, [], 1.0)


class Messages(unittest.TestCase):
    """The short text of a failed run: error lines of either file win, else
    the tail of the Code-Aster messages, not of the console."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="fb_msg_")

    def tearDown(self):
        shutil.rmtree(self.folder, True)

    def write(self, name, text):
        path = os.path.join(self.folder, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_tail_of_the_messages_stays(self):
        mess = self.write("m.mess", u"start\nstep 3 of 5\nthe solver stopped here\n")
        console = self.write("c.txt", u"console line\nexit code 1\n")
        self.assertEqual(fb_aster._messages(mess, console),
                         "start / step 3 of 5 / the solver stopped here")

    def test_error_lines_of_the_console_win(self):
        mess = self.write("m.mess", u"start\nnothing odd\n")
        console = self.write("c.txt", u"! <F> <JEVEUX_62> out of memory !\nend\n")
        self.assertEqual(fb_aster._messages(mess, console), "<F> <JEVEUX_62> out of memory")

    def test_no_messages_file(self):
        console = self.write("c.txt", u"a\nb\n")
        self.assertEqual(fb_aster._messages(os.path.join(self.folder, "none"), console), "a / b")


def _bridge_repo():
    """The bridge repository next to this repository or next to a folder
    above it, or None."""
    folder = os.path.dirname(os.path.abspath(os.path.join(HERE, "..")))
    for _ in range(6):
        path = os.path.join(folder, "MecwayAsterBridge")
        if os.path.isdir(path):
            return path
        up = os.path.dirname(folder)
        if up == folder:
            break
        folder = up
    return None


class BridgeCopies(unittest.TestCase):
    """Rules copied from the bridge stay the same as the bridge's own code on
    its branch develop. Read with git show only: the work tree of the bridge
    is not touched. Skipped without the bridge, git or that branch, and in
    IronPython."""

    @classmethod
    def setUpClass(cls):
        cls.repo = None
        if sys.platform == "cli":
            return
        repo = _bridge_repo()
        if repo is None:
            return
        try:
            subprocess.check_output(["git", "-C", repo, "rev-parse", "--verify", "-q",
                                     "develop"], stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError):
            return
        cls.repo = repo

    def setUp(self):
        if self.repo is None:
            self.skipTest("no MecwayAsterBridge with a branch develop next to this repository")

    def source(self, name):
        out = subprocess.check_output(["git", "-C", self.repo, "show",
                                       "develop:Scripts/" + name])
        return out.decode("utf-8")

    def bridge(self, name, names):
        """The top-level functions and assignments of a bridge file with these
        names, run in their own namespace."""
        import ast
        tree = ast.parse(self.source(name))
        body = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                body.append(node)
            elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in names for t in node.targets):
                body.append(node)
        space = {"os": os, "re": __import__("re"), "math": math, "hashlib": hashlib}
        exec(compile(ast.Module(body=body, type_ignores=[]), name, "exec"), space)
        missing = [n for n in names if n not in space]
        self.assertEqual(missing, [], "not in the bridge's {0}".format(name))
        return space

    def test_model_stem_and_folder_beside_the_model(self):
        import fb_mecway
        b = self.bridge("bridge_utils.py", ("model_stem", "model_work_dir", "MODEL_DIR_SUFFIX"))
        for path in (u"C:\\m\\Mijn Model (v2).liml", u"bar.liml", u"", None, u"__a__.liml",
                     u"x\\sp\u00e4tie.liml", u"a.b.c.liml", u"-x-.liml", u"C:\\m\\.liml"):
            self.assertEqual(fb_mecway.model_stem(path), b["model_stem"](path), repr(path))
        for path in (u"C:\\m\\Mijn Model.liml", u"C:\\m\\bar.liml"):
            self.assertEqual(fb_mecway.beside_model_folder(path), b["model_work_dir"](path))

    def test_fingerprint(self):
        b = self.bridge("bridge_manifest.py", ("_nano", "mesh_fingerprint", "MANIFEST_SUFFIX"))
        nodes = {3: (0.1, -0.2, 1e-10), 1: (1.0000000005, 2.0, -3.4999999995), 12: (0.0, 0.0, 0.0)}
        for eids in ([5, 2, 9], []):
            self.assertEqual(fb_aster.mesh_fingerprint(nodes, eids),
                             b["mesh_fingerprint"](nodes, eids))
        self.assertEqual(fb_aster.MANIFEST_SUFFIX, b["MANIFEST_SUFFIX"])

    def test_version_from_launcher(self):
        b = self.bridge("bridge_version.py", ("_DOTTED_RE", "aster_version_from_launcher"))
        for path in ("C:\\x y\\code_aster\\v2025\\17.4\\bin\\run_aster.bat",
                     "C:/a/17.4.0/bin/run_aster.bat", "C:\\a\\17\\bin\\run_aster.bat",
                     "C:\\a\\v17.4\\bin\\run_aster.bat", "C:\\tools\\run_aster.bat",
                     "bin\\run_aster.bat", "", None):
            self.assertEqual(fb_aster.version_from_launcher(path),
                             b["aster_version_from_launcher"](path), repr(path))

    def test_settings_are_read_as_the_bridge_has_them(self):
        import ast
        import fb_mecway
        text = self.source("bridge_utils.py")
        tree = ast.parse(text)
        config = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "CONFIG_BRIDGE" for t in node.targets):
                config = node.value
        self.assertTrue(isinstance(config, ast.Dict), "CONFIG_BRIDGE is no dict literal")
        values = {}
        for key, value in zip(config.keys, config.values):
            if isinstance(key, ast.Constant) and key.value in (
                    "exe_aster", "work_dir", "work_dir_beside_model"):
                values[key.value] = ast.literal_eval(value)
        self.assertEqual(len(values), 3, values)
        folder = tempfile.mkdtemp(prefix="fb_bridge_")
        try:
            path = os.path.join(folder, "bridge_utils.py")
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(text)
            got = fb_mecway.read_bridge_settings(path)
        finally:
            shutil.rmtree(folder, True)
        self.assertEqual(got, {"exe": values["exe_aster"], "work_dir": values["work_dir"],
                               "beside_model": values["work_dir_beside_model"]})


if __name__ == "__main__":
    unittest.main()
