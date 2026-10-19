#!/usr/bin/env bash
# job wrapper for CERN lxbatch (HTCondor, EosSubmit).
set -euo pipefail

log() { echo "[job_wrapper $(date +%H:%M:%S)] $*" >&2; }

ls -d "$PWD" >/dev/null 2>&1 || true   

PY="${BAKERY_SNAKEMAKE_PYTHON:-}"
if [[ $# -ge 3 && "$2" == "-m" && "$3" == "snakemake" ]]; then
  [[ -n "$PY" ]] || PY="$1"
  shift 3
elif [[ $# -ge 2 && "$1" == "-m" && "$2" == "snakemake" ]]; then
  shift 2
fi
if [[ -z "$PY" ]]; then
  PY="$(command -v python || command -v python3 || true)"
else
  PY="$(command -v "$PY" || true)"      # "python" -> its path on PATH; an absolute path stays
fi
if [[ -z "$PY" ]] || ! "$PY" -c "import snakemake" 2>/dev/null; then
  log "ERROR: no python with snakemake (tried '${PY:-none}')"
  log "PATH=$PATH"
  exit 91
fi

WORKDIR="${BAKERY_WORKDIR:-}"
snakefile=""; prev=""
for a in "$@"; do
  if [[ -z "$WORKDIR" && ( "$prev" == "--directory" || "$prev" == "-d" ) ]]; then WORKDIR="$a"; fi
  if [[ "$prev" == "--snakefile" || "$prev" == "-s" ]]; then snakefile="$a"; fi
  prev="$a"
done
if [[ -z "$WORKDIR" && -n "$snakefile" ]]; then
  sd="$(dirname "$snakefile")"
  if [[ "$(basename "$sd")" == "workflow" ]]; then WORKDIR="$(dirname "$sd")"; else WORKDIR="$sd"; fi
fi
if [[ -n "$WORKDIR" ]]; then ls -d "$WORKDIR" >/dev/null 2>&1 || true; fi   # EOS automount
if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
  cd "$WORKDIR"
else
  log "WARNING: workflow directory not found (WORKDIR='${WORKDIR}'); staying in $(pwd)"
fi

# everything conda writes goes to the job's scratch
SCRATCH="${_CONDOR_SCRATCH_DIR:-${TMPDIR:-/tmp}}"
BASE="$SCRATCH/bakery_conda"
CONDA_ROOT="$BASE/miniforge"
ENVS_DIR="$BASE/envs"

export BAKERY_REAL_HOME="${HOME:-}"
export HOME="$SCRATCH/home"
export XDG_CACHE_HOME="$SCRATCH/cache"
export TMPDIR="$SCRATCH/tmp"
export PIP_CACHE_DIR="$BASE/pip"
export CONDA_PKGS_DIRS="$BASE/pkgs"
export CONDA_ENVS_DIRS="$ENVS_DIR"
export CONDA_REGISTER_ENVS=false
export CONDA_NUMBER_CHANNEL_NOTICES=0
export CONDA_SOLVER=libmamba
export CONDARC=/dev/null                # ignore conda settings that live on AFS/EOS
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$TMPDIR" "$BASE" "$ENVS_DIR"

retry() { local n=$1; shift; local i
  for ((i=1;i<=n;i++)); do "$@" && return 0; log "attempt $i/$n failed"; sleep $((i*10)); done; return 1; }

# use an existing one else install miniforge3 on scratch
LOCAL_CONDA=""
for c in "${BAKERY_CONDA:-}" "$(dirname "$PY")/conda" "$(command -v conda || true)"; do
  if [[ -n "$c" && -x "$c" ]]; then LOCAL_CONDA="$c"; break; fi
done

if [[ -n "$LOCAL_CONDA" && "${BAKERY_FORCE_BOOTSTRAP:-0}" != 1 ]]; then
  export PATH="$(dirname "$LOCAL_CONDA"):$PATH"
  log "using existing conda: $LOCAL_CONDA"
else
  INSTALLER_URL="${BAKERY_MINIFORGE_URL:-https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh}"
  if [[ ! -x "$CONDA_ROOT/bin/conda" ]]; then
    log "no conda found: installing Miniforge into $CONDA_ROOT"
    retry 3 curl -fsSL -o "$BASE/miniforge.sh" "$INSTALLER_URL"
    bash "$BASE/miniforge.sh" -b -p "$CONDA_ROOT" >/dev/null
    rm -f "$BASE/miniforge.sh"
  fi
  export PATH="$CONDA_ROOT/bin:$PATH"
fi
log "host=$(hostname) scratch=$SCRATCH python=$PY conda=$(conda --version 2>&1) workdir=$(pwd)"

# --conda-prefix on scratch, conda deployment switched on
args=(); i=0; fixed=0
while (( i < $# )); do
  a="${@:i+1:1}"
  if [[ "$a" == "--conda-prefix" ]]; then args+=("--conda-prefix" "$ENVS_DIR"); i=$((i+2)); fixed=1; continue; fi
  if [[ "$a" == --conda-prefix=* ]]; then args+=("--conda-prefix=$ENVS_DIR"); i=$((i+1)); fixed=1; continue; fi
  args+=("$a"); i=$((i+1))
done
(( fixed )) || args+=("--conda-prefix" "$ENVS_DIR")

has() { local x; for x in "${args[@]}"; do [[ "$x" == "$1" || "$x" == "$1="* ]] && return 0; done; return 1; }
has --use-conda || has --deployment-method || has --software-deployment-method || args+=("--use-conda")
has --conda-frontend || args+=("--conda-frontend" "conda")
log "conda-prefix -> $ENVS_DIR"

log "exec: $PY -m snakemake ${args[*]:0:3} ..."
exec "$PY" -m snakemake "${args[@]}"
