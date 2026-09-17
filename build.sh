#!/usr/bin/env bash
# Build the AnoRL mix simulator.  Keeps the source here and links it into ns-3's scratch
# directory, so ns-3 stays a stock checkout and nothing outside anorl-mixsim/ is modified.
set -e
NS3="${NS3_DIR:-$HOME/ns3/ns-3.48}"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$NS3/ns3" ]; then
  echo "ns-3 not found at $NS3 — set NS3_DIR"; exit 1
fi
mkdir -p "$NS3/scratch"
ln -sf "$HERE/src/anorl-mix.cc" "$NS3/scratch/anorl-mix.cc"
cd "$NS3"
./ns3 build anorl-mix 2>&1 | tail -30
echo "built: $NS3/build/scratch/ns3.48-anorl-mix-optimized"
