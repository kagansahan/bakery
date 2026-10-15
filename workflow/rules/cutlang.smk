def cutlang_delphes(w):
    ds = recast(w, "cutlang")["recast"]["detsim"]
    return f"{RES}/{w.sqrts}/{w.process}/{w.param_pt}/delphes/{w.generator}.{ds}.root"


rule run_cutlang:
    input:
        root=cutlang_delphes,
    output:
        histos=RES + "/{sqrts}/{process}/{param_pt}/cutlang/{generator}.{analysis}.root",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.{analysis}.cutlang.log",
    params:
        adl_file=lambda w: os.path.abspath(recast(w, "cutlang")["recast"]["config"]["adl_file"]),
        input_format=lambda w: recast(w, "cutlang")["recast"]["config"].get("input_format", "DELPHES"),
        executable=lambda w: recast(w, "cutlang")["recast"]["config"].get("executable", "CLA"),
    wrapper:
        wrapper_path("cutlang")


rule cutlang_to_embake:
    input:
        histos=RES + "/{sqrts}/{process}/{param_pt}/cutlang/{generator}.{analysis}.root",
        delphes=cutlang_delphes,
    output:
        embake=RES + "/{sqrts}/{process}/{param_pt}/{generator}.cutlang.{analysis}.embake",
    log:
        LOGS + "/{sqrts}/{process}/{param_pt}/{generator}.{analysis}.cutlang_to_embake.log",
    params:
        masses=lambda w: point(w)["masses"],
        exclude_regions=lambda w: recast(w, "cutlang")["recast"]["config"].get("exclude_regions", []),
        bin_names=lambda w: recast(w, "cutlang")["recast"]["config"].get("bin_names", "index"),
        # must match what run_cutlang passes to CLA: it decides which weight CutLang used
        input_format=lambda w: recast(w, "cutlang")["recast"]["config"].get("input_format", "DELPHES"),
    conda:
        "../envs/uproot.yaml"
    script:
        "../scripts/cutlang_to_embake.py"
