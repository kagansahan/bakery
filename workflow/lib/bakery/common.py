"""
Shared pieces: errors, the path language, value conversions.

Path language
-------------
A path is names separated by ``.``; ``[*]`` maps the rest of the path over a list:
``"samples[*].process"``, ``"sim.detectors"``, ``"process.extrajet"``.
"""

import datetime
import difflib
import re


class BakeryError(Exception):
    """Base class of every bakery error."""


class ConfigError(BakeryError, ValueError):
    """The config (or the Snakefile's description of it) cannot be planned."""


class RecipeError(ConfigError):
    """The recipe and the config do not fit together, or a rule asked for a value it cannot get."""


class OrderError(BakeryError):
    """A WorkflowUtil step was called before the step it needs, or after it was too late."""


_SEGMENT = re.compile(r"^(?P<name>[A-Za-z_][\w-]*)(?P<star>\[\*\])?$")


def segments(path):
    """'samples[*].process' -> [('samples', True), ('process', False)]"""
    out = []
    for text in [s for s in str(path).split(".") if s]:
        match = _SEGMENT.match(text)
        if not match:
            raise RecipeError(f"bad path segment '{text}' in '{path}' (a name, optionally followed by [*])")
        out.append((match.group("name"), bool(match.group("star"))))
    if not out:
        raise RecipeError("empty path")
    return out


def head(path):
    return segments(path)[0][0]


def has_star(path):
    return any(star for _, star in segments(path))


def walk(obj, segs):
    """Follow `segs` from `obj`. A [*] segment maps the rest of the path over the list."""
    for i, (name, star) in enumerate(segs):
        obj = obj.get(name) if isinstance(obj, dict) else None
        if star:
            rest = segs[i + 1:]
            out = []
            for item in obj or []:
                value = walk(item, rest)
                out += value if any(s for _, s in rest) else [value]
            return out
    return obj


def walk_from(start, segs):
    """Like walk, but `start` is the value of the first segment already."""
    (name, star), rest = segs[0], segs[1:]
    if star:
        out = []
        for item in start or []:
            value = walk(item, rest) if rest else item
            out += value if any(s for _, s in rest) else [value]
        return out
    return walk(start, rest) if rest else start


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")


def parse_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{value!r} is not true/false")


def convert(value, type_):
    """Convert a config value to `type_` (bool, int, float, str)."""
    if type_ is bool:
        return parse_bool(value)
    if type_ is int:
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not an integer")
        return int(value)
    if type_ is float:
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not a number")
        return float(value)
    if type_ is str:
        return str(value)
    raise ValueError(f"unsupported type {type_!r}")


def plain_dates(obj):
    """YAML reads an unquoted 2026-10-12 as a date; bakery keeps such values as text."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: plain_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [plain_dates(v) for v in obj]
    return obj


def did_you_mean(word, choices):
    near = difflib.get_close_matches(str(word).replace("-", "_").lower(), sorted(choices), 1, 0.6)
    return f" -> did you mean '{near[0]}'?" if near else ""
