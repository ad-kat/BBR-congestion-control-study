#!/usr/bin/env python3
"""
plot_phase1.py — Reads iperf3 JSON output from run_phase1.sh and
produces a throughput-vs-buffer-size plot replicating Cao et al. IMC 2019 Figure 2.

Run after run_phase1.sh finishes. Results must be in results/phase1/.
If they're not there, you haven't run the experiments yet. Classic.
"""
'''
Why our plot doesn't match it properly (fig 8a of cao et al.)

Because:
--Their x-axis is log scale (10⁴ to 10⁷ bytes) — ours is categorical
--Their setup is 1 Gbps, 20ms RTT — ours is 100 Mbps, 40ms RTT
--They show BBR + CUBIC + Total simultaneously (fairness/coexistence 
experiment) — ours shows them separately as bulk flows
--Their buffer range goes to 100MB — ours stops at 10MB

So our plot doesn't cleanly replicate any single figure from the paper. 
What we actually reproduced is closest to the Section 4.1 narrative — 
the general finding that BBR handles shallow buffers better than CUBIC — 
but not any specific figure's exact setup.


'''

import json
import os
import sys
import glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── Config ────────────────────────────────────────────────────────────────────
RESULTS_DIR = "results/phase1"
OUTPUT_PLOT  = "results/phase1/figure2_replica.pdf"

# Must match the buffer sizes in run_phase1.sh, in the same order.
# If you changed them there, change them here. Consistency: not optional.
BUFFER_SIZES_KB = [10, 50, 200, 1024, 10240]
BUFFER_LABELS   = ["10 KB", "50 KB", "200 KB", "1 MB", "10 MB"]

CCA_STYLES = {
    "bbr":   {"color": "#185FA5", "marker": "o", "label": "BBR"},
    "cubic": {"color": "#A32D2D", "marker": "s", "label": "CUBIC"},
}
# ──────────────────────────────────────────────────────────────────────────────


def parse_iperf3_json(filepath: str) -> float:
    """
    Extract mean throughput (Mbps) from an iperf3 JSON file.
    iperf3 buries the summary in end.sum_received.bits_per_second.
    Because nothing can ever just be at the top level.

    Returns mean throughput in Mbps, or NaN on parse failure.
    """
    try:
        with open(filepath) as f:
            data = json.load(f)

        # bits_per_second → Mbps
        bps = data["end"]["sum_received"]["bits_per_second"]
        return bps / 1e6

    except (KeyError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  [!] Failed to parse {filepath}: {e}")
        return float('nan')


def load_results() -> dict:
    """
    Load all iperf3 results into a dict keyed by (cca, buf_kb).
    If a result file is missing, it gets NaN and a gentle shame message.
    """
    results = {}
    for cca in CCA_STYLES:
        for buf_kb in BUFFER_SIZES_KB:
            fname = os.path.join(RESULTS_DIR, f"{cca}_buf{buf_kb}kb.json")
            tput  = parse_iperf3_json(fname)
            results[(cca, buf_kb)] = tput
            status = f"{tput:.2f} Mbps" if not np.isnan(tput) else "MISSING"
            print(f"  {cca:6s} buf={buf_kb:6d} KB → {status}")
    return results


def plot_figure2(results: dict) -> None:
    """
    Produce the throughput vs. buffer size plot.
    Target: match the visual structure of Cao et al. Fig. 2 closely enough
    that someone who has read the paper goes "yeah, that looks right."
    """
    fig, ax = plt.subplots(figsize=(6, 4))

    x = np.arange(len(BUFFER_SIZES_KB))   # categorical x-axis

    for cca, style in CCA_STYLES.items():
        y = [results.get((cca, buf), float('nan')) for buf in BUFFER_SIZES_KB]
        ax.plot(
            x, y,
            color=style["color"],
            marker=style["marker"],
            linewidth=1.8,
            markersize=6,
            label=style["label"],
        )

    # ── Axes & labels ─────────────────────────────────────────────────────────
    ax.set_xticks(x)
    ax.set_xticklabels(BUFFER_LABELS, fontsize=9)
    ax.set_xlabel("Buffer Size", fontsize=10)
    ax.set_ylabel("Throughput (Mbps)", fontsize=10)
    ax.set_title("Throughput vs. Buffer Size — BBR vs. CUBIC\n(Reproducing Cao et al. IMC 2019 §4.1 / Fig. 8a behavior)", fontsize=10)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.grid(axis='y', linestyle='--', linewidth=0.5, alpha=0.6)
    ax.grid(axis='y', which='minor', linestyle=':', linewidth=0.3, alpha=0.4)

    # Spine cleanup — journals hate chartjunk and so do we
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    ax.legend(fontsize=9, frameon=False)

    # Annotate link capacity so reviewers don't ask "what was the bandwidth"
    ax.axhline(y=100, color='gray', linestyle=':', linewidth=1, alpha=0.7)
    ax.text(len(BUFFER_SIZES_KB) - 0.05, 101, '100 Mbps link', fontsize=8,
            color='gray', ha='right', va='bottom')

    fig.tight_layout()
    os.makedirs(os.path.dirname(OUTPUT_PLOT), exist_ok=True)
    fig.savefig(OUTPUT_PLOT, dpi=300, bbox_inches='tight')
    print(f"\n[+] Plot saved: {OUTPUT_PLOT}")
    print("[+] If BBR flatlines near 100 Mbps and CUBIC dips at small buffers,")
    print("    you've reproduced Fig. 2. Congratulations, the tc setup works.")


def main():
    if not os.path.isdir(RESULTS_DIR):
        print(f"[!] Results directory not found: {RESULTS_DIR}")
        print("[!] Run run_phase1.sh first. The plot can't manifest data from nothing.")
        sys.exit(1)

    print("[*] Loading Phase 1 results...")
    results = load_results()

    missing = sum(1 for v in results.values() if np.isnan(v))
    if missing > 0:
        print(f"\n[!] {missing} result(s) are missing. Plot will have gaps.")
        print("[!] Re-run run_phase1.sh for the missing configurations.")

    print("\n[*] Plotting Figure 2 replica...")
    plot_figure2(results)


if __name__ == '__main__':
    main()
