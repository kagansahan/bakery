import os

with open(snakemake.input.hepmc, "r", encoding="utf-8") as f:
    first_line = f.readline().strip()

with open(snakemake.output.root, "w") as out:
    out.write(first_line + f" (Delphes: delphes_card={snakemake.params.delphes_card})\n")
