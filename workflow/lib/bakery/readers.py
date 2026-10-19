"""
Snakemake -> bakery: rules as :class:`bakery.planner.RuleSpec`, jobs as :class:`bakery.readers.JobSpec`.
"""

import dataclasses
import os

from .planner import RuleSpec
from .project import strip_constraints, wildcard_names


@dataclasses.dataclass
class JobSpec:
    """One job Snakemake will run: what ``confirmation_screen`` shows."""
    rule: str
    outputs: list
    existing: list
    reason: str


def _flatten(value):
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        return [str(value)]
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flatten(v)]
    if isinstance(value, (list, tuple, set)):
        return [x for v in value for x in _flatten(v)]
    return [str(value)]


def read_rules(workflow, global_constraints, skip=("all",), skip_prefix="run_"):
    from snakemake.iocontainers import Wildcards

    specs = []
    for rule in workflow.rules:
        if rule.name in skip or rule.name.startswith(skip_prefix):
            continue
        outputs = tuple(strip_constraints(str(o)) for o in rule.output)
        names = frozenset(w for o in outputs for w in wildcard_names(o))
        own = dict(rule.wildcard_constraints)
        constraints = {w: p for w, p in {**dict(global_constraints), **own}.items() if w in names}
        items = list(rule.input)

        def inputs_fn(values, items=items, names=names):
            wildcards = Wildcards(fromdict={n: values[n] for n in names})
            out = []
            for item in items:
                if callable(item):
                    out += _flatten(item(wildcards))
                else:
                    out.append(strip_constraints(str(item)).format(**values))
            return out

        specs.append(RuleSpec(rule.name, outputs, names, constraints, own, inputs_fn))
    return specs


def needrun_jobs(workflow, skip=("all",), skip_prefix="run_"):
    dag = workflow.dag
    out = []
    for job in dag.needrun_jobs():
        if job.rule.name in skip or job.rule.name.startswith(skip_prefix):
            continue
        outputs = [str(o) for o in job.output]
        existing = [o for o in outputs if os.path.exists(o)]
        out.append(JobSpec(job.rule.name, outputs, existing, str(dag.reason(job))))
    return out


def invocation(workflow):
    """{label: value} of the command line options that change what runs."""
    settings = getattr(workflow, "dag_settings", None)

    def opt(name, default=None):
        return getattr(settings, name, default) if settings is not None else default

    out = {"targets": sorted(str(t) for t in (opt("targets") or ()))}
    out["cores"] = getattr(getattr(workflow, "resource_settings", None), "cores", "?")
    out["forceall"] = bool(opt("forceall", False))
    for flag in ("forcerun", "until", "omit_from", "allowed_rules"):
        value = opt(flag)
        if value:
            out[flag] = sorted(str(getattr(x, "name", x)) for x in value)
    out["rerun_triggers"] = sorted(getattr(t, "name", str(t)).lower() for t in (opt("rerun_triggers") or ()))
    return out
