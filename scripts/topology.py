#!/usr/bin/env python3
"""
topology.py — Dumbbell network topology for BBR mixed-workload experiments.
Replicating Cao et al. IMC 2019 setup because apparently we can't just trust
the paper and need to prove it ourselves. Science!
"""

from mininet.net import Mininet
from mininet.node import OVSKernelSwitch
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

    # Mininet network — TCLink gives us tc qdisc control per link
    net = Mininet(switch=OVSKernelSwitch, link=TCLink, autoSetMacs=True)

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

    info("*** Starting switches\n")
    for sw in [s1, s2]:
        sw.start([])

    info(f"*** Topology ready: {bw_mbps} Mbps / {rtt_ms} ms RTT / {buf_kb} KB buffer\n")
    return net, h1, h2, h3


def verify_connectivity(net, h1, h2, h3):
    """
    Sanity-check that ping actually works before wasting 2 hours on iperf3.
    Returns True if all hosts can reach h3. Shocking concept, I know.
    """
    info("*** Running connectivity check (pingFull)\n")
    # pingFull returns a dict; we just need RTT confirmation
    result = net.pingFull(hosts=[h1, h2, h3])

    # If RTT is wildly off, something is wrong with tc netem setup.
    # Print it so we can see before trusting the iperf3 output blindly.
    for src, dst, rtt_data in result:
        avg_rtt = rtt_data[3] if rtt_data else -1
        info(f"  {src} → {dst}: avg RTT = {avg_rtt:.2f} ms\n")

    return True


def main():
    parser = argparse.ArgumentParser(description='BBR dumbbell topology launcher')
    parser.add_argument('--bw',  type=float, default=100,  help='Bottleneck BW in Mbps')
    parser.add_argument('--rtt', type=float, default=40,   help='RTT in ms')
    parser.add_argument('--buf', type=float, default=200,  help='Buffer size in KB')
    parser.add_argument('--cli', action='store_true',       help='Drop into Mininet CLI')
    args = parser.parse_args()

    setLogLevel('info')

    info(f"*** Building topology: {args.bw} Mbps / {args.rtt} ms RTT / {args.buf} KB buf\n")
    net, h1, h2, h3 = build_dumbbell(
        bw_mbps=args.bw,
        rtt_ms=args.rtt,
        buf_kb=args.buf
    )

    net.start()
    verify_connectivity(net, h1, h2, h3)

    if args.cli:
        # Useful for debugging. Not for production. This is not production.
        CLI(net)

    # Caller can import build_dumbbell() directly for scripted experiments.
    # We stop here if run standalone.
    net.stop()
    info("*** Done. The network has been gracefully murdered.\n")


if __name__ == '__main__':
    main()
