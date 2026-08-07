WRAPPER_DIR = os.path.abspath(os.path.join(workflow.basedir, "wrappers"))
W_RIVET = "file://" + os.path.join(WRAPPER_DIR, "rivet")

def get_rivet_analysis(w):
    for analysis in config.get("analyses", []):
        if analysis["name"] == w.analysis:
            for recasting in analysis.get("recasting", []):
                if recasting.get("tool") == "rivet":
                    return recasting.get("config", {}).get("analysis", "")
    return ""

AVAILABLE_RECASTERS.append("rivet")
if "rivet" in ACTIVE_RECASTERS:
    rule run_rivet:
        input: 
            hepmc="results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz"
        output: 
            out="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.out"
        wildcard_constraints:
            recaster="rivet"
        params:
            analysis = get_rivet_analysis
        wrapper: W_RIVET

    rule rivet_to_embake:
        input: 
            out="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.out"
        output:
            embake="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.embake"
        wildcard_constraints:
            recaster="rivet"
        script:
            "../scripts/rivet_to_embake.py"
