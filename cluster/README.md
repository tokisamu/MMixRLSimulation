# Running the attack grid on the RPTU cluster

216 independent simulations: two mobility traces (`march`, `chain`), four layer counts
(3 to 6), five adversary ratios (0 to 0.4), three seeds, for two separated attacks (droppers,
corrupted mixes). Each simulation is one single-core SLURM array task.

Every command below that touches the cluster runs under your own login. Nothing here asks
for, stores or types your password.

## What the cluster needs

| requirement | why |
|---|---|
| g++ 11.1 or later, or clang 17 or later | ns-3.48 is C++23 |
| CMake 3.25 or later | ns-3.48's build files |
| Python 3.10 or later | ns-3.48's `./ns3` build wrapper |
| numpy 1.17 or later | scenario generation and analysis (the build script installs it in a venv if missing) |
| about 3 GB free | ns-3 source and build about 0.5 GB, results and event logs about 2 GB |

Put the unpacked directory on a filesystem with that much space. If your home quota is
small, use your site's work or scratch filesystem instead.

## Steps

**1. On your laptop, build the package.**

```bash
anorl-mixsim/cluster/pack.sh
```

This writes `anorl-mixsim/dist/anorl-cluster.tar.gz`, about 48 MB: the simulator source,
the scripts, the two Amigo traces and the ns-3 source tarball, so the build does not need
the cluster to reach the internet.

**2. Copy it to the cluster and unpack it.**

```bash
scp anorl-mixsim/dist/anorl-cluster.tar.gz ram25law@elwe1.rz.rptu.de:<directory with 3 GB free>/
```

Then, logged in on the cluster:

```bash
cd <that directory>
tar xzf anorl-cluster.tar.gz
cd anorl-cluster
```

**3. Find suitable modules.**

```bash
module avail gcc cmake python
```

Pick a GCC of at least 11.1, a CMake of at least 3.25 and a Python of at least 3.10.

**4. Build ns-3 and the simulator.** About 15 to 30 minutes.

```bash
anorl-mixsim/cluster/build_ns3.sh --gcc-module <gcc> --cmake-module <cmake> --python-module <python> --jobs 4
```

If your site does not allow builds on login nodes, first open an interactive session, for
example `srun --pty -c 8 --time=01:00:00 bash`, and pass `--jobs 8`.

The script checks every version above, builds with the release profile and without
`-march=native`, so the binary runs on compute nodes whose CPUs differ from the build node's,
writes `env.sh` recording exactly which modules and environment the jobs must use, and
confirms the binary starts.

**5. Verify the experiment design with this cluster's numpy.**

```bash
source env.sh
python3 anorl-mixsim/cluster/verify_design.py
```

It must end with `ALL CHECKS PASS`. It checks that the no-attack control is shared by both
attacks, that every honest participant sends the same messages at every ratio, that the
adversary sets are nested, and that droppers and corrupted mixes have the right roles.

**6. Choose a partition.**

```bash
sinfo -s
sacctmgr show assoc user=$USER format=account,partition,qos
```

Pass `--account` in the next step only if your site requires one.

**7. Dry run, then submit.**

```bash
anorl-mixsim/cluster/submit.sh --partition <partition> --dry-run
anorl-mixsim/cluster/submit.sh --partition <partition>
```

All 216 simulations go in as one job array, and the scheduler decides how many run at once.
Each task requests one core, 4 GB and a 12-hour time limit; a simulation uses well under
1 GB. Change the limit with `--time`.

Measured on the laptop, with eight simulations sharing ten cores:

| job | wall time |
|---|---|
| corrupted mixes at 0.3 or 0.4 on chain, 3 to 6 layers | 52 to 54 min, more for 6 layers at 0.4 |
| droppers at 0.4 on march, 3 layers | 9 min |

Cluster runtimes depend on its CPUs, so the 12-hour limit leaves a wide margin. Once a first
batch has finished, `sacct -X -j <job id> --format=JobID,Elapsed,State` shows the real
runtimes, and `--time` lets you tighten the limit, which usually gets jobs scheduled sooner.

**8. Watch progress.**

```bash
squeue -u $USER
python3 anorl-mixsim/cluster/missing.py
```

`missing.py` counts finished results and prints the indices still missing as an array spec.
A job counts as finished only when its event log carries the end-of-run marker and its result
file exists.

**9. Resubmit anything that failed or hit its time limit.**

```bash
anorl-mixsim/cluster/submit.sh --partition <partition> --indices "$(python3 anorl-mixsim/cluster/missing.py 2>/dev/null)" --time 24:00:00
```

**10. Bring the results home.**

On the cluster:

```bash
anorl-mixsim/cluster/collect.sh
```

On your laptop:

```bash
scp ram25law@elwe1.rz.rptu.de:<directory>/anorl-cluster/anorl_results_*.tar.gz anorl-mixsim/dist/
mkdir -p anorl-mixsim/results/cluster && tar xzf anorl-mixsim/dist/anorl_results_*.tar.gz -C anorl-mixsim/results/cluster
ANORL_OUT=anorl-mixsim/results/cluster/attacks python3 anorl-mixsim/analysis/aggregate_attacks.py --figdir anorl-mixsim/figures/cluster
```

## Do not mix cluster and laptop results

numpy's random generators and a CPU-tuned ns-3 build can both give different draws on
different machines. Averaging within one machine's runs is sound; averaging cluster runs with
laptop runs is not, because the paired design would silently break. Every result file records
the Python version, numpy version, host and ns-3 binary it came from, so this can be checked.

## Files

| file | role |
|---|---|
| `pack.sh` | laptop: builds the package |
| `build_ns3.sh` | cluster: checks the toolchain, builds ns-3 and the simulator, writes `env.sh` |
| `verify_design.py` | cluster: checks the experiment design before submitting |
| `jobs.tsv` | the 216 jobs, one line each, indexed for the job array |
| `submit.sh` | cluster: submits the job array, or resubmits given indices |
| `task.slurm` | one array task: generates, simulates, analyses, writes one result |
| `run_one.py` | the per-job entry point `task.slurm` calls |
| `missing.py` | lists unfinished jobs |
| `collect.sh` | bundles finished results for copying back |
