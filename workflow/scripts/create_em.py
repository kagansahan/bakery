"""
Merge the per-point .embake (JSON) files into one .embaked file in the
em-creator format, which SModelS tooling reads with eval():

  # EM-Baked <date>. <n> points, <m> signal regions, <tool>
  {(610, 120):{'SR1': 0.01, ..., '__t__':'2026-..', '__nevents__':5000},
   ...
  }
"""
import json
import sys
import time


def mass_key(masses):
    return tuple(int(m) if float(m).is_integer() else float(m) for m in masses)


def merge(files):
    points, tool, nsr = {}, None, set()
    for fname in files:
        with open(fname) as f:
            d = json.load(f)
        tool = tool or d.get("tool")
        entry = dict(d["efficiencies"])
        nsr.update(entry)
        entry["__t__"] = time.strftime("%Y-%m-%d_%H:%M:%S")
        entry["__nevents__"] = d.get("nevents")
        key = mass_key(d["masses"])
        if key in points:
            raise RuntimeError(f"mass point {key} appears twice ({fname})")
        points[key] = entry
    return points, tool, len(nsr)


def write(points, tool, nsr, out):
    with open(out, "w") as f:
        f.write(f"# EM-Baked {time.asctime()}. {len(points)} points, "
                f"{nsr} signal regions, {tool}\n")
        f.write("{")
        for k in sorted(points):
            f.write(f"{k!r}:{points[k]!r},\n")
        f.write("}\n")


if "snakemake" in globals():
    sm = snakemake  # noqa: F821
    with open(sm.log[0], "w") as log:
        sys.stderr = log
        points, tool, nsr = merge(list(sm.input))
        write(points, tool, nsr, sm.output[0])
        print(f"wrote {len(points)} points to {sm.output[0]}", file=log)
