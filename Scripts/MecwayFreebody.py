# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# MecwayFreebody.py
# Entry point of MecwayFreebody: section forces on the cuts of a selected group
# of elements, from a short follow-up run on the Code-Aster base the bridge
# kept. Register it in Mecway under Tools > Scripts and run it on a solved,
# saved model, with or without a selection.
#
# 'mw' and 'solution' exist only in this script's namespace; they are passed to
# fb_gui.run_window, and from there to fb_mecway (the only module that calls
# them, always on this thread).
#
# Modules:
#   fb_gui     : the non-modal window, the drawing
#   fb_mecway  : selection, mesh, solution, arrows, finding the bridge
#   fb_core    : cuts, geometry, resultants, axes, table text
#   fb_aster   : manifests, the follow-up run, reading its result
#   fb_nodecut : a cut by nodes on a plane
#   fb_docs    : the documentation tab (reads docs/ next to this folder)
#
# Compatible with IronPython 2.7.9.

import os
import sys
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
except NameError:
    pass

import fb_gui


def main():
    try:
        current = solution
    except NameError:
        current = None
    token = fb_gui.claim_instance()
    if token is None:
        # Second start while the window is open: bring it forward.
        if not fb_gui.activate_existing():
            mw.message(fb_gui.instance_busy_text())
        return
    try:
        fb_gui.run_window(mw, current)
    except Exception:
        fb_gui.log(u"stopped: {0}".format(traceback.format_exc()))
        mw.message(fb_gui.stopped_text(traceback.format_exc()))
    finally:
        fb_gui.release_instance(token)


main()
