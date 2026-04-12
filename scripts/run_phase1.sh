#!/usr/bin/env bash
# run_phase1.sh — Reproduces Cao et al. IMC 2019 Figure 2.
# Sweeps 5 buffer sizes at 100 Mbps / 40 ms RTT, running BBR and CUBIC
# bulk flows and saving iperf3 JSON output for later plotting.
#
# Run as root (Mininet needs it). Yes, sudo the whole thing.
# Usage: sudo bash run_phase1.sh

set -euo pipefail

# Resolve the repo root regardless of where you invoke the script from.
# Because "it works on my machine" is not a valid methodology.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# ── Config ────────────────────────────────────────────────────────────────────
BW_MBPS=100
RTT_MS=40
DURATION=30          # seconds per iperf3 run — enough to reach steady state
OUTPUT_DIR="$REPO_ROOT/results/phase1"
TOPOLOGY="$SCRIPT_DIR/topology.py"

# The 5 buffer sizes from Cao et al. Table 1. Don't change these
# unless you enjoy explaining to Prof. Balasubramanian why you didn't
# reproduce the right experiment.
BUFFER_SIZES_KB=(10 50 200 1024 10240)   # 10KB 50KB 200KB 1MB 10MB

# CCAs to test per buffer size
CCAS=("bbr" "cubic")
# ──────────────────────────────────────────────────────────────────────────────

mkdir -p "$OUTPUT_DIR"

# Confirm BBR and CUBIC are available — saves 30 minutes of debugging later
AVAILABLE=$(sysctl -n net.ipv4.tcp_available_congestion_control)
echo "[+] Available CCAs: $AVAILABLE"
for cca in "${CCAS[@]}"; do
    if ! echo "$AVAILABLE" | grep -qw "$cca"; then
        echo "[!] $cca is NOT available. Load it first: sudo modprobe tcp_$cca"
        exit 1
    fi
done
echo "[+] All required CCAs confirmed. The kernel cooperates, for once."

# ── Main sweep ────────────────────────────────────────────────────────────────
for BUF_KB in "${BUFFER_SIZES_KB[@]}"; do
    for CCA in "${CCAS[@]}"; do
        echo ""
        echo "════════════════════════════════════════════════════════"
        echo "  Buffer: ${BUF_KB} KB | CCA: ${CCA} | BW: ${BW_MBPS} Mbps | RTT: ${RTT_MS} ms"
        echo "════════════════════════════════════════════════════════"

        OUT_FILE="${OUTPUT_DIR}/${CCA}_buf${BUF_KB}kb.json"

        # Launch Mininet dumbbell topology in background via Python;
        # give it 3 seconds to boot before iperf3 tries to talk to it.
        # This is the "hope the race condition doesn't bite us" strategy.
        sudo python3 "$TOPOLOGY" \
            --bw "$BW_MBPS" \
            --rtt "$RTT_MS" \
            --buf "$BUF_KB" &
        TOPO_PID=$!
        sleep 3

        # iperf3: h1 (10.0.0.1) → h3 (10.0.0.3), single bulk stream.
        # -C sets the CCA per socket — this is the whole point.
        # -J outputs JSON so plot_phase1.py can parse it without regex trauma.
        sudo ip netns exec h1 iperf3 \
            --client 10.0.0.3 \
            --time "$DURATION" \
            --cong "$CCA" \
            --json \
            --logfile "$OUT_FILE" \
            --interval 1     # 1-second bandwidth samples for granularity
        STATUS=$?

        if [ $STATUS -eq 0 ]; then
            echo "[+] Saved: $OUT_FILE"
        else
            # iperf3 failing silently would be catastrophic for the paper.
            echo "[!] iperf3 returned non-zero ($STATUS) for $CCA buf=${BUF_KB}KB — check $OUT_FILE"
        fi

        # Kill topology cleanly — Mininet leaves zombie processes if you don't.
        # Ask me how I know.
        kill "$TOPO_PID" 2>/dev/null || true
        sleep 2
    done
done

echo ""
echo "[+] Phase 1 sweep complete. Results in: $OUTPUT_DIR"
echo "[+] Next: python3 plot_phase1.py to see if we reproduced Figure 2."
echo "    If we didn't... we debug tc. It's always tc."