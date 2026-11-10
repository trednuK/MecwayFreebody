# E7 model 1: linear solids, straight and distorted, plus a mixed mesh with interleaved cells.
# Run: python e7_solid.py [filter]
import concurrent.futures as cf
from e7_routes import *

CASES = [("h20", "HEXA20", (10, 2, 4), 0.), ("h20d", "HEXA20", (10, 2, 4), .15), ("h20m", "HEXA20", (20, 4, 8), .3),
         ("t10", "TETRA10", (10, 2, 4), 0.), ("t10d", "TETRA10", (10, 2, 4), .15),
         ("h8", "HEXA8", (20, 4, 8), 0.), ("h8d", "HEXA8", (20, 4, 8), .3),
         ("mix", "MIX", (10, 2, 4), 0.), ("mixd", "MIX", (10, 2, 4), .15)]


def one(a):
    tag, sh, dims, dist = a
    c = block_case("s_"+tag, sh, dims, dist)
    rows, info = run_routes(c)
    return rows, info


if __name__ == "__main__":
    flt = sys.argv[1:]
    todo = [a for a in CASES if not flt or a[0] in flt]
    all_r = []; infos = []
    with cf.ThreadPoolExecutor(4) as ex:
        for rows, info in ex.map(one, todo):
            show(rows); all_r += rows; infos.append(info)
            print(info["case"], {k: info[k]["err"] for k in ("A", "P", "B", "B0", "Bm", "C") if k in info})
    json.dump(dict(rows=all_r, info=infos), open(os.path.join(WD, "res_solid.json"), "w"))
