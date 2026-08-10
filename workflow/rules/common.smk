import os
from snakemake.utils import validate

schema_path = os.path.join(workflow.current_basedir, "../schemas/config.schema.yml")
validate(config, schema=schema_path)

AVAILABLE_GENERATORS = []
AVAILABLE_RECASTERS = []
AVAILABLE_DETECTORS = []

CONFIG_GENERATORS = [g["name"] for g in config.get("generators", [])]
CONFIG_DETECTORS = [d["name"] for d in config.get("detectors", [])]
CONFIG_RECASTERS = [r["name"] for r in config.get("recasters", [])]

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
        for generator in CONFIG_GENERATORS:

            for ana in config.get("analyses", []):
                if ana.get("sqrts") != sqrts_val: continue
                
                analysis = ana["name"]
                detector = ana.get("experiment", "NONE")
                
                if detector != "NONE" and detector not in CONFIG_DETECTORS: 
                    detector = "NONE"
                
                recasting_tools = [r["tool"] for r in ana.get("recasting", [])] or ["NONE"]
                
                for tool in recasting_tools:
                    if tool != "NONE" and tool not in CONFIG_RECASTERS: 
                        tool = "NONE"
                        
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
    all_targets = set()
    
    for rule in workflow.rules:
        if rule.name == "all": 
            continue
            
        constraints = getattr(rule, "wildcard_constraints", {}) or {}
        
        for output_pattern in rule.output:
            pattern_str = str(output_pattern)
            clean_pattern = re.sub(r'\{([^,}]+),[^}]+\}', r'{\1}', pattern_str)
            
            if "{" not in clean_pattern: 
                continue

            req_wcs = re.findall(r'\{([^}]+)\}', clean_pattern)
            
            for entry in manifest: 
                
                if "generator" in req_wcs and entry["generator"] not in ACTIVE_GENERATORS: 
                    continue
                if "detector" in req_wcs and entry["detector"] not in ACTIVE_DETECTORS: 
                    continue
                if "recaster" in req_wcs and entry["recaster"] not in ACTIVE_RECASTERS: 
                    continue
                    
                if any(entry.get(wc) == "NONE" for wc in req_wcs):
                    continue

                is_valid = True
                for wc_name, c_val in constraints.items():
                    if wc_name in entry:
                        clean_regex = str(c_val).strip('^$')
                        if not re.search(clean_regex, str(entry[wc_name])):
                            is_valid = False
                            break
                            
                if not is_valid:
                    continue  
                    
                try:
                    all_targets.add(clean_pattern.format(**entry))
                except KeyError:
                    pass
                    
    return list(all_targets)

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
def get_param_values(w): return get_manifest_item(w).get("param_values", [])
def get_nevents(w):
    for s in config.get("samples", []):
        if s.get("process") == w.process:
            return s["nevents"]
            
def get_extrajets(w):
    for p in config.get("processes", []):
        if p.get("name") == w.process:
            return p.get("extrajet", 0)
