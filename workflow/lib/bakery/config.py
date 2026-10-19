"""
What a config may contain, and :func:`validate`.

* sections: structured data from ``--configfile``; the recipe and the folder paths name them
  (``add_config_section`` only adds a description)
* options: single values from ``--config key=value`` (``add_config_option``)
* a JSON schema for the structure of the sections (``add_config_schema``)
* checks written in the Snakefile (``add_config_check``)
"""

import dataclasses
import os
import types

import yaml

from .common import ConfigError, convert, did_you_mean


#: options bakery itself reads; the Snakefile must declare them (with its own defaults and texts)
BUILTIN_OPTIONS = ("fake", "overwrite", "upstream", "downstream", "list_limit")

#: keys bakery always understands, without a declaration
FRAMEWORK_KEYS = {
    "bakery_help": "print the options, selectors, config sections and job values",
    "bakery_trace": "print one line per bakery stage while the Snakefile is read",
    "show": "comma separated: manifest, target_files -- the show_* lines print only these",
}

_TYPES = (bool, int, float, str)


@dataclasses.dataclass(frozen=True)
class Option:
    name: str
    type_: type
    default: object
    description: str
    warn_if: object = None
    warning: str = ""

    def parse(self, raw):
        if raw is None:
            return self.default
        try:
            return convert(raw, self.type_)
        except (TypeError, ValueError):
            raise ConfigError(f"--config {self.name}={raw!r}: should be {self.type_.__name__} "
                              f"({self.description})") from None

    def warning_for(self, value):
        if self.warning and self.warn_if is not None and value == self.warn_if:
            return self.warning
        return None


@dataclasses.dataclass(frozen=True)
class Check:
    function: object
    description: str


class ConfigSchema:
    def __init__(self):
        self.sections = {}      # name -> description
        self.file_only = set()  # sections that may not come from --config
        self.inferred = set()   # sections nobody added: a folder path or the recipe names them
        self.options = {}       # name -> Option
        self.schema_file = None
        self.checks = []

    def add_section(self, name, description):
        if name in self.sections and name not in self.inferred:
            raise ConfigError(f"config section '{name}' is added twice")
        self.inferred.discard(name)
        self.sections[name] = description

    def infer_section(self, name, description, file_only=False):
        """A section nobody added; an added one keeps its description."""
        if name not in self.sections:
            self.sections[name] = description
            self.inferred.add(name)
        if file_only:
            self.file_only.add(name)

    def add_option(self, name, type_, default, description, warn_if=None, warning=""):
        if name in self.options or name in self.sections:
            raise ConfigError(f"config key '{name}' is added twice")
        if type_ not in _TYPES:
            raise ConfigError(f"option '{name}': type must be one of bool, int, float, str")
        self.options[name] = Option(name, type_, convert(default, type_), description, warn_if, warning)

    def add_schema(self, path):
        if not os.path.isfile(path):
            raise ConfigError(f"config schema {path} does not exist")
        self.schema_file = path

    def add_check(self, function, description):
        self.checks.append(Check(function, description))


def validate(config, schema, selectors, cli_keys=()):
    """Return {option: value}. Raise ConfigError listing every problem found."""
    problems = []

    missing_builtin = [o for o in BUILTIN_OPTIONS if o not in schema.options]
    if missing_builtin:
        problems.append("bakery needs these options declared with add_config_option: " + ", ".join(missing_builtin))

    known = set(schema.sections) | set(schema.options) | set(selectors) | set(FRAMEWORK_KEYS)
    for key in config:
        if key not in known:
            problems.append(f"unknown config key '{key}'{did_you_mean(key, known)}")

    for key in sorted(schema.file_only):
        if key in cli_keys:
            problems.append(f"'{key}' cannot be set with --config; it comes only from the config file")

    for name, description in schema.sections.items():
        if name not in config:
            problems.append(f"the config has no '{name}' section ({description}). Did you forget --configfile?")

    options = {}
    for name, option in schema.options.items():
        try:
            options[name] = option.parse(config.get(name))
        except ConfigError as err:
            problems.append(str(err))

    if schema.schema_file and not problems:
        problems += _json_schema_problems(config, schema.schema_file)

    if not problems:
        problems += _duplicate_names(config, schema.sections)
        for check in schema.checks:
            for message in check.function(types.MappingProxyType(config)) or ():
                problems.append(f"{message} ({check.description})")

    if problems:
        raise ConfigError("the config has problems:\n  - " + "\n  - ".join(problems))
    return options


def _json_schema_problems(config, path):
    try:
        import jsonschema
    except ImportError:
        return [f"jsonschema is not installed; cannot check the config against {path}"]
    with open(path) as fh:
        schema = yaml.safe_load(fh)
    validator = jsonschema.validators.validator_for(schema)(schema)
    out = []
    for err in sorted(validator.iter_errors(config), key=lambda e: list(e.absolute_path))[:15]:
        where = "/".join(str(p) for p in err.absolute_path) or "<top>"
        out.append(f"{where}: {err.message}")
    return out


def _duplicate_names(config, sections):
    """Every list of named entries must have unique names (they become file names and lookups)."""
    out = []

    def visit(where, value):
        if isinstance(value, list):
            names = [v.get("name") for v in value if isinstance(v, dict) and "name" in v]
            dupes = sorted({n for n in names if names.count(n) > 1}, key=str)
            if dupes:
                out.append(f"{where}: the name {', '.join(map(str, dupes))} appears more than once")
            for i, v in enumerate(value):
                visit(f"{where}[{i}]", v)
        elif isinstance(value, dict):
            for k, v in value.items():
                visit(f"{where}.{k}", v)

    for name in sections:
        visit(name, config.get(name))
    return out
