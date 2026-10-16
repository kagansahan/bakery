"""MOCK of the rivet wrapper: a gzipped text YODA file (YODA2 / Rivet 4 layout).

Contains /_EVTCOUNT, and for every routine two RAW counters, their
finalised (scaled) copies and a non-nominal weight variant '[MUR=2]' that the
extraction must ignore.
"""
import gzip
import re
import zlib

import numpy as np

with gzip.open(snakemake.input.hepmc, "rt") as f:
    n = int(re.search(r"nevents=(\d+)", f.read()).group(1))
rng = np.random.default_rng(zlib.crc32(snakemake.output.yoda.encode()))


def counter(path, sumw, sumw2, nent):
    return (f"BEGIN YODA_COUNTER_V3 {path}\nPath: {path}\nTitle: \nType: Counter\n---\n"
            f"# sumW\t sumW2\t numEntries\n{sumw:.6e}\t{sumw2:.6e}\t{nent:.6e}\n"
            f"END YODA_COUNTER_V3\n\n")


out = [counter("/_EVTCOUNT", n, n, n), counter("/_XSEC", 1.0, 0.0, 1)]
for routine in snakemake.params.analyses:
    for sr in ("SR_A", "SR_B"):
        k = int(rng.binomial(n, rng.uniform(0.01, 0.2)))
        out.append(counter(f"/RAW/{routine}/{sr}", k, k, k))
        out.append(counter(f"/RAW/{routine}/{sr}[MUR=2]", 2 * k, 4 * k, k))
        out.append(counter(f"/{routine}/{sr}", k * 0.123, 0, k))  # finalised
with gzip.open(snakemake.output.yoda, "wt") as f:
    f.write("".join(out))
with open(snakemake.log[0], "w") as f:
    f.write(f"MOCK rivet -a {' -a '.join(snakemake.params.analyses)}  events={n}\n")
