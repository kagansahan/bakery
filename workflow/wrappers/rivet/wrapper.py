"""Snakemake wrapper: run several Rivet routines in one pass over a HepMC file.

  rivet -a A -a B [--ignore-beams] [--analysis-path DIR] [-x XS] -o out.yoda.gz in.hepmc.gz
"""
import os
import subprocess

p = snakemake.params
analyses = p.analyses if isinstance(p.analyses, (list, tuple)) else [p.analyses]
if not analyses:
    raise ValueError("no Rivet analyses given")

cmd = ["rivet"]
for a in analyses:
    cmd += ["-a", a]
if p.get("ignore_beams", True):
    cmd.append("--ignore-beams")
path = p.get("analysis_path", "")
if path:
    cmd += ["--analysis-path", os.path.abspath(path)]
xs = p.get("cross_section", None)
if xs:
    cmd += ["-x", str(xs)]
cmd += ["-o", snakemake.output.yoda, snakemake.input.hepmc]

with open(snakemake.log[0], "w") as lf:
    lf.write(" ".join(cmd) + "\n")
    lf.flush()
    subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, check=True)
