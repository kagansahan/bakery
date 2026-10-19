"""
``build_targets``: what each rule makes, and what this run asks for.

For every rule the output templates are filled from the selected rows that fit the rule's
``wildcard_constraints``. Each file is then

* ``blocked``: an input can never exist (no rule makes it and it is not on disk)
* ``on_disk``: all outputs exist (made again only with ``overwrite=true``)
* ``waiting``: an input is missing and ``upstream=false``
* ``to_run``: everything else

Rules come in as :class:`RuleSpec`; the planner does not know Snakemake.
"""

import dataclasses
import os
import re

from .common import ConfigError, RecipeError


STATES = ("to_run", "on_disk", "waiting", "blocked", "all")


@dataclasses.dataclass
class RuleSpec:
    name: str
    outputs: tuple                  # templates, constraints stripped
    wildcards: frozenset            # wildcard names of the outputs
    constraints: dict               # global + rule constraints for the output wildcards
    rule_constraints: dict          # the rule's own wildcard_constraints (for the checks)
    inputs_fn: object               # callable: {wildcard: value} -> list of input files


@dataclasses.dataclass
class RuleView:
    spec: RuleSpec
    rows: dict = dataclasses.field(default_factory=dict)        # primary output -> rows
    outputs: dict = dataclasses.field(default_factory=dict)     # primary output -> every output
    inputs: dict = dataclasses.field(default_factory=dict)      # primary output -> inputs
    chain: tuple = ()
    to_run: tuple = ()
    on_disk: tuple = ()
    waiting: dict = dataclasses.field(default_factory=dict)     # primary output -> missing inputs
    blocked: dict = dataclasses.field(default_factory=dict)     # primary output -> reason

    @property
    def name(self):
        return self.spec.name

    def files(self, state="to_run"):
        if state == "to_run":
            return list(self.to_run)
        if state == "on_disk":
            return list(self.on_disk)
        if state == "waiting":
            return sorted(self.waiting)
        if state == "blocked":
            return sorted(self.blocked)
        if state == "all":
            return list(self.chain)
        raise ConfigError(f"state must be one of {', '.join(STATES)}")


class LocalFileSystem:
    def exists(self, path):
        return os.path.exists(path)


class TargetPlanner:
    def __init__(self, selected, tool_wildcards, enabled_tools, settings, fs=None, short_path=str):
        self.selected = selected
        self.tool_wildcards = tool_wildcards      # {config section: wildcard}
        self.enabled_tools = enabled_tools        # {config section: [enabled names]}
        self.settings = settings                  # overwrite / upstream / downstream
        self.fs = fs or LocalFileSystem()
        self.short_path = short_path
        self.views = None
        self.covered = {}
        self.produced = set()
        self.owner = {}
        self.warnings = []

    # ---- rows no rule makes are left out of lookups ----------------------------------------------
    def handled(self, row):
        if self.views is None:
            return True
        return all(row.wildcards.get(w) in ("NONE", None) or row.wildcards.get(w) in self.covered.get(w, ())
                   for w in self.tool_wildcards.values())

    def plan(self, specs):
        views = {}
        for spec in specs:
            for w in sorted(set(spec.rule_constraints) - spec.wildcards):
                self.warnings.append(f"rule {spec.name}: wildcard_constraints has '{w}', but '{w}' is not a "
                                     f"wildcard of its output ({', '.join(sorted(spec.wildcards)) or 'none'})")
            view = RuleView(spec)
            for row in self.selected:
                wc = row.wildcards
                if any(wc.get(w) in (None, "NONE") for w in spec.wildcards):
                    continue
                if not all(re.fullmatch(p, str(wc.get(w))) for w, p in spec.constraints.items()):
                    continue
                files = [o.format(**wc) for o in spec.outputs]
                if not files:
                    continue
                view.rows.setdefault(files[0], []).append(row)
                view.outputs.setdefault(files[0], files)
            views[spec.name] = view
        self.views = views
        self._coverage()
        self._leave_out_unhandled()
        self._owners()
        self._blocked = set()
        for view in views.values():
            self._classify(view)
        if self.settings.get("downstream"):
            self._add_downstream()
        return views

    def _coverage(self):
        """A tool value is covered when a rule that names the tool wildcard in its own
        wildcard_constraints makes files for it. Rules that only pass a tool wildcard through (delphes reads any generator)
        do not count. A tool wildcard no rule constrains counts as covered for every value."""
        views = self.views
        self.covered = {}
        for w in self.tool_wildcards.values():
            producers = [v for v in views.values() if w in v.spec.rule_constraints and w in v.spec.wildcards]
            if producers:
                self.covered[w] = {r.wildcards[w] for v in producers for rows in v.rows.values() for r in rows}
            else:
                self.covered[w] = {r.wildcards[w] for r in self.selected}
        for section, wildcard in self.tool_wildcards.items():
            for name in self.enabled_tools.get(section, ()):
                if name not in self.covered.get(wildcard, set()):
                    self.warnings.append(f"{section}[{name}] is enabled, but no rule makes files for "
                                         f"{wildcard}={name}; it is left out")

    def _leave_out_unhandled(self):
        for v in self.views.values():
            kept_rows, kept_outputs = {}, {}
            for primary, rows in v.rows.items():
                rows = [r for r in rows if self.handled(r)]
                if rows:
                    kept_rows[primary], kept_outputs[primary] = rows, v.outputs[primary]
            v.rows, v.outputs = kept_rows, kept_outputs

    def _owners(self):
        views = self.views
        owners = {}
        for v in views.values():
            for files in v.outputs.values():
                for f in files:
                    owners.setdefault(f, []).append(v.name)
        self.produced = set(owners)
        self.owner = {f: names[0] for f, names in owners.items()}
        clashes = {}
        for f, names in owners.items():
            if len(set(names)) > 1:
                clashes.setdefault(tuple(sorted(set(names))), []).append(f)
        for names, files in clashes.items():
            self.warnings.append(f"rules {' and '.join(names)} both make {len(files)} files (e.g. "
                                 f"{self.short_path(files[0])}); check their wildcard_constraints")

    def _inputs(self, view, row):
        return [str(i) for i in view.spec.inputs_fn({k: row.wildcards[k] for k in view.spec.wildcards})]

    def _classify(self, view):
        chain, to_run, on_disk = [], [], []
        for primary, rows in view.rows.items():
            try:
                inputs = self._inputs(view, rows[0])
                self._same_inputs(view, primary, rows, inputs)
            except RecipeError as err:
                view.blocked[primary] = str(err).splitlines()[0]
                continue
            cannot = [i for i in inputs if i in self._blocked or (not self.fs.exists(i) and i not in self.produced)]
            if cannot:
                owner = self.owner.get(cannot[0])
                view.blocked[primary] = (f"needs {self.short_path(cannot[0])}, which "
                                         + (f"{owner} cannot make" if owner else "no rule makes and is not on disk"))
                continue
            view.inputs[primary] = inputs
            chain.append(primary)
            exists = all(self.fs.exists(f) for f in view.outputs[primary])
            missing = [i for i in inputs if not self.fs.exists(i)]
            if exists:
                on_disk.append(primary)
                if self.settings.get("overwrite") and not missing:
                    to_run.append(primary)
            elif missing and not self.settings.get("upstream"):
                view.waiting[primary] = missing
            else:
                to_run.append(primary)
        view.chain, view.to_run, view.on_disk = tuple(sorted(chain)), tuple(sorted(to_run)), tuple(sorted(on_disk))
        self._blocked.update(f for p in view.blocked for f in view.outputs[p])

    def _same_inputs(self, view, primary, rows, inputs):
        """Rows that make the same file must read the same inputs; otherwise the file name is too short."""
        for row in rows[1:]:
            other = self._inputs(view, row)
            if sorted(other) != sorted(inputs):
                diff = {k: (rows[0].wildcards[k], row.wildcards[k]) for k in row.wildcards
                        if rows[0].wildcards[k] != row.wildcards[k]}
                names = ", ".join(f"{k}={a} / {k}={b}" for k, (a, b) in diff.items())
                raise ConfigError(f"rule {view.name}: two rows make {self.short_path(primary)} from different inputs "
                                  f"({names}). Add the wildcard to the output path, or let the rule read one "
                                  f"input (param_path(..., {next(iter(diff), 'x')}=...)).")

    def _add_downstream(self):
        """downstream=true: run_X also asks for the missing files other rules make from X's files
        (the ones this run makes and the ones already on disk)."""
        for v in self.views.values():
            made = set(f for p in tuple(v.to_run) + tuple(v.on_disk) for f in v.outputs[p])
            extra, changed = set(), True
            while changed:
                changed = False
                for d in self.views.values():
                    if d is v:
                        continue
                    for primary in d.chain:
                        if primary in extra:
                            continue
                        ins = d.inputs.get(primary, [])
                        if ins and set(ins) & made and all(i in made or self.fs.exists(i) for i in ins):
                            if self.settings.get("overwrite") or not self.fs.exists(primary):
                                extra.add(primary)
                                made.update(d.outputs[primary])
                                changed = True
            v.to_run = tuple(sorted(set(v.to_run) | extra))

    # ---- results -----------------------------------------------------------------------------------
    def target_files(self, rule=None, state="to_run", by_rule=False):
        if state not in STATES:
            raise ConfigError(f"state must be one of {', '.join(STATES)}")
        if rule is not None and rule not in self.views:
            raise ConfigError(f"no rule '{rule}'; rules: {', '.join(self.views)}")
        views = [self.views[rule]] if rule else list(self.views.values())
        if by_rule:
            return {v.name: v.files(state) for v in views}
        return sorted({f for v in views for f in v.files(state)})
