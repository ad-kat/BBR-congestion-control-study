#!/usr/bin/env python3
"""
phase3_experiment.py
CSE 534 - BBR Under Mixed Workloads: Phase 3
Authors: Adri Katyayan, Mehtaab Naazneen Mohammed

Phase 3: Pacing Gain Modification Sweep
- Loads each custom tcp_bbr_gainXXX.ko module (compiled with pacing_gain probe-up = 1.10, 1.15, 1.20)
- Runs the full Phase 2 sweep (9 configs: buffer x RTT) under each gain variant
- Baseline (gain=1.25, stock BBRv1) results are READ from results/phase2/bbrv1/ — not re-run
- Output: results/phase3/gain_1.10/, gain_1.15/, gain_1.20/ (one JSON per config)

PRE-REQUISITES (read this, for once):
  1. Build three kernel modules from tcp_bbr.c with pacing_gain[1] edited to 1.10, 1.15, 1.20:
       cp net/ipv4/tcp_bbr.c tcp_bbr_gain110.c  (then edit the float, build as module)
     Place compiled .ko files at:
       ~/BBR congestion ctrl/BBR-congestion-control-study/modules/tcp_bbr_gain110.ko
       ~/BBR congestion ctrl/BBR-congestion-control-study/modules/tcp_bbr_gain115.ko
       ~/BBR congestion ctrl/BBR-congestion-control-study/modules/tcp_bbr_gain120.ko
     See docs/build_module.md for full kernel module build instructions.
  2. Run as root: sudo python3 phase3_experiment.py
  3. Phase 2 BBRv1 results must already exist (used as the 1.25 baseline in analysis).

Runtime: ~3 gain variants x 9 configs x ~2 min each = ~54 minutes. Go touch grass.
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

# --- still need root. still not sorry about it. ---
if os.geteuid() != 0:
    print("[ERROR] Must run as root. Mininet will throw a fit otherwise. sudo !!  and try again.")
    sys.exit(1)

# Mininet — if this import fails, you never installed it. Revisit the README.
from mininet.net import Mininet
from mininet.node import OVSController
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.clean import cleanup


# ============================================================
# CONFIGURATION — the dials you might actually need to turn
# ============================================================

# The three probe-up gain values we're testing as our "novel contribution".
# 1.25 is the stock BBRv1 baseline, already captured in Phase 2. Don't add it here.
GAIN_VARIANTS = [1.10, 1.15, 1.20]

# Maps gain float → the .ko module filename we built.
# Yes, we're encoding the gain into the filename. No, there's no better way in a shell env.
# The module must register itself as "bbr_mod" so we can select it via -C bbr_mod.
MODULE_DIR = Path("modules")
MODULE_FILES = {
    1.10: MODULE_DIR / "tcp_bbr_gain110.ko",
    1.15: MODULE_DIR / "tcp_bbr_gain115.ko",
    1.20: MODULE_DIR / "tcp_bbr_gain120.ko",
}

# The CCA name each module exposes after insmod.
# This MUST match whatever name the module registers with tcp_register_congestion_control().
# If you used tcp_bbr.c verbatim with a renamed module, it might still register as "bbr".
# In that case, rename the struct tcp_congestion_ops entry in the C file. You have to.
MODULE_CCA_NAME = {
    1.10: "bbr_mod",   # must match .name field in tcp_congestion_ops in tcp_bbr_gainXXX.c
    1.15: "bbr_mod",
    1.20: "bbr_mod",
}

# Output dirs — one per gain variant. Matches the repo structure.
RESULTS_DIRS = {
    1.10: Path("results/phase3/gain_1.10"),
    1.15: Path("results/phase3/gain_1.15"),
    1.20: Path("results/phase3/gain_1.20"),
}

# Exact same sweep parameters as Phase 2. Because consistency is a virtue (and the analysis script expects it).
BUFFER_SIZES_BYTES  = [10_000, 200_000, 10_000_000]
RTTS_MS             = [10, 40, 100]
BOTTLENECK_BW_MBPS  = 100
ACCESS_BW_MBPS      = 500
ELEPHANT_DURATION_S = 120
NUM_MICE            = 10
MICE_SIZE_MB        = 1
IPERF_PORT_ELEPHANT = 5201
IPERF_PORT_MICE     = 5202


# ============================================================
# MODULE MANAGEMENT — the part that requires kernel privileges
# (and a functioning make toolchain, which WSL2 sometimes mocks you about)
# ============================================================

def unload_bbr_mod():
    """
    Unloads the custom bbr_mod module if it's currently loaded.
    Also unloads stock tcp_bbr if it's somehow in the way.
    We do this before each gain variant to start clean.

    rmmod errors are not necessarily fatal — the module might not be loaded.
    We log and move on, like adults.
    """
    for mod in ["bbr_mod", "tcp_bbr"]:
        result = subprocess.run(
            ["rmmod", mod],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  [module] Unloaded '{mod}'")
        else:
            # Module wasn't loaded — fine. Not every rmmod needs to succeed.
            pass


def load_bbr_mod(ko_path: Path, gain: float) -> bool:
    """
    Loads the custom .ko module for the given gain variant using insmod.
    Validates that the CCA is now available in tcp_available_congestion_control.

    Args:
        ko_path: path to the compiled .ko file
        gain   : the gain value (for logging purposes, not for the kernel)

    Returns:
        True if load succeeded and CCA is available, False otherwise.
    """
    if not ko_path.exists():
        print(f"  [ERROR] Module not found: {ko_path}")
        print(f"          Build it first. See docs/build_module.md.")
        return False

    # insmod — the original "trust me bro" system call
    result = subprocess.run(
        ["insmod", str(ko_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  [ERROR] insmod failed for {ko_path}: {result.stderr.strip()}")
        print(f"          Common causes: module built for wrong kernel version,")
        print(f"          conflicting module already loaded, or WSL2 being WSL2.")
        return False

    print(f"  [module] Loaded {ko_path.name} (gain={gain})")
    time.sleep(0.5)  # give the kernel a moment to register the new CCA. It's not fast.

    # Verify the CCA actually shows up before we waste 9 experiments on a phantom
    available = subprocess.check_output(
        ["sysctl", "net.ipv4.tcp_available_congestion_control"]
    ).decode()

    cca_name = MODULE_CCA_NAME[gain]
    if cca_name not in available:
        print(f"  [ERROR] CCA '{cca_name}' not visible after insmod. Check module source.")
        print(f"          Available: {available.strip()}")
        return False

    print(f"  [module] CCA '{cca_name}' confirmed available.")
    return True


# ============================================================
# TOPOLOGY — identical to Phase 2. Copy-paste is not ideal, but neither is circular imports.
# ============================================================

def build_dumbbell(bw_mbps, rtt_ms, buf_bytes):
    """
    Constructs a dumbbell topology: h_elephant -- r1 -- r2 -- h_recv, with h_mice also on r1.
    Bottleneck is r1<->r2 with tc/netem RTT and tc/HTB rate limiting.

    If this crashes with an OVS error, kill all mininet processes and try again.
    That solves 80% of problems. The other 20% require actual debugging.
    """
    cleanup()

    net = Mininet(controller=OVSController, link=TCLink)

    # Our three actors: the rude elephant, the victimized mice sender, and the receiver
    h_elephant = net.addHost("h_elephant")
    h_mice     = net.addHost("h_mice")
    h_recv     = net.addHost("h_recv")

    r1 = net.addSwitch("r1")
    r2 = net.addSwitch("r2")
    controller = net.addController("c0")

    # Access links: high bw, negligible delay. Not the bottleneck. Should not be the bottleneck.
    net.addLink(h_elephant, r1, bw=ACCESS_BW_MBPS, delay="1ms")
    net.addLink(h_mice,     r1, bw=ACCESS_BW_MBPS, delay="1ms")
    net.addLink(h_recv,     r2, bw=ACCESS_BW_MBPS, delay="1ms")

    # THE bottleneck link — where the science happens and the mice suffer
    one_way_delay_ms = rtt_ms / 2.0
    buf_pkts = max(1, buf_bytes // 1500)  # netem counts packets, not bytes. Delightful.

    net.addLink(
        r1, r2,
        bw=bw_mbps,
        delay=f"{one_way_delay_ms}ms",
        max_queue_size=buf_pkts,
        use_htb=True
    )

    net.build()
    controller.start()
    r1.start([controller])
    r2.start([controller])

    return net, h_elephant, h_mice, h_recv


# ============================================================
# METRIC HELPERS — same as Phase 2. Consistency. It's a thing.
# ============================================================

def get_queue_occupancy(interface="r1-eth2"):
    """
    Reads tc qdisc stats for the bottleneck interface.
    Returns the backlog, drops, and send stats at a single snapshot in time.
    Single snapshot because we're not writing a monitoring daemon, we're writing a research script.
    """
    try:
        out = subprocess.check_output(
            ["tc", "-s", "qdisc", "show", "dev", interface],
            stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        return {}  # tc said no. Log nothing, move on.

    stats = {}

    m = re.search(r"Sent (\d+) bytes (\d+) pkt", out)
    if m:
        stats["bytes_sent"] = int(m.group(1))
        stats["pkts_sent"]  = int(m.group(2))

    m = re.search(r"dropped (\d+), overlimits (\d+)", out)
    if m:
        stats["dropped"]    = int(m.group(1))
        stats["overlimits"] = int(m.group(2))

    # backlog is the number we most care about — this is the standing queue depth
    m = re.search(r"backlog (\d+)b (\d+)p", out)
    if m:
        stats["backlog_bytes"] = int(m.group(1))
        stats["backlog_pkts"]  = int(m.group(2))

    return stats


def parse_iperf3_json(raw_json_str):
    """
    Parses iperf3 JSON output. Returns {goodput_mbps, retransmissions, duration_s}.
    Returns empty dict on failure because iperf3 sometimes just doesn't write valid JSON.
    It happens. We've made peace with it.
    """
    try:
        data = json.loads(raw_json_str)
        end  = data.get("end", {})
        sent = end.get("sum_sent", {})
        return {
            "goodput_mbps":    sent.get("bits_per_second", 0) / 1e6,
            "retransmissions": sent.get("retransmits", 0),
            "duration_s":      sent.get("seconds", 0),
        }
    except (json.JSONDecodeError, KeyError):
        return {}


def jains_fairness(throughputs):
    """
    Jain's Fairness Index. JFI = (sum x_i)^2 / (n * sum x_i^2).
    1.0 = perfectly fair. 1/n = maximally unfair (one winner, all losers crying).
    Named after Raj Jain. Beloved by networking paper reviewers everywhere.
    """
    if not throughputs or all(t == 0 for t in throughputs):
        return 0.0
    n  = len(throughputs)
    s  = sum(throughputs)
    sq = sum(t**2 for t in throughputs)
    return (s ** 2) / (n * sq) if sq > 0 else 0.0


# ============================================================
# CORE EXPERIMENT RUNNER — exactly like Phase 2, but CCA comes from the loaded module
# ============================================================

def run_single_experiment(gain, buf_bytes, rtt_ms):
    """
    Runs one (gain_variant, buffer_size, RTT) configuration.
    The loaded module's CCA name is used for both elephant and mice flows.

    Returns a dict of all metrics, serializable to JSON.

    Args:
        gain     : float, pacing gain value (1.10 / 1.15 / 1.20)
        buf_bytes: int, buffer size in bytes
        rtt_ms   : int, RTT in milliseconds
    """
    cca = MODULE_CCA_NAME[gain]  # whatever the module registered as

    print(f"\n{'='*60}")
    print(f"  Running: GAIN={gain}  BUF={buf_bytes//1000}KB  RTT={rtt_ms}ms  CCA={cca}")
    print(f"{'='*60}")

    net, h_elephant, h_mice, h_recv = build_dumbbell(
        bw_mbps=BOTTLENECK_BW_MBPS,
        rtt_ms=rtt_ms,
        buf_bytes=buf_bytes
    )

    result = {
        "pacing_gain":             gain,         # the actual independent variable
        "cca":                     cca,           # what the kernel calls it
        "buffer_bytes":            buf_bytes,
        "rtt_ms":                  rtt_ms,
        "timestamp":               datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mice_fcts_s":             [],
        "elephant_goodput_mbps":   None,
        "elephant_retransmissions":None,
        "queue_stats_midpoint":    {},
        "jains_fairness":          None,
    }

    recv_ip = h_recv.IP()

    try:
        # ---- iperf3 servers on receiver ----
        h_recv.cmd(f"iperf3 -s -p {IPERF_PORT_ELEPHANT} -D --logfile /tmp/iperf3_elephant_server.log")
        h_recv.cmd(f"iperf3 -s -p {IPERF_PORT_MICE}     -D --logfile /tmp/iperf3_mice_server.log")
        time.sleep(0.5)  # servers need a moment. They're not miracle workers.

        # ---- Sanity-check: is our CCA actually available? ----
        available = subprocess.check_output(
            ["sysctl", "net.ipv4.tcp_available_congestion_control"]
        ).decode()
        if cca not in available:
            # If we get here, the module load function should have caught this already.
            # But just in case the kernel changed its mind between then and now.
            print(f"  [ERROR] CCA '{cca}' disappeared between module load and experiment. "
                  f"Kernel is gaslighting us.")
            result["error"] = f"CCA {cca} not available at experiment start"
            return result

        # ---- Launch BBR elephant with modified gain ----
        elephant_cmd = (
            f"iperf3 -c {recv_ip} -t {ELEPHANT_DURATION_S} "
            f"-C {cca} -J -p {IPERF_PORT_ELEPHANT} "
            f"> /tmp/iperf3_elephant_client.json 2>&1 &"
        )
        h_elephant.cmd(elephant_cmd)
        elephant_pid = h_elephant.cmd("echo $!").strip()
        print(f"  [elephant] PID={elephant_pid}, running for {ELEPHANT_DURATION_S}s, gain={gain}...")

        # Head start: let the elephant fill the pipe before mice arrive.
        # This is the whole experimental setup — mice entering a pre-congested bottleneck.
        time.sleep(2)

        # ---- Sequential mice flows — same as Phase 2 ----
        print(f"  [mice] Sending {NUM_MICE} sequential mice ({MICE_SIZE_MB}MB each, CCA={cca})...")
        mice_fcts = []

        for i in range(NUM_MICE):
            t_start = time.monotonic()

            # 30s timeout: shallow buffers cause mice to stall indefinitely. We've seen it. It's grim.
            mice_cmd = (
                f"timeout 30 iperf3 -c {recv_ip} -n {MICE_SIZE_MB}M "
                f"-C {cca} -J -p {IPERF_PORT_MICE} "
                f"> /tmp/iperf3_mice_{i}.json 2>&1"
            )
            h_mice.cmd(mice_cmd)  # blocking — next mouse queues behind this one

            fct = time.monotonic() - t_start
            mice_fcts.append(fct)
            print(f"    Mouse {i+1}/{NUM_MICE}: FCT={fct:.4f}s")

        result["mice_fcts_s"] = mice_fcts

        # ---- Queue snapshot at "steady state" ----
        # By the time all mice finish, we're well into the elephant's ProbeBW cycle.
        # The standing queue should be fully developed — that's the whole point.
        result["queue_stats_midpoint"] = get_queue_occupancy("r1-eth2")

        # ---- Wait for elephant to finish ----
        elapsed   = 2 + sum(mice_fcts)
        remaining = max(0, ELEPHANT_DURATION_S - elapsed)
        if remaining > 0:
            print(f"  [elephant] Waiting {remaining:.1f}s for it to finish being rude...")
            time.sleep(remaining)

        # ---- Parse elephant JSON ----
        try:
            with open("/tmp/iperf3_elephant_client.json") as f:
                raw = f.read()
            ep = parse_iperf3_json(raw)
            result["elephant_goodput_mbps"]      = ep.get("goodput_mbps")
            result["elephant_retransmissions"]   = ep.get("retransmissions")
        except FileNotFoundError:
            print("  [WARN] Elephant iperf3 output not found. It may have crashed quietly.")

        # ---- Jain's Fairness Index ----
        mice_tputs = [(MICE_SIZE_MB * 8) / fct for fct in mice_fcts if fct > 0]
        all_tputs  = mice_tputs[:]
        if result["elephant_goodput_mbps"]:
            all_tputs.append(result["elephant_goodput_mbps"])
        result["jains_fairness"] = jains_fairness(all_tputs)

        print(
            f"  [done] avg_fct={sum(mice_fcts)/len(mice_fcts):.4f}s  "
            f"elephant={result['elephant_goodput_mbps']:.2f}Mbps  "
            f"JFI={result['jains_fairness']:.4f}"
        )

    except Exception as e:
        print(f"  [ERROR] Experiment exploded: {e}")
        result["error"] = str(e)

    finally:
        # Stop Mininet. Always. Every time. Without exception.
        # Leftover Mininet state has ruined many experiments and many moods.
        net.stop()
        cleanup()
        subprocess.run(["pkill", "-f", "iperf3"], capture_output=True)

    return result


# ============================================================
# RESULT SERIALIZATION
# ============================================================

def save_result(result, results_dir: Path):
    """
    Saves one result dict to a JSON file named by gain, buffer, rtt, and timestamp.
    Keeps the same naming convention as Phase 2 because the analysis script will thank us.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    gain = result.get("pacing_gain", "unknown")
    buf  = result.get("buffer_bytes", 0)
    rtt  = result.get("rtt_ms", 0)
    ts   = result.get("timestamp", "unknown").replace(":", "-").replace(".", "-")

    # gain_1.10 → stored as gain110 in filename so shells don't cry about dots
    gain_str = f"gain{int(gain * 100)}"
    filename = results_dir / f"bbr_{gain_str}_{buf}B_{rtt}ms_{ts}.json"

    with open(filename, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  [saved] {filename}")
    return filename


# ============================================================
# MAIN SWEEP
# ============================================================

def main():
    """
    Outer loop: iterates over GAIN_VARIANTS, loading/unloading kernel modules between each.
    Inner loop: runs the full 9-config Phase 2 sweep per gain variant.

    Total: 3 gains × 9 configs × ~2 min = ~54 minutes.
    Or longer, if WSL2 is having a bad day. It often is.

    The 1.25 baseline is NOT re-run here — it's the Phase 2 BBRv1 data.
    The analysis script reads both dirs and plots them together.
    """
    setLogLevel("warning")  # Mininet is chatty. We are not here for chat.

    total_configs = len(GAIN_VARIANTS) * len(BUFFER_SIZES_BYTES) * len(RTTS_MS)

    print("=" * 60)
    print("  CSE 534 - Phase 3: Pacing Gain Modification Sweep")
    print(f"  Gain variants tested: {GAIN_VARIANTS}  (baseline 1.25 = Phase 2 data)")
    print(f"  Configs per variant:  {len(BUFFER_SIZES_BYTES) * len(RTTS_MS)}")
    print(f"  Total experiments:    {total_configs}")
    print(f"  Estimated runtime:    ~{total_configs * 2} minutes (optimistic)")
    print("=" * 60)

    # Validate all module files exist before starting — better to fail now than 40 minutes in
    print("\n[pre-flight] Checking module files...")
    for gain in GAIN_VARIANTS:
        ko = MODULE_FILES[gain]
        if ko.exists():
            print(f"  OK  {ko}")
        else:
            print(f"  MISSING  {ko}")
            print(f"  Build instructions: see docs/build_module.md")
            print(f"  Aborting. Fix this first.")
            sys.exit(1)
    print("[pre-flight] All module files present. Proceeding.\n")

    experiment_num = 0
    all_configs    = list(itertools.product(BUFFER_SIZES_BYTES, RTTS_MS))

    for gain in GAIN_VARIANTS:
        print(f"\n{'#'*60}")
        print(f"# GAIN VARIANT: {gain}  (module: {MODULE_FILES[gain].name})")
        print(f"{'#'*60}")

        # Always unload first — you never know what's lurking in the kernel
        print(f"\n[module] Unloading any existing BBR module...")
        unload_bbr_mod()

        # Load our custom module for this gain variant
        print(f"[module] Loading {MODULE_FILES[gain].name}...")
        success = load_bbr_mod(MODULE_FILES[gain], gain)
        if not success:
            print(f"[SKIP] Skipping gain={gain} — module load failed. Fix it and re-run.")
            continue  # skip this gain, continue to next. Partial results > no results.

        for buf, rtt in all_configs:
            experiment_num += 1
            print(f"\n[{experiment_num}/{total_configs}] "
                  f"GAIN={gain}  BUF={buf//1000}KB  RTT={rtt}ms")

            result    = run_single_experiment(gain=gain, buf_bytes=buf, rtt_ms=rtt)
            saved_to  = save_result(result, RESULTS_DIRS[gain])

            # Brief inter-experiment pause. OVS switches need to decompress emotionally.
            time.sleep(5)

        # Unload before the next variant — clean kernel state for each gain value
        print(f"\n[module] Unloading gain={gain} module before next variant...")
        unload_bbr_mod()

    print(f"\n{'='*60}")
    print(f"  Phase 3 complete. {experiment_num} experiments run.")
    print(f"  Results:")
    for gain in GAIN_VARIANTS:
        print(f"    gain={gain}: {RESULTS_DIRS[gain]}/")
    print(f"  Baseline (gain=1.25): results/phase2/bbrv1/")
    print(f"  Next step: python3 scripts/phase3_analysis.py")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
