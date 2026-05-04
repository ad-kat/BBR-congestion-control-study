# BBR Under Mixed Workloads: Characterizing Short-Flow Latency and a Targeted Pacing Gain Improvement

**CSE 534 — Fundamentals of Computer Networks, Stony Brook University**

**Team:** Adri Katyayan (117353314) · Mehtaab Naazneen Mohammed (117376528)

---

## What This Is

BBR (Bottleneck Bandwidth and RTT) is Google's TCP congestion control algorithm, handling an estimated 40% of global Internet traffic. It's great at bulk throughput. It's less great at not bulldozing short-lived "mice" flows sharing the same bottleneck — turns out deliberately probing at 1.25x your link capacity leaves a standing queue that latency-sensitive flows have to wait behind. Shocking, truly.

This project empirically characterizes how bad that is, then proposes a fix: reduce the ProbeBW probe-up gain from 1.25x down to 1.10–1.20x as a kernel-level module swap. We measure the FCT vs. throughput tradeoff so you can decide if it's worth it. Extends Cao et al. (IMC 2019).

The experiment orchestration layer is called **MiceWatch**.

---

## Repository Structure

```
BBR-congestion-control-study/
  scripts/
    topology.py               # Mininet dumbbell topology builder
    run_phase1.sh             # Phase 1 sweep runner
    plot_phase1.py            # Phase 1 figures
    phase2_experiment.py      # Mixed workload characterization
    phase2_analysis.py        # Phase 2 figures + stats
    phase3_experiment.py      # Gain variant sweep (MiceWatch core)
    phase3_analysis.py        # Phase 3 figures + tradeoff curve
  modules/
    tcp_bbr_base.c            # Unmodified BBRv1 source (WSL2 kernel)
    tcp_bbr_gain110.c         # probe-up gain = 1.10x, CCA name: bbr_mod
    tcp_bbr_gain115.c         # probe-up gain = 1.15x, CCA name: bbr_mod115
    tcp_bbr_gain120.c         # probe-up gain = 1.20x, CCA name: bbr_mod120
    tcp_bbr_gain110.ko        # compiled kernel module
    tcp_bbr_gain115.ko        # compiled kernel module
    tcp_bbr_gain120.ko        # compiled kernel module
    Makefile
  docs/
    Project_Proposal.pdf
    build_module.md           # Full kernel module build guide (WSL2)
  references/
    papers.md
  results/
    phase1/                   # COMPLETE
    phase2/bbrv1/             # COMPLETE
    phase2/figures/
    phase3/gain_1.10/         # COMPLETE
    phase3/gain_1.15/         # COMPLETE
    phase3/gain_1.20/         # COMPLETE
    phase3/figures/
```

---

## Environment

| Item | Detail |
|------|--------|
| OS | WSL2, Ubuntu, kernel 6.6.87.2-microsoft-standard-WSL2 |
| Mininet | 2.3.0 |
| Python | 3.12 |
| iperf3 | 3.16 |
| Virtualenv | `bbrenv` |
| Working dir | `~/bbr-project` (symlink → `~/BBR congestion ctrl/BBR-congestion-control-study`) |

> **Note:** The space in the real path breaks `make`. Always use the symlink `~/bbr-project` for module build commands.

---

## Phases

### Phase 1 — Baseline Reproduction ✅ COMPLETE

Replicated Cao et al. (IMC 2019) Figure 2. BBR vs. CUBIC bulk throughput sweep across 5 buffer sizes at 100 Mbps / 40 ms RTT. Validates our tc/Mininet setup is not lying to us.

### Phase 2 — Mixed Workload Characterization ✅ COMPLETE

One 120s BBR elephant flow + 10 sequential 1 MB mice flows. Swept:
- Buffer sizes: 10 KB, 200 KB, 10 MB
- RTTs: 10, 40, 100 ms
- 9 configurations total

**Key findings:**

| Buffer | Mean FCT (10ms RTT) | JFI | Elephant Goodput |
|--------|-------------------|-----|-----------------|
| 10 KB  | 12.2s             | 0.265 | 84.5 → 5.9 → 2.3 Mbps |
| 200 KB | 1.23s             | ~1.0  | Stable |
| 10 MB  | 1.24s             | ~1.0  | Stable |

Hard cliff between 10 KB and 200 KB. BBR's 1.25x probe-up fills shallow buffers and starves mice. Turns out that's bad.

> BBRv3 skipped entirely — not available on WSL2 kernel 6.6.87. Documented as platform limitation.

### Phase 3 — Pacing Gain Modification ✅ COMPLETE

The novel contribution. Three custom kernel modules with reduced probe-up gain (1.10x, 1.15x, 1.20x). Full Phase 2 sweep re-run per variant. Produces an FCT vs. throughput tradeoff curve to guide real deployment choices.

**Hypothesis:** 1.10x gain cuts mice FCT 15–30% with under 5% elephant throughput loss.

**Output figures:** tradeoff curve, FCT vs. gain, goodput vs. gain, fairness vs. gain, FCT CDF at 10 KB buffer, heatmap grid by gain variant.

---

## Quickstart

```bash
# Clone and set up
git clone <REPO_URL> BBR-congestion-control-study
cd BBR-congestion-control-study
python3 -m venv bbrenv
source bbrenv/bin/activate
pip install numpy matplotlib pandas seaborn

# Enable BBR
sudo modprobe tcp_bbr

# Phase 2
sudo python3 scripts/phase2_experiment.py
python3 scripts/phase2_analysis.py

# Phase 3 (modules must be loaded first)
cd modules/
sudo insmod tcp_bbr_gain110.ko
sudo insmod tcp_bbr_gain115.ko
sudo insmod tcp_bbr_gain120.ko
cd ..
sudo python3 scripts/phase3_experiment.py
python3 scripts/phase3_analysis.py
```

> All experiment scripts require `sudo`. This is not negotiable — Mininet needs it.

---

## Known Quirks

- **`[ERROR] Experiment exploded: unsupported format string passed to NoneType`** — iperf3 race condition, elephant goodput is None. FCT data is still valid. Analysis handles it. Not a real error, just dramatic logging.
- **`sch_htb: quantum of class 50001 is big`** — harmless kernel warning. Ignore it like the rest of us do.
- **BBRv3 unavailable** — WSL2 kernel 6.6.87 does not ship a BBRv3 module. Documented limitation.
- **Space in project path** — `~/BBR congestion ctrl/` breaks `make`. Use symlink `~/bbr-project` always.

---

## Building Kernel Modules (optional)

See `docs/build_module.md` for the full guide. Requires cloning WSL2 kernel source at tag `linux-msft-wsl-6.6.87.2` and building headers + `Module.symvers` before the external module build works.

```bash
make KDIR=~/wsl2-kernel
```

Pre-compiled `.ko` files are included in `modules/` so most users won't need this.

---

## Related Work

- Cardwell et al. (CACM 2017) — original BBR paper
- **Cao et al. (IMC 2019, Stony Brook)** — primary paper this work extends
- Ware et al. (IMC 2019, CMU) — analytical model of BBR unfairness
- Scherrer et al. (IMC 2022, ETH Zurich) — fluid models proving BBR standing queue > 1.5 BDP
- BBR-GC, BBR-EFRA, BBR-R — related gain modifications (target RTT fairness, not mice FCT)

---

## Topology

```
h1 (elephant, BBR) ──┐
                      ├── s1 ══[bottleneck]══ s2 ── h3 (receiver)
h2 (mice, BBR/CUBIC)─┘

Bottleneck: 100 Mbps, RTT controlled via netem, buffer via HTB
```

---

*MiceWatch — because someone had to watch out for the mice.*