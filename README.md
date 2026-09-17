# AnoRL mix-network simulator

Anonymity and delay of the AnoRL mix network over the Amigo protest-mobility traces, in
ns-3. This directory is self-contained: it reads the Amigo arrays in `../amigo_copy/` and
writes only inside itself. Nothing outside `anorl-mixsim/` is modified.

## What is measured

**Anonymity entropy**, by the method of Iness Ben Guirat and Claudia Diaz, *Mixnet
optimization methods*, PoPETs 2022(3):456–477, doi 10.56553/popets-2022-0081. A target
input message is fixed, every message carries the probability that it is the target, and a
mix releasing a message hands it an even share of the probability mass in its pool. Their
Equation (15) is the un-normalised Shannon entropy of the resulting distribution over the
mixnet's outputs, in bits:

    H = - sum_i Pr_L[m_i = m_t] log2 Pr_L[m_i = m_t]

Their Algorithm 1 is reproduced exactly in `analysis/entropy.py`, including the detail that
the pool includes the departing message. Entropy is computed per target and averaged over
200 targets, as they do, and is **not** normalised by log2(N), as they do not.

**End-to-end delay**, from the client's origination to the last mix's broadcast.

## Setup

| parameter | value |
|---|---|
| participants | 250, from the Amigo trace |
| mixes | 10% of participants, drawn uniformly, fixed for the run |
| path | a uniformly random sequence of `L` distinct mixes, drawn per message (free route) |
| layers `L` | 3, 4, 5, 6 |
| client rate | 10 messages per participant per minute, Poisson |
| client budget | 10 tokens per 60 s slot |
| mix budget | `n` times the client budget, i.e. 2500 tokens per slot |
| mix delay | exponential, mean 5 s, sampled per hop |
| radio | 802.11n ad-hoc, HtMcs7, 40 MHz, 5 GHz, `RangePropagationLossModel` |
| range | 10 m |
| packet | 1024 bytes on the air |

Budgets are enforced per node per slot exactly as the protocol specifies: a node whose
budget is exhausted **holds** the packet until the next slot rather than dropping it.

## Which mobility trace

The Amigo traces each keep all 250 nodes inside a 7 m square for the first ~634 s, which is
a staging area and not a mobile ad-hoc network. `gen_scenario.py` detects that and re-bases
time to the first second after the crowd disperses. Connectivity of the radio graph at 10 m
then differs sharply between traces:

| trace | area | mean degree at 10 m | components at 10 m |
|---|---|---|---|
| `chain` | 423 × 250 m | 8.3 | 1 (connected) |
| `march` | 16 × 2400 m corridor | 111 | 1 |
| `gather` | 16 × 16 m | 162 | 1 |
| `blockade1` | 338 × 309 m | 6.6 | 29 (needs ~30 m to connect) |

Two traces are reported, at the same 10 m range, because they isolate different effects.

`chain` is connected, sparse and long: mean degree 8.2, diameter 60 hops, paths averaging
20.1 hops. It is also **completely static** after the crowd forms, with zero node movement
for the rest of the trace, so it measures a multi-hop wireless network but not a mobile
one.

`blockade1` is the mobile case: nodes move at 1.97 m/s and 6.2% of links change every
second. At 10 m it splits into 14 components and only 40.8% of (node, mix) pairs are in
the same component at any instant, but **every mix becomes reachable from every node
within a 120 s window**, so mobility itself bridges the partitions and delay-tolerant
carrying is what makes the scenario work.

`march` (mobile at 1.31 m/s, degree 104, 1.6-hop legs) and `gather` (nearly stationary in a
16 m square, degree 161, two-hop diameter) are both dense and connected. They are reported
because together with `chain` they show that neither topology nor mobility changes the
result as long as the network is connected.

## Transport

Between two mixes a packet crosses the mesh. Two modes:

* `--transport route` (default) — unicast along a shortest path over the current radio
  graph, recomputed once a simulated second. This gives the dissemination layer perfect
  neighbour knowledge, which is the paper's position that how retransmission is organised
  is orthogonal to the token layer. The MAC, the contention, the queueing and the losses
  are still ns-3's. A node with no path to the addressed mix holds the packet and retries,
  which is what a delay-tolerant node does under mobility, but only for as long as the
  token that paid for the transmission is still verifiable (below).
* `--transport flood` — epidemic dissemination with duplicate suppression and a hop limit,
  which is what the protocol assumes when no routing layer is present. Much more airtime.

The last mix's delivery is a broadcast in both modes.

**Frames the 802.11 ARQ gives up on are re-routed.** A unicast whose next hop walked out of
range between two rebuilds of the routing table is retried seven times by the MAC and then
abandoned, and the sender is never told. On a path averaging twenty hops this silently
loses several per cent of packets for a reason that has nothing to do with the protocol.
The simulator subscribes to the MAC's `DroppedMpdu` trace, recovers the packet, and
re-transmits it after a short pause so the sender can pick a next hop that is in range.
Measured on the `chain` trace at ten messages per participant per minute with three layers:
5,454 frames were abandoned by ARQ and 5,376 of them recovered, and delivery rose from
10,602 to 12,336 of 12,510 messages. `results/preliminary_no_mac_recovery/` keeps the runs
made before this was added; their delivery is lower and far more variable between seeds,
and their entropy is correspondingly understated. Do not quote them.

Packets held because a node's token budget for the slot is exhausted are released at the
next slot boundary plus a uniform stagger of up to one second, so that a slot boundary is
not a synchronised network-wide burst. The held packet spends a fresh token from the new
slot, so per-slot spending stays inside the budget.

## The token acceptance window bounds everything a packet can do

A spend names the slot it was made in, and a receiver accepts only the current or the
immediately preceding slot. The simulator carries that slot in the packet and enforces the
rule in three places, because a packet outside the window can no longer be verified by
anyone:

* a device that receives one drops it without verifying, as in Algorithm 6;
* a node with no route checks whether the token will still verify at its next retry, and
  drops the packet rather than carrying it further if it will not;
* a frame recovered from a MAC failure is checked before it is put back on the air.

This is what bounds store-carry-forward. A node may hold a packet while the network is
partitioned, but never past the life of its token, so the carry budget is a safety cap and
the window is the real limit. Measured on the partitioned trace over 11,229 accepted legs:
none exceeded the 120 s ceiling, the longest was 84.6 s, and 63 ran past 60 s, which are
the carried ones waiting for a partition to merge.

## Validation

`analysis/test_entropy.py` checks Algorithm 1 against six hand-computed cases (two messages
in a pool give exactly 1 bit, four give 2 bits, no overlap gives 0, mass is conserved, a
stuck message leaks exactly its share).

`analysis/validate_against_paper.py` simulates the paper's own stratified mixnet, writes it
in our event-log format, and runs our analysis over it. Reproducing two published
configurations:

| configuration | published | ours |
|---|---|---|
| L=3, W=50, λ_U=100 msg/s, D_e2e=1 s | 2.624 bits | 2.660 ± 0.061 |
| L=3, W=10, λ_U=5000 msg/s, D_e2e=1 s | 13.038 bits | 13.037 ± 0.002 |

A third, independent check comes from the runs themselves: the measured mean pool occupancy
per mix matches the M/M/∞ prediction λμ to within a few percent.

## Two deliberate deviations from the paper, both reported

1. **Free route rather than stratified.** Their mixnet has L layers of W mixes and every
   message crosses one mix per layer. AnoRL draws a random sequence of L distinct mixes.
   The per-mix update is unchanged because it depends only on pool occupancy, and the
   output cut is still well defined because every message crosses exactly L mixes.
2. **Messages are lost.** Their network is lossless, so probability mass is conserved. A
   mobile ad-hoc network loses messages, so mass leaks. We report the surviving mass and
   compute entropy over the delivered outputs renormalised to one, which is the anonymity
   of a target conditioned on the adversary observing it delivered.

Their Section 5.3 notes that variable propagation delay inflates entropy relative to a
constant delay. Ad-hoc delay variance is large and endogenous, so these numbers are not
directly comparable with their figures; they are comparable across our own `L`.

## Running it

```bash
./build.sh                                     # links src/ into $NS3_DIR/scratch and builds
python3 run_sweep.py --model chain --layers 3 4 5 6 --seeds 1 2 3 --jobs 3
python3 analysis/plot_sweep.py results/sweep.json --out figures/entropy_delay.png
```

`build.sh` needs ns-3 3.48 at `$NS3_DIR` (default `~/ns3/ns-3.48`), configured with the
`wifi`, `mobility`, `applications` and `stats` modules.

## Files

| path | role |
|---|---|
| `src/anorl-mix.cc` | the ns-3 simulator |
| `scenarios/gen_scenario.py` | builds `.ns2mobility`, `.scn` and `.json` from an Amigo trace |
| `analysis/entropy.py` | Algorithm 1 and Equation (15) over an event log |
| `analysis/test_entropy.py` | hand-computed unit tests |
| `analysis/validate_against_paper.py` | reproduces published values |
| `analysis/plot_sweep.py` | figures and the summary table |
| `run_sweep.py` | grid driver |
| `results/*.log` | event logs, one line per origination, arrival, departure and delivery |

## Event-log format

```
ORIG  <mid> <t> <node> <hop> <dst>     a token was spent and the packet went on the air
ARR   <mid> <t> <mix>  <hop>           the addressed mix received it
DEP   <mid> <t> <mix>  <hop>           the mix delay expired and it was released
DELIV <mid> <t> <mix>  <e2e>           the last mix broadcast the payload
```

Everything the analysis needs is derivable from arrival and departure times, which is what
a network observer sees; no field that an observer could not obtain is used.
