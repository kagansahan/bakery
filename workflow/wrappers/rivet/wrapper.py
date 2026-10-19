"""Snakemake wrapper: analyses HepMC(.gz) events with Rivet -> YODA(.gz).

Rule side (example):
    input:  hepmc=P_GEN_HEPMC
    output: yoda=P_RIVET_YODA                 # .yoda or .yoda.gz
    log:    P_LOG_RECAST                      # wrapper messages + rivet stdout/stderr
    params:
        analysis=...        # required: one Rivet routine, e.g. "ATLAS_2019_I1718132"
#        analysis_path=...   # optional: folder with compiled Rivet*.so (RIVET_ANALYSIS_PATH)
"""
import atexit
import gzip
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# --------------------------------------------------------------------------------------------------
# Log: the wrapper's own messages and rivet's stdout/stderr go to the same file
# --------------------------------------------------------------------------------------------------
log_file = Path(str(snakemake.log[0])) if len(snakemake.log) else None
if log_file:
    log_file.parent.mkdir(parents=True, exist_ok=True)
log = open(log_file, "a") if log_file else None
if log:
    atexit.register(log.close)


def say(msg):
    """Wrapper message: to the log; to stdout if there is no log."""
    print(f"[RivetWrapper] {msg}", file=log or sys.stdout, flush=True)


def die(msg):
    """Error: writes to the log and to stderr (so it shows in the Snakemake output), then exits."""
    say(f"ERROR: {msg}")
    if log:
        print(f"[RivetWrapper] {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------
def param(name, default=None):
    """A value from snakemake.params; the default if missing or None."""
    value = getattr(snakemake.params, name, None)
    return default if value is None else value


def as_list(value):
    """'A,B' / 'A B' / ['A', 'B'] / [['A'], 'B'] -> ['A', 'B']"""
    if value is None:
        return []
    if isinstance(value, str):
        return [v for v in value.replace(",", " ").split() if v]
    out = []
    for v in value:
        out.extend(as_list(v))
    return out


def one_analysis(value):
    """One analysis name: 'A' or ['A'] -> 'A'; nothing -> ''. Several names are an error."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = list(value)
        if len(value) > 1:
            die(f"one analysis only, got {value}")
        value = value[0] if value else ""
    value = str(value).strip()
    if any(c in value for c in ", \t\n"):
        die(f"one analysis only, got {value!r}")
    return value


def first_or(named, key):
    """Named file from input/output; the first one if there is no such name."""
    value = getattr(named, key, None)
    if value is None:
        if len(named) == 0:
            die(f"no {key} file given")
        value = named[0]
    return Path(str(value))


# --------------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------------
hepmc = first_or(snakemake.input, "hepmc")
yoda_out = first_or(snakemake.output, "yoda")

analysis = one_analysis(param("analysis"))

yoda_out.parent.mkdir(parents=True, exist_ok=True)


def write_yoda(src: Path):
    """src (.yoda) -> yoda_out; compresses if the output ends with .gz."""
    if yoda_out.suffix == ".gz":
        with open(src, "rb") as fin, gzip.open(yoda_out, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        shutil.move(str(src), yoda_out)


if not analysis:
    die("params.analysis is empty: a Rivet analysis is required")


# --------------------------------------------------------------------------------------------------
# Environment: analyses you compiled yourself (Rivet*.so made by rivet-build)
# --------------------------------------------------------------------------------------------------
env = os.environ.copy()
# analysis_path = as_list(param("analysis_path"))
# if analysis_path:
#     paths = [str(Path(p).resolve()) for p in analysis_path]
#     old = env.get("RIVET_ANALYSIS_PATH")
#     env["RIVET_ANALYSIS_PATH"] = os.pathsep.join(paths + ([old] if old else []))
#     # so that .info / .yoda reference files in the same folder are found too
#     old_data = env.get("RIVET_DATA_PATH")
#     env["RIVET_DATA_PATH"] = os.pathsep.join(paths + ([old_data] if old_data else []))


# --------------------------------------------------------------------------------------------------
# Rivet command
# --------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory(dir=yoda_out.parent) as tmp:
    tmp_yoda = Path(tmp) / "rivet.yoda"

    cmd = ["rivet", "-a", analysis, "-o", str(tmp_yoda)]

    # HepMC file (.hepmc or .hepmc.gz) is passed to rivet as it is; rivet opens the .gz itself
    cmd.append(str(hepmc))

    say(" ".join(shlex.quote(c) for c in cmd))
    # if analysis_path:
    #     say(f"RIVET_ANALYSIS_PATH={env['RIVET_ANALYSIS_PATH']}")

    # rivet's stdout/stderr go to the same log file as the wrapper messages
    rc = subprocess.call(cmd, stdout=log or sys.stdout, stderr=log or sys.stderr, env=env)

    if rc != 0:
        die(f"rivet failed (exit code {rc}), log: {log_file}")
    if not tmp_yoda.exists():
        die("rivet finished but no YODA file was produced")

    write_yoda(tmp_yoda)
    say(f"written: {yoda_out}")