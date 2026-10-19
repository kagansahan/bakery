#!/usr/bin/env python3
"""
.. module:: CutLangWrapper
        :synopsis: code that wraps around cutlang. Runs the cutlang executable
                   on an already-produced ROOT file (e.g. Delphes output).

.. moduleauthor:: Wolfgang Waltenberger <wolfgang.waltenberger@gmail.com>
.. moduleauthor:: Jan Mrozek <jmrozek@protonmail.ch>

..directory structure::
    em-creator --┬-CutLang---------┬-runs ~ dir with running script (CLA.sh)
                 |                 +-CLA  ~ dir with executable (CLA.exe)
                 |                 + ADLLHCAnalysis ~ contains adl files for analyses

NOTE: This is a trimmed version of the original CutLangWrapper, kept
      as a Snakemake rule wrapper. Everything that is not directly needed to
      run the CutLang executable on an already-produced ROOT file (Delphes
      execution, CutLang/ADLLHCAnalyses auto-install & compile, efficiency
      extraction, .embaked bookkeeping, mass-scan/summary-file bookkeeping,
      hepmc decompression, region/bin filtering, ...) has been removed.
      See the original em-creator CutLangWrapper for the full pipeline.
"""
# TODO: Adapt for paralelisation.
# TODO: Add exception mechanism to exe.
# TODO: Debug levels? Or adapt logging package?
# FIXME: Instead of exiting, raise exceptions?

# Standard library imports
import os                      # For path, unlink
import sys                     # For exit()
import colorama                # For output colors (in msg, error, ...)
import subprocess              # For Popen in exe method
import shutil                  # For move(), rmtree()
import tempfile                # For the temporary working directory
import re                      # For file references inside the ADL
from datetime import datetime  # For timestamp of log files
from typing import Union, Text, Optional # For type hinting

from colorama import Fore

# local imports
# NOTE: the original wrapper imported `execute` from `bakeryHelpers`. That
# module is part of the larger em-creator bakery pipeline and is not needed
# here, so `execute` is reimplemented locally with the same signature/contract.

def execute(cmd, cwd=None, logfile=None, exit_on_fail=False, prefix=None):
    """Run a command. Output goes to sys.stdout, which the caller may
    already have redirected to a log file -- this keeps wrapper messages
    and subprocess output in chronological order in a single stream.
    `logfile` kept in the signature for backward compatibility; unused.
    """
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if prefix:
        for line in result.stdout.splitlines():
            print(f"{prefix}{line}", flush=True)
    else:
        sys.stdout.write(result.stdout)
    if exit_on_fail and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode

#def execute(cmd, cwd=None, logfile=None, exit_on_fail=False):
#    """Run a command, optionally logging its output. Returns the exit code.
#
#    Drop-in replacement for bakeryHelpers.execute, used by _copy_cla() and run().
#    """
#    if logfile:
#        f = open(logfile, "a")
#    else:
#        f = open(os.devnull, "w")
#    try:
#        result = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
#        if exit_on_fail and result.returncode != 0:
#            sys.exit(result.returncode)
#        return result.returncode
#    finally:
#        f.close()

class CutLangWrapper:

    def __init__(self, adl_file: Union[Text, None] = None,
                 cutlang_path: Union[Text, None] = None,
                 keep: bool = False,
                 resource: Union[Text, None] = None,
                 analysis_name: Union[Text, None] = None,
                 adl_name: Union[Text, None] = None) -> None:
        """
        Prepares CutLangWrapper to run CutLang on an already-produced ROOT file.
        Assumes CutLang is already installed at `cutlang_path` (or $CUTLANG_PATH) --
        installing/compiling CutLang is out of scope for this wrapper.

        The ADL is given either directly (adl_file) or from a repository
        (resource + analysis_name [+ adl_name]).

        :param adl_file: path to the ADL analysis file to run
        :param cutlang_path: CutLang installation directory (default: $CUTLANG_PATH or "./CutLang/")
        :param keep: keep temporary files for debugging?
        :param resource: local directory of the ADL repository
        :param analysis_name: analysis directory inside the resource
        :param adl_name: ADL file name, if the analysis directory has more than one
        """
        # General vars
        self.resource_dir = None ## local copy of the resource (searched for ADL dependencies)
        if resource:
            adl_file = self._adl_from_resource(resource, analysis_name, adl_name)
        self.adl_file = os.path.abspath(adl_file) if adl_file else adl_file
        self.keep = keep ## keep temporary files?
        self.tempFiles = [] ## way to keep track of tempFiles

        self._info("Initialising CutLangWrapper ...")
        self._msg(f"adl_file (raw)      : {adl_file}")
        self._msg(f"adl_file (resolved) : {self.adl_file}")
        self._msg(f"keep temp files?    : {self.keep}")

        # Cutlang vars
        self.cutlanginstall = cutlang_path or os.environ.get("CUTLANG_PATH", "./CutLang/")
        self.cutlang_executable = os.path.join(self.cutlanginstall, "CLA/CLA.exe")
        self.cutlang_run_dir = "./runs"  # Directory where the CutLang will run
        self.cutlang_script = "CLA.sh"
        self._msg(f"cutlang_path (arg)        : {cutlang_path}")
        self._msg(f"CUTLANG_PATH (env)        : {os.environ.get('CUTLANG_PATH')}")
        self._msg(f"cutlanginstall (resolved) : {self.cutlanginstall}")
        self._msg(f"cutlang_executable        : {self.cutlang_executable}")

        # make auxiliary (temporary) working directory
        self._work_dir = tempfile.mkdtemp(prefix="cutlang_")
        self._info(f"Created temporary work directory: {self._work_dir}")

        # =====================
        #      Cutlang Init
        # =====================
        # NOTE: the original __init__ auto-cloned & compiled CutLang from
        # github here if it was missing. That logic was removed -- this
        # wrapper expects CutLang to already be installed, and only checks
        # for its presence.
        self._info("Checking CutLang installation ...")
        if not os.path.isdir(self.cutlanginstall):
            self._error(f"cannot find cutlang installation at {self.cutlanginstall}. Exiting.")
            sys.exit()
        self._msg(f"Found cutlang installation directory: {self.cutlanginstall}")
        if not os.path.exists(self.cutlang_executable):
            self._error(f"cannot find cutlang executable at {self.cutlang_executable}. Exiting.")
            sys.exit()
        self._msg(f"Found cutlang executable: {self.cutlang_executable}")
        self._info("Checking ADL analysis file ...")
        if self.adl_file is None or not os.path.isfile(self.adl_file):
            self._error(f"cannot find adl file {self.adl_file}. Exiting.")
            sys.exit()
        self._msg(f"Found adl file: {self.adl_file}")
        self._info("CutLang initialisation finished.")

    def run(self, input_root: str, output_file: str,
            input_type: str = "DELPHES", extra_args: str = "",
            logfile: Union[Text, None] = None) -> int:
        """ Runs CutLang on an already-produced (e.g. Delphes) ROOT file.

            input_root --┬-> CutLang --> output_file
            adl_file    --┘

            error values:
                -1:   Cannot find input ROOT file
                -3:   Could not copy CutLang to temporary directory
                -4    There were no histoOut files produced
        :param input_root: input ROOT file (e.g. delphes output)
        :param output_file: full path of the output file (first histoOut copy)
        :param input_type: input format passed to CLA.sh, e.g. "DELPHES"
        :param extra_args: extra, space-separated arguments appended to the CLA.sh call
        :param logfile: where to write CutLang's log; defaults to a file in the
                        temporary work dir if not given.
        """
#        if logfile is None:
#            time = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
#            logfile = os.path.join(self._work_dir, "log_" + time + ".txt")
#        logdir = os.path.dirname(logfile)
#        if logdir:
#            os.makedirs(logdir, exist_ok=True)
#        self._delete_dir(logfile)

        if logfile is None:
            time = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            logfile = os.path.join(self._work_dir, "log_" + time + ".txt")
        logdir = os.path.dirname(logfile)
        if logdir:
            os.makedirs(logdir, exist_ok=True)

        self._info("Starting CutLang run ...")
        self._msg(f"input_root  : {input_root}")
        self._msg(f"output_file : {output_file}")
        self._msg(f"input_type  : {input_type}")
        self._msg(f"extra_args  : '{extra_args}'")
        self._msg(f"logfile     : {logfile}")

        self._info(f"Checking input ROOT file {input_root} ...")
        if not os.path.isfile(input_root):
            self._error(f"cannot find input file {input_root}.")
            return -1
        self._msg(f"Found input ROOT file: {input_root}")

        # ======================
        #        CutLang
        # ======================
        # Prepare input paths
        cla_input = os.path.abspath(input_root)
        self._msg(f"Resolved input ROOT file to absolute path: {cla_input}")

        # copy cutlang to a temporary directory
        cla_temp_name = os.path.join(self._work_dir, "CLA_run")
        self._info(f"Preparing temporary CLA run directory: {cla_temp_name}")
        # to prevent errors from copy during reruns delete and remake
        if os.path.exists(cla_temp_name):
            self._msg(f"Temporary CLA run directory already exists, removing it: {cla_temp_name}")
            self._delete_dir(cla_temp_name)
        os.makedirs(cla_temp_name, exist_ok=True)
        self._msg(f"Created temporary CLA run directory: {cla_temp_name}")

        self._info(f"Copying CutLang installation ({self.cutlanginstall}) into {cla_temp_name} ...")
        if not self._copy_cla(cla_temp_name, logfile):
            self._error(f"Could not copy CutLang to temporary directory {cla_temp_name}.")
            self.removeTempFiles()
            return -3
        self._msg(f"CutLang successfully copied to {cla_temp_name}")
        cla_run_dir = os.path.join(cla_temp_name, self.cutlang_run_dir)
        self._msg(f"CLA run directory: {cla_run_dir}")

        # copy the ADL and its dependencies (onnx, xml, ...) into runs/
        local_adl = self._copy_adl(cla_run_dir)

        # run CutLang
        cmd = [self.cutlang_script, cla_input, input_type, "-i", local_adl]
        if extra_args:
            cmd += extra_args.split()
        self._info(f"Running CutLang: {' '.join(cmd)}")
        self._msg(f"(cwd={cla_run_dir}, log={logfile})")
        cla_retcode = execute(cmd, cwd=cla_run_dir, logfile=logfile, prefix="[CLA.sh] ")
        self._msg(f"CLA.sh exit code: {cla_retcode}")
        if cla_retcode != 0:
            self._error(f"CLA.sh exited with code {cla_retcode}. See log for details:\n"
                       f"{self._tail(logfile)}")
        else:
            self._info("CLA finished successfully.")

        ## now that we ran cutlang, mark the temp CLA dir as to-be-deleted
        self.tempFiles.append(cla_temp_name)

        # ====================
        #  Collect output
        # ====================
        self._info(f"Scanning {cla_run_dir} for histoOut files ...")
        histo_files = sorted(
            f for f in os.listdir(cla_run_dir)
            if f.startswith("histoOut") and f.endswith(".root")
        )
        self._msg(f"Found {len(histo_files)} histoOut file(s): {histo_files}")
        if not histo_files:
            self._error(f"No histoOut files produced in {cla_run_dir}. Log:\n"
                       f"{self._tail(logfile)}")
            self.removeTempFiles()
            return -4

        output_dir = os.path.dirname(output_file)
        if output_dir:
            self._msg(f"Ensuring output directory exists: {output_dir}")
            os.makedirs(output_dir, exist_ok=True)

        # Copy first histoOut file to output_file
        self._info(f"Copying first histoOut file ({histo_files[0]}) to output ...")
        shutil.copy2(os.path.join(cla_run_dir, histo_files[0]), output_file)
        self._info(f"First histoOut file copied to {output_file}")

        # Copy other histoOut files next to it (avoid name clashes)
        if len(histo_files) > 1:
            self._info(f"Copying {len(histo_files) - 1} additional histoOut file(s) ...")
        for i, hf in enumerate(histo_files[1:], start=1):
            dest = os.path.join(output_dir, f"histoOut_{i}.root")
            shutil.copy2(os.path.join(cla_run_dir, hf), dest)
            self._info(f"Additional histoOut file copied to {dest}")

        self._info(f"Cleaning up temporary files (keep={self.keep}) ...")
        self.removeTempFiles()
        self._info("CutLang run finished successfully. Returning 0.")
        return 0

    # =========================================================================
    # Private methods
    # =========================================================================

    def _adl_from_resource(self, resource, analysis_name, adl_name=None):
        """
        Return the ADL path <resource>/<analysis_name>/<adl_name>.adl.
        `resource` is a local directory (git repos are cloned by the Snakefile).
        """
        self.resource_dir = os.path.abspath(resource)
        ana_dir = os.path.join(self.resource_dir, analysis_name)
        if adl_name:
            adl = adl_name if adl_name.endswith(".adl") else adl_name + ".adl"
        else:
            adl = [f for f in os.listdir(ana_dir) if f.endswith(".adl")][0]
        return os.path.join(ana_dir, adl)

    def _copy_adl(self, run_dir):
        """
        Copy the ADL and the files it references (any quoted "path.ext", e.g.
        an onnx model) into run_dir. References are rewritten to the plain file
        name, so CutLang reads everything from its working directory.
        Returns the ADL file name.
        """
        adl_dir = os.path.dirname(self.adl_file)

        def copy_dep(m):
            ref = m.group(2)
            for src in (ref, os.path.join(adl_dir, ref),
                        os.path.join(adl_dir, os.path.basename(ref))):
                if os.path.isfile(src):
                    break
            else:
                src = None
                for root, _, files in os.walk(self.resource_dir or adl_dir):
                    if os.path.basename(ref) in files:
                        src = os.path.join(root, os.path.basename(ref))
                        break
            if src is None:          # not a file (e.g. a label): leave unchanged
                return m.group(0)
            shutil.copy2(src, os.path.join(run_dir, os.path.basename(src)))
            self._msg(f"Copied ADL dependency {src} -> {run_dir}")
            return f"{m.group(1)}{os.path.basename(src)}{m.group(1)}"

        lines = []
        with open(self.adl_file) as f:
            for line in f:
                code, hash_, comment = line.partition("#")   # skip comments
                code = re.sub(r"""(["'])([^\s"']+\.[A-Za-z]\w*)\1""", copy_dep, code)
                lines.append(code + hash_ + comment)
        adl_name = os.path.basename(self.adl_file)
        with open(os.path.join(run_dir, adl_name), "w") as f:
            f.writelines(lines)
        self._msg(f"Copied ADL {self.adl_file} -> {run_dir}")
        return adl_name

    def _copy_cla(self, where, logfile=None):
        """
        Copy CutLang to temporary directory.
        :param where    copy destination
        :param logfile  file where output of all commands is written
        """
        self._msg(f"_copy_cla: copying CutLang parts from {self.cutlanginstall} to {where}")
        partlist = ["analysis_core", "BP", "CLA", "runs", "scripts"]
        partlist = map(lambda x: os.path.join(self.cutlanginstall, x), partlist)
        for part in partlist:
            self._msg(f"Copying {part} -> {where} ...")
            cmd = ['cp', '-r', part, where]
            if execute(cmd, logfile=logfile) != 0:
                self._error(f"Failed to copy {part} to {where}.")
                return False
            self._msg(f"Copied {part}.")
        # To prevent redefinitions we have to replace all the shared libraries
        # in the tmp directory with links to the original ones
        core_dir = os.path.join(self.cutlanginstall, 'analysis_core')
        self._msg( f"Linking shared libraries in {core_dir} ..." )
        for filename in os.listdir(core_dir):
            if filename.endswith(".so"):
                link_name = os.path.join(where, 'analysis_core', filename)
                origin_name = os.path.abspath(os.path.join(core_dir, filename))
                self._msg(f"Linking {origin_name}  -> {link_name}")
                cmd = ['ln', '-sf', origin_name, link_name]
                if execute(cmd, logfile=logfile) != 0:
                    self._error(f"Failed to link {filename}.")
                    return False
        self._msg("_copy_cla: all parts copied and libraries linked successfully.")
        return True

    def removeTempFiles ( self ):
        """ remove all temp files that we know of """
        if self.keep:
            self._msg(f"keep=True, not removing temp files: {self.tempFiles}")
            return
        for t in self.tempFiles:
            if not os.path.exists ( t ):
                continue
            self._msg(f"Removing temp file/dir: {t}")
            if os.path.isdir ( t ):
                shutil.rmtree ( t )
            else:
                os.unlink ( t )
        self.tempFiles = []

    def _delete_dir(self, f):
        if os.path.exists(f):
            subprocess.getoutput("rm -rf %s" % f)

    @staticmethod
    def _tail(logfile, n=20):
        """Return the last n lines of logfile, for putting into error messages."""
        if not logfile or not os.path.isfile(logfile):
            return "(no log file)"
        try:
            with open(logfile, "r", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-n:]) if lines else "(log file is empty)"
        except OSError as e:
            return f"(could not read log file: {e})"

    @staticmethod
    def _info(*msg):
        """Print yellow info message"""
        print( f"{Fore.YELLOW}[CutLangWrapper] {' '.join(msg)}{Fore.RESET}", flush=True)

    @staticmethod
    def _debug(*msg):
        """Print green debug message."""
        print(f"{Fore.GREEN}[CutLangWrapper][DEBUG] {' '.join(msg)}{Fore.RESET}", flush=True)

    @staticmethod
    def _msg(*msg):
        """Print normal message"""
        print( f"{Fore.GREEN}[CutLangWrapper] {' '.join(msg)}{Fore.RESET}", flush=True)

    @staticmethod
    def _error(*msg):
        """Print red error message"""
        string = ' '.join(msg)
        print(f"{Fore.RED}[CutLangWrapper] Error: {string} {Fore.RESET}", flush=True)