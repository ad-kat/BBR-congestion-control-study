#!/usr/bin/env python3
"""
phase2_experiment.py
CSE 534 - BBR Under Mixed Workloads: Phase 2
Authors: Adri Katyayan, Mehtaab Naazneen Mohammed

Phase 2: Mixed Workload Characterization
- 1 BBR elephant flow (120s) + 10 sequential 1MB mice flows
- Sweep: buffer_size in {10KB, 200KB, 10MB} x RTT in {10, 40, 100ms}
- Metrics: mice FCT, elephant goodput, retransmissions, queue occupancy, Jain's fairness
- Comparison axis: BBRv1 vs BBRv3

Run as root: sudo python3 phase2_experiment.py
Results written to: results/phase2/bbrv1/ and results/phase2/bbrv3/
"""

import os
import sys
import json
import time
import subprocess
import itertools
import re
import datetime
from pathlib import Path

# --- because mininet refuses to work unless you're root, and so do we ---
if os.geteuid() != 0:
    print("[ERROR] This script must be run as root (sudo). Mininet throws a tantrum otherwise.")
    sys.exit(1)

# Mininet imports — if these fail, you forgot to install mininet. Classic.
from mininet.net import Mininet
from mininet.node import OVSController
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.clean import cleanup

# ============================================================
# CONFIGURATION — the only part you'll actually need to touch
# ============================================================

# Buffer sizes in bytes. 10KB is "lol no buffer", 10MB is "I have trust issues with drops"
BUFFER_SIZES_BYTES = [10_000, 200_000, 10_000_000]

# RTTs in milliseconds. 10ms = local datacenter, 100ms = talking to the moon
RTTS_MS = [10, 40, 100]

# How long the elephant flow runs. 120 seconds. Go get a coffee.
ELEPHANT_DURATION_S = 120

# Number of mice flows to send sequentially. Each is exactly 1MB because we're precise like that.
NUM_MICE = 10
MICE_SIZE_MB = 1

# CCA variants to test. BBRv1 is the old one; BBRv3 is Google's "we fixed it (maybe)" version.
# Requires BBRv3 kernel module loaded separately. See README (that you haven't written yet).
CCA_VARIANTS = ["bbr", "bbr3"]  # bbr3 requires the google/bbr branch module loaded via insmod

# Output dirs — one per CCA variant, matching the repo's results/phase2/bbrv1 and bbrv3 structure.
# Don't change these unless you want to fight the analysis script AND the handoff doc simultaneously.
RESULTS_DIRS = {
    "bbr":  Path("results/phase2/bbrv1"),
    "bbr3": Path("results/phase2/bbrv3"),
}

# Mininet dumbbell topology parameters
# Bandwidth of the bottleneck link in Mbps. 100 Mbps because we're not animals.
BOTTLENECK_BW_MBPS = 100

# Bandwidth of access links (sender->switch, receiver->switch). Way higher to not be the bottleneck.
ACCESS_BW_MBPS = 500

# iperf3 server port. 5201 is default. 5202 is for the second sender.
IPERF_PORT_ELEPHANT = 5201
IPERF_PORT_MICE     = 5202


# ============================================================
# TOPOLOGY BUILDER
# ============================================================

def build_dumbbell(bw_mbps, rtt_ms, buf_bytes):
    """
    Constructs a dumbbell topology: s1 -- r1 -- r2 -- s2, plus a receiver h_recv.
    The bottleneck is r1<->r2. tc/netem handles RTT and buffer; tc/HTB handles bandwidth.

    Args:
        bw_mbps  : bottleneck bandwidth in Mbps
        rtt_ms   : one-way delay is rtt_ms/2 per side (netem adds it symmetrically)
        buf_bytes: max queue size in bytes at the bottleneck

    Returns:
        net      : the Mininet network object (caller must net.stop() — don't forget)
        elephant_sender, mice_sender, receiver: the actual host objects
    """
    # Cleanup any zombie mininet processes from the last time this crashed
    cleanup()

    net = Mininet(controller=OVSController, link=TCLink)

    # Add our four actors in this TCP drama
    elephant_sender = net.addHost("h_elephant")   # the rude bandwidth hog
    mice_sender     = net.addHost("h_mice")       # the innocent victim
    receiver        = net.addHost("h_recv")       # suffers equally from both

    # Two routers forming the bottleneck link between them
    r1 = net.addSwitch("r1")
    r2 = net.addSwitch("r2")

    controller = net.addController("c0")

    # Access links: high bandwidth, negligible delay. These are NOT the bottleneck.
    # If they become the bottleneck, something has gone very wrong with your life choices.
    net.addLink(elephant_sender, r1, bw=ACCESS_BW_MBPS, delay="1ms")
    net.addLink(mice_sender,     r1, bw=ACCESS_BW_MBPS, delay="1ms")
    net.addLink(receiver,        r2, bw=ACCESS_BW_MBPS, delay="1ms")

    # THE bottleneck link — where dreams (and packets) go to die
    # delay is half the RTT because netem applies delay on each direction
    one_way_delay_ms = rtt_ms / 2.0

    # buf_size in packets ≈ buf_bytes / 1500 (MTU). netem thinks in packets, not bytes. Sigh.
    buf_pkts = max(1, buf_bytes // 1500)

    net.addLink(
        r1, r2,
        bw=bw_mbps,
        delay=f"{one_way_delay_ms}ms",
        max_queue_size=buf_pkts,    # this is the queue that will haunt our mice flows
        use_htb=True                # HTB gives us rate limiting; netem gives us delay. Together: pain.
    )

    net.build()
    controller.start()
    r1.start([controller])
    r2.start([controller])

    return net, elephant_sender, mice_sender, receiver


# ============================================================
# METRIC HELPERS
# ============================================================

def get_queue_occupancy(interface="r1-eth2"):
    """
    Reads tc qdisc stats for the bottleneck interface.
    Returns a dict with {packets_sent, dropped, overlimits, backlog_bytes, backlog_pkts}.

    This is the "how badly are we clogging the pipe" meter.
    Interface name is Mininet's auto-generated name — pray it matches.
    """
    try:
        out = subprocess.check_output(
            ["tc", "-s", "qdisc", "show", "dev", interface],
            stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        # tc failed, which means either the interface doesn't exist or Linux hates you today
        return {}

    stats = {}

    # Parse "Sent X bytes Y pkts" — tc's idea of a structured format
    m = re.search(r"Sent (\d+) bytes (\d+) pkt", out)
    if m:
        stats["bytes_sent"] = int(m.group(1))
        stats["pkts_sent"]  = int(m.group(2))

    # Parse drop and overlimit counts
    m = re.search(r"dropped (\d+), overlimits (\d+)", out)
    if m:
        stats["dropped"]    = int(m.group(1))
        stats["overlimits"] = int(m.group(2))

    # Backlog = current queue depth. This is the number we actually care about.
    m = re.search(r"backlog (\d+)b (\d+)p", out)
    if m:
        stats["backlog_bytes"] = int(m.group(1))
        stats["backlog_pkts"]  = int(m.group(2))

    return stats


def parse_iperf3_json(raw_json_str):
    """
    Parses iperf3 JSON output into a tidy dict.
    Returns {goodput_mbps, retransmissions, duration_s} or empty dict on failure.

    iperf3's JSON is actually fine. No complaints here. Unprecedented.
    """
    try:
        data = json.loads(raw_json_str)
        end  = data.get("end", {})
        sent = end.get("sum_sent", {})
        return {
            "goodput_mbps":     sent.get("bits_per_second", 0) / 1e6,
            "retransmissions":  sent.get("retransmits", 0),
            "duration_s":       sent.get("seconds", 0),
        }
    except (json.JSONDecodeError, KeyError):
        # iperf3 crashed or produced garbage. Probably a timeout. Log it and move on.
        return {}


def jains_fairness(throughputs):
    """
    Computes Jain's Fairness Index for a list of throughput values.
    JFI = (sum(x))^2 / (n * sum(x^2))
    Range: [1/n, 1.0]. 1.0 = perfectly fair. 1/n = maximally unfair (one winner, all losers).

    Named after Raj Jain, who apparently felt the networking world needed more Greek letters.
    """
    if not throughputs or all(t == 0 for t in throughputs):
        return 0.0
    n   = len(throughputs)
    s   = sum(throughputs)
    sq  = sum(t**2 for t in throughputs)
    return (s ** 2) / (n * sq) if sq > 0 else 0.0


# ============================================================
# CORE EXPERIMENT RUNNER
# ============================================================

def run_single_experiment(cca, buf_bytes, rtt_ms):
    """
    Runs one (cca, buffer_size, RTT) configuration:
      1. Spins up Mininet dumbbell topology
      2. Starts iperf3 server on receiver for both ports
      3. Launches BBR elephant flow for ELEPHANT_DURATION_S seconds
      4. Concurrently sends NUM_MICE sequential 1MB mice flows
      5. Collects queue stats at the midpoint (roughly)
      6. Tears everything down

    Returns a dict of all metrics, ready to be serialized to JSON.

    Args:
        cca      : string, "bbr" or "bbr3"
        buf_bytes: int, buffer size in bytes
        rtt_ms   : int/float, RTT in milliseconds

    Returns:
        dict with all metrics (or partial dict if something died mid-experiment)
    """
    print(f"\n{'='*60}")
    print(f"  Running: CCA={cca}  BUF={buf_bytes//1000}KB  RTT={rtt_ms}ms")
    print(f"{'='*60}")

    # Build the topology. If this explodes, check that OVS is running.
    net, h_elephant, h_mice, h_recv = build_dumbbell(
        bw_mbps=BOTTLENECK_BW_MBPS,
        rtt_ms=rtt_ms,
        buf_bytes=buf_bytes
    )

    result = {
        "cca": cca,
        "buffer_bytes": buf_bytes,
        "rtt_ms": rtt_ms,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mice_fcts_s": [],              # per-mouse FCT list
        "elephant_goodput_mbps": None,
        "elephant_retransmissions": None,
        "queue_stats_midpoint": {},
        "jains_fairness": None,
    }

    recv_ip = h_recv.IP()

    try:
        # ---- Step 1: Start iperf3 servers on receiver ----
        # -D = daemon mode. -p = port. -J = JSON output (which we'll parse later).
        # One server for elephant, one for mice, because they can't share. Typical.
        h_recv.cmd(f"iperf3 -s -p {IPERF_PORT_ELEPHANT} -D --logfile /tmp/iperf_elephant_server.log")
        h_recv.cmd(f"iperf3 -s -p {IPERF_PORT_MICE}     -D --logfile /tmp/iperf_mice_server.log")
        time.sleep(0.5)  # give the servers a moment to wake up before being bombarded

        # ---- Step 2: Verify CCA is available on this kernel ----
        # If bbr3 isn't available, the experiment is invalid. Fail loudly, not silently.
        available = subprocess.check_output(
            ["sysctl", "net.ipv4.tcp_available_congestion_control"]
        ).decode()
        if cca not in available:
            print(f"[WARN] CCA '{cca}' not found in available CCAs. Skipping this config.")
            print(f"       Available: {available.strip()}")
            print(f"       For bbr3: load the kernel module via insmod before running.")
            return result  # partial result, clearly marked as incomplete

        # ---- Step 3: Launch elephant flow in background ----
        # -t = duration, -C = CCA, -J = JSON output, -p = port
        # & at the end because we have mice to send concurrently. Multitasking is hard.
        elephant_cmd = (
            f"iperf3 -c {recv_ip} -t {ELEPHANT_DURATION_S} "
            f"-C {cca} -J -p {IPERF_PORT_ELEPHANT} "
            f"> /tmp/iperf_elephant_client.json 2>&1 &"
        )
        h_elephant.cmd(elephant_cmd)
        elephant_pid = h_elephant.cmd("echo $!").strip()
        print(f"  [elephant] PID={elephant_pid}, running for {ELEPHANT_DURATION_S}s...")

        # Give the elephant a head start to saturate the link before mice show up
        # because that's the whole point — mice arrive into an already-congested pipe
        time.sleep(2)

        # ---- Step 4: Send mice flows sequentially ----
        # Each mouse is 1MB. -n = bytes to transfer, -C = CCA, -J = JSON, -p = port.
        # We record wall-clock time around each iperf3 call as a proxy for FCT.
        print(f"  [mice] Sending {NUM_MICE} sequential mice flows ({MICE_SIZE_MB}MB each)...")
        mice_fcts = []

        for i in range(NUM_MICE):
            mice_start = time.monotonic()

            mice_cmd = (
                f"timeout 30 iperf3 -c {recv_ip} -n {MICE_SIZE_MB}M "
                f"-C {cca} -J -p {IPERF_PORT_MICE} "
                f"> /tmp/iperf_mice_{i}.json 2>&1"
            )
            h_mice.cmd(mice_cmd)  # blocking — next mouse waits for this one to finish

            mice_end = time.monotonic()
            fct = mice_end - mice_start
            mice_fcts.append(fct)
            print(f"    Mouse {i+1}/{NUM_MICE}: FCT = {fct:.4f}s")
        

        result["mice_fcts_s"] = mice_fcts

        # ---- Step 5: Grab queue stats at roughly the midpoint of the experiment ----
        # By now we're well into the elephant flow's steady state (ProbeBW cycling).
        # This is where the standing queue should be happily persisting, like an old friend
        # who never leaves even when you want them to.
        result["queue_stats_midpoint"] = get_queue_occupancy("r1-eth2")

        # ---- Step 6: Wait for elephant to finish ----
        # We wait the full duration minus the 2s head start minus mice time.
        # The elephant process is daemonized, so we poll for it.
        elapsed = 2 + sum(mice_fcts)
        remaining = max(0, ELEPHANT_DURATION_S - elapsed)
        if remaining > 0:
            print(f"  [elephant] Waiting {remaining:.1f}s for elephant to finish...")
            time.sleep(remaining)

        # ---- Step 7: Parse elephant iperf3 JSON output ----
        try:
            with open("/tmp/iperf_elephant_client.json") as f:
                elephant_raw = f.read()
            ep = parse_iperf3_json(elephant_raw)
            result["elephant_goodput_mbps"]     = ep.get("goodput_mbps")
            result["elephant_retransmissions"]  = ep.get("retransmissions")
        except FileNotFoundError:
            # iperf3 didn't write output — probably crashed. Add to the list of things to debug.
            print("  [WARN] Elephant iperf3 output not found. Did it crash?")

        # ---- Step 8: Compute Jain's Fairness Index ----
        # Between elephant goodput and average mice throughput (1MB / FCT).
        # This is a stretch — FCT mixes transfer + wait time — but it's directionally useful.
        mice_throughputs = [
            (MICE_SIZE_MB * 8) / fct for fct in mice_fcts if fct > 0
        ]
        all_throughputs = mice_throughputs[:]
        if result["elephant_goodput_mbps"]:
            all_throughputs.append(result["elephant_goodput_mbps"])
        result["jains_fairness"] = jains_fairness(all_throughputs)

        print(f"  [done] avg mice FCT={sum(mice_fcts)/len(mice_fcts):.4f}s, "
              f"elephant={result['elephant_goodput_mbps']:.2f} Mbps, "
              f"JFI={result['jains_fairness']:.4f}")

    except Exception as e:
        # If we got here, something exploded. Note it and move on — we have 8 more configs to run.
        print(f"  [ERROR] Experiment failed: {e}")
        result["error"] = str(e)

    finally:
        # ALWAYS stop Mininet. Always. Even if everything is on fire.
        # Leftover Mininet state will ruin every subsequent experiment.
        net.stop()
        cleanup()
        # Kill any lingering iperf3 processes. They're squatters.
        subprocess.run(["pkill", "-f", "iperf3"], capture_output=True)

    return result


# ============================================================
# RESULT SERIALIZATION
# ============================================================

def save_result(result, results_dir):
    """
    Saves one experiment result to a uniquely named JSON file.
    Naming: {cca}_{buf_bytes}B_{rtt_ms}ms_{timestamp}.json

    JSON is the least painful serialization format that isn't YAML.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    ts  = result.get("timestamp", "unknown").replace(":", "-").replace(".", "-")
    cca = result.get("cca", "unknown")
    buf = result.get("buffer_bytes", 0)
    rtt = result.get("rtt_ms", 0)

    filename = results_dir / f"{cca}_{buf}B_{rtt}ms_{ts}.json"

    with open(filename, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  [saved] {filename}")
    return filename


# ============================================================
# MAIN SWEEP
# ============================================================

def main():
    """
    The outer sweep loop. Iterates over all (CCA, buffer_size, RTT) combinations.
    Total configs: 2 CCAs × 3 buffers × 3 RTTs = 18 experiments.
    Each takes ~2 minutes. Total runtime: ~36 minutes. Plan accordingly.
    Go touch grass between runs. You've earned it.
    """
    setLogLevel("warning")  # Mininet is chatty by default. Silence is golden.

    print("=" * 60)
    print("  CSE 534 - Phase 2: Mixed Workload Characterization")
    print(f"  Total configurations: {len(CCA_VARIANTS) * len(BUFFER_SIZES_BYTES) * len(RTTS_MS)}")
    print(f"  Estimated runtime: ~{len(CCA_VARIANTS) * len(BUFFER_SIZES_BYTES) * len(RTTS_MS) * 2} minutes")
    print(f"  Results: results/phase2/bbrv1/  and  results/phase2/bbrv3/")
    print("=" * 60)

    # Sweep — the full factorial design from the proposal
    all_configs = list(itertools.product(CCA_VARIANTS, BUFFER_SIZES_BYTES, RTTS_MS))
    total       = len(all_configs)

    for i, (cca, buf, rtt) in enumerate(all_configs, 1):
        print(f"\n[{i}/{total}] CCA={cca}, BUF={buf//1000}KB, RTT={rtt}ms")

        result   = run_single_experiment(cca=cca, buf_bytes=buf, rtt_ms=rtt)
        # Route each result into its CCA-specific subdirectory — bbrv1/ or bbrv3/
        saved_to = save_result(result, RESULTS_DIRS[cca])

        # Brief pause between experiments — let the kernel breathe and the OVS switches reset.
        # Yes, 5 seconds matters. No, we don't know exactly why.
        time.sleep(5)

    print(f"\n{'='*60}")
    print(f"  All {total} experiments complete.")
    print(f"  BBRv1 results: {RESULTS_DIRS['bbr']}/")
    print(f"  BBRv3 results: {RESULTS_DIRS['bbr3']}/")
    print(f"  Next step: run phase2_analysis.py (your partner's job)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()