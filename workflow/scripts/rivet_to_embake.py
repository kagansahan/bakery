import os

with open(snakemake.input.out, "r", encoding="utf-8") as f:
    first_line = f.readline().strip()

with open(snakemake.output.embake, "w") as out:
    out.write(first_line + f" (EMBAKE from {snakemake.input.out})\n")
