
## BBR Reading List (In Order)

### 🟢 Level 1 — Background (Read These First)
*To understand the problem BBR is solving before you can understand BBR itself.*

**1. "TCP Congestion Control: A Systems Approach"**
 https://tcpcc.systemsapproach.org/intro.html

Read: Chapters 1–4 for the following: why congestion collapse happens, how slow-start works, what CUBIC does, and why loss-based control has limits. 

**2. LWN.net: "BBR Congestion Control" by Jonathan Corbet (2016)**
 https://lwn.net/Articles/701165/

A plain-English journalist wrote this when BBR was first released for Linux. It's 3 pages long and explains *why* BBR is different without any math. Read this before touching any paper.

---

### 🟡 Level 2 — The Two Required Papers
*Professor assigned these.*

**3. Cardwell et al. — "BBR: Congestion-Based Congestion Control" (2016)**
 https://queue.acm.org/detail.cfm?id=3022184

This is the original BBR paper written by the Google engineers who built it. The ACM Queue version is more readable than the CACM version. Focus laid on: the motivation (Section 1), how BtlBw and RTprop are measured (Section 2), and the 4 states (Section 3).

**4. Cao et al. — "When to Use and When Not to Use BBR" (IMC 2019)**
 https://www3.cs.stonybrook.edu/~anshul/imc19_bbr.pdf

 Focusing on: Figure 1 (how BBR works diagram), Figure 2 (their experiment setup), and the decision tree result. This paper directly shapes your experimental design.

---

### 🟠 Level 3 — Understanding BBR's Problems
*These explain the specific weaknesses your project is targeting.*

**5. APNIC Blog: "When to Use and Not Use BBR" (2020)**
 https://blog.apnic.net/2020/01/10/when-to-use-and-not-use-bbr/

This is a blog post summarizes the writer's own IMC paper in plain English, with clear figures. To be read *alongside* Paper #4 — it makes the heatmaps and decision tree much easier to understand.

**6. Song et al. — "Improvement of RTT Fairness Problem in BBR by Gamma Correction" (2021)**
 https://pmc.ncbi.nlm.nih.gov/articles/PMC8234792/

This paper explains *why* BBR builds a standing queue (the persistent queue problem) very clearly in Section 3. Even if you don't end up using their specific fix (gamma correction), their diagnosis of the root cause is excellent and directly relevant to your modification idea.

---

### 🔵 Level 4 — Survey (The Big Picture)
*Read this once you've done Levels 1–3. It ties everything together.*

**7. "BBR Congestion Control Algorithms: Evolution, Challenges and Future Directions" (ACM Computing Surveys, 2024)**
 https://dl.acm.org/doi/10.1145/3793537

This is a brand-new survey paper that covers BBRv1 → BBRv2 → BBRv3 and all the known problems (RTT unfairness, high retransmissions, deep buffer issues, mixed elephant/mice flows). Not read cover to cover, but used as a reference. The section on elephant vs. mice flows is directly relevant to project angle.

---

### 🔴 Level 5 — The Kernel (The Coding Part)

**8. The Linux BBR source code**
 https://github.com/google/bbr/blob/v3/net/ipv4/tcp_bbr.c

Find the line: `static const int bbr_pacing_gain[]`. That's the array potentially worth modifying. 

**9. Stanford CS 244 BBR Reproduction (blog post, 2017)**
 https://reproducingnetworkresearch.wordpress.com/2017/06/05/cs-244-17-congestion-based-congestion-control-with-bbr/

Students at Stanford tried to reproduce the original BBR paper results using Mininet. TIt talks about every pitfall they hit — wrong `tc` setup, kernel crashes, netem configuration. This will save hours of debugging.

---
