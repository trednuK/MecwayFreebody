# MecwayFreebody: contract between the parts

Status: phases 2 and 3 of `docs/research/00_onderzoeksverslag.md`. The report holds the why and the measurements. This file
holds the interfaces, so parts can be built at the same time. Change it only by agreement.

## Runtime

- `Scripts/` runs in Mecway's IronPython 2.7.9: Python 2.7, standard library, `clr`/WinForms in the GUI only. No numpy, no
  f-strings, no type hints, no `pathlib`. `mw` and `solution` exist only in the main script: pass them on.
- `fb_core.py` and `fb_aster.py` stay in the common subset of 2.7 and 3 and import neither `clr` nor `mw`, so CPython can test them.
- Numbers in files: never the `g` format in IronPython (it follows the Windows locale). `repr(0.3)` is not `0.3` there.
- Open files with `with`: IronPython has no reference counting.
- No private paths, names or e-mail addresses anywhere. Licence header MPL-2.0 on every source file, as in MecwaySectionProps.

## Files and owners

| File | Part | Holds |
|---|---|---|
| `Scripts/fb_core.py` | core | cut definition, geometry, resultants, axes, table text |
| `Scripts/fb_aster.py` | core | manifest, follow-up run files, starting Code-Aster, reading the result |
| `Scripts/MecwayFreebody.py` | panel | entry point (Tools > Scripts) |
| `Scripts/fb_mecway.py` | panel | everything that touches `mw` and `solution` |
| `Scripts/fb_gui.py` | panel | WinForms panel, drawing |
| `tests/test_core*.py`, `tests/test_aster*.py` | core | CPython, no Mecway |
| `tests/test_gui*.py` | panel | fake `mw`, Mecway's IronPython |

## Data

All lengths in metres, forces in N, moments in N.m.

```python
mesh = {"nodes": {nid: (x, y, z)}, "elements": {eid: (shape, [nid, ...])}}   # shape as mw.element_shape: "hex20", ...
mesh["component"] = {eid: name}                                              # mw.element_component
props = {eid: {"E": 210e9}}                                                  # optional; shells and beams later

plan = fb_core.plan_cuts(mesh, selected_eids)
plan == {
  "inside": [eid], "outside": [eid],
  "cut_nodes": [nid],                     # nodes(selection) & nodes(rest), node based
  "groups": [{"id": 1, "nodes": [nid],
              "faces": [(eid, faceid)],   # faces of selected elements with an outside neighbour
              "kind": "solid"}],          # "solid", later "shell", "beam", "mixed"
  "warnings": [code],
}
```

- Groups: cut nodes joined by cut faces. Groups that share nodes are one group. A cut node on no cut face (contact through an edge or a
  corner only) stays in the force sum: it joins the group it touches, or forms its own group, and gives a warning.
- Face numbers and node order as Mecway writes them in the `.liml`.
- Phase 2 and 3: solids only. A selection with shell or beam elements gives a clear refusal, not a wrong number.
- A refusal is the exception `fb_core.Refused` with `.code` and `.detail`. Codes of `plan_cuts`: `empty`, `unknown_element`, `shell_or_beam`,
  `shape`. Warning codes: `no_cut`, `edge_contact`, `edge_merge` (cuts with faces that only an edge joins are one group), `midside_not_shared`,
  `shell_or_beam_at_cut`.

```python
geo = fb_core.section_geometry(mesh, group, props)
geo == {"area": A, "centroid": (x, y, z),     # E weighted with props, else plain
        "planar": True, "normal": (nx, ny, nz),    # outward from the selection
        "axes": ((nx,ny,nz), (ax,ay,az), (bx,by,bz)),  # right handed; principal axes of a planar cut
        "outline": [[(u, v), ...], ...]}      # loops in the (a, b) plane about the centroid, for the drawing
```

`a` is the axis with the larger second moment; a sign is fixed by the largest component of `a`. Also `"inertia": (Ia, Ib)` and `"warnings"`
(`E_missing`: props incomplete, plain sum; `no_normal`: opposite faces cancel, normal 0). A non-planar cut has `"planar": False` and global axes. Curved faces are integrated with the shape functions; a straight-sided
approximation of area and centroid is not acceptable for hex20 and tet10.

## Follow-up run

```python
man = fb_aster.find_runs(folder, fingerprint)   # manifests in folder with this fingerprint, newest first
reason = fb_aster.refuse(man, version)          # None or a code from REFUSE
job = fb_aster.start(man, folder, plan, mesh, exe, scratch)  # returns at once; never blocks a UI thread; raises Refused
job.poll()                                      # None while running, else True or False
result = job.result()                           # below; job.error() and job.code() when poll() is False
job.stop()                                      # kills only its own process tree
```

Refusal codes: `solver`, `version`, `fingerprint`, `not_shared`, `no_base`, `schema`, `deformation`. The manifest of the bridge is
described in the header of `bridge_manifest.py`. Read optional keys with `.get`. `refuse` also takes `fingerprint` and `folder`. `scratch`
is optional (default the temp folder): the run makes an own folder under it and removes only that. `start` also refuses with `path`, `no_cut`,
`no_aster`. `job.code()` after a failed run: a refusal code, or `start`, `run`, `timeout`, `stopped`. A launcher path without a version gives
`version`. `split_deformation` gives `deformation` for a selected component that is missing or `MIXED`; `MECA_STATIQUE` is small everywhere.

```python
state = fb_aster.check_solution(result, rank, values, tol)   # None, "stale" or "unknown"
```

The same mesh with other loads has the same fingerprint, so a run must be checked against the open solution. `values`: `{nid: (ux, uy, uz)}`
of the active solution; linear the one step, nonlinear the last step of both (`rank` None). Relative to the largest displacement, on the
cut nodes that Mecway knows (`record["nid"]`, None for an added midside node). `unknown`: no such step, nodes without a value, nothing moved.

The run (measured, report section 5, E8 and E9):

- Export: `R base <folder> D 0`, unquoted, also with spaces. `F libr <sel.json> D 32`. Never `R` or `DR`: the base stays read only. Own
  scratch folder per run.
- Groups from positions, not names: `M = res.getMesh()`, `M.setGroupOfCells(name, [i-1 for i in positions])`, then
  `DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_NO=(... INTERSEC ...))`. Positions from `manifest["cells"]`; element eid is `M<eid>`, a split
  line3 also `H<eid>`.
- Skin: cells `K<n>` from `manifest["skin"]` whose parent element is selected and that are in the model: a skin cell of a fixed face is only
  in the mesh and `CALC_CHAMP` stops on it (`MODELISA6_96`). The cells of the model come from
  `res.getModel().getFiniteElementDescriptor().getListOfGroupsOfElements()`: position lists that end with a type number. The rest group
  holds the elements outside the selection, so a skin cell lying in the cut plane cannot enter by accident.
- `rs = CALC_CHAMP(RESULTAT=res, GROUP_MA=<selection + skin>, FORCE='REAC_NODA')`, without `EXCIT`.
- `M.getNodes(group)` is 0-based, as are the positions given to `setGroupOfCells` after `i-1`.
- Sum on x+u where the selected elements computed with large displacements (`manifest["deformation_by_component"]`, a value other than
  `PETIT`), else on x, with u from the base. Mixed components give a warning. `POST_RELEVE_T` is not used: it works on x only.

```python
result == {
  "steps": [{"rank": 1, "time": 1.0}],        # all stored steps; rank 0 included if stored
  "nodes": [{"index": i, "xyz": (x, y, z), "large": bool, "nid": n}],  # cut nodes as Code-Aster knows them, midside nodes after LINE_QUAD included;
                                              # undeformed x; large: sum this node on x + u (fb_core.positions)
  "forces": {rank: [(fx, fy, fz, mx, my, mz)]},   # same order as "nodes": what the rest does to the selection
  "disp": {rank: [(ux, uy, uz)]},
  "rest": {rank: {"sum": (6 values), "largest": F, "cut_largest": F, "tolerance": F, "count": n, "where": [(x, y, z), ...]}},  # sum about the origin
  "on_cut": {rank: {"sum": (6 values), "largest": F, "count": n, "where": [(x, y, z), ...], "tolerance": F,  # sum about the origin
                    "cuts": {group id: {"sum": (6 values), "largest": F, "count": n, "where": [...]}}}},
  "large": bool, "extra_nodes": bool, "warnings": [code],                  # mixed_deformation, skin_on_cut
  "seconds": t,
}
```

`rest` is the equilibrium check, and it needs no reading of loads: at nodes of the selection that are not cut nodes `REAC_NODA` must be
zero, unless something the cut does not see acts there (a support, a tie, bonded contact, a spring). `count` uses a tolerance relative to
the smallest resultant of the cuts (1e-4), so a light cut does not hide behind a heavy one, with the noise of the solver as a lower limit
(relative to the largest nodal force: 1e-10 linear, 1e-5 nonlinear). `count` stops at 200. Measured: 1e-9 N at 374 N on clean models; a tie shows 2690 N and points to the place. Rank 0 of a
nonlinear run is the state before the first step, not an equilibrium: its `rest` is not zero.

`on_cut` shows what acts on the cut nodes from outside the elements. A second `CALC_CHAMP` without `GROUP_MA` gives the force over all sides
of a node: zero on a free node, the force of a support or coupling on any other. By convention (report section 6.2) that force belongs to
the rest and stays in the sum of the cut, but the panel must show it. Same tolerance as `rest`. A nodal load on a cut node balances in that
force too, so it does not show here.

## Resultants

```python
per_group = fb_core.assign_nodes(plan, mesh, result)      # {group id: [index in result["nodes"]]}; midside nodes by nearest group node;
                                                          # Refused("node_mismatch") if nodes of the plan and the run do not fit
xyz = fb_core.positions(result, rank)                     # where the forces act, order of result["nodes"]: x, or x + u per node
mixed = fb_core.mixed_shape(result, per_group[gid])       # True if nodes of this cut are summed on different shapes
sum6 = fb_core.resultant(xyz_list, forces6_list, point)   # (Fx, Fy, Fz, Mx, My, Mz) about point, in global axes
shifted = fb_core.shift(sum6, old_point, new_point)       # M_new = M_old + (old - new) x F; no resum, so dragging is instant
local = fb_core.to_axes(sum6, axes)                       # (N, Vy, Vz, T, My, Mz); y is a, z is b
text = fb_core.table_text(rows, decimal=",")              # tab separated, for the clipboard and CSV
```

Sign: the force of the rest on the selection; N positive in tension, along the outward normal. The panel states this.


## Phase 4: shells, beams and mixed cuts

Agreed in `docs/design/fase4-plan.md` (version 2). Everything above stays valid; this section adds to it.

### Data

```python
props = {eid: {"E": 210e9,
               "thickness": t,                       # shells, from mw.material_property(m, "thickness")
               "section": {"A":, "IY":, "IZ":, "JX":, "shape": ...}}}   # beams, from the material
plan["groups"][k] == {"id": 1, "nodes": [nid],
                      "entities": [("face", eid, faceid), ("edge", eid, edge), ("end", eid, nid)],
                      "faces": [(eid, faceid)],     # kept for solids
                      "kind": "solid" | "shell" | "beam" | "mixed"}
```

- Neighbour rule per kind: a solid face counts with a solid neighbour outside the selection; a shell edge with a **shell** neighbour
  over the same edge; a beam end node when the node also belongs to an element outside the selection. Entities that share nodes form
  one group.
- Warnings: `skin_shell` (a selected shell lying on an outside solid face), `beam_along_cut` (both nodes of a beam on the cut),
  `mixed_cut`, `node_contact` (a cut node on no entity of its kind, for example a shell edge standing on a solid face or a plate edge
  next to an outside beam: its force is in the sum, but not in the neutral point, the axes or the drawing), and `drilling` (as built
  below: shells of the model that are not coplanar or carry a nodal moment about their normal, or any element that is not a shell,
  or any coupling, attached to a shell node in or around the selection). The drilling warning names `coef_rigi_drz` (null means
  Code-Aster's default 1e-5).

### Geometry

```python
geo == {..., "strips": [{"a": (x,y,z), "b": (x,y,z), "t": t, "w": (wx,wy,wz), "offset": e}],   # shells
             "beams": [{"node": nid, "A": A, "axes": ((x..),(y..),(z..))}]}               # beams
```

- Sections of beams come from the manifest (`cara`/`vale` as Code-Aster got them), not from Mecway's material: Mecway gives only
  the raw dimensions for most section types. Thickness of shells comes from Mecway (`material_property(m, "thickness")`).
- Strips: area t x L on the midline (shifted by e along w with `EXCENTREMENT`), length with quadratic edges integrated; second moments
  thin-walled including t·L³/12 about the edge.
- Axes: principal axes for solids or a planar set of strips; a single strip uses (n, t, w); a single beam its Code-Aster axes (for an
  L section these are the principal axes, not the legs; the panel says so); mixed or non-planar: global. A strip or a beam that
  computed with large displacements (`deformation_by_component` not PETIT) gets global axes and a warning `large_axes`: its local axes
  turn with the deformation.
- Trusses (BARRE, CABLE): x along the element, only N; there is no `beam_axes` entry.

### Signs

- Beam: N positive in tension along the outward normal. Cut at node 2 of the element: local +x; at node 1: -x, with x and z mirrored and
  y kept.
- Shell strip: n in the shell plane, perpendicular to the edge, out of the selected element; t along the edge; w the shell normal.
  t = w x n, so (n, t, w) is right handed. Components N (n), V_t, V_w, T (about n), M_t (about t), M_w (about w, always marked
  unreliable).
- Line3 beams split by the bridge: cell `M<eid>` is the half at node 1, `H<eid>` the half at node 2; the cut end uses its own half.

### Manifest schema 2 (bridge)

Schema 1 keeps working for solids. A selection with shells or beams and a schema 1 manifest is refused with `schema_old`.

```text
"components": {mecway name: {"model": "DKT"|"DST"|"COQUE_3D"|"POU_D_E"|"POU_D_T"|"POU_D_TG"|"POU_D_T_GD"|"BARRE"|"CABLE"|"3D",
                             "has_warping": bool,
                             "section": {"cara": [...], "vale": [...], "shape": ...}}}   # beams and trusses
"coef_rigi_drz": value or null
"beam_axes": {cell name: [[x], [y], [z]]}          # as given to Code-Aster, per (half) cell
"excentrement": {eid: e}                            # DKT/DST offsets
"not_shared": {kind: {"nodes": [nid], "origin": "user"|"bridge"}}   # schema 1: a list of kinds
```

### Refusals and checks

- New refusal codes: `beam_warping` (POU_D_TG), `beam_large_rotation` (POU_D_T_GD or beams with GROT_GDEP), `offset`
  (`offset_links`), `schema_old`, `not_shared_on_cut` (a connection from `not_shared` touches a cut node and also has nodes outside
  the selection; a bridge relation that lies wholly inside the selection, such as `line3truss`, is no reason to refuse).
- Version (V2026.1): `run_version` when the manifest has `aster_version` null (the bridge read it neither from the `.mess` nor from
  its launcher path; a missing key stays `schema`), `launcher_version` when the version of our launcher cannot be read from its path
  (`...\<version>\bin\run_aster.bat`, a dotted number as in the bridge); `version` only for a real mismatch. `start()` gives the
  launcher path or the version of the run as the detail of `Refused`.
- `not_shared` without a cut node becomes a warning, and only once `rest` and `on_cut` also count moments: a nodal moment m counts with
  |m| / L, where L is the largest distance from the cut to a node of the selection (the real lever arm; never zero, also for a beam
  cut at one node). The noise floor is noise x max(F_max, M_max / L), so a cut in pure bending has a floor too.
- Errors and tolerances are normalised as max(|M|, |F|·L) throughout.

### As built (part A, core)

Additions and refinements; where they differ from the text above, these hold.

- `plan_cuts` refuses only `empty`, `unknown_element`, `shape`; `shell_or_beam` and the warning `shell_or_beam_at_cut` are gone.
  `plan["drilling"]` holds the criteria: `not_coplanar`, `nodal_moment`, `other_element`, `coupling`; `"drilling"` is then also in
  `plan["warnings"]`. Optional mesh keys: `"moments": {nid: (mx, my, mz)}` (judged by direction), `"moment_nodes": [nid]` (no
  direction: counts), `"coupled_nodes": [nid]`.
- The panel fills `moments` and `moment_nodes` with `fb_mecway.read_moments_steps`, only when the model has shells. Mecway's API
  lists no loads, so they come from the saved `.liml` (outside `<solution>`), the nodes through `mw.named_selection`. As the bridge
  translates them: a `<moment>` on one node or one beam end counts (in N.m, a unit table); on more nodes, on faces or on an element
  selection it is no nodal moment and is left out. A `<noderotation>` whose value is not zero (DDL_IMPO in the bridge, no force)
  counts with its axis on every node of its selection, as a precaution: not measured. A moment whose direction cannot be told (a
  formula, an unknown unit, a time history that turns), and every node with more than one entry of which one is not steady, goes
  to `moment_nodes`. A file that ends inside an element counts as unreadable. Suppression per configuration is ignored (the active one cannot be read).
  What cannot be read is not guessed: a file that cannot be read or a selection the API does not know gives the panel warning
  `moments_unread`. The file holds the loads as last saved; the fingerprint covers the mesh only. A later bridge could give the
  nodal moments in the manifest; only `read_moments_steps` would change.
- `coupled_nodes` stays empty in the panel: `fb_aster.check_plan` gives `coupling` from the manifest's `not_shared`, what
  Code-Aster really got, for every kind of connection. It uses the plan's inside, outside and cut nodes, so it also works for a
  partial node cut.
- Drilling, measured with the bridge and Code-Aster (`tests/test_aster_shells_e2e.py`): a fold and a moment about the shell normal
  spoil a cut also when they lie beyond it (3.6e-5 and 2.7e-2 on both cuts); an in-plane tip moment is clean (3e-11), a solid
  attached to a shell too (5e-12). So `not_coplanar` and `nodal_moment` look at every shell of the model, and `nodal_moment` only at
  the part of a moment about the normal of a shell at that node; `other_element` and `coupling` at the shells in or around the selection.
- `edge_contact`: a cut node on no entity that only solids touch; `node_contact`: one that a shell or beam touches (either side).
  `skin_shell`: a selected shell whose corners all lie on one outside solid face, or an outside shell on a selected solid face.
- `props` per element, from `fb_aster.manifest_props(man, mesh, eids)` plus `E` and `thickness` from Mecway: `"model"`, `"truss"`,
  `"section"` (`A`, `IY`, `IZ`, `JX`, `shape`; a tapered one `"end2"`), `"beam_axes"` (`{"M": (x, y, z), "H": ...}`), `"offset"` (e along
  the normal of the node order), `"large"`.
- `geo["strips"]` also: `eid`, `faceid`, `n`, `edge` (t), `length`, `points`, `large`; `geo["beams"]` also: `eid`, `end` (1, 2), `cell`
  (M, H), `model`, `truss`, `section`, `large`; `geo["only_n"]`. Warnings also `thickness_missing`, `section_missing` (then `"area"` is
  None and every strip or beam of the group counts alike), `beam_axes_missing`, `large_axes`.
- A flat set of strips (one line in one plane: a plate cut straight across) keeps (n, t, w) like a single strip, so the axes do not
  swap when one more element is selected; principal axes for other planar sets (I, C, box). Inertia of (n, t, w): (0, t·L³/12).
  Several beams on one cut node: global axes.
- `fb_aster.check_plan(man, plan, mesh)`: `{"warnings", "drilling"}` or Refused; `start` calls it. Also `shape` (a shell or line of
  another model, such as DIS_T or Q4G) and `schema` (a component the manifest lacks). `not_shared` per connection from `groups`
  when the bridge gives them, else `nodes`; a connection wholly in the selection on a cut node gives the warning `relation_on_cut`
  (its Lagrange force is in the cut sum). `truss_part` gives model and section of the trusses of a mixed component.
- The lever L of `rest` and `on_cut`: max(largest distance from the cut to a node of the selection, extent of the cut nodes), else
  the extent of the selection, else 1 m; `result["lever"]`. Sizes are force-equivalents max(|F|, |m|/L); `rest` has
  `"cut_largest_moment"`. `result["coef_rigi_drz"]` as in the manifest (None: Code-Aster's default, `fb_aster.DRZ_DEFAULT`) and
  `result["drilling"]` (the plan's criteria and `coupling` from `not_shared`).
- `assign_nodes` checks for missing midside nodes only when the mesh has no quad8 or tri6 and a group has faces: QUAD8_9 and
  TRIA6_7 add centre nodes that are never shared. The bridge applies LINE_QUAD to the whole mesh when every non-solid elset is a
  shell that gets LINE_QUAD itself (COQUE_3D on linear shells), so a solid cut next to linear shells does need its midside nodes;
  quadratic shells get QUAD8_9 and block LINE_QUAD.
- `geo["axes_kind"]`: `section` (principal axes), `strip` (n, t, w), `beam`, `truss` or `global`. Only the core chooses the axes.
- `props[eid]["section"]` never comes from Mecway: Mecway gives only the raw dimensions of most section types; the section is the
  one Code-Aster got (`manifest_props`). `E` and `thickness` come from Mecway.
- The w of the axes of a strip or a flat strip set has a fixed sign (largest component positive), t = w x n; `strips[i]["w"]` keeps
  the normal of the node order, along which the offset e counts.
- A skin shell keeps its edges with a shell neighbour as entities (a plate glued on a block and going on past it); its other
  nodes are a node contact.
- `other_element` is conservative: measured clean for a solid on a shell (5e-12); it stays until beams and couplings on shells are
  measured.
- Zero thickness or area counts as missing. A beam axes entry that is not three rows of three numbers is dropped
  (`beam_axes_missing`); `beam_axes` or `excentrement` that is no dict refuses with `schema`. A selected shell or beam whose
  component the deformation table of a nonlinear run lacks refuses with `deformation`.
- The lever uses at most about 2000 cut nodes (a scale, not a result) and must be finite.

## Cut by nodes on a plane

Agreed in `docs/design/knopensnede-plan.md` (the rules after the review). `Scripts/fb_nodecut.py`, pure Python, no Mecway; the full
dict is described in its header.

```python
cut = fb_nodecut.plan_from_nodes(mesh, node_ids, side=1)   # side 1: where the plane normal points (largest component > 0)
cut == {"partial": bool, "rest_valid": bool,       # partial: the nodes close no body; "rest" means nothing then
        "elements": [eid],                         # selection of the follow-up run: grown body, or the layer if partial
        "plan": plan,                              # as plan_cuts gives it; partial: the reduced plan (never the back of the layer)
        "keep": [nid], "keep_points": [(x, y, z)], # cut nodes; + midpoints of linear edges for LINE_QUAD nodes
        "normal": (nx, ny, nz),                    # outward from the free body, as section_geometry gives it
        "plane": {"point", "normal", "tolerance", "distance"}, "side": 1 | -1,
        "selected", "not_cut", "layer", "leak", "warnings": [code]}   # partial_section, selected_not_cut
less = fb_nodecut.filter_result(result, cut[, mesh])   # a copy; same indices for nodes, forces, disp, on_cut totals
```

- Use: `start(man, folder, cut["plan"], mesh, exe)`, `less = filter_result(job.result(), cut)`, then
  `assign_nodes(cut["plan"], mesh, less)` and `section_geometry` per group of `cut["plan"]`, as for an element selection.
- Refusals (`Refused.code`), in this order: `unknown_node`, `nodes_collinear` (fewer than three nodes or on one line),
  `nodes_without_solid`, `nodes_not_planar`, `shell_or_beam`, `plane_through_elements`, `side_empty`, `no_cut`, and those of
  `plan_cuts` for the body. `shell_or_beam` is fb_nodecut's own rule: a shell or beam on a selected node refuses the node cut.
  Shells and beams elsewhere in the free body are allowed: a full section hands the grown body to `plan_cuts`, exactly as an
  element selection of that body (`cut["plan"] == plan_cuts(mesh, body)`); a partial section is the layer at the selected nodes,
  which then holds solids only.
- A partial section judges `plan["drilling"]` on the whole mesh (its reduced plan has no shells), so `not_coplanar` and
  `nodal_moment` look at every shell of the model there too.
- One tolerance for "on the plane": `PLANE_TOL` (1e-6) times the largest distance of a selected node to their mean.
- Full: the growth from the layer, never over a selected node or a midside node between two selected corners, does not reach an element
  with a node strictly at the other side. Else partial (also a U seen from its base, or a ring cut once). The subset rule then holds by
  construction and stays as a check.
- `filter_result` on a partial section: `rest[rank]["valid"] = False`, warning `partial_section`, `"nodecut"` with the flags and the
  kept indices. A full section loses no node, else `Refused("node_mismatch")`.
- `on_cut` of a partial section is only valid when the filter runs before `judge_rest`. The hook in `fb_aster`:
  `start(..., prepare=None)`; `Job.result()` applies `result = prepare(result)` right after `decode_result`, before `link_nodes` and
  `judge_rest`; caller `prepare=lambda r: fb_nodecut.filter_result(r, cut)`. `judge_rest` then gives a step of `rest` with
  `"valid": False` the tolerance but `"count": None` and no `"where"`, and judges `on_cut` over the kept nodes.
  `Refused("node_mismatch")` can come out of `Job.result()`. Without the hook, a step of `on_cut` that lost nodes gets
  `"valid": False`.
- Panel: `fb_gui.plan_and_start` passes `prepare` to `fb_aster.start` for a cut by nodes, so `job.result()` is the filtered
  result. `PanelModel.load(..., nodecut=cut)`; a partial section (`cut["partial"]`, `result["nodecut"]["partial"]` or
  `rest[rank]["valid"] is False`) shows no equilibrium, and an `on_cut` step with `"valid": False` says it cannot be told.

## Panel

- Non-modal window on its own STA thread, all `mw` calls through the script thread (a pattern proved in a separate
  tool; the drawing as in MecwaySectionProps `section_gui.py`). One instance per Mecway process.
- Flow: select elements, press Compute (or start with a selection). The run goes in the background with progress; the UI never blocks.
- Run folder: the panel looks next to the model and in the bridge's work folder, shows the run it uses, and allows another folder.
- Shows per cut: N, Vy, Vz, T, My, Mz about the neutral point, step choice, sign convention, units, the equilibrium result in plain view,
  warnings. The drawing of the section with arrows and numbers; the point can be dragged or typed; assignments are instant.
- Copy and save as CSV.
- Arrows in Mecway: `solution.set_variable` on `externalforcex/y/z` and `reactionmomx/y/z`, only if the field does not exist yet, otherwise
  say so and skip. The first write in a solution keeps its true values, so Mecway's legend is right; the legend does not follow a second
  write (measured), so later writes keep the length of the first and the panel says so.
  `mw.open()` closes a panel: never call it from the panel.

## Testing

- Reference is statics, always with two cuts. Negative controls stay as tests.
- Test windows never take the focus (`ShowWithoutActivation`, no `SetForegroundWindow`), can be covered by other windows and prefer
  off-screen drawing (`DrawToBitmap`). The user works on this PC.
- Scripts run in Mecway's own IronPython through a hidden `mecway.exe <model> script <file>`; `.ps1` files are blocked here. Kill only your
  own PID. Only self-made models.
