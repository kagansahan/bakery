"""
Texts bakery prints, and ``config.used.yaml``.

* :func:`report`, :func:`manifest_table`, :func:`target_files_table`, :func:`help_text`
* :func:`confirmation_screen`, :func:`nothing_to_run`: what ``ask_confirmation`` shows
* :func:`write_provenance`, :func:`read_provenance`, :func:`config_differences`: which config made
  an output folder
"""

import hashlib
import json
import os

import yaml


def report(views, settings, selection, n_rows, n_all, output, notes, warnings, short_path):
    s = settings
    lines = [f"bakery: {n_rows} manifest rows" + (f" (of {n_all})" if n_rows != n_all else "")
             + f"   output: {output}   fake={_bool_text(s['fake'])}   overwrite={_bool_text(s['overwrite'])}   "
             f"upstream={_bool_text(s['upstream'])}   downstream={_bool_text(s['downstream'])}"]
    if selection:
        lines.append("  selection: " + ", ".join(f"{k}={v}" for k, v in selection.items()))
    lines.append(f"  {'rule':<20}{'files':>7}{'to run':>8}{'on disk':>9}{'waiting':>9}{'blocked':>9}")
    for v in views.values():
        lines.append(f"  {v.name:<20}{len(v.chain):>7}{len(v.to_run):>8}{len(v.on_disk):>9}{len(v.waiting):>9}"
                     f"{len(v.blocked):>9}")
    lines += why_not(views.values(), short_path, settings, views.values())
    for n in notes:
        lines.append(f"  note: {n}")
    for w in dict.fromkeys(warnings):
        lines.append(f"  WARNING: {w}")
    return "\n".join(lines)


def why_not(views, short_path, settings, all_views, include_blocked=True):
    """Lines that explain waiting / on-disk / blocked files, with what one can run instead."""
    lines = []
    all_views = list(all_views)
    for v in views:
        if v.waiting:
            missing = sorted({m for ms in v.waiting.values() for m in ms})
            producers = sorted({p for p in (_owner_of(all_views, m) for m in missing) if p})
            lines.append(f"  {v.name}: {len(v.waiting)} waiting for input, e.g. {short_path(missing[0])} is missing")
            lines.append("      you can run: " + (", ".join(f"run_{p}" for p in producers) or "(nothing makes it)")
                         + f"   or run_{v.name} with --config upstream=true")
        if v.on_disk and not settings["overwrite"]:
            lines.append(f"  {v.name}: {len(v.on_disk)} on disk, not touched (--config overwrite=true rebuilds "
                         f"the outdated ones)")
        if include_blocked and v.blocked:
            lines.append(f"  {v.name}: {len(v.blocked)} cannot be planned: {next(iter(v.blocked.values()))}")
    return lines


def _owner_of(views, path):
    for v in views:
        for files in v.outputs.values():
            if path in files:
                return v.name
    return None


def _bool_text(value):
    return str(bool(value)).lower()


def manifest_table(manifest, columns=None, sort_by=None, limit=20):
    columns = list(columns or manifest.wildcard_names)
    rows = list(manifest)
    if sort_by:
        keys = [sort_by] if isinstance(sort_by, str) else list(sort_by)
        rows.sort(key=lambda r: tuple(str(_cell(r, k)) for k in keys))
    head = f"manifest: {len(manifest)} rows"
    if manifest.source is not None and len(manifest.full) != len(manifest):
        sel = ", ".join(f"{k}={v}" for k, v in manifest.selection.items()) or "selection"
        head += f" ({len(manifest.full)} before {sel})"
    shown = rows if not limit or limit <= 0 else rows[:limit]
    cells = [[str(_cell(r, c)) for c in columns] for r in shown]
    widths = [max([len(c)] + [len(row[i]) for row in cells]) for i, c in enumerate(columns)]
    lines = [head, "  " + "  ".join(c.ljust(w) for c, w in zip(columns, widths))]
    lines += ["  " + "  ".join(x.ljust(w) for x, w in zip(row, widths)) for row in cells]
    if len(shown) < len(rows):
        lines.append(f"  ... and {len(rows) - len(shown)} more (limit=0 shows all)")
    return "\n".join(lines)


def _cell(row, name):
    if name in row.wildcards:
        return row.wildcards[name]
    return row.get(name, "")


def target_files_table(by_rule, state, short_path, limit=10):
    total = sum(len(f) for f in by_rule.values())
    lines = [f"target files ({state}): {total}"]
    for name, files in by_rule.items():
        if not files:
            continue
        lines.append(f"  {name}: {len(files)}")
        shown = files if not limit or limit <= 0 else files[:limit]
        lines += [f"      {short_path(f)}" for f in shown]
        if len(shown) < len(files):
            lines.append(f"      ... and {len(files) - len(shown)} more")
    return "\n".join(lines)


def help_text(schema, framework_keys, wildcards, manifest, layout, formats):
    out = ["BAKERY OPTIONS (--config KEY=VALUE):"]
    for o in schema.options.values():
        out.append(f"  {o.name + '=' + o.type_.__name__.upper():<26} {o.description} (default: {o.default})")
    for k, d in framework_keys.items():
        out.append(f"  {k:<26} {d}")
    out.append("\nSELECTORS (--config WILDCARD=VALUE, '|' for several, * and ? as wildcards):")
    for name in wildcards.selectors:
        values = ", ".join(str(v) for v in manifest.values(name)[:8]) if manifest is not None else ""
        out.append(f"  {name:<14} {wildcards.get(name).description:<44} {values}")
    out.append("\nCONFIG SECTIONS (--configfile):")
    for name, d in schema.sections.items():
        out.append(f"  {name:<22} {d}")
    if schema.schema_file:
        out.append(f"  (structure: {layout.relative(schema.schema_file)})")
    out.append("\nFOLDERS:")
    for f in layout.folders.values():
        out.append(f"  {f.name:<10} {layout.relative(f.path) if f.path else f.template:<28} {f.description}")
    if formats:
        out.append("\nFORMATS:")
        for f in formats:
            out.append(f"  {f.name:<10} {f.description}")
    if manifest is not None:
        out.append("\nJOB VALUES (param(\"...\"), examples from this config):")
        examples = {}

        def visit(prefix, value, depth):
            if isinstance(value, dict) and depth < 3:
                for k, v in value.items():
                    visit(f"{prefix}.{k}", v, depth + 1)
            elif prefix not in examples and value not in (None, {}, []):
                examples[prefix] = value

        for row in manifest.full:
            for name, value in row.columns.items():
                examples.setdefault(name, value)
            for name, value in row.records.items():
                visit(name, value, 1)
        for path in sorted(examples):
            text = repr(examples[path])
            out.append(f"  {path:<36} {text if len(text) < 44 else text[:41] + '...'}")
    return "\n".join(out)


# Snakemake's own "needrun" reason text; if a Snakemake version words it differently, update it here.
PARAMS_PREFIX = ("Params have changed since last execution: Union of exclusive params before and now "
                 "across all output: ")


def confirmation_screen(jobs, settings_lines, invocation_lines, warnings, list_limit, short_path):
    files_new, files_old = [], []
    counts = {}
    for job in jobs:
        counts[job.rule] = counts.get(job.rule, 0) + 1
        for o in job.outputs:
            if o in job.existing:
                files_old.append((o, job.reason.replace(PARAMS_PREFIX, "params changed, ")))
            else:
                files_new.append((o, None))
    out = ["", "=" * 78, "  SETTINGS", "=" * 78]
    out += settings_lines
    out += ["-" * 78] + invocation_lines
    out += ["=" * 78, f"  PLAN    {len(jobs)} jobs, {len(files_new) + len(files_old)} files", "=" * 78]
    out += [f"  {name:<16} {n}" for name, n in counts.items()]

    def dump(heading, files):
        if not files:
            return
        files = sorted(files)
        out.append(f"\n  {heading}  ({len(files)}):")
        shown = files if list_limit <= 0 else files[:list_limit]
        for f, reason in shown:
            out.append(f"     {short_path(f)}")
            if reason:
                out.append(f"         reason: {reason[:150]}")
        if len(shown) < len(files):
            out.append(f"     ... and {len(files) - len(shown)} more (--config list_limit=0 lists all)")

    dump("WILL BE OVERWRITTEN (already exists)", files_old)
    dump("WILL BE CREATED", files_new)
    if warnings:
        out.append("")
    for w in warnings:
        out.append(f"  WARNING: {w}")
    out.append("=" * 78)
    return "\n".join(out)


def nothing_to_run(views, asked, settings, short_path):
    out = ["", "=" * 78, "  bakery: nothing to run for " + ", ".join(f"run_{a}" for a in asked), "=" * 78]
    lines = why_not([views[a] for a in asked], short_path, settings, views.values())
    for a in asked:
        v = views[a]
        if not (v.waiting or v.on_disk or v.blocked):
            lines.append(f"  {a}: no files for this config and selection")
        elif v.on_disk and settings["overwrite"] and not v.waiting and not v.blocked:
            lines.append(f"  {a}: {len(v.on_disk)} on disk and up to date")
    return "\n".join(out + lines + ["=" * 78])


PROVENANCE_FILE = "config.used.yaml"


def config_sections(config, sections):
    return {k: config[k] for k in sections if k in config}


def config_digest(sections):
    return hashlib.sha256(json.dumps(sections, sort_keys=True, default=str).encode()).hexdigest()


def read_provenance(folder):
    path = os.path.join(folder, PROVENANCE_FILE)
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def config_differences(old, new, limit=5):
    """'samples[0].nevents: 1000 -> 5000' lines between two config dicts."""
    out = []

    def visit(where, a, b):
        if len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in list(dict.fromkeys(list(a) + list(b))):
                visit(f"{where}.{k}" if where else str(k), a.get(k), b.get(k))
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                visit(f"{where}[{i}]", x, y)
        elif a != b:
            out.append(f"{where}: {_short(a)} -> {_short(b)}")

    visit("", old, new)
    return out


def _short(value):
    text = repr(value)
    return text if len(text) < 50 else text[:47] + "..."


def write_provenance(folder, sections, run_info):
    os.makedirs(folder, exist_ok=True)
    data = {"bakery_run": dict(run_info, config_sha256=config_digest(sections))}
    data.update(sections)
    with open(os.path.join(folder, PROVENANCE_FILE), "w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
