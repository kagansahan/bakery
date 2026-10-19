"""
:class:`WorkflowUtil`: the object a Snakefile talks to.

.. code-block:: python

    wf_util = bakery.WorkflowUtil()
    wf_util.load_workflow(workflow)
    ...
    onstart:
        wf_util.ask_confirmation()

It is a :class:`bakery.session.Session` plus the steps that read Snakemake's workflow, rules and
DAG. Every public method turns bakery errors into Snakemake's ``WorkflowError``.
"""

import functools
import getpass
import os
import socket
import sys

from . import readers, reports
from .common import BakeryError, OrderError
from .session import Session


def as_workflow_error(method):
    """Decorator: bakery errors become ``WorkflowError`` (Snakemake prints them without a traceback)."""
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except BakeryError as err:
            from snakemake.exceptions import WorkflowError
            raise WorkflowError(f"bakery: {err}") from None
    return wrapper


def is_main_process(workflow):
    return bool(getattr(workflow, "is_main_process", True))


def cli_keys(workflow):
    settings = getattr(workflow, "config_settings", None)
    return tuple((getattr(settings, "config", None) or {}).keys())


def config_files(workflow):
    settings = getattr(workflow, "config_settings", None)
    return [str(f) for f in (getattr(settings, "configfiles", None) or [])]


def has_terminal():
    return sys.stdin is not None and sys.stdin.isatty()


def run_info(workflow, short_path):
    import datetime
    import subprocess

    import snakemake

    info = {
        "date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "snakemake_version": getattr(snakemake, "__version__", "?"),
        "host": socket.gethostname(),
        "user": _user(),
        "command": " ".join(sys.argv),
        "config_files": [short_path(f) for f in config_files(workflow)],
    }
    try:
        root = os.path.dirname(os.path.abspath(workflow.basedir))
        commit = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=5)
        if commit.returncode == 0:
            dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True,
                                   timeout=5).stdout.strip()
            info["git_commit"] = commit.stdout.strip() + (" (dirty)" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def _user():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 -- no user name in some containers
        return "?"


class WorkflowUtil(Session):
    def __init__(self):
        super().__init__()
        self.workflow = None

    # ---- Snakemake ---------------------------------------------------------------------------------
    def load_workflow(self, workflow):
        """
        Take Snakemake's ``workflow``: the Snakefile's folder (base of ``declare_project_root``),
        main process or cluster job, the ``--config`` keys.
        """
        self.workflow = workflow
        self.base_dir = os.path.abspath(workflow.basedir)
        self.main = is_main_process(workflow)
        self.cli_keys = cli_keys(workflow)
        self.trace("load_workflow", f"{self.base_dir} ({'main process' if self.main else 'job'})")

    def load_config(self, config, cli_keys=None):
        """:meth:`bakery.session.Session.load_config`; ``cli_keys`` come from the workflow."""
        super().load_config(config, cli_keys if cli_keys is not None else self.cli_keys)

    def resolve_wrapper(self, name):
        """
        The ``wrapper:`` address of wrapper ``name``: ``file://<wrappers>/<name>``, or the fake tool
        with ``fake=true``.

        :raises snakemake.exceptions.WorkflowError: ``wrapper.py`` or ``environment.yaml`` is missing
        """
        return "file://" + super().resolve_wrapper(name)

    def build_targets(self, selected):
        """
        Read the rules defined so far and plan them: what each rule makes from ``selected``.

        Call it after the last rule. Rules named ``all`` or ``run_*`` are left out.

        :param selected: the rows of this run (``apply_selection``)
        :returns: ``{rule: RuleView}``
        """
        self._need(self.workflow is not None, "build_targets()", "load_workflow(workflow)")
        specs = readers.read_rules(self.workflow, self.get_wildcard_constraints())
        return self.plan_targets(selected, specs)

    def print_report(self):
        """:meth:`bakery.session.Session.print_report`, and the docstrings of ``run_<rule>``
        (``snakemake -l`` shows them)."""
        super().print_report()
        self._describe_run_rules()

    def _describe_run_rules(self):
        """Docstrings of run_<rule> (snakemake -l shows them)."""
        for name, view in self.planner.views.items():
            try:
                rule = self.workflow.get_rule(f"run_{name}")
            except Exception:  # noqa: BLE001 -- the Snakefile may not define it
                continue
            rule.docstring = (f"bakery: run {name} for {len(view.to_run)} files ({len(view.on_disk)} on disk, "
                              f"{len(view.waiting)} waiting)")

    # ---- 13. confirmation --------------------------------------------------------------------------
    def ask_confirmation(self):
        """
        Show what Snakemake is about to run, and ask ``Start? [y/N]``.

        Call it in ``onstart:``; Snakemake runs that only for a real run (not ``-n``) after the DAG is
        built. The question cannot be switched off.

        * no job to run: say why (waiting inputs, files on disk) and stop with exit code 0, before
          Snakemake runs the empty ``run_<rule>`` job
        * no terminal: stop, nothing runs
        * an answer other than ``y``: stop, nothing runs
        * ``y``: write ``config.used.yaml`` in the results folder and let Snakemake run
        """
        if self.planner is None or self.workflow is None:
            raise OrderError("ask_confirmation() needs load_workflow(workflow) and build_targets(selected)")
        jobs = readers.needrun_jobs(self.workflow)
        info = readers.invocation(self.workflow)
        if not jobs:
            asked = [t[4:] for t in info["targets"] if t.startswith("run_") and t[4:] in self.planner.views]
            print(reports.nothing_to_run(self.planner.views, asked or list(self.planner.views),
                                              self.options, self.short_path))
            raise SystemExit(0)
        warnings = self.list_warnings() + self._ownership_warnings()
        print(reports.confirmation_screen(jobs, self._settings_lines(), self._invocation_lines(info), warnings,
                                  self.options["list_limit"], self.short_path))
        if not has_terminal():
            raise SystemExit("bakery: confirmation needed, but there is no terminal to ask in; nothing was run.")
        import builtins     # in a Snakefile, `input` is Snakemake's
        answer = builtins.input("  Start? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("bakery: cancelled; no job was started.")
            raise SystemExit(0)
        self._write_provenance()

    def _settings_lines(self):
        out = []

        def kv(key, value):
            out.append(f"  {key:<16} {value}")

        info = self.config.get("info") or {}
        kv("config", f"{info.get('name', '-')}" + (f" v{info['version']}" if info.get("version") else "")
           + f"   ({', '.join(self.short_path(f) for f in config_files(self.workflow)) or 'no --configfile'})")
        kv("output", self.get_output_folder())
        for name, option in self.schema.options.items():
            value = self.options[name]
            warning = option.warning_for(value)
            kv(name, str(value).lower() if isinstance(value, bool) else value)
            if warning:
                out[-1] += f"    <-- {warning}"
        for section, wildcard in self.planner.tool_wildcards.items():
            kv(wildcard, ", ".join(sorted(self.planner.covered.get(wildcard, ()))) or "-")
        kv("selection", ", ".join(f"{k}={v}" for k, v in self.selected.selection.items()) or "(none)")
        kv("manifest", f"{len(self.selected)} rows" + (f" (of {len(self.manifest)})"
                                                       if len(self.selected) != len(self.manifest) else ""))
        return out

    def _invocation_lines(self, info):
        out = []

        def kv(key, value):
            out.append(f"  {key:<16} {value}")

        kv("target", ", ".join(info["targets"]) or "(default: all)")
        kv("cores", info["cores"])
        if info["forceall"]:
            kv("forceall (-F)", "True    <-- EVERYTHING is rebuilt, on disk or not")
        for label, flag in (("forcerun (-R)", "forcerun"), ("until (-U)", "until"),
                            ("omit-from (-O)", "omit_from"), ("allowed-rules", "allowed_rules")):
            if flag in info:
                kv(label, ", ".join(info[flag]))
        kv("rerun_triggers", ", ".join(info["rerun_triggers"]) or "-")
        kv("command", " ".join(sys.argv))
        return out

    def _sections(self):
        return reports.config_sections(self.config, self.schema.sections)

    def _results(self):
        return self.layout.folder_path("results") if self.layout.has("results") else None

    def _ownership_warnings(self):
        folder = self._results()
        old = reports.read_provenance(folder) if folder else None
        if not old:
            return []
        run = old.get("bakery_run") or {}
        if run.get("config_sha256") == reports.config_digest(self._sections()):
            return []
        old_sections = {k: v for k, v in old.items() if k != "bakery_run"}
        diff = reports.config_differences(old_sections, self._sections())
        made_by = ", ".join(run.get("config_files") or []) or "another config"
        return [f"{self.get_output_folder()} was made with a different config ({made_by}, {run.get('date', '?')}). "
                f"Changes: " + ("; ".join(diff) if diff else "(order only)")]

    def _write_provenance(self):
        folder = self._results()
        if folder:
            from . import __version__
            info = dict(run_info(self.workflow, self.short_path), bakery_version=__version__)
            reports.write_provenance(folder, self._sections(), info)


def _wrap_public_methods(cls):
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name)
        if callable(attr) and not isinstance(attr, type):
            setattr(cls, name, as_workflow_error(attr))
    return cls


_wrap_public_methods(WorkflowUtil)
