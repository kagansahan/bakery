**Bakery** is a Snakemake re-implementation of [em-creator](https://github.com/SModelS/em-creator):
it produces SModelS efficiency maps (`.embaked` files) for simplified-model topologies,
with two recasting chains:

```
mass point -> MG5_aMC + Pythia8 -> events.hepmc.gz -+-> Delphes -> CutLang -> .embake -+
              (one job, LHE kept)                    |                                     |
           or Pythia8 standalone ------------------->+-> Rivet (all routines, one pass) -> .embake -+
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

**Mock mode** (no HEP software, a few seconds). The tools are replaced by small
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

`config/config.example.yml` is an annotated example with every option; copy it to start a
new scan. `config/config.yml` is the minimal setup used for the first tests.

| key | meaning |
|---|---|
| `mode` | `real` or `mock` |
| `generators` | `MG5PY8` (MadGraph + Pythia8 shower) and/or `Pythia8` (Pythia8 standalone, MSSM topologies), each with `enabled` |
| `detectors` | named Delphes setups: `card`, `experiment` (used to pick the detector of a CutLang analysis), `executable` (`DelphesHepMC2` default), optional `enabled` |
| `processes` | topology `name` (a folder in `workflow/wrappers/mg5amcnlo/data/`), `sqrts`, `extrajet` (0-3), `parameters` |
| `analyses[].recasting[]` | `tool` (`cutlang`/`rivet`), `config`, optional `detsim` (see below) |
| `recasters` | optional on/off list per tool (`name`, `enabled`); default: all on |
| `samples` | `process`, `nevents`, `points`; masses **heaviest first**: value *i* fills `M{n-1-i}` in the SLHA template |

CutLang `config`: `adl_file` (path), optional `exclude_regions`, `bin_names` (`index` = `<region>_bin<i>`,
`label`, or a template such as `SR{i}` / `{region}_SR{i}` to match the SModelS dataset names),
`input_format` (`DELPHES` default, every event weight 1; `DELPHES2` makes CutLang use `Event.Weight`,
required for weighted samples such as the `*bias` topologies).
Rivet `config`: `routine` (Rivet analysis name), optional `sr_map` (counter name -> SModelS SR name).
Optional top-level `rivet_analysis_path` for locally built Rivet plugins, and
`rivet_ignore_beams` (default `false`; only set it if you know the beam check is wrong for your sample).

No `detsim` is needed in the usual case: Rivet never uses Delphes (`detsim` is `none`), and a
CutLang analysis uses the enabled detector whose `experiment` is the analysis's experiment
(its `experiment` field, or the prefix of its name: `CMS-SUS-19-006` -> `CMS`). Write
`detsim: <detector name>` only to override that, e.g. to choose between two cards of one experiment. Delphes runs once per (point, detsim) and is shared by all CutLang analyses;
Rivet runs once per point with all routines of that sqrt(s).

### Earlier config style (kagan-dev)

The config format of the `kagan-dev` branch is still accepted (`.test/config_legacy.yml`):

* `parameters` as `{name, index}`; `index` must be the SLHA placeholder that position fills
  (value *i* of *n* fills `M{n-1-i}`), otherwise the run stops instead of filling the wrong mass;
* `detsim` may be left out (as in the current style): the detector is the one whose
  `experiment` (or name) equals the analysis's experiment;
* Rivet routine under `config.analysis` (same as `config.routine`);
* `recasters` and `detectors[].enabled` switch tools and detectors off;
* a sample whose process is not under `processes` is skipped with a WARNING (a typo in a
  point list, e.g. a wrong number of masses, is still an error).

## Generators

**MG5PY8**: MadGraph5_aMC@NLO generates the sparticle pair plus `extrajet` matrix-element
jets (MLM matching), Pythia8 showers; the LHE file is kept.

**Pythia8** standalone (`workflow/wrappers/pythia8/`, off in `config/config.yml`): Pythia8
reads the same SLHA template (masses filled the same way) and produces the sparticle pairs of
the topology's MadGraph process card with its built-in SUSY 2 -> 2 processes. The pair kind
(e.g. `SUSY:qg2squarkgluino` for TGQ) is switched on explicitly and the sparticles are
listed in `SUSY:idVecA/idVecB`; events whose hard-process pair is not in the card (for T2
e.g. `~u_L ~d_L*`, for `p p > n1 n2` also `n1 n1`, `n2 n2`) are vetoed, and the cross
section in the HepMC file is `sigmaGen x` accepted fraction. Decays come from the SLHA decay
table; squarks or gluinos that the template declares stable (`DECAY <id> 0.0` without
channels, e.g. `~u_R`, `~d_R` in T2 and TGQ) get their decays computed by Pythia, because a
stable coloured particle cannot be hadronised. Differences to MG5PY8: no LHE, no matrix-element jets (`extrajet` is ignored, jets
come from the shower), MadGraph `$` / `/` exclusions are not applied, and SM particle masses
and decays are Pythia's own (`SLHA:minMassSM = 1000`, because the MadGraph templates give SM
widths without branching ratios; this also ignores SLHA Higgs masses, e.g. a non-125 GeV
`h` in a template). Only `import model MSSM_SLHA2` topologies are supported; for other
processes Pythia8 is skipped when the job list is built (with a note).
Like MadGraph, a second `generate` line starts a new process list, so only the pairs after
the last `generate` are used (`T2left`, `TChiQorig` have several `generate` lines; check
these cards).

## How the efficiencies are computed

**Rivet** (`workflow/scripts/rivet_to_embake.py`):
`eff(SR) = sumW(/RAW/<routine>/<SR>) / sumW(/_EVTCOUNT)`, nominal weight only (paths with `[`
are skipped). `/RAW/` objects are the pre-`finalize()` copies, so the routine's normalisation
does not matter. The routine must book one `Counter` per signal region.
Uses the `yoda` Python module if present, otherwise a built-in text-YODA parser.

**CutLang** (`workflow/scripts/cutlang_to_embake.py`): numerator = last `cutflow` bin of each
region without bins, and each `bincounts` bin of a binned region (named by `bin_names`; the
binned region itself is not an SR); denominator = the weight CutLang summed
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
stop with a clear error, and so does `T2ttoff_2L` (its proc card has no `import model`).
`extrajet: N` adds `j` ... `j`×N to every process line, before `$` / `/` exclusions and `,`
decay chains (the `@N` tag and comments are dropped). Cards that already list their own jet
lines (`SS_direct`, `SS_onestepCC`, `T2bW_2L`, `T2tt_2L`, `TChiQ`, `TChiWH_WToLNu_HToBB`,
`TChiWZ_ZToLL`) need `extrajet: 0`. For `*bias` topologies `JetMatching:nJetMax` in the Pythia8
card is set to the highest jet multiplicity of the process card.

Found in the first real run (T2) and handled by the wrapper:

* **Stable light squarks.** Several templates (T2, TGQ, ...) declare light squarks stable
  (`DECAY 2000001 0.0` without channels, e.g. `~u_R`, `~d_R` in T2). MadGraph produces them
  and Pythia cannot hadronise a stable coloured particle: about half of the T2 events failed
  ('unknown particle code', junction errors) and were dropped, i.e. the sample was silently
  biased to the left-handed squarks. Light (< 10 TeV) squarks and gluinos with such a block
  get `DECAY <id> auto`, so MadGraph computes widths and branching ratios.
  em-creator's templates have the same blocks.
* **Decoupled gluino.** With MLM matching MadGraph could not cluster extra-jet diagrams with a
  (350 TeV) t-channel gluino ("Clustering failed in cluster.f", the run stopped). When the
  gluino is heavier than 10 TeV and not produced, `/ go` is added to every process line.
* **Cross section in the HepMC file.** The MG5aMC-PY8 interface writes no cross section, so
  Rivet's `finalize()` scaled with garbage. The matched cross section from the MadGraph output
  is written into every event (`C` line). The efficiencies never depended on it (`/RAW/`).

A standalone test lives in `workflow/wrappers/mg5amcnlo/test/`.

## Status

The whole chain was run with the real tools on one T2 point (610/120 GeV, 1 extra jet for
MG5PY8, 500 events per generator; Oct 2026, built from source in a plain Linux container):
MadGraph5_aMC@NLO 3.6.7, Pythia 8.318 (+ MG5aMC_PY8_interface 1.3, HepMC 2.06.11), Delphes
(master, 2026-10), CutLang (master, 2026-10), ROOT 6.40 (pip `root`), Rivet 3.1 (dev, 2019) +
YODA 1.8.0 + FastJet 3.5.2, routine `ATLAS_2016_I1458270` built as a local plugin
(`rivet_analysis_path`).

| step | mock | real |
|---|---|---|
| MG5 + Pythia8 | OK | OK: 500 LHE events, 326 after MLM matching, matched sigma 0.343 pb |
| Pythia8 standalone | OK | OK: 500 events, sigma 0.46 pb; also TGQ, TChiWZ |
| Delphes | OK | OK (CMS card) |
| CutLang | OK | OK: CMS-SUS-19-006, 174 SR efficiencies summing to the preselection efficiency (0.47-0.48 for both generators) |
| Rivet | OK | OK: efficiencies equal Rivet's own cut-flow (e.g. SR2jl 27/500); finalised yields consistent with sigma x L x eff |
| extraction + `.embaked` | OK (unit tests) | OK |

Not yet done: a scan (many points), comparison with published SModelS maps, the cluster
profile with the real tools, Rivet 4 / YODA 2 (the extraction reads both formats).
Note for local installations: MG5aMC_PY8_interface 1.3 calls `Pythia::init()` twice, which
crashes with Pythia 8.318 in matched runs (the replaced LHE reader stays registered); use a
Pythia version the interface supports (e.g. the conda-forge pair) or patch Pythia's
`BeamSetup.cc`.
