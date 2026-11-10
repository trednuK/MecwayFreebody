# MecwayFreebody

Force and moment resultants on the cuts of a selection in [Mecway](https://mecway.com), from a Code-Aster run made with
[MecwayAsterBridge](https://github.com/trednuK/MecwayAsterBridge).

Select part of a structure. MecwayFreebody finds where it is cut from the rest and shows N, Vy, Vz, T, My and Mz on each cut, about the
neutral point or a point you drag on a drawing of the section. The forces are Code-Aster's own nodal forces, so they satisfy equilibrium:
integrating stress over a cut can be tens of percent off on a coarse mesh.

Version V2026.1 (see [CHANGELOG](CHANGELOG.md)). Solids, shells, beams and mixed cuts, and cut by nodes on a plane (the plane runs
through solids; shells and beams elsewhere in the free body count); linear and nonlinear static. Mecway's own solver is not supported.

## Requirements

- Mecway 35 (Windows).
- MecwayAsterBridge V2026.9 or newer, with the setting *Keep the Code-Aster base* on (`keep_base`). V2026.9 brings `keep_base` and
  manifest schema 2, which shells and beams need. V2026.8 and older have no `keep_base`, so MecwayFreebody finds no run.
- Code-Aster 17.4, with its launcher at `...\<version>\bin\run_aster.bat` (the folder of the Windows package): the version is read
  from that path.

## Installation

In Mecway: *Tools* > *Scripts...* > *New*, and choose `Scripts\MecwayFreebody.py`. It then appears in the *Tools* menu.

Keep the folder `docs` next to `Scripts`, as in this repository: the panel's tab *Documentation* reads the user guide and this
README from there. Without it the tab says which document it did not find; the panel itself works without it.

## Use

1. Turn on *Keep the Code-Aster base* on the start screen of the bridge and run the analysis, which must be linear or nonlinear static.
   The base is 125-450 MB per run; the newest three per model stay.
2. Select elements with Mecway's solution of that run open, or the nodes of a planar section with *Cut by* set to *Nodes on a plane*.
3. *Tools* > *MecwayFreebody*, then **Compute**. A short follow-up run of a few seconds starts in the background.
4. Choose the cut, the step and the axes. Drag or type the point. Copy the table or save it as CSV.

Sign: the force of the rest on the selection, N positive in tension. *In equilibrium* means nothing else acts on the selection besides the
cuts and its loads, as far as the follow-up run can see. If it says otherwise, read which place it points to: a support, a tie or bonded
contact on the selection.

The panel can also put arrows in Mecway's own solution view, as the fields *external force* and *reaction moment*. They sit on nodes, at a
fixed scale; the numbers are in the panel. If you save the model, these fields go into the `.liml`.

Full documentation: [English](docs/en/MecwayFreebody.md), [Nederlands](docs/MecwayFreebody.md). The panel shows it too, in the
tab *Documentation*, in the language of the panel.

## Development

- `Scripts/`: `MecwayFreebody.py` (entry point), `fb_gui.py`, `fb_mecway.py`, `fb_core.py`, `fb_aster.py`, `fb_nodecut.py` (cut by nodes
  on a plane), `fb_docs.py` (the tab *Documentation*). IronPython 2.7.9 inside Mecway; `fb_core.py`, `fb_aster.py`, `fb_nodecut.py`
  and `fb_docs.py` also run in CPython.
- Tests: `python tests/test_core.py`, `python tests/test_aster.py`, `python tests/test_nodecut.py`, `python tests/test_gui_all.py` (all
  panel parts, among them `nodes`, `shells` and `docs`; it starts a hidden Mecway several times, so run it in the background). End-to-end tests with Code-Aster need bases: `tests/test_aster_e2e.py`,
  `tests/test_solids_e2e.py`, `tests/test_aster_shells_e2e.py` (shells, beams, mixed) and `tests/test_nodecut_e2e.py` (cut by nodes).
  With the MecwayAsterBridge repository next to this one, `tests/test_aster.py` also compares the rules copied from the bridge (model
  name in file names, work folder next to the model, mesh fingerprint, version from the launcher path, its settings) with the bridge's
  branch `develop`, read through `git show`; without it those tests are skipped.
- Version: `VERSION` in `Scripts/fb_core.py`, shown in the header of the panel and in the copied table; changes in
  [CHANGELOG](CHANGELOG.md).
- Images of the panel in the user guide (`docs/images/window_*_{nl,en}.png`, with numbered markers): made off-screen by
  `tools/fb_figures.py` with Mecway's IronPython, without starting Mecway:
  `powershell -ExecutionPolicy Bypass -File tools/run_ipy.ps1 -Script tools/fb_figures.py -ScriptArgs <repo>,docs/images`.
  The numbers per image are in `tools/fb_marks.py`; `tests/test_gui_docs.py` checks them against the tables in both guides.
- Design: [contract](docs/design/contract.md), [research report](docs/research/00_onderzoeksverslag.md), plans for
  [phase 4](docs/design/fase4-plan.md) and the [cut by nodes](docs/design/knopensnede-plan.md) (Dutch).

## License

Mozilla Public License 2.0, see [LICENSE](LICENSE).

## Trademarks

Mecway is a product of Mecway Ltd. Code_Aster is a trademark of EDF. This project is not affiliated with or endorsed by Mecway Ltd or EDF.
