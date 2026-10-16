# One Delphes run per (point, generator, detector card); the ROOT file is
# shared by every CutLang analysis that asks for the same detsim.
rule run_delphes:
    input:
        hepmc=RES + "/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz",
    output:
        root=RES + "/{sqrts}/{process}/{param_pt}/delphes/{generator}.{detsim}.root",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.{detsim}.delphes.log",
    params:
        card=lambda w: os.path.abspath(DETECTORS[w.detsim]["card"]),
        executable=lambda w: DETECTORS[w.detsim].get("executable", "DelphesHepMC2"),
    wrapper:
        wrapper_path("delphes")
