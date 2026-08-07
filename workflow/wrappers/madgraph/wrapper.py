import os

process = snakemake.params.process_name
nevents = snakemake.params.nevents
sqrt = snakemake.params.sqrt
extrajets = snakemake.params.extrajets
shower = snakemake.params.shower
masses = snakemake.params.masses

os.makedirs(os.path.dirname(snakemake.output.hepmc), exist_ok=True)

with open(snakemake.output.hepmc, "w") as f:
    f.write(f"MG5PY8: (process={process}, sqrts={sqrt}, extrajets={extrajets},shower={shower} masses={masses}, nevents={nevents})\n")
