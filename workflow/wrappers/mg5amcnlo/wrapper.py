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

COLOURED_SPARTICLES = {1000001, 1000002, 1000003, 1000004, 1000005, 1000006,
                       2000001, 2000002, 2000003, 2000004, 2000005, 2000006, 1000021}
LIGHT = 1.0e4        # GeV; heavier sparticles count as decoupled


def slha_masses(text: str) -> Dict[int, float]:
    """PDG id -> mass from the BLOCK MASS of an (already filled) SLHA text."""
    masses, inside = {}, False
    for line in text.splitlines():
        tok = line.split("#", 1)[0].split()
        if not tok:
            continue
        if tok[0].upper() in ("BLOCK", "DECAY"):
            inside = tok[0].upper() == "BLOCK" and len(tok) > 1 and tok[1].upper() == "MASS"
            continue
        if inside and len(tok) >= 2:
            try:
                masses[abs(int(tok[0]))] = abs(float(tok[1]))
            except ValueError:
                pass
    return masses


def auto_widths(text: str):
    """'DECAY <id> 0.0' without channels -> 'DECAY <id> auto' for light squarks / gluinos.

    Several templates (e.g. T2, TGQ: ~u_R, ~d_R) declare light coloured
    sparticles stable. MadGraph then produces them, and Pythia cannot hadronise
    a stable coloured particle: those events fail ('unknown particle code',
    junction errors) and are dropped, which biases the sample (for T2 to the
    left-handed squarks). With 'auto' MadGraph computes width and branching
    ratios and passes them to Pythia in the LHE header.
    Returns (new text, list of PDG ids changed).
    """
    masses = slha_masses(text)
    lines = text.splitlines(keepends=True)
    decay_at, cur, changed = {}, None, []
    for i, line in enumerate(lines):
        tok = line.split("#", 1)[0].split()
        if tok and tok[0].upper() in ("DECAY", "BLOCK"):
            cur = None
            if tok[0].upper() == "DECAY" and len(tok) >= 3:
                try:
                    cur = abs(int(tok[1]))
                    decay_at[cur] = [i, float(tok[2]), 0]
                except ValueError:
                    cur = None
            continue
        if cur is not None and tok:
            decay_at[cur][2] += 1
    for pdg, (i, width, nch) in sorted(decay_at.items()):
        if (pdg in COLOURED_SPARTICLES and width == 0.0 and nch == 0
                and masses.get(pdg, 1e99) < LIGHT):
            lines[i] = f"DECAY {pdg} auto  # was 0.0 without channels (set by bakery)\n"
            changed.append(pdg)
    return "".join(lines), changed


def exclude_decoupled_gluino(proc_text: str, slha_text: str) -> Tuple[str, bool]:
    """Add '/ go' to every process line when the gluino is decoupled and not produced.

    With MLM matching MadGraph cannot cluster the extra-jet diagrams in which
    the jet comes off a (far off-shell) t-channel gluino ('Clustering failed in
    cluster.f': the channel produces no results.dat and the run stops), e.g.
    for T2 with a 350 TeV gluino. Such diagrams are negligible anyway.
    """
    if slha_masses(slha_text).get(1000021, 0.0) < LIGHT:
        return proc_text, False
    out, done = [], False
    for line in proc_text.splitlines():
        body, hashc, comment = line.partition("#")
        if body.strip().startswith(PROC_PREFIXES) and not re.search(r"(^|\s)go(\s|$)", body):
            if " / " in body:
                body = body.replace(" / ", " / go ", 1)
            else:
                cut = min([i for i in (body.find("@"), body.find(",")) if i >= 0],
                          default=len(body.rstrip()))
                body = body[:cut].rstrip() + " / go " + body[cut:]
            body = re.sub(r"\s+", " ", body).rstrip() + (" " if hashc else "")
            done = True
        out.append(body + hashc + comment)
    return "\n".join(out), done


PROC_PREFIXES = ("generate ", "add process ")


def _split_process(line: str):
    """'add process p p > a b $ c @2 # note' -> ('p p > a b', ' $ c')

    Returns the core process (before any '$', '/', ',' decay chain) and the
    rest (exclusions / decay chain) without the '@N' tag and the comment.
    """
    body = line.split("#", 1)[0]
    for prefix in PROC_PREFIXES:
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    body = re.sub(r"@\s*\d+", "", body).rstrip()
    cut = min([i for i in (body.find(" $"), body.find(" /"), body.find(",")) if i >= 0],
              default=len(body))
    return body[:cut].rstrip(), body[cut:]


def _n_jets(core: str) -> int:
    """Number of explicit 'j' in the final state of a core process."""
    final = core.split(">", 1)[1] if ">" in core else ""
    return final.split().count("j")


def generate_proc_card(template_path: str, extrajets: int, output_dir: str) -> str:
    """Build a process card with extra jet lines and the output directive.

    For every generate / add process line, add 'add process' lines with 1..extrajets
    extra jets, inserted before exclusions ('$', '/') and decay chains (','), and
    without the '@N' tag and trailing comment of the original line. Cards that
    already list their own jet multiplicities need extrajets == 0.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Proc card not found: {template_path}")
    with open(template_path, "r") as f:
        lines = [l.strip() for l in f if l.strip()]

    procs = [l for l in lines if l.startswith(PROC_PREFIXES)]
    if not procs:
        raise ValueError(f"{template_path}: no 'generate' line")
    if not any(l.startswith("import model ") for l in lines):
        # MG5 would silently fall back to the SM and fail on the SUSY particles
        raise ValueError(f"{template_path}: no 'import model' line")
    njets_in_card = max(_n_jets(_split_process(l)[0]) for l in procs)
    if extrajets > 0 and njets_in_card > 0:
        raise ValueError(
            f"{template_path} already generates up to {njets_in_card} extra jet(s); "
            f"set extrajet: 0 for this process (got {extrajets})")

    jet_lines = []
    for line in procs:
        core, rest = _split_process(line)
        for i in range(1, extrajets + 1):
            jet_lines.append("add process " + core + " j" * i + rest)

    return "\n".join(lines + jet_lines + [f"output {output_dir}"])


def max_jets_in_card(proc_card_path: str) -> int:
    """Highest number of explicit jets over the process lines of a finished card."""
    with open(proc_card_path) as f:
        procs = [l.strip() for l in f if l.strip().startswith(PROC_PREFIXES)]
    return max(_n_jets(_split_process(l)[0]) for l in procs)


def set_pythia_njetmax(card_text: str, njetmax: int) -> str:
    """MLM matching: JetMatching:nJetMax must be the highest jet multiplicity
    generated by MadGraph."""
    new, n = re.subn(r"^(\s*JetMatching:nJetMax\s*=\s*)\S+", rf"\g<1>{njetmax}",
                     card_text, flags=re.M)
    return new if n else card_text + f"\nJetMatching:nJetMax = {njetmax}\n"

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
    slha_content, auto = auto_widths(slha_content)
    if auto:
        msg(f"DECAY ... auto for {auto}: the template declares these light coloured "
            "sparticles stable; MadGraph computes their widths and branching ratios")
    param_card_path = os.path.join(workdir, "param_card.dat")
    with open(param_card_path, "w") as f:
        f.write(slha_content)
    info(f"Created param_card: {param_card_path}")

    # MG5 output directory name
    mass_str = "_".join(str(int(m)) if m == int(m) else str(m).replace(".", "p") for m in masses)
    mg5_output_dir = os.path.join(workdir, f"{topo}_{extrajets}jet_{mass_str}")

    # Proc card
    proc_card_content = generate_proc_card(proc_template, extrajets, mg5_output_dir)
    proc_card_content, nogo = exclude_decoupled_gluino(proc_card_content, slha_content)
    if nogo:
        msg("decoupled gluino excluded from the diagrams ('/ go')")
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
    mg5_output_dir: str,
    njetmax: Optional[int] = None,
) -> None:
    """Copy generated cards into the Cards/ subdirectory of the MG5 output."""
    info("Copying cards to the process directory ...")
    cards_dir = os.path.join(mg5_output_dir, "Cards")
    os.makedirs(cards_dir, exist_ok=True)
    shutil.copy(param_card_path, os.path.join(cards_dir, "param_card.dat"))
    shutil.copy(run_card_path, os.path.join(cards_dir, "run_card.dat"))
    if pythia_template and os.path.exists(pythia_template):
        with open(pythia_template) as f:
            text = f.read()
        if njetmax is not None:
            text = set_pythia_njetmax(text, njetmax)
        with open(os.path.join(cards_dir, "pythia8_card.dat"), "w") as f:
            f.write(text)
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

def mg5_cross_section(log_file: str) -> Optional[Tuple[float, float]]:
    """Last 'Matched cross-section' (after MLM matching) or, without matching,
    'Cross-section' that MadGraph printed, in pb."""
    matched, plain = None, None
    with open(log_file, errors="replace") as f:
        for line in f:
            m = re.search(r"(Matched )?[Cc]ross-section\s*:\s*([0-9.eE+-]+)\s*\+-\s*([0-9.eE+-]+)\s*pb", line)
            if m:
                val = (float(m.group(2)), float(m.group(3)))
                if m.group(1):
                    matched = val
                else:
                    plain = val
    return matched or plain


def add_hepmc_cross_section(src: str, dst: str, xs: Tuple[float, float]) -> None:
    """Copy a HepMC2 (IO_GenEvent) file and give every event the cross section.

    The MG5aMC-PY8 interface writes no 'C' line, so Rivet's crossSection() is
    undefined and finalize() scales the histograms with garbage (the bakery
    efficiencies use the /RAW/ objects and are not affected).
    """
    import gzip
    opener = gzip.open if src.endswith(".gz") else open
    cline = f"C {xs[0]:.16e} {xs[1]:.16e}\n"
    with opener(src, "rt") as fi, gzip.open(dst, "wt") as fo:
        pending = False
        for line in fi:
            if line.startswith("C "):
                continue                      # replace an existing one
            if pending and not line[:2] in ("N ", "U "):
                fo.write(cline)
                pending = False
            fo.write(line)
            if line.startswith("E "):
                pending = True
        if pending:
            fo.write(cline)


def collect_outputs(mg5_output_dir: str, hepmc_out: str, lhe_out: str,
                    log_file: Optional[str] = None) -> None:
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
        xs = mg5_cross_section(log_file) if log_file else None
        if xs:
            add_hepmc_cross_section(hepmc_src, hepmc_out, xs)
            info(f"HepMC copied to {hepmc_out}, cross section {xs[0]} +- {xs[1]} pb added")
        else:
            shutil.copy2(hepmc_src, hepmc_out)
            info(f"HepMC copied to {hepmc_out} (no cross section found in the MG5 log)")
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
            copy_cards_to_output_dir(param_card, run_card, templates["pythia"], mg5_output_dir,
                                     njetmax=max_jets_in_card(proc_card))
            launch_event_generation(workdir, mg5_output_dir, shower_type, log, mg_env)

        collect_outputs(mg5_output_dir, hepmc_out, lhe_out, log_file)
        info("Wrapper finished successfully.")
    except subprocess.CalledProcessError as e:
        error(f"MadGraph subprocess failed: {e} (see {log_file})")
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        info(f"Cleaned up temporary directory: {workdir}")


if __name__ == "__main__":
    main()