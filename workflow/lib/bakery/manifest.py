"""
Manifest rows, formats, wildcards and selection.

A :class:`Row` has

* columns, single values: ``row["sqrts"] == 13.0``
* records, dicts from the config: ``row.record("sim")``
* wildcard texts, after ``build_manifest``: ``row.wildcards["sqrts"] == "13p0"``
"""

import dataclasses
import fnmatch
import re
import types

from .common import ConfigError, RecipeError, did_you_mean, segments, walk_from


class Row:
    __slots__ = ("_columns", "_records", "_wildcards")

    def __init__(self, columns=None, records=None, wildcards=None):
        self._columns = dict(columns or {})
        self._records = dict(records or {})
        self._wildcards = dict(wildcards or {})

    # ---- building (rows never change; each step makes a new one) ---------------------------------
    def with_column(self, name, value):
        columns = dict(self._columns)
        columns[name] = value
        return Row(columns, self._records, self._wildcards)

    def with_record(self, name, record):
        records = dict(self._records)
        records[name] = record
        return Row(self._columns, records, self._wildcards)

    def with_wildcards(self, wildcards):
        return Row(self._columns, self._records, wildcards)

    # ---- reading ---------------------------------------------------------------------------------
    def __getitem__(self, name):
        if name not in self._columns:
            raise KeyError(f"the row has no column '{name}' (columns: {', '.join(self._columns)})")
        return self._columns[name]

    def get(self, name, default=None):
        return self._columns.get(name, default)

    def record(self, name):
        """The record bound under `name`; {} when there is none."""
        return self._records.get(name) or {}

    def has(self, name):
        return name in self._columns or name in self._records

    def read(self, path):
        """'sqrts' -> the column; 'sample.nevents' -> a field of the sample record.

        A plain name is a column first, then a record; a dotted path starts at a record first.
        """
        segs = segments(path)
        name, star = segs[0]
        if len(segs) == 1 and not star:
            if name in self._columns:
                return self._columns[name]
            return self._records.get(name)
        start = self._records[name] if name in self._records else self._columns.get(name)
        return walk_from(start, segs)

    @property
    def columns(self):
        return types.MappingProxyType(self._columns)

    @property
    def records(self):
        return types.MappingProxyType(self._records)

    @property
    def wildcards(self):
        return types.MappingProxyType(self._wildcards)

    def __repr__(self):
        return f"Row({self._wildcards or self._columns})"


class Manifest:
    """The rows of a config; a selection is a Manifest whose `source` is the full one."""

    def __init__(self, rows, wildcard_names=(), source=None, selection=None):
        self._rows = tuple(rows)
        self.wildcard_names = tuple(wildcard_names)
        self.source = source
        self.selection = dict(selection or {})
        self._index = {}

    @property
    def full(self):
        return self.source.full if self.source is not None else self

    def rows(self, where=None):
        return tuple(r for r in self._rows if where is None or where(r))

    def __len__(self):
        return len(self._rows)

    def __iter__(self):
        return iter(self._rows)

    @property
    def columns(self):
        names = {}
        for r in self._rows:
            names.update(dict.fromkeys(r.columns))
        return tuple(names)

    def values(self, wildcard):
        return tuple(dict.fromkeys(r.wildcards.get(wildcard) for r in self._rows))

    def matching(self, wildcards, where=None):
        """Rows whose wildcard texts equal the given ones."""
        key = tuple(sorted((k, str(v)) for k, v in wildcards.items()))
        if key not in self._index:
            self._index[key] = tuple(r for r in self._rows
                                     if all(str(r.wildcards.get(k)) == str(v) for k, v in wildcards.items()))
        rows = self._index[key]
        return rows if where is None else tuple(r for r in rows if where(r))

    @staticmethod
    def one(values, what, wildcards):
        distinct = {}
        for v in values:
            distinct.setdefault(repr(v), v)
        if len(distinct) > 1:
            raise RecipeError(f"{what} is ambiguous for {dict(wildcards)}: {len(distinct)} different values "
                              f"({', '.join(sorted(distinct)[:3])}). Fix the missing wildcard "
                              f"(param_path(..., det_sim='...')) or add it to the rule's output.")
        if not distinct:
            raise RecipeError(f"no manifest row matches {dict(wildcards)} for {what}")
        return next(iter(distinct.values()))


@dataclasses.dataclass(frozen=True)
class Format:
    name: str
    function: object
    pattern: str
    description: str

    def apply(self, value):
        return str(self.function(value))


class Formats:
    def __init__(self):
        self._formats = {}

    def add(self, name, function, pattern, description=""):
        if name in self._formats:
            raise ConfigError(f"format '{name}' is added twice")
        if not callable(function):
            raise ConfigError(f"format '{name}': the second argument is the function value -> text")
        re.compile(pattern)
        self._formats[name] = Format(name, function, pattern, description)

    def get(self, name):
        if name not in self._formats:
            raise ConfigError(f"no format '{name}' (declare_format); added: {', '.join(self._formats) or 'none'}")
        return self._formats[name]

    def all(self):
        return tuple(self._formats.values())


DEFAULT_PATTERN = r"[^/.]+"     # no '/' (folders) and no '.' (the separator in file names)


@dataclasses.dataclass(frozen=True)
class Wildcard:
    name: str
    column: str
    format: object          # Format or None
    pattern: str
    description: str

    def text(self, value):
        return self.format.apply(value) if self.format is not None else str(value)


class Wildcards:
    def __init__(self):
        self._wildcards = {}
        self.selectors = ()

    def declare(self, name, column, format, pattern, description):
        if name in self._wildcards:
            raise ConfigError(f"wildcard '{name}' is declared twice")
        pattern = pattern or (format.pattern if format is not None else DEFAULT_PATTERN)
        re.compile(pattern)
        self._wildcards[name] = Wildcard(name, column or name, format, pattern, description)

    def declare_selectors(self, names):
        unknown = [n for n in names if n not in self._wildcards]
        if unknown:
            raise ConfigError("declare_selector: " + ", ".join(
                f"'{n}' is not a declared wildcard{did_you_mean(n, self._wildcards)}" for n in unknown))
        self.selectors = tuple(dict.fromkeys(tuple(self.selectors) + tuple(names)))

    def names(self):
        return tuple(self._wildcards)

    def get(self, name):
        return self._wildcards[name]

    def all(self):
        return tuple(self._wildcards.values())

    def constraints(self):
        return {w.name: w.pattern for w in self._wildcards.values()}

    def check_columns(self, columns):
        problems = [f"wildcard '{w.name}' reads the column '{w.column}', which no declare_column makes"
                    f"{did_you_mean(w.column, columns)}" for w in self._wildcards.values() if w.column not in columns]
        if problems:
            raise RecipeError("\n".join(problems))

    def apply(self, row):
        """The row with its wildcard texts; each text must fit its pattern."""
        texts = {}
        for w in self._wildcards.values():
            value = row.get(w.column)
            text = "NONE" if value in (None, "NONE") else w.text(value)
            if text != "NONE" and not re.fullmatch(w.pattern, text):
                raise RecipeError(f"{w.name}='{text}' (from {w.column}={value!r}) does not fit the pattern "
                                  f"{w.pattern!r} and would break file names. Rename it in the config, or give "
                                  f"the wildcard a format/pattern.")
            texts[w.name] = text
        return row.with_wildcards(texts)


def patterns_from(values, selectors):
    """{selector: (pattern, ...)} from a dict; several patterns separated by '|' or ','."""
    out = {}
    for key in selectors:
        raw = values.get(key)
        if raw in (None, "", [], ()):
            continue
        parts = raw if isinstance(raw, (list, tuple)) else str(raw).replace(",", "|").split("|")
        parts = tuple(str(p).strip() for p in parts if str(p).strip())
        if parts:
            out[key] = parts
    return out


def _fits(text, patterns):
    return any(fnmatch.fnmatchcase(str(text).lower(), p.lower()) for p in patterns)


def select(manifest, selectors, include, exclude=None, on_empty="error"):
    """include/exclude: {wildcard: patterns}. Unknown names or values that match nothing are errors."""
    exclude = exclude or {}
    for kind, given in (("selector", include), ("exclude", exclude)):
        for key, patterns in given.items():
            if key not in selectors:
                raise ConfigError(f"{kind} '{key}' is not a declared selector ({', '.join(selectors)})")
            universe = sorted({str(v) for v in manifest.values(key)})
            for p in patterns:
                if not any(fnmatch.fnmatchcase(u.lower(), p.lower()) for u in universe):
                    raise ConfigError(f"{key}={p} matches nothing in the manifest. Available: "
                                      f"{', '.join(universe) or '(none)'}")
    rows = [r for r in manifest
            if all(_fits(r.wildcards[k], ps) for k, ps in include.items())
            and not any(_fits(r.wildcards[k], ps) for k, ps in exclude.items())]
    description = {k: "|".join(v) for k, v in include.items()}
    description.update({f"not {k}": "|".join(v) for k, v in exclude.items()})
    if not rows and on_empty == "error":
        raise ConfigError(f"the selection {description} keeps no manifest row")
    return Manifest(rows, manifest.wildcard_names, source=manifest, selection=description)
