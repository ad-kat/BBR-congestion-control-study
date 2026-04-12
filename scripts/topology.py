#!/usr/bin/env python3
"""
topology.py — Dumbbell network topology for BBR mixed-workload experiments.
Replicating Cao et al. IMC 2019 setup because apparently we can't just trust
the paper and need to prove it ourselves. Science!

IMPORTANT: iperf3 must run INSIDE this process while Mininet is alive.
Network namespaces die when Mininet exits, so trying to reach h1/h3
from the shell after this script returns is a fool's errand.
"""

from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import argparse
import time
import os


def build_dumbbell(bw_mbps=100, rtt_ms=40, buf_kb=200):
    """
    Classic dumbbell: 2 senders → bottleneck switch → 1 receiver.
    We use OVSKernelSwitch because we need actual kernel-space TCP,
    not some userspace fantasy that ignores congestion control entirely.

    Args:
        bw_mbps : bottleneck link bandwidth in Mbps (default: 100)
        rtt_ms  : one-way delay is rtt_ms/2 ms each side (default: 40ms RTT)
        buf_kb  : bottleneck queue size in kilobytes (default: 200 KB)
    """

    # Half the RTT per link side. Basic math, but let's be explicit
    # because someone WILL forget this at 2am before the deadline.
    delay_ms = rtt_ms / 2.0

    # Convert KB → bytes for netem. Because netem speaks bytes
    # and we speak English and here we are.
    buf_bytes = buf_kb * 1024

    # OVSBridge in standalone mode — handles L2 forwarding itself without
    # needing an external OpenFlow controller that WSL2 will quietly fail to start.
    # OVSKernelSwitch + Controller looked great on paper. This actually works.
    net = Mininet(switch=OVSBridge, link=TCLink, autoSetMacs=True,
                  controller=None)

    info("*** Creating nodes\n")
    # Two senders: h1 runs the elephant BBR flow, h2 runs mice flows
    h1 = net.addHost('h1')   # elephant sender — the bully of this experiment
    h2 = net.addHost('h2')   # mice sender — the victim

    # One receiver to collect their misery
    h3 = net.addHost('h3')

    # Two switches to form the dumbbell. Glamorous? No. Functional? Barely.
    s1 = net.addSwitch('s1')  # left switch (sender side)
    s2 = net.addSwitch('s2')  # right switch (receiver side)

    info("*** Wiring up the dumbbell\n")
    # Access links (sender → s1): high bandwidth, low delay
    # These aren't the bottleneck, so give them 1 Gbps to not be the problem
    net.addLink(h1, s1, bw=1000, delay='0.1ms')
    net.addLink(h2, s1, bw=1000, delay='0.1ms')

    # THE BOTTLENECK LINK — the entire reason this experiment exists.
    # HTB limits bandwidth; netem adds RTT; limit sets the queue size.
    # max_queue_size is in packets (MTU ~1500B), so we convert from bytes.
    max_queue_pkts = max(1, buf_bytes // 1500)
    net.addLink(
        s1, s2,
        bw=bw_mbps,
        delay=f'{delay_ms:.2f}ms',
        max_queue_size=max_queue_pkts,
        use_htb=True       # HTB for bandwidth shaping — netem alone isn't enough
    )

    # Access link (s2 → receiver): again, not the bottleneck
    net.addLink(s2, h3, bw=1000, delay='0.1ms')

    net.build()
    net.start()

    info(f"*** Topology ready: {bw_mbps} Mbps / {rtt_ms} ms RTT / {buf_kb} KB buffer\n")
    return net, h1, h2, h3


def verify_connectivity(h1, h3):
    """
    Ping h1 → h3 before wasting time on iperf3.
    If this fails, nothing else will work either.
    """
    info("*** Checking connectivity h1 → h3\n")
    result = h1.cmd(f'ping -c 3 -W 2 {h3.IP()}')
    info(result)
    if '0 received' in result or '100% packet loss' in result:
        info("*** [!] Ping failed — topology has a problem\n")
        return False
    info("*** Connectivity confirmed. Surprising how rarely this just works.\n")
    return True


def run_iperf3(h1, h3, cca, duration, out_file):
    """
    Start iperf3 server on h3, run client on h1, save JSON to out_file.
    Everything happens inside Mininet's namespace — because that's the
    only place these hosts actually exist.

    Args:
        h1       : Mininet sender host
        h3       : Mininet receiver host (iperf3 server)
        cca      : congestion control algorithm string e.g. 'bbr', 'cubic'
        duration : iperf3 test duration in seconds
        out_file : path to write iperf3 JSON output
    """
    info(f"*** Starting iperf3 server on h3 ({h3.IP()})\n")
    # -D daemonizes; -1 exits after one client connection so it doesn't linger
    h3.cmd('iperf3 -s -D -1')
    time.sleep(1)  # Give the server a moment to actually start. Impatience causes bugs.

    info(f"*** Running iperf3 client: h1 → h3 | CCA={cca} | {duration}s\n")
    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)

    # Run iperf3 and capture output — -J for JSON, -C for CCA selection
    cmd = (
        f'iperf3 --client {h3.IP()} '
        f'--time {duration} '
        f'--cong {cca} '
        f'--json '
        f'--interval 1'
    )
    output = h1.cmd(cmd)

    # Write the JSON output to file — h1.cmd() returns stdout as a string
    with open(out_file, 'w') as f:
        f.write(output)

    info(f"*** Result saved to: {out_file}\n")

    # Kill any lingering iperf3 server processes. They will haunt you otherwise.
    h3.cmd('pkill -f "iperf3 -s" 2>/dev/null || true')


def main():
    parser = argparse.ArgumentParser(description='BBR dumbbell topology + iperf3 runner')
    parser.add_argument('--bw',       type=float, default=100,    help='Bottleneck BW in Mbps')
    parser.add_argument('--rtt',      type=float, default=40,     help='RTT in ms')
    parser.add_argument('--buf',      type=float, default=200,    help='Buffer size in KB')
    parser.add_argument('--cca',      type=str,   default=None,   help='CCA to test (bbr/cubic)')
    parser.add_argument('--duration', type=int,   default=30,     help='iperf3 duration in seconds')
    parser.add_argument('--out',      type=str,   default=None,   help='Output JSON file path')
    parser.add_argument('--cli',      action='store_true',        help='Drop into Mininet CLI')
    args = parser.parse_args()

    setLogLevel('info')

    info(f"*** Building topology: {args.bw} Mbps / {args.rtt} ms RTT / {args.buf} KB buf\n")
    net, h1, h2, h3 = build_dumbbell(
        bw_mbps=args.bw,
        rtt_ms=args.rtt,
        buf_kb=args.buf
    )

    verify_connectivity(h1, h3)

    if args.cli:
        # Useful for debugging. Not for production. This is not production.
        CLI(net)
    elif args.cca and args.out:
        # The normal path: run iperf3 and save results
        run_iperf3(h1, h3, args.cca, args.duration, args.out)
    else:
        info("*** No --cca/--out specified and no --cli. Starting CLI by default.\n")
        CLI(net)

    net.stop()
    info("*** Done. The network has been gracefully murdered.\n")


if __name__ == '__main__':
    main()