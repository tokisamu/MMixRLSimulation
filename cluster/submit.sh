#!/bin/bash
# Submit all simulations as one SLURM job array and let the scheduler run them.
#
#   cluster/submit.sh --partition NAME [--account NAME] [--time 12:00:00] [--dry-run]
#   cluster/submit.sh --partition NAME --indices "3,17-20"      # resubmit only these tasks
#
# Written for bash 3.2 as well, so a dry run also works on macOS.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ANORL_ROOT="${ANORL_ROOT:-$(cd "$HERE/../.." && pwd)}"
PARTITION=""; ACCOUNT=""; TIME="12:00:00"; DRY=0; INDICES=""
MANIFEST="$HERE/jobs.tsv"
while [ $# -gt 0 ]; do
  case "$1" in
    --partition) PARTITION="$2"; shift 2;;
    --account)   ACCOUNT="$2"; shift 2;;
    --time)      TIME="$2"; shift 2;;
    --indices)   INDICES="$2"; shift 2;;
    --manifest)  MANIFEST="$2"; shift 2;;
    --dry-run)   DRY=1; shift;;
    *) echo "unknown option $1"; exit 2;;
  esac
done
[ -f "$MANIFEST" ] || { echo "manifest missing: $MANIFEST"; exit 1; }
# each task changes directory before reading the manifest, so a relative path given
# here would not be found there: make it absolute
MANIFEST="$(cd "$(dirname "$MANIFEST")" && pwd)/$(basename "$MANIFEST")"
N=$(( $(wc -l < "$MANIFEST") - 1 ))              # minus the header line
SPEC="${INDICES:-0-$((N - 1))}"
if [ "$DRY" = 0 ]; then
  [ -f "$ANORL_ROOT/env.sh" ] || { echo "env.sh missing: run cluster/build_ns3.sh first"; exit 1; }
  command -v sbatch >/dev/null || { echo "sbatch not found: this cluster may not use SLURM"; exit 1; }
  mkdir -p "$ANORL_ROOT/logs" "$ANORL_ROOT/results/attacks"
fi

set -- --parsable --job-name=anorl-attacks --array="$SPEC" --time="$TIME" \
       --cpus-per-task=1 --mem=4G \
       --output="$ANORL_ROOT/logs/%x_%A_%a.out" --error="$ANORL_ROOT/logs/%x_%A_%a.err" \
       --export=ALL,ANORL_ROOT="$ANORL_ROOT",MANIFEST="$MANIFEST"
[ -n "$PARTITION" ] && set -- "$@" --partition="$PARTITION"
[ -n "$ACCOUNT" ]   && set -- "$@" --account="$ACCOUNT"

if [ "$DRY" = 1 ]; then
  echo "[dry-run] one job array, tasks $SPEC, time limit $TIME"
  echo "          sbatch $* $HERE/task.slurm"
else
  id=$(sbatch "$@" "$HERE/task.slurm")
  echo "submitted job array $id: tasks $SPEC, time limit $TIME"
fi
