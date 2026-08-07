**Bakery** is an attempt to create a Snakemake-based version of the [em-creator](https://github.com/SModelS/em-creator) project. It aims to make particle physics simulation steps—such as event generation, detector simulation, and recasting.
Bu branch sadece bir skeleton ve taslak icerir
>  *Note: This branch contains only a skeleton and draft. This README and the documentation are still under active development, and the workflow cannot run on HTCondor or SLURM yet.*

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
