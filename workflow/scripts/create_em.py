import os
import ast
import time
from datetime import datetime

wc = snakemake.wildcards

points = {}
for fname in snakemake.input:
    param_pt = os.path.basename(os.path.dirname(fname))            
    masses = tuple(float(v.replace("p", ".")) for v in param_pt.split("_"))
    with open(fname) as f:
        body = "".join(line for line in f if not line.lstrip().startswith("#"))
    effs = ast.literal_eval(body.split(": ", 1)[1])
    if effs:                                 
        effs.setdefault("__t__", datetime.fromtimestamp(os.path.getmtime(fname))
                                         .strftime("%Y-%m-%d_%H:%M:%S"))
        points[masses] = effs

n_srs = len({sr for effs in points.values() for sr in effs if not sr.startswith("__")})
sqrts = wc.sqrts.replace("p", ".")

with open(snakemake.output.embaked, "w") as f:
    f.write(f"# EM-Baked {time.asctime()}. {len(points)} points, "
            f"{n_srs} signal regions, {wc.recaster}(emCreator)\n")
    f.write(f"# topology: {wc.process}, analysis: {wc.analysis}, "
            f"sqrts: {sqrts}, generator: {wc.generator}\n")
    f.write("{")
    for masses, effs in points.items():
        f.write(f"{masses}: {effs}, \n")
    f.write("}\n")

with open(snakemake.log[0], "w") as log:
    log.write(f"{len(points)} of {len(snakemake.input)} points written to {snakemake.output.embaked}\n")