# Efficiency maps with Rivet: a guide from scratch

This guide takes you from nothing to an SModelS efficiency map made with a Rivet
analysis. Rivet runs on the generated events directly (generator level), so the chain
is short:

```
MadGraph5_aMC@NLO + Pythia8 ──► HepMC ──► Rivet ──► YODA ──► .embake (one point) ──► .embaked (all points)
```

No Delphes, no CutLang. Everything except conda is installed by Snakemake.

## 1. Where to run

* **Linux** (lxplus, a Linux laptop or desktop). The conda environments of the tools are
  pinned for `linux-64`.
* **macOS** is untested for the real tools. The `fake=true` mode (step 6) works everywhere.
* Disk: about 10 GB for the conda environments, plus the events.
* Time: MadGraph needs a few minutes per mass point; Rivet seconds to minutes.

## 2. Get the code

The current code is on the `kagan-dev` branch (the default branch of the repository is
an older one):

```bash
git clone -b kagan-dev https://github.com/kagansahan/bakery.git
cd bakery
```

## 3. Install conda and Snakemake (once)

If `conda --version` does not work, install Miniforge:

```bash
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -b -p <a folder with a few GB free>/miniforge3
<that folder>/miniforge3/bin/conda init bash        # or zsh
```

Open a new terminal, then create the environment with Snakemake:

```bash
conda env create -f environment.yaml       # creates "bakery-environment"
conda activate bakery-environment
snakemake --version                        # 9.27.x
```

From now on, start every session with `conda activate bakery-environment` and run all
commands from the repository root (the `bakery` folder).

## 4. Choose what to compute

You need four things:

| What | Where to find it | Example |
| --- | --- | --- |
| a **topology** (simplified model) | a folder of `workflow/wrappers/mg5amcnlo/data/` | `T2` (squark pair, squark → q + LSP) |
| its **mass points** | your choice; heaviest mass first | `[1300.0, 700.0]` = squark 1300 GeV, LSP 700 GeV |
| the **SModelS analysis** and its **signal-region names** | the SModelS database: `<sqrts>/<experiment>/<analysis>-eff/`, one folder per signal region | `ATLAS-SUSY-2015-06`: `SR2jl`, `SR2jm`, ... |
| the **Rivet routine** of that analysis | `rivet --list-analyses` (see below) | `ATLAS_2016_I1458270` |

Masses: with `n` parameters, value `i` of a point fills the placeholder `M{n-1-i}` of the
topology's `spectrum.slha` (for T2: squark → `M1`, LSP → `M0`). Look at the SLHA file
of your topology to see which particle each placeholder sets.

**Which Rivet routines exist.** The workflow uses Rivet 4.1.4 and the routines that come
with it (several hundred). To browse them, make a small Rivet environment:

```bash
conda create -n rivet-only -c conda-forge rivet=4.1.4
conda activate rivet-only
rivet --list-analyses | grep -i susy
rivet --show-analysis ATLAS_2016_I1458270
conda activate bakery-environment          # back
```

The routine must count events per signal region with Rivet **counters**. The efficiency
of a signal region is

```
efficiency = sum of weights in /RAW/<routine>/<counter>  /  sum of weights in /RAW/_EVTCOUNT
```

so a routine that only fills histograms gives no efficiencies.

## 5. Write the configuration

Create `config/my_rivet.yml`:

```yaml
info:
  name: MY_RIVET_SCAN          # results go to results/MY_RIVET_SCAN/
  version: 1

generators:
  - {name: MG5PY8, enabled: true}

recasters:
  - {name: rivet, enabled: true}
  - {name: cutlang, enabled: false}

detector_simulation: []        # Rivet works on the generated events: no Delphes

processes:
  - name: T2                   # topology folder
    sqrts: 13.0
    extrajet: 0                # extra matrix-element jets (MLM matching)
    parameters:                # names only; heaviest first
      - {name: squark}
      - {name: mlsp}

samples:
  - process: T2
    nevents: 1000              # events per point; a few thousand for a usable map
    points:
      - [1300.0, 700.0]
      - [1600.0, 600.0]

analyses:
  - name: ATLAS-SUSY-2015-06   # SModelS name: it names the output files
    experiment: ATLAS
    sqrts: 13.0                # must equal processes[].sqrts
    lumi: 3.2
    recasting:
      - name: rivet
        settings:
          analysis: ATLAS_2016_I1458270          # Rivet routine (one)
          # Rivet counter name -> SModelS signal-region name (optional)
          sr_map: {2jl: SR2jl, 2jm: SR2jm, 2jt: SR2jt, 4jt: SR4jt, 5j: SR5j, 6jm: SR6jm, 6jt: SR6jt}
```

* `sr_map` renames the Rivet counters to the SModelS signal-region names. SModelS can only
  use the map when the names are the dataset folder names of the analysis. Counters you do
  not list keep their Rivet name. To see the counter names of a routine, run one point and
  look into its YODA file:

  ```bash
  zcat results/MY_RIVET_SCAN/13p0/T2/1300p0_700p0/MG5PY8.rivet.ATLAS-SUSY-2015-06.yoda.gz | grep "^BEGIN YODA_COUNTER" | grep /RAW/
  ```
* Several analyses: add more entries under `analyses`, one Rivet routine each.
* `config/config.yml` has all sections with comments, including Delphes and CutLang.

## 6. Run

Always look first. A dry run (`-n`) lists the jobs and runs nothing:

```bash
snakemake -n --configfile config/my_rivet.yml --use-conda --cores 1
```

For the config above: 2 `mg5py8`, 2 `rivet`, 2 `rivet_to_embake`, 1 `create_em`.

Optional, without any physics tool (placeholder files, seconds):

```bash
snakemake --configfile config/my_rivet.yml --cores 1 --config fake=true
rm -rf results/MY_RIVET_SCAN               # remove the placeholders before the real run
```

The real run:

```bash
snakemake --configfile config/my_rivet.yml --use-conda --cores 4
```

* bakery prints a **plan** and asks `Start? [y/N]`; answer `y`. The question needs a
  terminal (on lxplus use `tmux` for long runs, see the README).
* The first run builds the conda environments of MadGraph and Rivet (this takes a while,
  once).
* An interrupted run can be started again with the same command: finished files are kept.

Only part of the config: `--config param_pt=1300p0_700p0`; only the Rivet step on events
that exist: `snakemake run_rivet ...`. See the README for all options and for HTCondor.

## 7. Results

```
results/MY_RIVET_SCAN/13p0/T2/
├── MG5PY8.rivet.ATLAS-SUSY-2015-06.embaked        the efficiency map (all points)
└── 1300p0_700p0/
    ├── MG5PY8.events.hepmc.gz                     events
    ├── MG5PY8.rivet.ATLAS-SUSY-2015-06.yoda.gz    Rivet output
    ├── MG5PY8.rivet.ATLAS-SUSY-2015-06.embake     efficiencies of this point
    └── logs/                                      one log per step
```

```bash
cat results/MY_RIVET_SCAN/13p0/T2/MG5PY8.rivet.ATLAS-SUSY-2015-06.embaked
```

```
{(1300.0, 700.0): {'SR2jl': 0.37, 'SR2jm': 0.38, ..., '__nevents__': 93}, ...}
```

`__nevents__` is the number of events Rivet saw. Check it against `nevents` in the config
(see *Known issues*).

## Known issues

* **Only the routines that come with Rivet 4.1.4** can be used for now; routines you build
  yourself are not supported yet.
* **About half of the events are lost for T2-like templates.** Some SLHA templates declare
  the right-handed squarks stable (`DECAY 2000001 0.0`, no decay channels); Pythia cannot
  hadronise them and those events are dropped (`Nb of events after matching` in the
  generation log, `__nevents__` in the map). The efficiencies come from the left-handed
  squarks only; raise `nevents` to compensate.
* One Rivet routine per analysis entry; each runs in its own pass over the events.

## Troubleshooting

| Message | Meaning |
| --- | --- |
| rivet exits with an error about the analysis | the routine name is wrong (`rivet --list-analyses`) |
| `no /RAW/<analysis>/<region> counters` | the routine books no counters (histograms only) |
| `confirmation needed, but there is no terminal` | run in a terminal (or tmux), not in the background |
| the first run stays at `Creating conda environment` | building the environments; wait |

Logs: `results/<name>/<sqrts>/<process>/<point>/logs/`.
