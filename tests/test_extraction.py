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


def write_delphes(path, n, weights=None):
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    with uproot.recreate(path) as f:
        f["Delphes"] = {"Event.Weight": w}


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
    assert "searchbins" not in e          # binned region: only its bins are SRs


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


def test_cutlang_delphes2_uses_sum_of_weights(tmp_path):
    # DELPHES2: CutLang fills the cutflow with Event.Weight, here a constant 0.5
    # (MG5 often writes weight = cross section / N). 1000 events -> sumW = 500.
    write_delphes(tmp_path / "d.root", 1000, np.full(1000, 0.5))
    write_cutlang(tmp_path / "h.root", {"SR": {"cutflow": [1000, 60.0, 25.0]}})
    res = cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"),
                          input_format="DELPHES2")
    assert res["efficiencies"]["SR"] == pytest.approx(25.0 / 500.0)   # 50 of 1000 events


def test_cutlang_nonuniform_weights_need_delphes2(tmp_path):
    w = np.ones(100)
    w[:10] = 3.0                                   # a biased sample
    write_delphes(tmp_path / "d.root", 100, w)
    write_cutlang(tmp_path / "h.root", {"SR": {"cutflow": [100, 10]}})
    with pytest.raises(RuntimeError, match="DELPHES2"):
        cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"))
    res = cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"),
                          input_format="DELPHES2")
    assert res["efficiencies"]["SR"] == pytest.approx(10 / 120.0)


def test_cutlang_bin_name_template(tmp_path):
    write_delphes(tmp_path / "d.root", 1000)
    write_cutlang(tmp_path / "h.root", {
        "presel": {"cutflow": [1000, 200]},
        "searchbins": {"cutflow": [200, 200], "bincounts": [50, 30]},
    })
    res = cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"),
                          ["presel"], bin_names="SR{i}")
    e = res["efficiencies"]
    assert e["SR1"] == pytest.approx(0.05) and e["SR2"] == pytest.approx(0.03)
    assert "searchbins_bin1" not in e


def test_cutlang_bin_name_template_clash(tmp_path):
    write_delphes(tmp_path / "d.root", 100)
    write_cutlang(tmp_path / "h.root", {
        "A": {"cutflow": [100, 10], "bincounts": [5]},
        "B": {"cutflow": [100, 10], "bincounts": [4]},
    })
    with pytest.raises(RuntimeError, match="region"):
        cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"), bin_names="SR{i}")
    res = cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"),
                          bin_names="{region}_SR{i}")
    assert set(res["efficiencies"]) >= {"A_SR1", "B_SR1"}


def test_cutlang_tiny_nonuniform_weights_detected(tmp_path):
    # weights in pb for a small cross section: all far below np.allclose's atol
    w = np.geomspace(1e-12, 5e-9, 100)
    write_delphes(tmp_path / "d.root", 100, w)
    write_cutlang(tmp_path / "h.root", {"SR": {"cutflow": [100, 10]}})
    with pytest.raises(RuntimeError, match="DELPHES2"):
        cutlang.extract(str(tmp_path / "h.root"), str(tmp_path / "d.root"))


MG5 = os.path.join(HERE, "..", "workflow", "wrappers", "mg5amcnlo")


def load_mg5():
    spec = importlib.util.spec_from_file_location("mg5w", os.path.join(MG5, "wrapper.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def proc_lines(card):
    return [l for l in card.splitlines() if l.startswith(("generate", "add process"))]


def test_proc_card_jets_before_exclusions(tmp_path):
    mg5 = load_mg5()
    card = tmp_path / "proc_card.dat"
    card.write_text("import model MSSM_SLHA2\n"
                    "generate p p > n2 x1- $ n2 x1- @1 # comment\n"
                    "add process p p > n2 x1+ / ul dl, n2 > n1 z\n")
    lines = proc_lines(mg5.generate_proc_card(str(card), 2, "OUT"))
    assert "add process p p > n2 x1- j j $ n2 x1-" in lines
    assert "add process p p > n2 x1+ j / ul dl, n2 > n1 z" in lines
    assert len(lines) == 6


def test_proc_card_with_own_jets_refuses_extrajet(tmp_path):
    mg5 = load_mg5()
    card = tmp_path / "proc_card.dat"
    card.write_text("import model MSSM_SLHA2\ngenerate p p > t1 t1~ @1\n"
                    "add process p p > t1 t1~ j @2\n")
    assert mg5.generate_proc_card(str(card), 0, "OUT")
    with pytest.raises(ValueError, match="extrajet: 0"):
        mg5.generate_proc_card(str(card), 1, "OUT")


def test_pythia_njetmax():
    mg5 = load_mg5()
    txt = "JetMatching:qCut = -1.0\nJetMatching:nJetMax      = 1\n"
    assert "JetMatching:nJetMax      = 2" in mg5.set_pythia_njetmax(txt, 2)


P8 = os.path.join(HERE, "..", "workflow", "wrappers", "pythia8")
MG5_DATA = os.path.join(MG5, "data")


def load_p8():
    spec = importlib.util.spec_from_file_location("p8w", os.path.join(P8, "wrapper.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def p8_flags(settings):
    return sorted(s.split()[0] for s in settings if s.startswith("SUSY:") and s.endswith("= on"))


def test_pythia8_pairs_T2_squark_antisquark_only():
    p8 = load_p8()
    pairs = p8.sparticle_pairs(os.path.join(MG5_DATA, "T2", "proc_card.dat"))
    assert pairs == {(-1000001, 1000001), (-1000002, 1000002), (-2000001, 2000001), (-2000002, 2000002)}
    settings, extra = p8.pythia_settings(pairs, "x.slha", 13.0, 10, 1)
    assert p8_flags(settings) == ["SUSY:gg2squarkantisquark", "SUSY:qqbar2squarkantisquark"]
    assert "SUSY:qq2squarksquark" not in " ".join(settings)


def test_pythia8_TGQ_has_no_gluino_pairs():
    p8 = load_p8()
    pairs = p8.sparticle_pairs(os.path.join(MG5_DATA, "TGQ", "proc_card.dat"))
    settings, extra = p8.pythia_settings(pairs, "x.slha", 13.0, 10, 1)
    assert p8_flags(settings) == ["SUSY:qg2squarkgluino"]
    assert (1000021, 1000021) not in extra


def test_pythia8_skips_explicit_jet_lines_and_reads_charge():
    p8 = load_p8()
    pairs = p8.sparticle_pairs(os.path.join(MG5_DATA, "TChiWZ_ZToLL", "proc_card.dat"))
    assert pairs == {(-1000024, 1000023), (1000023, 1000024)}
    settings, _ = p8.pythia_settings(pairs, "x.slha", 13.0, 10, 1)
    assert p8_flags(settings) == ["SUSY:qqbar2chi+-chi0"]


def test_pythia8_refuses_non_mssm():
    p8 = load_p8()
    with pytest.raises(ValueError, match="MSSM"):
        p8.sparticle_pairs(os.path.join(MG5_DATA, "TRV1", "proc_card.dat"))


def test_pythia8_drops_stable_coloured_decay_blocks():
    p8 = load_p8()
    d = os.path.join(MG5_DATA, "T2")
    pairs = p8.sparticle_pairs(os.path.join(d, "proc_card.dat"))
    text = p8.fill_slha(os.path.join(d, "spectrum.slha"), [610.0, 120.0])
    new, dropped = p8.drop_stable_coloured(text, {x for pr in pairs for x in pr})
    assert dropped == [2000001, 2000002]            # ~d_R, ~u_R: 'DECAY ... 0.0', no channels
    decays = [l.split()[1] for l in new.splitlines() if l.upper().startswith("DECAY")]
    assert "2000001" not in decays and "2000002" not in decays
    assert "1000001" in decays and "1000022" in decays   # others untouched (LSP stays stable)


def test_mg5_auto_widths_for_stable_light_squarks():
    mg5 = load_mg5()
    text = mg5.fill_slha_template(os.path.join(MG5_DATA, "T2", "spectrum.slha"), [610.0, 120.0])
    new, changed = mg5.auto_widths(text)
    assert {2000001, 2000002} <= set(changed)          # ~d_R, ~u_R: 'DECAY ... 0.0', no channels
    assert 1000021 not in changed                       # gluino is decoupled
    assert any(l.startswith("DECAY 2000002 auto") for l in new.splitlines())
    lines = [l for l in new.splitlines() if l.upper().startswith("DECAY")]
    assert any(l.split()[1] == "1000022" and l.split()[2] != "auto" for l in lines)   # LSP untouched


def test_mg5_exclude_decoupled_gluino():
    mg5 = load_mg5()
    d = os.path.join(MG5_DATA, "T2")
    slha = mg5.fill_slha_template(os.path.join(d, "spectrum.slha"), [610.0, 120.0])
    card = mg5.generate_proc_card(os.path.join(d, "proc_card.dat"), 1, "OUT")
    new, done = mg5.exclude_decoupled_gluino(card, slha)
    assert done and all(l.endswith("/ go") for l in proc_lines(new))
    # T1 produces gluinos: untouched
    d1 = os.path.join(MG5_DATA, "T1")
    s1 = mg5.fill_slha_template(os.path.join(d1, "spectrum.slha"), [1400.0, 600.0])
    c1 = mg5.generate_proc_card(os.path.join(d1, "proc_card.dat"), 1, "OUT")
    assert mg5.exclude_decoupled_gluino(c1, s1) == (c1, False)
    # exclusions and tags keep their place
    s = "import model MSSM_SLHA2\ngenerate p p > n2 x1- $ n2 x1- @1 # c\nadd process p p > t1 t1~ / ul"
    new, _ = mg5.exclude_decoupled_gluino(s, slha)
    assert proc_lines(new) == ["generate p p > n2 x1- $ n2 x1- / go @1 # c",
                               "add process p p > t1 t1~ / go ul"]


def test_mg5_cross_section_into_hepmc(tmp_path):
    mg5 = load_mg5()
    log = tmp_path / "mg5.log"
    log.write_text("     Cross-section :   0.5263 +- 0.001449 pb\n"
                   "     Matched cross-section :   0.3432 +- 0.01125 pb\n")
    assert mg5.mg5_cross_section(str(log)) == (0.3432, 0.01125)
    src = tmp_path / "in.hepmc"
    src.write_text("HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n"
                   "E 0 -1 0 0 0 0 0 1 1 2 0 1 0.5\nN 1 \"0\"\nU GEV MM\nV -1 0 0 0 0 0 0 0 0\n"
                   "E 1 -1 0 0 0 0 0 1 1 2 0 1 0.5\nU GEV MM\nC 9 9\nV -1 0 0 0 0 0 0 0 0\n"
                   "HepMC::IO_GenEvent-END_EVENT_LISTING\n")
    dst = tmp_path / "out.hepmc.gz"
    mg5.add_hepmc_cross_section(str(src), str(dst), (0.3432, 0.01125))
    out = gzip.open(dst, "rt").read().splitlines()
    assert sum(l.startswith("C ") for l in out) == 2 and "C 9 9" not in out
    assert out[out.index("U GEV MM") + 1].startswith("C 3.432")
