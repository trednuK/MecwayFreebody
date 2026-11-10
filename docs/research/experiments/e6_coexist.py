# E6: hidden solves next to a visible Mecway. Same case three ways: alone, next to a visible
# Mecway, and two hidden solves at the same moment next to it. The numbers must be identical.
# A foreign Mecway is used as it is and never touched. Only when none runs, one is started
# here with a small self-made model; only that process is stopped again.
import os, sys, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *
from e6_shell import turned, R3, select, load_shell

os.makedirs(WD, exist_ok=True)


def case(tag):
    M = strip("quad8", mapfn=turned(m_fold(60), R3)); load_shell(M)
    S = select(M, 5, 15)
    r, g, sol = solve_main(M, tag)
    parts, layer, cut = analyse(M, S)
    R = sub_solve(M, layer, M.nodes_of(layer), r, tag, "m4l", exclude=cut)
    return np.concatenate([np.concatenate(cut_wrench(M, p, R)[:2]) for p in parts])


foreign = other_mecways()
print("other Mecway at start:", foreign, flush=True)
solo = case("cx_solo") if not foreign else None
own = None
if not foreign:
    M = strip("quad4", nu=4, nv=2)
    d = os.path.join(WD, "cx_visible_model"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "visible.liml"); M.write(p)
    own = subprocess.Popen([MECWAY, p])
    for i in range(300):
        w = own_windows(own.pid)
        if w:
            break
        time.sleep(.1)
    print("visible Mecway pid", own.pid, "windows", [q[0] for q in own_windows(own.pid)], flush=True)
    time.sleep(2)
try:
    near = case("cx_near")
    out = {}
    th = [threading.Thread(target=lambda k=k: out.__setitem__(k, case("cx_par%d" % k))) for k in (1, 2)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    ref = solo if solo is not None else near
    print("max difference next to visible Mecway vs reference: %.3e" % np.abs(near-ref).max())
    print("max difference two at once, vs reference: %.3e %.3e" % (np.abs(out[1]-ref).max(), np.abs(out[2]-ref).max()))
    print("scale of the values: %.3e" % np.abs(ref).max())
finally:
    if own is not None:
        print("visible Mecway still alive:", own.poll() is None, "windows", [q for q in own_windows(own.pid)], flush=True)
        own.kill()
print("Mecway left:", other_mecways())
