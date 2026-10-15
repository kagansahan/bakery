"""Snakemake wrapper: Delphes fast detector simulation on a (gzipped) HepMC file."""
import gzip
import os
import shutil
import subprocess
import tempfile

hepmc = snakemake.input.hepmc
out = os.path.abspath(snakemake.output.root)
card = snakemake.params.card
exe = snakemake.params.get("executable", "DelphesHepMC2")
log = snakemake.log[0]

if os.path.exists(out):  # Delphes refuses to overwrite
    os.remove(out)
tmp = tempfile.mkdtemp(prefix="delphes_")
try:
    if hepmc.endswith(".gz"):
        plain = os.path.join(tmp, "events.hepmc")
        with gzip.open(hepmc, "rb") as fi, open(plain, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    else:
        plain = os.path.abspath(hepmc)
    with open(log, "w") as lf:
        # run inside tmp: some cards write auxiliary files to the cwd
        subprocess.run([exe, card, out, plain], cwd=tmp, stdout=lf,
                       stderr=subprocess.STDOUT, check=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
