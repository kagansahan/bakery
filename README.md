# bakery

Snakemake workflow that **recasts** LHC analyses on simulated signal models. For every parameter
point of a model it generates events, simulates a detector where needed, runs the analysis logic
(CutLang or Rivet) and writes the signal-region efficiencies to `.embake` files. The files of all
points of a model are merged into one `.embaked` file per (process, generator, analysis).

```
MadGraph5_aMC@NLO + Pythia8 ──► HepMC ──► Delphes ──► ROOT ──► CutLang ──► ROOT ──► .embake ─┐
                                   │                                                          ├─► .embaked
                                   └──────────────────────► Rivet ──► YODA ──► .embake ──────┘
```

> **Status:** work in progress. See [TODO.md](TODO.md) for known gaps.

## Requirements

* [conda](https://docs.conda.io) / [mamba](https://mamba.readthedocs.io) (Miniforge is fine)
* Linux. The pinned conda environments of the wrappers are `linux-64` only (see *TODO*).

Every tool (MadGraph, Delphes, CutLang, Rivet, ...) is installed by Snakemake itself into its own
conda environment (`--use-conda`), so only Snakemake has to be installed by hand:

```bash
conda env create -f environment.yaml        # creates "bakery-environment"
conda activate bakery-environment
```

## Quick start

```bash
# 1. look at / edit the configuration (every section is commented)
$EDITOR config/config.yml

# 2. run the whole chain for all parameter points of the config
snakemake --configfile config/config.yml --use-conda --cores 4

# or one step only; upstream=true also makes the inputs that are still missing
snakemake run_cutlang --configfile config/config.yml --use-conda --cores 4 --config upstream=true
```

Snakemake is started from the repository root; the `Snakefile` is found in `workflow/`.
Before anything runs, bakery prints a **plan** (which files will be made, which exist already, which
wait for missing inputs) and asks `Start? [y/N]`. The question needs a terminal and cannot be
switched off. After a `y`, the configuration that was used is saved as `config.used.yaml` in the
output folder.

## Targets

Each rule has a target `run_<rule>`; `all` (the default) runs everything.

| Target | Result |
| --- | --- |
| `run_mg5py8` | events, HepMC |
| `run_delphes` | Delphes ROOT files |
| `run_cutlang` | CutLang ROOT files |
| `run_cutlang_to_embake` | `.embake` files from CutLang |
| `run_rivet` | Rivet YODA files |
| `run_rivet_to_embake` | `.embake` files from Rivet |
| `run_create_em` | merged `.embaked` files |

## Options

Options go after `--config` (`--config overwrite=true`). They are not part of the config file.

| Option | Default | Meaning |
| --- | --- | --- |
| `overwrite` | `false` | also rebuild outdated files that already exist on disk |
| `upstream` | `false` | also make the missing inputs of the requested `run_<rule>` |
| `downstream` | `false` | also make what depends on the new files |
| `partial_embake` | `false` | `create_em` with only the `.embake` files that exist (the `.embaked` file then misses points) |
| `fake` | `false` | placeholder files instead of running the real tools |
| `list_limit` | `10` | files listed per group on the plan screen (`0` = all) |
| `show` | | `manifest` and/or `target_files`: print the job table / the target files |
| `bakery_help` | | print the options, selectors and config sections |

**Selecting a part of the config.** The selectors `process`, `sqrts`, `param_pt`, `generator`,
`det_sim`, `detector`, `analysis` and `recaster` restrict the run, for example

```bash
snakemake run_create_em --configfile config/config.yml --use-conda --cores 1 \
          --config process=T2 analysis=ATLAS-SUSY-2018-22
```

**Re-running one step.** Files that exist are left alone. To rebuild one step, ask for it with
`overwrite=true`; `--rerun-triggers` (a Snakemake option) decides what counts as outdated:

```bash
snakemake run_cutlang --configfile config/config.yml --use-conda --cores 1 --config overwrite=true
```

## Recipes

All commands are run from the repository root. `CFG` stands for `--configfile config/config.yml --use-conda`;
write it out in full when you type the command.

**Look before you run**

```bash
# what would Snakemake run? (a dry run; the Start? question is not asked)
snakemake -n CFG --cores 1

# print the table of all jobs / all target files, and list every file instead of 10 per group
snakemake -n CFG --cores 1 --config show=manifest
snakemake -n CFG --cores 1 --config show=target_files list_limit=0

# list the options, selectors and config sections bakery knows
snakemake -n CFG --cores 1 --config bakery_help=true
```

**Run a part of the config**

```bash
# one process
snakemake CFG --cores 4 --config process=T2

# one parameter point (the name of its folder under results/)
snakemake CFG --cores 4 --config process=T2 param_pt=1300p0_700p0

# one analysis, one recasting tool, one generator
snakemake CFG --cores 4 --config analysis=ATLAS-SUSY-2018-22
snakemake CFG --cores 4 --config recaster=rivet
snakemake CFG --cores 4 --config generator=MG5PY8 det_sim=delphesCutlang detector=ATLAS

# a selector and a step together: only the Rivet .embake files of T2
snakemake run_rivet_to_embake CFG --cores 2 --config process=T2 recaster=rivet
```

**Run one step**

```bash
# the inputs must exist already
snakemake run_delphes CFG --cores 4

# make the missing inputs too (generation, detector simulation, ...)
snakemake run_cutlang CFG --cores 4 --config upstream=true

# generator level only: events and Rivet, nothing else
snakemake run_rivet CFG --cores 4 --config upstream=true
```

**Run again**

```bash
# rebuild the CutLang output of every point (files that exist are rebuilt)
snakemake run_cutlang CFG --cores 1 --config overwrite=true

# the same, ignoring the software environment: only the file dates count
snakemake run_cutlang CFG --cores 1 --config overwrite=true --rerun-triggers mtime

# rebuild a step and everything made from it (CutLang -> .embake -> .embaked)
snakemake run_cutlang CFG --cores 1 --config overwrite=true downstream=true

# rebuild only the merged .embaked files, from the .embake files as they are
snakemake run_create_em CFG --cores 1 --config overwrite=true --forcerun create_em --rerun-triggers input

# one point of one analysis again
snakemake run_cutlang CFG --cores 1 --config overwrite=true process=T2 param_pt=1300p0_700p0
```

**More events or more points**

```bash
# add a point to samples[].points in the config, then make only what is missing
snakemake CFG --cores 4

# merge what exists so far (the .embaked file misses the points that are not ready)
snakemake run_create_em CFG --cores 1 --config partial_embake=true
```

**Try the workflow without the tools**

```bash
# placeholder files instead of MadGraph, Delphes, CutLang and Rivet
snakemake CFG --cores 1 --config fake=true
```

**Other config, more cores, cluster**

```bash
snakemake --configfile config/other.yml --use-conda --cores 8
snakemake CFG --cores 8 --keep-going --rerun-incomplete       # go on after a failed job
snakemake --profile profiles/cern-htcondor --configfile config/config.yml run_cutlang   # HTCondor
```

**Look at the results**

```bash
ls results/TEST/13p0/T2/                                       # the .embaked files
cat results/TEST/13p0/T2/MG5PY8.rivet.ATLAS-SUSY-2018-22.embaked
cat results/TEST/13p0/T2/1300p0_700p0/logs/MG5PY8.cutlang.ATLAS-SUSY-2018-22.log
```

**Test one wrapper**

```bash
cd workflow/wrappers/rivet/test && snakemake -j1 --use-conda --forceall
cd workflow/wrappers/rivet_to_embake/test && snakemake -j1 --use-conda --forceall
cd workflow/wrappers/mg5amcnlo/test && snakemake -j1 --use-conda results/test1/events.hepmc.gz
```

## Configuration

`config/config.yml` has these sections (each is documented in the file):

| Section | Content |
| --- | --- |
| `info` | name and version; the name is also the output folder `results/<name>/` |
| `generators` | event generators (`MG5PY8`) |
| `recasters` | recasting tools (`cutlang`, `rivet`) |
| `detector_simulation` | detector simulations and their detectors (Delphes cards) |
| `processes` | physics processes: `sqrts`, extra jets, parameter names |
| `samples` | parameter points to generate |
| `analyses` | analyses and the settings of each recasting tool |

An analysis is recast on the detector of its experiment. An analysis whose experiment has no
detector simulation is recast at generator level (detector `NONE`, for example Rivet).

## Output

```
results/<info.name>/
└── <sqrts>/<process>/                                   e.g. 13p0/T2/
    ├── <generator>.<recaster>.<analysis>.embaked        all points of the model
    ├── logs/                                            log of the merge step
    └── <param_pt>/                                      e.g. 1300p0_700p0/
        ├── <generator>.events.hepmc.gz                  generator events
        ├── <det_sim>/<generator>.<detector>.root        detector simulation
        ├── <generator>.<recaster>.<analysis>.root       CutLang output  (or .yoda.gz for Rivet)
        ├── <generator>.<recaster>.<analysis>.embake     efficiencies of this point
        └── logs/                                        one log per step
```

An `.embake` file holds one line with the efficiencies of one parameter point, after an optional
comment line (`#`):

```
(1300.0,700.0): {'2jl': 0.4975, '2jm': 0.5373, ..., '__t__': '2026-10-19_04:26:41', '__nevents__': 201}
```

The `.embaked` file is a Python dictionary of these points, `{(m1, m2): {...}, ...}`.

## Wrappers

Each step is a Snakemake wrapper in `workflow/wrappers/<name>/` with its own `environment.yaml`,
`meta.yaml` and, for most, a `test/` folder.

| Wrapper | Does |
| --- | --- |
| `mg5amcnlo` | MadGraph5_aMC@NLO + Pythia8: events as HepMC (and LHE when asked) |
| `delphes/DelphesHepMC2` | Delphes fast detector simulation of HepMC events |
| `cutlang` | runs CutLang with an ADL file on a Delphes ROOT file |
| `cutlang_to_embake` | CutLang ROOT output to `.embake` |
| `rivet` | runs one Rivet analysis on HepMC events |
| `rivet_to_embake` | Rivet YODA output to `.embake` |
| `pythia8` | placeholder, not a working generator yet |

Test one wrapper on its own:

```bash
cd workflow/wrappers/rivet_to_embake/test
snakemake -j1 --use-conda --forceall
```

Some tests need an input that is not in the repository (large event files are ignored by
`.gitignore`); the header of each `test/Snakefile` says what to provide.

## Running on CERN lxbatch (HTCondor)

Jobs are submitted from lxplus, and the project has to live on EOS. The normal schedds refuse submit
files with `/eos` paths; the EosSubmit schedds (`module load lxbatch/eossubmit`) accept them, but then
every path in the submit file must be under `/eos`. If a submission fails with an EOS error, see
[EOS troubleshooting](https://batchdocs.web.cern.ch/troubleshooting/eos.html) and the
[EosSubmit limitations](https://batchdocs.web.cern.ch/local/eossubmit.html#limitations).

Snakemake has to keep running while the jobs are in the queue. So start it inside a tmux session that
survives logout (lxplus9, see [KB0008111](https://cern.service-now.com/service-portal?id=kb_article&n=KB0008111)):

```bash
systemctl --user start tmux.service
tmux attach
```

Inside tmux, load the EOS submit module, activate the environment and go to the project:

```bash
module load lxbatch/eossubmit
conda activate bakery-environment
cd /eos/user/<initial>/<username>/<bakery_folder>
```

The repository comes with a profile for this, `profiles/cern-htcondor/`: it submits every job to
HTCondor, keeps the Snakemake caches on EOS, builds the conda environments in the worker's scratch and
runs `job_wrapper.sh` on the worker first. You do not write submit files yourself.

Run a rule with the profile, and detach with `Ctrl-b d`:

```bash
snakemake --profile profiles/cern-htcondor --configfile <path_to_configfile> <rule/target_file> --config <options>
```

Note which lxplus node you are on (`hostname`). To check on the run later, log in to that same node
and run `tmux attach`. `condor_q` shows the jobs in the queue.

The environment also has the Slurm executor plugin of Snakemake; there is no Slurm profile yet.

## Repository layout

```
config/            configuration of a run
environment.yaml   conda environment with Snakemake
profiles/          cluster profiles
resources/         Delphes cards, ADL analysis files (ADL4HEP)
workflow/
├── Snakefile      rules
├── lib/bakery/    planning, wildcards, reports (the "bakery" Python package)
├── scripts/       create_em.py (merges .embake files)
├── schemas/       config schema
└── wrappers/      one folder per tool
```
