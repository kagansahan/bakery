#!/bin/bash
# Runs on the worker before each job; forwards HTCondor's arguments to Snakemake.
set -eo pipefail

SCRATCH="${_CONDOR_SCRATCH_DIR:-${TMPDIR:-/tmp}}"

# Caches and temp files on local scratch (not AFS, not EOS FUSE)
export CONDA_PKGS_DIRS="$SCRATCH/conda_pkgs"
export XDG_CACHE_HOME="$SCRATCH/cache"
export TMPDIR="$SCRATCH/tmp"
mkdir -p "$CONDA_PKGS_DIRS" "$XDG_CACHE_HOME" "$TMPDIR"

ls -d "$PWD" >/dev/null 2>&1 || true   # trigger the EOS automount

if ! python -c "import snakemake" 2>/dev/null; then
    echo "[job_wrapper] ERROR: no python with snakemake on PATH: $(command -v python || echo none)" >&2
    echo "[job_wrapper] PATH=$PATH" >&2
    exit 1
fi

echo "[job_wrapper] host=$(hostname) scratch=$SCRATCH python=$(command -v python)" \
     "conda=$(command -v conda || echo none)" >&2

exec "$@"