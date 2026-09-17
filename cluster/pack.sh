#!/bin/bash
# Run locally.  Builds anorl-cluster.tar.gz holding everything the cluster needs and nothing
# it does not: the simulator source, the scripts, the two Amigo traces, and the ns-3 source
# tarball so the build does not depend on the cluster reaching the internet.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SIM="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SIM/.." && pwd)"
NS3_TARBALL="${NS3_TARBALL:-$HOME/ns3/ns-3.48.tar.bz2}"
OUT="${1:-$SIM/dist/anorl-cluster.tar.gz}"   # kept inside anorl-mixsim, never at the repo root
mkdir -p "$(dirname "$OUT")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/anorl-cluster/anorl-mixsim/scenarios" "$STAGE/anorl-cluster/amigo_copy"
cp -R "$SIM/src" "$SIM/analysis" "$SIM/cluster" "$STAGE/anorl-cluster/anorl-mixsim/"
cp "$SIM/run_attacks.py" "$SIM/README.md" "$STAGE/anorl-cluster/anorl-mixsim/"
cp "$SIM/scenarios/gen_scenario.py" "$STAGE/anorl-cluster/anorl-mixsim/scenarios/"
for t in march chain gather blockade1; do
  if [ -f "$REPO/amigo_copy/${t}_node250_0.npy" ]; then
    cp "$REPO/amigo_copy/${t}_node250_0.npy" "$STAGE/anorl-cluster/amigo_copy/"
  else
    echo "warning: no Amigo trace for $t"
  fi
done
if [ -f "$NS3_TARBALL" ]; then cp "$NS3_TARBALL" "$STAGE/anorl-cluster/"; else echo "warning: no ns-3 tarball at $NS3_TARBALL; the cluster must download it"; fi
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '.DS_Store' -delete
tar -C "$STAGE" -czf "$OUT" anorl-cluster
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
tar -tzf "$OUT" | sed 's#^anorl-cluster/##' | grep -vE '/$' | sort | sed 's/^/  /'
