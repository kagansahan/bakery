"""MOCK of the cutlang wrapper: a histoOut-like ROOT file.

Regions written (mirrors a typical ADL such as CMS-SUS-19-006):
  presel      independent region, cutflow only
  ASR1        independent region, 'presel' + one more cut
  searchbins  DEPENDENT region ('presel' first): cutflow bin 1 counts only
              events that passed presel, plus a bincounts histogram
"""
import os
import zlib

import numpy as np
import uproot

n = uproot.open(snakemake.input.root)["Delphes"].num_entries
rng = np.random.default_rng(zlib.crc32(snakemake.output.histos.encode()))

pre = [n]
for _ in range(4):
    pre.append(int(pre[-1] * rng.uniform(0.6, 0.95)))
asr = pre + [int(pre[-1] * rng.uniform(0.2, 0.5))]
npre = pre[-1]
bins = rng.multinomial(int(npre * 0.8), [0.4, 0.3, 0.2, 0.1])
dep = [npre, npre]  # bin1: only presel-passing events reach it; bin2: 'presel' node


def h(values, labels):
    edges = np.arange(len(values) + 1) + 0.5
    return (np.asarray(values, dtype=np.float64), edges)


with uproot.recreate(snakemake.output.histos) as f:
    f["presel/cutflow"] = h(pre, None)
    f["ASR1/cutflow"] = h(asr, None)
    f["searchbins/cutflow"] = h(dep, None)
    f["searchbins/bincounts"] = h(bins, None)
with open(snakemake.log[0], "w") as f:
    f.write(f"MOCK CutLang adl={os.path.basename(snakemake.params.adl_file)} events={n}\n")
