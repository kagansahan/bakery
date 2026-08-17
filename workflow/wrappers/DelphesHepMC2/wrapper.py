import os
import sys
import gzip
import shutil
import subprocess
import tempfile

def info(msg):
    print(f"[DelphesHepMC2Wrapper] {msg}")

def error(msg, exit_code=1):
    print(f"[DelphesHepMC2Wrapper] ERROR: {msg}", file=sys.stderr)
    sys.exit(exit_code)

def run_command(cmd, cwd=None, log=None):
    info(f"Running: {' '.join(cmd)}")
    try:
        if log:
            with open(log, 'a') as f:
                subprocess.check_call(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        else:
            subprocess.check_call(cmd, cwd=cwd)
        return True
    except subprocess.CalledProcessError as e:
        error(f"Command failed with exit code {e.returncode}: {' '.join(cmd)}")
        return False

def decompress_gz(input_path, output_dir):
    basename = os.path.basename(input_path)
    if basename.endswith('.gz'):
        basename = basename[:-3]
    out_path = os.path.join(output_dir, basename)
    info(f"Decompressing {input_path} -> {out_path}")
    with gzip.open(input_path, 'rb') as f_in, open(out_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    return out_path

def main():
    try:
        input_hepmc = snakemake.input[0]
        output_root = snakemake.output[0]
        card_file = snakemake.params.card
        log_out = snakemake.log[0]
    except AttributeError:
        error("This wrapper must be run inside Snakemake (snakemake object not found).")

    delphes_exe = 'DelphesHepMC2'

    tmp_dir = tempfile.mkdtemp(prefix="delpheshepmc2wrapper_")
    info(f"Temporary directory: {tmp_dir}")

    if input_hepmc.endswith('.gz'):
        hepmc_input = decompress_gz(input_hepmc, tmp_dir)
    else:
        hepmc_input = input_hepmc

    info(f"Running Delphes with card {card_file}")
    success = run_command([delphes_exe, card_file, output_root, hepmc_input],
                          log=log_out)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()