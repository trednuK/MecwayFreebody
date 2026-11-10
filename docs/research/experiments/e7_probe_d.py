# E7 route D, first probe: what do the elementary vectors look like in the Python API?
from e7_routes import *

PROBE = r'''
import importlib
CA = importlib.import_module('code_aster.CA')
pb = CA.PhysicalProblem(model, cm)
for ch in (bc, tip, top, grav):
    pb.addLoad(ch)
pb.computeListOfLoads()
pb.computeDOFNumbering()
dc = CA.DiscreteComputation(pb)
sig = res.getField("SIEF_ELGA", 1)
u = res.getField("DEPL", 1)
print("DOC", dc.getMechanicalNodalForces.__doc__)
lap("x")
v = dc.getMechanicalNodalForces(sig, u, assembly=False)
print("TYPE", type(v))
tt = v.getElementaryTerms()
print("TERMS", len(tt), [type(q) for q in tt])
t = tt[0]
print("OPT", t.getOption(), t.getLocalMode(), t.getPhysicalQuantity())
c = t.getValues()
print("COLL", type(c), [a for a in dir(c) if not a.startswith("_")])
try:
    print("N", len(c))
    print("FIRST", type(c[1]), len(c[1]))
except Exception as e:
    print("EXC", e)
d = t.getFiniteElementDescriptor()
print("FED", [a for a in dir(d) if not a.startswith("_")])
for n in ("getListOfGroupsOfElements", "getListOfGroupsOfElementsbyElement", "getPhysics", "getModel"):
    if hasattr(d, n):
        try:
            q = getattr(d, n)()
            print(n, type(q), (q if not hasattr(q, "__len__") or len(q) < 8 else (len(q), q[0])))
        except Exception as e:
            print(n, "EXC", e)
lap("y")
v2 = dc.getMechanicalVolumetricForces(assembly=False)
print("VOL", [ (q.getOption(), q.getLocalMode()) for q in v2.getElementaryTerms()])
v3 = dc.getMechanicalNeumannForces(assembly=False)
print("NEU", [ (q.getOption(), q.getLocalMode()) for q in v3.getElementaryTerms()])
'''

c = block_case("d_p", "HEXA20", (4, 2, 2))
c2 = comm_first(c, "P")
c2 = c2.replace(chr(10)+"finish()"+chr(10), chr(10)+PROBE+chr(10)+"finish()"+chr(10))
m = c["mesh"]; m.free_ma = ("S", "S_SK"); m.free_no = ("CUTA", "CUTB")
write_mail(os.path.join(WD, "d_p.mail"), m)
r = run_aster("d_p", c2, mail="d_p.mail")
print(r["errors"], r["rc"])
mess = open(os.path.join(WD, "d_p.mess"), encoding="utf-8", errors="replace").read()
i = mess.find("DOC ")
print(mess[i:i+6000].encode("ascii", "replace").decode())
log = r.get("rc")
