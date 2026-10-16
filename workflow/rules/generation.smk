# MadGraph5_aMC@NLO + Pythia8 in one job. The LHE file is kept as an
# explicit output so that it is visible to the workflow and can be reused.
rule run_mg5py8:
    output:
        hepmc=RES + "/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz",
        lhe=RES + "/{sqrts}/{process}/{param_pt}/{generator}.events.lhe.gz",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.mg5.log",
    wildcard_constraints:
        generator="MG5PY8",
    params:
        process_name=lambda w: w.process,
        sqrt=lambda w: point(w)["sqrts_val"],
        nevents=lambda w: point(w)["nevents"],
        extrajets=lambda w: point(w)["extrajet"],
        parameter_point=lambda w: point(w)["masses"],
        seed=seed,
        shower="Pythia8",
    wrapper:
        wrapper_path("mg5amcnlo")


# Pythia8 standalone: hard process, shower and hadronisation in Pythia8 (no LHE).
rule run_pythia8:
    output:
        hepmc=RES + "/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.pythia8.log",
    wildcard_constraints:
        generator="Pythia8",
    params:
        process_name=lambda w: w.process,
        sqrt=lambda w: point(w)["sqrts_val"],
        nevents=lambda w: point(w)["nevents"],
        extrajets=lambda w: point(w)["extrajet"],
        parameter_point=lambda w: point(w)["masses"],
        seed=seed,
    wrapper:
        wrapper_path("pythia8")
