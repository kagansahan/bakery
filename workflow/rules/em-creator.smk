def get_embake_inputs(w):
    inputs = []
    for entry in manifest:
        if (entry["process"] == w.process and
            entry["generator"] == w.generator and
            entry["recaster"] == w.recaster and
            entry["analysis"] == w.analysis and
            entry["sqrts"] == w.sqrts):
            
            path = f"results/{entry['sqrts']}/{entry['process']}/{entry['param_pt']}/{entry['generator']}.{entry['recaster']}.{entry['analysis']}.embake"
            if path not in inputs:
                inputs.append(path)
    return inputs

rule create_em:
    input:
        get_embake_inputs
    output:
        embake="results/{sqrts}/{process}/{generator}.{recaster}.{analysis}.embaked"
    script:"../scripts/create_em.py"
