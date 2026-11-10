# Test results of the core

The last green runs of `tests/test_aster_e2e.py` and `tests/test_solids_e2e.py`: real Code-Aster 17.4 on bases that the bridge made, against exact
statics, two cuts, each stored step. The output below is verbatim; only blank lines are left out. Self-made models only.

- Date: 7 November 2026. Core: development state of 7 November 2026, on the way to V2026.1; bridge at commit `003daa4` (on its main).
- Bases built fresh with that bridge: `e9_chain.py lin lq nl`, `test_aster_e2e.py build` and `solids_build.py`. All models are small, up to about
  2000 elements; the two large ones (`k_lin`, `k_nl`) and the run in Mecway are skipped here.
- `eF` and `eM`: difference with the statics, relative to the larger of the force and the moment over the bar length.
- Rank 1 of `c_nl` stands at 1e-6: that step converged to `RESI_GLOB_RELA` 1e-5, and the difference is the residual of the run, not of the sum.
- Rank 0 of `c_nl` is the state before the first step and no equilibrium; the check says so (a test of its own).
- `c_other` is the mesh of `c_lin` with 20% more load: same fingerprint, so only `check_solution` can tell the runs apart.
- `g_line` has a support on cut nodes only: 2640 N that stays in the sum of the cut by convention, and that `on_cut` now shows.

## test_aster_e2e

```text
test_control_missing_midside_nodes (tests.test_aster_e2e.ExtraNodes.test_control_missing_midside_nodes) ... control c_lq midside: eF 1.33 eM 0.46
ok
test_nodes_of_mecway_are_linked (tests.test_aster_e2e.ExtraNodes.test_nodes_of_mecway_are_linked) ... ok
test_statics (tests.test_aster_e2e.ExtraNodes.test_statics) ... c_lq cut 1: eF 4.4e-12 eM 2.0e-12
c_lq cut 2: eF 6.1e-12 eM 6.1e-13
ok
test_control_fingerprint (tests.test_aster_e2e.Linear.test_control_fingerprint) ... ok
test_control_missing_midside_nodes (tests.test_aster_e2e.Linear.test_control_missing_midside_nodes) ... control midside: eF 1.33 eM 0.46
ok
test_control_missing_skin_cell (tests.test_aster_e2e.Linear.test_control_missing_skin_cell) ... control skin: eF 1.0e-02 eM 4.0e-12, rest count 28, 25 N
ok
test_control_wrong_sign (tests.test_aster_e2e.Linear.test_control_wrong_sign) ... control wrong sign: eF 2.00
ok
test_section_of_the_cut (tests.test_aster_e2e.Linear.test_section_of_the_cut) ... ok
test_shift_is_a_new_sum (tests.test_aster_e2e.Linear.test_shift_is_a_new_sum) ... ok
test_statics (tests.test_aster_e2e.Linear.test_statics) ... c_lin cut 1: eF 4.8e-12 eM 4.0e-12, 2.9 s
c_lin cut 2: eF 8.0e-12 eM 1.3e-12, 2.9 s
c_lin rest 1.1e-09 N of 753 N, on the cut 1.5e-09 N
ok
test_stop_real_run (tests.test_aster_e2e.Linear.test_stop_real_run) ... ok
test_tension_is_positive (tests.test_aster_e2e.Linear.test_tension_is_positive) ... ok
test_base_stays_read_only (tests.test_aster_e2e.Nonlinear.test_base_stays_read_only) ... ok
test_component_not_in_the_table (tests.test_aster_e2e.Nonlinear.test_component_not_in_the_table) ... ok
test_control_u_on_a_small_displacement_component (tests.test_aster_e2e.Nonlinear.test_control_u_on_a_small_displacement_component) ... ok
test_control_x_instead_of_x_plus_u (tests.test_aster_e2e.Nonlinear.test_control_x_instead_of_x_plus_u) ... control x instead of x+u: eM 2.4e-04
ok
test_last_step_is_the_last_step_of_the_solution (tests.test_aster_e2e.Nonlinear.test_last_step_is_the_last_step_of_the_solution) ... ok
test_mixed_components_sum_per_node (tests.test_aster_e2e.Nonlinear.test_mixed_components_sum_per_node) ... ok
test_rank_zero_is_no_equilibrium_and_the_check_says_so (tests.test_aster_e2e.Nonlinear.test_rank_zero_is_no_equilibrium_and_the_check_says_so) ... ok
test_statics_per_step (tests.test_aster_e2e.Nonlinear.test_statics_per_step) ... c_nl rank 1 cut 1: eF 1.2e-06 eM 2.7e-08, rest 7.3e-04 N, u 4.05 mm
c_nl rank 1 cut 2: eF 1.4e-06 eM 3.5e-08, rest 7.3e-04 N, u 4.05 mm
c_nl rank 2 cut 1: eF 9.3e-13 eM 8.4e-14, rest 2.9e-06 N, u 4.05 mm
c_nl rank 2 cut 2: eF 1.1e-12 eM 2.2e-14, rest 2.9e-06 N, u 4.05 mm
c_nl rank 3 cut 1: eF 2.4e-13 eM 9.2e-14, rest 1.6e-06 N, u 4.05 mm
c_nl rank 3 cut 2: eF 3.8e-13 eM 2.1e-14, rest 1.6e-06 N, u 4.05 mm
c_nl rank 4 cut 1: eF 2.4e-13 eM 3.8e-14, rest 1.8e-06 N, u 4.05 mm
c_nl rank 4 cut 2: eF 6.7e-13 eM 2.8e-14, rest 1.8e-06 N, u 4.05 mm
ok
test_base_of_another_load (tests.test_aster_e2e.StaleBase.test_base_of_another_load) ... stale base: disp differs 2.99e-05 m at 20% more load
ok
test_no_solution_values (tests.test_aster_e2e.StaleBase.test_no_solution_values) ... ok
test_own_solution (tests.test_aster_e2e.StaleBase.test_own_solution) ... ok
test_same_fingerprint (tests.test_aster_e2e.StaleBase.test_same_fingerprint) ... ok
----------------------------------------------------------------------
Ran 24 tests in 35.896s
OK
```

## test_solids_e2e

```text
test_missing_midsides_pyramid (tests.test_solids_e2e.Controls.test_missing_midsides_pyramid) ... control midside a_pyr13: eF=1.35e+00 eM=4.49e-01
ok
test_missing_midsides_tet (tests.test_solids_e2e.Controls.test_missing_midsides_tet) ... control midside a_tet10: eF=1.01e+00 eM=3.49e-01
ok
test_missing_midsides_wedge (tests.test_solids_e2e.Controls.test_missing_midsides_wedge) ... control midside a_w15x: eF=1.01e+00 eM=3.49e-01
ok
test_missing_skin_tet (tests.test_solids_e2e.Controls.test_missing_skin_tet) ... control skin a_tet10: count=14 eF=1.02e-02 eM=2.74e-13 rest=2.50e+01
ok
test_missing_skin_wedge (tests.test_solids_e2e.Controls.test_missing_skin_wedge) ... control skin a_w15z: count=14 eF=1.02e-02 eM=7.54e-12 rest=2.50e+01
ok
test_wrong_sign (tests.test_solids_e2e.Controls.test_wrong_sign) ... control sign: eF=2.00e+00 eM=7.07e-01
ok
test_hex20 (tests.test_solids_e2e.Distorted.test_hex20) ... d_hex20: count=0 cut=2.15e+03 eF=1.33e-12 eM=8.13e-13 nodes=74 rest=8.98e-10 s=2.40e+00 warn=
ok
test_hex8 (tests.test_solids_e2e.Distorted.test_hex8) ... d_hex8: count=0 cut=1.85e+03 eF=2.13e-13 eM=8.15e-14 nodes=30 rest=1.59e-10 s=2.40e+00 warn=
ok
test_oblique_plane (tests.test_solids_e2e.Distorted.test_oblique_plane) ... d_obl: count=0 cut=2.09e+03 eF=4.56e-12 eM=2.67e-12 nodes=74 rest=9.88e-10 s=2.40e+00 warn=
ok
test_oblique_plane_wedges (tests.test_solids_e2e.Distorted.test_oblique_plane_wedges) ... d_oblw: count=0 cut=1.27e+03 eF=3.13e-12 eM=2.01e-12 nodes=90 rest=1.27e-09 s=2.50e+00 warn=
ok
test_tet10 (tests.test_solids_e2e.Distorted.test_tet10) ... d_tet10: count=0 cut=1.33e+03 eF=1.81e-12 eM=1.08e-12 nodes=90 rest=8.87e-10 s=2.40e+00 warn=
ok
test_trapezoid_section (tests.test_solids_e2e.Distorted.test_trapezoid_section) ... d_trap: count=0 cut=2.64e+03 eF=1.47e-12 eM=1.01e-12 nodes=74 rest=9.37e-10 s=2.50e+00 warn=
ok
test_hex20 (tests.test_solids_e2e.EdgeAndCorner.test_hex20) ... edge e_hex20: count=0 cut=8.03e+01 eF=2.94e-13 eM=1.02e-13 groups=[5, 1] nodes=6 rest=2.87e-12
ok
test_hex8 (tests.test_solids_e2e.EdgeAndCorner.test_hex8) ... edge e_hex8: count=0 cut=9.10e+01 eF=9.02e-14 eM=3.11e-14 groups=[3, 1] nodes=4 rest=6.03e-13
ok
test_line_quad (tests.test_solids_e2e.EdgeAndCorner.test_line_quad) ... edge e_lq: count=0 cut=8.03e+01 eF=3.24e-13 eM=1.20e-13 groups=[3, 1] nodes=6 rest=4.51e-12
ok
test_read_in_ironpython (tests.test_solids_e2e.InMecway.test_read_in_ironpython) ... skipped 'only on request, with a base'
test_linear (tests.test_solids_e2e.Large.test_linear) ... skipped 'no base of k_lin, Code-Aster or numpy'
test_nonlinear (tests.test_solids_e2e.Large.test_nonlinear) ... skipped 'no base of k_nl, Code-Aster or numpy'
test_extra_nodes_on_triangles_and_quads (tests.test_solids_e2e.Linequad.test_extra_nodes_on_triangles_and_quads) ... ok
test_force_on_a_node_counts_on_the_selection (tests.test_solids_e2e.Nodal.test_force_on_a_node_counts_on_the_selection) ... nodal force: count=0 eF=1.34e-11 eM=7.27e-12 largest=1.13e-09
ok
test_linear (tests.test_solids_e2e.Pressure.test_linear) ... g_press: count=0 cut=1.21e+04 eF=3.25e-11 eM=1.76e-11 nodes=74 rest=1.32e-08 s=2.30e+00 warn=
ok
test_nonlinear_follower (tests.test_solids_e2e.Pressure.test_nonlinear_follower) ... n_press rank 1: count=0 eF=1.02e-06 eM=2.23e-08 rest=1.66e-03 u=5.44e-03
n_press rank 2: count=0 eF=3.05e-13 eM=7.65e-14 rest=8.11e-06 u=5.44e-03
n_press rank 3: count=0 eF=1.61e-10 eM=1.40e-11 rest=9.16e-07 u=5.44e-03
n_press rank 4: count=0 eF=1.55e-12 eM=5.60e-14 rest=3.89e-07 u=5.44e-03
ok
test_a_pyr13 (tests.test_solids_e2e.Shapes.test_a_pyr13) ... a_pyr13: count=0 cut=2.08e+03 eF=5.53e-12 eM=2.23e-12 nodes=74 rest=6.13e-10 s=2.40e+00 warn=
ok
test_a_pyr5 (tests.test_solids_e2e.Shapes.test_a_pyr5) ... a_pyr5: count=0 cut=1.73e+03 eF=1.43e-12 eM=7.97e-13 nodes=30 rest=4.94e-10 s=2.40e+00 warn=
ok
test_a_tet10 (tests.test_solids_e2e.Shapes.test_a_tet10) ... a_tet10: count=0 cut=1.28e+03 eF=9.62e-13 eM=2.74e-13 nodes=90 rest=5.36e-10 s=2.40e+00 warn=
ok
test_a_tet4 (tests.test_solids_e2e.Shapes.test_a_tet4) ... a_tet4: count=0 cut=1.80e+03 eF=2.97e-13 eM=1.34e-13 nodes=30 rest=2.81e-10 s=2.30e+00 warn=
ok
test_a_w15x (tests.test_solids_e2e.Shapes.test_a_w15x) ... a_w15x: count=0 cut=1.28e+03 eF=3.60e-12 eM=1.28e-12 nodes=90 rest=9.19e-10 s=2.50e+00 warn=
ok
test_a_w15z (tests.test_solids_e2e.Shapes.test_a_w15z) ... a_w15z: count=0 cut=2.08e+03 eF=1.46e-11 eM=7.54e-12 nodes=74 rest=1.09e-09 s=2.50e+00 warn=
ok
test_a_w6x (tests.test_solids_e2e.Shapes.test_a_w6x) ... a_w6x: count=0 cut=1.86e+03 eF=1.06e-12 eM=5.57e-13 nodes=30 rest=3.24e-10 s=2.40e+00 warn=
ok
test_a_w6z (tests.test_solids_e2e.Shapes.test_a_w6z) ... a_w6z: count=0 cut=1.83e+03 eF=5.61e-13 eM=3.42e-13 nodes=30 rest=1.83e-10 s=2.70e+00 warn=
ok
test_b_hw (tests.test_solids_e2e.Shapes.test_b_hw) ... b_hw: count=0 cut=1.73e+03 eF=4.25e-13 eM=2.31e-13 nodes=30 rest=1.62e-10 s=2.50e+00 warn=
ok
test_b_mix (tests.test_solids_e2e.Shapes.test_b_mix) ... b_mix: count=0 cut=1.76e+03 eF=7.03e-13 eM=3.71e-13 nodes=30 rest=4.26e-10 s=2.30e+00 warn=
ok
test_b_mix2 (tests.test_solids_e2e.Shapes.test_b_mix2) ... b_mix2: count=0 cut=2.08e+03 eF=3.71e-12 eM=1.50e-12 nodes=82 rest=8.08e-10 s=2.40e+00 warn=
ok
test_b_mixlq (tests.test_solids_e2e.Shapes.test_b_mixlq) ... b_mixlq: count=0 cut=2.08e+03 eF=6.52e-12 eM=3.75e-12 nodes=82 rest=9.39e-10 s=2.40e+00 warn=
ok
test_one_layer_all_nodes_on_a_cut (tests.test_solids_e2e.SmallSelections.test_one_layer_all_nodes_on_a_cut) ... layer_hex8: count=0 cut=1.19e+03 eF=6.04e-13 eM=1.68e-13 nodes=30 rest=0.00e+00 s=2.30e+00 warn=
ok
test_one_layer_quadratic (tests.test_solids_e2e.SmallSelections.test_one_layer_quadratic) ... layer_hex20: count=0 cut=1.42e+03 eF=1.25e-11 eM=3.84e-12 nodes=74 rest=1.44e-10 s=2.40e+00 warn=
ok
test_hex20 (tests.test_solids_e2e.Staircase.test_hex20) ... stairs a_hex20: count=0 cut=1.85e+03 eF=1.30e-11 eM=6.00e-12 nodes=118 rest=1.69e-09 s=2.80e+00 warn=
ok
test_hex8_line_quad (tests.test_solids_e2e.Staircase.test_hex8_line_quad) ... stairs c_lq: count=0 cut=1.85e+03 eF=5.61e-12 eM=2.32e-12 nodes=118 rest=7.04e-10 s=2.90e+00 warn=
ok
test_jagged_pyr13 (tests.test_solids_e2e.Staircase.test_jagged_pyr13) ... jag a_pyr13: count=0 cut=8.45e+02 eF=5.57e-12 eM=2.45e-12 nodes=170 rest=6.13e-10 s=2.80e+00 warn=
ok
test_jagged_tet10 (tests.test_solids_e2e.Staircase.test_jagged_tet10) ... jag a_tet10: count=0 cut=1.44e+03 eF=9.33e-13 eM=3.07e-13 nodes=138 rest=4.27e-10 s=2.60e+00 warn=
ok
test_jagged_tet4 (tests.test_solids_e2e.Staircase.test_jagged_tet4) ... jag a_tet4: count=0 cut=1.85e+03 eF=3.07e-13 eM=1.44e-13 nodes=44 rest=2.81e-10 s=2.50e+00 warn=
ok
test_jagged_wedge15 (tests.test_solids_e2e.Staircase.test_jagged_wedge15) ... jag a_w15x: count=0 cut=1.43e+03 eF=3.71e-12 eM=1.38e-12 nodes=106 rest=9.19e-10 s=2.60e+00 warn=
ok
test_mixed (tests.test_solids_e2e.Staircase.test_mixed) ... stairs b_mix2: count=0 cut=1.13e+03 eF=4.21e-12 eM=1.19e-12 nodes=141 rest=8.08e-10 s=2.60e+00 warn=
ok
test_tet10 (tests.test_solids_e2e.Staircase.test_tet10) ... stairs a_tet10: count=0 cut=1.13e+03 eF=1.10e-12 eM=1.84e-13 nodes=146 rest=5.28e-10 s=2.60e+00 warn=
ok
test_cut_through_the_support (tests.test_solids_e2e.Supports.test_cut_through_the_support) ... cut through support: count=8 cut=7.91e+02 cut_sum=[-2423.04, 686.95, -4287.07] free_cut_eF=7.50e-13 free_cut_eM=7.08e-13 identity_F=1.07e-12 identity_M=6.53e-13 largest=1.95e+03 node_reaction_error=1.42e-14 on_both=5 reaction_on_cut=[-862.51, 88.15, -41.28] rest_sum=[423.04, -1186.95, 5293.23]
ok
test_measure_support_on_the_cut_nodes_only (tests.test_solids_e2e.Supports.test_measure_support_on_the_cut_nodes_only) ... support on cut only: count=0 cut=1.71e+03 cut_sum=[-2000.0, -500.0, 1006.16] identity_F=1.49e-13 identity_M=2.11e-13 largest=9.77e-11 reaction=[1240.51, -899.04, 2148.88] warnings=[]
ok
test_selection_holds_the_support (tests.test_solids_e2e.Supports.test_selection_holds_the_support) ... support inside: count=21 cut=7.91e+02 eF=7.03e-13 eM=1.33e-13 erest_F=6.62e-13 erest_M=6.42e-13 largest=1.95e+03 rest_F=[-2000.0, -500.0, 1312.321] statics=[-2000.0, -500.0, 1312.321]
ok
test_selection_with_the_clamp (tests.test_solids_e2e.Supports.test_selection_with_the_clamp) ... clamp in the selection: count=37 erest_F=9.30e-12 erest_M=7.50e-12
ok
test_support_on_the_cut_nodes_is_shown (tests.test_solids_e2e.Supports.test_support_on_the_cut_nodes_is_shown) ... support on cut shown: F=[1240.51, -899.04, 2148.88] count=5 largest=1.66e+03 reaction=[1240.51, -899.04, 2148.88] tolerance=2.29e-01
ok
test_refused_by_the_manifest (tests.test_solids_e2e.Tie.test_refused_by_the_manifest) ... ok
test_tie_inside_the_selection (tests.test_solids_e2e.Tie.test_tie_inside_the_selection) ... tie inside: count=66 cut=2.05e+03 eF=7.63e-12 eM=2.99e-12 largest=1.78e+03 rest_F=[-0.0, 0.0, -0.0]
ok
test_tie_next_to_the_selection (tests.test_solids_e2e.Tie.test_tie_next_to_the_selection) ... tie beside: count=29 cut=9.26e+02 eF=3.25e-12 eM=4.93e-13 erest_F=3.25e-12 erest_M=2.66e-12 largest=1.78e+03 rest_F=[-2000.0, -500.0, 1006.16] statics=[-2000.0, -500.0, 1006.16] where_x=[0.1]
ok
test_centroid_by_hand_forces_by_statics (tests.test_solids_e2e.TwoMaterials.test_centroid_by_hand_forces_by_statics) ... f_two: count=0 cut=2.11e+03 eF=9.20e-12 eM=5.17e-12 nodes=74 rest=1.33e-09 s=2.70e+00 warn=
centroid f_two group 1: hand=1.50e-02 z=1.50e-02
centroid f_two group 2: hand=1.50e-02 z=1.50e-02
ok
test_props_of_one_material_only (tests.test_solids_e2e.TwoMaterials.test_props_of_one_material_only) ... ok
----------------------------------------------------------------------
Ran 54 tests in 198.045s
OK (skipped=3)
```
