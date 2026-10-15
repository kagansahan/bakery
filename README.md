**Bakery** is a Snakemake re-implementation of [em-creator](https://github.com/SModelS/em-creator):
it produces SModelS efficiency maps (`.embaked` files) for simplified-model topologies,
with two recasting chains:

```
mass point -> MG5_aMC + Pythia8 -> events.hepmc.gz -+-> Delphes -> CutLang -> .embake -+
              (one job, LHE kept)                    +-> Rivet (all routines, one pass) -> .embake -+
                                                                                                   v
                                                       one .embaked per (analysis, topology, tool)
```

## Install

```bash
git clone https://github.com/kagansahan/bakery.git && cd bakery
conda env create -f environment.yml
conda activate bakery
```

## Running on CERN lxbatch (HTCondor)
 
Jobs are submitted from lxplus, and the project has to live on EOS. The normal schedds refuse submit
files with `/eos` paths; the EosSubmit schedds (`module load lxbatch/eossubmit`) accept them, but then
every path in the submit file must be under `/eos`. If a submission fails with an EOS error, see
[EOS troubleshooting](https://batchdocs.web.cern.ch/troubleshooting/eos.html) and the
[EosSubmit limitations](https://batchdocs.web.cern.ch/local/eossubmit.html#limitations).
 
Snakemake has to keep running while the jobs are in the queue. So start it inside a tmux session that survives logout (lxplus9, see
[KB0008111](https://cern.service-now.com/service-portal?id=kb_article&n=KB0008111)):
 
```bash
systemctl --user start tmux.service
tmux attach
```
 
Inside tmux, load the EOS submit module, activate the environment and go to the project:
 
```bash
module load lxbatch/eossubmit
conda activate bakery
cd /eos/user/<initial>/<username>/<bakery_folder>
```
 
The repository comes with a profile for this, `profiles/cern-htcondor/`: it submits every job to HTCondor, keeps the Snakemake caches on EOS, builds the conda environments in the worker's scratch and runs `job_wrapper.sh` on the worker first. You do not write submit files yourself.
 
Run a rule with the profile, and detach with `Ctrl-b d`:
 
```bash
snakemake --profile profiles/cern-htcondor --configfile <path_to_configfile> <rule/target_file> --config <options>
```
 
Note which lxplus node you are on (`hostname`). To check on the run later, log in to that same node and run `tmux attach`. `condor_q` shows the jobs in the queue.

## Run

**Mock mode** (no HEP software, a few seconds). The four tools are replaced by small
wrappers that write files in the *real formats* (HepMC text, Delphes and CutLang ROOT
files, YODA), so the graph *and* the efficiency extraction are exercised.
Output goes to `results-mock/`, never to `results/`.

```bash
snakemake -s workflow/Snakefile --configfile .test/config.yml --cores 4
python -m pytest tests/          # unit tests of the extraction scripts
```

`.test/data/input.hepmc.gz` is a real HepMC2 file (48 Pythia8 events). To test the Rivet or
Delphes branch with the real tools before MadGraph runs, copy it to the path `run_mg5py8` would
write (`results/<sqrts>/<process>/<point>/MG5PY8.events.hepmc.gz`) and ask for a downstream target.

**Real mode** (each tool in its own conda environment):

```bash
snakemake -s workflow/Snakefile --configfile config/config.yml --cores 8 --use-conda
# CERN HTCondor: see the section above (profiles/cern-htcondor)
# SLURM: add  --executor slurm  and a profile with resources
```

## Configuration (`config/config.yml`)

| key | meaning |
|---|---|
| `mode` | `real` or `mock` |
| `generators` | currently only `MG5PY8` |
| `detectors` | named Delphes setups: `card`, `executable` (`DelphesHepMC2` default) |
| `processes` | topology `name` (a folder in `workflow/wrappers/mg5amcnlo/data/`), `sqrts`, `extrajet` (0-3), `parameters` |
| `analyses[].recasting[]` | `tool` (`cutlang`/`rivet`), `detsim` (a detector name, or `none` for Rivet), `config` |
| `samples` | `process`, `nevents`, `points`; masses **heaviest first**: value *i* fills `M{n-1-i}` in the SLHA template |

CutLang `config`: `adl_file` (path), optional `exclude_regions`, `bin_names: index|label`,
`input_format` (`DELPHES` default, every event weight 1; `DELPHES2` makes CutLang use `Event.Weight`,
required for weighted samples such as the `*bias` topologies).
Rivet `config`: `routine` (Rivet analysis name), optional `sr_map` (counter name -> SModelS SR name).
Optional top-level `rivet_analysis_path` for locally built Rivet plugins, and
`rivet_ignore_beams` (default `false`; only set it if you know the beam check is wrong for your sample).

The detector simulation is **chosen** per analysis and tool (`detsim`), not derived from the
experiment name. Delphes runs once per (point, detsim) and is shared by all CutLang analyses;
Rivet runs once per point with all routines of that sqrt(s).

## How the efficiencies are computed

**Rivet** (`workflow/scripts/rivet_to_embake.py`):
`eff(SR) = sumW(/RAW/<routine>/<SR>) / sumW(/_EVTCOUNT)`, nominal weight only (paths with `[`
are skipped). `/RAW/` objects are the pre-`finalize()` copies, so the routine's normalisation
does not matter. The routine must book one `Counter` per signal region.
Uses the `yoda` Python module if present, otherwise a built-in text-YODA parser.

**CutLang** (`workflow/scripts/cutlang_to_embake.py`): numerator = last `cutflow` bin of each
region, and each `bincounts` bin (`<region>_bin<i>`); denominator = the weight CutLang summed
over every event in the Delphes tree: the number of events for `DELPHES`, the sum of `Event.Weight`
for `DELPHES2`. Non-uniform weights with `DELPHES` stop with an error, because CutLang would ignore them. The cutflow is *not* used for the denominator: in a dependent region
(e.g. `region searchbins` starting with `presel`) CutLang only counts events that passed the
parent region, so a cutflow-based denominator overestimates the efficiency.

**Output** (`workflow/scripts/create_em.py`): em-creator format, readable with `eval()`:
`{(610, 120): {'SR1': 0.01, ..., '__t__': '...', '__nevents__': 5000}, ...}`.
Every per-point `.embake` (JSON) also keeps diagnostics (cut-flows, statistical errors).

## MadGraph wrapper notes

Ported from em-creator: XQCUT rules (applied in sequence, so the ISR rule overrides TChi),
mean mass for associate production, bias run card and matching Pythia8 card for `*bias`
topologies, local `idm` UFO model for `THig*`, reproducible `iseed` per point.
Topologies without an SLHA template (`T2left`, `T5btbtLL`, `T6btLL`, `T6tbLL`, `TSlepSlep`)
stop with a clear error. A standalone test lives in `workflow/wrappers/mg5amcnlo/test/`.

## Status

| step | mock | real |
|---|---|---|
| MG5 + Pythia8 | OK | wrapper ready, needs a first run (conda `mg5amcnlo` + `mg5amcnlo-pythia8-interface`) |
| Delphes | OK | wrapper ready, untested |
| CutLang | OK | wrapper ready, untested (`CLA` from the `cutlang` conda channel) |
| Rivet | OK | wrapper ready, untested; the routine must provide signal-region Counters |
| extraction + `.embaked` | OK (unit tests) | to be validated on real CutLang / YODA files |
