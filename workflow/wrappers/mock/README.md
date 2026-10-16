Mock twins of the real wrappers, selected with `mode: mock` in the config.
They run no physics. They write files in the same *formats* as the real tools
(gzipped HepMC/LHE text, a Delphes ROOT tree, a CutLang histoOut ROOT file
with region directories / cutflow / bincounts, a text YODA file with
/_EVTCOUNT and /RAW counters), so that the workflow graph and the efficiency
extraction scripts can be tested without MadGraph, Delphes, CutLang or Rivet.
Numbers are pseudo-random but reproducible (seeded from the file names).
