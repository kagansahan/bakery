import os

WRAPPER_DIR = os.path.abspath(os.path.join(workflow.basedir, "wrappers"))
W_MADGRAPH = "file://" + os.path.join(WRAPPER_DIR, "madgraph")

AVAILABLE_GENERATORS.append("MG5PY8")
if "MG5PY8" in ACTIVE_GENERATORS: 
    rule run_mg5py8:
        output:
            hepmc="results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz"
        params:
            process_name=get_process,
            nevents=get_nevents,
            sqrt=get_sqrts,
            extrajets=get_extrajets,
            shower="Pythia8",
            masses=get_param_values
        wrapper: W_MADGRAPH

W_PYTHIA8 = "file://" + os.path.join(WRAPPER_DIR, "pythia8")

AVAILABLE_GENERATORS.append("PYTHIA8")
if "PYTHIA8" in ACTIVE_GENERATORS: 
    rule run_pythia8:
        output:
            hepmc="results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz"
        params:
            process_name=get_process,
            nevents=get_nevents,
            sqrt=get_sqrts,
            extrajets=get_extrajets,
            shower="Pythia8",
            masses=get_param_values
        wrapper: W_PYTHIA8
