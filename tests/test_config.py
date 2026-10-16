"""The workflow builds its job graph from both config styles (snakemake dry run).

    python -m pytest tests/
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SNAKEMAKE = shutil.which("snakemake")


def dry_run(configfile, *extra):
    r = subprocess.run(
        [SNAKEMAKE, "-s", "workflow/Snakefile", "--configfile", configfile, "-n", *extra],
        cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def job_count(out, rule):
    m = re.search(rf"^{rule}\s+(\d+)$", out, re.M)
    return int(m.group(1)) if m else 0


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_current_config_style():
    code, out = dry_run(".test/config.yml")
    assert code == 0, out
    assert job_count(out, "run_mg5py8") == 2 and job_count(out, "run_pythia8") == 2


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_legacy_config_style():
    code, out = dry_run(".test/config_legacy.yml")
    assert code == 0, out
    assert "sample of process 'T1' skipped" in out
    # 2 points x 2 generators; ATLAS rivet+cutlang and CMS cutlang
    assert job_count(out, "run_rivet") == 4
    assert job_count(out, "run_cutlang") == 8
    assert job_count(out, "run_delphes") == 8


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_legacy_recaster_switch(tmp_path):
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(ROOT, ".test/config_legacy.yml")) as f:
        cfg = yaml.safe_load(f)
    for r in cfg["recasters"]:
        if r["name"] == "rivet":
            r["enabled"] = False
    path = tmp_path / "cfg.yml"
    path.write_text(yaml.safe_dump(cfg))
    code, out = dry_run(str(path))
    assert code == 0, out
    assert job_count(out, "run_rivet") == 0 and job_count(out, "run_cutlang") == 8


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_wrong_parameter_index_is_an_error(tmp_path):
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(ROOT, ".test/config_legacy.yml")) as f:
        cfg = yaml.safe_load(f)
    cfg["processes"][0]["parameters"] = [{"name": "MLSP", "index": 0},
                                         {"name": "MSQUARK", "index": 1}]
    path = tmp_path / "cfg.yml"
    path.write_text(yaml.safe_dump(cfg))
    code, out = dry_run(str(path))
    assert code != 0 and "heaviest first" in out


def legacy(tmp_path, edit):
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(ROOT, ".test/config_legacy.yml")) as f:
        cfg = yaml.safe_load(f)
    edit(cfg)
    path = tmp_path / "cfg.yml"
    path.write_text(yaml.safe_dump(cfg))
    return dry_run(str(path))


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_disabled_detector_ignored_when_matching_experiment(tmp_path):
    def edit(cfg):
        cfg["detectors"].append({"name": "ATLASold", "experiment": "ATLAS",
                                 "card": "old.tcl", "enabled": False})
    code, out = legacy(tmp_path, edit)
    assert code == 0, out
    assert job_count(out, "run_cutlang") == 8


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_pythia8_skipped_for_non_mssm(tmp_path):
    def edit(cfg):
        cfg["processes"][0]["name"] = "TRV1"     # DMsimp model
        for smp in cfg["samples"]:
            if smp["process"] == "T2":
                smp["process"] = "TRV1"
    code, out = legacy(tmp_path, edit)
    assert code == 0, out
    assert "Pythia8 skipped for TRV1" in out
    assert job_count(out, "run_pythia8") == 0 and job_count(out, "run_mg5py8") == 2


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_duplicate_entry_after_skipped_one(tmp_path):
    def edit(cfg):
        for r in cfg["recasters"]:
            r["enabled"] = r["name"] != "rivet"
        ana = cfg["analyses"][0]
        ana["recasting"].append(dict(ana["recasting"][0]))   # second rivet entry
    code, out = legacy(tmp_path, edit)
    assert code != 0 and "listed twice" in out


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_detector_from_analysis_name_prefix(tmp_path):
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(ROOT, ".test/config.yml")) as f:
        cfg = yaml.safe_load(f)
    for ana in cfg["analyses"]:
        ana.pop("experiment", None)          # CMS-SUS-19-006 -> CMS from the name
        for rc in ana["recasting"]:
            assert "detsim" not in rc
    path = tmp_path / "cfg.yml"
    path.write_text(yaml.safe_dump(cfg))
    code, out = dry_run(str(path))
    assert code == 0, out
    assert job_count(out, "run_cutlang") == 4 and job_count(out, "run_delphes") == 4
    assert "delphes-CMS.root" in out and "delphes-ATLAS" not in out


@pytest.mark.skipif(SNAKEMAKE is None, reason="snakemake not installed")
def test_example_config_is_valid():
    # config/config.example.yml documents every option; it must keep working
    code, out = dry_run("config/config.example.yml")
    assert code == 0, out
    # 4 mass points (3 x T2, 1 x T1), MG5PY8 only, CutLang + Rivet, 2 x 2 maps
    for rule, n in (("run_mg5py8", 4), ("run_cutlang", 4), ("run_rivet", 4), ("create_em", 4)):
        assert job_count(out, rule) == n, (rule, out)
