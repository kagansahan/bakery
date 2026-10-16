"""MOCK of the pythia8 wrapper: writes a tiny gzipped HepMC2 text file."""
import gzip

p = snakemake.params
n = int(p.nevents)
header = (f"# MOCK Pythia8 process={p.process_name} sqrts={p.sqrt} "
          f"masses={list(p.parameter_point)} seed={p.get('seed', 0)} nevents={n}\n")
with gzip.open(snakemake.output.hepmc, "wt") as f:
    f.write("HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n")
    f.write(header)
    f.write("HepMC::IO_GenEvent-END_EVENT_LISTING\n")
with open(snakemake.log[0], "w") as f:
    f.write("MOCK Pythia8: " + header)
