# Experiment E8: helpers for the probes on POURSUITE after CREA_MAILLAGE and on CALC_CHAMP without
# EXCIT. Research code, not the product. Self-made models only. Reuses the statics of E7.
import collections, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e7_lib
from e7_lib import *

WD8 = os.path.join(ROOT, "WorkDir", "exp8")
e7_lib.WD = WD8
os.makedirs(WD8, exist_ok=True)


def tree_rss(p):
    """Resident memory of a process and its children, bytes; 0 if it has gone."""
    import psutil
    try:
        ps = [p]+p.children(recursive=True)
    except psutil.Error:
        return 0
    t = 0
    for q in ps:
        try:
            t += q.memory_info().rss
        except psutil.Error:
            pass
    return t


def tmp_size(before):
    """Bytes in run_aster work folders that did not exist at the start."""
    t = 0
    root = tempfile.gettempdir()
    for d in os.listdir(root):
        if d.startswith("run_aster_") and d not in before:
            for w, _, fs in os.walk(os.path.join(root, d)):
                for f in fs:
                    try:
                        t += os.path.getsize(os.path.join(w, f))
                    except OSError:
                        pass
    return t


def arun(tag, comm, mail=None, sel=None, base_out=None, base_in=None, base_inout=None, mem=4000, ncpus=2,
         tlim=2400, wd=None, poll=False):
    """Run in the folder wd with relative names. base_out: `R base x R 0`, base_in: `R base x D 0`,
    base_inout: `R base x DR 0`. poll: also the peak memory of the process tree (OS view) and
    of the run_aster work folders. Returns wall, status, message counts, json and npz."""
    import psutil
    wd = wd or WD8
    os.makedirs(wd, exist_ok=True)
    comm = re.sub(r"np\.float64\(([^)]*)\)", r"\1", comm)       # repr of numpy 2 in E7 model text
    open(os.path.join(wd, tag+".comm"), "w", newline="\n").write(comm)
    x = ["P time_limit %d" % tlim, "P memory_limit %d" % mem, "P mpi_nbcpu 1", "P ncpus %d" % ncpus,
         "F comm %s.comm D 1" % tag, "F mess %s.mess R 6" % tag, "F libr %s.json R 33" % tag,
         "F libr %s.npz R 34" % tag]
    if mail:
        x.append("F mail %s D 20" % mail)
    if sel:
        x.append("F libr %s D 32" % sel)
    if base_out:
        os.makedirs(os.path.join(wd, base_out), exist_ok=True)
        x.append("R base %s R 0" % base_out)
    if base_in:
        x.append("R base %s D 0" % base_in)
    if base_inout:
        x.append("R base %s DR 0" % base_inout)
    open(os.path.join(wd, tag+".export"), "w", newline="\n").write("\n".join(x)+"\n")
    for suf in (".json", ".npz", ".mess"):
        p = os.path.join(wd, tag+suf)
        if os.path.exists(p):
            os.remove(p)
    before = set(os.listdir(tempfile.gettempdir()))
    t0 = time.perf_counter(); wall0 = time.time()
    pr = subprocess.Popen(["cmd", "/c", RUN_ASTER, tag+".export"], cwd=wd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    buf = []
    th = threading.Thread(target=lambda: buf.append(pr.stdout.read()))
    th.start()
    peak = peakd = 0
    if poll:
        ps = psutil.Process(pr.pid)
        while pr.poll() is None:
            peak = max(peak, tree_rss(ps))
            peakd = max(peakd, tmp_size(before))
            time.sleep(.2)
    rc = pr.wait(); th.join()
    wall = time.perf_counter()-t0
    log = buf[0].decode("utf-8", "replace")
    open(os.path.join(wd, tag+".log"), "w", encoding="utf-8").write(log)
    mess = ""
    p = os.path.join(wd, tag+".mess")
    if os.path.exists(p):
        mess = open(p, encoding="utf-8", errors="replace").read()
    errs = [ln.encode("ascii", "replace").decode().strip("? ") for ln in mess.splitlines()
            if "<F>" in ln or "<EXCEPTION>" in ln or "<S>" in ln or "<E>" in ln][:6]
    alarms = collections.Counter(re.findall(r"<A> <([A-Za-z0-9_]+)>", mess))
    mm = [[float(q) for q in g] for g in re.findall(r"\(Mo\) :\s+([\d.]+) /\s+([\d.]+) /\s+([\d.]+) /\s+([\d.]+)", mess)]
    out = dict(tag=tag, wall=wall, start=wall0, end=wall0+wall, rc=rc, errors=errs, alarms=dict(alarms),
               ok=(rc == 0 and not errs), peak_MB=peak/1e6, peak_tmp_MB=peakd/1e6, log=log,
               vmpeak=max((q[0] for q in mm), default=None), optimum=max((q[2] for q in mm), default=None),
               minimum=max((q[3] for q in mm), default=None))
    jp = os.path.join(wd, tag+".json")
    out["data"] = json.load(open(jp)) if os.path.exists(jp) and os.path.getsize(jp) else None
    np_ = os.path.join(wd, tag+".npz")
    out["npz"] = dict(np.load(np_)) if os.path.exists(np_) and os.path.getsize(np_) else None
    return out


def _wrap(items):
    out = []; line = items[0]
    for q in items[1:]:
        if len(line)+len(q)+1 > 78:
            out.append(line); line = " "
        line += " "+q
    out.append(line)
    return out


def bridge_mail(path, m, seed=8, offset=1000, node_off=5000, free=()):
    """Mesh file as bridge_mesh.write_mesh does it: cells in blocks per type (first seen first), the
    elements in the order of a shuffled model, then the skin cells K<n>; cell names M<eid> with
    gaps. Groups name cells by name. Sets m.pos {cell id: position, 1-based}, m.cid, m.names."""
    rng = np.random.default_rng(seed)
    el = [c for c in range(1, len(m.cells)+1) if c in m.region]
    sk = [c for c in range(1, len(m.cells)+1) if c not in m.region]
    order = rng.permutation(len(el))
    eids = offset+1+rng.permutation(2*len(el))[:len(el)]
    by_type = collections.OrderedDict(); names = {}
    for i in order:
        c = el[i]; names[c] = "M%d" % eids[i]
        by_type.setdefault(m.cells[c-1][0], []).append(c)
    for n, c in enumerate(sk):
        names[c] = "K%d" % (n+1)
        by_type.setdefault(m.cells[c-1][0], []).append(c)
    L_ = ["TITRE", "e8 self-made model", "FINSF", "COOR_3D"]
    for i, (x, y, z) in enumerate(m.xyz):
        L_.append("N%d %.17g %.17g %.17g" % (i+1+node_off, x, y, z))
    L_.append("FINSF")
    m.pos = {}; m.cid = {}; m.names = []
    for t, cs in by_type.items():
        L_.append(t)
        for c in cs:
            L_ += _wrap([names[c]]+["N%d" % (q+node_off) for q in m.cells[c-1][1]])
            m.names.append(names[c]); m.pos[c] = len(m.names); m.cid[len(m.names)] = c
        L_.append("FINSF")
    for n, ids in m.ma.items():
        if ids and n not in free:
            L_ += ["GROUP_MA", n]+_wrap([""]+[names[c] for c in ids])+["FINSF"]
    for n, ids in m.no.items():
        if ids and n not in free:
            L_ += ["GROUP_NO", n]+_wrap([""]+["N%d" % (q+node_off) for q in ids])+["FINSF"]
    L_.append("FIN")
    open(path, "w", newline="\n").write("\n".join(L_)+"\n")
    return m


def base_state(d):
    """{file: (size, mtime_ns, sha256)} of a base folder."""
    out = {}
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f); h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 22), b""):
                h.update(b)
        st = os.stat(p)
        out[f] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    return out


def base_MB(d):
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))/1e6


def rm(*names):
    for n in names:
        shutil.rmtree(os.path.join(WD8, n), ignore_errors=True)


# Python blocks for the follow-up run. Positions in the JSON are 1-based file positions.
HELP8 = HELP+r'''
def dump_mesh(M):
    n = M.getNumberOfCells()
    con = M.getConnectivity()
    ARR["xyz"] = np.asarray(M.getCoordinates().getValues(), dtype=float).reshape(-1, 3)
    ARR["clen"] = np.array([len(c) for c in con])
    ARR["conn"] = np.array([q for c in con for q in c])
def stored_loads(R, k):
    ll = R.getListOfLoads(k)
    d = dict(names=[str(x) for x in ll.getLoadNames()])
    for key, fn in (("real", "getMechanicalLoadsReal"), ("func", "getMechanicalLoadsFunction"), ("dbc", "getDirichletBCs")):
        try:
            d[key] = [q.userName for q in getattr(ll, fn)()]
        except Exception as e:
            d[key] = "ERR "+str(e)[:80]
    return d
'''
