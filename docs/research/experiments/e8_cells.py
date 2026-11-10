# E8 probe 1, mesh only: where does a bridge cell land after CREA_MAILLAGE, read in a POURSUITE?
# Own mesh in bridge style (e8_lib.bridge_mail); every cell is checked on its corner coordinates.
# Run: python e8_cells.py [filter]
from e8_lib import *

HC = HEX20C
CORNERS = {"HEXA8": 8, "HEXA20": 8, "PENTA6": 6, "TETRA4": 4, "QUAD4": 4, "QUAD8": 4, "TRIA3": 3, "TRIA6": 3,
           "SEG2": 2, "POI1": 1}
EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7), (4, 5), (5, 6), (6, 7), (7, 4))


def lattice(mix, n=(6, 3, 3), h=.01):
    """Cells on a lattice, one type per lattice box in turn, shared nodes."""
    m = Mesh(); m.parent = {}
    q = 0

    def mid(a, b):
        A, B = m.xyz[a-1], m.xyz[b-1]
        return m.node((A[0]+B[0])/2, (A[1]+B[1])/2, (A[2]+B[2])/2)
    for i in range(n[0]):
        for j in range(n[1]):
            for k in range(n[2]):
                t = mix[q % len(mix)]; q += 1
                c = [m.node(h*(i+(a+1)/2), h*(j+(b+1)/2), h*(k+(d+1)/2)) for a, b, d in HC[:8]]
                if t in ("HEXA8", "HEXA20"):
                    nd = c if t == "HEXA8" else c+[mid(c[a], c[b]) for a, b in EDGES]
                elif t == "PENTA6":
                    nd = [c[0], c[1], c[2], c[4], c[5], c[6]]
                elif t == "TETRA4":
                    nd = [c[0], c[1], c[2], c[4]]
                elif t in ("QUAD4", "QUAD8"):
                    nd = c[:4]
                    if t == "QUAD8":
                        nd = nd+[mid(nd[a], nd[(a+1) % 4]) for a in range(4)]
                elif t in ("TRIA3", "TRIA6"):
                    nd = c[:3]
                    if t == "TRIA6":
                        nd = nd+[mid(nd[a], nd[(a+1) % 3]) for a in range(3)]
                elif t == "SEG2":
                    nd = c[:2]
                else:
                    nd = c[:1]
                m.add(t, nd, 0)
    return m


V8 = ["HEXA8", "TETRA4", "QUAD4", "PENTA6", "TRIA3", "SEG2", "POI1"]
VARS = {
    # name: cell mix, CREA_MAILLAGE text
    "v2_mix_tout": (V8, "mesh = CREA_MAILLAGE(MAILLAGE=mesh, LINE_QUAD=_F(TOUT='OUI'))"),
    "v3_mix_part": (V8, "_g = _bridge_lq_groups(mesh, ('E_HEXA8', 'E_TETRA4', 'E_PENTA6'))\n"
                        "mesh = CREA_MAILLAGE(MAILLAGE=mesh, LINE_QUAD=_F(GROUP_MA=_g))"),
    "v4_q8_tout": (["QUAD8", "TRIA6"], "mesh = CREA_MAILLAGE(MAILLAGE=mesh, MODI_MAILLE=(\n"
                   "  _F(GROUP_MA='E_QUAD8', OPTION='QUAD8_9'), _F(GROUP_MA='E_TRIA6', OPTION='TRIA6_7')))"),
    "v5_mixed_q": (["HEXA20", "QUAD8", "TRIA6", "QUAD8", "SEG2"], "mesh = CREA_MAILLAGE(MAILLAGE=mesh, MODI_MAILLE=(\n"
                   "  _F(GROUP_MA='E_QUAD8', OPTION='QUAD8_9'), _F(GROUP_MA='E_TRIA6', OPTION='TRIA6_7')))"),
    "v6_q4_lq_q9": (["QUAD4", "TRIA3"], "mesh = CREA_MAILLAGE(MAILLAGE=mesh, LINE_QUAD=_F(TOUT='OUI'))\n"
                    "mesh = CREA_MAILLAGE(MAILLAGE=mesh, MODI_MAILLE=(\n"
                    "  _F(GROUP_MA='E_QUAD4', OPTION='QUAD8_9'), _F(GROUP_MA='E_TRIA3', OPTION='TRIA6_7')))"),
    "v7_none": (V8, "pass"),
}

FIRST = """DEBUT(LANG='EN')
def _bridge_lq_groups(mesh, groups):
    conn = mesh.getConnectivity()
    nodes = set()
    for g in groups:
        for c in mesh.getCells(g):
            nodes.update(conn[c])
    out = list(groups)
    for g in mesh.getGroupsOfCells():
        cells = mesh.getCells(g)
        if g not in out and len(cells) and all(set(conn[c]) <= nodes for c in cells):
            out.append(g)
    return tuple(out)
mesh = LIRE_MAILLAGE(UNITE=20, FORMAT='ASTER')
mesh = DEFI_GROUP(reuse=mesh, MAILLAGE=mesh, CREA_GROUP_MA=_F(NOM='all_elems', TOUT='OUI'),
                  CREA_GROUP_NO=_F(NOM='all_nodes', GROUP_MA='all_elems'))
%s
FIN()
"""

SECOND = r"""POURSUITE(LANG='EN')
""" + HELP8 + r"""
sel = json.load(open("fort.32"))
M = mesh
OUT["nodes"] = M.getNumberOfNodes(); OUT["cells"] = M.getNumberOfCells()
OUT["celltypes"] = [M.getCellTypeName(i) for i in range(M.getNumberOfCells())]
dump_mesh(M)
# 1. DEFI_GROUP with the file position as 'M<pos>'
M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_MA=_F(NOM='G_POS', MAILLE=tuple("M%d" % i for i in sel["pos"])))
OUT["G_POS"] = [int(i) for i in M.getCells('G_POS')]
# 2. the same from a list of 0-based ids
M.setGroupOfCells('G_IDS', [i-1 for i in sel["pos"]])
OUT["G_IDS"] = [int(i) for i in M.getCells('G_IDS')]
# 3. groups of the first run
OUT["E_all"] = {g: [int(i) for i in M.getCells(g)] for g in M.getGroupsOfCells() if g.startswith("E_")}
# negative controls: bridge names used as if they were kept
try:
    M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_MA=_F(NOM='G_EID', MAILLE=tuple(sel["names_in"])))
    OUT["G_EID"] = [int(i) for i in M.getCells('G_EID')]
except Exception as e:
    OUT["G_EID_err"] = str(e)[:200]
try:
    M = DEFI_GROUP(reuse=M, MAILLAGE=M, CREA_GROUP_MA=_F(NOM='G_OUT', MAILLE=tuple(sel["names_out"])))
    OUT["G_OUT"] = [int(i) for i in M.getCells('G_OUT')]
except Exception as e:
    OUT["G_OUT_err"] = str(e)[:300]
finish()
FIN()
"""


def check(tag, m, r, pos, ineid):
    """All cells: corners at the expected position? Returns counts."""
    a = r["npz"]; d = r["data"]
    xyz = a["xyz"]; clen = a["clen"]; conn = a["conn"]
    start = np.concatenate(([0], np.cumsum(clen)))
    delta = 0 if conn.min() == 0 else 1
    X = m.X()
    bad = 0; first = None
    types = collections.Counter()
    for p in range(1, len(m.cells)+1):
        c = m.cid[p]; t, nds = m.cells[c-1]
        nc = CORNERS[t]
        got = conn[start[p-1]:start[p]]-delta
        if np.abs(xyz[got[:nc]]-X[np.array(nds[:nc])-1]).max() > 1e-12:
            bad += 1
            first = first or (p, t)
        types["%s>%s" % (t, d["celltypes"][p-1])] += 1
    want = sorted(i-1 for i in pos)
    e_ok = all(sorted(m.pos[c]-1 for c in ids) == d["E_all"].get(g) for g, ids in m.ma.items())
    return dict(tag=tag, delta=delta, nn0=len(X), nn=d["nodes"], nc0=len(m.cells), nc=d["cells"], bad=bad, first=first,
                first_nodes_kept=float(np.abs(xyz[:len(X)]-X).max()), types=dict(types),
                pos_ok=d["G_POS"] == want, ids_ok=d["G_IDS"] == want, e_groups_ok=e_ok,
                g_eid=d.get("G_EID_err") or ("silent, %d of %d are the named cells" % (
                    len(set(d["G_EID"]) & set(ineid)), len(ineid)) if "G_EID" in d else None),
                g_out=d.get("G_OUT_err") or d.get("G_OUT"))


def one(name):
    mix, cm = VARS[name]
    m = lattice(mix)
    for t in set(c[0] for c in m.cells):
        m.ma["E_"+t] = [i+1 for i, c in enumerate(m.cells) if c[0] == t]
    bridge_mail(os.path.join(WD8, "c_%s.mail" % name), m, offset=0)
    rng = np.random.default_rng(1)
    pos = sorted(int(i) for i in rng.choice(len(m.cells), size=len(m.cells)//3, replace=False)+1)
    nums = [(n, int(n[1:])) for n in m.names if n[0] == "M"]
    inr = [n for n, k in nums if k <= len(m.cells)]
    outr = [n for n, k in nums if k > len(m.cells)][:3]
    ineid = [m.names.index(n) for n in inr]     # 0-based position of the cell with that name
    json.dump(dict(pos=pos, names_in=inr, names_out=outr), open(os.path.join(WD8, "c_%s_sel.json" % name), "w"))
    b = "c_%s_base" % name
    r1 = arun("c_%s_1" % name, FIRST % cm, mail="c_%s.mail" % name, base_out=b, mem=1024, ncpus=1)
    if not r1["ok"]:
        print(name, "first run failed", r1["errors"], r1["rc"]); return None
    r2 = arun("c_%s_2" % name, SECOND, sel="c_%s_sel.json" % name, base_in=b, mem=1024, ncpus=1)
    print(name, "POURSUITE ok", r2["ok"], r2["errors"], r2["alarms"], flush=True)
    if not r2["data"]:
        return None
    c = check(name, m, r2, pos, ineid)
    print(json.dumps(c), flush=True)
    rm(b)
    return c


def neg_k():
    """Negative control: a skin name K<n> in MAILLE. Whole process may die, so a run of its own."""
    m = lattice(["HEXA8", "QUAD4"])
    bridge_mail(os.path.join(WD8, "c_k.mail"), m)
    r1 = arun("c_k_1", FIRST % "pass", mail="c_k.mail", base_out="c_k_base", mem=1024, ncpus=1)
    r2 = arun("c_k_2", "POURSUITE(LANG='EN')\nmesh = DEFI_GROUP(reuse=mesh, MAILLAGE=mesh, CREA_GROUP_MA=_F(NOM='G', MAILLE=('K5',)))\n"
              "print('AFTER', mesh.getCells('G'))\nFIN()\n", base_in="c_k_base", mem=1024, ncpus=1)
    hits = [q.strip()[:120] for q in r2["log"].splitlines() if "Bad integer" in q or "AFTER" in q or "runtime error" in q]
    print("K5: first ok", r1["ok"], "second ok", r2["ok"], "rc", r2["rc"], hits[:4], r2["errors"][:3], flush=True)
    rm("c_k_base")


if __name__ == "__main__":
    flt = sys.argv[1:]
    if "neg" in flt:
        neg_k(); sys.exit()
    for n in VARS:
        if not flt or n in flt:
            one(n)
