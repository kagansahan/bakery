import os

WRAPPER_DIR = os.path.join(workflow.basedir, "wrappers")
W_DELPHES = "file://" + os.path.join(WRAPPER_DIR, "delphes")

def get_delphes_card(w):
    for detector in config.get("detectors", []):
        if detector["name"] == w.detector:
            return detector.get("card", "")
    return ""

AVAILABLE_DETECTORS.extend(["ATLAS", "CMS"])

if ACTIVE_DETECTORS:
    rule run_delphes:
        input:
            hepmc="results/{sqrts}/{process}/{param_pt}/{generator}.events.hepmc.gz"
        output:
            root="results/{sqrts}/{process}/{param_pt}/delphes/{generator}.{detector}.root"
        params:
            delphes_card = get_delphes_card
        wrapper: W_DELPHES
