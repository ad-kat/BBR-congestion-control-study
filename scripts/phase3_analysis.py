#!/usr/bin/env python3
"""
phase3_analysis.py
CSE 534 - BBR Under Mixed Workloads: Phase 3 Analysis
Authors: Adri Katyayan, Mehtaab Naazneen Mohammed

Reads Phase 3 JSON results (gain variants 1.10, 1.15, 1.20) PLUS the Phase 2 BBRv1
results (gain=1.25 baseline) and produces the core Phase 3 contribution figures:

  Fig 1: FCT vs Throughput tradeoff curve  (the main result)
  Fig 2: Mean mice FCT vs pacing gain  (line plot, one line per buffer size)
  Fig 3: Elephant goodput vs pacing gain  (how much does the elephant suffer?)
  Fig 4: Jain's Fairness vs pacing gain
  Fig 5: FCT CDF comparison — all four gain values, at 10KB buffer (worst case)
  Fig 6: Mean FCT heatmap grid — one subplot per gain variant (buffer x RTT)

Usage:
  python3 phase3_analysis.py
  python3 phase3_analysis.py --phase2-bbrv1-dir results/phase2/bbrv1
                             --phase3-dir results/phase3
                             --out-dir results/phase3/figures

Dependencies: pip install numpy matplotlib pandas seaborn
"""

import json
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns


# ============================================================
# PLOT STYLE — same aesthetic as Phase 2. Consistency. Reviewers notice.
# "Why does your Phase 3 look like a different paper?"  — Reviewer 2, probably
# ============================================================

plt.rcParams.update({
    "font.family":     "serif",
    "font.size":       11,
    "axes.titlesize":  12,
    "axes.labelsize":  11,
    "legend.fontsize": 9,
    "figure.dpi":      150,
    "savefig.dpi":     300,      # advisor WILL zoom in
    "savefig.bbox":    "tight",
    "axes.grid":       True,
    "grid.alpha":      0.3,
})

# Color palette: one color per gain variant + baseline.
# Blue family for modified gains, a stern black for the stock 1.25 baseline.
GAIN_COLORS = {
    1.10: "#1A9850",  # green — the hopeful improvement
    1.15: "#91CF60",  # light green — somewhat hopeful
    1.20: "#D9EF8B",  # yellow-green — marginal improvement territory
    1.25: "#D73027",  # red — the villain (stock BBRv1 baseline)
}

GAIN_LABELS = {
    1.10: "Gain 1.10 (modified)",
    1.15: "Gain 1.15 (modified)",
    1.20: "Gain 1.20 (modified)",
    1.25: "Gain 1.25 (BBRv1 baseline)",
}

# Exact axis values — must match both phase2_experiment.py and phase3_experiment.py
BUFFER_SIZES_BYTES = [10_000, 200_000, 10_000_000]
RTTS_MS            = [10, 40, 100]

BUF_LABELS = {10_000: "10 KB", 200_000: "200 KB", 10_000_000: "10 MB"}
RTT_LABELS = {10: "10 ms", 40: "40 ms", 100: "100 ms"}


# ============================================================
# DATA LOADING
# ============================================================

def load_phase3_results(phase3_base_dir: Path):
    """
    Loads Phase 3 JSON results from results/phase3/gain_1.10/, gain_1.15/, gain_1.20/.
    Tags each result with the gain value it came from (stored in the JSON under 'pacing_gain').

    Skips files with errors and no FCT data — same as Phase 2 loader.
    Returns a flat list of result dicts.
    """
    all_results = []
    gain_dirs   = {
        1.10: phase3_base_dir / "gain_1.10",
        1.15: phase3_base_dir / "gain_1.15",
        1.20: phase3_base_dir / "gain_1.20",
    }

    for gain, dir_path in gain_dirs.items():
        files = list(dir_path.glob("*.json"))
        if not files:
            print(f"[WARN] No results in {dir_path}. Did phase3_experiment.py run for gain={gain}?")
            continue

        print(f"  Loading {len(files)} files from {dir_path}...")
        for f in files:
            try:
                with open(f) as fp:
                    data = json.load(fp)

                # Skip if errored with no FCT data — the experiment died mid-run
                if "error" in data and not data.get("mice_fcts_s"):
                    print(f"    [SKIP] {f.name}: error, no FCT data")
                    continue

                # Stamp the gain in case the JSON doesn't have it (shouldn't happen, but defensively)
                data.setdefault("pacing_gain", gain)
                all_results.append(data)

            except (json.JSONDecodeError, IOError) as e:
                print(f"    [SKIP] {f.name}: {e}")

    return all_results


def load_phase2_baseline(bbrv1_dir: Path):
    """
    Loads Phase 2 BBRv1 results and tags them as gain=1.25 (the stock probe-up value).
    These are the baseline data points on our tradeoff curves.

    We're not re-running Phase 2 — that would be wasteful and also take another hour.
    """
    files = list(bbrv1_dir.glob("*.json"))
    if not files:
        print(f"[WARN] No Phase 2 BBRv1 results in {bbrv1_dir}. "
              f"The baseline will be missing from all plots.")
        return []

    print(f"  Loading {len(files)} Phase 2 baseline files from {bbrv1_dir}...")
    results = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
            if "error" in data and not data.get("mice_fcts_s"):
                continue
            data["pacing_gain"] = 1.25  # tag as baseline gain
            results.append(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"    [SKIP] {f.name}: {e}")

    return results


def results_to_dataframe(results):
    """
    Converts flat list of result dicts to a tidy pandas DataFrame.
    One row per experiment. Derived columns computed here.

    Same structure as Phase 2 DataFrame, with 'pacing_gain' as the new grouping variable.
    """
    rows = []
    for r in results:
        fcts = r.get("mice_fcts_s", [])
        if not fcts:
            continue

        fcts_arr = np.array(fcts)
        queue    = r.get("queue_stats_midpoint", {})

        rows.append({
            "pacing_gain":              r.get("pacing_gain", 1.25),
            "cca":                      r.get("cca", "bbr"),
            "buffer_bytes":             r["buffer_bytes"],
            "rtt_ms":                   r["rtt_ms"],
            "mean_fct_s":               fcts_arr.mean(),
            "median_fct_s":             np.median(fcts_arr),
            "p99_fct_s":                np.percentile(fcts_arr, 99),
            "std_fct_s":                fcts_arr.std(),
            "elephant_goodput_mbps":    r.get("elephant_goodput_mbps"),
            "elephant_retransmissions": r.get("elephant_retransmissions"),
            "jains_fairness":           r.get("jains_fairness"),
            "queue_backlog_pkts":       queue.get("backlog_pkts", np.nan),
            "queue_dropped":            queue.get("dropped", np.nan),
            "_fcts_raw":                fcts,
        })

    df = pd.DataFrame(rows)
    df["buf_label"]   = df["buffer_bytes"].map(BUF_LABELS)
    df["rtt_label"]   = df["rtt_ms"].map(RTT_LABELS)
    df["gain_label"]  = df["pacing_gain"].map(GAIN_LABELS)
    return df


# ============================================================
# PLOT 1: The Main Result — FCT vs Throughput Tradeoff Curve
# This is Figure 1 in the paper. This is why Phase 3 exists.
# ============================================================

def plot_fct_throughput_tradeoff(df, out_dir):
    """
    Scatter/line plot: x-axis = elephant goodput (Mbps), y-axis = mean mice FCT (s).
    Each point is one (gain, buffer, RTT) configuration.
    Points connected by gain value — shows the tradeoff curve as gain decreases.

    Lower gain → further left on x-axis (lower elephant throughput)
                 AND further down on y-axis (lower mice FCT).
    If our hypothesis holds, these move together, revealing the tradeoff.

    This is the plot that goes in the paper abstract if the results cooperate.
    """
    # Need both metrics — drop rows where either is missing
    plot_df = df.dropna(subset=["elephant_goodput_mbps", "mean_fct_s"]).copy()

    fig, ax = plt.subplots(figsize=(8, 6))

    # One set of points+line per buffer size. RTT is encoded in point size.
    markers = {10: "o", 40: "s", 100: "^"}
    sizes   = {10: 60, 40: 90, 100: 120}

    for buf in BUFFER_SIZES_BYTES:
        buf_df = plot_df[plot_df["buffer_bytes"] == buf].copy()
        if buf_df.empty:
            continue

        # Average across RTTs for the connecting line — the "tradeoff spine"
        spine = (
            buf_df.groupby("pacing_gain")[["elephant_goodput_mbps", "mean_fct_s"]]
            .mean()
            .reset_index()
            .sort_values("pacing_gain")  # sort so line goes from 1.10 → 1.25 (improvement→baseline)
        )

        # Draw the connecting line first so scatter points sit on top
        ax.plot(
            spine["elephant_goodput_mbps"],
            spine["mean_fct_s"],
            color="gray", linewidth=0.8, alpha=0.5, zorder=1,
        )

        # Now scatter each (gain, RTT) point individually
        for rtt in RTTS_MS:
            point_df = buf_df[buf_df["rtt_ms"] == rtt]
            if point_df.empty:
                continue

            for _, row in point_df.iterrows():
                ax.scatter(
                    row["elephant_goodput_mbps"],
                    row["mean_fct_s"],
                    color=GAIN_COLORS.get(row["pacing_gain"], "black"),
                    marker=markers[rtt],
                    s=sizes[rtt],
                    zorder=5,
                    label=None,  # we build legend manually below
                )

    # Build legend entries for gain colors (separate from RTT markers)
    for gain in sorted(GAIN_COLORS.keys()):
        ax.scatter([], [], color=GAIN_COLORS[gain], s=80, label=GAIN_LABELS[gain])
    for rtt, marker in markers.items():
        ax.scatter([], [], color="gray", marker=marker, s=60, label=f"RTT = {rtt} ms")

    ax.set_xlabel("Elephant Goodput (Mbps)")
    ax.set_ylabel("Mean Mice FCT (s)")
    ax.set_title("Phase 3: FCT vs Throughput Tradeoff — Pacing Gain Reduction")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    # Annotate gain values at the top of each cluster for readability
    for gain in sorted(GAIN_COLORS.keys()):
        subset = plot_df[plot_df["pacing_gain"] == gain]
        if not subset.empty:
            ax.annotate(
                f"g={gain}",
                xy=(subset["elephant_goodput_mbps"].mean(), subset["mean_fct_s"].mean()),
                fontsize=7, color=GAIN_COLORS[gain],
                ha="center",
                xytext=(0, 8), textcoords="offset points",
            )

    _save(fig, out_dir, "fig1_fct_throughput_tradeoff.pdf")


# ============================================================
# PLOT 2: Mean FCT vs Pacing Gain (line plot per buffer size)
# ============================================================

def plot_fct_vs_gain(df, out_dir):
    """
    Line plot: x-axis = pacing gain (1.10, 1.15, 1.20, 1.25),
               y-axis = mean mice FCT, one line per buffer size, averaged across RTTs.

    This shows whether reducing the gain monotonically improves FCT, and by how much.
    If the lines are flat, our hypothesis is wrong. Publish anyway (kidding).
    """
    # Average across RTTs for a clean per-(gain, buffer) summary
    agg = (
        df.groupby(["pacing_gain", "buffer_bytes"])["mean_fct_s"]
        .mean()
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(7, 5))

    buf_colors = {
        10_000:       "#D73027",  # red — the suffering buffer
        200_000:      "#FC8D59",  # orange — medium buffer
        10_000_000:   "#4575B4",  # blue — the comfortable buffer
    }

    for buf in BUFFER_SIZES_BYTES:
        subset = agg[agg["buffer_bytes"] == buf].sort_values("pacing_gain")
        if subset.empty:
            continue

        ax.plot(
            subset["pacing_gain"],
            subset["mean_fct_s"],
            marker="o", linewidth=2, markersize=7,
            color=buf_colors[buf],
            label=BUF_LABELS[buf],
        )

        # Annotate endpoint values so readers don't have to squint at the y-axis
        for _, row in subset.iterrows():
            ax.annotate(
                f"{row['mean_fct_s']:.2f}s",
                xy=(row["pacing_gain"], row["mean_fct_s"]),
                fontsize=7, ha="left",
                xytext=(4, 0), textcoords="offset points",
            )

    ax.set_xlabel("Pacing Gain (probe-up entry)")
    ax.set_ylabel("Mean Mice FCT (s)")
    ax.set_title("Phase 3: Mean Mice FCT vs Pacing Gain (averaged over RTTs)")
    ax.set_xticks(sorted(df["pacing_gain"].unique()))
    ax.legend(title="Buffer Size")

    _save(fig, out_dir, "fig2_fct_vs_gain.pdf")


# ============================================================
# PLOT 3: Elephant Goodput vs Pacing Gain
# ============================================================

def plot_goodput_vs_gain(df, out_dir):
    """
    Line plot: x-axis = pacing gain, y-axis = elephant goodput.
    Same layout as Figure 2, but the other side of the tradeoff.

    If the elephant loses less than 5% throughput from 1.25→1.10, we've won.
    If it loses 40%, we've just invented a different problem. Either way, publish.
    """
    plot_df = df.dropna(subset=["elephant_goodput_mbps"]).copy()
    agg = (
        plot_df.groupby(["pacing_gain", "buffer_bytes"])["elephant_goodput_mbps"]
        .mean()
        .reset_index()
    )

    buf_colors = {
        10_000:       "#D73027",
        200_000:      "#FC8D59",
        10_000_000:   "#4575B4",
    }

    fig, ax = plt.subplots(figsize=(7, 5))

    for buf in BUFFER_SIZES_BYTES:
        subset = agg[agg["buffer_bytes"] == buf].sort_values("pacing_gain")
        if subset.empty:
            continue

        ax.plot(
            subset["pacing_gain"],
            subset["elephant_goodput_mbps"],
            marker="o", linewidth=2, markersize=7,
            color=buf_colors[buf],
            label=BUF_LABELS[buf],
        )

    # Reference line at link capacity — everything below it is a throughput loss
    ax.axhline(y=100, color="black", linestyle="--", linewidth=0.8, label="Link capacity (100 Mbps)")
    ax.set_xlabel("Pacing Gain (probe-up entry)")
    ax.set_ylabel("Elephant Goodput (Mbps)")
    ax.set_title("Phase 3: Elephant Goodput vs Pacing Gain (averaged over RTTs)")
    ax.set_xticks(sorted(df["pacing_gain"].unique()))
    ax.set_ylim(0, 110)
    ax.legend(title="Buffer Size")

    _save(fig, out_dir, "fig3_goodput_vs_gain.pdf")


# ============================================================
# PLOT 4: Jain's Fairness Index vs Pacing Gain
# ============================================================

def plot_fairness_vs_gain(df, out_dir):
    """
    Line plot: JFI vs pacing gain, one line per buffer size.
    We expect JFI to improve (increase toward 1.0) as gain decreases.
    If the 10KB line jumps from ~0.3 to ~0.8, that's a meaningful story.
    """
    agg = (
        df.dropna(subset=["jains_fairness"])
        .groupby(["pacing_gain", "buffer_bytes"])["jains_fairness"]
        .mean()
        .reset_index()
    )

    buf_colors = {
        10_000:       "#D73027",
        200_000:      "#FC8D59",
        10_000_000:   "#4575B4",
    }

    fig, ax = plt.subplots(figsize=(7, 5))

    for buf in BUFFER_SIZES_BYTES:
        subset = agg[agg["buffer_bytes"] == buf].sort_values("pacing_gain")
        if subset.empty:
            continue

        ax.plot(
            subset["pacing_gain"],
            subset["jains_fairness"],
            marker="o", linewidth=2, markersize=7,
            color=buf_colors[buf],
            label=BUF_LABELS[buf],
        )

    ax.axhline(y=1.0, color="green", linestyle="--", linewidth=0.8, alpha=0.6, label="Perfect fairness")
    ax.set_xlabel("Pacing Gain (probe-up entry)")
    ax.set_ylabel("Jain's Fairness Index")
    ax.set_title("Phase 3: Jain's Fairness vs Pacing Gain")
    ax.set_xticks(sorted(df["pacing_gain"].unique()))
    ax.set_ylim(0, 1.05)
    ax.legend(title="Buffer Size")

    _save(fig, out_dir, "fig4_fairness_vs_gain.pdf")


# ============================================================
# PLOT 5: FCT CDF at 10KB buffer — all four gain values
# The 10KB buffer is where things go wrong, so this is the most interesting panel.
# ============================================================

def plot_fct_cdf_10kb(df, out_dir):
    """
    CDF of individual mouse FCTs at the 10KB buffer, for all four gain variants.
    All RTTs pooled. This is the "smoking gun" figure for the worst-case scenario.

    If the CDF curves shift left as gain decreases, that's our whole argument in one plot.
    If they don't, we reconsider our life choices and reread the BBR paper.
    """
    buf = 10_000  # the shallow buffer that started this whole research direction
    subset = df[df["buffer_bytes"] == buf]

    fig, ax = plt.subplots(figsize=(7, 5))

    for gain in sorted(GAIN_COLORS.keys(), reverse=True):  # 1.25 first, then improvements
        gain_df = subset[subset["pacing_gain"] == gain]
        all_fcts = []
        for fcts in gain_df["_fcts_raw"]:
            all_fcts.extend(fcts)

        if not all_fcts:
            continue

        sorted_fcts = np.sort(np.array(all_fcts))
        cdf = np.arange(1, len(sorted_fcts) + 1) / len(sorted_fcts)

        ax.plot(
            sorted_fcts, cdf,
            label=GAIN_LABELS[gain],
            color=GAIN_COLORS[gain],
            linewidth=2,
        )

    ax.set_xlabel("Mice FCT (s)")
    ax.set_ylabel("CDF")
    ax.set_title("Phase 3: Mice FCT CDF at 10KB Buffer (all RTTs pooled)")
    ax.legend(loc="lower right")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1.05)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    _save(fig, out_dir, "fig5_fct_cdf_10kb.pdf")


# ============================================================
# PLOT 6: FCT Heatmap Grid — one subplot per gain variant
# ============================================================

def plot_fct_heatmaps(df, out_dir):
    """
    Grid of FCT heatmaps (buffer x RTT), one panel per gain variant.
    Shared color scale across all panels so comparisons are visually valid.

    Layout: 1 row x 4 columns (1.10, 1.15, 1.20, 1.25).
    If 1.10 is visually cooler than 1.25, we're done. Paper writes itself.
    """
    gains  = sorted(df["pacing_gain"].unique())
    n      = len(gains)
    vmin   = df["mean_fct_s"].min()
    vmax   = df["mean_fct_s"].max()

    fig, axes = plt.subplots(1, n, figsize=(5 * n, 4), sharey=True)
    if n == 1:
        axes = [axes]

    for ax, gain in zip(axes, gains):
        subset = df[df["pacing_gain"] == gain]

        pivot = subset.pivot_table(
            index="buffer_bytes",
            columns="rtt_ms",
            values="mean_fct_s",
            aggfunc="mean"
        )
        # Sort axes small→large
        pivot = pivot.loc[sorted(pivot.index), sorted(pivot.columns)]
        pivot.index   = [BUF_LABELS[b] for b in pivot.index]
        pivot.columns = [RTT_LABELS[r] for r in pivot.columns]

        sns.heatmap(
            pivot, ax=ax,
            annot=True, fmt=".3f",
            cmap="YlOrRd",   # yellow=fast, red=slow. Intuitive.
            vmin=vmin, vmax=vmax,
            linewidths=0.5,
            cbar=(ax == axes[-1]),
        )
        ax.set_title(f"Mean FCT (s) — Gain {gain}")
        ax.set_xlabel("RTT")
        ax.set_ylabel("Buffer Size" if ax == axes[0] else "")

    fig.suptitle("Phase 3: Mice FCT Heatmap by Pacing Gain Variant", y=1.02)
    _save(fig, out_dir, "fig6_fct_heatmaps_by_gain.pdf")


# ============================================================
# SUMMARY TABLE — numbers for the paper. Check these before LaTeX.
# ============================================================

def print_summary_table(df):
    """
    Prints aggregate FCT and goodput per (gain, buffer), averaged over RTTs.
    Also prints per-config FCT reduction percentages relative to 1.25 baseline.
    Verify these numbers before you write the results section. Seriously.
    """
    print("\n" + "=" * 75)
    print("PHASE 3 SUMMARY — Mean Mice FCT (s) by Gain / Buffer (avg over RTTs)")
    print("=" * 75)

    agg_fct = (
        df.groupby(["pacing_gain", "buf_label"])["mean_fct_s"]
        .mean()
        .unstack("buf_label")
    )
    print(agg_fct.to_string(float_format=lambda x: f"{x:.4f}"))

    print("\n" + "=" * 75)
    print("PHASE 3 SUMMARY — FCT Reduction vs Baseline (gain=1.25) per Buffer")
    print("=" * 75)

    if 1.25 in agg_fct.index:
        baseline = agg_fct.loc[1.25]
        for gain in agg_fct.index:
            if gain == 1.25:
                continue
            reduction = (baseline - agg_fct.loc[gain]) / baseline * 100
            print(f"\n  Gain {gain} vs 1.25:")
            for buf_label, pct in reduction.items():
                print(f"    {buf_label}: {pct:+.1f}% FCT change")
    else:
        print("  (No baseline data — Phase 2 BBRv1 results not found)")

    print("\n" + "=" * 75)
    print("PHASE 3 SUMMARY — Elephant Goodput (Mbps) by Gain / Buffer (avg over RTTs)")
    print("=" * 75)

    agg_gp = (
        df.dropna(subset=["elephant_goodput_mbps"])
        .groupby(["pacing_gain", "buf_label"])["elephant_goodput_mbps"]
        .mean()
        .unstack("buf_label")
    )
    print(agg_gp.to_string(float_format=lambda x: f"{x:.2f}"))
    print()


# ============================================================
# FILE SAVE HELPER
# ============================================================

def _save(fig, out_dir, filename):
    """
    Saves figure as both PDF (for LaTeX) and PNG (for the slide deck your advisor
    will ask for 48 hours before the presentation).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = out_dir / filename
    png_path = out_dir / filename.replace(".pdf", ".png")

    fig.savefig(pdf_path)
    fig.savefig(png_path)
    plt.close(fig)

    print(f"  [saved] {pdf_path}  +  {png_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 3 analysis: pacing gain tradeoff figures for CSE 534 BBR project."
    )
    parser.add_argument(
        "--phase2-bbrv1-dir", default="results/phase2/bbrv1",
        help="Phase 2 BBRv1 results dir — used as gain=1.25 baseline"
    )
    parser.add_argument(
        "--phase3-dir", default="results/phase3",
        help="Phase 3 base dir containing gain_1.10/, gain_1.15/, gain_1.20/"
    )
    parser.add_argument(
        "--out-dir", default="results/phase3/figures",
        help="Output dir for all figures"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  CSE 534 - Phase 3: Analysis")
    print("=" * 60)

    # ---- Load Phase 3 gain variant results ----
    print("\nLoading Phase 3 results...")
    p3_results = load_phase3_results(Path(args.phase3_dir))

    # ---- Load Phase 2 BBRv1 as baseline (gain=1.25) ----
    print("\nLoading Phase 2 BBRv1 baseline...")
    baseline_results = load_phase2_baseline(Path(args.phase2_bbrv1_dir))

    all_results = p3_results + baseline_results

    if not all_results:
        print("No valid results found. Check your dirs and try again.")
        return

    # ---- Build unified DataFrame ----
    df = results_to_dataframe(all_results)
    if df.empty:
        print("DataFrame is empty after filtering. Something is very wrong.")
        return

    print(f"\n  Loaded {len(df)} valid experiments.")
    print(f"  Gain variants present: {sorted(df['pacing_gain'].unique())}")

    # ---- Summary table (sanity check before putting numbers in the paper) ----
    print_summary_table(df)

    # ---- Generate all Phase 3 figures ----
    print(f"\nGenerating figures in {args.out_dir}/...")
    plot_fct_throughput_tradeoff(df, args.out_dir)  # Fig 1: THE result
    plot_fct_vs_gain(df, args.out_dir)               # Fig 2: FCT improvement
    plot_goodput_vs_gain(df, args.out_dir)            # Fig 3: throughput cost
    plot_fairness_vs_gain(df, args.out_dir)           # Fig 4: fairness
    plot_fct_cdf_10kb(df, args.out_dir)               # Fig 5: CDF at worst case
    plot_fct_heatmaps(df, args.out_dir)               # Fig 6: heatmap grid

    print(f"\n  All {6} figures saved to {args.out_dir}/")
    print("  Put them in LaTeX. Write the results section. Graduate.")


if __name__ == "__main__":
    main()
