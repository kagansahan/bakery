import os
os.makedirs(os.path.dirname(snakemake.output.embake), exist_ok=True)

with open(snakemake.output.embake, "w") as out:
    for fname in snakemake.input:
        with open(fname, "r") as inf:
            line = inf.readline().strip()
            if line:
                out.write(line + "\n")
