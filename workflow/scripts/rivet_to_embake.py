"""
Turn the YODA output of one Rivet run into per-signal-region efficiencies.

  efficiency(SR) = sumW( /RAW/<routine>/<counter> ) / sumW( /_EVTCOUNT )

* /RAW/... holds the objects as they were *before* finalize(), so the result
  does not depend on how the routine normalises its output.
* /_EVTCOUNT is the sum of weights of every event Rivet processed.
* paths containing "[" belong to non-nominal weight streams and are skipped.

Uses the `yoda` Python module when available, otherwise a small parser for
the plain-text (optionally gzipped) YODA format, so the script also runs
without a YODA installation.
"""
import gzip
import json
import math
import sys


class TextCounter:
    def __init__(self, path, sumw, sumw2, nent):
        self.path, self._sumw, self._sumw2, self._n = path, sumw, sumw2, nent

    def sumW(self):
        return self._sumw

    def sumW2(self):
        return self._sumw2

    def numEntries(self):
        return self._n


def read_yoda_text(fname):
    """Return {path: TextCounter} for every Counter in a text YODA file."""
    opener = gzip.open if fname.endswith(".gz") else open
    counters, cur, data_started = {}, None, False
    with opener(fname, "rt") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("BEGIN YODA_COUNTER"):
                cur, data_started = line.split()[2], False
                continue
            if line.startswith("END YODA"):
                cur = None
                continue
            if cur is None or not line:
                continue
            if line == "---":
                data_started = True
                continue
            if line.startswith("#") or not data_started:
                continue
            tok = line.split()
            try:
                vals = [float(t) for t in tok]
            except ValueError:
                continue
            if cur not in counters and len(vals) >= 2:
                n = vals[2] if len(vals) > 2 else float("nan")
                counters[cur] = TextCounter(cur, vals[0], vals[1], n)
    return counters


def read_counters(fname):
    try:
        import yoda  # noqa: F401
        aos = yoda.read(fname)
        out = {}
        for path, ao in aos.items():
            is_counter = isinstance(ao, yoda.Counter) if hasattr(yoda, "Counter") \
                else ao.type() == "Counter"
            if is_counter:
                out[path] = ao
        return out, "yoda"
    except ImportError:
        return read_yoda_text(fname), "text-parser"


def extract(fname, routine, sr_map=None):
    sr_map = sr_map or {}
    counters, reader = read_counters(fname)
    if "/_EVTCOUNT" not in counters:
        raise RuntimeError(f"{fname}: no /_EVTCOUNT counter, is this a Rivet output?")
    evt = counters["/_EVTCOUNT"]
    total = evt.sumW()
    if total <= 0:
        raise RuntimeError(f"{fname}: /_EVTCOUNT sumW = {total}")

    prefix = f"/RAW/{routine}/"
    effs, errs = {}, {}
    for path, ao in sorted(counters.items()):
        if not path.startswith(prefix) or "[" in path:
            continue
        name = path[len(prefix):]
        if "/" in name:  # counters inside sub-directories: keep full sub-path
            name = name.replace("/", "_")
        name = sr_map.get(name, name)
        effs[name] = ao.sumW() / total
        errs[name] = math.sqrt(max(ao.sumW2(), 0.0)) / total

    if not effs:
        found = sorted({p.split("/")[2] for p in counters if p.startswith("/RAW/")})
        raise RuntimeError(
            f"{fname}: no nominal Counter under {prefix}. "
            f"Routines with RAW objects in this file: {found}. "
            "The routine must book one Counter per signal region."
        )
    nev = evt.numEntries()
    return {
        "efficiencies": effs,
        "nevents": int(nev) if not math.isnan(nev) else None,
        "sumw": total,
        "diagnostics": {"stat_errors": errs, "reader": reader, "routine": routine},
    }


if "snakemake" in globals():
    sm = snakemake  # noqa: F821
    with open(sm.log[0], "w") as log:
        sys.stderr = log
        res = extract(sm.input.yoda, sm.params.routine, dict(sm.params.sr_map))
        res["masses"] = list(sm.params.masses)
        res["tool"] = "rivet"
        print(f"{len(res['efficiencies'])} signal regions, sumW={res['sumw']}", file=log)
        with open(sm.output.embake, "w") as f:
            json.dump(res, f, indent=1)
