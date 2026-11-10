# E6 case 1: M4 and M4L on shells and beams, two cuts, exact statics. All layer nodes held
# in displacement and rotation. Flat, folded along an element edge, turned in 3D, curved.
# Run: python e6_shell.py [filter words]
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e6_mesh import *

os.makedirs(WD, exist_ok=True)
FILTER = sys.argv[1:]
R3 = rotation()
SHAPES = ("quad4", "quad8", "tri3", "tri6")
NEG = (("noRot", dict(rotdirs="")), ("twoRot", dict(rotdirs="xy")))


def wanted(*w):
    return not FILTER or any(any(f in q for q in w) for f in FILTER)


def load_shell(M):
    M.loads.append(dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)))
    M.loads.append(dict(type="nforce", nodes=M.corner, F=(40., 0., 150.)))
    M.loads.append(dict(type="gravity", g=g_oblique))


def load_couple(M):
    """Pure couples at the tip: in the cut only a moment. A nodal moment in the plane of the
    tip, and a pair of forces. Makes the reaction-moment share visible."""
    t1, t2 = tip_axes(M)
    M.loads.append(dict(type="nmoment", nodes=M.tip, M=tuple(2.*t1+3.*t2)))
    n = np.cross(t1, t2)
    M.loads.append(dict(type="nforce", nodes=M.corner, F=tuple(100.*n)))
    M.loads.append(dict(type="nforce", nodes=M.corner2, F=tuple(-100.*n)))


def select(M, a, b):
    return [e for e, i in M.par.items() if a <= i < b]


GEO = [("flat", m_flat), ("flat_turned", turned(m_flat, R3)), ("flat_skew", m_skew()),
       ("fold90", m_fold(90)), ("fold60", m_fold(60)),
       ("fold90_turned", turned(m_fold(90), R3)), ("fold60_turned", turned(m_fold(60), R3)),
       ("arc", m_arc()), ("arc_turned", turned(m_arc(), R3))]

if __name__ == "__main__":
    for sh in SHAPES:
        for name, fn in GEO:
            if wanted(sh, name):
                M = strip(sh, mapfn=fn); load_shell(M)
                run_case(M, select(M, 5, 15), "s1_"+name, sh, negatives=NEG if name in ("fold60_turned",) else ())
            save_results("e6_shell")
        # the cut exactly on the fold line: the rotation there belongs to both legs
        for name, fn in (("foldcut90", m_fold(90)), ("foldcut60_turned", turned(m_fold(60), R3))):
            if wanted(sh, name):
                M = strip(sh, mapfn=fn); load_shell(M)
                run_case(M, select(M, 10, 15), "s1_"+name, sh)
        # pure couples
        for name, fn in (("flat", turned(m_flat, R3)), ("fold60", turned(m_fold(60), R3))):
            if wanted(sh, name, "couple"):
                M = strip(sh, mapfn=fn); load_couple(M)
                run_case(M, select(M, 5, 15), "s1_couple_"+name, sh)
        save_results("e6_shell")
    if wanted("line2", "beam"):
        for name, fn in (("beam", m_flat), ("beam_turned", turned(m_flat, R3)), ("frame", turned(m_fold(60), R3))):
            M = beam(mapfn=fn)
            M.loads += [dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)),
                        dict(type="nmoment", nodes=M.tip, M=(4., -3., 2.)),
                        dict(type="gravity", g=g_oblique)]
            S = [e for e, i in M.par.items() if 5 <= i < 15]
            run_case(M, S, "b1_"+name, "line2", negatives=(("noRot", dict(rotdirs="")),) if name == "frame" else ())
            M = beam(mapfn=fn)
            M.loads.append(dict(type="nmoment", nodes=M.tip, M=(4., -3., 2.)))
            run_case(M, [e for e, i in M.par.items() if 5 <= i < 15], "b1_couple_"+name, "line2")
        M = beam_tee(Rm=R3)
        M.loads += [dict(type="nforce", nodes=M.tip, F=(300., 200., -100.)),
                    dict(type="nforce", nodes=M.tip2, F=(-50., 100., 80.)),
                    dict(type="nmoment", nodes=M.tip2, M=(1., 2., -1.)),
                    dict(type="gravity", g=g_oblique)]
        run_case(M, M.S, "b1_tee3cuts", "line2")
        save_results("e6_shell")
