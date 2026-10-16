"""MOCK of the delphes wrapper: a ROOT file with a 'Delphes' tree of N events."""
import gzip
import re

import numpy as np
import uproot

with gzip.open(snakemake.input.hepmc, "rt") as f:
    n = int(re.search(r"nevents=(\d+)", f.read()).group(1))
with uproot.recreate(snakemake.output.root) as f:
    f["Delphes"] = {"Event.Weight": np.ones(n, dtype=np.float64)}
with open(snakemake.log[0], "w") as f:
    f.write(f"MOCK Delphes card={snakemake.params.card} events={n}\n")
