"""
The steps of a bakery Snakefile that do not need Snakemake.

:class:`Session` holds everything a Snakefile declares and builds, and checks that the steps come in
order. :class:`bakery.workflowUtil.WorkflowUtil` adds the steps that read Snakemake's workflow
(``load_workflow``, ``build_targets``, ``ask_confirmation``). A plain :class:`Session` can load a
config, build the manifest and apply a selection without Snakemake:

.. code-block:: python

    from bakery.session import Session

    s = Session()
    s.declare_project_root("/path/to/project")
    ...                                   # sections, options, formats, recipe, wildcards
    s.load_config(yaml.safe_load(open("config/config.yaml")))
    s.validate_config()
    manifest = s.build_manifest()
    selected = s.apply_selection(manifest, selectors={"process": "T2"})
    s.print_manifest(selected)

The order of the steps:

1. ``declare_project_root``, ``declare_folder``
2. ``add_config_section`` (optional), ``add_config_option``, ``add_config_schema``, ``add_config_check``
3. ``declare_format``
4. ``expand_rows``, ``declare_lookup``, ``declare_column`` (the manifest recipe)
5. ``declare_wildcard``, ``declare_selector``
6. ``load_config``, ``validate_config``
7. ``build_manifest``, ``apply_selection``
8. ``declare_path``, ``get_wildcard_constraints``
9. in rules: ``param``, ``param_path``, ``match``, ``resolve_wrapper``, ``resolve_script``
10. ``build_targets`` (``plan_targets`` without Snakemake), ``list_target_files``
11. ``print_report``

Verbs: ``declare_*`` describes and computes nothing, ``add_*`` adds an allowed config key or format,
``get_*`` returns one value now, ``list_*`` returns data and never prints, ``print_*`` always prints,
``show_*`` prints only when ``--config show=...`` asks for it.
"""
import copy
import os
import re

from . import reports
from .common import ConfigError, OrderError, parse_bool, plain_dates, segments, walk
from .config import FRAMEWORK_KEYS, ConfigSchema, validate
from .jobValues import REQUIRED, Param, ParamPath, RowLookup, as_dict
from .manifest import Formats, Manifest, Wildcards, patterns_from, select
from .planner import TargetPlanner
from .project import FakeTools, PathTemplates, ProjectLayout, RealTools, strip_constraints
from .recipe import DeclareColumn, DeclareLookup, ExpandRows, Recipe
from .tools import Tools


class Session:
    """
    Everything one Snakefile declares and builds.

    :ivar layout: the project root and the declared folders (:class:`bakery.project.ProjectLayout`)
    :ivar schema: config sections, options, JSON schema, checks (:class:`bakery.config.ConfigSchema`)
    :ivar recipe: the manifest recipe (:class:`bakery.recipe.Recipe`)
    :ivar wildcards: declared wildcards and selectors (:class:`bakery.manifest.Wildcards`)
    :ivar config: the loaded config (a copy; dates as text), ``None`` before :meth:`load_config`
    :ivar options: option values after :meth:`validate_config`
    :ivar manifest: every row of the config, after :meth:`build_manifest`
    :ivar selected: the rows of this run, after :meth:`apply_selection`
    :ivar planner: what each rule makes, after ``build_targets`` (:class:`bakery.planner.TargetPlanner`)
    :ivar main: ``True`` in the main process (prints), ``False`` in a cluster job (quiet)
    """

    def __init__(self):
        self.layout = ProjectLayout()
        self.schema = ConfigSchema()
        self.formats = Formats()
        self.recipe = Recipe()
        self.wildcards = Wildcards()
        self.paths = PathTemplates()
        self.base_dir = None
        self.main = True
        self.cli_keys = ()
        self.config = None
        self.options = None
        self.tool_resolver = None
        self.manifest = None
        self.selected = None
        self.planner = None
        self.notes = []
        self._row_lookup = None
        self._trace = []
        self._trace_on = None

    # ---- helpers -----------------------------------------------------------------------------------
    def _need(self, ready, step, before):
        if not ready:
            raise OrderError(f"{step} needs {before} first")

    def _declaring(self, step):
        if self.options is not None:
            raise OrderError(f"{step} comes after validate_config(); move it above load_config/validate_config")

    def trace(self, stage, text):
        """
        One ``[bakery]`` line per stage, printed with ``--config bakery_trace=true``.

        Lines before :meth:`load_config` are kept and printed once the config says whether to.
        """
        line = f"[bakery] {stage:<18} {text}"
        if self._trace_on is None:
            self._trace.append(line)
        elif self._trace_on and self.main:
            print(line)

    def say(self, text):
        """Print in the main process only."""
        if self.main and text:
            print(text)

    def short_path(self, path):
        """``path`` relative to the project root, for messages."""
        return self.layout.relative(path) if self.layout.root else path

    # ---- 1. project layout ---------------------------------------------------------------------------
    def declare_project_root(self, path):
        """
        The project root.

        :param path: relative to the Snakefile's folder (``".."`` for ``<root>/workflow/Snakefile``), or
            absolute. Without a workflow (no :meth:`load_workflow`), relative to the current folder.
        """
        base = self.base_dir or os.getcwd()
        self.layout.set_root(path if os.path.isabs(path) else os.path.join(base, path))
        self.trace("project root", self.layout.root)

    def declare_folder(self, name, path, must_exist=False, description=""):
        """
        A named folder of the project.

        .. code-block:: python

            wf_util.declare_folder("wrappers", "workflow/wrappers", must_exist=True,
                                   description="one folder per tool")
            wf_util.declare_folder("results", "results/{info.name}")

        A project has ``config``, ``profiles``, ``wrappers``, ``scripts``, ``schemas``, ``report``,
        ``resources``, ``inputs`` and ``results`` without declaring them (see
        :data:`bakery.project.DEFAULT_FOLDERS`); declaring one of these names replaces it.

        :param name: the name other steps use: ``wrappers``, ``scripts``, ``schemas``, ``report``,
            ``inputs`` (files named in the config), ``results`` (what the workflow makes), ...
        :param path: relative to the project root. ``{a.b}`` is filled in from the config when it is
            loaded; the value must be a safe folder name.
        :param must_exist: :meth:`validate_config` fails when the folder is missing
        :param description: shown by ``bakery_help``
        """
        self._declaring("declare_folder")
        self.layout.declare(name, path, must_exist, description)

    # ---- 2. config keys ------------------------------------------------------------------------------
    def add_config_section(self, name, description=""):
        """
        Describe a section of the config file (``--configfile``).

        Not needed for the sections the recipe reads or a folder path names (``results/{info.name}``):
        they are known already, a missing one is an error, and one a folder path names comes only from
        the config file. Use it for a description, or for a section only the checks read.

        :param name: top-level key, e.g. ``"samples"``
        :param description: shown in errors and by ``bakery_help``
        """
        self._declaring("add_config_section")
        self.schema.add_section(name, description)

    def add_config_option(self, name, type_, default, description="", warn_if=None, warning=""):
        """
        A single value given with ``--config name=value``.

        bakery reads ``fake``, ``overwrite``, ``upstream``, ``downstream`` and ``list_limit`` itself;
        a Snakefile must declare them.

        :param type_: ``bool``, ``int``, ``float`` or ``str``; ``--config`` values are converted
        :param default: the value when it is not given
        :param warn_if: a value that shows ``warning`` on the confirmation screen
        :raises bakery.common.ConfigError: (in :meth:`validate_config`) when the value has the wrong type
        """
        self._declaring("add_config_option")
        self.schema.add_option(name, type_, default, description, warn_if, warning)

    def add_config_schema(self, file):
        """
        A JSON schema (written in YAML) for the structure of the config sections.

        :param file: relative to the ``schemas`` folder (or the project root without one)
        """
        self._declaring("add_config_schema")
        if not os.path.isabs(file):
            file = os.path.join(self.layout.folder_path("schemas"), file)
        self.schema.add_schema(file)

    def add_config_check(self, function, description=""):
        """
        A check JSON schema cannot express (cross references, lengths, ...).

        .. code-block:: python

            def points_fit_parameters(cfg):
                \"\"\"every point has one value per parameter\"\"\"
                ...
                yield "samples[0].points[1] has 1 value, T2 has 2 parameters"

            wf_util.add_config_check(points_fit_parameters)

        :param function: ``function(config)`` returns or yields problem texts
        :param description: added to each problem; the function's docstring when empty
        """
        self._declaring("add_config_check")
        self.schema.add_check(function, description or getattr(function, "__doc__", "") or function.__name__)

    # ---- 3. formats ----------------------------------------------------------------------------------
    def declare_format(self, name, function, pattern, description=""):
        """
        How a column value is written in a file name.

        .. code-block:: python

            wf_util.declare_format("tag", lambda v: str(v).replace(".", "p"), pattern=r"\\d+p\\d+")

        :param function: ``value -> text``
        :param pattern: regular expression every text must match; it becomes the wildcard constraint
        """
        self._declaring("declare_format")
        self.formats.add(name, function, pattern, description)

    # ---- 4. recipe -----------------------------------------------------------------------------------
    def expand_rows(self, record, over, where=None, missing=None):
        """
        Recipe step: one row per item of ``over``; the item is kept in the row as a record.

        .. code-block:: python

            wf_util.expand_rows("sample", over="samples[*]")
            wf_util.expand_rows("point", over="sample.points[*]")
            wf_util.expand_rows("gen", over=Tools("generators", enabled=True))
            wf_util.expand_rows("sim", over=..., missing="NONE")

        :param record: the record name, read later as ``row.record("sample")`` or
            ``param("sample.nevents")``
        :param over: a path with ``[*]`` (from the row's records, else from the config), a function
            ``row -> items``, or :class:`bakery.tools.Tools`. A plain name as item becomes ``{"name": item}``.
        :param where: ``row -> bool``; rows it rejects are dropped
        :param missing: when no item is left: ``None`` drops the row, a value keeps it with that
            record, a function ``row -> value or None`` decides per row
        """
        self._declaring("expand_rows")
        self.recipe.add(ExpandRows(record, over, where, missing))

    def declare_lookup(self, record, section, key, by):
        """
        Recipe step: find the entry of a config list whose ``key`` equals a value of the row.

        .. code-block:: python

            wf_util.declare_lookup("process", section="processes", key="name", by="sample.process")

        :param record: the record name for the entry found
        :param section: the list: a config section or a path into a record
        :param by: the value to look for: a column or a record path
        :raises bakery.common.RecipeError: (in :meth:`build_manifest`) when there is no such entry
        """
        self._declaring("declare_lookup")
        self.recipe.add(DeclareLookup(record, section, key, by))

    def declare_column(self, name, from_, missing=None, known=None, unknown="NONE"):
        """
        Recipe step: one value per row.

        .. code-block:: python

            wf_util.declare_column("sqrts", from_="process.sqrts", missing=13.0)
            wf_util.declare_column("recaster", from_="recasting.name",
                                   known=Tools("recasters"), unknown="NONE")

        :param from\\_: a path (``"process.sqrts"``) or a function ``row -> value``
        :param missing: the value (or ``row -> value``) when ``from_`` gives nothing
        :param known: allowed values (a list or :class:`bakery.tools.Tools`)
        :param unknown: what a value outside ``known`` becomes (see ``build_manifest(on_unknown=)``)
        """
        self._declaring("declare_column")
        self.recipe.add(DeclareColumn(name, from_, missing, known, unknown))

    # ---- 5. wildcards --------------------------------------------------------------------------------
    def declare_wildcard(self, name, column=None, format=None, pattern=None, description=""):
        """
        A column that appears in file names.

        .. code-block:: python

            wf_util.declare_wildcard("sqrts", format="tag")                          # 13.0 -> 13p0
            wf_util.declare_wildcard("param_pt", column="param_values", format="point")

        :param column: the column it shows; ``name`` when not given
        :param format: the name of an :meth:`declare_format`; the column keeps the raw value
        :param pattern: the wildcard constraint; else the format's, else ``[^/.]+``
        """
        self._declaring("declare_wildcard")
        self.wildcards.declare(name, column, self.formats.get(format) if format else None, pattern, description)

    def declare_selector(self, *names):
        """
        Wildcards a run can be narrowed with: ``--config process=T2 generator='MG5*|Pythia8'``.
        """
        self._declaring("declare_selector")
        self.wildcards.declare_selectors(names)

    # ---- 6. config -----------------------------------------------------------------------------------
    def load_config(self, config, cli_keys=None):
        """
        Take the config (a copy; YAML dates become text).

        :param config: Snakemake's ``config`` (``--configfile`` and ``--config`` merged)
        :param cli_keys: keys that came from ``--config`` (``info`` may not)
        """
        self.config = plain_dates(copy.deepcopy(dict(config or {})))
        if cli_keys is not None:
            self.cli_keys = tuple(cli_keys)
        try:
            self._trace_on = parse_bool(self.config.get("bakery_trace", False))
        except ValueError:
            self._trace_on = False
        if self._trace_on and self.main:
            print("\n".join(self._trace))
        self._trace = []
        self._infer_sections()
        sections = [k for k in self.config if k in self.schema.sections]
        self.trace("load_config", f"{len(sections)} sections, --config: {', '.join(self.cli_keys) or 'none'}")

    def validate_config(self):
        """
        Check the config and freeze the declarations.

        Checks, all reported at once: unknown keys (with "did you mean"), missing sections, option
        types, ``info`` given with ``--config``, the JSON schema, repeated names, the
        :meth:`add_config_check` functions, the recipe against the sections, the folders.

        :raises bakery.common.ConfigError: listing every problem
        """
        self._need(self.config is not None, "validate_config()", "load_config(config)")
        self._need(self.layout.root is not None, "validate_config()", "declare_project_root(...)")
        self.recipe.frozen = True
        self._infer_sections()
        self.wildcards.check_columns(self.recipe.columns())
        self.options = validate(self.config, self.schema, self.wildcards.selectors, self.cli_keys)
        self.layout.resolve(self.config)
        self.layout.check()
        fake_dir = os.path.join(self.layout.root, ".snakemake", "fake_tool")
        self.tool_resolver = (FakeTools(fake_dir, write=self.main) if self.options["fake"]
                              else RealTools(self.layout.folder_path("wrappers"), self.layout.folder_path("scripts")))
        self.trace("validate_config", "ok: " + ", ".join(f"{k}={v}" for k, v in self.options.items()))

    def _infer_sections(self):
        """The sections nobody added: those folder paths are filled in from (file only) and those the recipe reads."""
        for section, folder in self.layout.config_sections().items():
            self.schema.infer_section(section, f"names the {folder} folder; only from --configfile", file_only=True)
        for section in self.recipe.config_sections():
            self.schema.infer_section(section, "read by the recipe")

    # ---- 7. manifest ---------------------------------------------------------------------------------
    def build_manifest(self, on_empty="error", on_unknown="none"):
        """
        Apply the recipe to the config.

        :param on_empty: ``"error"`` or ``"warn"`` when the config gives no row
        :param on_unknown: a value outside ``known=`` of a column: ``"none"`` turns it into
            ``unknown`` (with a note), ``"error"`` stops
        :returns: every row
        :rtype: :class:`bakery.manifest.Manifest`
        :raises bakery.common.RecipeError: a lookup finds nothing, a value does not fit its pattern
        """
        self._need(self.options is not None, "build_manifest()", "validate_config()")
        rows, notes = self.recipe.build(self.config, on_unknown)
        rows = [self.wildcards.apply(r) for r in rows]
        self.notes = notes
        if not rows:
            message = "the config gives no manifest row (are the tools enabled, do analyses match?)"
            if on_empty == "error":
                raise ConfigError(message)
            self.notes.append(message)
        self.manifest = Manifest(rows, self.wildcards.names())
        self.trace("build_manifest", f"{len(rows)} rows")
        return self.manifest

    def apply_selection(self, manifest, selectors="config", exclude=None, on_empty="error"):
        """
        The rows of this run.

        .. code-block:: python

            selected = wf_util.apply_selection(manifest)                           # --config process=T2
            selected = wf_util.apply_selection(manifest, selectors={"process": "T2"})
            selected = wf_util.apply_selection(manifest, exclude={"generator": "Pythia8"})

        Patterns may use ``*`` and ``?``; several are separated by ``|`` (or ``,``).

        :param manifest: what to select from
        :param selectors: ``"config"`` (the selectors given with ``--config``), a dict, or ``None``
        :param exclude: a dict of patterns to leave out
        :param on_empty: ``"error"`` or ``"warn"`` when nothing is left
        :rtype: :class:`bakery.manifest.Manifest` (its ``full`` is the whole manifest)
        :raises bakery.common.ConfigError: a selector that is not declared or matches nothing
        """
        self._need(self.manifest is not None, "apply_selection()", "build_manifest()")
        if selectors == "config":
            include = patterns_from(self.config, self.wildcards.selectors)
        elif selectors is None:
            include = {}
        else:
            include = patterns_from(dict(selectors), list(dict(selectors)))
        excl = patterns_from(dict(exclude or {}), list(dict(exclude or {})))
        self.selected = select(manifest, self.wildcards.selectors, include, excl, on_empty)
        chosen = ", ".join(f"{k}={v}" for k, v in self.selected.selection.items())
        self.trace("apply_selection", f"{len(self.selected)} rows" + (f" ({chosen})" if chosen else ""))
        return self.selected

    # ---- 8. paths ------------------------------------------------------------------------------------
    def declare_path(self, folder, template):
        """
        A file template inside a declared folder.

        .. code-block:: python

            P_GEN_HEPMC = wf_util.declare_path("results", f"{POINT}/{{generator}}.events.hepmc.gz")

        :param folder: a :meth:`declare_folder` name
        :param template: relative to the folder; every ``{x}`` must be a declared wildcard
        :returns: the absolute template
        :raises bakery.common.ConfigError: an unknown wildcard (with "did you mean")
        """
        self._need(self.options is not None, "declare_path()", "validate_config() (folders need the config)")
        return self.paths.declare(folder, self.layout.folder_path(folder), template, self.wildcards.names())

    def get_wildcard_constraints(self):
        """``{wildcard: pattern}`` for ``wildcard_constraints: **wf_util.get_wildcard_constraints()``."""
        return self.wildcards.constraints()

    # ---- 9. values for rules -------------------------------------------------------------------------
    def _lookup(self):
        if self._row_lookup is None:
            self._need(self.manifest is not None, "param()/param_path()", "build_manifest()")
            handled = self.planner.handled if self.planner is not None else None
            self._row_lookup = RowLookup(self.manifest, self._resolve_input, handled)
        return self._row_lookup

    def _resolve_input(self, value):
        folder = self.layout.folder_path("inputs")
        return value if os.path.isabs(value) else os.path.join(folder, value)

    def param(self, path, default=REQUIRED, type_=None, is_file=False):
        """
        A value of the job, read from its manifest rows when Snakemake builds the job.

        .. code-block:: python

            nevents=wf_util.param("sample.nevents", type_=int),
            delphes_card=wf_util.param(("detector.delphes_card", "detector.card"), is_file=True),

        :param path: a column (``"sqrts"``), a record path (``"sample.nevents"``), or a tuple of
            paths tried in order
        :param default: the value when the config does not set it; without one that is an error
        :param type_: ``int``, ``float``, ``str`` or ``bool``, checked
        :param is_file: the value is a file name relative to the ``inputs`` folder
        :returns: a function Snakemake calls with the job's wildcards
        :raises bakery.common.RecipeError: the path does not start with a recipe name (now), or the
            value is missing, has the wrong type or differs between the job's rows (per job)
        """
        for p in ((path,) if isinstance(path, str) else path):
            self.recipe.check_path(p)
        return Param(self._lookup, path, default, type_, is_file)

    def param_path(self, template, **fixed):
        """
        A path of the job: ``template`` filled from its manifest rows.

        .. code-block:: python

            root=wf_util.param_path(P_DET_ROOT, det_sim="delphesCutlang"),

        :param template: a :meth:`declare_path` template
        :param fixed: values of wildcards the job does not have (a value or a :meth:`param`)
        :returns: a function Snakemake calls with the job's wildcards
        """
        unknown = [k for k in fixed if k not in self.wildcards.names()]
        if unknown:
            raise ConfigError(f"param_path: {', '.join(unknown)} is not a declared wildcard")
        return ParamPath(self._lookup, template, fixed)

    def match(self, wildcard, **columns):
        """
        A ``wildcard_constraints`` pattern from the config instead of names in the Snakefile.

        .. code-block:: python

            wildcard_constraints:
                det_sim=wf_util.match("det_sim", det_sim_type="delphes"),

        :returns: the values of ``wildcard`` in rows whose ``columns`` equal the given values,
            joined with ``|``; a pattern that matches nothing (with a note) when there are none
        """
        self._need(self.manifest is not None, "match()", "build_manifest()")
        values = sorted({r.wildcards[wildcard] for r in self.manifest
                         if all(r.get(k) == v for k, v in columns.items())} - {"NONE"})
        if not values:
            self.notes.append(f"match({wildcard!r}, {columns}) matches no row; the rule makes nothing")
            return "(?!)"
        return "|".join(re.escape(v) for v in values)

    def resolve_wrapper(self, name):
        """
        The folder of wrapper ``name`` (``wrappers`` folder), or the fake tool with ``fake=true``.

        :raises bakery.common.ConfigError: ``wrapper.py`` or ``environment.yaml`` is missing
        """
        self._need(self.tool_resolver is not None, "resolve_wrapper()", "validate_config()")
        return self.tool_resolver.wrapper(name)

    def resolve_script(self, name):
        """The script ``name`` in the ``scripts`` folder, or the fake tool with ``fake=true``."""
        self._need(self.tool_resolver is not None, "resolve_script()", "validate_config()")
        return self.tool_resolver.script(name)

    def resolve_report(self, name):
        """A caption file of ``report(...)`` in the ``report`` folder."""
        return os.path.join(self.layout.folder_path("report"), name)

    def get_option(self, name):
        """The value of an :meth:`add_config_option` (after :meth:`validate_config`)."""
        self._need(self.options is not None, "get_option()", "validate_config()")
        if name not in self.options:
            raise ConfigError(f"no option '{name}' (add_config_option); options: {', '.join(self.options)}")
        return self.options[name]

    def get_config(self, path):
        """
        A value of the config, e.g. ``get_config("info.name")``.

        :raises bakery.common.ConfigError: the config does not have it
        """
        self._need(self.config is not None, "get_config()", "load_config(config)")
        value = walk(self.config, segments(path))
        if value is None:
            raise ConfigError(f"the config has no {path}")
        return value

    def list_files(self, template, same=(), like=None, existing_only=False):
        """
        Every file of ``template`` from the rows that agree with a job on some wildcards.

        .. code-block:: python

            def group_embakes(wildcards):
                return wf_util.list_files(P_EMBAKE, same=("sqrts", "process", "generator",
                                          "recaster", "analysis"), like=wildcards)

        Only files some rule makes are listed (once ``build_targets`` has run).

        :param same: the wildcards that must agree
        :param like: the job's wildcards
        :param existing_only: only files on disk
        :rtype: list[str]
        """
        values = as_dict(like) if like is not None else {}
        planner = self.planner
        out = set()
        for row in self.manifest.full.rows(planner.handled if planner else None):
            if all(str(row.wildcards[k]) == str(values[k]) for k in same):
                path = strip_constraints(template).format(**row.wildcards)
                if planner is None or planner.views is None or path in planner.produced:
                    out.add(path)
        if existing_only:
            out = {p for p in out if os.path.exists(p)}
        return sorted(out)

    # ---- manifest views ------------------------------------------------------------------------------
    def list_manifest(self, manifest, where=None, columns=None):
        """
        The rows of ``manifest``.

        :param where: ``row -> bool``
        :param columns: names; then each row is a dict of those wildcards/columns
        """
        rows = manifest.rows(where)
        if columns is None:
            return list(rows)
        return [{c: (r.wildcards[c] if c in r.wildcards else r.get(c)) for c in columns} for r in rows]

    def print_manifest(self, manifest, columns=None, sort_by=None, limit=20):
        """
        Print ``manifest`` as a table.

        :param columns: wildcards/columns to show; every wildcard when ``None``
        :param sort_by: a name or a list of names
        :param limit: rows shown; ``0`` shows all
        """
        self.say(reports.manifest_table(manifest, columns, sort_by, limit))

    def show_manifest(self, manifest, columns=None, sort_by=None, limit=20):
        """:meth:`print_manifest`, only with ``--config show=manifest``."""
        if "manifest" in self._show():
            self.print_manifest(manifest, columns, sort_by, limit)

    def _show(self):
        raw = (self.config or {}).get("show") or ""
        return {s.strip() for s in str(raw).replace("|", ",").split(",") if s.strip()}

    # ---- 10.-11. targets -----------------------------------------------------------------------------
    def plan_targets(self, selected, specs):
        """
        ``build_targets`` without Snakemake.

        :param selected: the rows of this run (:meth:`apply_selection`)
        :param specs: the rules, as :class:`bakery.planner.RuleSpec`
        :returns: ``{rule: RuleView}``
        """
        self._need(self.selected is not None, "build_targets()", "apply_selection(manifest)")
        enabled = {s: [t.get("name") for t in Tools(s, True).items(self.config)]
                   for s in self.recipe.tool_columns()}
        tool_wildcards = {}
        for section, column in self.recipe.tool_columns().items():
            for w in self.wildcards.all():
                if w.column == column:
                    tool_wildcards[section] = w.name
        self.planner = TargetPlanner(selected, tool_wildcards, enabled, self.options, short_path=self.short_path)
        self._row_lookup = None
        self.planner.plan(specs)
        self.trace("build_targets", ", ".join(f"{v.name}={len(v.to_run)}" for v in self.planner.views.values()))
        return self.planner.views

    def list_target_files(self, rule=None, state="to_run", by_rule=False):
        """
        Files of the plan.

        .. code-block:: python

            for _name, _files in wf_util.list_target_files(by_rule=True).items():   # run_<rule>
                ...
            rule all:
                input: wf_util.list_target_files(state="all")

        :param rule: one rule, or every rule
        :param state: ``"to_run"`` (this run makes them), ``"on_disk"``, ``"waiting"`` (an input is
            missing), ``"blocked"`` (cannot be made), ``"all"`` (to_run + on_disk + waiting)
        :param by_rule: ``{rule: files}`` instead of one sorted list
        """
        self._need(self.planner is not None, "list_target_files()", "build_targets(selected)")
        return self.planner.target_files(rule, state, by_rule)

    def print_target_files(self, rule=None, state="to_run", limit=10):
        """Print :meth:`list_target_files` per rule; ``limit`` files per rule (``0``: all)."""
        by_rule = self.list_target_files(rule, state, by_rule=True)
        self.say(reports.target_files_table(by_rule, state, self.short_path, limit))

    def show_target_files(self, rule=None, state="to_run", limit=10):
        """:meth:`print_target_files`, only with ``--config show=target_files``."""
        if "target_files" in self._show():
            self.print_target_files(rule, state, limit)

    # ---- 12. report ----------------------------------------------------------------------------------
    def list_warnings(self):
        """Warnings of the declared paths and the plan, without repeats."""
        return list(dict.fromkeys(self.paths.warnings + (self.planner.warnings if self.planner else [])))

    def get_output_folder(self):
        """The ``results`` folder, relative to the project root."""
        return self.short_path(self.layout.folder_path("results")) + "/" if self.layout.has("results") else "-"

    def print_report(self):
        """
        The summary: files per rule (to run, on disk, waiting, blocked), what can be run instead,
        notes and warnings. With ``--config bakery_help=true`` also the help. Main process only.
        """
        self._need(self.planner is not None, "print_report()", "build_targets(selected)")
        if not self.main:
            return
        if _true(self.config.get("bakery_help")):
            print(reports.help_text(self.schema, FRAMEWORK_KEYS, self.wildcards, self.manifest, self.layout,
                                    self.formats.all()))
        print(reports.report(self.planner.views, self.options, self.selected.selection, len(self.selected),
                             len(self.manifest), self.get_output_folder(), self.notes, self.list_warnings(), self.short_path))


def _true(value):
    try:
        return parse_bool(value or False)
    except ValueError:
        return False
