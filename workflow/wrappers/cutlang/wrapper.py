import os

adl_file = snakemake.params.adl_file

with open(snakemake.input.root, "r", encoding="utf-8") as f:
    first_line = f.readline().strip()

with open(snakemake.output.out, "w") as out:
    out.write(first_line + f" (Cutlang: adl_file={adl_file})\n")
