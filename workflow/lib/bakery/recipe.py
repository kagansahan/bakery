"""
The manifest recipe: ordered steps that turn a config into rows.

* :class:`ExpandRows`: one row per item; the item is kept as a record
* :class:`DeclareLookup`: find a record in a config list by a value
* :class:`DeclareColumn`: one value per row

A step reads a path from the row when its first name is a record or column of the row, otherwise
from the config: ``"samples[*]"`` is the config's list, ``"sample.points[*]"`` the row's sample.
"""

import abc

from .common import RecipeError, has_star, head, segments, walk
from .manifest import Row
from .tools import Tools


class _Context:
    def __init__(self, config, on_unknown):
        self.config = config
        self.on_unknown = on_unknown
        self.notes = []

    def read(self, path, row):
        """A path from the row if its first name is in the row, otherwise from the config."""
        if callable(path):
            return path(row)
        segs = segments(path)
        if row.has(segs[0][0]):
            return row.read(path)
        if segs[0][0] not in self.config:
            raise RecipeError(f"'{path}': '{segs[0][0]}' is neither bound by an earlier recipe step nor a "
                              f"config section")
        return walk(self.config, segs)


def _as_record(item):
    return {"name": item} if isinstance(item, str) else item


class Step(abc.ABC):
    def __init__(self, name):
        self.name = name

    @abc.abstractmethod
    def apply(self, row, ctx):
        ...

    def reads(self):
        """Paths this step reads (for the order check)."""
        return ()


class ExpandRows(Step):
    def __init__(self, record, over, where=None, missing=None):
        super().__init__(record)
        if isinstance(over, str) and not has_star(over):
            raise RecipeError(f"expand_rows('{record}', over='{over}'): the path needs a [*] to iterate over")
        self.over, self.where, self.missing = over, where, missing

    def reads(self):
        return (self.over,) if isinstance(self.over, str) else ()

    def _items(self, row, ctx):
        if isinstance(self.over, Tools):
            return self.over.items(ctx.config)
        value = ctx.read(self.over, row)
        return list(value or [])

    def apply(self, row, ctx):
        kept = []
        for item in self._items(row, ctx):
            new = row.with_record(self.name, _as_record(item))
            if self.where is None or self.where(new):
                kept.append(new)
        if kept or self.missing is None:
            return kept
        fallback = self.missing(row) if callable(self.missing) else self.missing
        return [] if fallback is None else [row.with_record(self.name, _as_record(fallback))]


class DeclareLookup(Step):
    def __init__(self, record, section, key, by):
        super().__init__(record)
        self.section, self.key, self.by = section, key, by

    def reads(self):
        return (self.section, self.by)

    def apply(self, row, ctx):
        value = ctx.read(self.by, row)
        entries = ctx.read(self.section, row) or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get(self.key) == value:
                return [row.with_record(self.name, entry)]
        if value in (None, "NONE"):
            return [row.with_record(self.name, {})]
        names = sorted(str(e.get(self.key)) for e in entries if isinstance(e, dict))
        raise RecipeError(f"{self.by}='{value}': there is no entry with {self.key}={value!r} in {self.section} "
                          f"(there: {', '.join(names) or 'none'})")


class DeclareColumn(Step):
    def __init__(self, name, from_, missing=None, known=None, unknown="NONE"):
        super().__init__(name)
        self.from_, self.missing, self.known, self.unknown = from_, missing, known, unknown

    def reads(self):
        return (self.from_,) if isinstance(self.from_, str) else ()

    def _known(self, ctx):
        if self.known is None:
            return None
        if isinstance(self.known, Tools):
            return self.known.names(ctx.config)
        return set(self.known)

    def apply(self, row, ctx):
        value = ctx.read(self.from_, row)
        if value is None and self.missing is not None:
            value = self.missing(row) if callable(self.missing) else self.missing
        known = self._known(ctx)
        if known is not None and value not in known and value not in (None, "NONE"):
            source = self.known if isinstance(self.known, Tools) else sorted(known)
            if ctx.on_unknown == "error":
                raise RecipeError(f"{self.name}='{value}' is not one of {source}")
            ctx.notes.append(f"{self.name}: '{value}' is not one of {source}; it becomes {self.unknown}")
            value = self.unknown
        return [row.with_column(self.name, value)]


class Recipe:
    def __init__(self):
        self.steps = []
        self.frozen = False

    def add(self, step):
        if self.frozen:
            raise RecipeError(f"the recipe is already used (validate_config); '{step.name}' comes too late")
        self.steps.append(step)

    def names(self):
        return {s.name for s in self.steps}

    def records(self):
        return {s.name for s in self.steps if isinstance(s, (ExpandRows, DeclareLookup))}

    def columns(self):
        return {s.name for s in self.steps if isinstance(s, DeclareColumn)}

    def config_sections(self):
        """Config sections the recipe reads directly, in the order the steps first read them."""
        out, bound = {}, set()
        for step in self.steps:
            for path in step.reads():
                if isinstance(path, str) and head(path) not in bound:
                    out[head(path)] = None
            if isinstance(step, ExpandRows) and isinstance(step.over, Tools):
                out[step.over.section] = None
            if isinstance(step, DeclareColumn) and isinstance(step.known, Tools):
                out[step.known.section] = None
            bound.add(step.name)
        return list(out)

    def tool_columns(self):
        """{config section: column} for columns that name a tool of a section (generator, det_sim, ...)."""
        out = {}
        tool_records = {s.name: s.over.section for s in self.steps
                        if isinstance(s, ExpandRows) and isinstance(s.over, Tools)}
        for s in self.steps:
            if not isinstance(s, DeclareColumn):
                continue
            if isinstance(s.from_, str) and len(segments(s.from_)) == 2:
                rec, field = segments(s.from_)[0][0], segments(s.from_)[1][0]
                if rec in tool_records and field == "name":
                    out.setdefault(tool_records[rec], s.name)
            if isinstance(s.known, Tools):
                out.setdefault(s.known.section, s.name)
        return out

    def check_path(self, path):
        name = head(path)
        if name not in self.names():
            raise RecipeError(f"'{path}': '{name}' is not a record or column of the recipe; a path starts "
                              f"with one of: {', '.join(sorted(self.names()))}")

    def build(self, config, on_unknown="none"):
        if on_unknown not in ("none", "error"):
            raise RecipeError("on_unknown must be 'none' or 'error'")
        ctx = _Context(config, on_unknown)
        rows = [Row()]
        for step in self.steps:
            rows = [r for row in rows for r in step.apply(row, ctx)]
        return rows, list(dict.fromkeys(ctx.notes))
