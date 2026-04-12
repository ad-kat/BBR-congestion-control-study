# Paper Notes For Replication

## Cao et al. (IMC 2019)

Paper: "When to use and when not to use BBR: An empirical analysis and evaluation study"  
Link: https://netsys.cs.stonybrook.edu/sites/netsys.cs.stonybrook.edu/files/2024-06/p130-Cao.pdf

### Important figure-number correction

In the 2019 IMC paper, Figure 2 is the testbed diagram, not the throughput heatmap. The goodput heatmaps are in Figure 5, the latency heatmaps are in Figure 6, and the fairness bandwidth-share plots are in Figure 8.

### Exact setup details to mirror

- Testbeds:
  - Mininet/LAN use a dumbbell topology.
  - Minimum RTT between hosts in the Mininet/LAN setup: 40 us.
  - WAN setup places senders at Stony Brook University, receiver at Rutgers University.
  - Minimum WAN RTT: 7 ms.
  - Host NIC peak bandwidth: 1 Gbps.
- Traffic-control implementation:
  - `tc netem` for delay.
  - `tc tbf` for bandwidth and bottleneck buffer size.
  - Traffic shaping is applied on a separate router, not on end hosts.
  - BBR version studied: Linux 4.15.
- LAN goodput study:
  - 640 configurations total.
  - 5 runs per configuration.
  - 60 seconds per run.
  - RTT values: 5, 10, 25, 50, 75, 100, 150, 200 ms.
  - Bandwidth values: 10, 20, 50, 100, 250, 500, 750, 1000 Mbps.
  - Buffer sizes: 0.1, 1, 10, 20, 50 MB.
- Heatmaps highlighted in the paper:
  - "Shallow buffer" example: 100 KB.
  - "Deep buffer" example: 10 MB.

### Directly stated numeric results

These are the exact values stated in the text and are safer replication anchors than reading colors off heatmaps.

| Scenario | Cubic | BBR | Note |
| --- | ---: | ---: | --- |
| 100 KB buffer, 200 ms RTT, 500 Mbps BW | 179.6 Mbps | 386.0 Mbps | BBR goodput improvement: 115% |
| Average loss percentage at 100 KB buffer | 0.9% | 10.1% | BBR much lossier in shallow buffers |
| Average loss percentage at 10 MB buffer | 1.3% | 0.8% | Loss gap reverses in deep buffers |
| 25 ms RTT, 500 Mbps BW, retransmits at 100 KB buffer | 1,649 | 235,798 | Example of shallow-buffer aggressiveness |
| 25 ms RTT, 500 Mbps BW, retransmits at 10 MB buffer | 471 | 0 | Same path after increasing buffer |

### Fairness results stated in text

- Mininet fairness experiment:
  - Link bandwidth: 1 Gbps.
  - RTT: 20 ms.
  - Buffer varied from 10 KB to 100 MB.
- Reported outcomes:
  - At 10 KB buffer, BBR gets 94% of network goodput.
  - At 10 MB buffer, Cubic gets about 3x the bandwidth of BBR.
  - Around 5 MB buffer, BBR and Cubic share bandwidth roughly evenly.
- WAN fairness observation:
  - Their WAN path appears to have an in-the-wild bottleneck buffer around 20 KB.

### Table 1 values

This table is directly usable as a ground-truth fairness/loss reference for the mixed BBR/Cubic experiment under 1 Gbps bandwidth and 20 ms RTT in Mininet.

| Buffer (bytes) | BBR Retr# | Cubic Retr# |
| ---: | ---: | ---: |
| 1e4 | 26,746 | 908 |
| 1e5 | 305,029 | 1,398 |
| 1e6 | 68,741 | 3,987 |
| 5e6 | 1,324 | 1,145 |
| 1e7 | 204 | 794 |
| 5e7 | 0 | 7 |
| 1e8 | 0 | 16 |

### Replication takeaways

- The main decision boundary is relative buffer size versus BDP:
  - Small buffer relative to BDP favors BBR goodput.
  - Large buffer relative to BDP favors Cubic goodput.
- For our project, the easiest defensible reproduction targets are:
  - shallow vs deep buffer comparisons,
  - retransmission gap,
  - mixed BBR/Cubic fairness swing as buffer size changes.
- The paper does not publish a full numeric table for every heatmap cell in Figure 5. Exact per-cell goodput values would need either:
  - author data,
  - reproduction from experiment logs,
  - or manual digitization from the figure image.

## Scherrer et al. (IMC 2022)

Paper: "Model-Based Insights on the Performance, Fairness, and Stability of BBR"  
Link: https://netsec.ethz.ch/publications/papers/scherrer_bbr_imc22.pdf

### Queueing and standing-queue results

- For BBRv1 in a single-bottleneck network with equal propagation delay and a queue only at the bottleneck, the paper states the steady-state queue length is:
  - `q = d * C`
  - This is 1 BDP, since `BDP = d * C`.
- For BBRv2 under the same single-bottleneck assumptions, the equilibrium queue is:
  - `q = ((N - 1) / (4N + 1)) * d * C`
  - For many flows, this approaches about 0.25 BDP.
- Their theoretical summary states BBRv2 reduces queue length by at least 75% relative to BBRv1 when the buffer is large enough to accommodate the BBRv1 equilibrium queue.

### What this means for our project

- This 2022 paper supports the claim that BBRv1 builds a persistent standing queue in deep-buffer settings.
- It does not support a universal "1.5 BDP" queue claim for the specific model analyzed in the paper.
- The explicit queue formulas in the paper are:
  - BBRv1 deep-buffer equilibrium: about 1 BDP.
  - BBRv2 equilibrium under their assumptions: less than BBRv1, approaching 0.25 BDP for large `N`.
- For hypothesis framing, this is the safer reading:
  - BBRv1 can maintain a persistent non-trivial queue even though its design goal is low delay.
  - BBRv2 usually reduces that queue, but does not eliminate queueing problems in all settings.

### Other directly useful insights

- BBRv1 is highly unfair to loss-based CCAs in shallow drop-tail buffers and can nearly starve them.
- BBRv1 causes high loss, up to about 20%, under drop-tail.
- BBRv2 mostly improves fairness and buffer usage, but the paper identifies a new issue:
  - in large drop-tail buffers above 5 BDP, BBRv2 can again increase buffer utilization because of startup-phase `inflight_hi` behavior.

## Notes For Our Replica

- If we cite Cao et al. for experiment design, cite:
  - exact RTT values,
  - exact bandwidth values,
  - exact buffer sizes,
  - experiment duration and repetition count.
- If we cite Scherrer et al. for queueing intuition, cite:
  - BBRv1 standing queue in deep buffers,
  - BBRv2 queue reduction,
  - and avoid overstating the queue as "1.5 BDP" unless another source explicitly supports that number.
