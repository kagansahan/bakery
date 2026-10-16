# Rivet runs ONCE per (point, generator) with every routine needed at this
# sqrts, so the HepMC file is read and the jets clustered only once.
rule run_rivet:
    input:
        hepmc=RES + "/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz",
    output:
        yoda=RES + "/{sqrts}/{process}/{param_pt}/rivet/{generator}.yoda.gz",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.rivet.log",
    params:
        analyses=rivet_routines,
        analysis_path=config.get("rivet_analysis_path", ""),
        # off by default: Rivet then checks that the HepMC beams match the routine
        ignore_beams=config.get("rivet_ignore_beams", False),
    wrapper:
        wrapper_path("rivet")


rule rivet_to_embake:
    input:
        yoda=RES + "/{sqrts}/{process}/{param_pt}/rivet/{generator}.yoda.gz",
    output:
        embake=RES + "/{sqrts}/{process}/{param_pt}/{generator}.rivet.{analysis}.embake",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.{analysis}.rivet_to_embake.log",
    params:
        masses=lambda w: point(w)["masses"],
        routine=lambda w: recast(w, "rivet")["recast"]["config"]["routine"],
        sr_map=lambda w: recast(w, "rivet")["recast"]["config"].get("sr_map", {}),
    conda:
        "../envs/yoda.yaml"
    script:
        "../scripts/rivet_to_embake.py"
