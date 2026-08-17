#!/usr/bin/env python3
"""

"""
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

def compute_xqcut(topo: str, m0: float, masses: List[float]) -> float:
    """Compute the merging scale (XQCUT) based on topology and first mass."""
    xqcut = m0 / 4.0
    if "TChi" in topo or "THig" in topo:
        xqcut = m0 / 6.0
    elif "TRV1" in topo:
        xqcut = m0 / 15.0 if m0 >= 450.0 else 30.0
    elif "TRS1" in topo:
        xqcut = m0 / 15.0 if m0 >= 525.0 else 35.0
    elif "ISR" in topo:
        if m0 <= 25.0:
            xqcut = 15.0
        elif 25.0 < m0 <= 60.0:
            xqcut = m0 / 2.0
    info(f"Computed XQCUT = {xqcut} for topology {topo}, m0 = {m0}")
    return xqcut

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

def resolve_template_paths(topo: str, default_dir: str) -> Dict[str, str]:
    """
    Choose the appropriate template files for a topology.
    Returns a dict with keys 'slha', 'proc', 'run', 'pythia'.
    """
    topo_dir = get_data_dir(topo)

    def resolve(filename: str) -> str:
        path = os.path.join(topo_dir, filename)
        if not os.path.exists(path):
            path = os.path.join(default_dir, filename)
            msg(f"Using default template for {filename}")
        return path

    return {
        "slha": resolve("spectrum.slha"),
        "proc": resolve("proc_card.dat"),
        "run": resolve("run_card.dat"),
        "pythia": resolve("pythia8_card.dat"),
    }

def main():
    # Snakemake parameters
    topo = snakemake.params.get("process_name", "T1")
    f_sqrts = float(snakemake.params.get("sqrt", 13.0))
    extrajets = int(snakemake.params.get("extrajets", 0))
    nevents = int(snakemake.params.get("nevents", 10000))
    shower_type = snakemake.params.get("shower", "Pythia8")
    raw_masses = snakemake.params.get("parameter_point", [1400.0, 600.0])
    masses = [float(m) for m in raw_masses]

    #hepmc_out = snakemake.output.hepmc
    hepmc_out = snakemake.output.get("hepmc")
    lhe_out = snakemake.output.lhe
    log_file = snakemake.log[0]

    info(f"Starting MadGraph5 wrapper for topology: {topo}")
    info(f"Masses: {masses}, extrajets: {extrajets}, nevents: {nevents}, sqrt(s): {f_sqrts} TeV")

    # Resolve templates
    default_dir = get_default_dir()
    templates = resolve_template_paths(topo, default_dir)

    # Compute MG5 parameters
    m0 = masses[0]
    xqcut = compute_xqcut(topo, m0, masses)
    ebeam = int(f_sqrts * 1000 / 2)
    mg_params = {
        "EBEAM": ebeam,
        "NEVENTS": nevents,
        "MAXJETFLAVOR": 5,
        "PDFLABEL": "'nn23lo1'",
        "XQCUT": xqcut,
        "PTLUND": 2.0,
        "KTDURHAM": -1.0,
    }
    info(f"Beam energy: {ebeam} GeV")

    # Create a temporary working directory
    workdir = tempfile.mkdtemp(prefix=f"mg5_{topo}_")
    info(f"Working directory: {workdir}")
    try:
        # Prepare all cards
        param_card, proc_card, run_card, mg5_output_dir = prepare_cards(
            workdir, topo, extrajets, masses,
            templates["slha"], templates["proc"], templates["run"], mg_params
        )

        # MG5 environment
        mg_env = get_mg5_env()

        with open(log_file, "w") as log:
            generate_process_directory(workdir, proc_card, log, mg_env)
            copy_cards_to_output_dir(param_card, run_card, templates["pythia"], mg5_output_dir)
            launch_event_generation(workdir, mg5_output_dir, shower_type, log, mg_env)

        # Collect outputs
        collect_outputs(mg5_output_dir, hepmc_out, lhe_out)
        info("Wrapper finished successfully.")

    except subprocess.CalledProcessError as e:
        error(f"MadGraph subprocess failed: {e}")
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        info(f"Cleaned up temporary directory: {workdir}")

if __name__ == "__main__":
    main()