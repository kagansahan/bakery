"""Snakemake wrapper: Pythia8 standalone (hard process + shower + hadronisation).

No MadGraph: Pythia8 reads the SUSY spectrum and decay table (the topology's
SLHA template, shared with the mg5amcnlo wrapper) and generates the sparticle
pair itself with its built-in SUSY 2->2 processes, restricted to the pairs
the topology's MadGraph process card produces.

Differences to MG5PY8, by construction:
  * no matrix-element jets: extra radiation comes from the parton shower only
    (extrajet is ignored), so hard ISR is less well described;
  * MadGraph '$' / '/' exclusions are not applied (Pythia's processes include
    every diagram; with decoupled sparticles in the templates the effect is
    negligible);
  * the pair kind (gluino-gluino, squark-gluino, chargino-neutralino, ...) is
    selected with Pythia's process switches and the sparticles with
    SUSY:idVecA/idVecB. That still allows pairs the card does not list (e.g.
    ~u_L ~d_L* for T2, or n1 n1 and n2 n2 for 'p p > n1 n2'), so every event
    whose hard-process pair is not in the card is vetoed, and the cross
    section written to the HepMC file is sigmaGen x accepted fraction.
Only MSSM topologies are supported (import model MSSM_SLHA2).

Output: gzipped HepMC2 ASCII (what DelphesHepMC2 and Rivet read), with the
generated cross section attached to every event.
"""
import gzip
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MG5_DATA = os.path.join(HERE, "..", "mg5amcnlo", "data")

# MSSM_SLHA2 UFO particle names -> PDG id of the particle (antiparticle: '~',
# or the opposite charge sign for charginos / sleptons)
MSSM_PDG = {
    "dl": 1000001, "ul": 1000002, "sl": 1000003, "cl": 1000004, "b1": 1000005, "t1": 1000006,
    "dr": 2000001, "ur": 2000002, "sr": 2000003, "cr": 2000004, "b2": 2000005, "t2": 2000006,
    "el-": 1000011, "sve": 1000012, "mul-": 1000013, "svm": 1000014, "ta1-": 1000015,
    "svt": 1000016, "er-": 2000011, "mur-": 2000013, "ta2-": 2000015,
    "go": 1000021, "n1": 1000022, "n2": 1000023, "n3": 1000025, "n4": 1000035,
    "x1+": 1000024, "x2+": 1000037,
}
# MSSM_SLHA2-full squark mass eigenstates
for i, pdg in enumerate((1000002, 1000004, 1000006, 2000002, 2000004, 2000006), 1):
    MSSM_PDG[f"su{i}"] = pdg
for i, pdg in enumerate((1000001, 1000003, 1000005, 2000001, 2000003, 2000005), 1):
    MSSM_PDG[f"sd{i}"] = pdg
SELF_CONJUGATE = {1000021, 1000022, 1000023, 1000025, 1000035}


def kind(pdg):
    a = abs(pdg)
    if a in (1000021,):
        return "go"
    if a in (1000022, 1000023, 1000025, 1000035):
        return "chi0"
    if a in (1000024, 1000037):
        return "chi+"
    if a % 1000000 <= 6:
        return "sq"
    return "sl"


# Pythia8 SUSY process switches per pair kind
PROCESS_FLAGS = {
    ("go", "go"): ["SUSY:gg2gluinogluino", "SUSY:qqbar2gluinogluino"],
    ("go", "sq"): ["SUSY:qg2squarkgluino"],
    ("sq", "sq~"): ["SUSY:gg2squarkantisquark", "SUSY:qqbar2squarkantisquark"],
    ("sq", "sq"): ["SUSY:qq2squarksquark"],
    ("chi0", "chi0"): ["SUSY:qqbar2chi0chi0"],
    ("chi+", "chi0"): ["SUSY:qqbar2chi+-chi0"],
    ("chi+", "chi+"): ["SUSY:qqbar2chi+chi-"],
    ("chi0", "go"): ["SUSY:qqbar2chi0gluino"],
    ("chi+", "go"): ["SUSY:qqbar2chi+-gluino"],
    ("chi0", "sq"): ["SUSY:qg2chi0squark"],
    ("chi+", "sq"): ["SUSY:qg2chi+-squark"],
    ("sl", "sl"): ["SUSY:qqbar2sleptonantislepton"],
}


def pair_class(a, b):
    ka, kb = kind(a), kind(b)
    if ka == kb == "sq":
        return ("sq", "sq~") if (a > 0) != (b > 0) else ("sq", "sq")
    return tuple(sorted((ka, kb)))


def pdg_of(name, defines):
    """Set of signed PDG ids for a MadGraph particle or multiparticle label."""
    key = name.lower()
    if key in defines:
        out = set()
        for sub in defines[key]:
            out |= pdg_of(sub, defines)
        return out
    anti = key.endswith("~")
    base = key[:-1] if anti else key
    if base in MSSM_PDG:
        pdg = MSSM_PDG[base]
    elif base.replace("-", "+") in MSSM_PDG:          # x1- is the antiparticle of x1+
        pdg, anti = MSSM_PDG[base.replace("-", "+")], not anti
    elif base.replace("+", "-") in MSSM_PDG:          # el+ is the antiparticle of el-
        pdg, anti = MSSM_PDG[base.replace("+", "-")], not anti
    else:
        raise ValueError(f"particle {name!r} is not an MSSM sparticle Pythia8 can produce")
    return {pdg if (pdg in SELF_CONJUGATE or not anti) else -pdg}


def sparticle_pairs(proc_card):
    """{(pdgA, pdgB)} (signed, sorted) from the 'generate' / 'add process' lines.

    Lines with extra 'j' in the final state are skipped: in Pythia8 the
    extra jets come from the shower.
    """
    with open(proc_card) as f:
        text = f.read().replace("\\\n", " ")
    lines = [l.split("#", 1)[0].strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    model = next((l.split()[2] for l in lines if l.startswith("import model ")), None)
    if model is None or not model.startswith("MSSM_SLHA2"):
        raise ValueError(f"{proc_card}: model {model!r}; Pythia8 standalone supports "
                         "only MSSM topologies (import model MSSM_SLHA2)")
    defines = {}
    pairs = set()
    for l in lines:
        tok = l.split()
        if tok[0] == "define" and len(tok) >= 4 and tok[2] == "=":
            defines[tok[1].lower()] = tok[3:]
            continue
        if not l.startswith(("generate ", "add process ")):
            continue
        if l.startswith("generate "):
            pairs = set()     # like MadGraph: 'generate' starts a new process list
        body = l.split(None, 1)[1] if l.startswith("generate ") else l.split(None, 2)[2]
        body = re.sub(r"@\s*\d+", "", body)
        core = re.split(r"\s\$|\s/|,", body)[0]
        final = [x for x in core.split(">", 1)[1].split()]
        if any(x.lower() == "j" for x in final):
            continue      # explicit extra-jet line
        if len(final) != 2:
            raise ValueError(f"{proc_card}: '{l}' is not a 2 -> 2 sparticle pair; "
                             "Pythia8 standalone cannot produce it")
        a, b = (pdg_of(x, defines) for x in final)
        pairs |= {tuple(sorted((x, y))) for x in a for y in b}
    if not pairs:
        raise ValueError(f"{proc_card}: no process line")
    return pairs


def pythia_settings(pairs, slha, sqrts, nevents, seed):
    """Pythia8 settings, and the pairs Pythia may produce beyond `pairs`
    (|PDG|, sorted; these events are vetoed in main()).

    The process switches select the kind of pair (e.g. squark-gluino only), the
    SUSY:idVecA/B lists the sparticles; within one kind Pythia allows every
    combination of the listed sparticles.
    """
    classes = sorted({pair_class(a, b) for a, b in pairs})
    missing = [c for c in classes if c not in PROCESS_FLAGS]
    if missing:
        raise ValueError(f"no Pythia8 SUSY process produces a {missing} pair")
    flags = sorted({f for c in classes for f in PROCESS_FLAGS[c]})
    ids = sorted({abs(x) for pair in pairs for x in pair})
    allowed = set()
    for i, a in enumerate(ids):
        for b in ids[i:]:
            for sa in (a, -a):
                for sb in (b, -b):
                    if pair_class(sa, sb) in classes:
                        allowed.add(tuple(sorted((abs(sa), abs(sb)))))
    extra = sorted(allowed - {tuple(sorted((abs(x), abs(y)))) for x, y in pairs})
    vec = "{" + ",".join(str(x) for x in ids) + "}"
    settings = [
        f"Beams:eCM = {sqrts * 1000.0}",
        f"Main:numberOfEvents = {nevents}",
        "SLHA:readFrom = 2",
        f"SLHA:file = {slha}",
        # keep Pythia's own SM masses and decays (the MG5 templates carry SM
        # widths without branching ratios)
        "SLHA:minMassSM = 1000.0",
        *[f"{f} = on" for f in flags],
        f"SUSY:idVecA = {vec}",
        f"SUSY:idVecB = {vec}",
        "Random:setSeed = on",
        f"Random:seed = {seed}",
        "Next:numberCount = 1000",
    ]
    return settings, extra


def fill_slha(template, masses):
    """Same placeholder rule as the mg5amcnlo wrapper: value i fills M{n-1-i}."""
    with open(template) as f:
        text = f.read()
    n = len(masses)
    for i, m in enumerate(masses):
        text = re.sub(rf"\bM{n - i - 1}\b", repr(float(m)), text)
    left = re.findall(r"\bM[0-9]\b", text)
    if left:
        raise ValueError(f"{template}: placeholders {sorted(set(left))} not filled; got {n} masses")
    return text


def drop_stable_coloured(slha_text, produced):
    """Remove empty, zero-width DECAY blocks of produced squarks / gluinos.

    Several templates (e.g. T2, TGQ: ~u_R, ~d_R) declare such particles stable
    ('DECAY 2000001 0.0' with no channels). A stable coloured sparticle cannot
    be hadronised (Pythia then fails on about half of the T2 events). Without
    the block Pythia computes the widths and branching ratios itself from the
    spectrum. Neutral / colourless sparticles are left as the template says.
    Returns (new text, list of PDG ids whose block was removed).
    """
    lines = slha_text.splitlines(keepends=True)
    blocks, cur = {}, None          # pdg -> [start, end, width, n_channels]
    for i, line in enumerate(lines):
        tok = line.split("#", 1)[0].split()
        if tok and tok[0].upper() in ("DECAY", "BLOCK"):
            cur = None
            if tok[0].upper() == "DECAY" and len(tok) >= 3:
                try:
                    cur = abs(int(tok[1]))
                    blocks[cur] = [i, i + 1, float(tok[2]), 0]
                except ValueError:
                    cur = None
            continue
        if cur is not None:
            blocks[cur][1] = i + 1
            if tok:
                blocks[cur][3] += 1
    drop = sorted(pdg for pdg in {abs(x) for x in produced}
                  if kind(pdg) in ("sq", "go") and pdg in blocks
                  and blocks[pdg][2] == 0.0 and blocks[pdg][3] == 0)
    for pdg in sorted(drop, key=lambda q: -blocks[q][0]):
        start, end = blocks[pdg][0], blocks[pdg][1]
        lines[start:end] = [f"# DECAY {pdg}: empty zero-width block removed by bakery, "
                            "Pythia computes the decays\n"]
    return "".join(lines), drop


def import_pythia():
    for name in ("pythia8", "pythia8mc"):   # conda-forge / PyPI module names
        try:
            return __import__(name)
        except ImportError:
            pass
    raise ImportError("no Pythia8 Python module (pythia8 or pythia8mc)")


def to_hepmc(pyhepmc, ev, number, sigma_pb, sigma_err_pb, weight):
    """Pythia8 event record -> HepMC GenEvent, same vertex logic as Pythia8ToHepMC:
    a particle is outgoing from the first existing end vertex among its
    mothers (or a new one); mothers without an end vertex are attached to it."""
    gev = pyhepmc.GenEvent(pyhepmc.Units.GEV, pyhepmc.Units.MM)
    gev.event_number = number
    parts = [None]
    for i in range(1, ev.size()):
        p = ev[i]
        parts.append(pyhepmc.GenParticle(
            pyhepmc.FourVector(p.px(), p.py(), p.pz(), p.e()), p.id(), p.statusHepMC()))
        parts[-1].generated_mass = p.m()
    end_vtx = [None] * ev.size()
    for i in range(1, ev.size()):
        p = ev[i]
        moms = [m for m in p.motherList() if m > 0]
        if not moms:
            continue          # the two beams
        v = next((end_vtx[m] for m in moms if end_vtx[m] is not None), None)
        if v is None:
            v = pyhepmc.GenVertex(pyhepmc.FourVector(p.xProd(), p.yProd(), p.zProd(), p.tProd()))
            gev.add_vertex(v)
        for m in moms:
            if end_vtx[m] is None:
                v.add_particle_in(parts[m])
                end_vtx[m] = v
        v.add_particle_out(parts[i])
    gev.weights = [weight]
    xs = pyhepmc.GenCrossSection()
    xs.set_cross_section(sigma_pb, sigma_err_pb)
    gev.cross_section = xs
    return gev


def hard_pair(process):
    """Signed, sorted PDG ids of the two outgoing particles of the hard process."""
    return tuple(sorted((process[5].id(), process[6].id())))


def listed_sigma(info, n_ok, n_all):
    """Cross section of the card's pairs: sigmaGen x accepted fraction, in pb."""
    f = n_ok / n_all
    sig, err = info.sigmaGen() * 1e9, info.sigmaErr() * 1e9      # mb -> pb
    stat = sig * (f * (1 - f) / n_all) ** 0.5
    return sig * f, ((err * f) ** 2 + stat ** 2) ** 0.5


def main():
    p = snakemake.params  # noqa: F821
    topo = p.process_name
    masses = [float(m) for m in p.parameter_point]
    sqrts = float(p.sqrt)
    nevents = int(p.nevents)
    seed = int(p.get("seed", 1))
    out = os.path.abspath(snakemake.output.hepmc)  # noqa: F821
    log = open(snakemake.log[0], "w", buffering=1)  # noqa: F821
    # Pythia8 (C++) writes to file descriptors 1 and 2, not to sys.stdout:
    # redirect the descriptors so its messages end up in the log too
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    sys.stdout = log
    sys.stderr = log

    topo_dir = os.path.join(MG5_DATA, topo)
    slha_t = os.path.join(topo_dir, "spectrum.slha")
    proc = os.path.join(topo_dir, "proc_card.dat")
    for f in (slha_t, proc):
        if not os.path.exists(f):
            raise FileNotFoundError(f"{topo}: {f} missing")
    if int(p.get("extrajets", 0)):
        print(f"[pythia8] note: extrajet={p.extrajets} ignored, jets come from the shower")

    pairs = sparticle_pairs(proc)
    tmp = tempfile.mkdtemp(prefix="pythia8_")
    try:
        slha = os.path.join(tmp, "spectrum.slha")
        text, dropped = drop_stable_coloured(fill_slha(slha_t, masses),
                                             {x for pair in pairs for x in pair})
        if dropped:
            print(f"[pythia8] note: the template declares {dropped} stable (DECAY width 0, "
                  "no channels); Pythia computes their decays instead")
        with open(slha, "w") as f:
            f.write(text)
        settings, extra = pythia_settings(pairs, slha, sqrts, nevents, seed)
        print(f"[pythia8] {topo} masses={masses} pairs={sorted(pairs)}")
        if extra:
            print(f"[pythia8] note: Pythia also produces {extra}; these events "
                  "are vetoed")
        for s in settings:
            print("[pythia8]   " + s)
        log.flush()

        pythia8 = import_pythia()
        import pyhepmc
        py = pythia8.Pythia("", True)
        for s in settings:
            if not py.readString(s):
                raise RuntimeError(f"Pythia8 rejected setting: {s}")
        if not py.init():
            raise RuntimeError("Pythia8 initialisation failed (see the log above)")

        plain = os.path.join(tmp, "events.hepmc")
        n_ok, n_all, n_fail = 0, 0, 0
        with pyhepmc.open(plain, "w", format="hepmc2") as wr:
            while n_ok < nevents:
                if not py.next():
                    n_fail += 1
                    if n_fail > max(100, nevents // 10):
                        raise RuntimeError(f"too many failed events ({n_fail})")
                    continue
                n_all += 1
                if n_all > 1000 * nevents:
                    raise RuntimeError(f"{n_ok} of {n_all} events have a pair of the card; "
                                       "the veto rejects almost everything")
                # 2 -> 2 hard process: entries 5 and 6 are the outgoing sparticles
                if hard_pair(py.process) not in pairs:
                    continue
                info = py.infoPython()
                sigma_pb, err_pb = listed_sigma(info, n_ok + 1, n_all)
                wr.write(to_hepmc(pyhepmc, py.event, n_ok, sigma_pb, err_pb, info.weight()))
                n_ok += 1
        py.stat()
        info = py.infoPython()
        sigma_pb, err_pb = listed_sigma(info, n_ok, n_all)
        print(f"[pythia8] {n_ok} events written, {n_all - n_ok} vetoed (pair not in the "
              f"card), {n_fail} failed")
        print(f"[pythia8] sigma(all pairs) = {info.sigmaGen() * 1e9:.6g} pb, "
              f"sigma(card pairs) = {sigma_pb:.6g} +- {err_pb:.3g} pb")
        # every event carries the running estimate; write the final cross
        # section into all of them ('C <sigma> <error>' lines of HepMC2)
        final = f"C {sigma_pb:.16e} {err_pb:.16e}\n"
        with open(plain, "r") as fi, gzip.open(out, "wt") as fo:
            for line in fi:
                fo.write(final if line.startswith("C ") else line)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        log.flush()


if "snakemake" in globals():
    main()
