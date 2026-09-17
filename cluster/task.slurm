#!/bin/bash
# One array task = one simulation.  Submitted by cluster/submit.sh, never by hand.
set -euo pipefail
: "${ANORL_ROOT:?}" "${MANIFEST:?}" "${SLURM_ARRAY_TASK_ID:?}"
source "$ANORL_ROOT/env.sh"
# ns-3 adds a profile suffix to scratch binaries for some profiles, such as
# ns3.48-anorl-mix-optimized, and none for the release profile, which gives ns3.48-anorl-mix.
# Accept both, without ls, so a missing match cannot abort the script under set -e.
BIN=""
for c in "$ANORL_ROOT"/ns-3.48/build/scratch/ns3.48-anorl-mix "$ANORL_ROOT"/ns-3.48/build/scratch/ns3.48-anorl-mix-*; do
  if [ -f "$c" ] && [ -x "$c" ]; then BIN="$c"; break; fi
done
[ -n "$BIN" ] || { echo "ns-3 binary not found under $ANORL_ROOT/ns-3.48/build/scratch"; exit 1; }
export ANORL_BIN="$BIN"
export ANORL_AMIGO="$ANORL_ROOT/amigo_copy"
export ANORL_OUT="$ANORL_ROOT/results/attacks"
# scenario files are bulky and regenerable, so they live on node-local disk and are removed
export ANORL_SCN="${TMPDIR:-/tmp}/anorl_${SLURM_ARRAY_JOB_ID:-0}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$ANORL_SCN"
trap 'rm -rf "$ANORL_SCN"' EXIT
cd "$ANORL_ROOT/anorl-mixsim"
python3 cluster/run_one.py --index "$SLURM_ARRAY_TASK_ID" --manifest "$MANIFEST"
