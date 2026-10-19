# Standard library imports
import os                      # For path, unlink
import sys                     # For exit()
import colorama                # For output colors (in msg, error, ...)
import subprocess              # For Popen in exe method
import shutil                  # For move(), rmtree()
import tempfile                # For the temporary working directory
from datetime import datetime  # For timestamp of log files
from typing import Union, Text, Optional # For type hinting

from cutlang_wrapper import CutLangWrapper

if __name__ == "__main__":
    # Called by Snakemake when 'snakemake' object is defined.
    if 'snakemake' in globals():
        print("[CutLangWrapper] Running in Snakemake mode.", flush=True)
        adl_file = snakemake.params.get("adl_file")
        resource = snakemake.params.get("resource")
        analysis_name = snakemake.params.get("analysis_name")
        adl_name = snakemake.params.get("adl_name")
        cutlang_path = snakemake.params.get("cutlang_path", None)
        keep = snakemake.params.get("keep", False)
        input_type = snakemake.params.get("input_type", "DELPHES")
        extra_args = snakemake.params.get("extra_args", "")

        # snakemake.log is only set if the rule has a log: directive
        logfile = snakemake.log[0] if len(snakemake.log) > 0 else None

        if logfile:
            logdir = os.path.dirname(logfile)
            if logdir:
                os.makedirs(logdir, exist_ok=True)
            if os.path.exists(logfile):
                os.remove(logfile)
            log_fh = open(logfile, "a", buffering=1)  # line-buffered
            sys.stdout = log_fh
            sys.stderr = log_fh

        print(f"[CutLangWrapper] input        : {snakemake.input[0]}", flush=True)
        print(f"[CutLangWrapper] output       : {snakemake.output[0]}", flush=True)
        print(f"[CutLangWrapper] adl_file     : {adl_file}", flush=True)
        print(f"[CutLangWrapper] cutlang_path : {cutlang_path}", flush=True)
        print(f"[CutLangWrapper] input_type   : {input_type}", flush=True)
        print(f"[CutLangWrapper] extra_args   : {extra_args}", flush=True)
        print(f"[CutLangWrapper] keep         : {keep}", flush=True)
        print(f"[CutLangWrapper] log          : {logfile}", flush=True)

        cutlang = CutLangWrapper(adl_file=adl_file, cutlang_path=cutlang_path, keep=keep,
                                 resource=resource, analysis_name=analysis_name, adl_name=adl_name)
        ret = cutlang.run(snakemake.input[0], snakemake.output[0],
                          input_type=input_type, extra_args=extra_args, logfile=logfile)
        print(f"[CutLangWrapper] run() returned {ret}. Exiting with {0 if ret == 0 else 1}.", flush=True)
        sys.exit(0 if ret == 0 else 1)
    else:
        # Command line mode (for testing)
        print("[CutLangWrapper] Running in CLI mode.", flush=True)
        import argparse
        argparser = argparse.ArgumentParser(description='cutlang runner.')
        argparser.add_argument('-i', '--input', help='input ROOT file (e.g. Delphes output)',
                               type=str, required=True)
        argparser.add_argument('-o', '--output', help='output file (first histoOut copy)',
                               type=str, required=True)
        argparser.add_argument('-a', '--adl_file', help='ADL analysis file',
                               type=str, default=None)
        argparser.add_argument('-r', '--resource', help='ADL repository (local directory)',
                               type=str, default=None)
        argparser.add_argument('-n', '--analysis_name', help='analysis directory inside the resource',
                               type=str, default=None)
        argparser.add_argument('-A', '--adl_name', help='ADL file name inside the analysis directory',
                               type=str, default=None)
        argparser.add_argument('-C', '--cutlang_path', help='CutLang installation directory [$CUTLANG_PATH]',
                               type=str, default=None)
        argparser.add_argument('-k', '--keep', help='keep temporary files for debugging',
                               action="store_true")
        argparser.add_argument('-t', '--input_type', help='input type passed to CLA.sh [DELPHES]',
                               type=str, default="DELPHES")
        argparser.add_argument('-e', '--extra_args', help='extra, space-separated args for CLA.sh',
                               type=str, default="")
        argparser.add_argument('-l', '--log', help='log file path',
                               type=str, default=None)
        args = argparser.parse_args()
        print(f"[CutLangWrapper] Parsed args: {vars(args)}", flush=True)

        cutlang = CutLangWrapper(adl_file=args.adl_file, cutlang_path=args.cutlang_path, keep=args.keep,
                                 resource=args.resource, analysis_name=args.analysis_name,
                                 adl_name=args.adl_name)
        ret = cutlang.run(args.input, args.output,
                          input_type=args.input_type, extra_args=args.extra_args, logfile=args.log)
        print(f"[CutLangWrapper] run() returned {ret}. Exiting with {0 if ret == 0 else 1}.", flush=True)
        sys.exit(0 if ret == 0 else 1)