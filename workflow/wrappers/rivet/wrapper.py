import os

rivet_analysis = snakemake.params.analysis

with open(snakemake.input.hepmc, "r", encoding="utf-8") as f:
    first_line = f.readline().strip()

with open(snakemake.output.out, "w") as out:
    out.write(first_line + f" (Rivet: rivet_analysis={rivet_analysis})\n")
