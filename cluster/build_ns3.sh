#!/bin/bash
# Build ns-3 and the AnoRL simulator on the cluster, and write env.sh for the jobs.
#
#   cluster/build_ns3.sh [--gcc-module NAME] [--cmake-module NAME] [--python-module NAME] [--jobs N]
#
# Run from the unpacked anorl-cluster directory on a login node (or inside an interactive
# `srun` session if your site asks that builds not run on login nodes).  Modules are only
# loaded if you name them; otherwise the toolchain already on PATH is checked, and if it is
# too old the script lists the candidate modules and stops.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ANORL_ROOT="$(cd "$HERE/../.." && pwd)"
GCC_MOD=""; CMAKE_MOD=""; PY_MOD=""; JOBS=4
while [ $# -gt 0 ]; do
  case "$1" in
    --gcc-module)    GCC_MOD="$2"; shift 2;;
    --cmake-module)  CMAKE_MOD="$2"; shift 2;;
    --python-module) PY_MOD="$2"; shift 2;;
    --jobs)          JOBS="$2"; shift 2;;
    *) echo "unknown option $1"; exit 2;;
  esac
done
say () { printf '\n== %s\n' "$*"; }

# make `module` usable in a non-login shell, without tripping set -u inside site scripts
init_modules () {
  type module >/dev/null 2>&1 && return 0
  set +u
  for f in /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash \
           /usr/share/Modules/init/bash; do
    [ -f "$f" ] && source "$f" && break
  done
  set -u
  type module >/dev/null 2>&1
}

LOADS=()
if [ -n "$GCC_MOD$CMAKE_MOD$PY_MOD" ]; then
  init_modules || { echo "no module system found, but a module was requested"; exit 1; }
  for m in $GCC_MOD $CMAKE_MOD $PY_MOD; do
    say "module load $m"
    set +u; module load "$m"; set -u
    LOADS+=("$m")
  done
fi

candidates () {
  if init_modules; then
    echo "candidate modules on this cluster:"
    set +u; module -t avail 2>&1 | grep -iE '^(gcc|gnu|cmake|python|anaconda|miniconda|miniforge)' | sort -u | sed 's/^/    /'; set -u
    echo "rerun with, for example:  cluster/build_ns3.sh --gcc-module <gcc> --cmake-module <cmake> --python-module <python>"
  fi
}

say "checking the toolchain"
# ns-3.48 needs g++ 11.1 or clang 17, CMake 3.25, and Python 3.10 for its ./ns3 build wrapper
command -v python3 >/dev/null || { echo "python3 not found"; candidates; exit 1; }
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "python3 $(python3 --version 2>&1 | cut -d' ' -f2) is older than 3.10, which ns-3.48's build wrapper requires"
  candidates; exit 1
fi
echo "python3 $(python3 --version 2>&1 | cut -d' ' -f2) ok"
command -v cmake >/dev/null || { echo "cmake not found"; candidates; exit 1; }
CMV=$(cmake --version | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
python3 - "$CMV" <<'PY' || { echo "cmake $CMV is older than 3.25, which ns-3.48 requires"; candidates; exit 1; }
import sys
M, m = (int(x) for x in sys.argv[1].split("."))
sys.exit(0 if (M, m) >= (3, 25) else 1)
PY
echo "cmake $CMV ok"
CXX="${CXX:-g++}"
command -v "$CXX" >/dev/null || { echo "$CXX not found"; candidates; exit 1; }
echo "compiler: $($CXX --version | head -1)"
CXXV="$("$CXX" -dumpfullversion -dumpversion 2>/dev/null | head -1)"
if "$CXX" --version 2>/dev/null | grep -qi clang; then CXXKIND=clang; else CXXKIND=gcc; fi
if ! python3 - "$CXXKIND" "$CXXV" <<'PY'
import sys
kind, ver = sys.argv[1], sys.argv[2]
parts = [int(x) for x in (ver.split(".") + ["0", "0"])[:2]]
need = (17, 0) if kind == "clang" else (11, 1)
sys.exit(0 if tuple(parts) >= need else 1)
PY
then
  echo "$CXXKIND $CXXV is too old: ns-3.48 needs g++ 11.1 or later, or clang 17 or later"
  candidates; exit 1
fi
echo "$CXXKIND $CXXV ok"
probe="$(mktemp -d)"
printf '#include <optional>\n#include <string_view>\nint main(){ std::optional<int> x = 1; return *x - 1; }\n' > "$probe/p.cc"
if ! "$CXX" -std=c++23 "$probe/p.cc" -o "$probe/p" 2>/dev/null && \
   ! "$CXX" -std=c++2b "$probe/p.cc" -o "$probe/p" 2>/dev/null; then
  rm -rf "$probe"
  echo "$CXX cannot compile C++23, which ns-3.48 requires; load a newer GCC module"
  candidates; exit 1
fi
rm -rf "$probe"
echo "C++23 ok"

say "checking Python and numpy"
command -v python3 >/dev/null || { echo "python3 not found"; candidates; exit 1; }
PYOK=$(python3 -c 'import numpy,sys; v=tuple(int(x) for x in numpy.__version__.split(".")[:2]); print(1 if v>=(1,17) else 0)' 2>/dev/null || echo 0)
VENV=""
if [ "$PYOK" != 1 ]; then
  say "numpy missing or older than 1.17: creating a virtual environment"
  python3 -m venv "$ANORL_ROOT/venv"
  "$ANORL_ROOT/venv/bin/pip" install --quiet --upgrade pip || true
  if ! "$ANORL_ROOT/venv/bin/pip" install --quiet 'numpy>=1.17'; then
    echo "could not install numpy (no internet from this node?). Load a Python module that ships numpy."
    candidates; exit 1
  fi
  VENV="$ANORL_ROOT/venv"
  source "$VENV/bin/activate"
fi
echo "python $(python3 --version 2>&1 | cut -d' ' -f2), numpy $(python3 -c 'import numpy;print(numpy.__version__)')"

say "unpacking ns-3.48"
cd "$ANORL_ROOT"
if [ ! -d ns-3.48 ]; then
  if [ -f ns-3.48.tar.bz2 ]; then
    tar xjf ns-3.48.tar.bz2
  else
    curl -fL -o ns-3.48.tar.bz2 https://www.nsnam.org/releases/ns-3.48.tar.bz2 && tar xjf ns-3.48.tar.bz2
  fi
fi

say "configuring: release profile, no CPU-specific tuning"
# the optimized profile adds -march=native, which would build for the login node's CPU and can
# crash with an illegal instruction on compute nodes that have a different one
cd "$ANORL_ROOT/ns-3.48"
./ns3 configure --build-profile=release \
  --enable-modules=wifi,mobility,applications,stats --disable-examples --disable-tests \
  -- -DNS3_NATIVE_OPTIMIZATIONS=OFF

say "building the simulator"
mkdir -p scratch
ln -sf "$ANORL_ROOT/anorl-mixsim/src/anorl-mix.cc" scratch/anorl-mix.cc
./ns3 build -j "$JOBS" anorl-mix
# ns-3 adds a profile suffix to scratch binaries for some profiles, such as
# ns3.48-anorl-mix-optimized, and none for the release profile, which gives ns3.48-anorl-mix.
# Accept both, without ls, so a missing match cannot abort the script under set -e.
BIN=""
for c in "$ANORL_ROOT"/ns-3.48/build/scratch/ns3.48-anorl-mix "$ANORL_ROOT"/ns-3.48/build/scratch/ns3.48-anorl-mix-*; do
  if [ -f "$c" ] && [ -x "$c" ]; then BIN="$c"; break; fi
done
[ -n "$BIN" ] || { echo "build finished but no binary was found in $ANORL_ROOT/ns-3.48/build/scratch"; exit 1; }
if grep -qE -- '-march=native' "$ANORL_ROOT/ns-3.48/cmake-cache/CMakeCache.txt" 2>/dev/null \
   && grep -qE '^NS3_NATIVE_OPTIMIZATIONS:BOOL=ON' "$ANORL_ROOT/ns-3.48/cmake-cache/CMakeCache.txt"; then
  echo "native CPU tuning is still on: refusing, the binary would not be portable"; exit 1
fi
echo "built $BIN"

say "writing $ANORL_ROOT/env.sh"
{
  echo "# written by cluster/build_ns3.sh on $(hostname) at $(date)"
  echo '_anorl_u=0; case $- in *u*) _anorl_u=1; set +u;; esac'
  if [ ${#LOADS[@]} -gt 0 ]; then
    echo 'if ! type module >/dev/null 2>&1; then'
    echo '  for f in /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash /usr/share/Modules/init/bash; do [ -f "$f" ] && source "$f" && break; done'
    echo 'fi'
    for m in "${LOADS[@]}"; do echo "module load $m"; done
  fi
  [ -n "$VENV" ] && echo "source \"$VENV/bin/activate\""
  echo "export LD_LIBRARY_PATH=\"$ANORL_ROOT/ns-3.48/build/lib:\${LD_LIBRARY_PATH:-}\""
  echo '[ "$_anorl_u" = 1 ] && set -u; unset _anorl_u'
} > "$ANORL_ROOT/env.sh"
cat "$ANORL_ROOT/env.sh"

say "smoke test: the binary starts and reads its options"
source "$ANORL_ROOT/env.sh"
"$BIN" --PrintHelp >/dev/null 2>&1 && echo "binary runs" || { echo "the binary does not start on this node"; exit 1; }
echo
echo "build complete.  Next:  python3 $ANORL_ROOT/anorl-mixsim/cluster/verify_design.py"
