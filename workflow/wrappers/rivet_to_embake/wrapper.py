#!/usr/bin/env python3
"""Snakemake wrapper: Rivet YODA output -> .embake of one parameter point.

One Rivet analysis per file: params.analysis names it. When the YODA file has only one
analysis, params.analysis can be left out.
"""
import gzip                        # For .yoda.gz
import math                        # For isfinite
import os                          # For path, makedirs
import re                          # For YODA parsing
import sys                         # For argv access in _load_snakemake
from datetime import datetime      # For timestamp of embake files


class RivetEmbakeExtractor:
    """
    Reads a Rivet YODA file and writes the efficiencies it contains into
    an .embake file.

    Usage::

        ext = RivetEmbakeExtractor(
            yoda       = "out.yoda.gz",
            embake     = "out.embake",
            param_vals = ["1000", "500"],
            analysis   = "ATLAS_2019_I1718132",       # optional if the file has only one analysis
            filter_str = "SR_C, SR_D",                # optional
        )
        ext.run(log_path="run.log")
    """

    _BLOCK = re.compile(r"^BEGIN (YODA_COUNTER_V\d+) (\S+)\s*$")
    _END = re.compile(r"^END (YODA_COUNTER_V\d+)\s*$")

    def __init__(self, yoda, embake, param_vals, analysis=None, filter_str=""):
        """
        :param yoda:       path to the Rivet .yoda or .yoda.gz file
        :param embake:     path of the .embake file to write
        :param param_vals: list of mass/parameter values, e.g. ["1000", "500"]
        :param analysis:   the Rivet analysis to read, e.g. "ATLAS_2019_I1718132" (one name);
                           may be left out if the file has only one
        :param filter_str: comma separated list of signal regions to skip, e.g. "SR_C, SR_D"
        """
        self.yoda = yoda
        self.embake = embake
        self.param_vals = [str(v) for v in param_vals]
        self.analysis = self._one(analysis)
        self.filter_regions = set(self._as_list(filter_str))
        self.routine = ""                # the analysis read; set by _efficiencies, written to the comment line

    # =========================================================================
    #      Public API
    # =========================================================================

    def run(self, log_path=None):
        """ Does all the work. If log_path is given, stdout/stderr are
            redirected there for the duration of the run.
            :param log_path: file to write logs to, or None to log to stdout
        """
        if log_path:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            with open(log_path, "wt") as log:
                self._redirect(log, self._execute)
        else:
            self._execute()

    @property
    def mass(self) -> str:
        """ the mass/parameter tuple, formatted as CutLang-style string,
            e.g. "(1000,500)" """
        return "(" + ",".join(self.param_vals) + ")"

    # =========================================================================
    #      Main flow
    # =========================================================================

    def _execute(self):
        """ Extracts the efficiencies and writes the .embake file.
            Raises RuntimeError if no efficiencies could be found.
        """
        counters = self._read_counters()
        entries, nevents = self._efficiencies(counters)
        self._info(f"{len(entries)} signal regions of {self.routine}, nevents = {nevents:g}")
        self._write_embake(entries, nevents)
        self._info(f"wrote: {self.embake}")

    # =========================================================================
    #      YODA reading
    # =========================================================================

    def _read_counters(self):
        """ All counters of the file, by path.
            :returns: {path: (sumW, sumW2, numEntries)}
        """
        if not os.path.exists(self.yoda):
            raise RuntimeError(f"cannot find the Rivet output {self.yoda}.")
        opener = gzip.open if self.yoda.endswith(".gz") else open
        counters = {}
        path, row = None, None
        with opener(self.yoda, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                begin = self._BLOCK.match(line)
                if begin:
                    path, row, in_data = begin.group(2), None, False
                    continue
                if path is None:
                    continue
                if line.startswith("---"):
                    in_data = True
                    continue
                if self._END.match(line):
                    if row is not None:
                        counters[path] = row
                    path = None
                    continue
                if in_data and line.strip() and not line.startswith("#"):
                    values = line.split()
                    if len(values) < 3:
                        raise RuntimeError(f"{self.yoda}: counter {path}: expected "
                                           f"'sumW sumW2 numEntries', got {line!r}")
                    row = tuple(float(v) for v in values[:3])
        if not counters:
            raise RuntimeError(f"no counters in {self.yoda} (Rivet 4 / YODA2 text output expected).")
        return counters

    @staticmethod
    def _is_nominal(path):
        """ Weight variations are written as 'NAME[VARIATION]'. """
        return "[" not in path

    def _efficiencies(self, counters):
        """ Efficiency of every signal region of the analysis.
            :returns: entries, nevents
                        entries -- {region name: efficiency}
                        nevents -- number of events Rivet processed
        """
        total = counters.get("/RAW/_EVTCOUNT") or counters.get("/_EVTCOUNT")
        if total is None:
            raise RuntimeError(f"{self.yoda}: no event counter (/RAW/_EVTCOUNT or /_EVTCOUNT).")
        sum_all, _, nevents = total
        if sum_all <= 0:
            raise RuntimeError(f"{self.yoda}: the event counter has sumW = {sum_all:g}.")

        found = {}                       # analysis -> {region: sumW}
        for path, (sumw, _, _) in counters.items():
            if not path.startswith("/RAW/") or not self._is_nominal(path):
                continue
            parts = path[len("/RAW/"):].split("/")
            if len(parts) != 2 or parts[0].startswith("_"):
                continue                 # not <analysis>/<region>: histograms of other kinds, _EVTCOUNT, ...
            analysis, region = parts
            found.setdefault(analysis, {})[region] = sumw

        if not found:
            raise RuntimeError(f"{self.yoda}: no /RAW/<analysis>/<region> counters.")
        if self.analysis:
            if self.analysis not in found:
                self._error(f"no counters for {self.analysis} in {self.yoda}; it has {sorted(found)}")
                raise RuntimeError(f"Rivet analysis not found: {self.analysis}")
            self.routine = self.analysis
        elif len(found) == 1:
            self.routine = next(iter(found))
        else:
            self._error(f"{self.yoda} has several analyses: {sorted(found)}; set params.analysis")
            raise RuntimeError(f"params.analysis is needed: the file has {len(found)} analyses")

        entries = {}
        for region in sorted(found[self.routine]):
            if region in self.filter_regions:
                continue
            eff = found[self.routine][region] / sum_all
            if not math.isfinite(eff):
                raise RuntimeError(f"{self.yoda}: efficiency of {region} is {eff}")
            entries[region] = eff
        if not entries:
            raise RuntimeError(f"no efficiencies found for {self.routine} in {self.yoda}.")
        return entries, nevents

    # =========================================================================
    #      Output writing
    # =========================================================================

    def _write_embake(self, entries, nevents):
        """ Writes the extracted efficiencies to self.embake.
            :param entries: {region: efficiency}, as returned by _efficiencies
            :param nevents: number of events, as returned by _efficiencies
        """
        os.makedirs(os.path.dirname(self.embake) or ".", exist_ok=True)
        nev = str(int(nevents)) if nevents == int(nevents) else str(nevents)
        ts = datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
        self._msg(f"Writing efficiency values for masses {self.mass} to file:\n {self.embake}")
        with open(self.embake, "wt") as f:
            f.write(f"# rivet_to_embake {datetime.now().ctime()}. {len(entries)} signal regions, "
                    f"nevents: {nev}, analysis: {self.routine}, "
                    f"source: {os.path.basename(self.yoda)}\n")
            f.write(f"{self.mass}: {{")
            for key, value in entries.items():
                f.write(f"{self._name(key)!r}: {value!r}, ")
            f.write(f"'__t__':'{ts}', ")
            f.write(f"'__nevents__':{nev}")
            f.write("}")

    # =========================================================================
    #      Helpers
    # =========================================================================

    @staticmethod
    def _name(key):
        """ Region name as written in the file: no quotes or brackets, which would break the literal. """
        return key.replace("'", "").replace('"', "").replace("[", "").replace("]", "").replace(" ", "_")

    @staticmethod
    def _one(value):
        """ One analysis name: 'A' or ['A'] -> 'A'; nothing -> ''. Several are an error. """
        if value is None:
            return ""
        if not isinstance(value, str):
            value = list(value)
            if len(value) > 1:
                raise RuntimeError(f"one analysis only, got {value}")
            value = value[0] if value else ""
        value = str(value).strip()
        if re.search(r"[\s,]", value):
            raise RuntimeError(f"one analysis only, got {value!r}")
        return value

    @staticmethod
    def _as_list(value):
        """ 'A,B' / 'A B' / ['A', 'B'] / [['A'], 'B'] -> ['A', 'B'] """
        if value is None:
            return []
        if isinstance(value, str):
            return [v for v in value.replace(",", " ").split() if v]
        out = []
        for v in value:
            out.extend(RivetEmbakeExtractor._as_list(v))
        return out

    @staticmethod
    def _info(*msg):
        """ Print an info message """
        print(f"[rivet_to_embake] {' '.join(map(str, msg))}")

    @staticmethod
    def _msg(*msg):
        """ Print a normal message """
        print(f"[rivet_to_embake] {' '.join(map(str, msg))}")

    @staticmethod
    def _error(*msg):
        """ Print an error message """
        print(f"[rivet_to_embake] Error: {' '.join(map(str, msg))}")

    @staticmethod
    def _redirect(stream, fn):
        """ Runs fn() with stdout/stderr temporarily redirected to stream.
            :param stream: file-like object to redirect stdout/stderr to
            :param fn:     callable to run under the redirection
        """
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        try:
            fn()
        finally:
            sys.stdout, sys.stderr = old_out, old_err


# ===========================================================================
#  Entry point
# ===========================================================================

def _load_snakemake():
    """ Returns the snakemake object injected by Snakemake's `script:` /
        `wrapper:` directive, or None if run standalone. """
    try:
        return snakemake  # noqa: F821
    except NameError:
        return None


def _named_or_first(files, *names):
    """ A named input/output file; the first one when none of the names is used. """
    for name in names:
        value = getattr(files, name, None)
        if value is not None:
            return str(value)
    if len(files) == 0:
        raise RuntimeError(f"no file given (looked for {', '.join(names)})")
    return str(files[0])


def _parse_cli():
    """ Parses command line arguments for standalone use. """
    import argparse
    p = argparse.ArgumentParser(description='Rivet YODA efficiency extractor.')
    p.add_argument("-i", "--input", help="Rivet .yoda or .yoda.gz file", required=True)
    p.add_argument("-o", "--output", help=".embake file to write", required=True)
    p.add_argument("-m", "--mass", help="mass/parameter values, e.g. 1000 500",
                   nargs="+", required=True)
    p.add_argument("-l", "--log", help="log file to write to", required=True)
    p.add_argument("-a", "--analysis", help="the Rivet analysis to read (default: the only one in the file)",
                   default=None)
    p.add_argument("-f", "--filter", help='signal regions to filter out, e.g. "SR_C, SR_D"',
                   default="")
    return p.parse_args()


if __name__ == "__main__" or _load_snakemake() is not None:
    smk = _load_snakemake()

    if smk is not None:
        log_val = smk.log[0] if isinstance(smk.log, (list, tuple)) else smk.log
        RivetEmbakeExtractor(
            yoda=_named_or_first(smk.input, "yoda", "input"),
            embake=_named_or_first(smk.output, "embake", "output"),
            param_vals=list(smk.params.masses),
            analysis=getattr(smk.params, "analysis", None),
            filter_str=getattr(smk.params, "filter", "") or "",
        ).run(log_path=str(log_val))
    else:
        args = _parse_cli()
        RivetEmbakeExtractor(
            yoda=args.input,
            embake=args.output,
            param_vals=args.mass,
            analysis=args.analysis,
            filter_str=args.filter,
        ).run(log_path=args.log)