**Bakery** is an attempt to create a Snakemake-based version of the [em-creator](https://github.com/SModelS/em-creator) project. It aims to automate particle physics simulation and recasting steps.

## Installation

**1. Clone the repository:**
```bash
git clone https://github.com/kagansahan/bakery.git
cd bakery
```
**2. Create and activate the Conda environment:**
```bash
conda env create -f environment.yml
conda activate environment-snakemake
```
This environment installs Snakemake and the HTCondor/SLURM plugins.

**3. Test Run:**
To verify that the skeleton works, you can run it in local mode. It will run the workflow from start to finish and create fake output files in the results/ directory without calling any real simulation tools:
```bash
snakemake -s workflow/Snakefile --configfile config/config.yml --cores 1
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

## Wildcards
Wildcards are placeholders that connect Snakemake rules through their input and output files. If a wildcard has the same name in a rule's input and output, Snakemake makes sure their values match. For example, whatever value {generator} gets in the output, it gets the exact same value in the input.

This connection also works across multiple rules. When one rule's output becomes another rule's input, the wildcard values pass through the whole workflow. For instance, the event generation rule makes the {generator}.events.hepmc file. Next, the detector simulation rule takes this file as input and makes the {generator}.{detector}.root output.

```python
rule run_generator:
    output: "results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc"
    params:
        extrajet=get_extrajets

rule run_detector:
    input: "results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc"

    output: "results/{sqrts}/{process}/{param_pt}/delphes/{generator}.{detector}.root"

rule run_recaster:
    input: "results/{sqrts}/{process}/{param_pt}/delphes/{generator}.{detector}.root"
    output: "results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.out"
```

Wildcards also pull values directly from the config file into the rules. Any setting in the config can link to a wildcard. Because of this, if you want to add a new parameter point, a new analysis, or a new tool, you only need to add it to the config file. Snakemake uses the wildcards to find this new data and create the right jobs automatically. You do not have to change the rules at all.

```python
def get_extrajets(wildcards):
    for process in config.get("processes", []):
        if process["name"] == wildcards.process:
            return process.get("extrajets", 0)
            
    return 0
```

The main wildcards and parameter variables used in Bakery are as follows:

| Wildcard / Variable | Description | Example Value |
|---|---|---|
| `{sqrts}` | Center-of-mass energy | `13p0` (13.0 TeV) |
| `{process}` | Physics process | `T2`, `T1` |
| `{param_pt}` | Parameter point (format in filename) | `1400p0_200p0` |
| `{param_dict}` | Dictionary containing parameter names and values | `{"MSQUARK": 1400.0, "MLSP": 200.0}` |
| `{param_values}` | List containing only parameter values | `[1400.0, 200.0]` |
| `{param_names}` | List containing only parameter names | `["MSQUARK", "MLSP"]` |
| `{generator}` | Event generator | `MG5PY8`, `Pythia8` |
| `{detector}` | Detector | `ATLAS`, `CMS` |
| `{analysis}` | Analysis name | `ATLAS-SUSY-2018-22` |
| `{recaster}` | Recasting tool | `rivet`, `cutlang` |

## Wrappers and Scripts

The Bakery workflow uses two Snakemake mechanisms: wrappers and scripts. 

### Wrappers
A wrapper is a standard Python script that runs a specific tool (like MadGraph, Delphes, Rivet, or CutLang) and links its inputs and outputs to Snakemake. Wrappers are called with the `wrapper:` command and are kept in the `workflow/wrappers/<tool_name>/` folder. This structure makes them easy to reuse. Bakery uses wrappers for event generation, detector simulation, and recasting. (Note: Right now, these wrappers do not run the real tools; they only produce fake outputs to test the workflow).

#### Available Wrappers
Currently, Bakery comes with two available wrappers: `delpheshepmc2` (located in `wrappers/DelphesHepMC2`) and `mg5amcnlo` (located in `wrappers/mg5amcnlo`). More detailed documentation regarding these wrappers will be found here. Note: These wrappers are not integrated into the main workflow yet.

Each wrapper includes a `Snakefile` within its `test` directory. This allows them to be executed and tested independently of the main workflow, and serves as a practical example for future use. To run a test, navigate to the test directory and execute the following command:

```bash
snakemake --cores <number of cores> --use-conda
```

### Scripts
Scripts are a lighter and more flexible method. They are independent Python files called directly with the `script:` command. Instead of running external tools, scripts handle helper tasks like data conversion, file merging, or format changes. This keeps the rule files clean and easy to read. In Bakery, scripts are used to convert recasting outputs into the EMBAKE format (`cutlang_to_embake.py` and `rivet_to_embake.py`) and `scripts/em-creator.py` to merge EMBAKE files.