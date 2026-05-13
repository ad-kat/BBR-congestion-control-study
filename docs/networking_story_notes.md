# 🌐 The Epic Saga of How Your Data Actually Gets Anywhere
### CSE 534 — Complete Story-Based Notes (Spring 2026)
*A tale of bits, packets, routers, and the occasional disaster*

---

## Prologue: The World Before the Internet Was Cool

Picture this: it's the 1980s. You want to send a message to someone across the country. You either mail a letter (slow) or pick up a phone (expensive). Computers existed, but they were lonely islands — giant, expensive boxes that couldn't talk to each other. Engineers looked at this situation and thought, *"We can do better."* And so began the story of computer networking — a story that involves everything from literal electrical signals on copper wire all the way up to Google secretly owning half the internet. Let's go layer by layer, bottom to top, and figure out how your cat video actually gets from YouTube to your eyeballs.

---

## Chapter 1: The Physical Layer — "It's Just Vibes (and Electrons)"

Before any of the clever stuff can happen, someone has to figure out how to make a `1` and a `0` actually travel somewhere. That's the **Physical Layer's** job, and it is blissfully dumb — it has no idea what those bits mean, it just shoves them across a medium.

### What Does the Physical Layer Actually Do?

The physical layer converts bits into signals and back. A `1` might be a high voltage, a flash of light in a fiber optic cable, or a particular radio wave frequency. A `0` is the other thing. The medium can be copper wire (Ethernet cable), fiber optic glass, or air (WiFi). That's literally it. No addresses, no error checking at this level — just raw signal.

### The Data Link Layer (Layer 2) — "Finally, Some Structure"

Sitting just above the physical layer, the **Data Link Layer** has two sub-layers with very important jobs:

**Logical Link Control (LLC):** Packages bits into *frames* — chunks of data with a header and a trailer — and performs error detection. Because the physical layer is basically sending signals into the void and hoping for the best, the data link layer adds a **CRC (Cyclic Redundancy Check)** so the receiver can detect corrupted frames. What happens if a packet is corrupted? Two options: Ethernet drops it and lets higher layers deal with it; WiFi retransmits it right there.

**Medium Access Control (MAC):** When multiple devices share the same wire or air, they need rules for who gets to talk when. This is the MAC sublayer's problem. Without it, everyone shouts at once and nobody hears anything. The MAC address is a 48-bit hardware address burned into your network card — think of it as your device's physical name, like "the blue house on Elm Street" as opposed to the city/state/zip of an IP address.

### Ethernet — The LAN Standard That Won Everything

Ethernet is the dominant wired LAN technology. An Ethernet frame looks like this:

`[Preamble | Destination MAC | Source MAC | Type | Data | Pad | CRC]`

When an Ethernet frame is sent on a shared bus, **every device on the bus receives it**. Each device checks the destination MAC address and decides whether to pay attention or ignore it. This broadcast nature is important for understanding why hubs are terrible and switches are great (more on that shortly).

### The Collision Problem: CSMA/CD

When multiple devices share the same medium, collisions are possible — two devices transmit at once, the signals overlap, and everyone gets garbage. Ethernet uses **CSMA/CD (Carrier Sense Multiple Access / Collision Detection)** to handle this:

1. Before transmitting, **listen** to see if someone else is already talking (Carrier Sense)
2. If the channel is idle, transmit
3. While transmitting, keep listening for collisions (Collision Detection)
4. If a collision is detected, send a jam signal, stop, and wait a **random** backoff time before trying again
5. The random backoff prevents the same two devices from colliding again immediately — it uses **binary exponential backoff**, doubling the wait range each time

### WiFi — CSMA/CD's Problematic Cousin: CSMA/CA

WiFi uses **CSMA/CA (Collision Avoidance)** instead of CSMA/CD. Why? Because detecting collisions is hard when you're transmitting radio waves — you can't easily hear yourself and detect a collision simultaneously. Also, the **hidden terminal problem**: device A and device C can both hear B but not each other. A thinks the channel is free, C thinks the channel is free, they both transmit to B at the same time — collision at B. WiFi solves this with Request-to-Send/Clear-to-Send (RTS/CTS) handshakes, though this adds overhead. WiFi is complicated (variable sending rates, mesh networks, power saving modes, security with WEP/WPA/802.11x), which is why entire courses exist just for wireless networking.

### Hubs, Bridges, Switches — A Hardware Evolution Story

This is a story of getting slightly smarter each generation:

**Hubs (Layer 1):** A hub is just a repeater. It receives a signal and blasts it out every other port. It has no idea what a MAC address is. It creates a single **collision domain** — every device connected to the hub competes for the same bandwidth. Terrible at scale.

**Bridges (Layer 2):** A bridge learns which MAC addresses are on which port by watching traffic. When it sees a frame, it either forwards it to the correct port (if it knows the destination) or floods it everywhere (if it doesn't). This **segments the collision domain** — devices on different bridge ports don't collide with each other. This was a big improvement.

**Switches (Layer 2):** Modern switches are multi-port bridges with hardware acceleration. They maintain a **MAC address table** mapping MAC addresses to ports. When a frame arrives, the switch looks up the destination MAC and forwards it only to the right port — no flooding (except for unknown destinations, broadcast, and multicast). Switches create separate collision domains per port. Most modern networks use switches and routers, sometimes in the same device.

**Routers (Layer 3):** Routers operate at the network layer, dealing with IP addresses, not MAC addresses. Critically, **routers isolate broadcast domains** — a broadcast frame (destined for MAC `ff:ff:ff:ff:ff:ff`) does NOT cross a router. This is why your home WiFi broadcasts don't escape to the rest of the internet and take it down.

### ARP — The Layer 2.5 Glue

Here's a gap in the story: your computer knows the IP address of the machine it wants to talk to (thanks to DNS, which we'll get to), but Ethernet needs a MAC address to actually deliver a frame on the local network. How do you get the MAC from the IP?

**ARP (Address Resolution Protocol)** to the rescue. It's called "Layer 2.5" because it sits awkwardly between layers — it has no IP header and it's not part of Ethernet either.

The process: your computer broadcasts an ARP request: *"Hey everyone, who has IP address 192.168.1.254? Tell me your MAC address!"* The machine with that IP responds: *"That's me! My MAC is 00:19:55:35:1a:d0."* Your computer caches this mapping in its ARP table and uses the MAC to build Ethernet frames going forward.

---

## Chapter 2: The Network Layer — "Who Are You and How Do I Find You?"

Now we leave the local network and enter the wide world of the internet. The **Network Layer** has two fundamental jobs: **routing** (deciding which path a packet should take) and **forwarding** (actually moving the packet from input port to output port). Think of routing as planning a road trip on a map, and forwarding as the act of turning the steering wheel at each intersection.

### IP — The Universal Language

The **Internet Protocol (IP)** is the glue that holds everything together. Every device on the internet speaks IP. An IP packet (datagram) has a header containing:

- **Source and Destination IP address** (32 bits each in IPv4)
- **TTL (Time to Live):** decremented at each router; when it hits 0, the packet is dropped. This prevents packets from looping forever. The internet is full of enough problems without immortal zombie packets wandering around.
- **Protocol:** tells the receiver what's inside (TCP, UDP, ICMP, etc.)
- **Header checksum**
- **Fragmentation fields:** for when a packet is too big for a link

Total overhead: 20 bytes of IP + 20 bytes of TCP + application data. Not free, but not catastrophic.

### IP Addressing and Subnets

IPv4 addresses are 32 bits, written as four decimal numbers separated by dots (e.g., `192.168.1.1`). An address has two parts: the **network prefix** and the **host** part. A **subnet mask** (or CIDR notation like `/24`) tells you where the split is. Devices in the same subnet can talk directly via Ethernet/ARP. Devices in different subnets must go through a **router**.

How do you get an IP address? Either a sysadmin hard-codes it, or **DHCP (Dynamic Host Configuration Protocol)** assigns one automatically. DHCP also hands out the default gateway (your router's IP), the DNS server address, and the subnet mask. Plug and play.

How do ISPs get IP blocks? From **ICANN** (Internet Corporation for Assigned Names and Numbers), which manages DNS and IP allocation globally. ICANN allocates large blocks to regional registries, which allocate to ISPs, which subdivide and allocate to customers.

### IPv6 — The Fix We've Been Slowly Deploying for 30 Years

IPv4 has 32-bit addresses: ~4.3 billion total. In the 1990s, people realized this would run out. Enter **IPv6** with 128-bit addresses — enough for every grain of sand on Earth to have multiple IP addresses and still have room left over.

IPv6 also simplifies the header (removing fragmentation fields, no header checksum) and makes routing more efficient. The transition from IPv4 to IPv6 is done via **tunneling** — IPv6 packets get wrapped inside IPv4 packets to travel through routers that don't yet speak IPv6. It's the networking equivalent of putting a letter inside another envelope. The transition has been slow and painful, as anyone who has ever managed a network can tell you.

### Virtual Circuits vs. Packet Switching

Two fundamentally different philosophies for routing data:

**Virtual Circuits (Connection-Oriented):** Before sending data, you set up a dedicated circuit through the network. Every packet follows the same pre-established path, tagged with a circuit identifier. Resources are reserved. Predictable, but inflexible. (Think phone calls.)

**Packet Switching (Store-and-Forward):** No pre-established path. Each packet is an independent entity. Routers receive a complete packet, look up where to forward it, and send it on its way. No reservation, no guaranteed path — "best effort" delivery. The internet uses this. It's efficient for bursty traffic because bandwidth is shared statistically (**statistical multiplexing**).

### How Routers Forward Packets

A router has multiple **input ports** and **output ports**, each with a different network address. When a packet arrives at an input port, the router looks up the destination IP in its **forwarding table** to find the **next hop** — the next router to send the packet to. The forwarding table maps destination prefixes to output ports.

The router uses **longest prefix match** — if a packet's destination matches multiple entries in the table, it uses the one with the longest matching prefix (most specific). This is how the internet's routing tables handle the hierarchy of IP addresses.

Inside the router, a **switching fabric** moves packets from input buffers to output buffers. If the fabric is slower than the input rate, queues build up at input ports — **queuing delay and packet loss** from buffer overflow. This is where congestion begins (more on this in the transport layer chapter).

### Intra-Domain Routing — Finding the Best Path Inside an AS

The internet is divided into **Autonomous Systems (ASes)** — independent networks (ISPs, universities, companies) each with their own routing policies. Inside an AS, you use **intra-domain routing protocols**. The goal: find the lowest-cost path from source to destination.

Networks are modeled as **graphs** — routers are nodes, links are edges with costs (based on bandwidth, latency, or just set to 1). Routing algorithms find shortest paths through this graph. But computing shortest paths in a huge, dynamic, distributed network is non-trivial. No single node knows the whole graph. Links go up and down. New routers are added.

**Link State Routing (OSPF, ISIS):**
Each router floods information about its directly connected links to everyone in the AS — these are called **Link State Packets (LSPs)**. Once every router has the complete topology, each independently runs **Dijkstra's shortest path algorithm** to compute routes to all destinations. OSPF (Open Shortest Path First) uses IP packets for this. Link state converges faster and avoids count-to-infinity (because everyone has the full picture), but requires flooding and is more complex.

**Distance Vector Routing (RIP):**
Each router only knows the shortest path costs to all destinations from its own perspective, and shares these **distance vectors** with direct neighbors. Each router updates its table using the **Bellman-Ford** equation: `d(A,Y) = min over all neighbors V of [ c(A,V) + d(V,Y) ]`. This is distributed and simple, but suffers from the infamous **count-to-infinity problem**:

Imagine link A→B costs 4, and C→B costs 1. Now A→B becomes 60. C thinks it can still reach A in 5 (via B), B thinks it can reach A in 6 (via C), and they keep incrementing each other forever. Bad news travels slowly. RIP uses UDP. In practice, link state (OSPF) is more popular.

### Inter-Domain Routing — BGP, the Protocol the Whole Internet Agrees On

Between ASes, there's only one routing protocol: **BGP (Border Gateway Protocol)**. The entire world's internet connectivity depends on this one protocol working. No pressure.

BGP is a **path vector** protocol — like distance vector, but instead of just advertising the cost, each router advertises the entire AS path. This solves count-to-infinity (you can see cycles in the path and reject them) and lets ASes implement **routing policies**.

BGP operations: routers establish TCP sessions with neighbors on port 179, exchange route advertisements (prefixes reachable through that AS), and then send incremental updates when things change. Route advertisements include the **AS-path** (sequence of ASes) and the **origin AS**.

Route selection is not shortest-path — it's driven by business relationships:
1. **Local preference** (highest wins — set by the operator based on policy)
2. Shorter AS path
3. Lowest origin type
4. Hot potato routing (get the packet out of your AS fast)

AS Business Relationships (the money side of routing):
- **Customer pays Provider** for transit (provider carries traffic anywhere)
- **Peers** exchange traffic for free, but only to/from their own customers (not other providers)
- **Tier-1 ISPs** have no providers — they peer with all other Tier-1s

Filter/export rules: Routes learned from customers are advertised to everyone. Routes learned from providers are only advertised to customers (otherwise you'd be giving free transit to two providers at once — paying to route their traffic — and that's a very bad business model).

BGP security is still an active, unsolved problem. A misconfigured BGP advertisement can accidentally attract traffic meant for the whole internet. This has happened. It was not fun.

---

## Chapter 3: The Transport Layer — "End-to-End, Baby"

We've gotten a packet routed across the internet. Now what? The network layer gets packets between machines. But a machine runs dozens of applications at once — your browser, Spotify, Discord, a game. Who gets which packet? That's the **Transport Layer's** job.

### Demultiplexing with Ports

The transport layer adds **ports** — 16-bit numbers that identify which application on a machine should receive the data. A connection is uniquely identified by the 4-tuple: `(src_ip, src_port, dst_ip, dst_port)`. Port 80 is HTTP, 443 is HTTPS, 22 is SSH, etc. The OS delivers incoming packets to the correct application based on the destination port.

### TCP vs. UDP — Choose Your Fighter

**UDP (User Datagram Protocol):** Connectionless, stateless, no reliability, no ordering guarantees. You shoot packets into the void and hope they arrive. Why use it? Speed and simplicity. Good for: DNS lookups, video streaming (where a dropped frame is better than a delayed one), online games, VoIP.

**TCP (Transmission Control Protocol):** Connection-oriented, stateful, provides in-order reliable delivery. The heavy lifter. Good for: HTTP, file transfers, anything where correctness matters.

### TCP Mechanics — How It Actually Works

**The Three-Way Handshake:** Before sending data, TCP establishes a connection:
1. Client sends **SYN** (synchronize)
2. Server responds with **SYN-ACK**
3. Client sends **ACK**

Now both sides know each other's sequence numbers and are ready to communicate. **Connection teardown** is a four-way process (FIN, ACK, FIN, ACK) with careful handling for the edge case where the final ACK is lost — that's the "two generals problem" in disguise.

**Sequence Numbers and ACKs:** Every byte sent has a sequence number. The receiver sends **ACKs (acknowledgments)** indicating the next byte it expects. **Cumulative ACKs** mean an ACK for byte N implies receipt of all bytes before N. If a packet is lost, the receiver keeps ACKing the last good byte it got.

**ARQ (Automatic Repeat reQuest):** The fundamental reliability mechanism. If the sender doesn't receive an ACK within a timeout, it retransmits. Stop-and-wait (send one, wait for ACK) is simple but wastes bandwidth — the pipe is mostly empty.

**Sliding Window:** The fix. The sender can have up to W bytes in flight (unacknowledged) simultaneously. After each ACK, the window slides forward. This keeps the pipe full. The right window size is roughly the **Bandwidth-Delay Product (BDP)**: `BDP = bandwidth × RTT`. This is the theoretical maximum data you can have in flight simultaneously.

**Timeouts and RTT Estimation:** The timeout (RTO) needs to be set carefully. Too short → unnecessary retransmissions. Too long → slow recovery. TCP estimates RTT with an exponential moving average: `RTT_estimate = (1-α) * RTT_estimate + α * new_sample` (α ≈ 0.125). **Karn's algorithm:** don't use samples from retransmitted segments (you can't tell if the ACK is for the first or second send).

**Fast Retransmit:** Waiting for a full timeout is expensive. If the sender receives **three duplicate ACKs** (the same ACK three times in a row), it assumes the packet is lost and retransmits immediately without waiting for the timeout. This is much faster.

### Flow Control — Don't Drown the Receiver

The receiver has a buffer of finite size. If the sender sends too fast, the receiver's buffer overflows and data is lost. The receiver tells the sender its **advertised window** — how much buffer space is available. The sender limits unacknowledged data to `min(cwnd, advertised_window)`. If the receiver's buffer fills up, it advertises window = 0, and the sender stops.

### Congestion Control — Don't Drown the Network

Flow control protects the receiver. **Congestion control** protects the *network* (the routers in between). In 1986, an internet congestion collapse reduced throughput on a 32 kbps link by a factor of 1000 to just 40 bps — everyone was retransmitting furiously, making congestion worse, in a death spiral. This motivated the need for proper congestion control.

The core challenge: end hosts can't directly observe congestion inside the network (there are too many routers, and the end-to-end principle says transport shouldn't interact with routers). So TCP infers congestion from **packet loss** — if a packet is dropped, a router somewhere was overloaded.

**AIMD (Additive Increase, Multiplicative Decrease):**
- When things are going well, increase the congestion window by 1 per RTT (additive)
- When loss is detected, cut the window in half (multiplicative decrease)
- This converges to a fair and efficient operating point — a key mathematical result

**TCP Slow Start:** Starting too fast causes congestion; starting too slow wastes bandwidth. Slow start doubles cwnd every RTT (exponential growth — misnaming alert: this is NOT slow) until hitting the **slow start threshold (ssthresh)**, then switches to additive increase.

**TCP Tahoe:** Slow start → congestion avoidance. On any loss: reset cwnd to 1, ssthresh = cwnd/2, restart slow start.

**TCP Reno (improvement):** Distinguishes between timeout (bad, full reset) and triple duplicate ACK (less bad, fast retransmit + fast recovery). On triple dup ACK: ssthresh = cwnd/2, cwnd = cwnd/2 (stay in congestion avoidance). Much faster recovery.

**TCP CUBIC:** Instead of linear AIMD, uses a cubic function for window growth. Default on most Linux and macOS systems.

**BBR (Bottleneck Bandwidth and Round-trip propagation time):** Google's 2016 contribution. The problem with loss-based congestion control: **bufferbloat**. Routers with large buffers cause huge queuing delays before loss occurs — you're filling the buffer, adding seconds of latency, but TCP doesn't react until the buffer *overflows*. BBR doesn't wait for loss. Instead, it estimates the **BDP of the bottleneck link** (`max_bandwidth × min_RTT`) and tries to operate at exactly that rate — full utilization, minimal queuing. BBR accounts for ~40% of internet traffic today. It has its own issues with fairness under loss, and BBR2 is an ongoing improvement effort.

**Why congestion control is hard in practice:** TCP assumes loss = congestion. But WiFi drops packets due to interference, not congestion — TCP wrongly slows down. On high-bandwidth, high-RTT paths (like satellite or transcontinental links), TCP's slow ramp-up wastes enormous capacity. Different environments need different algorithms, and picking the wrong one costs real performance.

**TCP Throughput formula:** `Throughput ≈ (√(3/2) × MSS) / (RTT × √p)` where p is the packet loss rate and MSS is the maximum segment size. Lower RTT, lower loss → higher throughput. This equation explains why WAN performance is so sensitive to latency.

---

## Chapter 4: The Application Layer — "Finally, Something Users Actually See"

We've built the whole stack. Now applications sit on top and use it, blissfully unaware of all the chaos below.

### DNS — The Internet's Phone Book (That Everyone Relies On Totally)

Before your browser can talk to `www.stonybrook.edu`, it needs an IP address. That's DNS's job.

**The pre-DNS dark ages:** All name-to-IP mappings lived in a file called `hosts.txt` managed manually at SRI. Admins emailed changes in. Computers periodically FTP'd a fresh copy. As the internet grew, this became a complete disaster — unscalable, full of duplicates, often stale.

**DNS Design:** A hierarchical, distributed, cached naming system with four properties it needed to have: scalable (hierarchical design), fault tolerant (replicated widely), low latency (anycast + caching), universally accessible (geographically distributed).

The hierarchy: Root DNS servers → TLD servers (`.com`, `.edu`, `.uk`, etc.) → Authoritative name servers for each domain. There are 13 logical root name servers (each massively replicated via anycast). Verisign manages `.com`. Educause manages `.edu`.

**Resolution process (iterative):**
1. Your computer asks its **local DNS server** (assigned by DHCP or configured manually — e.g., 8.8.8.8 for Google, 1.1.1.1 for Cloudflare)
2. If it's cached, done. If not, the local DNS asks the **root server**
3. Root says "I don't know, try the .edu TLD server"
4. Local DNS asks the TLD server
5. TLD says "try cs.stonybrook.edu's authoritative server"
6. Local DNS asks the authoritative server, gets the answer
7. Local DNS caches the result (for TTL seconds) and returns it to you

**DNS Record Types:**
- **A record:** hostname → IPv4 address
- **AAAA record:** hostname → IPv6 address
- **NS record:** delegation — "for this domain, ask THIS name server"
- **CNAME record:** hostname → canonical hostname (aliasing — used extensively in CDNs)
- **MX record:** domain → mail server canonical name

**DNS Caching:** Without caching, every single web request would require multiple DNS round trips before the actual HTTP request could even start. Caching makes this bearable. TTL values control how long cached entries are kept. Popular domains have short TTLs so changes propagate quickly.

**DNS as a power tool:** DNS is used for way more than name resolution. CDNs use DNS to redirect users to nearby servers. Load balancers use it (one domain → many IPs). Akamai alone serves 30-40% of global internet traffic partly through clever DNS tricks.

**DNS Security:** Traditional DNS is completely unencrypted, sent over UDP port 53. Attackers can intercept queries (surveillance), forge responses (redirecting you to fake bank websites — DNS spoofing), or DDoS the TLD servers. **DNSSec** adds cryptographic signatures to DNS records. **DNS over HTTPS (DoH)** wraps DNS queries in HTTPS — port 443, indistinguishable from web traffic, hard to block. **DNS over TLS (DoT)** uses TLS on dedicated port 853 — easier for enterprises to manage and filter. DoH is preferred by privacy-conscious users and browser makers; DoT is preferred by enterprise admins who want visibility.

### HTTP — The Protocol That Runs the Web

HTTP is the application-layer protocol for transferring web content. A browser issues **GET requests**; a server responds with content. Simple in concept, but the evolution from HTTP/1.0 to HTTP/2 tells a story about performance optimization under real-world constraints.

**HTTP/1.0 (Non-persistent):** For every object (the HTML file, each image, each CSS file), a brand new TCP connection is established (SYN, SYN-ACK, ACK, then the GET request, then the response, then FIN). Cost per object: **2 RTTs + file transmission time**. A typical webpage with 30 objects means 30 TCP connection setups. This is genuinely painful.

**HTTP/1.1 — The Three Ps:**
- **Persistent:** Keep the TCP connection open and reuse it for multiple requests
- **Parallel:** Open up to 6 parallel connections to the same server
- **Pipelined:** Send multiple requests without waiting for responses (in theory)

Pipelining sounds great but has a fatal flaw: **head-of-line blocking**. If one response is slow (large image), it blocks all the responses queued behind it, even if they're tiny and ready. So HTTP/1.1 in practice uses persistent + parallel but skips pipelining.

**HTTP/2:** The real fix for head-of-line blocking. HTTP/2 multiplexes multiple request-response streams over a **single** TCP connection using binary framing. Responses can arrive out of order — stream 3's response doesn't block stream 7's. HTTP/2 also adds **header compression** (HPACK — headers are often identical between requests) and **stream prioritization** (tell the server which resources matter most for rendering). HTTP/2 was based on Google's **SPDY** protocol. It's much faster than HTTP/1.1 on lossy links.

**HTTP Response Time:** `HTTP response time = 2RTT + file transmission time`. This formula is for a single object over non-persistent HTTP. The RTTs dominate for small files, transmission time for large ones.

### CDNs — Because One Server Is Never Enough

You run a popular website. Suddenly you have a million users. You can't serve them all from one server in New Jersey — users in Tokyo get terrible latency, and the server catches fire. Solution: **Content Delivery Networks (CDNs)**.

A CDN is a globally distributed cluster of caches — servers placed inside or near ISPs all over the world. When a user requests `foo.jpg`, DNS redirects them to the **nearest CDN server** that has it cached. Two redirection methods: change the DNS CNAME record to point to a CDN hostname (the CDN's DNS server then directs to the nearest node), or embed CDN URLs directly in the HTML.

CDNs solve scalability, fault tolerance, low latency, and give content providers control — all the properties DNS itself tries to provide. **Akamai** has 365K+ servers in 135 countries, handles 100 terabits/second, and serves 85% of internet traffic within a single hop of a CDN. That's not a small operation.

Redirection to the *closest* CDN server: either the CDN's authoritative name server uses the DNS resolver's location as a proxy for user location, or **anycast** routing is used (same IP address at all CDN nodes, BGP routes to the closest one).

---

## Chapter 5: Alternate Internet Architectures — "Wait, Didn't We Agree This Was Decentralized?"

Here's a plot twist: the internet was designed as a decentralized, end-to-end, dumb-network-smart-edges system. And then Google happened.

**The Centralization Trend:** Google, Microsoft, Amazon, and Netflix don't just use the internet — they *own* substantial portions of it. Google has its own DNS (8.8.8.8), its own CDN, its own WAN connecting datacenters, its own undersea cables, and points-of-presence (PoPs) inside most major ISPs. If you're watching YouTube, the video is probably served from a Google server sitting inside your own ISP. Traffic that used to cross the internet backbone now stays inside Google's private network.

This means the internet increasingly looks like a few giant silos connected to each other, rather than a flat mesh of independent networks. The architecture that BGP and IP were designed for — thousands of roughly equal peers — looks less and less like the reality.

**Web3 and Decentralized Alternatives:** In response to this centralization, there's a movement to build decentralized alternatives. **IPFS (InterPlanetary File System)** is a decentralized storage and delivery network — content addressed by its hash rather than its location. No central authority. Built on peer-to-peer. Whether Web3/crypto-based architectures are the future or an elaborate science project remains... unclear. The jury is out and the technology keeps changing.

---

## Epilogue: Putting It All Together

Let's trace a single HTTP request — you type `www.stonybrook.edu` into your browser — through every layer:

1. **DNS (Application Layer):** Browser asks local DNS for the IP of `www.stonybrook.edu`. Local DNS queries root → TLD → authoritative server. Returns `129.49.2.176`. Cached for future use.

2. **TCP Handshake (Transport Layer):** Browser initiates a TCP connection to `129.49.2.176:443` (HTTPS). Three-way handshake: SYN → SYN-ACK → ACK.

3. **IP Routing (Network Layer):** Each TCP segment becomes an IP packet. Your router uses BGP-derived routes to forward it to your ISP. Your ISP forwards it through the internet backbone. Each router does a forwarding table lookup. BGP's path vector routes it across ASes. TTL decrements at each hop.

4. **Data Link + Physical (Link/Physical Layers):** At each hop, the IP packet gets wrapped in an Ethernet (or WiFi) frame with appropriate MAC addresses. ARP resolves the next-hop IP to a MAC address on each local network segment. The frame is transmitted as electrical signals, light pulses, or radio waves.

5. **HTTP Request (Application Layer):** TCP delivers the bytes in order to the server. HTTP/2 sends a GET request for `/index.html`.

6. **Response + Congestion Control:** The server sends the file back. TCP's congestion window grows (slow start → congestion avoidance). If packets drop, fast retransmit kicks in. The advertised window ensures the receiver's buffer isn't overwhelmed.

7. **Content Delivery:** If Stony Brook uses a CDN, DNS already directed you to a nearby CDN server. The actual web server just populates the CDN cache; you talk to the edge.

Every single one of these steps, every protocol in this story, is running simultaneously for millions of users. The fact that it works at all is genuinely impressive.

---

## Quick-Reference Summary Table

| Layer | What It Does | Key Protocols/Concepts |
|-------|-------------|----------------------|
| Application | User-facing services | HTTP, HTTP/2, DNS, CDNs, DoH, DoT |
| Transport | End-to-end delivery | TCP, UDP, congestion control (AIMD, Tahoe, Reno, CUBIC, BBR), flow control, sliding window |
| Network | Routing across internet | IP (v4/v6), BGP, OSPF, RIP, DHCP, ARP, subnets, CIDR |
| Data Link | Local delivery + MAC | Ethernet, WiFi, CSMA/CD, CSMA/CA, Switches, Bridges |
| Physical | Bits ↔ signals | Copper, fiber, radio waves, hubs, repeaters |

---

*Notes compiled for CSE 534, Spring 2026 — covering all lecture material from Physical Layer through Alternate Internet Architectures.*
