#!/usr/bin/env python3
"""Snakemake wrapper: MadGraph5_aMC@NLO (+ Pythia8 shower) for SModelS simplified models."""
import os
import re
import sys
import shutil
import tempfile
import subprocess
from typing import Dict, List, Tuple, Optional


def info(message: str) -> None:
    print(f"[mg5amcnloWrapper][INFO] {message}", file=sys.stdout, flush=True)

def msg(message: str) -> None:
    print(f"[mg5amcnloWrapper][MSG] {message}", file=sys.stdout, flush=True)

def error(message: str) -> None:
    print(f"[mg5amcnloWrapper][ERROR] {message}", file=sys.stderr, flush=True)

def get_data_dir(topo: str) -> str:
    """Return the data directory path for a given topology."""
    wrapper_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(wrapper_dir, "data", topo)

def get_default_dir() -> str:
    """Return the default template directory path."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "default")

ASSOCIATE_TOPOS = {"TGQ", "T3GQ", "T5GQ", "TChiWZ", "TChiWZoff", "THigWZ",
                   "THigWZoff", "TChiWH", "TChiWHoff", "THigWH", "THigWHoff"}


def compute_xqcut(topo: str, masses: List[float]) -> float:
    """Merging scale (XQCUT), same rules and order as SModelS/em-creator.

    The rules are applied one after the other (not if/elif): for e.g.
    TChiZISR the ISR rule overrides the TChi rule at low masses.
    For associate production the reference mass is the mean of the first two.
    """
    m0 = masses[0]
    mref = (masses[0] + masses[1]) / 2.0 if topo in ASSOCIATE_TOPOS else m0
    xqcut = mref / 4.0
    if "TChi" in topo or "THig" in topo:
        xqcut = mref / 6.0
    if "TRV1" in topo:
        xqcut = mref / 15.0 if m0 >= 450.0 else 30.0
    if "TRS1" in topo:
        xqcut = mref / 15.0 if m0 >= 525.0 else 35.0
    if "ISR" in topo and m0 <= 25.0:
        xqcut = 15.0
    if "ISR" in topo and 25.0 < m0 <= 60.0:
        xqcut = mref / 2.0
    info(f"Computed XQCUT = {xqcut} for topology {topo}, masses = {masses}")
    return xqcut


def set_seed(run_card: str, seed: int) -> str:
    """Replace the value in the '... = iseed' line of the run card."""
    new, n = re.subn(r"^\s*\S+\s*=\s*iseed", f" {seed} = iseed", run_card, flags=re.M)
    if n != 1:
        raise RuntimeError("could not find a unique 'iseed' line in the run card")
    return new


def fill_run_card(template_path: str, params: Dict[str, str]) -> str:
    """Replace @@KEY@@ placeholders in a run card template with given values."""
    with open(template_path, "r") as f:
        content = f.read()
    for key, value in params.items():
        content = content.replace(f"@@{key}@@", str(value))
    return content

def fill_slha_template(slha_path: str, masses: List[float]) -> str:
    """
    Replace M{n-i-1} placeholders in an SLHA template with the mass values.
    """
    with open(slha_path, "r") as f:
        text = f.read()
    n = len(masses)
    for i in range(n):
        placeholder = f"M{n-i-1}"
        text = re.sub(rf'\b{placeholder}\b', str(masses[i]), text, flags=re.IGNORECASE)
    left = re.findall(r"\bM[0-9]\b", text)
    if left:
        raise ValueError(f"{slha_path}: placeholders {sorted(set(left))} not filled; "
                         f"got {n} masses")
    return text

def generate_proc_card(template_path: str, extrajets: int, output_dir: str) -> str:
    """Build a process card with extra jet lines and the output directive."""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Proc card not found: {template_path}")
    with open(template_path, "r") as f:
        lines = f.readlines()

    proc_lines = []
    jet_lines = []
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        proc_lines.append(line_str)
        if line_str.startswith("generate ") or line_str.startswith("add process "):
            for i in range(1, extrajets + 1):
                new_line = line_str.replace("generate ", "add process ")
                if " $" in new_line:
                    new_line = new_line.replace(" $", " j" * i + " $")
                elif "/" in new_line:
                    parts = new_line.split("/")
                    if len(parts) == 2:
                        new_line = parts[0] + " j" * i + " /" + parts[1]
                else:
                    new_line = new_line + " j" * i
                jet_lines.append(new_line)

    return "\n".join(proc_lines + jet_lines + [f"output {output_dir}"])

def prepare_cards(
    workdir: str,
    topo: str,
    extrajets: int,
    masses: List[float],
    slha_template: str,
    proc_template: str,
    run_template: str,
    mg_params: Dict[str, str]
) -> Tuple[str, str, str, str]:
    """
    Create param_card, proc_card, and run_card in the workdir.
    Returns paths to the cards and the output directory name.
    """
    info("Preparing cards (SLHA, proc, run) ...")
    # SLHA (param_card)
    slha_content = fill_slha_template(slha_template, masses)
    param_card_path = os.path.join(workdir, "param_card.dat")
    with open(param_card_path, "w") as f:
        f.write(slha_content)
    info(f"Created param_card: {param_card_path}")

    # MG5 output directory name
    mass_str = "_".join(str(int(m)) if m == int(m) else str(m).replace(".", "p") for m in masses)
    mg5_output_dir = os.path.join(workdir, f"{topo}_{extrajets}jet_{mass_str}")

    # Proc card
    proc_card_content = generate_proc_card(proc_template, extrajets, mg5_output_dir)
    proc_card_path = os.path.join(workdir, "mg5proc")
    with open(proc_card_path, "w") as f:
        f.write(proc_card_content)
    info(f"Created proc card: {proc_card_path}")

    # Run card
    if os.path.exists(run_template):
        run_content = fill_run_card(run_template, mg_params)
    else:
        run_content = "\n".join(f" {v} = {k}" for k, v in mg_params.items())
    run_card_path = os.path.join(workdir, "run_card.dat")
    with open(run_card_path, "w") as f:
        f.write(run_content)
    info(f"Created run card: {run_card_path}")

    return param_card_path, proc_card_path, run_card_path, mg5_output_dir

def get_mg5_env() -> dict:
    """Set up environment variables for Pythia8 if a Conda environment is active."""
    env = os.environ.copy()
    if "CONDA_PREFIX" in env:
        conda_lib = os.path.join(env["CONDA_PREFIX"], "lib")
        env["LD_LIBRARY_PATH"] = f"{conda_lib}:{env.get('LD_LIBRARY_PATH', '')}"
        env["PYTHIA8DATA"] = os.path.join(env["CONDA_PREFIX"], "share/Pythia8/xmldoc")
        msg("Conda environment detected, Pythia8 paths set.")
    return env

def generate_process_directory(workdir: str, proc_card_path: str, log_fh, mg_env: dict) -> None:
    """Run mg5_aMC to create the process directory (diagrams + matrix elements)."""
    info("Generating process directory...")
    mg5_exe = "mg5_aMC"
    subprocess.run([mg5_exe, proc_card_path],
                   cwd=workdir,
                   env=mg_env,
                   stdout=log_fh,
                   stderr=subprocess.STDOUT,
                   check=True)
    info("Process directory created successfully.")

def copy_cards_to_output_dir(
    param_card_path: str,
    run_card_path: str,
    pythia_template: Optional[str],
    mg5_output_dir: str
) -> None:
    """Copy generated cards into the Cards/ subdirectory of the MG5 output."""
    info("Copying cards to the process directory ...")
    cards_dir = os.path.join(mg5_output_dir, "Cards")
    os.makedirs(cards_dir, exist_ok=True)
    shutil.copy(param_card_path, os.path.join(cards_dir, "param_card.dat"))
    shutil.copy(run_card_path, os.path.join(cards_dir, "run_card.dat"))
    if pythia_template and os.path.exists(pythia_template):
        shutil.copy(pythia_template, os.path.join(cards_dir, "pythia8_card.dat"))
    info("Cards copied.")

def launch_event_generation(workdir: str, mg5_output_dir: str, shower_type: str,
                            log_fh, mg_env: dict) -> None:
    """Launch the event generation step (shower + detector)."""
    info(f"Launching event generation (shower={shower_type}) ...")
    cmd_file = os.path.join(workdir, "mg5cmd")
    with open(cmd_file, "w") as f:
        f.write("set automatic_html_opening False\n")
        f.write(f"launch {mg5_output_dir}\n")
        f.write(f"shower={shower_type}\n")
        f.write("detector=OFF\n")
        f.write("0\n")
        f.write("0\n")
    subprocess.run(["mg5_aMC", cmd_file],
                   cwd=workdir,
                   env=mg_env,
                   stdout=log_fh,
                   stderr=subprocess.STDOUT,
                   check=True)
    info("Event generation completed.")

def collect_outputs(mg5_output_dir: str, hepmc_out: str, lhe_out: str) -> None:
    """Copy the generated LHE and HepMC files to the Snakemake output paths."""
    info("Collecting output files ...")
    run_dir = os.path.join(mg5_output_dir, "Events", "run_01")

    # LHE
    lhe_src = os.path.join(run_dir, "unweighted_events.lhe.gz")
    if not os.path.exists(lhe_src):
        lhe_src = os.path.join(run_dir, "unweighted_events.lhe")
    if not os.path.exists(lhe_src):
        raise FileNotFoundError(f"LHE file not found in {run_dir}")
    shutil.copy2(lhe_src, lhe_out)
    info(f"LHE copied to {lhe_out}")

    # HepMC
    if hepmc_out is not None:
        hepmc_src = os.path.join(run_dir, "tag_1_pythia8_events.hepmc.gz")
        if not os.path.exists(hepmc_src):
            hepmc_src = os.path.join(run_dir, "tag_1_pythia8_events.hepmc")
        if not os.path.exists(hepmc_src):
            raise FileNotFoundError(f"HepMC file not found in {run_dir}")
        shutil.copy2(hepmc_src, hepmc_out)
        info(f"HepMC copied to {hepmc_out}")
    else:
        info("HepMC is not asked.")

def resolve_template_paths(topo: str, default_dir: str) -> Dict[str, Optional[str]]:
    """
    Choose the template files for a topology (as in SModelS/em-creator):
      spectrum.slha, proc_card.dat : must exist in data/<topo>/
      run_card.dat : data/<topo>/ > default/run_card_bias.dat for *bias*
                     topologies > default/run_card.dat
      pythia8 card : data/pythia8/pythia8_card_match.dat for *bias* topologies,
                     otherwise MG5's own default
    """
    topo_dir = get_data_dir(topo)
    if not os.path.isdir(topo_dir):
        raise FileNotFoundError(f"no templates for topology {topo} in {topo_dir}")
    slha = os.path.join(topo_dir, "spectrum.slha")
    proc = os.path.join(topo_dir, "proc_card.dat")
    for p in (slha, proc):
        if not os.path.exists(p):
            raise FileNotFoundError(f"{topo}: required template {p} is missing")

    run = os.path.join(topo_dir, "run_card.dat")
    if not os.path.exists(run):
        name = "run_card_bias.dat" if "bias" in topo else "run_card.dat"
        run = os.path.join(default_dir, name)
        msg(f"Using default template {name}")

    pythia = None
    if "bias" in topo:
        pythia = os.path.join(os.path.dirname(default_dir), "pythia8", "pythia8_card_match.dat")
    return {"slha": slha, "proc": proc, "run": run, "pythia": pythia}


def localise_models(proc_card_text: str) -> str:
    """'import model idm' -> 'import model /abs/path/data/models/idm' when the
    UFO model is shipped with the wrapper (MG5 does not include idm)."""
    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "models")
    out = []
    for line in proc_card_text.splitlines():
        tok = line.split()
        if len(tok) >= 3 and tok[0] == "import" and tok[1] == "model":
            base = tok[2].split("-")[0]
            if os.path.isdir(os.path.join(models_dir, base)):
                restrict = tok[2][len(base):]
                line = " ".join(["import", "model", os.path.join(models_dir, base) + restrict] + tok[3:])
        out.append(line)
    return "\n".join(out)


def main():
    p = snakemake.params
    topo = p.process_name
    f_sqrts = float(p.sqrt)
    extrajets = int(p.extrajets)
    nevents = int(p.nevents)
    shower_type = p.get("shower", "Pythia8")
    seed = int(p.get("seed", 0))
    masses = [float(m) for m in p.parameter_point]

    hepmc_out = snakemake.output.get("hepmc")
    lhe_out = snakemake.output.lhe
    log_file = snakemake.log[0]
    if hepmc_out and shower_type.upper() == "OFF":
        raise ValueError("a HepMC output is requested but shower=OFF")

    info(f"Starting MadGraph5 wrapper for topology: {topo}")
    info(f"Masses: {masses}, extrajets: {extrajets}, nevents: {nevents}, "
         f"sqrt(s): {f_sqrts} TeV, seed: {seed}")

    templates = resolve_template_paths(topo, get_default_dir())

    ebeam = int(f_sqrts * 1000 / 2)
    mg_params = {
        "EBEAM": ebeam,
        "NEVENTS": nevents,
        "MAXJETFLAVOR": 5,
        "PDFLABEL": "'nn23lo1'",
        "XQCUT": compute_xqcut(topo, masses),
        "PTLUND": 2.0,
        "KTDURHAM": -1.0,
    }

    workdir = tempfile.mkdtemp(prefix=f"mg5_{topo}_")
    info(f"Working directory: {workdir}")
    try:
        param_card, proc_card, run_card, mg5_output_dir = prepare_cards(
            workdir, topo, extrajets, masses,
            templates["slha"], templates["proc"], templates["run"], mg_params
        )
        with open(proc_card) as f:
            txt = localise_models(f.read())
        with open(proc_card, "w") as f:
            f.write(txt + "\n")
        if seed > 0:
            with open(run_card) as f:
                txt = set_seed(f.read(), seed)
            with open(run_card, "w") as f:
                f.write(txt)

        mg_env = get_mg5_env()
        with open(log_file, "w") as log:
            generate_process_directory(workdir, proc_card, log, mg_env)
            copy_cards_to_output_dir(param_card, run_card, templates["pythia"], mg5_output_dir)
            launch_event_generation(workdir, mg5_output_dir, shower_type, log, mg_env)

        collect_outputs(mg5_output_dir, hepmc_out, lhe_out)
        info("Wrapper finished successfully.")
    except subprocess.CalledProcessError as e:
        error(f"MadGraph subprocess failed: {e} (see {log_file})")
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        info(f"Cleaned up temporary directory: {workdir}")


if __name__ == "__main__":
    main()