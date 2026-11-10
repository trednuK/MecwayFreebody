# One run through the real bridge code, without Mecway. As TestFiles/Verificatie/_run_one.py of
# the bridge, plus the step Main does after a run: bridge_manifest.finish_run.
# use: python e9_one.py <bridge> <work> <model.liml> <analysis> <settings.json>
import io, json, os, shutil, subprocess, sys

bridge, work, liml, analysis, cfg_path = sys.argv[1:6]
sys.path.insert(0, os.path.join(bridge, "Scripts"))
cfg = json.load(io.open(cfg_path, encoding="utf-8"))
if os.path.isdir(work):
    shutil.rmtree(work)
os.makedirs(work)
model = os.path.join(work, os.path.basename(liml))
shutil.copy(liml, model)
import bridge_utils as u
u.CONFIG_BRIDGE["work_dir"] = work
u.CONFIG_BRIDGE["language"] = "en"
u.CONFIG_BRIDGE.update(cfg.get("general", {}))
u.CONFIG_BRIDGE["analyses"][analysis].update(cfg.get("settings", {}))
u.CONFIG_BRIDGE["active_analysis"] = analysis
u.set_run_log("20261107_120000", model)
from bridge_from_liml import extract_aster_data_from_liml
from bridge_mesh import write_mesh
from bridge_to_aster import generate_AsterSolver_files
import bridge_manifest

md = extract_aster_data_from_liml(model)
mail = os.path.join(work, u.run_name(".mail"))
if not (md and write_mesh(mail, md)):
    sys.exit("mesh failed")
exp = generate_AsterSolver_files(work, md, mail, u.run_name(".resu"))
if not exp:
    sys.exit("generate failed: see the log")
with open(os.path.join(work, u.run_name("_console.txt")), "w") as f:
    rc = subprocess.call([u.exe_aster_path(), exp], stdout=f, stderr=subprocess.STDOUT,
                         timeout=1500, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
print("run_aster exit", rc)
print("manifest", bridge_manifest.finish_run(work, md, exp, rc == 0))
