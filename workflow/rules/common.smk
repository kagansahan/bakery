import os
import re
import sys
from decimal import Decimal
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
    """13.0 -> '13p0', 610.0 -> '610p0', 1e-05 -> '0p00001' (never an exponent,
    which the param_pt / sqrts wildcard constraints would not match)"""
    txt = format(Decimal(repr(float(x))), "f")
    if "." not in txt:
        txt += ".0"
    tok = txt.replace(".", "p").replace("-", "m")
    if not re.fullmatch(r"m?[0-9]+p[0-9]+", tok):
        raise ConfigError(f"value {x!r} cannot be used in a file name ({tok!r})")
    return tok


def unfmt(s):
    return float(s.replace("m", "-").replace("p", "."))


# ---------------------------------------------------------------------
# cross-checks the JSON schema cannot express
#
# Two config styles are accepted (see README): the explicit one (parameters
# as names, detsim per recasting entry, Rivet 'routine') and the earlier
# kagan-dev one (parameters as {name, index}, detector chosen through the
# analysis 'experiment', Rivet 'analysis', a 'recasters' on/off list).
# ---------------------------------------------------------------------
def note(msg):
    print(f"[bakery] {msg}", file=sys.stderr)


def param_names(proc):
    """Parameter names of a process, heaviest first.

    The i-th of n values fills M{n-1-i} in the SLHA template. An explicit
    'index' must agree with that, so a point can never silently fill the
    wrong placeholder.
    """
    pars = proc["parameters"]
    names = []
    for i, par in enumerate(pars):
        if isinstance(par, str):
            names.append(par)
            continue
        expected = len(pars) - 1 - i
        if "index" in par and par["index"] != expected:
            raise ConfigError(
                f"process {proc['name']}: parameter {par['name']} has index {par['index']}, "
                f"but as value {i + 1} of {len(pars)} it fills M{expected}; list the "
                "parameters (and the values of every point) heaviest first")
        names.append(par["name"])
    return names


PROCESSES = {p["name"]: dict(p, parameter_names=param_names(p)) for p in config["processes"]}
DETECTORS = {d["name"]: d for d in config.get("detectors", [])}
GENERATORS = [g["name"] for g in config["generators"] if g["enabled"]]
if not GENERATORS:
    raise ConfigError("no generator is enabled")
# no 'recasters' list means every tool is on
TOOLS_ON = ({r["name"] for r in config["recasters"] if r["enabled"]}
            if "recasters" in config else {"cutlang", "rivet"})

SAMPLES = []
for s in config["samples"]:
    if s["process"] not in PROCESSES:
        note(f"WARNING: sample of process '{s['process']}' skipped: "
             "the process is not defined under 'processes'")
        continue
    npar = len(PROCESSES[s["process"]]["parameter_names"])
    for pt in s["points"]:
        if len(pt) != npar:
            raise ConfigError(
                f"point {pt} of {s['process']} has {len(pt)} values, "
                f"the process declares {npar} parameters"
            )
    SAMPLES.append(s)
if not SAMPLES:
    raise ConfigError("no sample refers to a defined process")


def default_detsim(ana, key):
    """Earlier style: the enabled detector whose 'experiment' (or name) is the
    analysis's. None if the matching detectors are all disabled."""
    exp = ana.get("experiment")
    match = [d for d in DETECTORS.values() if exp and d.get("experiment", d["name"]) == exp]
    on = [d["name"] for d in match if d.get("enabled", True)]
    if len(on) == 1:
        return on[0]
    if match and not on:
        return None
    raise ConfigError(
        f"{key}: no detsim given and {len(on)} enabled detectors match experiment {exp!r}; "
        "add 'detsim: <detector name>' to this recasting entry")


RECASTS = {}  # (analysis, tool) -> dict(analysis entry, recasting entry)
SEEN = set()
for ana in config["analyses"]:
    for rc in ana["recasting"]:
        key = (ana["name"], rc["tool"])
        if key in SEEN:
            raise ConfigError(f"{key} is listed twice; one detsim per analysis and tool")
        SEEN.add(key)
        if rc["tool"] not in TOOLS_ON:
            note(f"{key} skipped: recaster '{rc['tool']}' is disabled")
            continue
        rc = dict(rc, config=dict(rc["config"]))
        if rc["tool"] == "rivet":
            rc.setdefault("detsim", "none")
            if rc["detsim"] != "none":
                raise ConfigError(f"{key}: Rivet reads HepMC, detsim must be 'none'")
            if "routine" not in rc["config"] and "analysis" in rc["config"]:
                rc["config"]["routine"] = rc["config"]["analysis"]   # earlier key name
            if "routine" not in rc["config"]:
                raise ConfigError(f"{key}: config.routine (Rivet analysis name) missing")
        if rc["tool"] == "cutlang":
            if "detsim" not in rc:
                rc["detsim"] = default_detsim(ana, key)
                if rc["detsim"] is None:
                    note(f"{key} skipped: every detector of experiment "
                         f"{ana.get('experiment')!r} is disabled")
                    continue
            if rc["detsim"] not in DETECTORS:
                raise ConfigError(
                    f"{key}: detsim '{rc['detsim']}' is not defined under 'detectors'"
                )
            if not DETECTORS[rc["detsim"]].get("enabled", True):
                note(f"{key} skipped: detector '{rc['detsim']}' is disabled")
                continue
            if "adl_file" not in rc["config"]:
                raise ConfigError(f"{key}: config.adl_file missing")
            if MODE == "real" and not os.path.exists(rc["config"]["adl_file"]):
                raise ConfigError(f"{key}: ADL file {rc['config']['adl_file']} not found")
        RECASTS[key] = {"analysis": ana, "recast": rc}

if MODE == "real":
    for name in sorted({r["recast"]["detsim"] for r in RECASTS.values()} - {"none"}):
        if not os.path.exists(DETECTORS[name]["card"]):
            raise ConfigError(f"Delphes card {DETECTORS[name]['card']} not found")


# ---------------------------------------------------------------------
# job list: every (point, generator, analysis, tool) at matching sqrts
# ---------------------------------------------------------------------
POINTS = {}  # (process, param_pt) -> dict
for s in SAMPLES:
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


def card_model(topo):
    """'import model' of a topology's MadGraph process card (None if absent)."""
    card = os.path.join(WRAPPERS, "mg5amcnlo", "data", topo, "proc_card.dat")
    if not os.path.exists(card):
        return None
    with open(card) as f:
        for line in f:
            tok = line.split("#", 1)[0].split()
            if tok[:2] == ["import", "model"] and len(tok) > 2:
                return tok[2]
    return None


def generators_for(topo):
    """Pythia8 standalone can only produce MSSM sparticle pairs."""
    gens = list(GENERATORS)
    if "Pythia8" in gens and not (card_model(topo) or "").startswith("MSSM_SLHA2"):
        note(f"Pythia8 skipped for {topo}: model {card_model(topo)!r} is not MSSM_SLHA2")
        gens.remove("Pythia8")
    return gens


GENS_FOR = {name: generators_for(name) for name in {p["process"] for p in POINTS.values()}}


def jobs():
    for (proc, pt), p in POINTS.items():
        for gen in GENS_FOR[p["process"]]:
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
        if not RECASTS:
            raise ConfigError("the config produces no jobs: every recasting entry is "
                              "skipped (disabled recasters / detectors)")
        if not any(GENS_FOR.values()):
            raise ConfigError("the config produces no jobs: no enabled generator can "
                              "produce the processes")
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
