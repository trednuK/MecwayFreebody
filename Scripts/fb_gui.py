# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_gui.py
# Responsibility: the non-modal window of MecwayFreebody.
#   run_window(mw, solution)  show the window until the user closes it
#   claim_instance() / release_instance() / activate_existing()
#                             one window per Mecway process
#   PanelModel                what the window shows, without Windows Forms
#   draw_cut()                the drawing of a cut (System.Drawing)
#   plan_and_start()          the cut and its follow-up run; a cut by nodes on a
#                             plane gives fb_aster.start its filter (prepare)
#
# Two ways to make the cut: the selected elements (fb_core.plan_cuts), or the
# selected nodes on a plane with a side (fb_nodecut.plan_from_nodes; see
# docs/design/knopensnede-plan.md, the rules after the review).
#
# Threads. The window runs on its own STA thread (Application.Run). The script
# thread (Mecway's) keeps Mecway's messages going and runs every mw call
# (_MwCaller): the window only posts requests and looks for the answer in its
# timer, so it never waits for Mecway, and Mecway never waits for the window.
# Reading a mesh is a generator: Mecway answers between its chunks. A python
# thread does the heavy sums (_Worker); it writes its outcome in a slot and
# touches no control. Nothing here opens a message box.
#
# Why the window has its own thread: found in an earlier tool (after a box selection in
# the viewport, buttons of a window on Mecway's own thread stopped responding).
#
# Tabs: the panel, and the documentation (fb_docs) built when first opened.
# Header and footer sit above and below both.
#
# Texts: every user text in Dutch and English; the NL/EN buttons redraw the
# window. Compatible with IronPython 2.7.9; PanelModel and the text functions
# also run in CPython 3 (tests).

import io
import json
import math
import os
import threading
import time
import traceback

import fb_aster
import fb_core
import fb_docs
import fb_mecway
import fb_nodecut

PANEL_TITLE = u"MecwayFreebody"
_INSTANCE_NAME = u"MecwayFreebody_{0}"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPTS_DIR, "fb_settings.json")
LOG_NAME = "MecwayFreebody_log.txt"
# Seconds Mecway may take to answer before the panel says it is busy: longer
# for a whole mesh. A modal dialog of Mecway stops the script thread.
ASK_TIMEOUT = 20.0
READ_TIMEOUT = 300.0
TICK_MS = 200
COMPUTING = ("plan", "run", "finish", "check")
SELECTION_TICKS = 5
GRAB_PX = 16
PLANE_LINE = 20.0       # px under the title of the drawing: the plane of a node cut
TINY = 1e-9             # below this share of the largest value: shown as 0

T = {
    "title": (u"Krachten op de snede", u"Forces on the cut"),
    "sub": (u"Selecteer elementen in Mecway en klik op Bereken.",
            u"Select elements in Mecway and click Compute."),
    "sub_nodes": (u"Selecteer in Mecway de knopen van een vlakke doorsnede en klik op Bereken.",
                  u"Select the nodes of a planar section in Mecway and click Compute."),
    "compute": (u"Bereken", u"Compute"),
    "stop": (u"Stop", u"Stop"),
    "sel_none": (u"Geen elementen geselecteerd", u"No elements selected"),
    "sel_n": (u"{0} elementen geselecteerd", u"{0} elements selected"),
    "sel_faces": (u"Vlakken geselecteerd: kies elementen",
                  u"Faces selected: select elements instead"),
    "sel_nomodel": (u"Geen model bereikbaar", u"No model available"),
    "sel_nodes_n": (u"{0} knopen geselecteerd  ·  kant {1}", u"{0} nodes selected  ·  side {1}"),
    "sel_nodes_none": (u"Geen knopen geselecteerd  ·  kant {0}",
                       u"No nodes selected  ·  side {0}"),
    "folder": (u"Runmap:", u"Run folder:"),
    "f_auto": (u"Zoek overal", u"Look everywhere"),
    "f_model": (u"Naast het model", u"Next to the model"),
    "f_bridge": (u"Werkmap van de bridge", u"Work folder of the bridge"),
    "f_other": (u"Andere map", u"Another folder"),
    "browse": (u"Kies...", u"Choose..."),
    "browse_title": (u"Map met de run van de bridge",
                     u"Folder with the run of the bridge"),
    "run": (u"Run:", u"Run:"),
    "run_item": (u"{0}  ·  {1}  ·  {2}  ·  Code-Aster {3}",
                 u"{0}  ·  {1}  ·  {2}  ·  Code-Aster {3}"),
    "run_used": (u"Gebruikt: {0}  ·  model {1}  ·  map {2}",
                 u"In use: {0}  ·  model {1}  ·  folder {2}"),
    "run_foreign": (u"Run van een ander model ({0}, open is {1}). Er wordt niet vanzelf "
                    u"gerekend; kies een andere run, of klik zelf op Bereken als dit "
                    u"dezelfde mesh en lasten zijn.",
                    u"Run of another model ({0}, open is {1}). Nothing is computed by "
                    u"itself; choose another run, or click Compute yourself if this is "
                    u"the same mesh with the same loads."),
    "run_none": (u"Geen run gevonden met een bewaarde base. Zet in de bridge "
                 u"(V2026.9 of nieuwer) \"Code-Aster-base bewaren\" aan, reken, en "
                 u"sla het model op.",
                 u"No run with a kept base found. Switch on \"keep the "
                 u"Code-Aster base\" in the bridge (V2026.9 or newer), run it, and "
                 u"save the model."),
    "run_other": (u"{0} run(s) gevonden, maar van een ander model: het model is "
                  u"gewijzigd sinds de run. Reken opnieuw met de bridge.",
                  u"{0} run(s) found, but of another model: the model changed "
                  u"since the run. Run the bridge again."),
    "looked": (u"Gezocht in: {0}", u"Looked in: {0}"),
    "b_no_bridge": (u"Bridge niet gevonden: kies zelf een map.",
                    u"Bridge not found: choose a folder yourself."),
    "b_unreadable": (u"Instellingen van de bridge niet leesbaar: kies zelf een "
                     u"map, en zet exe_aster in fb_settings.json.",
                     u"Settings of the bridge not readable: choose a folder "
                     u"yourself, and set exe_aster in fb_settings.json."),
    "b_no_aster": (u"Code-Aster niet gevonden (run_aster.bat): zet exe_aster in "
                   u"fb_settings.json.",
                   u"Code-Aster not found (run_aster.bat): set exe_aster in "
                   u"fb_settings.json."),
    "step": (u"Stap:", u"Step:"),
    "step_item": (u"{0}  ·  t = {1}", u"{0}  ·  t = {1}"),
    "axes": (u"Assen:", u"Axes:"),
    "ax_section": (u"Doorsnede", u"Section"),
    "ax_global": (u"Globaal", u"Global"),
    # the local axes of a cut, by case: radio text, short name in the table, note
    "ax_r_section": (u"Hoofdassen", u"Principal axes"),
    "ax_r_strip": (u"Strook n, t, w", u"Strip n, t, w"),
    "ax_r_beam": (u"Balkassen", u"Beam axes"),
    "ax_r_truss": (u"Staafas", u"Truss axis"),
    "ax_r_global": (u"Eigen assen (hier globaal)", u"Own axes (global here)"),
    "ax_s_section": (u"doorsnede", u"section"),
    "ax_s_strip": (u"strook n,t,w", u"strip n,t,w"),
    "ax_s_beam": (u"balk", u"beam"),
    "ax_s_truss": (u"staaf", u"truss"),
    "ax_s_global": (u"globaal", u"global"),
    "ax_head": (u"Assen", u"Axes"),
    "ax_n_section": (u"Snede {0}: hoofdassen van de doorsnede, y de as met het grootste "
                     u"traagheidsmoment.",
                     u"Cut {0}: principal axes of the section, y the axis with the larger "
                     u"second moment."),
    "ax_n_strip": (u"Snede {0}: één schaalstrook, assen n (in het schaalvlak, uit de "
                   u"selectie), t (langs de ribbe) en w (schaalnormaal). M_w is "
                   u"onbetrouwbaar.",
                   u"Cut {0}: one shell strip, axes n (in the shell plane, out of the "
                   u"selection), t (along the edge) and w (shell normal). M_w is "
                   u"unreliable."),
    "ax_n_beam": (u"Snede {0}: de balkassen x, y, z zoals Code-Aster ze gebruikte. Bij "
                  u"een L-profiel zijn dat de hoofdassen, niet de benen.",
                  u"Cut {0}: the beam axes x, y, z as Code-Aster used them. For an L "
                  u"section these are the principal axes, not the legs."),
    "ax_n_truss": (u"Snede {0}: een staaf (truss of kabel) draagt alleen N langs zijn as.",
                   u"Cut {0}: a truss or cable carries only N along its axis."),
    "ax_n_global": (u"Snede {0} is gemengd, niet vlak of draait mee met grote "
                    u"verplaatsingen: globale assen X, Y, Z.",
                    u"Cut {0} is mixed, not planar or turns with large displacements: "
                    u"global axes X, Y, Z."),
    "ax_n_all_global": (u"Globale assen X, Y, Z voor alle sneden.",
                        u"Global axes X, Y, Z for all cuts."),
    "unit": (u"Eenheid:", u"Unit:"),
    "cut": (u"Snede", u"Cut"),
    "mode": (u"Snede via:", u"Cut by:"),
    "mode_elements": (u"Elementen", u"Elements"),
    "mode_nodes": (u"Knopen op een vlak", u"Nodes on a plane"),
    "mode_tip": (u"Elementen: de snede volgt uit de geselecteerde elementen. Knopen op een "
                 u"vlak: selecteer de knopen van een vlakke doorsnede; het vrije lichaam "
                 u"ligt aan één kant van het vlak, te wisselen met Andere kant.",
                 u"Elements: the cut follows from the selected elements. Nodes on a plane: "
                 u"select the nodes of a planar section; the free body lies at one side of "
                 u"the plane, to switch with Other side."),
    "side_button": (u"Andere kant", u"Other side"),
    "side_tip": (u"Kies het vrije lichaam aan de andere kant van het vlak en reken opnieuw. "
                 u"Zonder last of oplegging op de snedeknopen zijn de resultanten van de twee "
                 u"kanten tegengesteld.",
                 u"Take the free body at the other side of the plane and compute again. "
                 u"Without a load or support on the cut nodes, the resultants of the two sides "
                 u"are opposite."),
    # a cut by nodes on a plane: side, normal, partial section
    "nc_row": (u"{0}  ·  kant {1}", u"{0}  ·  side {1}"),
    "nc_sign": (u"Snede via {0} knopen op een vlak met normaal n = ({1}). Het vrije lichaam "
                u"ligt aan kant {2}, {3}. Zonder last of oplegging op de snedeknopen geeft de "
                u"andere kant precies tegengestelde krachten en momenten.",
                u"Cut by {0} nodes on a plane with normal n = ({1}). The free body lies at "
                u"side {2}, {3}. Without a load or support on the cut nodes, the other side "
                u"gives exactly opposite forces and moments."),
    "nc_plus": (u"waar n heen wijst", u"where n points"),
    "nc_minus": (u"tegen n in", u"against n"),
    "nc_copy": (u"Snede via knopen op een vlak", u"Cut by nodes on a plane"),
    "nc_side": (u"kant", u"side"),
    "nc_normal": (u"normaal n", u"normal n"),
    "nc_partial": (u"deeldoorsnede", u"partial section"),
    "sign": (u"Teken: de kracht van de rest op de selectie. N is positief bij "
             u"trek, langs de normaal naar buiten. Oplegging of koppeling op "
             u"een snedeknoop telt als de rest.",
             u"Sign: the force of the rest on the selection. N is positive in "
             u"tension, along the outward normal. A support or tie on a cut "
             u"node counts as the rest."),
    "sign_base": (u"Teken: de kracht van de rest op de selectie. Oplegging of koppeling "
                  u"op een snedeknoop telt als de rest.",
                  u"Sign: the force of the rest on the selection. A support or tie on "
                  u"a cut node counts as the rest."),
    "sign_section": (u"Doorsnede: N positief bij trek, langs de normaal naar buiten.",
                     u"Section: N positive in tension, along the outward normal."),
    "sign_strip": (u"Strook: n in het schaalvlak, loodrecht op de ribbe, uit het "
                   u"geselecteerde element; t langs de ribbe; w de schaalnormaal, "
                   u"t = w × n. N langs n (positief bij trek), V_t, V_w, T om n, M_t om t, "
                   u"M_w om w (onbetrouwbaar).",
                   u"Strip: n in the shell plane, perpendicular to the edge, out of the "
                   u"selected element; t along the edge; w the shell normal, t = w × n. "
                   u"N along n (positive in tension), V_t, V_w, T about n, M_t about t, "
                   u"M_w about w (unreliable)."),
    "sign_beam": (u"Balk: N positief bij trek, langs de normaal naar buiten. Snede bij "
                  u"knoop 2 van het element: de lokale +x; bij knoop 1: −x, met x en z "
                  u"gespiegeld en y gelijk.",
                  u"Beam: N positive in tension, along the outward normal. Cut at node 2 "
                  u"of the element: the local +x; at node 1: −x, with x and z mirrored "
                  u"and y kept."),
    "sign_truss": (u"Staaf: alleen N, positief bij trek.",
                   u"Truss: N only, positive in tension."),
    "sign_global": (u"Globaal: Fx, Fy, Fz en Mx, My, Mz langs de globale assen.",
                    u"Global: Fx, Fy, Fz and Mx, My, Mz along the global axes."),
    "unreliable": (u"(?)", u"(?)"),
    "eq_wait": (u"Nog niets berekend", u"Nothing computed yet"),
    "eq_wait2": (u"De evenwichtscontrole komt hier te staan.",
                 u"The equilibrium check will show here."),
    "eq_start": (u"Stap 0: de begintoestand", u"Step 0: the starting state"),
    "eq_start2": (u"Dit is de toestand voor de eerste stap, nog geen evenwicht: hier "
                  u"is geen controle. Kies een latere stap.",
                  u"This is the state before the first step, not an equilibrium yet: "
                  u"no check here. Choose a later step."),
    "eq_rest": (u"Rest naast de snede: grootste {0}; som F ({1}) {2}, M ({3}) {4} om de "
                u"oorsprong (0; 0; 0).",
                u"Rest off the cut: largest {0}; sum F ({1}) {2}, M ({3}) {4} about the "
                u"origin (0; 0; 0)."),
    "eq_ok": (u"In evenwicht: de sneden zijn compleet",
              u"In equilibrium: the cuts are complete"),
    "eq_ok2": (u"Op de knopen naast de snede grijpt niets anders aan (grootste "
               u"restkracht {0}).",
               u"Nothing else acts on the nodes off the cut (largest stray "
               u"force {0})."),
    "eq_on_cut": (u"Let op: op {0} snedeknopen grijpt ook een oplegging of koppeling aan, "
                  u"per knoop tot {1}, samen {2}. Dat zit in de kracht van deze snede.",
                  u"Note: on {0} cut nodes a support or coupling acts as well, up to "
                  u"{1} per node, {2} together. That is part of the force of this cut."),
    "eq_partial": (u"Deeldoorsnede: geen evenwichtscontrole",
                   u"Partial section: no equilibrium check"),
    "eq_partial2": (u"De knopen sluiten geen lichaam af; de som is de kracht door het vlak bij "
                    u"deze knopen. De andere knopen van de laag elementen aan deze kant dragen "
                    u"ook kracht, dus de rest naast de snede zegt hier niets over evenwicht, en "
                    u"een tie, oplegging of contact in die laag blijft onzichtbaar. Oppervlak "
                    u"en zwaartepunt passen niet precies bij de som: randknopen dragen een deel "
                    u"van de aangrenzende vlakken mee.",
                    u"The nodes close no body; the sum is the force through the plane at these "
                    u"nodes. The other nodes of the layer of elements at this side carry force "
                    u"too, so the equilibrium check (the forces off the cut) says nothing "
                    u"here, and a tie, support or contact in that layer stays unseen. Area and "
                    u"centroid do not fit the sum exactly: edge nodes carry part of the "
                    u"neighbouring faces."),
    "eq_on_cut_unknown": (u"Of er op de snedeknopen ook een oplegging of koppeling aangrijpt, is "
                          u"bij deze stap niet na te gaan.",
                          u"Whether a support or coupling acts on the cut nodes as well cannot "
                          u"be told at this step."),
    "eq_bad": (u"NIET in evenwicht: er grijpt nog iets anders aan",
               u"NOT in equilibrium: something else acts as well"),
    "eq_bad2": (u"{0} knopen naast de snede dragen tot {1}, samen {2}: een "
                u"oplegging, tie, bonded contact of veer. Deze tabel toont dan "
                u"niet alles. Eerste plek ({3}) mm.",
                u"{0} nodes off the cut carry up to {1}, together {2}: a "
                u"support, tie, bonded contact or spring. This table then does "
                u"not show everything. First place ({3}) mm."),
    "point": (u"Punt:", u"Point:"),
    "p_section": (u"n, y, z in mm vanaf het neutrale punt",
                  u"n, y, z in mm from the neutral point"),
    "p_global": (u"X, Y, Z globaal in mm", u"X, Y, Z global in mm"),
    "p_offset": (u"X, Y, Z in mm vanaf het neutrale punt",
                 u"X, Y, Z in mm from the neutral point"),
    "p_strip": (u"n, t, w in mm vanaf het neutrale punt",
                u"n, t, w in mm from the neutral point"),
    "p_beam": (u"x, y, z van de balk in mm vanaf het neutrale punt",
               u"x, y, z of the beam in mm from the neutral point"),
    "neutral": (u"Neutraal punt", u"Neutral point"),
    "node": (u"Knoop", u"Node"),
    "node_tip": (u"Getypt nummer, anders de geselecteerde knoop in Mecway, "
                 u"anders de dichtstbijzijnde snedeknoop",
                 u"The typed number, else the node selected in Mecway, else "
                 u"the nearest cut node"),
    "node_bad": (u"Knoop {0} bestaat niet.", u"Node {0} does not exist."),
    "node_set": (u"Punt op knoop {0}.", u"Point on node {0}."),
    "num_bad": (u"Dat is geen getal.", u"That is not a number."),
    "arrows": (u"Pijlen in Mecway:", u"Arrows in Mecway:"),
    "a_nodes": (u"Per snedeknoop", u"Per cut node"),
    "a_result": (u"Eén resultante", u"One resultant"),
    "a_write": (u"Schrijf pijlen", u"Write arrows"),
    "a_hint": (u"Zet de oplossing aan en kies external force of reaction "
               u"moment in de boom. De velden komen bij opslaan in het .liml.",
               u"Show the solution and choose external force or reaction "
               u"moment in the tree. The fields go into the .liml when you save."),
    "a_scale": (u"{0}: de legenda in Mecway klopt, grootste {1}.",
                u"{0}: the legend in Mecway is right, largest {1}."),
    "a_rescaled": (u"{0}: de pijlen houden de lengte van de eerste keer; de grootste is "
                   u"{1}, de legenda in Mecway toont nog {2}.",
                   u"{0}: the arrows keep the length of the first time; the largest is "
                   u"{1}, Mecway's legend still shows {2}."),
    "a_exists": (u"{0} bestaat al in de oplossing: overgeslagen. Blijft zo in het "
                 u"paneel.",
                 u"{0} already exists in the solution: skipped. It stays in the "
                 u"panel only."),
    "a_zero": (u"{0} is nul: niet geschreven.", u"{0} is zero: not written."),
    "a_cleared": (u"{0} is hier nul: de eerdere pijlen van dit paneel zijn weggehaald.",
                  u"{0} is zero here: the earlier arrows of this panel are removed."),
    "a_clear_failed": (u"{0} is hier nul, maar de eerdere pijlen van dit paneel konden "
                       u"niet weg: ze staan nog in Mecway.",
                       u"{0} is zero here, but the earlier arrows of this panel could not "
                       u"be removed: they are still in Mecway."),
    "a_inside": (u"Snede {0}: knoop {1} ligt binnen in het volume, achter de buitenkant: "
                 u"de pijl is mogelijk niet te zien. Verberg de elementen aan één kant van "
                 u"de snede, zet het punt op een buitenknoop (Knoop), of schrijf per "
                 u"snedeknoop.",
                 u"Cut {0}: node {1} lies inside the solid, behind its outside: the arrow "
                 u"may not show. Hide the elements at one side of the cut, put the point "
                 u"on an outside node (Node), or write per cut node."),
    "a_place": (u"Snede {0}: resultante staat op knoop {1}, {2} mm van het "
                u"gekozen punt. De getallen blijven om het gekozen punt.",
                u"Cut {0}: the resultant stands on node {1}, {2} mm from the "
                u"chosen point. The numbers stay about the chosen point."),
    "a_same": (u"Snede {0}: resultante staat op knoop {1}, het gekozen punt.",
               u"Cut {0}: the resultant stands on node {1}, the chosen point."),
    "a_lumped": (u"{0} toegevoegde middenknopen staan op de buurknoop (Mecway "
                 u"kent ze niet).",
                 u"{0} added midside nodes stand on the neighbour node (Mecway "
                 u"does not know them)."),
    "a_step": (u"Stap {0} van de vervolgrun.", u"Step {0} of the follow-up run."),
    "a_no_solution": (u"Geen oplossing in Mecway om pijlen in te zetten. Laad de "
                      u"oplossing en start het paneel opnieuw.",
                      u"No solution in Mecway to put arrows in. Load the solution "
                      u"and start the panel again."),
    "a_no_step": (u"De oplossing in Mecway heeft geen stap op dit moment: geen pijlen "
                  u"geschreven.",
                  u"The solution in Mecway has no step at this time: no arrows written."),
    "a_stale": (u"De oplossing is niet meer bereikbaar. Sluit het paneel en "
                u"start het opnieuw.",
                u"The solution can no longer be reached. Close the panel and "
                u"start it again."),
    "a_mesh_differs": (u"De oplossing in Mecway hoort niet bij deze mesh.",
                       u"The solution in Mecway does not belong to this mesh."),
    "a_numbering": (u"De knoopnummers van de oplossing lopen niet door: pijlen "
                    u"kunnen niet worden geplaatst.",
                    u"The node numbers of the solution are not contiguous: arrows "
                    u"cannot be placed."),
    "copy": (u"Kopieer", u"Copy"),
    "copy_img": (u"Kopieer tekening", u"Copy drawing"),
    "csv": (u"Bewaar CSV", u"Save CSV"),
    "close": (u"Sluiten", u"Close"),
    "copied": (u"Tabel gekopieerd (plakbaar in Excel)",
               u"Table copied (pastes into Excel)"),
    "copied_img": (u"Tekening gekopieerd", u"Drawing copied"),
    "copy_fail": (u"Kopiëren mislukt: {0}", u"Copy failed: {0}"),
    "saved": (u"Opgeslagen: {0}", u"Saved: {0}"),
    "csv_title": (u"Tabel opslaan", u"Save table"),
    "csv_filter": (u"CSV (*.csv)|*.csv", u"CSV (*.csv)|*.csv"),
    "reading": (u"Model lezen...", u"Reading the model..."),
    "scanning": (u"Runs zoeken...", u"Looking for runs..."),
    "planning": (u"Snede bepalen...", u"Finding the cuts..."),
    "running": (u"Vervolgrun bezig... {0} s", u"Follow-up run busy... {0} s"),
    "finishing": (u"Resultaat lezen...", u"Reading the result..."),
    "checking": (u"Vergelijken met de oplossing...", u"Comparing with the solution..."),
    "outdated": (u"Resultaat van een eerdere selectie", u"Result of an earlier selection"),
    "done": (u"Klaar: {0} snede(n), vervolgrun {1} s.",
             u"Done: {0} cut(s), follow-up run {1} s."),
    "busy_text": (u"Het venster van MecwayFreebody is al open.",
                  u"The MecwayFreebody window is already open."),
    "stopped_by": (u"MecwayFreebody gestopt door een fout:\n{0}",
                   u"MecwayFreebody stopped by an error:\n{0}"),
    # refusals of a run, of a cut and of the panel
    "r_solver": (u"Deze run is geen statische berekening: alleen lineair en "
                 u"niet-lineair statisch kunnen.",
                 u"This run is not a static analysis: only linear and nonlinear "
                 u"static can be used."),
    "r_version": (u"Deze run komt van een andere Code-Aster-versie ({0}): reken "
                  u"opnieuw met de bridge.",
                  u"This run comes from another Code-Aster version ({0}): run "
                  u"the bridge again."),
    "r_launcher_version": (u"Uit het pad van de Code-Aster-starter is geen versie af te lezen "
                           u"({0}). Verwacht: ...\\<versie>\\bin\\run_aster.bat. Zet exe_aster "
                           u"op zo'n pad: in fb_settings.json als het daar staat (dat gaat "
                           u"voor), anders in de bridge. Aan de run ligt het niet.",
                           u"The Code-Aster version cannot be read from the path of the "
                           u"launcher ({0}). Expected: ...\\<version>\\bin\\run_aster.bat. Set "
                           u"exe_aster to such a path: in fb_settings.json if it is there (that "
                           u"one wins), else in the bridge. The run is not the problem."),
    "r_run_version": (u"Deze run noemt geen Code-Aster-versie: de bridge kon hem niet lezen "
                      u"uit de .mess en niet uit het pad van zijn starter. Zet exe_aster in de "
                      u"bridge op ...\\<versie>\\bin\\run_aster.bat en reken opnieuw met de "
                      u"bridge.",
                      u"This run does not name its Code-Aster version: the bridge could read "
                      u"it neither from the .mess nor from the path of its launcher. Set "
                      u"exe_aster in the bridge to ...\\<version>\\bin\\run_aster.bat and run "
                      u"the bridge again."),
    "r_fingerprint": (u"Het model is gewijzigd sinds deze run: reken opnieuw met "
                      u"de bridge.",
                      u"The model changed since this run: run the bridge again."),
    "r_not_shared": (u"Deze run noemt verbindingen die de snede niet ziet ({0}), zoals "
                     u"contact of een koppeling, maar niet hun knopen: of ze de snede "
                     u"raken, is niet na te gaan, dus geen getallen. Werk zo nodig de "
                     u"bridge bij en reken opnieuw.",
                     u"This run names connections the cut does not see ({0}), such as "
                     u"contact or a coupling, but not their nodes: whether they touch "
                     u"the cut cannot be checked, so no numbers. Update the bridge if "
                     u"needed and run it again."),
    "r_no_base": (u"De base van deze run ontbreekt: reken opnieuw met \"base "
                  u"bewaren\" aan.",
                  u"The base of this run is missing: run the bridge again with "
                  u"\"keep base\" on."),
    "r_schema": (u"Het manifest van deze run is van een onbekende vorm: werk de "
                 u"bridge en MecwayFreebody bij.",
                 u"The manifest of this run has an unknown form: update the "
                 u"bridge and MecwayFreebody."),
    "r_deformation": (u"De run noemt niet voor elke component hoe er gerekend is "
                      u"(klein of grote verplaatsingen).",
                      u"The run does not say for every component how it computed "
                      u"(small or large displacements)."),
    "r_stale": (u"Deze run hoort niet bij de open oplossing: de verplaatsingen "
                u"verschillen (zelfde mesh, andere lasten of een andere solver?). "
                u"Geen tabel. Reken opnieuw met de bridge of kies de juiste run.",
                u"This run does not belong to the open solution: the displacements "
                u"differ (same mesh, other loads or another solver?). No table. Run "
                u"the bridge again or choose the right run."),
    "r_empty": (u"Selecteer eerst elementen in Mecway.",
                u"Select elements in Mecway first."),
    # refusals of a cut by nodes on a plane (fb_nodecut); a key ending in
    # _nodes is the text of a code when the cut is made by nodes
    "r_empty_nodes": (u"Selecteer eerst in Mecway de knopen van een vlakke doorsnede.",
                      u"Select the nodes of a planar section in Mecway first."),
    "r_unknown_node": (u"De geselecteerde knopen passen niet bij de mesh ({0}).",
                       u"The selected nodes do not fit the mesh ({0})."),
    "r_nodes_collinear": (u"Een vlak heeft minstens drie knopen nodig die niet op één lijn "
                          u"liggen ({0}).",
                          u"A plane needs at least three nodes that are not on one line "
                          u"({0})."),
    "r_nodes_without_solid": (u"Er zijn knopen geselecteerd die bij geen volume-element horen "
                              u"({0}). Selecteer knopen van volume-elementen.",
                              u"Some selected nodes belong to no solid element ({0}). Select "
                              u"nodes of solid elements."),
    "r_nodes_not_planar": (u"De knopen liggen niet in één vlak ({0}). Selecteer alleen de knopen "
                           u"van één vlakke doorsnede.",
                           u"The nodes do not lie in one plane ({0}). Select only the nodes of "
                           u"one planar section."),
    "r_plane_through_elements": (u"Het vlak door de knopen loopt door elementen heen ({0}): de "
                                 u"snede moet langs elementvlakken lopen.",
                                 u"The plane through the nodes runs through elements ({0}): the "
                                 u"cut must follow element faces."),
    "r_side_empty": (u"Aan deze kant van de knopen ligt geen element: kies de andere kant.",
                     u"No element lies at this side of the nodes: choose the other side."),
    "r_no_cut_nodes": (u"De rest van het model deelt geen van deze knopen: er is geen snede.",
                       u"The rest of the model shares none of these nodes: there is no cut."),
    "r_shell_or_beam_nodes": (u"Schalen of balken aan de geselecteerde knopen ({0}): een snede "
                              u"via knopen loopt alleen door volume-elementen. Selecteer hier "
                              u"elementen.",
                              u"Shells or beams at the selected nodes ({0}): a cut by nodes "
                              u"runs through solid elements only. Select elements here."),
    "r_node_mismatch_nodes": (u"De knopen van de vervolgrun passen niet bij de snede door de "
                              u"geselecteerde knopen: {0}. Reken opnieuw met de bridge, of "
                              u"selecteer de knopen opnieuw.",
                              u"The nodes of the follow-up run do not fit the cut through the "
                              u"selected nodes: {0}. Run the bridge again, or select the nodes "
                              u"again."),
    "r_unknown_element": (u"De selectie past niet bij de mesh ({0}).",
                          u"The selection does not fit the mesh ({0})."),
    "r_shell_or_beam": (u"De selectie bevat schalen of balken ({0}): dat kan nog "
                        u"niet. Selecteer alleen volume-elementen.",
                        u"The selection holds shells or beams ({0}): not possible "
                        u"yet. Select solid elements only."),
    "r_beam_warping": (u"De selectie raakt balken met welving (POU_D_TG, {0}): de "
                       u"knoopkrachten van dit balktype kloppen niet in Code-Aster, dus "
                       u"geen getallen.",
                       u"The selection touches beams with warping (POU_D_TG, {0}): the "
                       u"nodal forces of this beam type are not right in Code-Aster, so "
                       u"no numbers."),
    "r_beam_large_rotation": (u"De selectie raakt balken met grote rotaties (POU_D_T_GD "
                              u"of GROT_GDEP, {0}): hun assen draaien mee en dat wordt "
                              u"nog niet ondersteund.",
                              u"The selection touches beams with large rotations "
                              u"(POU_D_T_GD or GROT_GDEP, {0}): their axes turn along "
                              u"and that is not supported yet."),
    "r_offset": (u"Het model heeft offsets met verschoven knopen (offset_links, {0}): de "
                 u"snede loopt dan via knopen die de selectie niet deelt, dus geen "
                 u"getallen.",
                 u"The model has offsets with shifted nodes (offset_links, {0}): the cut "
                 u"then runs through nodes the selection does not share, so no numbers."),
    "r_schema_old": (u"De bridge die deze run maakte is te oud voor schalen en balken "
                     u"(manifest schema 1). Werk de bridge bij naar V2026.9 of nieuwer "
                     u"en reken opnieuw.",
                     u"The bridge that made this run is too old for shells and beams "
                     u"(manifest schema 1). Update the bridge to V2026.9 or newer and "
                     u"run it again."),
    "r_not_shared_on_cut": (u"Een verbinding die de snede niet ziet ({0}) zit aan een "
                            u"snedeknoop en ook aan knopen buiten de selectie: de kracht "
                            u"op de snede is dan niet eenduidig, dus geen getallen. Leg "
                            u"de snede ergens anders.",
                            u"A connection the cut does not see ({0}) holds a cut node and "
                            u"also nodes outside the selection: the force on the cut is "
                            u"then not unique, so no numbers. Put the cut elsewhere."),
    "r_shape": (u"De selectie bevat een onbekende elementvorm ({0}).",
                u"The selection holds an unknown element shape ({0})."),
    "r_no_cut": (u"De selectie heeft geen snede: ze raakt de rest van het model "
                 u"niet.",
                 u"The selection has no cut: it does not touch the rest of the "
                 u"model."),
    "r_no_aster": (u"Code-Aster niet gevonden: zet exe_aster in fb_settings.json.",
                   u"Code-Aster not found: set exe_aster in fb_settings.json."),
    "r_path": (u"Code-Aster kan deze mapnaam niet lezen: {0}.",
               u"Code-Aster cannot read this folder name: {0}."),
    "r_start": (u"De vervolgrun startte niet: {0}", u"The follow-up run did not start: {0}"),
    "r_run": (u"De vervolgrun liep fout: {0}", u"The follow-up run failed: {0}"),
    "r_timeout": (u"De vervolgrun duurde te lang en is gestopt.",
                  u"The follow-up run took too long and was stopped."),
    "r_stopped": (u"Gestopt.", u"Stopped."),
    "r_node_mismatch": (u"De knopen van de run passen niet bij de snede: {0}",
                        u"The nodes of the run do not fit the cut: {0}"),
    "r_busy": (u"Mecway antwoordt niet (open dialoog of een solve?). Probeer het "
               u"zo opnieuw.",
               u"Mecway does not answer (an open dialog, or a solve?). Try again "
               u"in a moment."),
    "r_no_model": (u"Geen model bereikbaar in Mecway: {0}",
                   u"No model available in Mecway: {0}"),
    "r_mesh_changed": (u"De mesh veranderde tijdens het lezen. Probeer het opnieuw.",
                       u"The mesh changed while it was read. Try again."),
    "r_error": (u"Fout: {0}", u"Error: {0}"),
    # warnings
    "w_edge_contact": (u"Er zijn snedeknopen zonder snedevlak (contact via een "
                       u"ribbe of hoekpunt): ze tellen mee in de kracht, niet in "
                       u"oppervlak en zwaartepunt.",
                       u"There are cut nodes without a cut face (contact through "
                       u"an edge or corner): they count in the force, not in "
                       u"area and centroid."),
    "w_shell_or_beam_at_cut": (u"Schalen of balken raken de snede: hun krachten "
                               u"tellen mee, het oppervlak niet.",
                               u"Shells or beams touch the cut: their forces "
                               u"count, their area does not."),
    "w_midside_not_shared": (u"Middenknopen op de snede worden niet gedeeld: "
                             u"controleer de overgang.",
                             u"Midside nodes on the cut are not shared: check "
                             u"the transition."),
    "w_E_missing": (u"E niet bekend voor alle elementen op de snede: neutraal "
                    u"punt zonder E-weging.",
                    u"E not known for all elements on the cut: neutral point "
                    u"without E weighting."),
    "w_mixed_deformation": (u"De selectie mengt componenten met kleine en grote "
                            u"verplaatsingen.",
                            u"The selection mixes components with small and "
                            u"large displacements."),
    "w_skin_on_cut": (u"Een belast vlak ligt op de snede: bekijk de snede kritisch.",
                      u"A loaded face lies on the cut: look at the cut critically."),
    "w_edge_merge": (u"Sneden zijn samengevoegd omdat ze een ribbe delen: de kracht "
                     u"daar is niet eenduidig te verdelen.",
                     u"Cuts were joined because they share an edge: the force there "
                     u"cannot be divided uniquely."),
    "w_no_normal": (u"Deze snede heeft geen eenduidige normaal: N, V en T zeggen hier weinig. "
                    u"Bekijk de globale componenten.",
                    u"This cut has no clear normal: N, V and T mean little here. Look at "
                    u"the global components."),
    "w_deformation": (u"De run noemt niet voor elke component of er met grote "
                      u"verplaatsingen is gerekend: controleer de vorm waarop gesommeerd "
                      u"is.",
                      u"The run does not say for every component whether it used large "
                      u"displacements: check the shape the sum was made on."),
    "w_solution_unknown": (u"Niet na te gaan of deze run bij de oplossing in Mecway "
                           u"hoort: er zijn geen verplaatsingen om mee te vergelijken.",
                           u"Cannot tell whether this run belongs to the solution in "
                           u"Mecway: there are no displacements to compare with."),
    "w_other_model": (u"Deze run komt van een ander model ({0}).",
                      u"This run comes from another model ({0})."),
    "w_no_cut": (u"De selectie heeft geen snede.", u"The selection has no cut."),
    "w_none": (u"Geen waarschuwingen.", u"No warnings."),
    "w_partial_section": (u"Deeldoorsnede: de knopen sluiten geen lichaam af. De som is de "
                          u"kracht door het vlak bij deze knopen; er is geen evenwichtscontrole.",
                          u"Partial section: the nodes close no body. The sum is the force "
                          u"through the plane at these nodes; there is no equilibrium check."),
    "w_selected_not_cut": (u"Geselecteerde knopen die de rest niet deelt, dragen geen kracht in "
                           u"de som: {0}.",
                           u"Selected nodes the rest does not share carry no force in the sum: "
                           u"{0}."),
    "w_non_planar": (u"Snede {0} is niet vlak: geen N, V, T en M, maar globale "
                     u"componenten; de tekening is een projectie.",
                     u"Cut {0} is not planar: no N, V, T and M but global "
                     u"components; the drawing is a projection."),
    "w_large": (u"Grote verplaatsingen: som, neutraal punt en assen volgen de "
                u"vervormde snede per stap, de tekening blijft de onvervormde. "
                u"Punt in doorsnede-assen beweegt mee, een globaal punt niet.",
                u"Large displacements: sum, neutral point and axes follow the "
                u"deformed cut per step, the drawing stays undeformed. A point "
                u"in section axes moves along, a global point does not."),
    "w_mixed_shape": (u"Snede {0}: delen zijn op x, delen op x + u gesommeerd.",
                      u"Cut {0}: parts are summed on x, parts on x + u."),
    "w_mixed_cut": (u"Een snede mengt volumes, schalen of balken: de getallen staan in "
                    u"globale assen, om het met E gewogen zwaartepunt van alle delen.",
                    u"A cut mixes solids, shells or beams: the numbers are in global "
                    u"axes, about the E-weighted centroid of all parts."),
    "w_skin_shell": (u"Een huidschaal: een geselecteerde schaal op een volumevlak buiten de "
                     u"selectie, of een schaal buiten de selectie op een geselecteerd "
                     u"volumevlak. Dat is een grensvlak, geen snede; de kracht telt mee via "
                     u"de gedeelde knopen.",
                     u"A skin shell: a selected shell on a solid face outside the selection, "
                     u"or an outside shell on a selected solid face. That is a boundary, "
                     u"not a cut; its force counts through the shared nodes."),
    "w_beam_along_cut": (u"Een balk ligt met beide knopen op de snede: hij telt mee in "
                         u"de kracht, maar ligt langs de snede in plaats van erdoor.",
                         u"A beam has both nodes on the cut: it counts in the force, but "
                         u"lies along the cut instead of through it."),
    "w_node_contact": (u"Er zijn snedeknopen zonder snede-entiteit van hun soort (bijvoorbeeld "
                       u"een schaalribbe op een volumevlak, of een plaatrand naast een balk): "
                       u"hun kracht zit in de som, niet in het neutrale punt, de assen of de "
                       u"tekening.",
                       u"There are cut nodes on no cut entity of their kind (for example a "
                       u"shell edge on a solid face, or a plate edge next to a beam): their "
                       u"force is in the sum, not in the neutral point, the axes or the "
                       u"drawing."),
    "w_drilling": (u"Boorstijfheid: de schalen van het model liggen niet in één vlak of dragen "
                   u"een knoopmoment om hun normaal (of met onbekende richting), of een ander "
                   u"element of een koppeling "
                   u"grijpt aan op een schaalknoop bij de selectie. Code-Aster geeft schalen "
                   u"een fictieve stijfheid om de normaal (COEF_RIGI_DRZ = {0}); het moment "
                   u"dat daarin verdwijnt, staat niet in de snede. Gemeten relatieve fout: "
                   u"2,7e-2 bij een knoopmoment om de normaal, 3,6e-5 bij een knik.",
                   u"Drilling stiffness: the shells of the model are not in one plane or "
                   u"carry a nodal moment about their normal (or of unknown direction), or "
                   u"another element or a "
                   u"coupling acts on a shell node at the selection. Code-Aster gives shells "
                   u"a fictitious stiffness about the normal (COEF_RIGI_DRZ = {0}); the "
                   u"moment lost in it is not in the cut. Measured relative error: 2.7e-2 "
                   u"with a nodal moment about the normal, 3.6e-5 with a fold."),
    "drz_default": (u"standaard van Code-Aster, 1e-5", u"Code-Aster's default, 1e-5"),
    "w_moments_unread": (u"Momentlasten niet gelezen ({0}): een knoopmoment om een "
                         u"schaalnormaal meldt het paneel dan niet bij de boorstijfheid.",
                         u"Moment loads not read ({0}): a nodal moment about a shell normal "
                         u"is then not reported under drilling stiffness."),
    "mu_not_saved": (u"model nog niet opgeslagen", u"model not saved yet"),
    "mu_not_liml": (u"het model is geen .liml-bestand", u"the model is no .liml file"),
    "mu_unreadable": (u"het .liml-bestand is niet te lezen", u"the .liml file cannot be read"),
    "mu_names": (u"onbekende selectie: {0}", u"unknown selection: {0}"),
    "w_large_axes": (u"Een strook of balk rekende met grote verplaatsingen: zijn lokale assen "
                     u"draaien mee, dus staan de getallen in globale assen.",
                     u"A strip or beam computed with large displacements: its local axes "
                     u"turn along, so the numbers are in global axes."),
    "w_unreliable_mw": (u"M_w (het moment om de schaalnormaal van een strook) is "
                        u"onbetrouwbaar: de fictieve boorstijfheid van schalen neemt een "
                        u"deel ervan op. Gemarkeerd met (?).",
                        u"M_w (the moment about the shell normal of a strip) is unreliable: "
                        u"the fictitious drilling stiffness of shells takes part of it. "
                        u"Marked with (?)."),
    "w_no_thickness": (u"Geen schaaldikte uit Mecway voor: {0}.",
                       u"No shell thickness from Mecway for: {0}."),
    "w_thickness_missing": (u"Een strook op de snede heeft geen dikte: de stroken wegen alleen "
                            u"naar hun lengte, en het oppervlak A staat als –.",
                            u"A strip on the cut has no thickness: the strips weigh by their "
                            u"length only, and the area A shows as –."),
    "w_section_missing": (u"Een balk op de snede heeft geen sectie (A): de balken wegen even "
                          u"zwaar, en het oppervlak A staat als –.",
                          u"A beam on the cut has no section (A): the beams weigh alike, "
                          u"and the area A shows as –."),
    "w_truss": (u"Snede {0} is een staaf: alleen N, de andere getallen staan als –.",
                u"Cut {0} is a truss: N only, the other numbers show as –."),
    # drawing
    "d_title": (u"Snede {0}, gezien van buiten de selectie",
                u"Cut {0}, seen from outside the selection"),
    "d_about": (u"Om {0} ({1}; {2}) mm", u"About {0} ({1}; {2}) mm"),
    "d_neutral": (u"het neutrale punt", u"the neutral point"),
    "d_node": (u"knoop {0}", u"node {0}"),
    "d_chosen": (u"het gekozen punt", u"the chosen point"),
    "d_real": (u"Pijlen wijzen in de echte richting; de lengte is niet op schaal.",
               u"Arrows point in the real direction; their length is not to scale."),
    "d_none": (u"Bereken een snede om de tekening te zien.",
               u"Compute a cut to see the drawing."),
    "d_area": (u"A = {0} mm²", u"A = {0} mm²"),
    "d_plane": (u"Vlak n = ({0}) {1}  ·  kant {2}", u"Plane n = ({0}) {1}  ·  side {2}"),
    "d_in": (u"het beeld in", u"into the picture"),
    "d_out": (u"naar u toe", u"toward you"),
}
LANGS = ("nl", "en")
UNITS = (("N", 1.0, u"N", u"N·m"), ("kN", 1e-3, u"kN", u"kN·m"))
SUPERSCRIPT = {"-": u"⁻", "0": u"⁰", "1": u"¹", "2": u"²", "3": u"³", "4": u"⁴",
               "5": u"⁵", "6": u"⁶", "7": u"⁷", "8": u"⁸", "9": u"⁹"}
FOLDER_CHOICES = (("auto", "f_auto"), ("model", "f_model"), ("bridge", "f_bridge"),
                  ("other", "f_other"))
_DEFAULTS = {"language": "", "unit": "N", "axes": "section", "folder": "auto",
             "folder_other": u"", "arrow_mode": "nodes", "bridge_scripts": u"",
             "exe_aster": u"", "cut_mode": "elements"}
CUT_MODES = ("elements", "nodes")
_CACHE = {}


# ==========================================
# SETTINGS, LANGUAGE, LOG
# ==========================================
def log(text):
    """One line in the log in the temporary folder; never raises."""
    try:
        path = os.path.join(os.environ.get("TEMP", SCRIPTS_DIR), LOG_NAME)
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(u"{0}  {1}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def settings(path=None):
    """The settings, defaults filled in (read once per module load)."""
    if "settings" not in _CACHE:
        values = dict(_DEFAULTS)
        try:
            with io.open(path or SETTINGS_PATH, encoding="utf-8") as f:
                data = json.loads(f.read())
            if isinstance(data, dict):
                values.update(data)
        except (IOError, OSError, ValueError):
            pass
        _CACHE["settings"] = values
    return _CACHE["settings"]


def save_setting(key, value, path=None):
    """Store one setting; a failure (read-only folder) is only logged."""
    values = settings(path)
    values[key] = value
    try:
        with io.open(path or SETTINGS_PATH, "w", encoding="utf-8") as f:
            f.write(u"{0}".format(json.dumps(values, indent=1, sort_keys=True,
                                             ensure_ascii=False)))
    except (IOError, OSError) as e:
        log(u"settings not saved: {0}".format(e))


def _windows_language():
    try:
        from System.Globalization import CultureInfo
        name = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName
        return "nl" if name == "nl" else "en"
    except Exception:
        return "en"


def language():
    value = settings().get("language")
    return value if value in LANGS else _windows_language()


def tx(key, lang):
    nl, en = T[key]
    return nl if lang == "nl" else en


def instance_busy_text():
    return tx("busy_text", language())


def stopped_text(detail):
    return tx("stopped_by", language()).format(detail)


def separators(lang="en"):
    """(decimal sign, list separator) of Windows: Excel reads a paste and a CSV
    by these, whatever the language of the panel."""
    try:
        from System.Globalization import CultureInfo
        culture = CultureInfo.CurrentCulture
        return (u"{0}".format(culture.NumberFormat.NumberDecimalSeparator),
                u"{0}".format(culture.TextInfo.ListSeparator))
    except Exception:
        return (u",", u";") if lang == "nl" else (u".", u",")


def csv_text(rows, decimal, separator):
    """CSV with the list separator of Windows; a cell with a separator, a quote
    or a line end stands between double quotes. Cells as fb_core.table_text."""
    lines = []
    for row in rows:
        cells = []
        for cell in row:
            text = u"{0}".format(fb_core.table_text([[cell]], decimal)[:-2])
            if separator in text or u'"' in text or u"\r" in text or u"\n" in text:
                text = u'"{0}"'.format(text.replace(u'"', u'""'))
            cells.append(text)
        lines.append(separator.join(cells))
    return u"\r\n".join(lines) + u"\r\n"


# ==========================================
# NUMBERS
# ==========================================
def fmt(value, dec=u".", digits=5):
    """A number for the eye: grouped digits, x10^n far from 1. Fixed point only:
    the g format follows the Windows locale in IronPython."""
    if value is None:
        return u"–"
    if value == 0:
        return u"0"
    a = abs(value)
    sign = u"−" if value < 0 else u""
    e = int(math.floor(math.log10(a)))
    if -4 <= e < 9:
        decimals = max(0, digits - 1 - e)
        text = "%.*f" % (decimals, a)
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        whole, _, part = text.partition(".")
        if len(whole) > 4:
            groups = []
            while len(whole) > 3:
                groups.insert(0, whole[-3:])
                whole = whole[:-3]
            groups.insert(0, whole)
            whole = u" ".join(groups)
        return sign + whole + (dec + part if part else u"")
    mantissa = a / 10.0 ** e
    text = ("%.*f" % (digits - 1, mantissa)).rstrip("0").rstrip(".")
    return u"{0}{1} × 10{2}".format(sign, text.replace(".", dec),
                                    u"".join(SUPERSCRIPT[c] for c in str(e)))


def parse_number(text):
    """A typed number with a point or a comma; ValueError if it is none."""
    cleaned = text.strip().replace(u" ", u"").replace(u" ", u"")
    cleaned = cleaned.replace(u"−", u"-").replace(u",", u".")
    if not cleaned:
        raise ValueError("empty")
    value = float(cleaned)
    if value != value or abs(value) == float("inf"):
        raise ValueError("not finite")
    return value


def clean(values, size):
    """(N, Vy, Vz, T, My, Mz) with round-off shown as zero: a force against the
    largest force, a moment against the largest moment or force x size."""
    forces = max(abs(v) for v in values[:3])
    moments = max(max(abs(v) for v in values[3:]), forces * size)
    return ([0.0 if abs(v) < TINY * forces else v for v in values[:3]] +
            [0.0 if abs(v) < TINY * moments else v for v in values[3:]])


def reason_text(code, lang, detail=u"", version=u"", mode="elements"):
    """A refusal in plain words. mode "nodes": a cut by nodes on a plane, where
    some codes of the core mean something else (empty, no_cut, ...)."""
    key = "r_" + (code or "error")
    if mode == "nodes" and key + "_nodes" in T:
        key += "_nodes"
    if key not in T:
        return tx("r_error", lang).format(u"{0} {1}".format(code, detail).strip())
    # the version of the run: from the manifest in the run list, from the
    # detail of Refused when start() refuses
    arg = (version or detail) if code == "version" else detail
    return tx(key, lang).format(arg)


def warning_text(code, lang, arg=None):
    key = "w_" + code
    if key not in T:
        return u"{0}".format(code)
    return tx(key, lang).format(arg)


# ==========================================
# A CUT BY NODES ON A PLANE
# ==========================================
def side_sign(side):
    return u"+" if side == 1 else u"−"


def vector_text(v, dec=u".", digits=4):
    """A unit vector for the eye: round-off shown as 0."""
    return u"; ".join(fmt(c if abs(c) > 1e-9 else 0.0, dec, digits) for c in v)


def node_list_text(nids, most=10):
    nids = sorted(nids)
    text = u", ".join(u"{0}".format(n) for n in nids[:most])
    return text + (u", …" if len(nids) > most else u"")


# ==========================================
# 3D HELPERS
# ==========================================
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    size = math.sqrt(_dot(a, a))
    return (a[0] / size, a[1] / size, a[2] / size) if size > 0 else None


def _plane_axes(normal):
    """(n, a, b), right handed, for a view along a normal."""
    n = _unit(normal) or (1.0, 0.0, 0.0)
    helper = (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (0.0, 1.0, 0.0)
    a = _unit(_cross(helper, n))
    return n, a, _cross(n, a)


def _newell(points):
    """Area vector of a polygon, by the order of its points."""
    x = y = z = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        x += (p[1] - q[1]) * (p[2] + q[2])
        y += (p[2] - q[2]) * (p[0] + q[0])
        z += (p[0] - q[0]) * (p[1] + q[1])
    return (x / 2.0, y / 2.0, z / 2.0)


def _turned_normal(faces, mesh, moved, normal):
    """Unit normal of faces on the moved nodes. A face counts with the sign its
    winding has against the undeformed outward normal."""
    if not normal or not any(normal):
        return None
    total = [0.0, 0.0, 0.0]
    corners = {3: 3, 6: 3, 4: 4, 8: 4, 9: 4}
    for eid, faceid in faces:
        nids = mesh["elements"][eid][1]
        local = fb_core.face_local_nodes(mesh["elements"][eid][0], faceid)
        ring = [nids[k] for k in local[:corners[len(local)]]]
        old = _newell([mesh["nodes"][q] for q in ring])
        new = _newell([moved[q] for q in ring])
        sign = 1.0 if _dot(old, normal) >= 0 else -1.0
        for k in range(3):
            total[k] += sign * new[k]
    return _unit(total)


def _turned_axis(pairs, old_centre, new_centre, axes, n):
    """Where axis a of a cut went: the best linear fit of the in-plane map from
    the undeformed to the moved nodes, applied to a and laid in the new plane."""
    a0, b0 = axes[1], axes[2]
    maa = mab = mbb = 0.0
    p = [0.0, 0.0, 0.0]
    q = [0.0, 0.0, 0.0]
    for x, y in pairs:
        d = (x[0] - old_centre[0], x[1] - old_centre[1], x[2] - old_centre[2])
        e = (y[0] - new_centre[0], y[1] - new_centre[1], y[2] - new_centre[2])
        ca, cb = _dot(d, a0), _dot(d, b0)
        maa += ca * ca
        mab += ca * cb
        mbb += cb * cb
        for k in range(3):
            p[k] += e[k] * ca
            q[k] += e[k] * cb
    det = maa * mbb - mab * mab
    if det <= 1e-12 * max(maa * mbb, 1e-300):
        guess = a0
    else:
        guess = tuple((mbb * p[k] - mab * q[k]) / det for k in range(3))
    share = _dot(guess, n)
    return _unit((guess[0] - share * n[0], guess[1] - share * n[1],
                  guess[2] - share * n[2]))


_GLOBAL = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
SECTION_NAMES = (u"N", u"Vy", u"Vz", u"T", u"My", u"Mz")
STRIP_NAMES = (u"N", u"V_t", u"V_w", u"T", u"M_t", u"M_w")
GLOBAL_NAMES = (u"Fx", u"Fy", u"Fz", u"Mx", u"My", u"Mz")
NEUTRAL_POINT = ("section", (0.0, 0.0, 0.0))
# The axes of a cut (contract, phase 4): principal axes of a section (solid or
# a planar set of strips), (n, t, w) of one strip, the Code-Aster axes of one
# beam, the axis of one truss, or global (mixed, not planar, large rotations)
AXES_KINDS = ("section", "strip", "beam", "truss", "global")
KIND_NAMES = {"section": SECTION_NAMES, "strip": STRIP_NAMES, "beam": SECTION_NAMES,
              "truss": SECTION_NAMES, "global": GLOBAL_NAMES}
AXIS_LETTERS = {"section": (u"y", u"z"), "strip": (u"t", u"w"), "beam": (u"y", u"z"),
                "truss": (u"y", u"z"), "global": (u"a", u"b")}
TRUSS_MODELS = ("BARRE", "CABLE")
_CIRCLE_SIDES = 48


def _same_axes(p, q, tol=1e-9):
    return all(abs(p[i][k] - q[i][k]) <= tol for i in range(3) for k in range(3))


def _code_and_arg(item):
    """A warning of the core: a code, or (code, detail)."""
    if isinstance(item, (list, tuple)):
        return item[0], (item[1] if len(item) > 1 else None)
    return item, None


def _rect(hy, hz):
    return [(-hy / 2.0, -hz / 2.0), (hy / 2.0, -hz / 2.0), (hy / 2.0, hz / 2.0),
            (-hy / 2.0, hz / 2.0)]


def _round(r):
    return [(r * math.cos(2 * math.pi * k / _CIRCLE_SIDES),
             r * math.sin(2 * math.pi * k / _CIRCLE_SIDES)) for k in range(_CIRCLE_SIDES)]


def beam_loops(section):
    """Loops of a beam section in its own (y, z), metres, from the cara/vale
    Code-Aster got (RECTANGLE HY/HZ or H, hollow with EPY/EPZ or EP; CERCLE R,
    hollow with EP). [] when the outline is not known (GENERALE and others)."""
    section = section or {}
    cara = dict(zip([u"{0}".format(c).upper() for c in section.get("cara") or []],
                    section.get("vale") or []))
    try:
        if "HY" in cara or "H" in cara:
            hy = float(cara.get("HY", cara.get("H")))
            hz = float(cara.get("HZ", cara.get("H")))
            if hy <= 0 or hz <= 0:
                return []
            loops = [_rect(hy, hz)]
            epy = float(cara.get("EPY", cara.get("EP", 0.0)))
            epz = float(cara.get("EPZ", cara.get("EP", 0.0)))
            if 0 < 2 * epy < hy and 0 < 2 * epz < hz:
                loops.append(_rect(hy - 2 * epy, hz - 2 * epz))
            return loops
        if "R" in cara:
            r = float(cara["R"])
            if r <= 0:
                return []
            loops = [_round(r)]
            ep = float(cara.get("EP", 0.0))
            if 0 < ep < r:
                loops.append(_round(r - ep))
            return loops
    except (TypeError, ValueError):
        return []
    return []


# ==========================================
# WHAT THE WINDOW SHOWS (no Windows Forms)
# ==========================================
class PanelModel(object):
    """The outcome of one follow-up run and the choices on it. A base sum per
    cut and step is made once about the neutral point; moving the point only
    shifts it (fb_core.shift), so dragging is instant."""

    def __init__(self):
        self.lang = "en"
        self.unit = "N"
        self.axes = "section"
        self.mesh = None
        self.plan = None
        self.result = None
        self.man = None
        self.folder = u""
        self.props = None
        self.cuts = []
        self.rank = None
        self.index = 0
        self.warnings = []
        self.nodecut = None
        self._positions = {}

    def load(self, mesh, plan, geos, result, per_group, man, folder, props=None,
             nodecut=None):
        """nodecut: the cut of fb_nodecut.plan_from_nodes when the cut is made
        by nodes on a plane (plan is then its plan), else None."""
        self.mesh = mesh
        self.plan = plan
        self.result = result
        self.man = man
        self.folder = folder
        self.props = props
        self.nodecut = nodecut
        self.cuts = []
        self.index = 0
        self._positions = {}
        nodes = result["nodes"]
        for group in plan["groups"]:
            indices = per_group.get(group["id"], [])
            points = [nodes[i]["xyz"] for i in indices]
            own, _ = fb_mecway.result_to_nodes(mesh, group["nodes"], points)
            for i, nid, p in zip(indices, own, points):
                if nodes[i].get("nid") is None and \
                        fb_mecway._distance2(mesh["nodes"][nid], p) < 1e-14:
                    nodes[i]["nid"] = nid
            self.cuts.append({
                "id": group["id"], "group": group, "geo": geos[group["id"]],
                "indices": indices, "points": points, "targets": own,
                "large": any(nodes[i].get("large") for i in indices),
                "point": NEUTRAL_POINT, "node": None,
                "frames": {}, "bases": {}})
        steps = result["steps"]
        self.rank = steps[-1]["rank"] if steps else None
        self.warnings = self._collect_warnings(geos)

    def _collect_warnings(self, geos):
        out = []
        seen = set()

        def add(code, arg=None, once=True):
            if once:
                if code in seen:
                    return
                seen.add(code)
            out.append(("code", code, arg))
        for item in list(self.plan.get("warnings", [])) + list(
                self.result.get("warnings", [])):
            code, arg = _code_and_arg(item)
            add(code, arg)
        if self.nodecut is not None:
            for code in self.nodecut.get("warnings") or []:
                if code == "selected_not_cut":
                    add(code, node_list_text(self.nodecut.get("not_cut") or []))
                else:
                    add(code)
            if self.partial():
                add("partial_section")
        for cut in self.cuts:
            geo = cut["geo"]
            kind = self.axes_kind(cut)
            if not geo.get("planar") and kind == "global" and \
                    cut["group"].get("kind", "solid") in ("solid", "shell"):
                add("non_planar", cut["id"], False)
            for item in geo.get("warnings", []):
                add(*_code_and_arg(item))
            if fb_core.mixed_shape(self.result, cut["indices"]):
                add("mixed_shape", cut["id"], False)
            if kind == "global" and cut["large"] and \
                    cut["group"].get("kind", "solid") in ("shell", "beam"):
                add("large_axes")
            if kind == "strip":
                add("unreliable_mw")
            if kind == "truss":
                add("truss", cut["id"], False)
        if any(cut["large"] for cut in self.cuts):
            add("large")
        return out

    def note_missing(self, missing):
        """A warning for shell components of the selection whose thickness
        Mecway did not give (fb_mecway.read_props)."""
        names = set((missing or {}).get("thickness") or [])
        component = (self.mesh or {}).get("component") or {}
        used = sorted(set(component.get(e) for e in self.plan["inside"]) & names)
        if used:
            self.warnings.append(("code", "no_thickness", u", ".join(used)))
        # moments not read (fb_mecway.read_moments_steps): the drilling
        # warning looks at every shell of the model
        unread = (missing or {}).get("moments")
        if unread and self.mesh is not None and has_shells(self.mesh):
            if isinstance(unread, (list, tuple)):
                arg = (u"names", u", ".join(u"{0}".format(n) for n in unread))
            else:
                arg = (u"code", u"{0}".format(unread))
            self.warnings.append(("code", "moments_unread", arg))

    def _warning_arg(self, code, arg):
        if code == "drilling":
            value = (self.man or {}).get("coef_rigi_drz")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return fmt(float(value), self.dec())
            return tx("drz_default", self.lang)
        if code == "moments_unread" and isinstance(arg, tuple):
            kind, value = arg
            if kind == "code":
                key = "mu_" + value
                return tx(key, self.lang) if key in T else value
            return tx("mu_names", self.lang).format(value)
        return arg

    def warning_lines(self):
        return [warning_text(code, self.lang, self._warning_arg(code, arg))
                for _, code, arg in self.warnings]

    # ---- axes per case ---------------------------------------------------------
    def axes_kind(self, cut):
        """One of AXES_KINDS: what the local axes of this cut are. The core
        may say it in geo["axes_kind"]; else it follows from the contract's
        data. A strip or beam that computed with large displacements is global:
        its local axes turn along (contract, large_axes)."""
        if "axes_kind" not in cut:
            cut["axes_kind"] = self._axes_kind(cut)
        return cut["axes_kind"]

    def _axes_kind(self, cut):
        geo = cut["geo"]
        kind = cut["group"].get("kind", "solid")
        if kind != "solid" and (cut["large"] or "large_axes" in [
                _code_and_arg(w)[0] for w in geo.get("warnings") or []]):
            return "global"
        given = geo.get("axes_kind")
        if given in AXES_KINDS:
            return given
        if kind == "mixed":
            return "global"
        if kind == "shell":
            if len(geo.get("strips") or []) == 1:
                return "strip"
            return "section" if geo.get("planar") else "global"
        if kind == "beam":
            if len(geo.get("beams") or []) != 1:
                return "global"
            return "truss" if self._is_truss(cut) else "beam"
        return "section" if geo.get("planar") else "global"

    def _beam_component(self, cut, beam):
        """The manifest entry of the component of a beam at the cut."""
        names = (self.mesh or {}).get("component") or {}
        comps = (self.man or {}).get("components") or {}
        for entity in cut["group"].get("entities") or []:
            if entity[0] == "end" and (beam is None or entity[2] == beam.get("node")):
                entry = comps.get(names.get(entity[1]))
                if entry is not None:
                    return entry
        return None

    def _is_truss(self, cut):
        beam = (cut["geo"].get("beams") or [None])[0] or {}
        if beam.get("model"):
            return beam["model"] in TRUSS_MODELS
        entry = self._beam_component(cut, beam) or {}
        return entry.get("model") in TRUSS_MODELS

    def shown_kind(self, cut):
        """The axes the table and drawing use for a cut: its own, or global."""
        return self.axes_kind(cut) if self.axes == "section" else "global"

    def mask(self, cut):
        """Per component: "" shown, "none" not carried (a truss), "doubt"
        unreliable (M_w of a strip). The numbers themselves stay six floats."""
        kind = self.shown_kind(cut)
        if kind == "truss":
            return ["", "none", "none", "none", "none", "none"]
        if kind == "strip":
            return ["", "", "", "", "", "doubt"]
        return [""] * 6

    def axes_note(self, cut=None):
        cut = cut or self.cut()
        if cut is None:
            return u""
        if self.axes != "section":
            return tx("ax_n_all_global", self.lang)
        return tx("ax_n_" + self.axes_kind(cut), self.lang).format(cut["id"])

    def radio_text(self, cut=None):
        cut = cut or self.cut()
        if cut is None:
            return tx("ax_section", self.lang)
        return tx("ax_r_" + self.axes_kind(cut), self.lang)

    def sign_text(self):
        """The sign convention of each kind of axes in the table."""
        if not self.cuts:
            return tx("sign", self.lang)
        kinds = []
        for cut in self.cuts:
            kind = self.shown_kind(cut)
            if kind not in kinds:
                kinds.append(kind)
        parts = [tx("sign_base", self.lang)]
        for kind in AXES_KINDS:
            if kind in kinds:
                parts.append(tx("sign_" + kind, self.lang))
        if self.nodecut is not None:
            parts.append(self.side_text())
        return u" ".join(parts)

    # ---- a cut by nodes on a plane ------------------------------------------------
    def partial(self):
        """True for a partial section of a cut by nodes: the sum is the force
        through the plane at the nodes, "rest" means nothing."""
        flags = (self.result or {}).get("nodecut") or {}
        return bool((self.nodecut or {}).get("partial") or flags.get("partial"))

    def side_text(self):
        """Side, normal of the plane, and that the other side is opposite."""
        cut = self.nodecut
        side = cut["side"]
        return tx("nc_sign", self.lang).format(
            len(cut["selected"]), vector_text(cut["plane"]["normal"], self.dec()),
            side_sign(side), tx("nc_plus" if side == 1 else "nc_minus", self.lang))

    def basis(self):
        """What the table was made for: ("elements", 0, [eid]) or ("nodes",
        side, [nid]), ids sorted; None without a result."""
        if self.nodecut is not None:
            return ("nodes", self.nodecut["side"], sorted(self.nodecut["selected"]))
        if self.plan:
            return ("elements", 0, sorted(self.plan["inside"]))
        return None

    # ---- choices ---------------------------------------------------------------
    def cut(self):
        return self.cuts[self.index] if 0 <= self.index < len(self.cuts) else None

    def step_time(self):
        """Time of the chosen step; None without a result."""
        if not self.result:
            return None
        for item in self.result["steps"]:
            if item["rank"] == self.rank:
                return item.get("time")
        return None

    def steps(self):
        return self.result["steps"] if self.result else []

    def dec(self):
        return u"," if self.lang == "nl" else u"."

    def unit_row(self):
        for row in UNITS:
            if row[0] == self.unit:
                return row
        return UNITS[0]

    # ---- frames and sums -------------------------------------------------------
    def positions(self, rank):
        if rank not in self._positions:
            self._positions[rank] = fb_core.positions(self.result, rank)
        return self._positions[rank]

    def _deformed_frame(self, cut, rank):
        """
        Neutral point and axes of the cut at a step of a large-displacement run.
        The centroid comes from the faces on x + u. The normal does not: the core
        turns a face outward by the middle of its element, and the nodes off the
        cut are not in the result, so a shift beyond an element or a turn beyond
        90 degrees would flip it. Each face keeps the winding it has on the
        undeformed mesh instead, which holds for any rotation. Axis a follows the
        best fit of the cut nodes, so a turn about the normal counts too.
        """
        mesh = self.mesh
        group = cut["group"]
        used = set(group["nodes"])
        elements = {}
        for eid, _ in group["faces"]:
            elements[eid] = mesh["elements"][eid]
            used.update(elements[eid][1])
        nodes = dict((n, mesh["nodes"][n]) for n in used)
        where = self.positions(rank)
        pairs = []
        for i, p, nid in zip(cut["indices"], cut["points"], cut["targets"]):
            if fb_mecway._distance2(mesh["nodes"][nid], p) < 1e-14:
                nodes[nid] = where[i]
                pairs.append((p, where[i]))
        moved = {"nodes": nodes, "elements": elements}
        geo = fb_core.section_geometry(moved, group, self.props)
        centre = tuple(geo["centroid"])
        axes = cut["geo"]["axes"]
        n = _turned_normal(group["faces"], mesh, nodes, cut["geo"].get("normal"))
        if cut["geo"].get("planar") and n is not None:
            a = _turned_axis(pairs, cut["geo"]["centroid"], centre, axes, n)
            if a is not None:
                axes = (n, a, _cross(n, a))
        return centre, axes

    def _moved_frame(self, cut, rank):
        """A cut with strips or beams at a step of a large-displacement run:
        its numbers are in global axes (large_axes), so only the neutral point
        moves, by the mean displacement of the cut nodes. The undeformed axes
        stay for the mapping of a point, so a chosen point moves along."""
        where = self.positions(rank)
        nodes = self.result["nodes"]
        shift = [0.0, 0.0, 0.0]
        count = 0
        for i in cut["indices"]:
            x = nodes[i]["xyz"]
            for k in range(3):
                shift[k] += where[i][k] - x[k]
            count += 1
        c = cut["geo"]["centroid"]
        if count:
            c = tuple(c[k] + shift[k] / count for k in range(3))
        return tuple(c), cut["geo"]["axes"]

    def frame(self, cut, rank=None):
        """(neutral point, axes) of a cut at a step."""
        rank = self.rank if rank is None else rank
        if rank not in cut["frames"]:
            if cut["large"] and cut["group"].get("kind", "solid") != "solid":
                cut["frames"][rank] = self._moved_frame(cut, rank)
            elif cut["large"]:
                cut["frames"][rank] = self._deformed_frame(cut, rank)
            else:
                cut["frames"][rank] = (tuple(cut["geo"]["centroid"]),
                                       cut["geo"]["axes"])
        return cut["frames"][rank]

    def _base(self, cut, rank):
        if rank not in cut["bases"]:
            where = self.positions(rank)
            forces = self.result["forces"][rank]
            xyz = [where[i] for i in cut["indices"]]
            f6 = [forces[i] for i in cut["indices"]]
            cut["bases"][rank] = fb_core.resultant(xyz, f6, self.frame(cut, rank)[0])
        return cut["bases"][rank]

    def point_global(self, cut, rank=None):
        kind, value = cut["point"]
        if kind == "global":
            return value
        c, axes = self.frame(cut, rank)
        return tuple(c[k] + value[0] * axes[0][k] + value[1] * axes[1][k] +
                     value[2] * axes[2][k] for k in range(3))

    def sum6(self, cut, rank=None):
        """Forces and moments about the chosen point, global axes."""
        rank = self.rank if rank is None else rank
        return fb_core.shift(self._base(cut, rank), self.frame(cut, rank)[0],
                             self.point_global(cut, rank))

    def is_section(self, cut):
        """True when the numbers of this cut are in its own axes."""
        return self.shown_kind(cut) != "global"

    def components(self, cut):
        """The six numbers of the table for a cut, N and N.m; always six
        floats (a truss too: mask() says what is shown)."""
        s = self.sum6(cut)
        return fb_core.to_axes(s, self.frame(cut)[1]) if self.is_section(cut) else s

    def names(self, cut=None):
        if cut is None:
            return SECTION_NAMES if self.axes == "section" else GLOBAL_NAMES
        return KIND_NAMES[self.shown_kind(cut)]

    def column_names(self):
        """Per component the names over all cuts, joined by "/" where cuts
        differ (a strip next to a solid: "Mz/M_w")."""
        if not self.cuts:
            return list(self.names())
        out = []
        for k in range(6):
            seen = []
            for cut in self.cuts:
                name = self.names(cut)[k]
                if name not in seen:
                    seen.append(name)
            out.append(u"/".join(seen))
        return out

    def value_text(self, cut, k, value, factor, dec):
        mark = self.mask(cut)[k]
        if mark == "none":
            return fmt(None)
        text = fmt(value * factor, dec)
        return text + u" " + tx("unreliable", self.lang) if mark == "doubt" else text

    def size(self, cut):
        """A length of the cut, for the round-off of moments (clean): the root
        of its area, or without an area (a strip without thickness, a beam
        without A: contract) the diagonal of its nodes. 1 m when that is zero,
        as for a single beam end."""
        area = cut["geo"].get("area")
        if area is not None:
            return math.sqrt(max(area, 0.0)) or 1.0
        nodes = (self.mesh or {}).get("nodes") or {}
        points = [nodes[n] for n in cut["group"].get("nodes") or [] if n in nodes]
        if not points:
            return 1.0
        return math.sqrt(sum((max(p[k] for p in points) - min(p[k] for p in points)) ** 2
                             for k in range(3))) or 1.0

    def area_mm2(self, cut):
        """A in mm², None when the core gives none."""
        area = cut["geo"].get("area")
        return None if area is None else area * 1e6

    # ---- point -----------------------------------------------------------------
    def point_shown(self, cut=None):
        """The three numbers of the point fields, mm."""
        cut = cut or self.cut()
        kind, value = cut["point"]
        if self.axes == "section":
            if kind == "section":
                out = value
            else:
                c, axes = self.frame(cut)
                d = tuple(value[k] - c[k] for k in range(3))
                out = tuple(_dot(d, axes[k]) for k in range(3))
        else:
            out = self.point_global(cut)
        return tuple(v * 1e3 for v in out)

    def set_point_shown(self, numbers, cut=None):
        cut = cut or self.cut()
        kind = "section" if self.axes == "section" else "global"
        cut["point"] = (kind, tuple(v * 1e-3 for v in numbers))
        cut["node"] = None

    def view_axes(self, cut):
        """(n, a, b) of the drawing: the axes of the cut (the outline of the
        core is in them), one strip or one beam in its own axes also when its
        numbers are global, else a view along the mean normal."""
        geo = cut["geo"]
        single = len(geo.get("strips") or []) + len(geo.get("beams") or []) == 1
        own = geo.get("planar") or (
            single and cut["group"].get("kind", "solid") in ("shell", "beam"))
        normal = geo.get("normal") or (0.0, 0.0, 0.0)
        if own and not (_same_axes(geo["axes"], _GLOBAL) and not geo.get("outline")
                        and any(normal)):
            return geo["axes"]
        return _plane_axes(normal)

    def view_letters(self, cut, view):
        """Names of the two axes of the drawing: those of the cut's own axes
        when the drawing uses them, else a and b of a plane view."""
        geo = cut["geo"]
        if not _same_axes(view, geo["axes"]):
            return AXIS_LETTERS["global"]
        kind = cut["group"].get("kind", "solid")
        if kind == "shell" and len(geo.get("strips") or []) == 1:
            return AXIS_LETTERS["strip"]
        if kind == "beam" and len(geo.get("beams") or []) == 1:
            return AXIS_LETTERS["beam"]
        if _same_axes(geo["axes"], _GLOBAL):
            return (u"Y", u"Z")
        return AXIS_LETTERS["section"]

    def point_hint(self, cut=None):
        """What the three point fields mean."""
        cut = cut or self.cut()
        if self.axes != "section":
            return tx("p_global", self.lang)
        if cut is None:
            return tx("p_section", self.lang)
        geo = cut["geo"]
        kind = cut["group"].get("kind", "solid")
        if kind == "shell" and len(geo.get("strips") or []) == 1:
            return tx("p_strip", self.lang)
        if kind == "beam" and len(geo.get("beams") or []) == 1:
            return tx("p_beam", self.lang)
        if _same_axes(geo["axes"], _GLOBAL):
            return tx("p_offset", self.lang)
        return tx("p_section", self.lang)

    def set_point_plane(self, u, v, cut=None):
        """Position in the plane of the drawing (a drag), in metres. The depth
        along the normal stays."""
        cut = cut or self.cut()
        n, a, b = self.view_axes(cut)
        c = cut["geo"]["centroid"]
        here = self.point_undeformed(cut)
        depth = _dot((here[0] - c[0], here[1] - c[1], here[2] - c[2]), n)
        d = tuple(depth * n[k] + u * a[k] + v * b[k] for k in range(3))
        axes = cut["geo"]["axes"]
        if self.axes == "global":
            cut["point"] = ("global", tuple(c[k] + d[k] for k in range(3)))
        else:
            cut["point"] = ("section", tuple(_dot(d, axes[k]) for k in range(3)))
        cut["node"] = None

    def set_neutral(self, cut=None):
        cut = cut or self.cut()
        cut["point"] = NEUTRAL_POINT
        cut["node"] = None

    def set_node(self, nid, cut=None):
        cut = cut or self.cut()
        x = self.mesh["nodes"][nid]
        c = cut["geo"]["centroid"]
        axes = cut["geo"]["axes"]
        d = (x[0] - c[0], x[1] - c[1], x[2] - c[2])
        cut["point"] = ("section", tuple(_dot(d, axes[k]) for k in range(3)))
        cut["node"] = nid

    def point_undeformed(self, cut):
        """The point on the undeformed section: where a Mecway node stands."""
        kind, value = cut["point"]
        if kind == "global":
            return value
        c = cut["geo"]["centroid"]
        axes = cut["geo"]["axes"]
        return tuple(c[k] + value[0] * axes[0][k] + value[1] * axes[1][k] +
                     value[2] * axes[2][k] for k in range(3))

    def nearest_cut_node(self, cut=None):
        cut = cut or self.cut()
        return fb_mecway.nearest_node(self.mesh, cut["group"]["nodes"],
                                      self.point_undeformed(cut))[0]

    # ---- table -----------------------------------------------------------------
    def headers(self):
        row = self.unit_row()
        names = self.column_names()
        doubt = any(self.mask(cut)[5] == "doubt" for cut in self.cuts)
        out = ([tx("cut", self.lang), u"A [mm²]"] +
               [u"{0} [{1}]".format(n, row[2]) for n in names[:3]] +
               [u"{0} [{1}]".format(n, row[3]) for n in names[3:]])
        if self.axes_column():
            out.append(tx("ax_head", self.lang))
        if doubt:
            out[7] = u"{0} {1}".format(out[7], tx("unreliable", self.lang))
        return out

    def row_label(self, cut):
        if self.nodecut is not None:
            return tx("nc_row", self.lang).format(cut["id"], side_sign(self.nodecut["side"]))
        return u"{0}".format(cut["id"])

    def axes_column(self):
        """The column with the axes of each cut: only when some cut is not
        in section axes (a strip, beam, truss or a global cut)."""
        return any(self.shown_kind(cut) != "section" for cut in self.cuts) and \
            self.axes == "section"

    def axes_short(self, cut):
        return tx("ax_s_" + self.shown_kind(cut), self.lang)

    def rows(self):
        """Text per cut for the table on screen."""
        factor = self.unit_row()[1]
        dec = self.dec()
        out = []
        for cut in self.cuts:
            values = clean(self.components(cut), self.size(cut))
            out.append([self.row_label(cut), fmt(self.area_mm2(cut), dec, 4)] +
                       [self.value_text(cut, k, v, factor, dec)
                        for k, v in enumerate(values)] +
                       ([self.axes_short(cut)] if self.axes_column() else []))
        return out

    def step_text(self):
        for step in self.steps():
            if step["rank"] == self.rank:
                if step.get("time") is None:
                    return u"{0}".format(step["rank"])
                return tx("step_item", self.lang).format(
                    step["rank"], fmt(step["time"], self.dec()))
        return u""

    def copy_rows(self):
        """Rows of the contract's table_text: raw numbers, text around them."""
        row = self.unit_row()
        man = self.man or {}
        rows = [[PANEL_TITLE, fb_core.VERSION], [u"Run", man.get("run_id"), man.get("model")],
                [tx("step", self.lang), self.rank],
                [tx("axes", self.lang),
                 tx("ax_section" if self.axes == "section" else "ax_global",
                    self.lang)],
                [self.sign_text()], []]
        if self.nodecut is not None:
            nc = self.nodecut
            row_nc = [tx("nc_copy", self.lang),
                      u"{0} {1}".format(tx("nc_side", self.lang), side_sign(nc["side"])),
                      u"{0} ({1})".format(tx("nc_normal", self.lang),
                                          vector_text(nc["plane"]["normal"], self.dec()))]
            if self.partial():
                row_nc.append(tx("nc_partial", self.lang))
            rows.insert(5, row_nc)
        head = self.headers()
        rows.append(head[:2] + [u"{0} X [mm]".format(tx("point", self.lang)),
                                u"{0} Y [mm]".format(tx("point", self.lang)),
                                u"{0} Z [mm]".format(tx("point", self.lang))] +
                    head[2:])
        for cut in self.cuts:
            p = self.point_global(cut)
            values = clean(self.components(cut), self.size(cut))
            mask = self.mask(cut)
            rows.append([self.row_label(cut), self.area_mm2(cut)] +
                        [v * 1e3 for v in p] +
                        [None if mask[k] == "none" else v * row[1]
                         for k, v in enumerate(values)] +
                        ([self.axes_short(cut)] if self.axes_column() else []))
        state, title, detail = self.equilibrium()
        rows += [[], [title], [detail]]
        return rows

    # ---- equilibrium -----------------------------------------------------------
    def equilibrium(self):
        """(state, title, sentence): state "ok", "bad" or "none"."""
        lang = self.lang
        rest = self.result["rest"].get(self.rank) if self.result else None
        if rest is None:
            return "none", tx("eq_wait", lang), tx("eq_wait2", lang)
        row = self.unit_row()
        dec = self.dec()

        def force(v):
            return u"{0} {1}".format(fmt(v * row[1], dec, 4), row[2])

        def numbers(values):
            return u"; ".join(fmt(v * row[1], dec, 4) for v in values)
        if self.partial() or rest.get("valid") is False:
            # rule 7 of the node cut: the layer's other nodes carry force too
            return ("none", tx("eq_partial", lang),
                    tx("eq_partial2", lang) + self._on_cut_text(force))
        s = rest["sum"]
        line = tx("eq_rest", lang).format(force(rest["largest"]), numbers(s[:3]), row[2],
                                          numbers(s[3:]), row[3])
        line += self._on_cut_text(force)
        if self.rank == 0 and len(self.steps()) > 1:
            return "none", tx("eq_start", lang), tx("eq_start2", lang) + u" " + line
        if not rest["count"]:
            return ("ok", tx("eq_ok", lang),
                    tx("eq_ok2", lang).format(force(rest["largest"])) + u" " + line)
        total = math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
        where = rest.get("where") or []
        place = u"; ".join(fmt(v * 1e3, dec, 4) for v in where[0]) if where else u"?"
        return ("bad", tx("eq_bad", lang),
                tx("eq_bad2", lang).format(rest["count"], force(rest["largest"]),
                                           force(total), place) + u" " + line)

    def _on_cut_text(self, force):
        """A sentence if the cut shown carries a support: by agreement that
        counts as the rest, but the user must see it."""
        if self.rank == 0 and len(self.steps()) > 1:
            return u""
        info = (self.result.get("on_cut") or {}).get(self.rank) or {}
        if info.get("valid") is False:
            # judged before nodes were left out (fb_nodecut.filter_result)
            return u" " + tx("eq_on_cut_unknown", self.lang)
        cut = self.cut()
        cuts = info.get("cuts") or {}
        part = None
        if cut is not None:
            part = cuts.get(cut["id"], cuts.get(str(cut["id"])))
        if not part or not part.get("count"):
            return u""
        s = part["sum"]
        return u" " + tx("eq_on_cut", self.lang).format(
            part["count"], force(part.get("largest", 0.0)),
            force(math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)))

    # ---- arrows in Mecway ---------------------------------------------------------
    def arrow_cuts(self):
        """The cuts as fb_mecway wants them, at the step shown."""
        forces = self.result["forces"][self.rank]
        out = []
        for cut in self.cuts:
            out.append({
                "id": cut["id"], "nodes": cut["group"]["nodes"],
                "points": cut["points"],
                "forces": [forces[i] for i in cut["indices"]],
                "point": self.point_undeformed(cut), "sum6": self.sum6(cut)})
        return out

    # ---- drawing -----------------------------------------------------------------
    def view(self):
        """What draw_cut needs, in metres in the plane of the undeformed cut."""
        cut = self.cut()
        if cut is None or self.rank is None:
            return None
        geo = cut["geo"]
        n, a, b = self.view_axes(cut)
        c = geo["centroid"]
        nodes = self.mesh["nodes"]

        def plane(p):
            d = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
            return (_dot(d, a), _dot(d, b))
        points = [plane(nodes[nid]) for nid in cut["group"]["nodes"]]
        section = self.is_section(cut)
        directions = (geo["axes"] if section else _GLOBAL)
        row = self.unit_row()
        dec = self.dec()
        values = clean(self.components(cut), self.size(cut))
        names = self.names(cut)
        mask = self.mask(cut)
        arrows = []
        for k in range(6):
            d = directions[k % 3]
            text = u"{0} = {1} {2}".format(names[k], fmt(values[k] * row[1], dec),
                                           row[2 if k < 3 else 3])
            if mask[k] == "doubt":
                text += u" " + tx("unreliable", self.lang)
            arrows.append({"kind": "F" if k < 3 else "M",
                           "value": 0.0 if mask[k] == "none" else values[k],
                           "text": text, "dir": (_dot(d, a), _dot(d, b), _dot(d, n))})
        if cut["node"] is not None:
            what = tx("d_node", self.lang).format(cut["node"])
        elif cut["point"] == NEUTRAL_POINT:
            what = tx("d_neutral", self.lang)
        else:
            what = tx("d_chosen", self.lang)
        shown = plane(self.point_undeformed(cut))
        letters = self.view_letters(cut, (n, a, b))
        out = {
            "title": tx("d_title", self.lang).format(cut["id"]),
            "about": tx("d_about", self.lang).format(
                what, fmt(shown[0] * 1e3, dec, 4), fmt(shown[1] * 1e3, dec, 4)),
            "real": tx("d_real", self.lang),
            "loops": geo.get("outline") or [], "points": points, "point": shown,
            "strips": self._strip_shapes(cut, plane),
            "beams": self._beam_shapes(cut, plane, dec),
            "arrows": arrows, "axis_names": letters}
        if self.nodecut is not None:
            out["plane"] = self._plane_mark(n)
        return out

    def _plane_mark(self, n):
        """The plane of a cut by nodes in the drawing: its normal is along the
        line of sight, into the picture or toward the viewer; and the side."""
        nc = self.nodecut
        normal = nc["plane"]["normal"]
        toward = _dot(normal, n) > 0
        text = tx("d_plane", self.lang).format(
            vector_text(normal, self.dec()),
            tx("d_out" if toward else "d_in", self.lang), side_sign(nc["side"]))
        if self.partial():
            text += u"  ·  " + tx("nc_partial", self.lang)
        return {"text": text, "toward": toward}

    def _strip_shapes(self, cut, plane):
        """Each strip as a thin rectangle t x L on its midline, shifted by its
        offset along w."""
        out = []
        for strip in cut["geo"].get("strips") or []:
            w = strip.get("w") or (0.0, 0.0, 0.0)
            t = float(strip.get("t") or 0.0)
            e = float(strip.get("offset") or 0.0)

            def at(p, s):
                return plane(tuple(p[k] + (e + s) * w[k] for k in range(3)))
            out.append([at(strip["a"], -t / 2.0), at(strip["b"], -t / 2.0),
                        at(strip["b"], t / 2.0), at(strip["a"], t / 2.0)])
        return out

    def _beam_shapes(self, cut, plane, dec):
        """Each beam with its outline when the section is known, else a circle
        of area A with a label."""
        out = []
        nodes = self.mesh["nodes"]
        for beam in cut["geo"].get("beams") or []:
            node = beam.get("node")
            if node not in nodes:
                continue
            x = nodes[node]
            axes = beam.get("axes") or cut["geo"]["axes"]
            # the core gives the values of the section (A, IY, ...), the
            # outline needs the cara/vale of the manifest
            loops = beam_loops(beam.get("section")) or beam_loops(
                (self._beam_component(cut, beam) or {}).get("section"))
            area = beam.get("A")
            label = None
            if not loops and area:
                loops = [_round(math.sqrt(float(area) / math.pi))]
                label = tx("d_area", self.lang).format(fmt(float(area) * 1e6, dec, 4))
            shapes = []
            for loop in loops:
                shapes.append([plane(tuple(x[k] + y * axes[1][k] + z * axes[2][k]
                                           for k in range(3))) for y, z in loop])
            out.append({"loops": shapes, "label": label, "at": plane(x)})
        return out


# ==========================================
# THE MAP OF THE DRAWING
# ==========================================
def view_map(view, w, h, top=30.0, bottom=44.0, keep_point=True):
    """Scale and centre of the drawing: {"s", "ox", "oy", "cu", "cv"}. Fixed by
    the section; keep_point also fits the point, not while it is dragged. A
    cut by nodes has a line about its plane under the title."""
    if view.get("plane"):
        top += PLANE_LINE
    loops = list(view["loops"]) + list(view.get("strips") or [])
    for beam in view.get("beams") or []:
        loops += beam["loops"]
    us = [p[0] for loop in loops for p in loop] + [p[0] for p in view["points"]]
    vs = [p[1] for loop in loops for p in loop] + [p[1] for p in view["points"]]
    if keep_point or not us:
        us = us + [view["point"][0], 0.0]
        vs = vs + [view["point"][1], 0.0]
    size = max(max(us) - min(us), max(vs) - min(vs)) or 1e-3
    cu = (max(us) + min(us)) / 2.0
    cv = (max(vs) + min(vs)) / 2.0
    height = max(40.0, h - top - bottom)
    margin = min(70.0, 0.2 * min(w, height))
    s = min((w - 2 * margin) / size, (height - 2 * margin) / size)
    s = max(s, 1e-6)
    return {"s": s, "ox": w / 2.0, "oy": top + height / 2.0, "cu": cu, "cv": cv}


def to_pixel(m, u, v):
    return (m["ox"] + (u - m["cu"]) * m["s"], m["oy"] - (v - m["cv"]) * m["s"])


def from_pixel(m, x, y):
    return (m["cu"] + (x - m["ox"]) / m["s"], m["cv"] - (y - m["oy"]) / m["s"])


def not_shared_text(value):
    """The kinds in a manifest's not_shared: a list in schema 1, a dict
    {kind: {"nodes", "origin"}} in schema 2."""
    if isinstance(value, dict):
        return u", ".join(sorted(u"{0}".format(k) for k in value))
    if isinstance(value, (list, tuple)):
        return u", ".join(u"{0}".format(k) for k in value)
    return u""


def has_shells(mesh):
    return any(shape in fb_mecway.SHELL_SHAPES for shape, _ in mesh["elements"].values())


def selection_differs(selected, inside):
    """True if a polled selection is not the one a table was made for. None:
    not known."""
    if selected is None or inside is None:
        return False
    return sorted(selected) != sorted(inside)


def chosen_ids(selection, mode):
    """The ids a cut is made of: the selected elements, or the selected nodes
    for a cut by nodes on a plane."""
    if not selection:
        return []
    return list(selection.get("node_ids" if mode == "nodes" else "elements") or [])


def selection_key(selection, mode):
    """(mode, sorted ids) of a polled selection, to compare with
    PanelModel.basis(); None: not known."""
    if selection is None:
        return None
    return (mode, sorted(chosen_ids(selection, mode)))


def plan_and_start(mesh, ids, mode, side, props, man, folder, exe):
    """Worker: the cut and the start of its run, (plan, geos, job, cut). By
    elements: fb_core.plan_cuts, cut None. By nodes on a plane:
    fb_nodecut.plan_from_nodes with its reduced plan, and its filter on the
    result of the run. Refused when there is no cut."""
    cut = None
    prepare = None
    if mode == "nodes":
        cut = fb_nodecut.plan_from_nodes(mesh, ids, side)
        plan = cut["plan"]

        def prepare(result):
            return fb_nodecut.filter_result(result, cut)
    else:
        plan = fb_core.plan_cuts(mesh, ids)
    if not plan["groups"]:
        raise fb_core.Refused("no_cut", "")
    geos = dict((g["id"], fb_core.section_geometry(mesh, g, props)) for g in plan["groups"])
    if prepare is None:
        job = fb_aster.start(man, folder, plan, mesh, exe)
    else:
        # Job.result() filters before the equilibrium is judged; a refusal of
        # the filter (node_mismatch) comes out of job.result()
        job = fb_aster.start(man, folder, plan, mesh, exe, prepare=prepare)
    return plan, geos, job, cut


def foreign_run(man, path):
    """True if a run carries the name of another model than the open one. An
    unsaved model has no name to compare."""
    name = man.get("model")
    if not name or not path or not os.path.dirname(path):
        return False
    return fb_mecway.model_stem(name) != fb_mecway.model_stem(path)


def solution_state(result, values):
    """None, "stale" or "unknown": does this run belong to the solution open in
    Mecway? fb_aster decides; without its check nothing can be told."""
    check = getattr(fb_aster, "check_solution", None)
    return "unknown" if check is None else check(result, None, values)


def near_point(m, view, x, y, reach=GRAB_PX):
    px, py = to_pixel(m, view["point"][0], view["point"][1])
    return (x - px) ** 2 + (y - py) ** 2 <= reach * reach


# ==========================================
# ONE WINDOW PER MECWAY PROCESS
# ==========================================
def claim_instance():
    """Token for release_instance(), True without .NET, or None when the
    window is already open in this Mecway process."""
    try:
        from System.Threading import Semaphore
        from System.Diagnostics import Process
        name = _INSTANCE_NAME.format(Process.GetCurrentProcess().Id)
    except Exception:
        return True
    semaphore = Semaphore(1, 1, name)
    if not semaphore.WaitOne(0):
        semaphore.Dispose()
        return None
    return semaphore


def release_instance(token):
    if token is None or token is True:
        return
    try:
        token.Release()
    finally:
        token.Dispose()


def activate_existing():
    """Bring the open window forward (second start of the script). Win32 by
    title: a second start may run in a fresh script engine without Windows
    Forms. Returns True when it was found."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.FindWindowExW.restype = ctypes.c_void_p
        user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]    # focus: second start
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        hwnd = None
        while True:
            hwnd = user32.FindWindowExW(None, hwnd, None, PANEL_TITLE)
            if not hwnd:
                return False
            owner = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)      # focus: SW_RESTORE, second start
                user32.SetForegroundWindow(hwnd)    # focus: second start
                return True
    except Exception:
        return False


# ==========================================
# MW CALLS FROM THE WINDOW THREAD
# ==========================================
class _MwCaller(object):
    """
    The window hands work that uses mw to the script thread and looks for the
    answer later; it never waits. post(fn) is one call, post_steps(generator)
    is work in chunks with Mecway's messages in between. A ticket is a dict:
    "done", "result", "error". direct=True runs at once (tests).
    """

    def __init__(self, direct=False):
        self.direct = direct
        self._lock = threading.Lock()
        self._queue = []

    def _run_step(self, ticket):
        """One piece of a ticket; True when it is finished."""
        try:
            gen = ticket.get("gen")
            if gen is None:
                ticket["result"] = ticket["fn"]()
                return True
            next(gen)
            return False
        except StopIteration:
            return True
        except Exception as e:
            ticket["error"] = e
            ticket["trace"] = traceback.format_exc()
            return True

    def _add(self, ticket):
        ticket["done"] = False
        ticket["cancelled"] = False
        if self.direct:
            while not self._run_step(ticket):
                pass
            ticket["done"] = True
            return ticket
        with self._lock:
            self._queue.append(ticket)
        return ticket

    def post(self, fn):
        return self._add({"fn": fn})

    def post_steps(self, gen):
        return self._add({"gen": gen})

    def cancel(self, ticket):
        """A ticket that took too long leaves the queue: it does not run when
        Mecway is back."""
        ticket["cancelled"] = True
        with self._lock:
            if ticket in self._queue:
                self._queue.remove(ticket)

    def cancel_all(self):
        with self._lock:
            for ticket in self._queue:
                ticket["cancelled"] = True
            self._queue = []

    def serve_once(self):
        """Script thread: one piece of the oldest request, if any."""
        with self._lock:
            ticket = self._queue[0] if self._queue else None
        if ticket is None:
            return False
        finished = self._run_step(ticket)
        if finished:
            with self._lock:
                if ticket in self._queue:
                    self._queue.remove(ticket)
            ticket["done"] = True
        return True

    def serve(self, thread, pump=None):
        """Script thread: run requests and keep Mecway's messages going until
        the window thread ends."""
        while thread.IsAlive:
            self.serve_once()
            if pump is not None:
                try:
                    pump()
                except Exception:
                    log(u"pump: {0}".format(traceback.format_exc()))
            thread.Join(10)
        self.cancel_all()


class _Worker(object):
    """A python thread for the heavy sums. It writes in a slot the timer reads;
    it touches no control and an error never leaves it."""

    def __init__(self, fn):
        self.fn = fn
        self.done = False
        self.value = None
        self.error = None
        self.trace = None
        self.after = None
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def _run(self):
        try:
            self.value = self.fn()
        except Exception as e:
            self.error = e
            self.trace = traceback.format_exc()
        with self._lock:
            self.done = True
            after = self.after
        if after is not None:
            after(self)

    def when_done(self, fn):
        """fn(worker) once the work has ended, now if it already has. For a
        worker nobody looks at any more."""
        with self._lock:
            self.after = fn
            done = self.done
        if done:
            fn(self)


def _stop_started_job(worker):
    """A planning worker that lost its window: stop the run it started."""
    try:
        if worker.value is not None:
            worker.value[2].stop()
    except Exception:
        log(u"late stop: {0}".format(traceback.format_exc()))


# ==========================================
# THE WINDOW
# ==========================================
def run_window(mw, solution=None, options=None):
    """Show the window until the user closes it. ImportError when Windows
    Forms cannot be loaded. options (tests): "no_activate", "location",
    "size", "on_ready": fn(window), "on_thread": fn() on the window thread
    before any control, returning a function for when the window is gone (or
    None)."""
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Threading import Thread, ThreadStart, ApartmentState
        from System.Windows.Forms import Application
    except Exception as e:
        raise ImportError(u"Windows Forms: {0}".format(e))
    outcome = {"error": None}
    caller = _MwCaller(False)

    def build_and_run():
        after = None
        try:
            on_thread = (options or {}).get("on_thread")
            if on_thread is not None:
                after = on_thread()
            from System.Windows.Forms import Application as App
            from System.Windows.Forms import UnhandledExceptionMode as Mode
            # Before any control or timer of this thread: without this .NET
            # shows its dialog with Quit, which closes Mecway without saving.
            try:
                App.SetUnhandledExceptionMode(Mode.CatchException, True)
            except Exception:
                log(u"mode: {0}".format(traceback.format_exc()))
            window = _Window(mw, solution, caller, options)
            App.ThreadException += window.on_thread_exception
            try:
                App.Run(window.form)
            finally:
                App.ThreadException -= window.on_thread_exception
        except Exception:
            outcome["error"] = traceback.format_exc()
        finally:
            if after is not None:
                try:
                    after()
                except Exception:
                    log(u"after: {0}".format(traceback.format_exc()))

    thread = Thread(ThreadStart(build_and_run))
    thread.SetApartmentState(ApartmentState.STA)
    thread.IsBackground = True
    thread.Start()
    on_ui_thread = (Thread.CurrentThread.GetApartmentState() ==
                    ApartmentState.STA)
    caller.serve(thread, Application.DoEvents if on_ui_thread else None)
    if outcome["error"]:
        raise RuntimeError(outcome["error"])


def _forms():
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    import System.Drawing as D
    import System.Windows.Forms as F
    return D, F


_CLICK_SAFE = {}


def _no_version(self):
    return u""


def click_safe_button():
    """A Button whose click does not depend on WindowFromPoint: a window of
    Mecway's thread over the spot swallowed clicks (seen in an earlier tool).
    It clicks on a release inside its own area after a press on it. The three
    properties keep TypeDescriptor working on an IronPython subclass: Windows
    Forms asks them when a click goes wrong."""
    cls = _CLICK_SAFE.get("Button")
    if cls is not None:
        return cls
    D, F = _forms()
    base = F.Button
    left = F.MouseButtons.Left
    native = F.FlatStyle.System

    class ClickSafe(base):
        CompanyName = property(_no_version)
        ProductName = property(_no_version)
        ProductVersion = property(_no_version)

        def OnMouseDown(self, e):
            self._fb_down = e.Button == left
            base.OnMouseDown(self, e)

        def OnClick(self, e):
            self._fb_clicked = True
            base.OnClick(self, e)

        def OnMouseUp(self, e):
            down = getattr(self, "_fb_down", False)
            self._fb_down = False
            self._fb_clicked = False
            base.OnMouseUp(self, e)
            if down and not self._fb_clicked and e.Button == left and \
                    self.FlatStyle != native and self.Enabled and \
                    self.ClientRectangle.Contains(e.Location):
                self.OnClick(e)

    _CLICK_SAFE["Button"] = ClickSafe
    return ClickSafe


WS_EX_NOACTIVATE = 0x08000000


def quiet_form_class():
    """The form of the tests (option no_activate): shown without activation,
    and with WS_EX_NOACTIVATE, so Windows does not make it the foreground
    window when another program's foreground window closes or is minimized,
    nor on a click. In CreateParams, which Windows Forms also reads when it
    sets the styles again after the handle is made (a style set on the handle
    itself was gone by the time the window showed; measured). Not for the user:
    such a window cannot be typed into."""
    cls = _CLICK_SAFE.get("QuietForm")
    if cls is not None:
        return cls
    D, F = _forms()
    base = F.Form

    class QuietForm(base):
        CompanyName = property(_no_version)
        ProductName = property(_no_version)
        ProductVersion = property(_no_version)

        def get_ShowWithoutActivation(self):
            return True

        def get_CreateParams(self):
            params = super(QuietForm, self).CreateParams
            params.ExStyle |= WS_EX_NOACTIVATE
            return params

    _CLICK_SAFE["QuietForm"] = QuietForm
    return QuietForm


def has_no_activate(hwnd):
    """WS_EX_NOACTIVATE on this window (the tests check quiet_form_class)."""
    import ctypes
    user32 = ctypes.windll.user32
    try:
        get = user32.GetWindowLongPtrW
    except AttributeError:                  # 32-bit Windows has only this one
        get = user32.GetWindowLongW
    get.restype = ctypes.c_ssize_t
    get.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return bool(get(ctypes.c_void_p(hwnd), -20) & WS_EX_NOACTIVATE)    # GWL_EXSTYLE


C = {}


def _colors():
    D, F = _forms()
    if not C:
        rgb = D.Color.FromArgb
        C.update({
            "header": rgb(32, 41, 54), "header_sub": rgb(170, 182, 196),
            "accent": rgb(0, 120, 212), "text": rgb(30, 30, 30),
            "muted": rgb(105, 112, 120), "line": rgb(225, 229, 234),
            "band": rgb(247, 249, 251), "bg": D.Color.White,
            "fill": rgb(207, 227, 247), "edge": rgb(31, 59, 87),
            "force": rgb(209, 52, 47), "moment": rgb(124, 58, 175),
            "grey": rgb(120, 126, 134), "point": rgb(242, 140, 40),
            "error": rgb(180, 30, 30),
            "ok_bg": rgb(222, 241, 226), "ok_text": rgb(20, 90, 50),
            "bad_bg": rgb(250, 222, 222), "bad_text": rgb(150, 20, 20),
            "none_bg": rgb(238, 241, 245), "none_text": rgb(80, 86, 94),
        })
    return C


def ui_scale():
    """Screen dots per 96: the layout in pixels follows the fonts in points."""
    try:
        from System.Drawing import Graphics
        from System import IntPtr
        g = Graphics.FromHwnd(IntPtr.Zero)
        try:
            return max(1.0, float(g.DpiY) / 96.0)
        finally:
            g.Dispose()
    except Exception:
        return 1.0


def open_web(url):
    """A web address of a link in the documentation, in the default browser;
    only http and https get here (fb_docs.resolve_link)."""
    from System.Diagnostics import Process
    Process.Start(url)


class _Window(object):
    def __init__(self, mw, solution, caller, options=None):
        self.mw = mw
        self.solution = solution
        self.caller = caller
        self.options = options or {}
        self.lang = language()
        self.model = PanelModel()
        self.model.lang = self.lang
        values = settings()
        self.model.unit = values.get("unit") if values.get("unit") in ("N", "kN") else "N"
        self.model.axes = "global" if values.get("axes") == "global" else "section"
        self.folder_choice = values.get("folder") or "auto"
        self.folder_other = values.get("folder_other") or u""
        self.arrow_mode = values.get("arrow_mode") or "nodes"
        # the cut: by the selected elements, or by the selected nodes on a
        # plane with a side (1: where the plane normal points, -1: the other)
        self.cut_mode = values.get("cut_mode") if values.get("cut_mode") in CUT_MODES \
            else "elements"
        self.side = 1
        self.phase = None           # read, scan, plan, run, finish
        self.failed_run = False     # the last computation did not succeed
        self.selected_now = None    # last polled selection
        self.outdated = False       # the table is not of the present selection
        self.pending_model = None   # a result waiting for the check of the solution
        self.close_reason = None
        self.plan_state = {}
        self.want_compute = False
        self.auto = True            # first scan: compute if there is a selection
        self.wait = None            # (ticket, out, deadline)
        self.worker = None
        self.job = None
        self.started = 0.0
        self.asks = []              # [(ticket, fn(out, error), deadline, out)]
        self.selection_busy = False
        self.ticks = 0
        self.last = {}              # path, selection, mesh, props of the last read
        self.scan = {"runs": [], "folders": [], "other": 0, "bridge": None,
                     "version": None, "fingerprint": None}
        self.run_id = None
        self.run_refusal = None
        self.status = u""
        self.status_error = False
        self.selection_text = u""
        self.selection_seen = {"elements": [], "node_ids": [], "faces": []}
        self.status_done = None
        self.arrow_text = u""
        self.arrow_state = None     # outcome of the last write of arrows
        self.own = {}               # what this panel wrote in the solution
        self.drag = False
        self.drag_time = 0.0
        self.map = None
        self.view = None
        self._filling = False
        self._doc_quiet = False
        D, F = _forms()
        self.D, self.F = D, F
        self.k = ui_scale()
        form = self._make_form()
        form.AutoScaleMode = getattr(F.AutoScaleMode, "None")
        form.Text = PANEL_TITLE
        form.BackColor = _colors()["bg"]
        form.FormBorderStyle = F.FormBorderStyle.Sizable
        form.StartPosition = F.FormStartPosition.CenterScreen
        form.Font = D.Font("Segoe UI", 9.0)
        # The tabs take a strip and a border from the panel: the window is larger by
        # as much, so the panel keeps its size. Set before the window has a handle:
        # MinimumSize on a window with one moves it without SWP_NOACTIVATE, which
        # activates it (measured in the tests).
        dw, dh = self.tab_border = self._tab_border(form.Font)
        form.ClientSize = D.Size(self.px(1180) + dw, self.px(780) + dh)
        form.MinimumSize = D.Size(self.px(960) + dw, self.px(660) + dh)
        if "location" in self.options:
            form.StartPosition = F.FormStartPosition.Manual
            form.Location = D.Point(*self.options["location"])
        if "size" in self.options:
            form.ClientSize = D.Size(*self.options["size"])
        self.form = form
        self.timer = F.Timer()
        self.timer.Interval = TICK_MS
        self.timer.Tick += self._on_tick
        form.Shown += self._guard(self._on_shown)
        # the panel lays itself out when its body changes size (_on_body_size):
        # a hidden tab gets its size only when it is shown again
        form.FormClosing += self._on_closing
        # the documentation tab (fb_docs): which tab and document are open, kept
        # over a render; open_web opens a web address (tests replace it)
        self.tab = "panel"
        self.doc_rel = fb_docs.doc_list(self.lang)[0][1]
        self.doc_anchor = None
        self.use_browser = self.options.get("doc_browser", True)
        self.open_web = self.options.get("open_web") or open_web
        self.render()

    def _make_form(self):
        F = self.F
        if not self.options.get("no_activate"):
            return F.Form()
        form = quiet_form_class()()
        form.ShowInTaskbar = False
        return form

    # ---------------- helpers ----------------
    def px(self, value):
        return int(round(value * self.k))

    def t(self, key):
        return tx(key, self.lang)

    def _guard(self, fn):
        """An event handler that cannot take the window down."""
        def handler(sender=None, args=None):
            try:
                fn()
            except Exception as e:
                log(u"handler: {0}".format(traceback.format_exc()))
                self._set_status(tx("r_error", self.lang).format(e), True)
        return handler

    def on_thread_exception(self, sender, args):
        log(u"thread: {0}".format(args.Exception))
        self._set_status(tx("r_error", self.lang).format(args.Exception.Message), True)

    def _set_status(self, text, error=False):
        self.status, self.status_error = text, error
        self.status_done = None
        lb = getattr(self, "status_label", None)
        if lb is not None and not lb.IsDisposed:
            lb.Text = text
            lb.ForeColor = _colors()["error" if error else "muted"]

    def _label(self, parent, text, x, y, w, h, size=9.0, bold=False, color=None,
               align=None, back=None, wrap=False):
        D, F = self.D, self.F
        lb = F.Label()
        lb.Text = text
        lb.Location = D.Point(self.px(x), self.px(y))
        lb.Size = D.Size(self.px(w), self.px(h))
        lb.Font = D.Font("Segoe UI", size,
                         D.FontStyle.Bold if bold else D.FontStyle.Regular)
        lb.ForeColor = color if color is not None else _colors()["text"]
        lb.TextAlign = align if align is not None else \
            (D.ContentAlignment.TopLeft if wrap else D.ContentAlignment.MiddleLeft)
        lb.BackColor = back if back is not None else D.Color.Transparent
        lb.AutoEllipsis = not wrap
        parent.Controls.Add(lb)
        return lb

    def _fit_label(self, label, slot):
        """Make a one-line label as wide as its text, at least slot (in 96ths
        of an inch), and return that width: the field next to it starts
        after it, in any language and font size."""
        need = self.F.TextRenderer.MeasureText(label.Text or u" ", label.Font).Width
        width = max(self.px(slot), need + self.px(2))
        label.Width = width
        return width

    def _button(self, parent, text, x, y, w, fn, primary=False, h=28):
        D, F = self.D, self.F
        b = click_safe_button()()
        b.Text = text
        b.Location = D.Point(self.px(x), self.px(y))
        b.Size = D.Size(self.px(w), self.px(h))
        b.FlatStyle = F.FlatStyle.Flat
        b.Font = D.Font("Segoe UI", 9.0)
        b.Cursor = F.Cursors.Hand
        col = _colors()
        if primary:
            b.BackColor = col["accent"]
            b.ForeColor = D.Color.White
            b.FlatAppearance.BorderSize = 0
        else:
            b.BackColor = col["bg"]
            b.ForeColor = col["text"]
            b.FlatAppearance.BorderColor = D.Color.FromArgb(200, 205, 212)
        b.Click += self._guard(fn)
        parent.Controls.Add(b)
        return b

    def _combo(self, parent, x, y, w, items, fn):
        D, F = self.D, self.F
        cb = F.ComboBox()
        cb.DropDownStyle = F.ComboBoxStyle.DropDownList
        cb.Location = D.Point(self.px(x), self.px(y))
        cb.Size = D.Size(self.px(w), self.px(24))
        for item in items:
            cb.Items.Add(item)
        cb.SelectedIndexChanged += self._guard(fn)
        parent.Controls.Add(cb)
        return cb

    def _radio(self, parent, text, x, y, checked, fn):
        D, F = self.D, self.F
        rb = F.RadioButton()
        rb.FlatStyle = F.FlatStyle.System    # no subclass: Windows handles its clicks
        rb.Text = text
        rb.AutoSize = True
        rb.Location = D.Point(self.px(x), self.px(y))
        rb.Checked = checked
        rb.CheckedChanged += self._guard(fn)
        parent.Controls.Add(rb)
        return rb

    def _textbox(self, parent, x, y, w, fn):
        D, F = self.D, self.F
        tb = F.TextBox()
        tb.Location = D.Point(self.px(x), self.px(y))
        tb.Size = D.Size(self.px(w), self.px(24))
        tb.TextChanged += self._guard(fn)
        parent.Controls.Add(tb)
        return tb

    # ---------------- building ----------------
    def render(self):
        """Build every control; all state lives elsewhere, so the language
        switch is one more render."""
        D, F = self.D, self.F
        col = _colors()
        form = self.form
        self._filling = True
        form.SuspendLayout()
        # Disposing the form's active control makes Windows Forms focus the next
        # one (ContainerControl.AfterControlRemoved), whether the window has the
        # focus or not, and that activates the window: an inactive panel would
        # take the focus from Mecway. It forgets that control first.
        if form.IsHandleCreated and not form.ContainsFocus:
            form.ActiveControl = None
        for c in list(form.Controls):
            c.Dispose()
        form.Controls.Clear()
        W = form.ClientSize.Width
        # bar and run strip sit in the panel tab: narrower by the tab border
        Wp = W - self.tab_border[0]

        header = F.Panel()
        header.BackColor = col["header"]
        header.Dock = F.DockStyle.Top
        header.Size = D.Size(W, self.px(56))
        self._label(header, self.t("title") + u"  ·  " + PANEL_TITLE + u" " + fb_core.VERSION,
                    16, 4, 640, 28,
                    13, True, D.Color.White)
        self.subtitle = self._label(header, self.last.get("path") or self._sub_text(),
                                    16, 31, 700, 20, 8.5, False, col["header_sub"])
        langs = F.FlowLayoutPanel()
        langs.Dock = F.DockStyle.Right
        langs.Width = self.px(120)
        langs.Padding = F.Padding(0, self.px(15), 0, 0)
        langs.BackColor = col["header"]
        for code in LANGS:
            b = click_safe_button()()
            b.Text = code.upper()
            b.Size = D.Size(self.px(46), self.px(26))
            b.FlatStyle = F.FlatStyle.Flat
            b.Font = D.Font("Segoe UI", 9.0, D.FontStyle.Bold)
            b.ForeColor = D.Color.White
            b.BackColor = col["accent"] if code == self.lang else col["header"]
            b.FlatAppearance.BorderColor = col["header_sub"]
            b.Cursor = F.Cursors.Hand
            b.Click += self._guard(self._lang_handler(code))
            langs.Controls.Add(b)
        header.Controls.Add(langs)

        bar = F.Panel()
        bar.BackColor = col["band"]
        bar.Dock = F.DockStyle.Top
        bar.Size = D.Size(Wp, self.px(76))
        self.compute_button = self._button(bar, self.t("compute"), 16, 8, 110,
                                           self.on_compute, True)
        self.stop_button = self._button(bar, self.t("stop"), 134, 8, 64, self.on_stop)
        self.progress = F.ProgressBar()
        self.progress.Style = F.ProgressBarStyle.Marquee
        self.progress.MarqueeAnimationSpeed = 30
        self.progress.Location = D.Point(self.px(208), self.px(14))
        self.progress.Size = D.Size(self.px(130), self.px(16))
        self.progress.Visible = False
        bar.Controls.Add(self.progress)
        # How the cut is made: by the selected elements, or by the selected
        # nodes on a plane with a side (docs/design/knopensnede-plan.md)
        self.mode_label = self._label(bar, self.t("mode"), 348, 10, 64, 24)
        self.mode_combo = self._combo(bar, 414, 10, 150,
                                      [self.t("mode_" + m) for m in CUT_MODES],
                                      self._on_mode)
        self.mode_combo.SelectedIndex = CUT_MODES.index(self.cut_mode)
        self.side_button = self._button(bar, self.t("side_button"), 570, 9, 100,
                                        self.on_side, h=26)
        self._set_selection_text(self.selection_seen, False)
        # each field after its label, as wide as the label's text (the old
        # places are the least: 414, 570, 678)
        self.mode_combo.Left = self.px(348) + self._fit_label(self.mode_label, 64) + self.px(2)
        self.side_button.Left = self.mode_combo.Right + self.px(6)
        left = self.side_button.Right + self.px(8)
        self.selection_label = self._label(bar, self.selection_text, 678, 10, 300, 24)
        self.selection_label.Left = left
        self.selection_label.Width = max(self.px(120), Wp - left - self.px(16))
        self.selection_label.Anchor = (F.AnchorStyles.Left | F.AnchorStyles.Right |
                                       F.AnchorStyles.Top)
        self.folder_label = self._label(bar, self.t("folder"), 16, 45, 70, 24)
        keys = [c for c, _ in FOLDER_CHOICES]
        self.folder_combo = self._combo(bar, 86, 45, 165,
                                        [self.t(k) for _, k in FOLDER_CHOICES],
                                        self._on_folder)
        self.folder_combo.Left = self.px(16) + self._fit_label(self.folder_label, 68) + \
            self.px(2)
        self.folder_combo.SelectedIndex = (keys.index(self.folder_choice)
                                           if self.folder_choice in keys else 0)
        self.browse_button = self._button(bar, self.t("browse"), 258, 44, 76,
                                          self.on_browse, h=26)
        self.browse_button.Left = self.folder_combo.Right + self.px(7)
        self.run_title = self._label(bar, self.t("run"), 344, 45, 36, 24)
        self.run_title.Left = self.browse_button.Right + self.px(10)
        self.run_combo = self._combo(bar, 382, 45, 380, [], self._on_run)
        self.run_combo.Left = self.run_title.Left + self._fit_label(self.run_title, 36) + \
            self.px(2)
        self.run_combo.Width = max(self.px(160), Wp - self.run_combo.Left - self.px(16))
        self.run_combo.Anchor = (F.AnchorStyles.Left | F.AnchorStyles.Right |
                                 F.AnchorStyles.Top)

        run_strip = F.Panel()
        run_strip.BackColor = col["band"]
        run_strip.Dock = F.DockStyle.Top
        run_strip.Size = D.Size(Wp, self.px(24))
        self.run_label = self._label(run_strip, u"", 16, 0, 900, 22, 8.5)
        self.run_label.Width = Wp - self.px(32)
        self.run_label.Anchor = (F.AnchorStyles.Left | F.AnchorStyles.Right |
                                 F.AnchorStyles.Top)

        footer = F.Panel()
        footer.BackColor = col["band"]
        footer.Dock = F.DockStyle.Bottom
        footer.Size = D.Size(W, self.px(46))
        if getattr(self, "status_done", None):
            self.status = self.t("done").format(*self.status_done)
        self.status_label = self._label(footer, self.status, 16, 6, 400, 34, 9)
        self.status_label.Width = W - self.px(16 + 530)
        self.status_label.Anchor = (F.AnchorStyles.Left | F.AnchorStyles.Right |
                                    F.AnchorStyles.Top)
        self._set_status(self.status, self.status_error)
        for offset, width, key, fn in ((110, 100, "close", self.form.Close),
                                       (214, 96, "csv", self.on_csv),
                                       (350, 126, "copy_img", self.on_copy_image),
                                       (440, 80, "copy", self.on_copy)):
            b = self._button(footer, self.t(key), 0, 9, width, fn)
            b.Location = D.Point(W - self.px(offset + 6), self.px(9))
            b.Anchor = F.AnchorStyles.Right | F.AnchorStyles.Top

        body = F.Panel()
        body.Dock = F.DockStyle.Fill
        body.BackColor = col["bg"]
        self.body = body
        self.left = F.Panel()
        self.left.BackColor = col["bg"]
        body.Controls.Add(self.left)
        self.right = F.Panel()
        self.right.BackColor = col["bg"]
        body.Controls.Add(self.right)
        self._build_left()
        self._build_right()
        body.SizeChanged += self._guard(self._on_body_size)

        # Two tabs between header and footer: the panel, and the documentation
        # (fb_docs; its page is built when it is first opened). Header and
        # footer stay on both: language, status and Close.
        tabs = F.TabControl()
        tabs.Dock = F.DockStyle.Fill
        page_main = F.TabPage()
        page_docs = F.TabPage()
        for page, text in ((page_main, self.t("title")),
                           (page_docs, fb_docs.tx("tab", self.lang))):
            page.Text = text
            page.Padding = F.Padding(0)
            page.UseVisualStyleBackColor = False
            page.BackColor = col["bg"]
            tabs.TabPages.Add(page)
        # their real size before the bar goes in: its anchors are taken from the
        # size its parent has then (a new TabPage is 200 x 100)
        inner_h = max(self.px(100), form.ClientSize.Height - header.Height - footer.Height)
        tabs.Size = D.Size(W, inner_h)
        for page in (page_main, page_docs):
            page.Size = D.Size(Wp, max(self.px(50), inner_h - self.tab_border[1]))
        page_main.Controls.Add(body)
        page_main.Controls.Add(run_strip)
        page_main.Controls.Add(bar)
        self.tabs, self.page_docs = tabs, page_docs
        self.doc_view = self.doc_browser = self.doc_list = None
        self.chrome_h = header.Height + bar.Height + run_strip.Height + footer.Height

        # The tab is chosen before the TabControl has a handle: selecting one
        # afterwards in code focuses a control of the page, which activates the
        # window (TabControl.UpdateTabSelection). See show_tab.
        if self.tab == "docs":
            tabs.SelectedIndex = 1      # focus: none, the TabControl has no handle yet
        tabs.SelectedIndexChanged += self._guard(self._on_tab)
        form.Controls.Add(tabs)
        form.Controls.Add(footer)
        form.Controls.Add(header)
        form.ResumeLayout()
        self._fill_runs()
        self._filling = False
        if self.tab == "docs":
            self._build_docs()
        self._layout()
        self._refresh()
        self._update_buttons()

    def _build_left(self):
        D, F = self.D, self.F
        col = _colors()
        p = self.left
        self.banner = F.Panel()
        self.banner_title = self._label(self.banner, u"", 10, 3, 500, 22, 10.5, True)
        self.banner_text = self._label(self.banner, u"", 10, 25, 500, 52, 8.5, wrap=True)
        self.banner_title.BackColor = D.Color.Transparent
        p.Controls.Add(self.banner)

        self.step_label = self._label(p, self.t("step"), 0, 0, 40, 24)
        self.step_combo = self._combo(p, 0, 0, 150, [], self._on_step)
        self.axes_label = self._label(p, self.t("axes"), 0, 0, 44, 24)
        self.radio_section = self._radio(p, self.model.radio_text(), 0, 0,
                                         self.model.axes == "section", self._on_axes)
        self.radio_global = self._radio(p, self.t("ax_global"), 0, 0,
                                        self.model.axes == "global", self._on_axes)
        self.unit_label = self._label(p, self.t("unit"), 0, 0, 54, 24)
        self.unit_combo = self._combo(p, 0, 0, 70, [u[0] for u in UNITS], self._on_unit)
        self.unit_combo.SelectedIndex = 1 if self.model.unit == "kN" else 0
        self.axes_note = self._label(p, self.model.axes_note(), 0, 0, 500, 18, 8.0, False,
                                     col["muted"], wrap=True)

        self.outdated_label = self._label(p, self.t("outdated"), 0, 0, 400, 20, 9, True,
                                          col["error"])
        self.outdated_label.Visible = self.outdated
        lv = F.ListView()
        lv.View = F.View.Details
        lv.ForeColor = col["grey" if self.outdated else "text"]
        lv.FullRowSelect = True
        lv.GridLines = True
        lv.HideSelection = False
        lv.MultiSelect = False
        lv.ItemSelectionChanged += self._guard(self._on_table)
        p.Controls.Add(lv)
        self.table = lv

        self.sign_label = self._label(p, self.model.sign_text(), 0, 0, 500, 46, 8.0, False,
                                      col["muted"], wrap=True)
        tb = F.TextBox()
        tb.Multiline = True
        tb.ReadOnly = True
        tb.ScrollBars = F.ScrollBars.Vertical
        tb.BorderStyle = F.BorderStyle.FixedSingle
        tb.BackColor = col["band"]
        tb.Font = D.Font("Segoe UI", 8.5)
        p.Controls.Add(tb)
        self.warning_box = tb

        self.arrow_title = self._label(p, self.t("arrows"), 0, 0, 110, 24, 9, True)
        self.arrow_combo = self._combo(p, 0, 0, 130,
                                       [self.t("a_nodes"), self.t("a_result")],
                                       self._on_arrow_mode)
        self.arrow_combo.SelectedIndex = 1 if self.arrow_mode == "resultant" else 0
        self.arrow_button = self._button(p, self.t("a_write"), 0, 0, 110, self.on_arrows,
                                         h=26)
        tb = F.TextBox()
        tb.Multiline = True
        tb.ReadOnly = True
        tb.BorderStyle = getattr(F.BorderStyle, "None")
        tb.BackColor = col["bg"]
        tb.Font = D.Font("Segoe UI", 8.0)
        p.Controls.Add(tb)
        self.arrow_label = tb
        self._show_arrows()

    def _build_right(self):
        D, F = self.D, self.F
        col = _colors()
        p = self.right
        self.picture = F.PictureBox()
        self.picture.SizeMode = F.PictureBoxSizeMode.Normal
        self.picture.BackColor = col["bg"]
        self.picture.MouseDown += self._mouse(self.on_mouse_down)
        self.picture.MouseMove += self._mouse(self.on_mouse_move)
        self.picture.MouseUp += self._mouse(self.on_mouse_up)
        p.Controls.Add(self.picture)
        self.point_title = self._label(p, self.t("point"), 0, 0, 44, 24, 9, True)
        self.point_boxes = [self._textbox(p, 0, 0, 74, self._on_point_typed)
                            for _ in range(3)]
        self.point_hint = self._label(p, u"", 0, 0, 220, 24, 8.0, False, col["muted"])
        self.neutral_button = self._button(p, self.t("neutral"), 0, 0, 110,
                                           self.on_neutral, h=26)
        self.node_box = self._textbox(p, 0, 0, 70, lambda: None)
        self.node_button = self._button(p, self.t("node"), 0, 0, 60, self.on_node, h=26)
        tips = F.ToolTip()
        tips.SetToolTip(self.node_box, self.t("node_tip"))
        tips.SetToolTip(self.mode_label, self.t("mode_tip"))
        tips.SetToolTip(self.mode_combo, self.t("mode_tip"))
        tips.SetToolTip(self.side_button, self.t("side_tip"))
        tips.SetToolTip(self.node_button, self.t("node_tip"))
        self.tips = tips

    def _mouse(self, fn):
        def handler(sender, e):
            try:
                fn(e.X, e.Y)
            except Exception as ex:
                log(u"mouse: {0}".format(traceback.format_exc()))
                self.drag = False
                self._set_status(tx("r_error", self.lang).format(ex), True)
        return handler

    def _layout(self):
        body = getattr(self, "body", None)
        if body is None or body.IsDisposed:
            return
        D = self.D
        px = self.px
        w, h = body.ClientSize.Width, body.ClientSize.Height
        if w < px(100) or h < px(100):
            return
        pad = px(12)
        lw = min(px(660), max(px(450), int(w * 0.54)))
        self.left.Location = D.Point(0, 0)
        self.left.Size = D.Size(lw, h)
        self.right.Location = D.Point(lw, 0)
        self.right.Size = D.Size(max(px(50), w - lw), h)

        iw = lw - 2 * pad
        y = px(8)
        self.banner.Location = D.Point(pad, y)
        # As high as its text: at a narrow window the sentence takes more lines
        need = self.F.TextRenderer.MeasureText(
            self.banner_text.Text or u" ", self.banner_text.Font,
            D.Size(iw - px(20), 0), self.F.TextFormatFlags.WordBreak).Height
        high = max(px(62), px(29) + need)
        self.banner.Size = D.Size(iw, high)
        self.banner_title.Width = iw - px(20)
        self.banner_text.Size = D.Size(iw - px(20), need + px(4))
        y += high + px(6)
        x = pad
        # a label as wide as its text, at least its slot: the field after it
        # never overlaps it ("Eenheid:")
        for ctrl, width in ((self.step_label, 36), (self.step_combo, 104),
                            (self.unit_label, 48), (self.unit_combo, 50)):
            ctrl.Location = D.Point(x, y)
            if ctrl in (self.step_combo, self.unit_combo):
                ctrl.Width = px(width)
                x += px(width + 4)
            else:
                x += self._fit_label(ctrl, width) + px(4)
        # the radios are as wide as their text, which names the axes of the cut;
        # on a row of their own when they do not fit next to step and unit
        group = [(self.axes_label, self._fit_label(self.axes_label, 40) + px(4)),
                 (self.radio_section, self.radio_section.PreferredSize.Width + px(8)),
                 (self.radio_global, self.radio_global.PreferredSize.Width + px(8))]
        if x + sum(w for _, w in group) > pad + iw:
            x = pad
            y += px(28)
        for ctrl, width in group:
            radio = ctrl is not self.axes_label
            ctrl.Location = D.Point(x, y + (px(3) if radio else 0))
            x += width
        y += px(28)
        note_h = self.F.TextRenderer.MeasureText(
            self.axes_note.Text or u" ", self.axes_note.Font, D.Size(iw, 0),
            self.F.TextFormatFlags.WordBreak).Height + px(2)
        self.axes_note.Location = D.Point(pad, y - px(2))
        self.axes_note.Size = D.Size(iw, note_h)
        y += note_h + px(2)
        if self.outdated:
            self.outdated_label.Location = D.Point(pad, y - px(2))
            self.outdated_label.Width = iw
            y += px(20)
        bottom = h - px(8)
        arrows_h = px(78)
        warn_h = max(px(46), min(px(96), int(h * 0.15)))
        sign_h = max(px(30), self.F.TextRenderer.MeasureText(
            self.sign_label.Text or u" ", self.sign_label.Font, D.Size(iw, 0),
            self.F.TextFormatFlags.WordBreak).Height + px(4))
        table_h = bottom - y - arrows_h - warn_h - sign_h - px(12)
        if table_h < px(96):
            # a small window: the warnings scroll, the table keeps a few rows
            give = max(0, min(warn_h - px(46), px(96) - table_h))
            warn_h -= give
            table_h += give
        self.table.Location = D.Point(pad, y)
        self.table.Size = D.Size(iw, max(px(60), table_h))
        self._fit_columns()
        y += self.table.Height + px(4)
        self.sign_label.Location = D.Point(pad, y)
        self.sign_label.Size = D.Size(iw, sign_h)
        y += sign_h + px(2)
        self.warning_box.Location = D.Point(pad, y)
        self.warning_box.Size = D.Size(iw, warn_h)
        y += warn_h + px(4)
        self.arrow_title.Location = D.Point(pad, y)
        self.arrow_combo.Location = D.Point(
            pad + self._fit_label(self.arrow_title, 116) + px(2), y)
        self.arrow_button.Location = D.Point(self.arrow_combo.Right + px(6), y - px(1))
        self.arrow_label.Location = D.Point(pad, y + px(28))
        self.arrow_label.Size = D.Size(iw, bottom - y - px(28))

        rw, rh = self.right.ClientSize.Width, self.right.ClientSize.Height
        strip = px(72)
        self.picture.Location = D.Point(0, 0)
        self.picture.Size = D.Size(rw, max(px(50), rh - strip))
        y = rh - strip + px(6)
        x = px(4)
        self.point_title.Location = D.Point(x, y)
        x += self._fit_label(self.point_title, 44) + px(2)
        for box in self.point_boxes:
            box.Location = D.Point(x, y)
            box.Width = px(70)
            x += px(74)
        self.point_hint.Location = D.Point(x + px(4), y)
        self.point_hint.Width = max(px(40), rw - x - px(8))
        y += px(32)
        self.neutral_button.Location = D.Point(px(50), y)
        self.node_box.Location = D.Point(px(170), y + px(1))
        self.node_button.Location = D.Point(px(246), y)
        self._draw()

    def _fit_columns(self):
        lv = self.table
        count = lv.Columns.Count
        if count < 2:
            return
        # Wide enough for what is in it: a number must never end in dots. If it
        # does not fit, the list scrolls sideways.
        width = lv.ClientSize.Width - 2
        measure = self.F.TextRenderer.MeasureText
        pad = self.px(14)
        font = lv.Font
        need = [measure(lv.Columns[i].Text, font).Width + pad for i in range(count)]
        for item in lv.Items:
            for i in range(min(count, item.SubItems.Count)):
                need[i] = max(need[i], measure(item.SubItems[i].Text, font).Width + pad)
        spare = max(0, width - sum(need)) // count
        for i in range(count):
            lv.Columns[i].Width = need[i] + spare

    # ---------------- tabs and documentation ----------------
    def _tab_border(self, font):
        """(width, height) a TabControl takes around its page: measured on a
        control of its own that no window holds, so the panel's window gets no
        handle yet. A guess if Windows does not answer."""
        D, F = self.D, self.F
        guess = (self.px(8), self.px(30))
        probe = F.TabControl()
        try:
            probe.Font = font
            probe.Size = D.Size(self.px(600), self.px(400))
            page = F.TabPage()
            page.Text = u"Probe"
            probe.TabPages.Add(page)
            inner = probe.DisplayRectangle
            dw = probe.ClientSize.Width - inner.Width
            dh = probe.ClientSize.Height - inner.Height
            if 0 <= dw <= self.px(60) and 0 <= dh <= self.px(80):
                return dw, dh
            log(u"tabs: border not measured ({0}, {1})".format(dw, dh))
        except Exception:
            log(u"tabs: border: {0}".format(traceback.format_exc()))
        finally:
            probe.Dispose()
        return guess

    def _on_body_size(self):
        if not self._filling:
            self._layout()

    def show_tab(self, name):
        """Open the tab "panel" or "docs" from code without taking the focus: the
        controls are built again with that tab chosen before they have handles.
        (SelectedIndex on a TabControl with a handle focuses the first control of
        the page, and that activates the window.) A click on a tab goes through
        _on_tab. Posted, as the language switch: a control that calls this from
        its own handler is not disposed inside it."""
        if name != self.tab:
            self.tab = name
            self.form.BeginInvoke(self.F.MethodInvoker(self._guard(self._rerender)))

    def _on_tab(self):
        if self._filling:
            return
        if self.tabs.SelectedIndex == 1:
            self.tab = "docs"
            self._build_docs()
        else:
            self.tab = "panel"
            self._layout()

    def _build_docs(self):
        """The documentation page: the list of documents, the browser element
        (or a text box without it) and the trademark notice. Once per render."""
        if self.doc_view is not None and not self.doc_view.IsDisposed:
            return
        D, F = self.D, self.F
        col = _colors()
        items = fb_docs.doc_list(self.lang)
        k = fb_docs.same_doc(self.doc_rel)
        if k is not None:
            self.doc_rel = items[k][1]      # the same document in this language
        lst = F.ListBox()
        lst.Dock = F.DockStyle.Left
        lst.Width = self.px(240)
        lst.BorderStyle = getattr(F.BorderStyle, "None")
        lst.BackColor = col["band"]
        lst.IntegralHeight = False
        lst.DrawMode = F.DrawMode.OwnerDrawFixed
        lst.ItemHeight = self.px(30)
        for title, _rel in items:
            lst.Items.Add(title)
        lst.DrawItem += self._draw_doc_item
        browser = None
        if self.use_browser:
            try:
                browser = F.WebBrowser()
                browser.ScriptErrorsSuppressed = True
                browser.AllowWebBrowserDrop = False
                browser.IsWebBrowserContextMenuEnabled = False
                # shortcuts stay on, for Ctrl+C, Ctrl+A and Ctrl+F; a new window
                # (Ctrl+N, shift-click) is refused in _on_doc_new_window
            except Exception:
                log(u"docs: no browser element: {0}".format(traceback.format_exc()))
                browser = None
        viewer = browser
        if viewer is None:
            # without a browser element: the text of the page
            viewer = F.TextBox()
            viewer.Multiline = True
            viewer.ReadOnly = True
            viewer.ScrollBars = F.ScrollBars.Vertical
            viewer.BorderStyle = getattr(F.BorderStyle, "None")
            viewer.BackColor = col["bg"]
            viewer.Font = D.Font("Segoe UI", 9.5)
        viewer.Dock = F.DockStyle.Fill
        gap = F.Panel()
        gap.Dock = F.DockStyle.Left
        gap.Width = self.px(8)
        gap.BackColor = col["bg"]
        notice = F.Label()
        notice.Text = fb_docs.TRADEMARK_NOTICE[0 if self.lang == "nl" else 1]
        notice.Font = D.Font("Segoe UI", 8.0)
        notice.ForeColor = col["muted"]
        notice.Dock = F.DockStyle.Bottom
        notice.Height = self.px(36)      # two lines: a narrow window wraps it
        notice.Padding = F.Padding(self.px(4), self.px(6), self.px(4), 0)
        page = self.page_docs
        page.SuspendLayout()
        # docked from the last added: the notice at the bottom, the list at
        # the left, the gap, then the viewer fills the rest
        for c in (viewer, gap, lst, notice):
            page.Controls.Add(c)
        page.ResumeLayout()
        self.doc_list, self.doc_browser, self.doc_view = lst, browser, viewer
        self.doc_notice = notice
        if browser is not None:
            browser.Navigating += self._on_doc_navigating
            browser.DocumentCompleted += self._on_doc_completed
            browser.NewWindow += self._on_doc_new_window
        lst.SelectedIndexChanged += self._guard(self._on_doc_chosen)
        self._show_doc(self.doc_rel)

    def _draw_doc_item(self, sender, e):
        try:
            if e.Index < 0:
                return
            D, F = self.D, self.F
            col = _colors()
            selected = (e.State & F.DrawItemState.Selected) == F.DrawItemState.Selected
            brush = D.SolidBrush(col["accent"] if selected else col["band"])
            try:
                e.Graphics.FillRectangle(brush, e.Bounds)
            finally:
                brush.Dispose()
            r = D.Rectangle(e.Bounds.X + self.px(10), e.Bounds.Y,
                            e.Bounds.Width - self.px(14), e.Bounds.Height)
            F.TextRenderer.DrawText(
                e.Graphics, u"{0}".format(self.doc_list.Items[e.Index]), self.form.Font, r,
                D.Color.White if selected else col["text"],
                F.TextFormatFlags.VerticalCenter | F.TextFormatFlags.Left |
                F.TextFormatFlags.EndEllipsis)
        except Exception:
            log(u"docs: draw: {0}".format(traceback.format_exc()))

    def _show_doc(self, rel, anchor=None):
        """Show the document rel (relative to docs/), at anchor if given; one in
        the list is selected there, one outside it leaves no selection."""
        self.doc_rel = rel
        self.doc_anchor = anchor
        rels = [r for _t, r in fb_docs.doc_list(self.lang)]
        self._doc_quiet = True
        try:
            self.doc_list.SelectedIndex = rels.index(rel) if rel in rels else -1
        finally:
            self._doc_quiet = False
        html = fb_docs.doc_html(rel, self.lang)
        if self.doc_browser is not None:
            self.doc_browser.DocumentText = html
        else:
            self.doc_view.Text = fb_docs.page_text(html)

    def _on_doc_chosen(self):
        if self._doc_quiet:
            return
        k = self.doc_list.SelectedIndex
        items = fb_docs.doc_list(self.lang)
        if 0 <= k < len(items):
            try:
                self._show_doc(items[k][1])
            except Exception as e:
                log(u"docs: {0}".format(traceback.format_exc()))
                self._set_status(fb_docs.tx("not_shown", self.lang).format(e), True)

    def _scroll_doc(self, anchor):
        try:
            el = self.doc_browser.Document.GetElementById(anchor)
            if el is not None:
                el.ScrollIntoView(True)
        except Exception:
            pass

    def doc_link(self, url):
        """A link clicked in a document (the address as the browser element has
        it). Documents open in this tab, anchors scroll, web addresses go to
        open_web; nothing else opens. False: let the browser element load it
        (only the page of DocumentText itself, about:blank)."""
        if url in (u"about:blank", u""):
            return False
        try:
            kind, target, anchor = fb_docs.resolve_link(self.doc_rel, fb_docs.href_from_url(url))
            if kind == "anchor":
                self._scroll_doc(anchor)
            elif kind == "doc":
                self._show_doc(target, anchor)
            elif kind == "web":
                self.open_web(target)
            else:
                self._set_status(fb_docs.tx("link_none", self.lang).format(
                    fb_docs.href_from_url(url)))
        except Exception as e:
            log(u"docs: link: {0}".format(traceback.format_exc()))
            self._set_status(fb_docs.tx("link_failed", self.lang).format(e), True)
        return True

    def _on_doc_navigating(self, sender, args):
        try:
            url = args.Url.OriginalString if args.Url is not None else u""
            if self.doc_link(u"{0}".format(url)):
                args.Cancel = True
        except Exception:
            args.Cancel = True
            log(u"docs: navigating: {0}".format(traceback.format_exc()))

    def _on_doc_completed(self, sender, args):
        anchor, self.doc_anchor = self.doc_anchor, None
        if anchor:
            self._scroll_doc(anchor)

    def _on_doc_new_window(self, sender, args):
        # never a window of Internet Explorer (shift-click, a target)
        args.Cancel = True

    # ---------------- contents ----------------
    def _fill_runs(self):
        """The run combo from the last scan."""
        cb = self.run_combo
        keep = self._filling
        self._filling = True
        try:
            cb.Items.Clear()
            runs = self.scan["runs"]
            for man in runs:
                cb.Items.Add(self.t("run_item").format(
                    man.get("run_id") or u"?", man.get("model") or u"?",
                    man.get("analysis") or man.get("solver") or u"?",
                    man.get("aster_version") or u"?"))
            ids = [man.get("run_id") for man in runs]
            if runs:
                cb.SelectedIndex = ids.index(self.run_id) if self.run_id in ids else 0
                self.run_id = ids[cb.SelectedIndex]
            else:
                self.run_id = None
        finally:
            self._filling = keep
        self._show_run()

    def chosen_run(self):
        for man in self.scan["runs"]:
            if man.get("run_id") == self.run_id:
                return man
        return None

    def run_problem(self, man):
        """The refusal code of a run, for the text and for Compute."""
        scan = self.scan
        bridge = scan.get("bridge") or {}
        if man is None:
            return "no_base"
        if "no_aster" in (bridge.get("problems") or []) or not bridge.get("exe"):
            return "no_aster"
        return fb_aster.refuse(man, scan.get("version"), scan.get("fingerprint"))

    def _show_run(self):
        col = _colors()
        lb = self.run_label
        man = self.chosen_run()
        scan = self.scan
        self.run_refusal = None
        if man is None:
            if scan.get("other"):
                text = self.t("run_other").format(scan["other"])
            elif scan.get("fingerprint") is None:
                text = u""
            else:
                text = self.t("run_none") + u"  " + self.t("looked").format(
                    u"; ".join(scan.get("folders") or [u"–"]))
            problems = (scan.get("bridge") or {}).get("problems") or []
            for code in problems:
                text = (text + u"  " + self.t("b_" + code)).strip()
            lb.Text = text
            lb.ForeColor = col["error" if text else "muted"]
            return
        code = self.run_problem(man)
        self.run_refusal = code
        if code:
            detail = not_shared_text(man.get("not_shared"))
            if code == "launcher_version":
                detail = (scan.get("bridge") or {}).get("exe") or u"?"
            lb.Text = reason_text(code, self.lang, detail, man.get("aster_version") or u"?")
            lb.ForeColor = col["error"]
        else:
            path = self.last.get("path")
            if foreign_run(man, path):
                lb.Text = self.t("run_foreign").format(man.get("model"),
                                                       fb_mecway.model_stem(path))
                lb.ForeColor = col["error"]
            else:
                lb.Text = self.t("run_used").format(man.get("run_id"), man.get("model"),
                                                    man.get("_folder"))
                lb.ForeColor = col["muted"]

    def _refresh(self):
        """All contents from the model."""
        model = self.model
        model.lang = self.lang
        self._filling, keep = True, self._filling
        try:
            self._fill_steps()
            self._fill_table()
            self._fill_point()
        finally:
            self._filling = keep
        self._show_equilibrium()
        lines = model.warning_lines()
        self.warning_box.Text = u"\r\n".join(lines) if lines else self.t("w_none")
        self.point_hint.Text = model.point_hint()
        self._show_axes_texts()
        self._draw()

    def _show_axes_texts(self):
        """Radio, note and sign: they follow the axes of the cut shown."""
        model = self.model
        before = (self.radio_section.Text, self.sign_label.Text, self.axes_note.Text)
        self.radio_section.Text = model.radio_text()
        self.axes_note.Text = model.axes_note()
        self.sign_label.Text = model.sign_text()
        self.point_hint.Text = model.point_hint()
        if (self.radio_section.Text, self.sign_label.Text, self.axes_note.Text) != before:
            self._layout()

    def _refresh_numbers(self):
        """After a change of point: the numbers only."""
        rows = self.model.rows()
        lv = self.table
        for i, row in enumerate(rows):
            if i < lv.Items.Count:
                for j, text in enumerate(row):
                    lv.Items[i].SubItems[j].Text = text
        self._fit_columns()
        self._draw()

    def _fill_steps(self):
        cb = self.step_combo
        cb.Items.Clear()
        model = self.model
        ranks = [s["rank"] for s in model.steps()]
        for s in model.steps():
            if s.get("time") is None:
                cb.Items.Add(u"{0}".format(s["rank"]))
            else:
                cb.Items.Add(self.t("step_item").format(s["rank"], fmt(s["time"], model.dec())))
        if model.rank in ranks:
            cb.SelectedIndex = ranks.index(model.rank)

    def _fill_table(self):
        F = self.F
        lv = self.table
        model = self.model
        lv.BeginUpdate()
        try:
            lv.Items.Clear()
            lv.Columns.Clear()
            heads = model.headers()
            for i, head in enumerate(heads):
                lv.Columns.Add(head, self.px(70),
                               F.HorizontalAlignment.Left if i == 0 or head == self.t("ax_head")
                               else F.HorizontalAlignment.Right)
            if model.cuts:
                for i, row in enumerate(model.rows()):
                    item = F.ListViewItem(row[0])
                    for text in row[1:]:
                        item.SubItems.Add(text)
                    lv.Items.Add(item)
                    item.Selected = (i == model.index)
        finally:
            lv.EndUpdate()
        self._fit_columns()

    def _fill_point(self):
        cut = self.model.cut()
        boxes = self.point_boxes
        if cut is None:
            for box in boxes:
                box.Text = u""
            return
        dec = self.model.dec()
        shown = self.model.point_shown(cut)
        for box, value in zip(boxes, shown):
            box.Text = (u"%.3f" % value).rstrip(u"0").rstrip(u".").replace(u".", dec) or u"0"

    def _show_equilibrium(self):
        col = _colors()
        state, title, text = self.model.equilibrium()
        self.banner.BackColor = col[state + "_bg"]
        self.banner_title.ForeColor = col[state + "_text"]
        self.banner_text.ForeColor = col[state + "_text"]
        self.banner_title.Text = title
        before = self.banner_text.Text
        self.banner_text.Text = text
        if text != before:
            self._layout()

    def _draw(self):
        pic = getattr(self, "picture", None)
        if pic is None or pic.IsDisposed:
            return
        w, h = pic.ClientSize.Width, pic.ClientSize.Height
        if w < 50 or h < 50:
            return
        self.view = self.model.view()
        hint = self.t("d_none")
        if self.view is not None:
            self.map = view_map(self.view, float(w), float(h), keep_point=not self.drag)
        else:
            self.map = None
        old = pic.Image
        pic.Image = draw_cut(self.view, self.map, w, h, hint)
        if old is not None:
            old.Dispose()

    def _update_buttons(self):
        busy = self.phase is not None
        ready = bool(self.model.cuts)
        for ctrl, on in ((self.compute_button, not busy),
                         (self.stop_button, busy),
                         (self.folder_combo, not busy),
                         (self.browse_button, not busy),
                         (self.run_combo, not busy),
                         (self.mode_combo, not busy),
                         (self.side_button, not busy and self.cut_mode == "nodes"),
                         (self.arrow_button, ready and not busy)):
            if not ctrl.IsDisposed:
                ctrl.Enabled = on
        if not self.progress.IsDisposed:
            self.progress.Visible = busy

    # ---------------- the steps of a computation ----------------
    def _on_shown(self):
        self.timer.Start()
        if not self.options.get("no_activate"):
            self.form.Activate()        # focus: the user just started the script
        self._start(False)
        ready = self.options.get("on_ready")
        if ready is not None:
            ready(self)

    def on_compute(self):
        if self.phase is None:
            self.auto = False
            self._start(True)

    def _start(self, compute):
        """Read selection and mesh on the script thread, then scan for runs."""
        self.want_compute = compute
        self.phase = "read"
        self.started = time.time()
        self._set_status(self.t("reading"))
        out = {}
        mw, solution = self.mw, self.solution

        mode = self.cut_mode
        out["mode"], out["side"] = mode, self.side

        def steps():
            out["path"] = fb_mecway.model_path(mw)
            out["selection"] = fb_mecway.read_selection(mw, solution)
            if compute and not chosen_ids(out["selection"], mode):
                return
            for _ in fb_mecway.read_mesh_steps(mw, out):
                yield
            out["missing"] = {}
            out["props"] = fb_mecway.read_props(mw, out["mesh"], out["missing"])
            # nodal moments for the drilling warning; without shells it has
            # nothing to judge
            if has_shells(out["mesh"]):
                read = {}
                for _ in fb_mecway.read_moments_steps(mw, out["mesh"], read):
                    yield
                if read.get("unread"):
                    out["missing"]["moments"] = read["unread"]
        ticket = self.caller.post_steps(steps())
        self.wait = (ticket, out, time.time() + READ_TIMEOUT)
        self._update_buttons()

    def _drop_worker(self):
        """Nobody waits for this worker any more; if it is starting a run, that
        run is stopped when it has."""
        worker, self.worker = self.worker, None
        if worker is not None and self.phase == "plan":
            worker.when_done(_stop_started_job)

    def _fail(self, code, detail=u""):
        job, self.job = self.job, None
        if job is not None:
            try:
                job.stop()
            except Exception:
                log(u"stop: {0}".format(traceback.format_exc()))
        if self.wait is not None:
            self.caller.cancel(self.wait[0])
            self.wait = None
        if code != "stopped" and (self.want_compute or self.phase in COMPUTING):
            self.failed_run = True
        self._drop_worker()
        self.phase = None
        self.want_compute = False
        self.pending_model = None
        self._set_status(reason_text(code, self.lang, detail, mode=self.cut_mode),
                         code != "stopped")
        self._update_buttons()
        self._show_outdated()

    def _fail_error(self, error, trace=None):
        if trace:
            log(u"failed: {0}".format(trace))
        if isinstance(error, fb_core.Refused):
            self._fail(error.code, u"{0}".format(error.detail))
        elif isinstance(error, fb_mecway.MeshChanged):
            self._fail("mesh_changed")
        else:
            self._fail("error", u"{0}".format(error))

    def _start_worker(self, phase, fn):
        self.phase = phase
        self.worker = _Worker(fn)
        self._update_buttons()

    def _on_tick(self, sender, args):
        try:
            self._tick()
        except Exception as e:
            log(u"tick: {0}".format(traceback.format_exc()))
            self._fail("error", u"{0}".format(e))

    def _tick(self):
        self.ticks += 1
        self._tick_asks()
        if self.phase is None:
            if self.ticks % SELECTION_TICKS == 0:
                self._ask_selection()
            return
        if self.phase == "read":
            self._tick_read()
        elif self.phase == "run":
            self._tick_run()
        elif self.phase == "check":
            self._tick_check()
        elif self.worker is not None and self.worker.done:
            worker, self.worker = self.worker, None
            if worker.error is not None:
                self._fail_error(worker.error, worker.trace)
            elif self.phase == "scan":
                self._after_scan(worker.value)
            elif self.phase == "plan":
                self._after_plan(worker.value)
            elif self.phase == "finish":
                self._after_finish(worker.value)

    def _tick_read(self):
        ticket, out, deadline = self.wait
        if not ticket["done"]:
            if time.time() > deadline:
                self.caller.cancel(ticket)
                self._fail("busy")
            return
        self.wait = None
        if ticket.get("error") is not None:
            error = ticket["error"]
            if isinstance(error, fb_mecway.MeshChanged):
                self._fail("mesh_changed")
            else:
                log(u"read: {0}".format(ticket.get("trace")))
                self._set_selection_text(None)
                self._fail("no_model", u"{0}".format(error))
            return
        self._set_selection_text(out.get("selection"))
        if self.want_compute and not chosen_ids(out["selection"], out["mode"]):
            self._fail("empty")
            return
        self.last = out
        self._set_status(self.t("scanning"))
        mesh, path = out["mesh"], out["path"]
        choice, other = self.folder_choice, self.folder_other
        self.subtitle.Text = path or self._sub_text()
        self._start_worker("scan", lambda: scan_runs(mesh, path, choice, other))

    def _after_scan(self, scan):
        self.scan = scan
        self._fill_runs()
        mode, side = self.last["mode"], self.last["side"]
        ids = chosen_ids(self.last["selection"], mode)
        go = self.want_compute or (self.auto and bool(ids))
        self.auto = False
        if not go:
            self.phase = None
            self._set_status(u"")
            self._update_buttons()
            return
        man = self.chosen_run()
        foreign = man is not None and foreign_run(man, self.last.get("path"))
        if self.run_problem(man) or (foreign and not self.want_compute):
            self.phase = None
            self._set_status(self.run_label.Text if self.want_compute else u"",
                             self.want_compute)
            self.want_compute = False
            self._update_buttons()
            return
        mesh = self.last["mesh"]
        props = self.last["props"][0]
        exe = self.scan["bridge"]["exe"]
        folder = man["_folder"]
        self._set_status(self.t("planning"))

        def work():
            return plan_and_start(mesh, ids, mode, side, props, man, folder, exe)
        self.plan_state = {"mesh": mesh, "props": props, "man": man, "folder": folder,
                           "missing": self.last.get("missing") or {}}
        self._start_worker("plan", work)

    def _after_plan(self, value):
        plan, geos, job, cut = value
        self.plan_state.update({"plan": plan, "geos": geos, "cut": cut})
        self.job = job
        self.phase = "run"
        self.started = time.time()
        self._set_status(self.t("running").format(0))
        self._update_buttons()

    def _tick_run(self):
        job = self.job
        state = job.poll()
        if state is None:
            self._set_status(self.t("running").format(int(time.time() - self.started)))
            return
        self.job = None
        if state is False:
            text = job.error() or u""
            code = job.code() if hasattr(job, "code") else "run"
            self._fail(code, u"{0}".format(text))
            return
        self._set_status(self.t("finishing"))
        st = self.plan_state
        unit, axes, lang = self.model.unit, self.model.axes, self.lang

        def work():
            result = job.result()
            per_group = fb_core.assign_nodes(st["plan"], st["mesh"], result)
            model = PanelModel()
            model.unit, model.axes, model.lang = unit, axes, lang
            model.load(st["mesh"], st["plan"], st["geos"], result, per_group,
                       st["man"], st["folder"], st["props"], nodecut=st.get("cut"))
            model.note_missing(st.get("missing"))
            # the first step shown: frames and sums ready before the swap
            model.rows()
            return model
        self._start_worker("finish", work)

    def _after_finish(self, model):
        """The numbers are ready; first the question whether this run is the
        solution that is open in Mecway."""
        self.pending_model = model
        self.phase = "check"
        self._set_status(self.t("checking"))
        solution = self.solution
        nids = list(model.plan["cut_nodes"])
        out = {}
        steps = (model.result or {}).get("steps") or []
        last = steps[-1].get("time") if steps else None
        ticket = self.caller.post_steps(fb_mecway.solution_disp_steps(solution, nids, out,
                                                                      time=last))
        self.wait = (ticket, out, time.time() + ASK_TIMEOUT)

    def _tick_check(self):
        ticket, out, deadline = self.wait
        late = time.time() > deadline
        if not ticket["done"] and not late:
            return
        if late:
            self.caller.cancel(ticket)
        self.wait = None
        model, self.pending_model = self.pending_model, None
        state = "unknown"
        if ticket["done"] and ticket.get("error") is None:
            state = solution_state(model.result, out.get("values"))
        if state == "stale":
            self._fail("stale")
            return
        if state is not None:
            model.warnings.append(("code", "solution_unknown", None))
        if foreign_run(model.man, self.last.get("path")):
            model.warnings.append(("code", "other_model", model.man.get("model")))
        self._install(model)

    def _install(self, model):
        model.unit, model.axes, model.lang = self.model.unit, self.model.axes, self.lang
        self.model = model
        self.phase = None
        self.failed_run = False
        self.arrow_state = None
        self._show_arrows()
        seconds = model.result.get("seconds") or 0.0
        self._set_status(self.t("done").format(len(model.cuts), u"%.1f" % seconds))
        self.status_done = (len(model.cuts), u"%.1f" % seconds)
        basis = model.basis()
        self.selected_now = (basis[0], basis[2]) if basis else None
        self._refresh()
        self._update_buttons()
        self._show_outdated()

    def on_stop(self):
        if self.phase is None:
            return
        self._fail("stopped")

    # ---------------- questions to Mecway ----------------
    def _ask(self, fn, done, steps=False, timeout=ASK_TIMEOUT):
        """Run fn on the script thread; done(result, error) in the timer."""
        ticket = self.caller.post_steps(fn) if steps else self.caller.post(fn)
        self.asks.append((ticket, done, time.time() + timeout))

    def _tick_asks(self):
        for entry in list(self.asks):
            ticket, done, deadline = entry
            if ticket["done"]:
                self.asks.remove(entry)
                done(ticket.get("result"), ticket.get("error"))
            elif time.time() > deadline:
                self.asks.remove(entry)
                self.caller.cancel(ticket)
                done(None, "busy")

    def _set_selection_text(self, selection, new=True):
        self.selection_seen = selection
        nodes = (selection.get("node_ids") or []) if selection is not None else []
        if selection is None:
            text = self.t("sel_nomodel")
        elif self.cut_mode == "nodes":
            sign = side_sign(self.side)
            text = (self.t("sel_nodes_n").format(len(nodes), sign) if nodes
                    else self.t("sel_nodes_none").format(sign))
        elif selection["elements"]:
            text = self.t("sel_n").format(len(selection["elements"]))
        elif selection.get("faces"):
            text = self.t("sel_faces")
        else:
            text = self.t("sel_none")
        self.selection_text = text
        lb = getattr(self, "selection_label", None)
        if lb is not None and not lb.IsDisposed and lb.Text != text:
            lb.Text = text
        if selection is not None and new:
            self.selected_now = selection_key(selection, self.cut_mode)
            self._show_outdated()

    def _show_outdated(self):
        """A table of another selection (or of the other way to cut), or left
        over from a failed run, stays in view but grey, with a line that says
        so."""
        now, basis = self.selected_now, self.model.basis()
        differs = basis is not None and (
            basis[0] != self.cut_mode or
            (basis[0] == "nodes" and basis[1] != self.side) or
            (now is not None and (now[0] != basis[0] or selection_differs(now[1], basis[2]))))
        outdated = bool(self.model.cuts) and (differs or self.failed_run)
        if outdated == self.outdated:
            return
        self.outdated = outdated
        col = _colors()
        self.table.ForeColor = col["grey" if outdated else "text"]
        self.outdated_label.Visible = outdated
        self._layout()

    def _ask_selection(self):
        """One question at a time: no queue builds up behind a dialog."""
        if self.selection_busy:
            return
        self.selection_busy = True
        mw, solution = self.mw, self.solution

        def done(result, error):
            self.selection_busy = False
            if error != "busy":
                self._set_selection_text(None if error else result)
        self._ask(lambda: fb_mecway.read_selection(mw, solution), done)

    # ---------------- events ----------------
    def _lang_handler(self, code):
        def change():
            if code != self.lang:
                self.lang = code
                self.status = u""
                save_setting("language", code)
                self.form.BeginInvoke(self.F.MethodInvoker(self._guard(self._rerender)))
        return change

    def _rerender(self):
        self.render()

    def _sub_text(self):
        return self.t("sub_nodes" if self.cut_mode == "nodes" else "sub")

    def _on_mode(self):
        """Elements or nodes on a plane. Nothing is computed by itself; a table
        of the other way stays, grey."""
        if self._filling or self.phase is not None:
            return
        i = self.mode_combo.SelectedIndex
        if not 0 <= i < len(CUT_MODES) or CUT_MODES[i] == self.cut_mode:
            return
        self.cut_mode = CUT_MODES[i]
        save_setting("cut_mode", self.cut_mode)
        if not self.last.get("path"):
            self.subtitle.Text = self._sub_text()
        self._set_selection_text(self.selection_seen)
        self._show_outdated()
        self._update_buttons()

    def on_side(self):
        """The free body at the other side of the plane, computed at once."""
        if self.phase is not None or self.cut_mode != "nodes":
            return
        self.side = -self.side
        self._set_selection_text(self.selection_seen, False)
        # the table of the other side is grey until this side is computed
        self._show_outdated()
        self.on_compute()

    def _on_folder(self):
        if self._filling or self.phase is not None:
            return
        choice = FOLDER_CHOICES[self.folder_combo.SelectedIndex][0]
        self.folder_choice = choice
        save_setting("folder", choice)
        if choice == "other" and not self.folder_other:
            self.on_browse()
        else:
            self._start(False)

    def on_browse(self):
        if self.phase is not None:
            return
        F = self.F
        dlg = F.FolderBrowserDialog()
        dlg.Description = self.t("browse_title")
        if self.folder_other:
            dlg.SelectedPath = self.folder_other
        if dlg.ShowDialog(self.form) != F.DialogResult.OK:    # focus: the user clicked
            return
        self.folder_other = dlg.SelectedPath
        save_setting("folder_other", self.folder_other)
        self.folder_choice = "other"
        save_setting("folder", "other")
        self._filling, keep = True, self._filling
        self.folder_combo.SelectedIndex = len(FOLDER_CHOICES) - 1
        self._filling = keep
        self._start(False)

    def _on_run(self):
        if self._filling:
            return
        i = self.run_combo.SelectedIndex
        if 0 <= i < len(self.scan["runs"]):
            self.run_id = self.scan["runs"][i].get("run_id")
            self._show_run()

    def _on_step(self):
        if self._filling:
            return
        i = self.step_combo.SelectedIndex
        steps = self.model.steps()
        if 0 <= i < len(steps):
            self.model.rank = steps[i]["rank"]
            self._after_change()

    def _on_axes(self):
        if self._filling:
            return
        axes = "section" if self.radio_section.Checked else "global"
        if axes != self.model.axes:
            self.model.axes = axes
            save_setting("axes", axes)
            self._after_change()

    def _on_unit(self):
        if self._filling:
            return
        self.model.unit = UNITS[self.unit_combo.SelectedIndex][0]
        save_setting("unit", self.model.unit)
        self._after_change()

    def _after_change(self):
        self._refresh()

    def _on_table(self):
        if self._filling:
            return
        for i in range(self.table.Items.Count):
            if self.table.Items[i].Selected and i != self.model.index:
                self.model.index = i
                self._filling = True
                try:
                    self._fill_point()
                finally:
                    self._filling = False
                self._show_axes_texts()
                self._draw()
                return

    def _on_point_typed(self):
        if self._filling or self.model.cut() is None:
            return
        try:
            numbers = [parse_number(box.Text) for box in self.point_boxes]
        except ValueError:
            self._set_status(self.t("num_bad"), True)
            return
        self._set_status(u"")
        self.model.set_point_shown(numbers)
        self._refresh_numbers()

    def _point_moved(self):
        """After a preset or a drag: boxes, numbers, drawing."""
        self._filling = True
        try:
            self._fill_point()
        finally:
            self._filling = False
        self._refresh_numbers()

    def on_neutral(self):
        if self.model.cut() is not None:
            self.model.set_neutral()
            self._point_moved()

    def on_node(self):
        model = self.model
        if model.cut() is None:
            return
        text = self.node_box.Text.strip()
        if text:
            try:
                self._use_node(int(text))
            except ValueError:
                self._set_status(self.t("num_bad"), True)
            return
        mw = self.mw

        def done(result, error):
            nid = result[0] if result and not error else model.nearest_cut_node()
            self._use_node(nid)
        self._ask(lambda: fb_mecway.selected_nodes(mw), done)

    def _use_node(self, nid):
        if nid not in self.model.mesh["nodes"]:
            self._set_status(self.t("node_bad").format(nid), True)
            return
        self.model.set_node(nid)
        self._set_status(self.t("node_set").format(nid))
        self._point_moved()

    def _on_arrow_mode(self):
        if self._filling:
            return
        self.arrow_mode = "resultant" if self.arrow_combo.SelectedIndex else "nodes"
        save_setting("arrow_mode", self.arrow_mode)

    def on_mouse_down(self, x, y):
        if self.view is not None and self.map is not None and \
                near_point(self.map, self.view, x, y):
            self.drag = True

    def on_mouse_move(self, x, y):
        if not self.drag:
            over = (self.view is not None and self.map is not None and
                    near_point(self.map, self.view, x, y))
            self.picture.Cursor = self.F.Cursors.Hand if over else self.F.Cursors.Default
            return
        now = time.time()
        if now - self.drag_time < 0.03:
            return
        self.drag_time = now
        self._drag_to(x, y)

    def _drag_to(self, x, y):
        pic = self.picture
        x = min(max(x, 4), pic.ClientSize.Width - 4)
        y = min(max(y, 4), pic.ClientSize.Height - 4)
        u, v = from_pixel(self.map, x, y)
        self.model.set_point_plane(u, v)
        self._point_moved()

    def on_mouse_up(self, x, y):
        if self.drag:
            self._drag_to(x, y)
            self.drag = False
            self._draw()

    # ---------------- arrows ----------------
    def on_arrows(self):
        model = self.model
        if not model.cuts or self.phase is not None:
            return
        cuts = model.arrow_cuts()
        places, lumped = [], 0
        if self.arrow_mode == "resultant":
            values, places = fb_mecway.resultant_values(model.mesh, cuts)
        else:
            values, lumped = fb_mecway.per_node_values(model.mesh, cuts)
        rank = model.rank
        mw, solution, own = self.mw, self.solution, self.own
        out = {}
        gen = fb_mecway.arrow_steps(mw, solution, values, own, out,
                                    time=model.step_time())

        def done(result, error):
            if error == "busy":
                self._set_status(self.t("r_busy"), True)
                return
            self.arrow_state = (out, error, places, lumped, rank)
            self._show_arrows()
        self._ask(gen, done, steps=True, timeout=READ_TIMEOUT)

    def _arrow_lines(self, places, lumped, rank):
        """Where the arrows stand, in the language of the moment."""
        return arrow_lines(places, lumped, rank, self.lang, self.model.dec())

    def _show_arrows(self):
        """The outcome of the last write of arrows; scroll bar only with text."""
        F = self.F
        text = u""
        if self.arrow_state is not None:
            out, error, places, lumped, rank = self.arrow_state
            if error is not None:
                text = self.t("r_error").format(error)
            else:
                text = u"\r\n".join(arrow_report(
                    out, self._arrow_lines(places, lumped, rank), self.lang,
                    self.model.unit_row(), self.model.dec()))
        self.arrow_text = text
        self.arrow_label.ScrollBars = (F.ScrollBars.Vertical if text
                                       else getattr(F.ScrollBars, "None"))
        self.arrow_label.Text = text

    # ---------------- copy and save ----------------
    def table_text(self):
        decimal = separators(self.lang)[0]
        return fb_core.table_text(self.model.copy_rows(), decimal)

    def _clip_text(self, text):
        """The clipboard; tests replace this, so they never touch the user's."""
        self.F.Clipboard.SetText(text)

    def _clip_image(self, image):
        self.F.Clipboard.SetImage(image)

    def on_copy(self):
        if not self.model.cuts:
            return
        try:
            self._clip_text(self.table_text())
            self._set_status(self.t("copied"))
        except Exception as e:
            self._set_status(self.t("copy_fail").format(e), True)

    def on_copy_image(self):
        if self.view is None:
            return
        pic = self.picture
        w = max(900, 2 * pic.ClientSize.Width)
        h = max(900, 2 * pic.ClientSize.Height)
        try:
            m = view_map(self.view, w / 2.0, h / 2.0)
            self._clip_image(draw_cut(self.view, m, w, h, u"", 2.0))
            self._set_status(self.t("copied_img"))
        except Exception as e:
            self._set_status(self.t("copy_fail").format(e), True)

    def on_csv(self):
        if not self.model.cuts:
            return
        F = self.F
        dlg = F.SaveFileDialog()
        dlg.Title = self.t("csv_title")
        dlg.Filter = self.t("csv_filter")
        dlg.DefaultExt = "csv"
        dlg.RestoreDirectory = True
        dlg.FileName = u"{0}_cuts.csv".format(
            fb_mecway.model_stem(self.last.get("path") or u"model"))
        if dlg.ShowDialog(self.form) != F.DialogResult.OK:    # focus: the user clicked
            return
        self.save_csv(dlg.FileName)

    def save_csv(self, path):
        decimal, separator = separators(self.lang)
        if separator == decimal:
            separator = u";"
        text = csv_text(self.model.copy_rows(), decimal, separator)
        with io.open(path, "w", encoding="utf-8-sig", newline=u"") as f:
            f.write(u"{0}".format(text))
        self._set_status(self.t("saved").format(path))

    # ---------------- closing ----------------
    def _on_closing(self, sender, args):
        self.close_reason = u"{0}".format(args.CloseReason)
        log(u"closing: {0}".format(self.close_reason))
        try:
            self.timer.Stop()
            self.caller.cancel_all()
            if self.job is not None:
                self.job.stop()
            self._drop_worker()
        except Exception:
            log(u"closing: {0}".format(traceback.format_exc()))


def scan_runs(mesh, path, choice, other):
    """Worker: fingerprint and the runs that fit, newest first."""
    fingerprint = fb_aster.mesh_fingerprint(mesh["nodes"], list(mesh["elements"]))
    bridge = fb_mecway.find_bridge(SCRIPTS_DIR, path, settings())
    folders = fb_mecway.run_folders(path, bridge, choice, other)
    runs = []
    for folder in folders:
        runs += fb_aster.find_runs(folder, fingerprint)
    runs.sort(key=lambda m: str(m.get("run_id") or ""), reverse=True)
    runs.sort(key=lambda m: foreign_run(m, path))       # stable: own model first
    foreign = 0
    if not runs:
        for folder in folders:
            foreign += len(fb_aster.find_runs(folder, None))
    return {"runs": runs, "folders": folders, "other": foreign, "bridge": bridge,
            "fingerprint": fingerprint,
            "version": fb_aster.version_from_launcher(bridge.get("exe"))}


def arrow_lines(places, lumped, rank, lang, dec):
    """Where the arrows stand: per resultant its node (and whether it lies
    inside the solid), added midside nodes, the step."""
    lines = []
    for place in places:
        if place["distance"] < 1e-7:
            lines.append(tx("a_same", lang).format(place["cut"], place["node"]))
        else:
            lines.append(tx("a_place", lang).format(
                place["cut"], place["node"], fmt(place["distance"] * 1e3, dec, 4)))
        if place.get("inside"):
            lines.append(tx("a_inside", lang).format(place["cut"], place["node"]))
    if lumped:
        lines.append(tx("a_lumped", lang).format(lumped))
    lines.append(tx("a_step", lang).format(rank))
    return lines


def arrow_report(out, lines, lang, unit_row, dec):
    """What happened with the arrows, in sentences."""
    if out.get("refused"):
        return [tx("a_" + out["refused"], lang)]
    report = []
    names = {"force": u"external force", "moment": u"reaction moment"}
    largest = out.get("largest") or {}
    for name in out.get("written", []):
        value = largest.get(name, 0.0)
        unit = unit_row[2] if name == "force" else unit_row[3]

        def amount(v):
            return u"{0} {1}".format(fmt(v * unit_row[1], dec), unit)
        size = (out.get("sizes") or {}).get(name, value)
        if abs(size - value) <= 1e-9 * max(abs(size), abs(value)):
            report.append(tx("a_scale", lang).format(names[name], amount(value)))
        else:
            report.append(tx("a_rescaled", lang).format(names[name], amount(value),
                                                        amount(size)))
    for name in out.get("cleared", []):
        report.append(tx("a_cleared", lang).format(names[name]))
    for name, why in out.get("skipped", []):
        key = {"exists": "a_exists", "clear_failed": "a_clear_failed"}.get(why, "a_zero")
        report.append(tx(key, lang).format(names[name]))
    if out.get("written"):
        report.extend(lines)
        report.append(tx("a_hint", lang))
    return report


# ==========================================
# THE DRAWING (System.Drawing)
# ==========================================
def draw_cut(view, m, w, h, hint=u"", k=1.0):
    """Bitmap w x h of a cut. Outline, cut nodes, axes through the neutral
    point, the chosen point, and arrows with numbers there. Seen from outside
    the selection, so the normal points at the viewer. m: view_map for w/k x
    h/k; k > 1 draws larger for the clipboard."""
    D, F = _forms()
    from System import Array
    from System.Drawing.Drawing2D import (AdjustableArrowCap, DashStyle, FillMode,
                                          GraphicsPath, SmoothingMode)
    from System.Drawing.Text import TextRenderingHint
    col = _colors()
    bmp = D.Bitmap(int(w), int(h))
    g = D.Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.TextRenderingHint = TextRenderingHint.AntiAlias
    g.Clear(col["bg"])
    if k != 1.0:
        g.ScaleTransform(float(k), float(k))
        w, h = w / float(k), h / float(k)
    font = D.Font("Segoe UI", 8.5)
    bold = D.Font("Segoe UI", 9.0, D.FontStyle.Bold)
    if view is None:
        size = g.MeasureString(hint, font)
        g.DrawString(hint, font, D.SolidBrush(col["muted"]),
                     float((w - size.Width) / 2), float(h / 2))
        g.Dispose()
        return bmp

    def P(u, v):
        x, y = to_pixel(m, u, v)
        return D.PointF(float(x), float(y))
    g.DrawString(view["title"], bold, D.SolidBrush(col["text"]), 8.0, 6.0)
    # section
    loops = [lp for lp in view["loops"] if len(lp) >= 3]
    if loops:
        path = GraphicsPath(FillMode.Alternate)
        for lp in loops:
            path.AddPolygon(Array[D.PointF]([P(u, v) for u, v in lp]))
        g.FillPath(D.SolidBrush(col["fill"]), path)
        g.DrawPath(D.Pen(col["edge"], 1.3), path)
    # strips one by one: where they meet (an I of shells) they must not cancel
    for strip in view.get("strips") or []:
        path = GraphicsPath(FillMode.Alternate)
        path.AddPolygon(Array[D.PointF]([P(u, v) for u, v in strip]))
        g.FillPath(D.SolidBrush(col["fill"]), path)
        g.DrawPath(D.Pen(col["edge"], 1.3), path)
    # beams: the outline, a hollow one with its hole; else a circle of area A
    for beam in view.get("beams") or []:
        shapes = [lp for lp in beam["loops"] if len(lp) >= 3]
        if shapes:
            path = GraphicsPath(FillMode.Alternate)
            for lp in shapes:
                path.AddPolygon(Array[D.PointF]([P(u, v) for u, v in lp]))
            g.FillPath(D.SolidBrush(col["fill"]), path)
            edge = D.Pen(col["edge"], 1.3)
            if beam.get("label"):
                edge.DashStyle = DashStyle.Dash
            g.DrawPath(edge, path)
        if beam.get("label"):
            # above the left of the circle: off the axis names in the middle
            q = P(beam["at"][0], beam["at"][1])
            corners = [P(u, v) for lp in shapes for u, v in lp] or [q]
            left = min(p.X for p in corners)
            top = min(p.Y for p in corners)
            g.DrawString(beam["label"], font, D.SolidBrush(col["muted"]),
                         float(max(4.0, left)), float(max(24.0, top - 18.0)))
    dot = D.SolidBrush(col["edge"])
    if len(view["points"]) <= 3000:
        for u, v in view["points"]:
            q = P(u, v)
            g.FillEllipse(dot, q.X - 1.5, q.Y - 1.5, 3.0, 3.0)
    # axes through the neutral point
    c = P(0.0, 0.0)
    pen = D.Pen(col["grey"], 1.0)
    pen.DashStyle = DashStyle.Dash
    reach = min(w, h) * 0.34
    g.DrawLine(pen, c.X - reach, c.Y, c.X + reach, c.Y)
    g.DrawLine(pen, c.X, c.Y + reach, c.X, c.Y - reach)
    grey = D.SolidBrush(col["grey"])
    g.DrawString(view["axis_names"][0], bold, grey, float(c.X + reach + 2), float(c.Y - 10))
    g.DrawString(view["axis_names"][1], bold, grey, float(c.X + 2), float(c.Y - reach - 18))
    g.FillEllipse(D.Brushes.White, c.X - 5, c.Y - 5, 10.0, 10.0)
    g.DrawEllipse(D.Pen(D.Color.Black, 1.2), c.X - 5, c.Y - 5, 10.0, 10.0)
    p = P(view["point"][0], view["point"][1])
    if abs(p.X - c.X) + abs(p.Y - c.Y) > 2:
        link = D.Pen(col["point"], 1.0)
        link.DashStyle = DashStyle.Dot
        g.DrawLine(link, c, p)

    length = max(46.0, min(110.0, min(w, h) * 0.20))
    boxes = []
    labels = []       # drawn last, on a light ground: nothing runs through a number
    mark = view.get("plane")
    if mark:
        # The normal of the plane along the line of sight: a dot toward the
        # viewer, a cross into the picture; the line keeps numbers off it
        x, y, r = 16.0, 26.0 + PLANE_LINE / 2.0, 6.0
        pn = D.Pen(col["edge"], 1.4)
        g.FillEllipse(D.Brushes.White, x - r, y - r, 2 * r, 2 * r)
        g.DrawEllipse(pn, x - r, y - r, 2 * r, 2 * r)
        if mark["toward"]:
            g.FillEllipse(D.SolidBrush(col["edge"]), x - 2.0, y - 2.0, 4.0, 4.0)
        else:
            g.DrawLine(pn, x - 3.5, y - 3.5, x + 3.5, y + 3.5)
            g.DrawLine(pn, x - 3.5, y + 3.5, x + 3.5, y - 3.5)
        size = g.MeasureString(mark["text"], font)
        g.DrawString(mark["text"], font, D.SolidBrush(col["text"]), float(x + r + 4.0),
                     float(y - size.Height / 2.0))
        boxes.append((4.0, 26.0, x + r + 8.0 + size.Width, PLANE_LINE))

    def label(text, x, y, brush):
        """A number near (x, y), inside the picture and off other numbers."""
        size = g.MeasureString(text, bold)
        size = D.SizeF(size.Width + 4.0, size.Height)
        lx = min(max(4.0, x), w - size.Width - 4.0)
        ly = min(max(26.0, y), h - 48.0)
        for _ in range(12):
            hit = False
            for bx, by, bw, bh in boxes:
                if lx < bx + bw and bx < lx + size.Width and \
                        ly < by + bh and by < ly + size.Height:
                    hit = True
                    ly = by + bh + 1.0
                    break
            if not hit:
                break
        if ly + size.Height > h - 46.0:
            ly = max(26.0, h - 46.0 - size.Height)
        boxes.append((lx, ly, size.Width, size.Height))
        labels.append((text, brush, lx, ly, size))

    def straight(item, top, shift):
        sign = 1.0 if item["value"] > 0 else -1.0
        da, db, dn = [sign * v for v in item["dir"]]
        plane = math.sqrt(da * da + db * db)
        color = col["force"] if item["kind"] == "F" else col["moment"]
        share = 0.4 + 0.6 * abs(item["value"]) / top
        size = length * share * plane * (1.0 if item["kind"] == "F" else 0.85)
        ex, ey = da / plane, -db / plane
        ox, oy = p.X - ey * shift, p.Y + ex * shift
        tip = D.PointF(float(ox + ex * size), float(oy + ey * size))
        pn = D.Pen(color, 2.0)
        pn.CustomEndCap = AdjustableArrowCap(4.0, 5.0)
        if item["kind"] == "M":
            back = D.PointF(float(tip.X - ex * 7.0), float(tip.Y - ey * 7.0))
            g.DrawLine(pn, D.PointF(ox, oy), back)
            g.DrawLine(pn, back, tip)
        else:
            g.DrawLine(pn, D.PointF(ox, oy), tip)
        lx = tip.X + ex * 6.0
        if ex < -0.3:
            lx -= g.MeasureString(item["text"], bold).Width
        ly = tip.Y + ey * 6.0 - 8.0
        label(item["text"], lx, ly, D.SolidBrush(color))

    def through(item, slot):
        """A force along the normal: a dot comes out of the picture, a cross
        goes in."""
        toward = item["dir"][2] * item["value"] > 0
        color = col["force"]
        x, y = p.X + 16.0 + slot * 4.0, p.Y + 16.0
        pn = D.Pen(color, 2.0)
        g.FillEllipse(D.Brushes.White, x - 8, y - 8, 16.0, 16.0)
        g.DrawEllipse(pn, x - 8, y - 8, 16.0, 16.0)
        if toward:
            g.FillEllipse(D.SolidBrush(color), x - 2.5, y - 2.5, 5.0, 5.0)
        else:
            g.DrawLine(pn, x - 5, y - 5, x + 5, y + 5)
            g.DrawLine(pn, x - 5, y + 5, x + 5, y - 5)
        label(item["text"], x + 12.0, y - 8.0, D.SolidBrush(color))

    def turning(item):
        """A moment along the normal: an arc, counter-clockwise when it points
        at the viewer."""
        toward = item["dir"][2] * item["value"] > 0
        color = col["moment"]
        pn = D.Pen(color, 2.0)
        pn.CustomEndCap = AdjustableArrowCap(4.0, 5.0)
        r = 30.0
        sweep = -270.0 if toward else 270.0
        start = 45.0 if toward else 135.0
        g.DrawArc(pn, float(p.X - r), float(p.Y - r), float(2 * r), float(2 * r),
                  float(start), float(sweep))
        label(item["text"], p.X - 30.0, p.Y - r - 20.0, D.SolidBrush(color))

    forces = [a for a in view["arrows"] if a["kind"] == "F" and a["value"] != 0]
    moments = [a for a in view["arrows"] if a["kind"] == "M" and a["value"] != 0]
    top_f = max([abs(a["value"]) for a in forces] or [1.0])
    top_m = max([abs(a["value"]) for a in moments] or [1.0])
    for item in moments:
        if math.sqrt(item["dir"][0] ** 2 + item["dir"][1] ** 2) < 0.2:
            turning(item)
        else:
            straight(item, top_m, 9.0)
    for i, item in enumerate(forces):
        if math.sqrt(item["dir"][0] ** 2 + item["dir"][1] ** 2) < 0.2:
            through(item, i)
        else:
            straight(item, top_f, 0.0)
    g.FillEllipse(D.SolidBrush(col["point"]), p.X - 6, p.Y - 6, 12.0, 12.0)
    g.DrawEllipse(D.Pen(D.Color.Black, 1.2), p.X - 6, p.Y - 6, 12.0, 12.0)
    g.DrawString(view["about"], font, D.SolidBrush(col["text"]), 8.0, float(h - 40))
    g.DrawString(view["real"], font, D.SolidBrush(col["muted"]), 8.0, float(h - 22))
    ground = D.SolidBrush(D.Color.FromArgb(225, 255, 255, 255))
    for text, brush, lx, ly, size in labels:
        g.FillRectangle(ground, float(lx - 1.0), float(ly), float(size.Width), float(size.Height))
        g.DrawString(text, bold, brush, float(lx + 1.0), float(ly))
    g.Dispose()
    return bmp
