"""Unit tests for the efficiency extraction scripts (no HEP software needed).

    python -m pytest tests/
"""
import gzip
import importlib.util
import os

import numpy as np
import pytest
import uproot

HERE = os.path.dirname(__file__)
SCRIPTS = os.path.join(HERE, "..", "workflow", "scripts")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rivet = load("rivet_to_embake")
cutlang = load("cutlang_to_embake")
create_em = load("create_em")


def yoda_counter(path, sumw, sumw2, n, version=3):
    if version == 2:  # YODA 1.x / Rivet 3
        return (f"BEGIN YODA_COUNTER_V2 {path}\nPath: {path}\nTitle: \nType: Counter\n---\n"
                f"# sumW\t sumW2\t numEntries\n{sumw}\t{sumw2}\t{n}\nEND YODA_COUNTER_V2\n")
    return (f"BEGIN YODA_COUNTER_V3 {path}\nPath: {path}\nTitle: \nType: Counter\n---\n"
            f"# sumW\t sumW2\t numEntries\n{sumw}\t{sumw2}\t{n}\nEND YODA_COUNTER_V3\n")


@pytest.mark.parametrize("version", [2, 3])
def test_rivet_raw_over_evtcount(tmp_path, version):
    f = tmp_path / "out.yoda.gz"
    txt = "".join([
        yoda_counter("/_EVTCOUNT", 1000, 1000, 1000, version),
        yoda_counter("/_EVTCOUNT[MUR=2]", 2000, 4000, 1000, version),
        yoda_counter("/RAW/ANA/SR1", 100, 100, 100, version),
        yoda_counter("/RAW/ANA/SR1[MUR=2]", 999, 999, 100, version),  # must be skipped
        yoda_counter("/ANA/SR1", 0.42, 0, 100, version),               # finalised: ignored
        yoda_counter("/RAW/OTHER/SR9", 500, 500, 500, version),        # other routine
    ])
    with gzip.open(f, "wt") as g:
        g.write(txt)
    res = rivet.extract(str(f), "ANA", {"SR1": "SR1_hepdata"})
    assert res["efficiencies"] == {"SR1_hepdata": pytest.approx(0.1)}
    assert res["nevents"] == 1000


def test_rivet_missing_routine(tmp_path):
    f = tmp_path / "out.yoda"
    f.write_text(yoda_counter("/_EVTCOUNT", 10, 10, 10) + yoda_counter("/RAW/X/a", 1, 1, 1))
    with pytest.raises(RuntimeError, match="no nominal Counter"):
        rivet.extract(str(f), "ANA")


def write_cutlang(path, regions):
    with uproot.recreate(path) as f:
        for name, hists in regions.items():
            for hname, vals in hists.items():
                edges = np.arange(len(vals) + 1) + 0.5
                f[f"{name}/{hname}"] = (np.asarray(vals, dtype=float), edges)


def write_delphes(path, n):
    with uproot.recreate(path) as f:
        f["Delphes"] = {"Event.Weight": np.ones(n)}


def test_cutlang_dependent_region_uses_total_events(tmp_path):
    # 1000 generated events, 200 pass presel. 'searchbins' depends on presel,
    # so CutLang's cutflow bin 1 there is 200, not 1000.
    write_delphes(tmp_path / "d.root", 1000)
    write_cutlang(tmp_path / "h.root", {
        "presel": {"cutflow": [1000, 600, 200]},
        "searchbins": {"cutflow": [200, 200], "bincounts": [50, 30, 0]},
    })
    res = cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"), ["presel"])
    e = res["efficiencies"]
    assert "presel" not in e
    assert e["searchbins_bin1"] == pytest.approx(0.05)   # 50/1000, not 50/200
    assert e["searchbins_bin2"] == pytest.approx(0.03)
    assert e["searchbins"] == pytest.approx(0.2)


def test_create_em_roundtrip(tmp_path):
    import json
    files = []
    for m, eff in (([610.0, 120.0], 0.1), ([650.5, 220.0], 0.2)):
        p = tmp_path / f"{m[0]}.embake"
        p.write_text(json.dumps({"masses": m, "efficiencies": {"SR1": eff},
                                 "nevents": 10, "tool": "rivet"}))
        files.append(str(p))
    points, tool, nsr = create_em.merge(files)
    out = tmp_path / "x.embaked"
    create_em.write(points, tool, nsr, str(out))
    d = eval(out.read_text())  # this is how em-creator / SModelS tools read it
    assert d[(610, 120)]["SR1"] == 0.1
    assert d[(650.5, 220)]["__nevents__"] == 10
