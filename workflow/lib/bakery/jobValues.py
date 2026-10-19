"""
Values of one job, read from its manifest rows.

``param(...)`` and ``param_path(...)`` return callables. Snakemake calls them once per job with the
job's wildcards; the job's rows are the manifest rows with the same wildcard texts, and all of them
must give the same value.
"""

from .common import RecipeError
from .manifest import Manifest


class _Required:
    def __repr__(self):
        return "REQUIRED"


REQUIRED = _Required()
_TYPES = (bool, int, float, str)
_NUMBER = (int, float)
_CHECKS = {
    int: lambda v: (isinstance(v, int) and not isinstance(v, bool), v),
    float: lambda v: (isinstance(v, _NUMBER) and not isinstance(v, bool),
                      float(v) if isinstance(v, _NUMBER) and not isinstance(v, bool) else v),
    str: lambda v: (isinstance(v, str), v),
    bool: lambda v: (isinstance(v, bool), v),
}


def as_dict(wildcards):
    """A plain dict from a dict, a Snakemake Wildcards object, or anything with items()."""
    return {k: str(v) for k, v in dict(wildcards.items()).items()}


class RowLookup:
    """Reads values for jobs from the full manifest. `handled(row)` leaves out rows no rule makes."""

    def __init__(self, manifest, resolve_file, handled=None):
        self.manifest = manifest.full
        self.resolve_file = resolve_file
        self.handled = handled or (lambda row: True)

    def rows(self, wildcards, fixed=None):
        fixed = {k: str(v) for k, v in (fixed or {}).items()}
        return self.manifest.matching(wildcards, lambda r: self.handled(r) and all(
            str(r.wildcards.get(k)) == v for k, v in fixed.items()))

    def value(self, wildcards, path):
        rows = self.rows(wildcards)
        if not rows:
            raise RecipeError(f"no manifest row matches {wildcards} (is the rule's output missing a wildcard?)")
        return Manifest.one([r.read(path) for r in rows], f"'{path}'", wildcards)

    def record_keys(self, wildcards, path):
        """For error messages: the fields of the record `path` points into."""
        parent = path.rsplit(".", 1)[0] if "." in path else None
        for row in self.rows(wildcards):
            if not parent:
                break
            value = row.record(parent) if "." not in parent else row.read(parent)
            if isinstance(value, dict):
                return sorted(value)
        return []

    def fill(self, wildcards, template, fixed):
        rows = self.rows(wildcards, fixed)
        if not rows:
            pinned = ", ".join(f"{k}={v}" for k, v in fixed.items())
            if pinned:
                raise RecipeError(f"no manifest row with {pinned} for {wildcards}: is {pinned} enabled in the "
                                  f"config, and does a rule make it?")
            raise RecipeError(f"no manifest row matches {wildcards}")
        return Manifest.one([template.format(**r.wildcards) for r in rows], f"the path {template}", wildcards)


class Param:
    """param("sample.nevents", type_=int) -- a tuple of paths is tried in order."""

    def __init__(self, lookup_factory, paths, default=REQUIRED, type_=None, is_file=False):
        self._lookup_factory = lookup_factory    # () -> RowLookup (built later, by build_targets)
        self.paths = (paths,) if isinstance(paths, str) else tuple(paths)
        if type_ is not None and type_ not in _TYPES:
            raise RecipeError("param: type must be one of bool, int, float, str")
        self.default, self.type_, self.is_file = default, type_, is_file
        self.__name__ = f"param({' or '.join(self.paths)})"

    def __call__(self, wildcards):
        lookup = self._lookup_factory()
        wc = as_dict(wildcards)
        value = None
        for path in self.paths:
            value = lookup.value(wc, path)
            if value is not None:
                break
        label = " or ".join(self.paths)
        if value is None:
            if self.default is not REQUIRED:
                return self.default
            keys = lookup.record_keys(wc, self.paths[0])
            hint = f"; {self.paths[0].rsplit('.', 1)[0]} has: {', '.join(keys)}" if keys else ""
            raise RecipeError(f"{label} is not set in the config (for {wc}){hint}")
        if self.type_ is not None:
            ok, value = _CHECKS[self.type_](value)
            if not ok:
                raise RecipeError(f"{label} = {value!r} should be {self.type_.__name__} (for {wc})")
        return lookup.resolve_file(str(value)) if self.is_file else value


class ParamPath:
    """param_path(P_DET_ROOT, det_sim="delphesCutlang") -- fixed values may be param(...) too."""

    def __init__(self, lookup_factory, template, fixed):
        self._lookup_factory = lookup_factory
        self.template, self.fixed = template, dict(fixed)
        self.__name__ = "param_path(...)"

    def __call__(self, wildcards):
        wc = as_dict(wildcards)
        fixed = {k: (v(wildcards) if callable(v) else v) for k, v in self.fixed.items()}
        return self._lookup_factory().fill(wc, self.template, fixed)
