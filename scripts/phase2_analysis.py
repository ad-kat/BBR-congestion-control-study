#!/usr/bin/env python3
"""
phase2_analysis.py
CSE 534 - BBR Under Mixed Workloads: Phase 2 Analysis
Authors: Adri Katyayan, Mehtaab Naazneen Mohammed

Reads raw JSON results from phase2_experiment.py and produces:
  1. Heatmaps: mice mean FCT (buffer_size x RTT), one per CCA
  2. Bar charts: elephant goodput comparison (BBRv1 vs BBRv3)
  3. FCT CDF: distribution of per-mouse FCTs across all configs
  4. Jain's Fairness Index: heatmap (buffer x RTT) per CCA
  5. Queue occupancy: scatter across configs

Usage: python3 phase2_analysis.py [--bbrv1-dir results/phase2/bbrv1] [--bbrv3-dir results/phase2/bbrv3] [--out-dir results/phase2/figures/]
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
# PLOTTING STYLE — because ugly figures in a paper = reviewer rejection
# Use a clean academic style. This is a research paper, not a startup pitch deck.
# ============================================================

plt.rcParams.update({
    "font.family":     "serif",
    "font.size":       11,
    "axes.titlesize":  12,
    "axes.labelsize":  11,
    "legend.fontsize": 9,
    "figure.dpi":      150,
    "savefig.dpi":     300,       # because your advisor will zoom in on the PDF
    "savefig.bbox":    "tight",
    "axes.grid":       True,
    "grid.alpha":      0.3,
})

# Color palette — one per CCA. Colorblind-friendly because accessibility matters
# (also because one of your reviewers might be colorblind and will be annoyed)
CCA_COLORS = {
    "bbr":  "#2077B4",   # a dignified blue for the classic
    "bbr3": "#D62728",   # a dramatic red for the pretender (who may or may not be better)
}

CCA_LABELS = {
    "bbr":  "BBRv1",
    "bbr3": "BBRv3",
}

# The exact buffer sizes and RTTs from the experiment sweep — must match phase2_experiment.py
BUFFER_SIZES_BYTES  = [10_000, 200_000, 10_000_000]
RTTS_MS             = [10, 40, 100]

# Human-readable axis tick labels — nobody wants to read "10000" on a heatmap
BUF_LABELS = {10_000: "10 KB", 200_000: "200 KB", 10_000_000: "10 MB"}
RTT_LABELS = {10: "10 ms", 40: "40 ms", 100: "100 ms"}


# ============================================================
# DATA LOADING
# ============================================================

def load_results(bbrv1_dir, bbrv3_dir):
    """
    Loads JSON result files from results/phase2/bbrv1/ and results/phase2/bbrv3/ separately,
    then merges them into one list. Keeping them split on disk matches the repo structure;
    merging them here means every plot function gets the full picture in one DataFrame.

    Skips files that errored mid-experiment — they happen, it's fine, move on.

    Returns:
        list of result dicts
    """
    all_results = []

    for label, dir_path in [("bbrv1", Path(bbrv1_dir)), ("bbrv3", Path(bbrv3_dir))]:
        json_files = list(dir_path.glob("*.json"))
        if not json_files:
            print(f"[WARN] No JSON files in {dir_path}. Did the {label} experiments run?")
            continue

        print(f"Loading {len(json_files)} files from {dir_path}...")
        for f in json_files:
            try:
                with open(f) as fp:
                    data = json.load(fp)
                if "error" in data:
                    # Experiment blew up mid-run. Noted. Moving on.
                    print(f"  [SKIP] {f.name}: error — '{data['error']}'")
                    continue
                all_results.append(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"  [SKIP] {f.name}: parse error — {e}")

    print(f"  Loaded {len(all_results)} valid experiments total.")
    return all_results


def results_to_dataframe(results):
    """
    Flattens the list of result dicts into a tidy pandas DataFrame.
    One row per experiment. Derived columns computed here so plots stay clean.

    Columns:
        cca, buffer_bytes, rtt_ms, mean_fct_s, median_fct_s, p99_fct_s,
        elephant_goodput_mbps, elephant_retransmissions, jains_fairness,
        queue_backlog_pkts
    """
    rows = []
    for r in results:
        fcts = r.get("mice_fcts_s", [])
        if not fcts:
            # No FCT data = the mice never ran = something is very wrong = skip
            continue

        fcts_arr = np.array(fcts)
        queue    = r.get("queue_stats_midpoint", {})

        rows.append({
            "cca":                      r["cca"],
            "buffer_bytes":             r["buffer_bytes"],
            "rtt_ms":                   r["rtt_ms"],
            # Aggregate FCT statistics across the 10 mice for this config
            "mean_fct_s":               fcts_arr.mean(),
            "median_fct_s":             np.median(fcts_arr),
            "p99_fct_s":                np.percentile(fcts_arr, 99),
            "std_fct_s":                fcts_arr.std(),
            # Elephant metrics
            "elephant_goodput_mbps":    r.get("elephant_goodput_mbps"),
            "elephant_retransmissions": r.get("elephant_retransmissions"),
            # Fairness
            "jains_fairness":           r.get("jains_fairness"),
            # Queue depth at experiment midpoint
            "queue_backlog_pkts":       queue.get("backlog_pkts", np.nan),
            "queue_dropped":            queue.get("dropped", np.nan),
            # Keep raw FCT list for CDF plots
            "_fcts_raw":                fcts,
        })

    df = pd.DataFrame(rows)
    # Add human-readable labels for plot axes
    df["buf_label"] = df["buffer_bytes"].map(BUF_LABELS)
    df["rtt_label"] = df["rtt_ms"].map(RTT_LABELS)
    return df


# ============================================================
# PLOT 1: Mice FCT Heatmaps (one per CCA)
# ============================================================

def plot_fct_heatmaps(df, out_dir):
    """
    Produces side-by-side heatmaps of mean mice FCT (buffer x RTT), one column per CCA.
    Color scale is shared across both to make BBRv1 vs BBRv3 visually comparable.

    This is Figure 1 in the paper. Make it look good.
    """
    ccas = df["cca"].unique()
    fig, axes = plt.subplots(1, len(ccas), figsize=(5 * len(ccas), 4), sharey=True)

    if len(ccas) == 1:
        axes = [axes]  # handle the degenerate single-CCA case gracefully

    # Compute global color scale so both heatmaps are comparable
    vmin = df["mean_fct_s"].min()
    vmax = df["mean_fct_s"].max()

    for ax, cca in zip(axes, sorted(ccas)):
        subset = df[df["cca"] == cca]

        # Pivot into (buffer x RTT) matrix for heatmap — seaborn needs this shape
        pivot = subset.pivot_table(
            index="buffer_bytes",
            columns="rtt_ms",
            values="mean_fct_s",
            aggfunc="mean"  # in case of duplicates (re-runs)
        )
        # Sort axes so heatmap reads small→large on both dimensions
        pivot = pivot.loc[
            sorted(pivot.index),
            sorted(pivot.columns)
        ]
        # Relabel for readability
        pivot.index   = [BUF_LABELS[b] for b in pivot.index]
        pivot.columns = [RTT_LABELS[r] for r in pivot.columns]

        sns.heatmap(
            pivot,
            ax=ax,
            annot=True,
            fmt=".3f",           # 3 decimal places — we're precise scientists
            cmap="YlOrRd",       # yellow→red: low latency is good (cool), high is bad (hot)
            vmin=vmin,
            vmax=vmax,
            linewidths=0.5,
            cbar=(ax == axes[-1]),  # only show colorbar on the last panel
        )
        ax.set_title(f"Mean Mice FCT (s) — {CCA_LABELS.get(cca, cca)}")
        ax.set_xlabel("RTT")
        ax.set_ylabel("Buffer Size" if ax == axes[0] else "")

    fig.suptitle("Phase 2: Mice FCT Heatmap (BBR Elephant + Mice)", y=1.02)
    _save(fig, out_dir, "fig1_fct_heatmap.pdf")


# ============================================================
# PLOT 2: Elephant Goodput Comparison (BBRv1 vs BBRv3)
# ============================================================

def plot_elephant_goodput(df, out_dir):
    """
    Grouped bar chart: elephant throughput per (buffer, RTT) config, grouped by CCA.
    Expects the elephant to be selfish and fast — if not, something's broken.

    This quantifies the throughput cost of having BBRv1 vs BBRv3 as the elephant.
    """
    # Melt into long format for seaborn grouping
    plot_df = df.dropna(subset=["elephant_goodput_mbps"]).copy()
    plot_df["config"] = (
        plot_df["buf_label"] + "\n" + plot_df["rtt_label"]
    )

    fig, ax = plt.subplots(figsize=(12, 5))

    # Sort configs by buffer then RTT for a logical left-to-right ordering
    config_order = [
        f"{BUF_LABELS[b]}\n{RTT_LABELS[r]}"
        for b in BUFFER_SIZES_BYTES
        for r in RTTS_MS
    ]

    sns.barplot(
        data=plot_df,
        x="config",
        y="elephant_goodput_mbps",
        hue="cca",
        order=[c for c in config_order if c in plot_df["config"].values],
        palette=CCA_COLORS,
        ax=ax,
        errwidth=1.5,
        capsize=0.05,
    )

    ax.set_xlabel("Configuration (Buffer Size / RTT)")
    ax.set_ylabel("Elephant Goodput (Mbps)")
    ax.set_title("Phase 2: Elephant Flow Throughput — BBRv1 vs BBRv3")
    ax.axhline(y=100, color="black", linestyle="--", linewidth=0.8, label="Link Capacity (100 Mbps)")
    ax.legend(title="CCA")
    ax.set_ylim(0, 110)

    # Label bars with exact values — reviewers love precision
    for container in ax.containers:
        ax.bar_label(container, fmt="%.1f", fontsize=7, padding=2)

    _save(fig, out_dir, "fig2_elephant_goodput.pdf")


# ============================================================
# PLOT 3: Mice FCT CDF (per buffer size, both CCAs overlaid)
# ============================================================

def plot_fct_cdf(df, out_dir):
    """
    CDF of individual mouse FCTs, one subplot per buffer size.
    BBRv1 and BBRv3 overlaid on each panel. All RTTs pooled together.

    CDF plots are the lingua franca of networking papers. They're expected.
    Reviewers will complain if you don't have one.
    """
    buf_sizes = sorted(df["buffer_bytes"].unique())
    fig, axes = plt.subplots(1, len(buf_sizes), figsize=(5 * len(buf_sizes), 4), sharey=True)

    if len(buf_sizes) == 1:
        axes = [axes]

    for ax, buf in zip(axes, buf_sizes):
        for cca in sorted(df["cca"].unique()):
            # Collect all individual FCT values for this (buf, CCA) combination
            subset   = df[(df["buffer_bytes"] == buf) & (df["cca"] == cca)]
            all_fcts = []
            for fcts in subset["_fcts_raw"]:
                all_fcts.extend(fcts)

            if not all_fcts:
                continue  # no data for this combo, skip silently

            all_fcts_arr = np.sort(np.array(all_fcts))
            cdf          = np.arange(1, len(all_fcts_arr) + 1) / len(all_fcts_arr)

            ax.plot(
                all_fcts_arr, cdf,
                label=CCA_LABELS.get(cca, cca),
                color=CCA_COLORS.get(cca, "gray"),
                linewidth=2,
            )

        ax.set_title(f"Buffer = {BUF_LABELS[buf]}")
        ax.set_xlabel("Mice FCT (s)")
        if ax == axes[0]:
            ax.set_ylabel("CDF")
        ax.legend()
        ax.set_xlim(left=0)
        ax.set_ylim(0, 1.05)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    fig.suptitle("Phase 2: Mice FCT CDF — BBRv1 vs BBRv3 (all RTTs pooled)", y=1.02)
    _save(fig, out_dir, "fig3_fct_cdf.pdf")


# ============================================================
# PLOT 4: Jain's Fairness Index Heatmap
# ============================================================

def plot_fairness_heatmap(df, out_dir):
    """
    Heatmap of Jain's Fairness Index — same layout as Figure 1 (the FCT heatmap).
    Closer to 1.0 = everyone is getting their fair share.
    Closer to 0 = the elephant ate all the bandwidth. Again.
    """
    ccas = df["cca"].unique()
    fig, axes = plt.subplots(1, len(ccas), figsize=(5 * len(ccas), 4), sharey=True)

    if len(ccas) == 1:
        axes = [axes]

    for ax, cca in zip(axes, sorted(ccas)):
        subset = df[df["cca"] == cca]
        pivot  = subset.pivot_table(
            index="buffer_bytes",
            columns="rtt_ms",
            values="jains_fairness",
            aggfunc="mean"
        )
        pivot = pivot.loc[sorted(pivot.index), sorted(pivot.columns)]
        pivot.index   = [BUF_LABELS[b] for b in pivot.index]
        pivot.columns = [RTT_LABELS[r] for r in pivot.columns]

        sns.heatmap(
            pivot, ax=ax,
            annot=True, fmt=".3f",
            cmap="RdYlGn",   # red=unfair, green=fair. Intuitive. For once.
            vmin=0, vmax=1,
            linewidths=0.5,
            cbar=(ax == axes[-1]),
        )
        ax.set_title(f"Jain's FI — {CCA_LABELS.get(cca, cca)}")
        ax.set_xlabel("RTT")
        ax.set_ylabel("Buffer Size" if ax == axes[0] else "")

    fig.suptitle("Phase 2: Jain's Fairness Index (Elephant + Mice)", y=1.02)
    _save(fig, out_dir, "fig4_jains_fairness.pdf")


# ============================================================
# PLOT 5: Queue Occupancy vs. RTT (scatter, per buffer size)
# ============================================================

def plot_queue_occupancy(df, out_dir):
    """
    Scatter plot: queue backlog (packets) vs RTT, colored by CCA, faceted by buffer size.
    This is the smoking gun — if BBRv1 has higher queue occupancy than BBRv3,
    that's why the mice are suffering.
    """
    plot_df = df.dropna(subset=["queue_backlog_pkts"]).copy()
    if plot_df.empty:
        print("[SKIP] No queue occupancy data available (tc stats may have failed).")
        return

    buf_sizes = sorted(plot_df["buffer_bytes"].unique())
    fig, axes = plt.subplots(1, len(buf_sizes), figsize=(5 * len(buf_sizes), 4), sharey=False)

    if len(buf_sizes) == 1:
        axes = [axes]

    for ax, buf in zip(axes, buf_sizes):
        subset = plot_df[plot_df["buffer_bytes"] == buf]

        for cca in sorted(subset["cca"].unique()):
            cca_data = subset[subset["cca"] == cca]
            ax.scatter(
                cca_data["rtt_ms"],
                cca_data["queue_backlog_pkts"],
                label=CCA_LABELS.get(cca, cca),
                color=CCA_COLORS.get(cca, "gray"),
                s=80, alpha=0.8, zorder=5,
            )
            # Connect the dots — it's not a rigorous regression, but it's readable
            cca_sorted = cca_data.sort_values("rtt_ms")
            ax.plot(
                cca_sorted["rtt_ms"],
                cca_sorted["queue_backlog_pkts"],
                color=CCA_COLORS.get(cca, "gray"),
                alpha=0.5, linewidth=1.2,
            )

        ax.set_title(f"Buffer = {BUF_LABELS[buf]}")
        ax.set_xlabel("RTT (ms)")
        ax.set_ylabel("Queue Backlog (pkts)" if ax == axes[0] else "")
        ax.set_xticks(RTTS_MS)
        ax.legend()

    fig.suptitle("Phase 2: Bottleneck Queue Occupancy at Experiment Midpoint", y=1.02)
    _save(fig, out_dir, "fig5_queue_occupancy.pdf")


# ============================================================
# SUMMARY TABLE — for the paper's results section
# ============================================================

def print_summary_table(df):
    """
    Prints a plain-text summary table for sanity checking before you put numbers in the paper.
    Check this before copying anything into LaTeX. Seriously.
    """
    print("\n" + "=" * 75)
    print("PHASE 2 SUMMARY — Mean Mice FCT (s) by CCA / Buffer / RTT")
    print("=" * 75)

    pivot = df.pivot_table(
        index=["cca", "buf_label"],
        columns="rtt_label",
        values="mean_fct_s",
        aggfunc="mean"
    )
    print(pivot.to_string(float_format=lambda x: f"{x:.4f}"))

    print("\n" + "=" * 75)
    print("PHASE 2 SUMMARY — Jain's Fairness Index by CCA / Buffer / RTT")
    print("=" * 75)

    pivot_jfi = df.pivot_table(
        index=["cca", "buf_label"],
        columns="rtt_label",
        values="jains_fairness",
        aggfunc="mean"
    )
    print(pivot_jfi.to_string(float_format=lambda x: f"{x:.4f}"))

    print("\n" + "=" * 75)
    print("PHASE 2 SUMMARY — Elephant Goodput (Mbps) by CCA / Buffer / RTT")
    print("=" * 75)

    pivot_gp = df.pivot_table(
        index=["cca", "buf_label"],
        columns="rtt_label",
        values="elephant_goodput_mbps",
        aggfunc="mean"
    )
    print(pivot_gp.to_string(float_format=lambda x: f"{x:.2f}"))
    print()


# ============================================================
# FILE SAVE HELPER
# ============================================================

def _save(fig, out_dir, filename):
    """
    Saves a figure to both PDF (for the paper) and PNG (for quick previewing).
    PDF because LaTeX. PNG because your advisor wants it in a slide deck immediately.
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
        description="Phase 2 analysis and figure generation for CSE 534 BBR project."
    )
    parser.add_argument(
        "--bbrv1-dir", default="results/phase2/bbrv1",
        help="Directory containing BBRv1 JSON results"
    )
    parser.add_argument(
        "--bbrv3-dir", default="results/phase2/bbrv3",
        help="Directory containing BBRv3 JSON results"
    )
    parser.add_argument(
        "--out-dir", default="results/phase2/figures",
        help="Output directory for generated figures (PDF + PNG)"
    )
    args = parser.parse_args()

    # ---- Load from both CCA subdirs and merge ----
    results = load_results(args.bbrv1_dir, args.bbrv3_dir)
    if not results:
        print("No valid results to analyze. Exiting.")
        return

    # ---- Convert to DataFrame ----
    df = results_to_dataframe(results)
    if df.empty:
        print("DataFrame is empty after filtering. Check your JSON files.")
        return

    print(f"  Loaded {len(df)} valid experiments into DataFrame.")

    # ---- Sanity check: print summary table ----
    print_summary_table(df)

    # ---- Generate all figures ----
    print(f"\nGenerating figures in {args.out_dir}/...")
    plot_fct_heatmaps(df, args.out_dir)       # Fig 1 — the main result
    plot_elephant_goodput(df, args.out_dir)    # Fig 2 — does the elephant suffer?
    plot_fct_cdf(df, args.out_dir)             # Fig 3 — networking paper staple
    plot_fairness_heatmap(df, args.out_dir)    # Fig 4 — Jain's FI
    plot_queue_occupancy(df, args.out_dir)     # Fig 5 — causal evidence

    print(f"\nAll figures saved to {args.out_dir}/")
    print("Go put them in your LaTeX document. You deserve it.")


if __name__ == "__main__":
    main()