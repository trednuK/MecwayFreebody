# E6 case 2: M4 and M4L (and M3 with own shape functions) on wedges, pyramids and mixed
# meshes, two cuts, exact statics. Straight and distorted. Block as in E1, clamped at x=0.
# Run: python e6_solid.py [filter words]
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *

os.makedirs(WD, exist_ok=True)
FILTER = sys.argv[1:]
DIST = .3
OUT = "e6_solid_"+FILTER[0] if FILTER else "e6_solid"


def wanted(*w):
    return not FILTER or any(any(f in q for q in w) for f in FILTER)


if __name__ == "__main__":
    for code in ("wedge6y", "wedge15y", "wedge6x", "wedge15x", "pyr5", "pyr13", "hp8", "hp20"):
        for n, label in ((1, "grid"),):
            for dist in (0., DIST):
                case = "w2_%s%s" % (label, "_dist" if dist else "")
                if not wanted(code, case):
                    continue
                M = block(code, n, dist); block_loads(M)
                nx = M.dims[0]
                S = [e for e, c in M.cell.items() if nx//4 <= c[0] < 3*nx//4]
                run_case(M, S, case, code, m3=m3_nodal)
                save_results(OUT)
    # finer pyramid mesh: more than one element across the width
    for code in ("wedge6y", "pyr5", "pyr13"):
        if wanted(code, "fine"):
            M = block(code, 2, DIST); block_loads(M)
            nx = M.dims[0]
            S = [e for e, c in M.cell.items() if nx//4 <= c[0] < 3*nx//4]
            run_case(M, S, "w2_fine_dist", code, m3=m3_nodal)
            save_results(OUT)
    # meshes made by Mecway's refine_x2: real transition elements, stair-shaped cuts through them
    for base in ("hex8", "hex20"):
        for region in ("sec", "corner"):
            case = "w2_refine_%s" % region
            if not wanted(base, case, "refine"):
                continue
            try:
                M = refined_block(base, region, "ref_%s_%s" % (base, region))
            except Exception as ex:
                fail(case, base, "refine", ex)
                continue
            block_loads(M)
            # second window: the cut runs through the pyramids and tets of the transition
            for label, (x1, x2) in (("", (.05, .15)), ("_trans", (.045, .155))):
                if region == "corner" and label:
                    continue
                S = select_x(M, x1, x2)
                parts, layer, cut = analyse(M, S)
                cnt = {}
                for e in layer:
                    cnt[M.m.elems[e][0]] = cnt.get(M.m.elems[e][0], 0)+1
                print("  layer holds", cnt, flush=True)
                run_case(M, S, case+label, base+"mix", m3=m3_nodal)
                save_results(OUT)
