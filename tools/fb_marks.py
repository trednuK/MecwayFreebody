# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_marks.py
# The numbered markers of the images in the user guide: per image the parts in
# the order of their numbers (1, 2, 3 ...). tools/fb_figures.py puts each disc
# at its part; tests/test_gui_docs.py checks that the table under each image in
# docs/MecwayFreebody.md and docs/en/MecwayFreebody.md has exactly these
# numbers. Change a list here, then the tables and the images. No clr: this
# file is read by CPython too.

FIGURES = {
    # the panel tab with a cut by elements
    "window_elements": ["tabs", "language", "compute", "mode", "selection", "folder", "run",
                        "run_line", "banner", "view", "axes_note", "table", "sign", "warnings",
                        "arrows", "drawing", "point", "about", "point_boxes", "neutral",
                        "node", "status", "copy", "close"],
    # a cut by nodes on a plane, side -, a partial section
    "window_nodes": ["mode", "side", "selection", "banner", "table", "sign", "warnings",
                     "plane"],
    # an earlier step and arrows written in Mecway
    "window_arrows": ["step", "table", "arrow_mode", "write", "report"],
    # the tab Documentation
    "window_docs": ["tabs", "list", "viewer", "notice", "language"],
}


def keys(name):
    return list(FIGURES[name])


def number(name, key):
    return FIGURES[name].index(key) + 1
