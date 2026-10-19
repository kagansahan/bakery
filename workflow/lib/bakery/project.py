"""
Where things live.

* :class:`ProjectLayout`: the project root and named folders (``results/{info.name}`` is filled in
  from the config)
* :class:`PathTemplates`: ``declare_path``; every ``{x}`` must be a declared wildcard
* :class:`RealTools` / :class:`FakeTools`: the wrapper/script of a rule, or one placeholder tool
"""

import dataclasses
import os
import re

from .common import ConfigError, did_you_mean, head, segments, walk


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+-]*$")


#: the folders every project has: (name, path, must_exist, description). ``declare_folder`` replaces one.
DEFAULT_FOLDERS = (
    ("config", "config", True, "config files; bakery run --configfile <name> looks here"),
    ("profiles", "profiles", False, "Snakemake profiles; bakery run --profile <name> looks here"),
    ("wrappers", "workflow/wrappers", True, "one folder per tool: wrapper.py + environment.yaml (resolve_wrapper)"),
    ("scripts", "workflow/scripts", True, "python scripts of script: rules (resolve_script)"),
    ("schemas", "workflow/schemas", False, "JSON schema of the config (add_config_schema)"),
    ("report", "workflow/report", False, "captions of report() outputs (resolve_report)"),
    ("resources", "resources", False, "static data the workflow reads, e.g. downloaded tables"),
    ("inputs", ".", True, "files named in the config (cards, ADL files): param(..., is_file=True)"),
    ("results", "results", False, "every file this config makes; bakery clean only deletes here"),
)


@dataclasses.dataclass
class Folder:
    name: str
    template: str
    must_exist: bool
    description: str
    path: str = None        # absolute, once resolved


class ProjectLayout:
    def __init__(self):
        self.root = None
        self.folders = {}
        self._defaults = set()      # folders still as DEFAULT_FOLDERS made them

    def set_root(self, root):
        """Set the root and make the default folders (a first call only)."""
        self.root = os.path.abspath(root)
        for name, template, must_exist, description in DEFAULT_FOLDERS:
            if name not in self.folders:
                self._add(name, template, must_exist, description)
                self._defaults.add(name)

    def declare(self, name, template, must_exist=False, description=""):
        """Add a folder, or replace a default one (it keeps its description when none is given)."""
        if self.root is None:
            raise ConfigError("declare_project_root(...) comes before declare_folder(...)")
        if name in self.folders and name not in self._defaults:
            raise ConfigError(f"folder '{name}' is declared twice")
        if name in self._defaults:
            description = description or self.folders[name].description
            self._defaults.discard(name)
        self._add(name, template, must_exist, description)

    def _add(self, name, template, must_exist, description):
        self.folders[name] = Folder(name, template, must_exist, description)
        if not _PLACEHOLDER.search(template):
            self.folders[name].path = self._join(template)

    def config_sections(self):
        """``{section: folder}`` for the sections folder paths are filled in from (``results/{info.name}``)."""
        out = {}
        for folder in self.folders.values():
            for match in _PLACEHOLDER.finditer(folder.template):
                out.setdefault(head(match.group(1)), folder.name)
        return out

    def resolve(self, config):
        """Fill in the config values of the folder paths."""
        for folder in self.folders.values():
            if folder.path is None:
                folder.path = self._join(_PLACEHOLDER.sub(lambda m: self._value(folder, m.group(1), config),
                                                          folder.template))

    def check(self):
        """Folders declared with must_exist=True must be there."""
        missing = [f for f in self.folders.values() if f.must_exist and not os.path.isdir(f.path)]
        if missing:
            raise ConfigError("missing project folders:\n  - " + "\n  - ".join(
                f"{f.name}: {self.relative(f.path)}/ ({f.description})" for f in missing))

    def folder_path(self, name):
        folder = self.folders.get(name)
        if folder is None:
            raise ConfigError(f"no folder '{name}' is declared (declare_folder); declared: "
                              + ", ".join(self.folders))
        if folder.path is None:
            raise ConfigError(f"folder '{name}' ({folder.template}) needs the config: call it after load_config")
        return folder.path

    def has(self, name):
        return name in self.folders

    def relative(self, path):
        try:
            rel = os.path.relpath(path, self.root)
        except ValueError:
            return path
        return path if rel.startswith("..") else rel

    def _join(self, rel):
        return os.path.normpath(rel if os.path.isabs(rel) else os.path.join(self.root, rel))

    @staticmethod
    def _value(folder, path, config):
        value = walk(config, segments(path))
        if value in (None, ""):
            raise ConfigError(f"folder '{folder.name}' is {folder.template}, but the config has no {path}")
        if not _SAFE_PART.match(str(value)):
            raise ConfigError(f"{path}={value!r} names the folder {folder.template}; use letters, digits, "
                              f"'_', '+' or '-' only")
        return str(value)


_WILDCARD = re.compile(r"\{\s*(\w+)\s*(?:,[^{}]*(?:\{[^{}]*\}[^{}]*)*)?\}")


def wildcard_names(template):
    return [m.group(1) for m in _WILDCARD.finditer(template)]


def strip_constraints(template):
    return _WILDCARD.sub(lambda m: "{" + m.group(1) + "}", template)


class PathTemplates:
    def __init__(self):
        self.templates = {}     # absolute template -> folder name
        self.warnings = []

    def declare(self, folder_name, folder_path, template, wildcards):
        if os.path.isabs(template):
            raise ConfigError(f"declare_path('{folder_name}', '{template}'): the template is relative to the folder")
        unknown = [w for w in wildcard_names(template) if w not in wildcards]
        if unknown:
            raise ConfigError(f"declare_path: {template} has " + ", ".join(
                f"{{{w}}}, which is not a declared wildcard{did_you_mean(w, wildcards)}" for w in unknown))
        full = os.path.join(folder_path, template)
        if full in self.templates:
            self.warnings.append(f"the path {folder_name}/{template} is declared twice; one name is enough")
        self.templates[full] = folder_name
        return full


FAKE_WRAPPER_CODE = '''"""FAKE tool (bakery, fake=true): writes placeholder outputs, runs nothing."""
import gzip, pathlib
for target in map(str, snakemake.output):
    pathlib.Path(target).parent.mkdir(parents=True, exist_ok=True)
    with (gzip.open if target.endswith(".gz") else open)(target, "wt") as fh:
        fh.write(f"# FAKE {snakemake.rule}\\n# input:  {[str(i) for i in snakemake.input]}\\n"
                 f"# params: {dict(snakemake.params.items())}\\n")
for log in map(str, getattr(snakemake, "log", []) or []):
    pathlib.Path(log).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(log).write_text(f"[FAKE] {snakemake.rule}\\n")
'''
FAKE_ENVIRONMENT = "channels: [conda-forge]\ndependencies: [python]\n"


class RealTools:
    def __init__(self, wrappers_dir, scripts_dir):
        self.wrappers_dir, self.scripts_dir = wrappers_dir, scripts_dir

    def wrapper(self, name):
        folder = os.path.join(self.wrappers_dir, name)
        missing = [f for f in ("wrapper.py", "environment.yaml") if not os.path.isfile(os.path.join(folder, f))]
        if missing:
            raise ConfigError(f"wrapper '{name}': {folder} has no {' and no '.join(missing)}")
        return folder

    def script(self, name):
        path = os.path.join(self.scripts_dir, name)
        if not os.path.isfile(path):
            raise ConfigError(f"script '{name}': {path} does not exist")
        return path


class FakeTools:
    def __init__(self, folder, write=True):
        self.folder = folder
        if write:
            os.makedirs(folder, exist_ok=True)
            for name, content in (("wrapper.py", FAKE_WRAPPER_CODE), ("environment.yaml", FAKE_ENVIRONMENT)):
                target = os.path.join(folder, name)
                if not os.path.exists(target) or open(target).read() != content:
                    with open(target, "w") as fh:
                        fh.write(content)

    def wrapper(self, name):
        return self.folder

    def script(self, name):
        return os.path.join(self.folder, "wrapper.py")
