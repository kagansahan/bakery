"""
Turn the CutLang output (histoOut-*.root) of one analysis into efficiencies.

CutLang writes one TDirectory per ADL region. Inside:
  cutflow    TH1D, bin 1 = "all Events" (filled with weight 1), bin k+1 = after
             the k-th command of the region (filled with the event weight)
  bincounts  TH1D, one bin per `bin` statement (only if the region has bins)

Which event weight CutLang uses depends on the input format (CutLang source,
CLA/delphes.C and CLA/DELPHES2.C):
  DELPHES   every event gets weight 1; Event.Weight is ignored
  DELPHES2  the weight is Event.Weight from the Delphes tree

Denominator: whatever CutLang summed for *every* generated event, i.e. the
number of events in the Delphes tree (DELPHES) or the sum of Event.Weight
(DELPHES2). Samples with non-uniform weights (the *bias topologies) are only
correct with DELPHES2; with DELPHES the weights would be silently dropped, so
that combination is an error.

We deliberately do NOT use a cutflow bin for the denominator: in a region that
depends on another one (e.g. `region searchbins` starting with `presel`),
CutLang returns before filling bin 1 for events that failed the parent region,
so bin 1 (and bin 2) count only the events that passed the parent.

Numerator: the last cutflow bin of a region (= events passing every command;
trailing `histo` commands always pass), and each bincounts bin.
"""
import json
import sys

import numpy as np
import uproot


def delphes_weights(delphes_file):
    """Number of events and the Event.Weight array (None if there is no such branch)."""
    with uproot.open(delphes_file) as f:
        tree = f["Delphes"]
        n = tree.num_entries
        keys = set(tree.keys(recursive=True))
        for bname in ("Event/Event.Weight", "Event.Weight"):
            if bname in keys:
                # arrays([...]) instead of tree[bname]: uproot would split the '.'
                w = tree.arrays([bname], library="np")[bname]
                w = np.concatenate([np.atleast_1d(x) for x in w]) if w.dtype == object else w
                return n, np.asarray(w, dtype=float)
    return n, None


def denominator(delphes_file, input_format="DELPHES"):
    """Sum of the weights CutLang used, over every event in the Delphes tree."""
    n, w = delphes_weights(delphes_file)
    if n == 0:
        raise RuntimeError(f"{delphes_file}: Delphes tree is empty")
    uniform = w is None or len(w) == 0 or np.allclose(w, w[0])
    fmt = input_format.upper()
    if fmt == "DELPHES2":
        if w is None:
            raise RuntimeError(f"{delphes_file}: input format DELPHES2 but no Event.Weight branch")
        return n, float(w.sum())
    if not uniform:
        raise RuntimeError(
            f"{delphes_file}: events carry non-uniform weights (a *bias sample?), but "
            f"CutLang input format {input_format} uses weight 1 for every event. "
            "Set input_format: DELPHES2 for this analysis so CutLang reads Event.Weight.")
    return n, float(n)


def extract(histos_file, delphes_file, exclude_regions=(), bin_names="index",
            input_format="DELPHES"):
    ntot, denom = denominator(delphes_file, input_format)
    if denom <= 0:
        raise RuntimeError(f"{delphes_file}: sum of weights is {denom}")

    effs, cutflows, warnings = {}, {}, []
    with uproot.open(histos_file) as f:
        regions = [k for k, cls in f.classnames(recursive=False, cycle=False).items()
                   if cls.startswith("TDirectory")]
        for region in regions:
            if region in exclude_regions:
                continue
            d = f[region]
            keys = set(d.keys(recursive=False, cycle=False))
            if "cutflow" not in keys:
                continue
            cf = d["cutflow"]
            vals = cf.values()
            labels = list(cf.axis().labels() or [])
            cutflows[region] = {
                "labels": labels, "values": [float(v) for v in vals],
            }
            if len(vals) == 0:
                continue
            effs[region] = float(vals[-1]) / denom
            if vals[0] > ntot:
                warnings.append(f"{region}: cutflow bin 1 ({vals[0]}) > Delphes events ({ntot})")

            if "bincounts" in keys:
                bc = d["bincounts"]
                bvals = bc.values()
                blabels = list(bc.axis().labels() or [])
                for i, v in enumerate(bvals):
                    if bin_names == "label" and i < len(blabels) and blabels[i]:
                        name = f"{region}_" + "_".join(blabels[i].split())
                    else:
                        name = f"{region}_bin{i + 1}"
                    effs[name] = float(v) / denom

    if not effs:
        raise RuntimeError(f"{histos_file}: no region with a cutflow found "
                           f"(excluded: {list(exclude_regions)})")
    return {
        "efficiencies": effs,
        "nevents": int(ntot),
        "sumw": denom,
        "input_format": input_format,
        "diagnostics": {"cutflows": cutflows, "warnings": warnings},
    }


if "snakemake" in globals():
    sm = snakemake  # noqa: F821
    with open(sm.log[0], "w") as log:
        sys.stderr = log
        res = extract(sm.input.histos, sm.input.delphes,
                      list(sm.params.exclude_regions), sm.params.bin_names,
                      sm.params.input_format)
        res["masses"] = list(sm.params.masses)
        res["tool"] = "cutlang"
        for w in res["diagnostics"]["warnings"]:
            print("WARNING:", w, file=log)
        print(f"{len(res['efficiencies'])} signal regions, N={res['nevents']}", file=log)
        with open(sm.output.embake, "w") as f:
            json.dump(res, f, indent=1)
