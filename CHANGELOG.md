# Changelog

## V2026.1 (2026-11-10)

First release. Needs MecwayAsterBridge V2026.9 or newer (`keep_base`, manifest schema 2).

- **Resultants on the cuts of a selection**: select elements in Mecway and MecwayFreebody finds where they are cut from the rest. Per
  cut it shows N, Vy, Vz, T, My and Mz about the neutral point, a node or a point you drag on a drawing of the section. The forces are
  Code-Aster's own nodal forces from a short follow-up run on the kept base of a bridge run, so they satisfy equilibrium.
- **Solids, shells, beams and mixed cuts**: section axes and the outline for planar solid cuts, strips for shell edges (thickness and
  offset), beam and truss ends in their own axes, global axes for a mixed or curved cut. Linear and nonlinear static, small and large
  displacements.
- **Cut by nodes on a plane**: the nodes of a planar section as the cut, with a choice of side; a section that closes off no body is
  summed as a partial section, without the equilibrium check.
- **Equilibrium check**: force left on nodes of the selection off the cuts (a support, tie, bonded contact or spring), with the place,
  and supports on the cut itself.
- **Checks before a number**: the run must be of the open model (mesh fingerprint), of the same Code-Aster version, static, and of a
  bridge that describes its connections; otherwise a refusal in plain words (a version that cannot be read points to the launcher
  setting `exe_aster`, not to the run). Warnings for drilling stiffness of shells, M_w of a
  strip, skin shells, contact through an edge, mixed small and large displacements and more.
- **Table, CSV and arrows**: copy the table or save it as CSV; put the resultants or the nodal forces as arrows in Mecway's own
  solution view.
- **Documentation in the panel**: the user guide (Dutch and English, with numbered images of the panel) and the README in the tab
  *Documentation*.
