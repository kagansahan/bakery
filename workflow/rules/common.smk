import os
import zlib
from snakemake.utils import validate

validate(config, schema=os.path.join(workflow.basedir, "schemas/config.schema.yml"))

MODE = config.get("mode", "real")
# mock and real results never share a directory, so mock files can never be
# mistaken for physics output
RES = config.get("output_root", "results" if MODE == "real" else "results-mock")
LOGS = os.path.join("logs" if MODE == "real" else "logs-mock")
WRAPPERS = os.path.abspath(os.path.join(workflow.basedir, "wrappers"))


def wrapper_path(tool):
    """Real wrapper, or its mock twin when mode == mock."""
    sub = os.path.join("mock", tool) if MODE == "mock" else tool
    return "file://" + os.path.join(WRAPPERS, sub)


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------
# helpers to turn numbers into file-name tokens and back
# ---------------------------------------------------------------------
def fmt(x):
    """13.0 -> '13p0', 610.0 -> '610p0'"""
    return str(float(x)).replace(".", "p").replace("-", "m")


def unfmt(s):
    return float(s.replace("m", "-").replace("p", "."))


# ---------------------------------------------------------------------
# cross-checks the JSON schema cannot express
# ---------------------------------------------------------------------
PROCESSES = {p["name"]: p for p in config["processes"]}
DETECTORS = {d["name"]: d for d in config.get("detectors", [])}
GENERATORS = [g["name"] for g in config["generators"] if g["enabled"]]
if not GENERATORS:
    raise ConfigError("no generator is enabled")

for s in config["samples"]:
    if s["process"] not in PROCESSES:
        raise ConfigError(
            f"sample uses process '{s['process']}' which is not defined under 'processes'"
        )
    npar = len(PROCESSES[s["process"]]["parameters"])
    for pt in s["points"]:
        if len(pt) != npar:
            raise ConfigError(
                f"point {pt} of {s['process']} has {len(pt)} values, "
                f"the process declares {npar} parameters"
            )

RECASTS = {}  # (analysis, tool) -> dict(analysis entry, recasting entry)
for ana in config["analyses"]:
    for rc in ana["recasting"]:
        key = (ana["name"], rc["tool"])
        if key in RECASTS:
            raise ConfigError(f"{key} is listed twice; one detsim per analysis and tool")
        if rc["tool"] == "rivet":
            if rc["detsim"] != "none":
                raise ConfigError(f"{key}: Rivet reads HepMC, detsim must be 'none'")
            if "routine" not in rc["config"]:
                raise ConfigError(f"{key}: config.routine (Rivet analysis name) missing")
        if rc["tool"] == "cutlang":
            if rc["detsim"] not in DETECTORS:
                raise ConfigError(
                    f"{key}: detsim '{rc['detsim']}' is not defined under 'detectors'"
                )
            if "adl_file" not in rc["config"]:
                raise ConfigError(f"{key}: config.adl_file missing")
            if MODE == "real" and not os.path.exists(rc["config"]["adl_file"]):
                raise ConfigError(f"{key}: ADL file {rc['config']['adl_file']} not found")
        RECASTS[key] = {"analysis": ana, "recast": rc}

if MODE == "real":
    for d in DETECTORS.values():
        if not os.path.exists(d["card"]):
            raise ConfigError(f"Delphes card {d['card']} not found")


# ---------------------------------------------------------------------
# job list: every (point, generator, analysis, tool) at matching sqrts
# ---------------------------------------------------------------------
POINTS = {}  # (process, param_pt) -> dict
for s in config["samples"]:
    proc = PROCESSES[s["process"]]
    for pt in s["points"]:
        key = (proc["name"], "_".join(fmt(v) for v in pt))
        POINTS[key] = {
            "process": proc["name"],
            "sqrts": fmt(proc["sqrts"]),
            "sqrts_val": float(proc["sqrts"]),
            "masses": [float(v) for v in pt],
            "nevents": s["nevents"],
            "extrajet": proc.get("extrajet", 0),
        }


def jobs():
    for (proc, pt), p in POINTS.items():
        for gen in GENERATORS:
            for (ana, tool), r in RECASTS.items():
                if float(r["analysis"]["sqrts"]) != p["sqrts_val"]:
                    continue
                yield dict(p, param_pt=pt, generator=gen, analysis=ana, tool=tool,
                           detsim=r["recast"]["detsim"])


def final_targets():
    out = set()
    for j in jobs():
        out.add(
            f"{RES}/{j['sqrts']}/embaked/{j['analysis']}.{j['process']}."
            f"{j['generator']}.{j['tool']}.embaked"
        )
    if not out:
        raise ConfigError("the config produces no jobs (check sqrts of processes and analyses)")
    return sorted(out)


# ---------------------------------------------------------------------
# lookups used by rules
# ---------------------------------------------------------------------
def point(w):
    return POINTS[(w.process, w.param_pt)]


def recast(w, tool):
    return RECASTS[(w.analysis, tool)]


def seed(w):
    """Reproducible MG5 seed per point (1..30081 is MG5's allowed range)."""
    return zlib.crc32(f"{w.process}_{w.param_pt}_{w.generator}".encode()) % 30000 + 1


def rivet_routines(w):
    """All Rivet routines needed for this sqrts, run in one pass over the HepMC."""
    sq = unfmt(w.sqrts)
    return sorted({r["recast"]["config"]["routine"] for (a, t), r in RECASTS.items()
                   if t == "rivet" and float(r["analysis"]["sqrts"]) == sq})


wildcard_constraints:
    sqrts="[0-9p]+",
    process="[A-Za-z0-9_]+",
    param_pt="[0-9pm_]+",
    generator="|".join(GENERATORS),
    analysis="[A-Za-z0-9-]+",
    detsim="[A-Za-z0-9-]+",
    tool="cutlang|rivet",
