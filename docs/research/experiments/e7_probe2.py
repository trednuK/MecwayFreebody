# E7 probe: plastic zone report on the small tet10 model, route A only.
from e7_nl import *
c = nl_block("n_t10p", "TETRA10", (10, 2, 4))
rows, info = run_routes(c, routes=("A",))
summary(rows)
print(info["A"]["err"], info["A"].get("plast"))
