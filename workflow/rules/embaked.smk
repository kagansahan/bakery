def embake_inputs(w):
    sq = w.sqrts
    return sorted({
        f"{RES}/{j['sqrts']}/{j['process']}/{j['param_pt']}/"
        f"{j['generator']}.{j['tool']}.{j['analysis']}.embake"
        for j in jobs()
        if j["sqrts"] == sq and j["process"] == w.process and j["generator"] == w.generator
        and j["tool"] == w.tool and j["analysis"] == w.analysis
    })


# Merge all mass points into one em-creator compatible .embaked file
rule create_em:
    input:
        embake_inputs,
    output:
        RES + "/{sqrts}/embaked/{analysis}.{process}.{generator}.{tool}.embaked",
    log:
        LOGS + "/{sqrts}/embaked/{analysis}.{process}.{generator}.{tool}.log",
    script:
        "../scripts/create_em.py"
