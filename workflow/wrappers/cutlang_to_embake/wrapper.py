#!/usr/bin/env python3
"""
.. module:: cutlang_to_embake
        :synopsis: code that extracts efficiencies from a CutLang ROOT output
                   file and writes them into an .embaked file. Can be run
                   via Snakemake's `script:` directive or standalone.

.. moduleauthor:: Wolfgang Waltenberger <wolfgang.waltenberger@gmail.com>
.. moduleauthor:: Jan Mrozek <jmrozek@protonmail.ch>
"""
# TODO: Add exception mechanism, instead of just raising RuntimeError?
# TODO: Debug levels? Or adapt logging package?
# FIXME: uproot backend does not filter ignored regions the same way ROOT does.

# Standard library imports
import os                      # For path, makedirs
import re                      # For filter string parsing
import sys                     # For argv access in _load_snakemake
from datetime import datetime  # For timestamp of embaked files


class CutLangEmbakeExtractor:
    """
    Reads a CutLang output (.root) file and writes the efficiencies it
    contains into an .embaked file.

    Usage::

        ext = CutLangEmbakeExtractor(
            cla_out    = "histoOut.root",
            embake     = "out.embaked",
            param_vals = ["1000", "500"],
            filter_str = "SR4bin2, SR5bin1",
        )
        ext.run(log_path="run.log")
    """

    def __init__(self, cla_out, embake, param_vals, filter_str=""):
        """
        :param cla_out:    path to the CutLang .root output file
        :param embake:     path of the .embaked file to write
        :param param_vals: list of mass/parameter values, e.g. ["1000", "500"]
        :param filter_str: comma separated list of regions/bins to skip,
                            e.g. "SR7, SR5, SR4bin2, SR4bin3"
        """
        self.cla_out = cla_out
        self.embake = embake
        self.param_vals = [str(v) for v in param_vals]
        self.filter_regions, self.filter_bins = self._parse_filter(filter_str)

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
        """ Extracts the efficiencies and writes the .embaked file.
            Raises RuntimeError if no efficiencies could be found.
        """
        entries, nevents = self._extract()

        self._info(f"nevents[:5] = {nevents[:5]}")
        if len(set(nevents)) > 1:
            self._error(f"Number of events is not consistent across regions: {set(nevents)}")
        if not nevents:
            raise RuntimeError("No efficiencies found.")

        self._write_embake(entries, nevents)
        self._info(f"wrote: {self.embake}")

    def _extract(self):
        """ Extracts the efficiencies from the CutLang output, via ROOT,
            falling back to uproot.
            :returns: entries, nevents tuple:
                        entries -- String containing efficiencies extracted
                                   from cla_out
                        nevents -- List of numbers of events for each entry.
        """
        try:
            return self._extract_ROOT()
        except Exception as e:
            self._info(f"ROOT-based extractor failed ({e}), using uproot-based extractor!")
            return self._extract_uproot()

    # =========================================================================
    #      ROOT backend
    # =========================================================================

    def _extract_ROOT(self):
        """ Extracts the efficiencies from CutLang output, via ROOT.
            :returns: entries, nevents tuple (see _extract)
        """
        import ROOT  # To parse CutLang output

        f = ROOT.TFile(self.cla_out)
        if f is None:
            raise RuntimeError(f"ROOT: cannot find CutLang results at {self.cla_out}.")

        entries, nevents = "", []
        contains_eff = False  # Whether this root file yielded any efficiencies
        tmp = ROOT.TH1D()  # temporary TH1D structure to read results into

        self._debug("ROOT objects found in CutLang results:")
        self._debug(str([k.ReadObj().GetName() for k in f.GetListOfKeys()]))

        # Traverse all keys in the ROOT file
        for key in f.GetListOfKeys():
            obj = key.ReadObj()
            if not isinstance(obj, ROOT.TDirectoryFile):
                self._debug(f"ROOT {obj.GetName()} is not a TDirectoryFile.")
                continue

            # if the region is filtered out, move on to the next one
            region = obj.GetName()
            if self._region_ignored(region):
                continue

            # if there is no cutflow defined in the region, move on
            keys = [k.ReadObj().GetName() for k in obj.GetListOfKeys()]
            if "cutflow" not in keys:
                self._info(f"Cutflow not found in {region} in {self.cla_out}")
                continue

            # copy cutflow object into the temp object and process it
            tmp = obj.cutflow
            nbins = tmp.GetNbinsX()
            if tmp[2] == 0:
                entries += "NaN"
                nevents.append(0)
                continue

            # tmp[2] == number of all events
            entries += f"'{region}': {tmp[nbins - 1] / tmp[2]}, "
            nevents.append(tmp[2])
            contains_eff = True

            # if the region contains bins, process them too
            if "bincounts" in keys:
                tmp = obj.bincounts
                n = tmp.GetNbinsX()
                self._info(f"ROOT found {n} bins in {region} section.")
                skip = self.filter_bins.get(region, [])
                for i in range(n + 1):
                    if i in skip:
                        continue
                    label = tmp.GetXaxis().GetBinLabel(i)
                    entries += self._bin_entry(region, label, tmp[i] / nevents[-1])

        if not contains_eff:
            raise RuntimeError(f"ROOT: no efficiencies found in {self.cla_out}.")
        return entries, nevents

    # =========================================================================
    #      uproot backend
    # =========================================================================

    def _extract_uproot(self):
        """ Extracts the efficiencies from CutLang output, via uproot.
            :returns: entries, nevents tuple (see _extract)
        """
        if not os.path.exists(self.cla_out):
            raise RuntimeError(f"uproot: cannot find CutLang results at {self.cla_out}.")
        import uproot

        f = uproot.open(self.cla_out)
        entries, nevents = "", []
        contains_eff = False  # Whether this root file yielded any efficiencies

        self._debug("uproot objects found in CutLang results:")
        self._debug(str([name for name in f]))

        for name, obj in f.items():
            if name.endswith("/bincounts;1"):
                region = name.replace("/bincounts;1", "")
                self._info(f"uproot found bins in {region} section.")
                labels = obj.axes[0].labels()
                skip = self.filter_bins.get(region, [])
                values = obj.values()
                entries += f"'{region}_': {values[-1]}, "
                for i, v in enumerate(values):
                    if i in skip:
                        continue
                    entries += self._bin_entry(region, labels[i], v / nevents[-1])
                continue

            if "/cutflow;1" not in name:
                continue

            region = name.replace("/cutflow;1", "")
            if self._region_ignored(region):
                continue

            # copy cutflow values and process them
            values = obj.values()
            n = len(values)
            entries += f"'{region}': {values[n - 2] / values[1]}, "
            nevents.append(values[1])
            contains_eff = True

        if not contains_eff:
            raise RuntimeError(f"uproot: no efficiencies found in {self.cla_out}.")
        return entries, nevents

    # =========================================================================
    #      Output writing
    # =========================================================================

    def _write_embake(self, entries, nevents):
        """ Writes the extracted efficiencies to self.embake.
            :param entries: efficiency entries string, as returned by _extract
            :param nevents: list of numbers of events, as returned by _extract
        """
        os.makedirs(os.path.dirname(self.embake) or ".", exist_ok=True)
        nev = nevents[0]
        if nev == int(nev):
            nev = str(int(nev))
        ts = datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
        self._msg(f"Writing efficiency values for masses {self.mass} to file:\n {self.embake}")
        with open(self.embake, "wt") as f:
            f.write(f"{self.mass}: {{")
            f.write(entries)
            f.write(f"'__t__':'{ts}', ")
            f.write(f"'__nevents__':{nev}")
            f.write("}")

    # =========================================================================
    #      Filter parsing + helpers
    # =========================================================================

    @staticmethod
    def _parse_filter(string):
        """ Takes comma separated string of regions and returns a tuple
            of set and dictionary (regionList, binList), e.g.
            "SR4, SR5bin2, SR5bin3" -> ({"SR4"}, {"SR5": [2, 3]})
            :param string: comma separated list of regions/bins to filter out
        """
        string = (string or "").replace(" ", "")
        if not string:
            return set(), {}

        filterList = string.split(",")
        binList = {}
        removedElements = set()
        for x in filterList:
            searchObj = re.search(r"bin(\d+)", x)
            if searchObj:
                removedElements.add(x)
                regionName = x[:searchObj.start()]
                if regionName in binList:
                    binList[regionName].append(int(searchObj.group(1)))
                else:
                    binList[regionName] = [int(searchObj.group(1))]

        regionList = set(filterList) - removedElements
        return regionList, binList

    def _region_ignored(self, region: str) -> bool:
        """ True if this region should be skipped, either because it is
            in the baseline/preselection or was explicitly filtered out.
            :param region: name of the CutLang region
        """
        return region in self.filter_regions or region in {"baseline", "presel"}

    @staticmethod
    def _bin_entry(region: str, bin_label: str, value) -> str:
        """ Formats a single bin efficiency as an entry for the .embaked file.
            :param region:    name of the CutLang region the bin belongs to
            :param bin_label: label of the bin, as reported by CutLang
            :param value:     efficiency value for this bin
        """
        name = f"{region}_{bin_label.replace(' ', '_')}"
        name = name.replace("[", "").replace("]", "")
        name = name.replace("'", "").replace('"', "")
        name = name.replace("and", "").replace("__", "_")
        name = name.replace("Size(jets)", "njets")
        name = name.replace("Size(bjets)", "nbjets")
        return f"'{name}': {value}, "

    # =========================================================================
    #      Logging + redirection
    # =========================================================================

    @staticmethod
    def _info(*msg):
        """ Print an info message """
        print(f"[cutlang_to_embake] {' '.join(map(str, msg))}")

    @staticmethod
    def _debug(*msg):
        """ Print a debug message. Disabled by default. """
        return
        print(f"[cutlang_to_embake] DEBUG {' '.join(map(str, msg))}")

    @staticmethod
    def _msg(*msg):
        """ Print a normal message """
        print(f"[cutlang_to_embake] {' '.join(map(str, msg))}")

    @staticmethod
    def _error(*msg):
        """ Print an error message """
        print(f"[cutlang_to_embake] Error: {' '.join(map(str, msg))}")

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
    """ Returns the snakemake object injected by Snakemake's `script:`
        directive, or None if run standalone. """
    try:
        return snakemake  # noqa: F821
    except NameError:
        return None


def _parse_cli():
    """ Parses command line arguments for standalone use. """
    import argparse
    p = argparse.ArgumentParser(description='CutLang efficiency extractor.')
    p.add_argument("-i", "--input", help="CutLang .root output file", required=True)
    p.add_argument("-o", "--output", help=".embaked file to write", required=True)
    p.add_argument("-m", "--mass", help="mass/parameter values, e.g. 1000 500",
                    nargs="+", required=True)
    p.add_argument("-l", "--log", help="log file to write to", required=True)
    p.add_argument("-f", "--filter", help='regions/bins to filter out, e.g. "SR4, SR5bin2"',
                    default="")
    return p.parse_args()


if __name__ == "__main__":
    smk = _load_snakemake()

    if smk is not None:
        log_val = smk.log[0] if isinstance(smk.log, (list, tuple)) else smk.log
        CutLangEmbakeExtractor(
            cla_out=smk.input.input,
            embake=smk.output.output,
            param_vals=list(smk.params.masses),
            filter_str=getattr(smk.params, "filter", "") or "",
        ).run(log_path=str(log_val))
    else:
        args = _parse_cli()
        CutLangEmbakeExtractor(
            cla_out=args.input,
            embake=args.output,
            param_vals=args.mass,
            filter_str=args.filter,
        ).run(log_path=args.log)