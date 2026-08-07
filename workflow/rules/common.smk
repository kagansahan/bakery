import os
from snakemake.utils import validate

schema_path = os.path.join(workflow.current_basedir, "../schemas/config.schema.yml")
validate(config, schema=schema_path)

AVAILABLE_GENERATORS = []
AVAILABLE_RECASTERS = []
AVAILABLE_DETECTORS = []

ACTIVE_RECASTERS = [r["name"] for r in config.get("recasters", []) if r.get("enabled", False)]
ACTIVE_GENERATORS = [g["name"] for g in config.get("generators", []) if g.get("enabled", False)]
ACTIVE_DETECTORS  = [d["name"] for d in config.get("detectors", []) if d.get("enabled", True)]

manifest = []

for sample in config.get("samples", []):
    process = sample["process"]
    proc_info = next((p for p in config["processes"] if p["name"] == process), None)
    if not proc_info: continue
    
    sqrts_val = proc_info.get("sqrts", 13.0)
    sqrts = str(sqrts_val).replace(".", "p")
    param_names = [p["name"] for p in proc_info.get("parameters", [])]
    
    points = sample.get("points", [])
    if not points and "scan" in sample:
        points = [[600.0, 0.0], [1000.0, 400.0], [1400.0, 800.0]]
        
    for pt in points:
        param_pt = "_".join([str(v).replace(".", "p") for v in pt])
        param_dict = dict(zip(param_names, pt))
        param_values = pt
        
        for generator in ACTIVE_GENERATORS:
            for ana in config.get("analyses", []):
                if ana.get("sqrts") != sqrts_val:
                    continue
                
                analysis = ana["name"]
                detector = ana.get("experiment", "NONE")
                
                if detector != "NONE" and detector not in ACTIVE_DETECTORS:
                    continue
                
                recasting_tools = [r["tool"] for r in ana.get("recasting", [])] or ["NONE"]
                
                for tool in recasting_tools:
                    if tool != "NONE" and tool not in ACTIVE_RECASTERS: 
                        continue
                        
                    manifest.append({
                        "sqrts": sqrts,
                        "process": process,
                        "generator": generator,
                        "detector": detector,
                        "analysis": analysis,
                        "recaster": tool,
                        "param_pt": param_pt,
                        "param_dict": param_dict,
                        "param_values": param_values,
                        "param_names": param_names
                    })

def get_all_outputs(wildcards):
    targets = set()
    
    for rule in workflow.rules:
        if rule.name == "all": 
            continue
            
        for out in rule.output:
            out_pattern = str(out)
            
            clean_pattern = re.sub(r'\{([A-Za-z0-9_]+),[^}]+\}', r'{\1}', out_pattern)
            found_wildcards = re.findall(r'\{([A-Za-z0-9_]+)\}', clean_pattern)
            
            if not found_wildcards:
                targets.add(clean_pattern)
                continue
            
            for combo in manifest:
                if not all(w in combo for w in found_wildcards):
                    continue
                
                valid_for_rule = True
                for wc_name, constraint_regex in rule.wildcard_constraints.items():
                    if wc_name in combo:
                        if not re.fullmatch(constraint_regex, str(combo[wc_name])):
                            valid_for_rule = False
                            break
                
                if not valid_for_rule:
                    continue
                
                format_dict = {w: combo[w] for w in found_wildcards}
                targets.add(clean_pattern.format(**format_dict))
                
    return list(targets)

def get_manifest_item(w):
    for entry in manifest:
        if entry["process"] == w.process and entry["param_pt"] == w.param_pt:
            if hasattr(w, "analysis") and entry["analysis"] != w.analysis:
                continue
            if hasattr(w, "generator") and entry["generator"] != w.generator:
                continue
            if hasattr(w, "recaster") and entry["recaster"] != w.recaster:
                continue
            return entry
    return {}

def get_process(w): return w.process
def get_sqrts(w): return float(w.sqrts.replace("p", "."))
def get_nevents(w): return config.get("nevents", 10000)
def get_param_values(w): return get_manifest_item(w).get("param_values", [])
def get_extrajets(w):
    proc_info = next((p for p in config.get("processes", []) if p["name"] == w.process), None)
    return proc_info.get("extrajet", 0) if proc_info else 0
