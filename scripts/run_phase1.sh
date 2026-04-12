#!/usr/bin/env bash
# run_phase1.sh — Reproduces Cao et al. IMC 2019 Figure 2.
# Sweeps 5 buffer sizes at 100 Mbps / 40 ms RTT for BBR and CUBIC.
#
# iperf3 runs INSIDE topology.py while Mininet is alive — not from here.
# Trying to reach Mininet namespaces from an external shell is how you
# spend 3 hours debugging something that was never going to work.
#
# Usage: sudo bash scripts/run_phase1.sh

set -euo pipefail

# Resolve paths regardless of where you invoke this from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TOPOLOGY="$SCRIPT_DIR/topology.py"
OUTPUT_DIR="$REPO_ROOT/results/phase1"

# ── Config ────────────────────────────────────────────────────────────────────
BW_MBPS=100
RTT_MS=40
DURATION=30          # seconds per iperf3 run — enough to reach steady state

# The 5 buffer sizes from Cao et al. Table 1. Don't change these
# unless you enjoy explaining to Prof. Balasubramanian why you didn't
# reproduce the right experiment.
BUFFER_SIZES_KB=(10 50 200 1024 10240)   # 10KB 50KB 200KB 1MB 10MB
CCAS=("bbr" "cubic")
# ──────────────────────────────────────────────────────────────────────────────

mkdir -p "$OUTPUT_DIR"

# Confirm BBR and CUBIC are available before wasting anyone's time
AVAILABLE=$(sysctl -n net.ipv4.tcp_available_congestion_control)
echo "[+] Available CCAs: $AVAILABLE"
for cca in "${CCAS[@]}"; do
    if ! echo "$AVAILABLE" | grep -qw "$cca"; then
        echo "[!] $cca is NOT available. Load it: sudo modprobe tcp_$cca"
        exit 1
    fi
done
echo "[+] All required CCAs confirmed. The kernel cooperates, for once."

# Clean up any leftover Mininet state from a previous crashed run.
# mn --clean is the "have you tried turning it off and on again" of Mininet.
echo "[+] Cleaning up any leftover Mininet state..."
sudo mn --clean 2>/dev/null || true

# ── Main sweep ────────────────────────────────────────────────────────────────
for BUF_KB in "${BUFFER_SIZES_KB[@]}"; do
    for CCA in "${CCAS[@]}"; do
        echo ""
        echo "════════════════════════════════════════════════════════"
        echo "  Buffer: ${BUF_KB} KB | CCA: ${CCA} | BW: ${BW_MBPS} Mbps | RTT: ${RTT_MS} ms"
        echo "════════════════════════════════════════════════════════"

        OUT_FILE="${OUTPUT_DIR}/${CCA}_buf${BUF_KB}kb.json"

        # topology.py handles everything: builds the network, runs iperf3,
        # saves JSON, then exits cleanly. One process, one responsibility.
        sudo python3 "$TOPOLOGY" \
            --bw  "$BW_MBPS" \
            --rtt "$RTT_MS"  \
            --buf "$BUF_KB"  \
            --cca "$CCA"     \
            --duration "$DURATION" \
            --out "$OUT_FILE"

        if [ -f "$OUT_FILE" ] && [ -s "$OUT_FILE" ]; then
            echo "[+] Saved: $OUT_FILE"
        else
            echo "[!] Output file missing or empty for $CCA buf=${BUF_KB}KB — check above for errors"
        fi

        # Brief pause between runs so the kernel clears its state.
        # Skipping this is how you get mysterious throughput anomalies.
        sleep 2

        # Clean Mininet state between runs — leftover bridges cause weird failures
        sudo mn --clean 2>/dev/null || true
        sleep 1
    done
done

echo ""
echo "[+] Phase 1 sweep complete. Results in: $OUTPUT_DIR"
echo "[+] Next: python3 scripts/plot_phase1.py"
echo "    If the plot matches Fig. 2, the tc setup works and you can trust Phase 2."