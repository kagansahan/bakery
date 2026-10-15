"""Snakemake wrapper: run CutLang (CLA) with one ADL file on a Delphes ROOT file.

CLA writes histoOut-<adl name>.root into its working directory; we run it in
a temporary directory and move that file to the Snakemake output.
"""
import glob
import os
import shutil
import subprocess
import tempfile

root = os.path.abspath(snakemake.input.root)
adl = snakemake.params.adl_file
fmt = snakemake.params.get("input_format", "DELPHES")
exe = snakemake.params.get("executable", "CLA")
out = os.path.abspath(snakemake.output.histos)

tmp = tempfile.mkdtemp(prefix="cutlang_")
try:
    # copy the ADL next to the run so relative table/function includes resolve
    shutil.copy(adl, tmp)
    adl_local = os.path.join(tmp, os.path.basename(adl))
    cmd = [exe, root, fmt, "-i", adl_local]
    with open(snakemake.log[0], "w") as lf:
        lf.write(" ".join(cmd) + "\n")
        lf.flush()
        subprocess.run(cmd, cwd=tmp, stdout=lf, stderr=subprocess.STDOUT, check=True)
    found = glob.glob(os.path.join(tmp, "histoOut*.root"))
    if len(found) != 1:
        raise RuntimeError(f"expected one histoOut*.root from CutLang, found {found}; "
                           f"see {snakemake.log[0]}")
    shutil.move(found[0], out)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
