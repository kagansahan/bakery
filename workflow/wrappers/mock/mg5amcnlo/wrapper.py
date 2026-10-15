"""MOCK of the mg5amcnlo wrapper: writes tiny gzipped HepMC2/LHE text files."""
import gzip

p = snakemake.params
n = int(p.nevents)
header = (f"# MOCK process={p.process_name} sqrts={p.sqrt} masses={list(p.parameter_point)} "
          f"extrajets={p.extrajets} seed={p.get('seed', 0)} nevents={n}\n")
with gzip.open(snakemake.output.hepmc, "wt") as f:
    f.write("HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n")
    f.write(header)
    f.write("HepMC::IO_GenEvent-END_EVENT_LISTING\n")
with gzip.open(snakemake.output.lhe, "wt") as f:
    f.write('<LesHouchesEvents version="3.0">\n<!--\n' + header + "-->\n</LesHouchesEvents>\n")
with open(snakemake.log[0], "w") as f:
    f.write("MOCK MG5: " + header)
