# BBR-congestion-control-study
This project evaluates the performance of modern TCP congestion control algorithms, focusing on Google’s BBR. Using controlled network experiments, we compare BBR with CUBIC and Reno under mixed traffic workloads and analyze throughput, latency, and fairness to understand congestion behavior and identify potential improvements.


# Evaluating and Improving BBR Congestion Control

## Overview
This project evaluates the performance of modern TCP congestion control algorithms under mixed network workloads and proposes an improvement to Google's BBR algorithm.

We compare:
- BBR
- CUBIC
- Reno

Metrics analyzed:
- Throughput
- Latency
- Packet loss
- Fairness

## Research Motivation
Modern Internet traffic contains a mix of short-lived flows (web requests) and long-lived flows (video streaming, file transfers).
Existing congestion control algorithms often fail to maintain fairness and low latency under mixed workloads.

This project studies these behaviors and proposes a modification to improve short-flow latency.

## Methodology
1. Deploy congestion control algorithms on Linux
2. Use network emulation to simulate constrained networks
3. Run controlled traffic workloads
4. Collect metrics and analyze results

## Repository Structure
(brief explanation of folders)

## References
BBR: Bottleneck Bandwidth and RTT
SIGCOMM 2016
