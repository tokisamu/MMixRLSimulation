#!/bin/bash
# On the cluster: bundle the finished results so they can be copied back in one file.
#   cluster/collect.sh            result summaries only, small
#   cluster/collect.sh --with-logs   also the event logs, large
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ANORL_ROOT="${ANORL_ROOT:-$(cd "$HERE/../.." && pwd)}"
cd "$ANORL_ROOT/results"
stamp=$(date +%Y%m%d_%H%M)
if [ "${1:-}" = "--with-logs" ]; then
  tar czf "$ANORL_ROOT/anorl_results_$stamp.tar.gz" attacks
else
  tar czf "$ANORL_ROOT/anorl_results_$stamp.tar.gz" attacks/*.result.json
fi
n=$(ls attacks/*.result.json 2>/dev/null | wc -l)
echo "packed $n results into $ANORL_ROOT/anorl_results_$stamp.tar.gz"
