WRAPPER_DIR = os.path.abspath(os.path.join(workflow.basedir, "wrappers"))
W_CUTLANG = "file://" + os.path.join(WRAPPER_DIR, "cutlang")

def get_adl_file(w):
    for analysis in config.get("analyses", []):
        if analysis["name"] == w.analysis:
            for recasting in analysis.get("recasting", []):
                if recasting.get("tool") == "cutlang":
                    return recasting.get("config", {}).get("adl_file", "")
    return ""

def get_cutlang_input(w):
    detector = "NONE"
    for ana in config.get("analyses", []):
        if ana["name"] == w.analysis:
            detector = ana.get("experiment", "NONE")
            break
    return f"results/{w.sqrts}/{w.process}/{w.param_pt}/delphes/{w.generator}.{detector}.root"

AVAILABLE_RECASTERS.append("cutlang")
if "cutlang" in ACTIVE_RECASTERS:
    rule run_cutlang:
        input:
            root=get_cutlang_input
        output:
            out="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.out"
        params:
            adl_file=get_adl_file
        wildcard_constraints:
            recaster="cutlang"
        wrapper: W_CUTLANG

    rule cutlang_to_embake:
        input:
            out="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.out"
        output:
            embake="results/{sqrts}/{process}/{param_pt}/{generator}.{recaster}.{analysis}.embake"
        wildcard_constraints:
            recaster="cutlang"
        script:
            "../scripts/cutlang_to_embake.py"
