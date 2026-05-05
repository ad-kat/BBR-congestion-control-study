// runner.rs — the part that actually does the work.
// Spawns Mininet, sets up tc/netem, fires iperf3, collects metrics.
// If something breaks here, it's probably Mininet. It's always Mininet.

use std::path::Path;
use std::time::{Duration, Instant};
use tokio::process::Command;
use tokio::time::sleep;
use serde::{Deserialize, Serialize};
use std::fs;

// ─── Data Structures ──────────────────────────────────────────────────────────

/// Configuration for a single experiment run.
/// Everything that changes between runs lives here.
/// Everything that stays constant lives in the binary. Like a reasonable person.
#[derive(Debug, Clone)]
pub struct ExperimentConfig {
    pub bw_mbps: u64,
    pub elephant_duration_s: u64,
    pub num_mice: u32,
    pub mice_size_mb: u32,
    pub elephant_port: u16,
    pub mice_port: u16,
    pub output_dir: String,
}

/// The full parameter sweep — all CCAs × RTTs × buffer sizes.
/// Cartesian product of doom. 27 experiments if you use all defaults.
#[derive(Debug)]
pub struct SweepConfig {
    pub ccas: Vec<String>,
    pub rtts_ms: Vec<u64>,
    pub buffers_bytes: Vec<u64>,
    pub experiment: ExperimentConfig,
}

/// The result of one complete experiment run.
/// Every field that could possibly fail to measure is an Option<f64>.
/// Because life is uncertain and iperf3 crashes more than you'd expect.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExperimentResult {
    // Experiment identity — what we set up
    pub cca: String,
    pub rtt_ms: u64,
    pub buffer_bytes: u64,
    pub bw_mbps: u64,
    pub timestamp: String,

    // Elephant flow metrics — the rude bandwidth hog
    pub elephant_goodput_mbps: Option<f64>,
    pub elephant_retransmits: Option<u64>,

    // Mice flow metrics — the innocent victims
    pub mice_fcts_s: Vec<f64>,           // FCT per mouse flow in seconds
    pub mice_fct_mean_s: Option<f64>,    // mean FCT — the headline number
    pub mice_fct_p99_s: Option<f64>,     // p99 FCT — the "how bad can it get" number
    pub mice_fct_min_s: Option<f64>,
    pub mice_fct_max_s: Option<f64>,

    // Derived metrics
    pub jains_fairness: Option<f64>,     // Jain's fairness index — 1.0 = perfect, 0.0 = catastrophic
    pub mice_throughput_mbps: Option<f64>, // average mice throughput

    // Queue occupancy from tc -s qdisc
    pub queue_avg_packets: Option<f64>,
    pub queue_drops: Option<u64>,

    // Did it blow up?
    pub error: Option<String>,
}

/// Raw iperf3 JSON output structure — the parts we actually care about.
/// iperf3's JSON schema is... extensive. We ignore most of it. Deliberately.
#[derive(Debug, Deserialize)]
struct Iperf3Output {
    end: Option<Iperf3End>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct Iperf3End {
    sum_received: Option<Iperf3Sum>,
    sum_sent: Option<Iperf3Sum>,
}

#[derive(Debug, Deserialize)]
struct Iperf3Sum {
    bits_per_second: Option<f64>,
    retransmits: Option<u64>,
    seconds: Option<f64>,
    bytes: Option<u64>,
}

// ─── Main Sweep ───────────────────────────────────────────────────────────────

/// Run the full parameter sweep. This is the outer loop.
/// It iterates over every (CCA, RTT, buffer) combination and runs one experiment each.
/// Total runtime: approximately "go get lunch".
pub async fn run_sweep(config: SweepConfig) -> anyhow::Result<Vec<ExperimentResult>> {
    let mut all_results: Vec<ExperimentResult> = Vec::new();

    // Create output directory if it doesn't exist.
    // Unlike certain shell scripts, we don't just let the OS yell at us about this.
    fs::create_dir_all(&config.experiment.output_dir)?;

    let total = config.ccas.len() * config.rtts_ms.len() * config.buffers_bytes.len();
    let mut run_index = 0;

    for cca in &config.ccas {
        for &rtt_ms in &config.rtts_ms {
            for &buffer_bytes in &config.buffers_bytes {
                run_index += 1;
                println!(
                    "\n[{}/{}] CCA={}, RTT={}ms, BUF={}",
                    run_index, total, cca, rtt_ms,
                    format_bytes(buffer_bytes)
                );

                let result = run_single_experiment(
                    cca,
                    rtt_ms,
                    buffer_bytes,
                    &config.experiment,
                ).await;

                match &result {
                    Ok(r) => {
                        if let Some(fct) = r.mice_fct_mean_s {
                            println!(
                                "  [ok] mean mice FCT={:.3}s, elephant={:.1}Mbps, JFI={:.4}",
                                fct,
                                r.elephant_goodput_mbps.unwrap_or(0.0),
                                r.jains_fairness.unwrap_or(0.0)
                            );
                        }
                        // Save result to JSON immediately — don't wait for everything to finish.
                        // If Mininet crashes on experiment 17, we at least have 16 results.
                        save_result_json(r, &config.experiment.output_dir)?;
                        all_results.push(r.clone());
                    }
                    Err(e) => {
                        eprintln!("  [error] experiment failed: {}", e);
                        // Record the failure so the report can show it instead of silently ignoring it.
                        let failed = make_error_result(cca, rtt_ms, buffer_bytes, &config.experiment, &e.to_string());
                        save_result_json(&failed, &config.experiment.output_dir)?;
                        all_results.push(failed);
                    }
                }

                // Brief pause between experiments — lets the kernel settle down.
                // 5 seconds. We don't know exactly why this matters. It just does.
                sleep(Duration::from_secs(5)).await;
            }
        }
    }

    Ok(all_results)
}

// ─── Single Experiment ────────────────────────────────────────────────────────

/// Run one experiment: one (CCA, RTT, buffer) combination.
/// Sets up the Mininet topology, fires the elephant + mice flows, collects everything.
/// Returns a result struct even if things go sideways — error field explains what happened.
async fn run_single_experiment(
    cca: &str,
    rtt_ms: u64,
    buffer_bytes: u64,
    config: &ExperimentConfig,
) -> anyhow::Result<ExperimentResult> {

    let timestamp = chrono_timestamp();

    // Step 1: clean up any zombie Mininet state from previous runs.
    // Mininet is very good at leaving corpses if you kill it mid-run.
    cleanup_mininet().await?;

    // Step 2: build the Mininet dumbbell topology via a Python helper.
    // Yes, we're calling Python from Rust. Yes, this is ironic.
    // No, we're not reimplementing Mininet in Rust. That's someone else's PhD.
    let topology_handle = spawn_topology(rtt_ms, buffer_bytes, config).await?;

    // Give Mininet a moment to actually come up before we start hammering it.
    // "It works on my machine" is not a valid excuse if you didn't wait for OVS.
    sleep(Duration::from_secs(3)).await;

    // Step 3: start the iperf3 servers (they wait for connections).
    let _server_handles = start_iperf_servers(config).await?;
    sleep(Duration::from_secs(1)).await;

    // Step 4: launch the elephant flow in the background.
    // It will run for elephant_duration_s seconds and monopolize the bottleneck link.
    // That's the whole point. That's the villain of this story.
    let elephant_handle = launch_elephant(cca, config).await?;

    // Wait a moment for the elephant to establish its flow and fill the pipe.
    // Sending mice immediately gives BBR no time to show its worst behavior.
    sleep(Duration::from_secs(5)).await;

    // Step 5: run mice flows sequentially and record FCT for each.
    // Sequential because we want per-flow FCT, not aggregate throughput.
    let mice_fcts = run_mice_flows(cca, config).await;

    // Step 6: collect elephant metrics once it finishes.
    let elephant_result = collect_elephant_result(elephant_handle).await;

    // Step 7: collect queue stats from tc before we tear everything down.
    let queue_stats = collect_queue_stats().await;

    // Step 8: tear down Mininet. Always. Even if everything caught fire.
    // Leftover Mininet state will corrupt every subsequent experiment.
    let _ = cleanup_mininet().await;
    let _ = topology_handle; // drop it

    // Step 9: compute derived metrics and assemble the result struct.
    let result = assemble_result(
        cca, rtt_ms, buffer_bytes, config,
        timestamp,
        mice_fcts,
        elephant_result,
        queue_stats,
    );

    Ok(result)
}

// ─── Mininet / tc Setup ───────────────────────────────────────────────────────

/// Kill any lingering Mininet processes from previous runs.
/// This is not optional. Mininet leaves a mess every time it crashes.
async fn cleanup_mininet() -> anyhow::Result<()> {
    // mn --clean is the nuclear option — kills everything OVS-related.
    let _ = Command::new("sudo")
        .args(["mn", "--clean"])
        .output()
        .await;

    // Also kill any stray iperf3 processes. They're squatters.
    let _ = Command::new("sudo")
        .args(["pkill", "-f", "iperf3"])
        .output()
        .await;

    Ok(())
}

/// Spawn the Mininet dumbbell topology via the Python topology script.
/// Returns a handle to the subprocess — caller must keep it alive for the experiment duration.
/// When the handle is dropped, the topology tears down. That's the deal.
async fn spawn_topology(
    rtt_ms: u64,
    buffer_bytes: u64,
    config: &ExperimentConfig,
) -> anyhow::Result<tokio::process::Child> {
    // The Python topology script lives next to the Rust binary's repo root.
    // We resolve it relative to the current working directory.
    // If you moved the script, that's on you.
    let topology_script = Path::new("scripts/topology.py");

    let child = Command::new("sudo")
        .args([
            "python3",
            topology_script.to_str().unwrap_or("scripts/topology.py"),
            "--bw", &config.bw_mbps.to_string(),
            "--rtt", &rtt_ms.to_string(),
            "--buf", &buffer_bytes.to_string(),
        ])
        .spawn()
        .map_err(|e| anyhow::anyhow!("Failed to spawn Mininet topology: {}. Is Mininet installed?", e))?;

    Ok(child)
}

/// Apply tc/netem and tc/HTB settings to the bottleneck interface.
/// Called once per experiment after Mininet is up.
/// tc is powerful, finicky, and poorly documented. These settings are empirically validated.
async fn apply_tc_settings(
    interface: &str,
    bw_mbps: u64,
    rtt_ms: u64,
    buffer_bytes: u64,
) -> anyhow::Result<()> {
    let delay_ms = rtt_ms / 2; // netem adds delay per direction, so half-RTT each side
    let burst = bw_mbps * 1000 / 8; // burst size in bytes, roughly 1ms worth of data

    // Delete existing qdisc if there is one — idempotent setup matters.
    let _ = Command::new("sudo")
        .args(["tc", "qdisc", "del", "dev", interface, "root"])
        .output()
        .await;

    // HTB root qdisc with rate limiting — this enforces the bottleneck bandwidth.
    Command::new("sudo")
        .args([
            "tc", "qdisc", "add", "dev", interface, "root", "handle", "1:",
            "htb", "default", "12",
        ])
        .output()
        .await?;

    Command::new("sudo")
        .args([
            "tc", "class", "add", "dev", interface, "parent", "1:", "classid", "1:12",
            "htb", "rate", &format!("{}mbit", bw_mbps),
            "burst", &burst.to_string(),
        ])
        .output()
        .await?;

    // netem child qdisc adds RTT delay and enforces the buffer size limit.
    // limit sets the queue depth in packets — approximate from bytes/MTU.
    let limit_packets = (buffer_bytes / 1500).max(1); // 1500 = MTU, at least 1 packet
    Command::new("sudo")
        .args([
            "tc", "qdisc", "add", "dev", interface, "parent", "1:12",
            "handle", "10:", "netem",
            "delay", &format!("{}ms", delay_ms),
            "limit", &limit_packets.to_string(),
        ])
        .output()
        .await?;

    Ok(())
}

// ─── iperf3 Flow Control ───────────────────────────────────────────────────────

/// Start iperf3 servers on both ports — one for elephant, one for mice.
/// They run in server mode (-s) and just sit there waiting for flows.
async fn start_iperf_servers(config: &ExperimentConfig) -> anyhow::Result<Vec<tokio::process::Child>> {
    let mut handles = Vec::new();

    for port in [config.elephant_port, config.mice_port] {
        let h = Command::new("sudo")
            .args([
                "iperf3", "-s",
                "-p", &port.to_string(),
                "--one-off", // exit after one client. Because we're running these ourselves.
            ])
            .spawn()
            .map_err(|e| anyhow::anyhow!("Failed to start iperf3 server on port {}: {}", port, e))?;
        handles.push(h);
    }

    Ok(handles)
}

/// Launch the elephant (bulk) flow — a long-lived TCP stream using the specified CCA.
/// Returns a handle to the iperf3 client process. Caller collects its output.
/// The elephant runs for elephant_duration_s and doesn't stop for mice. That's the problem.
async fn launch_elephant(
    cca: &str,
    config: &ExperimentConfig,
) -> anyhow::Result<tokio::process::Child> {

    // h_elephant is the Mininet host that sends the bulk flow.
    // We invoke iperf3 inside that namespace via `ip netns exec`.
    // "h_elephant" is the namespace name — matches topology.py's naming.
    let handle = Command::new("sudo")
        .args([
            "ip", "netns", "exec", "h_elephant",
            "iperf3",
            "-c", "10.0.0.3",        // receiver IP — h_recv in topology.py
            "-p", &config.elephant_port.to_string(),
            "-t", &config.elephant_duration_s.to_string(),
            "-C", cca,               // per-socket CCA selection — the whole point
            "-J",                    // JSON output so we can parse it
            "--logfile", &format!("/tmp/micewatch_elephant_{}.json", cca),
        ])
        .spawn()
        .map_err(|e| anyhow::anyhow!("Failed to launch elephant flow: {}", e))?;

    Ok(handle)
}

/// Run mice flows sequentially and return the FCT for each.
/// Each mouse is a 1MB iperf3 transfer. It should finish in ~80ms at 100Mbps.
/// With BBR hogging the buffer, it won't. That's the entire research question.
async fn run_mice_flows(
    cca: &str,
    config: &ExperimentConfig,
) -> Vec<f64> {
    let mut fcts: Vec<f64> = Vec::new();

    for i in 0..config.num_mice {
        let start = Instant::now();

        // Run iperf3 from h_mice namespace, transferring exactly mice_size_mb megabytes.
        // -n sets transfer size in bytes, -J gives JSON output.
        let output = Command::new("sudo")
            .args([
                "ip", "netns", "exec", "h_mice",
                "iperf3",
                "-c", "10.0.0.3",
                "-p", &config.mice_port.to_string(),
                "-n", &format!("{}M", config.mice_size_mb),
                "-C", cca,
                "-J",
            ])
            .output()
            .await;

        let elapsed = start.elapsed().as_secs_f64();

        match output {
            Ok(out) if out.status.success() => {
                // Try to parse iperf3's JSON. If it's malformed, fall back to wall-clock time.
                // Wall-clock is slightly noisier but close enough for research purposes.
                let fct = parse_iperf3_fct(&out.stdout).unwrap_or(elapsed);
                println!("  [mouse {}/{}] FCT={:.4}s", i + 1, config.num_mice, fct);
                fcts.push(fct);
            }
            Ok(out) => {
                eprintln!("  [mouse {}/{}] iperf3 exited non-zero: {}",
                    i + 1, config.num_mice,
                    String::from_utf8_lossy(&out.stderr));
                // Don't push — a failed transfer shouldn't count as a valid FCT measurement.
            }
            Err(e) => {
                eprintln!("  [mouse {}/{}] failed to spawn iperf3: {}", i + 1, config.num_mice, e);
            }
        }

        // Brief gap between mice flows — prevents port conflicts and gives the OS a breather.
        sleep(Duration::from_millis(200)).await;
    }

    fcts
}

/// Parse FCT from iperf3 JSON output.
/// Returns the actual measured transfer duration in seconds, or None if parsing fails.
/// iperf3's JSON is quite consistent — unless it crashes, which is its hobby.
fn parse_iperf3_fct(stdout: &[u8]) -> Option<f64> {
    let json_str = std::str::from_utf8(stdout).ok()?;
    let parsed: Iperf3Output = serde_json::from_str(json_str).ok()?;

    if let Some(err) = &parsed.error {
        eprintln!("  [iperf3 error field] {}", err);
        return None;
    }

    parsed.end?
        .sum_received?
        .seconds
}

/// Parse throughput from iperf3 JSON — used for elephant goodput.
/// bits_per_second → Mbps. iperf3 reports in bits, because of course it does.
fn parse_iperf3_throughput(stdout: &[u8]) -> Option<f64> {
    let json_str = std::str::from_utf8(stdout).ok()?;
    let parsed: Iperf3Output = serde_json::from_str(json_str).ok()?;
    let bps = parsed.end?.sum_received?.bits_per_second?;
    Some(bps / 1_000_000.0) // bits/sec → Mbps
}

/// Parse retransmit count from iperf3 JSON — a proxy for congestion severity.
fn parse_iperf3_retransmits(stdout: &[u8]) -> Option<u64> {
    let json_str = std::str::from_utf8(stdout).ok()?;
    let parsed: Iperf3Output = serde_json::from_str(json_str).ok()?;
    parsed.end?.sum_sent?.retransmits
}

// ─── Metric Collection ────────────────────────────────────────────────────────

/// Wait for the elephant flow to finish and collect its output.
/// Returns (goodput_mbps, retransmits) or (None, None) if iperf3 bailed.
async fn collect_elephant_result(
    mut handle: tokio::process::Child
) -> (Option<f64>, Option<u64>) {

    let status = handle.wait().await;
    if status.is_err() {
        return (None, None);
    }

    // Read the elephant's logfile — we wrote it there because capturing child output
    // while also waiting for process completion in async Rust requires more ceremony
    // than just reading a file. Trade-off accepted.
    let logfile = "/tmp/micewatch_elephant_bbr.json"; // default; gets overwritten per run
    match fs::read(logfile) {
        Ok(data) => {
            let goodput = parse_iperf3_throughput(&data);
            let retransmits = parse_iperf3_retransmits(&data);
            (goodput, retransmits)
        }
        Err(_) => (None, None),
    }
}

/// Collect queue occupancy stats via `tc -s qdisc show`.
/// Returns (avg_queue_packets, drop_count) or (None, None) if tc is confused.
/// tc -s output is not JSON. It's not anything. It's just vibes.
async fn collect_queue_stats() -> (Option<f64>, Option<u64>) {
    let output = Command::new("sudo")
        .args(["tc", "-s", "qdisc", "show"])
        .output()
        .await;

    match output {
        Ok(out) => {
            let text = String::from_utf8_lossy(&out.stdout);
            parse_tc_queue_stats(&text)
        }
        Err(_) => (None, None),
    }
}

/// Parse `tc -s qdisc show` output for queue backlog and drops.
/// tc output looks like: "backlog 47180b 32p requeues 0" — completely unambiguous, obviously.
/// We extract the packet count ("32p") and the drop count from "dropped X".
fn parse_tc_queue_stats(tc_output: &str) -> (Option<f64>, Option<u64>) {
    let mut queue_packets: Option<f64> = None;
    let mut drops: Option<u64> = None;

    for line in tc_output.lines() {
        // Look for "backlog Nb Mp" — N bytes, M packets
        if line.contains("backlog") {
            if let Some(packets) = extract_backlog_packets(line) {
                queue_packets = Some(packets as f64);
            }
        }
        // Look for "dropped N" in the stats lines
        if line.contains("dropped") {
            if let Some(d) = extract_dropped(line) {
                drops = Some(drops.unwrap_or(0) + d);
            }
        }
    }

    (queue_packets, drops)
}

/// Extract packet count from a tc backlog line like "backlog 47180b 32p requeues 0".
/// The "p" suffix marks packet count. This is about as close to a spec as tc gets.
fn extract_backlog_packets(line: &str) -> Option<u64> {
    for token in line.split_whitespace() {
        if let Some(stripped) = token.strip_suffix('p') {
            if let Ok(n) = stripped.parse::<u64>() {
                return Some(n);
            }
        }
    }
    None
}

/// Extract dropped count from a tc stats line like "Sent 0 bytes 0 pkt (dropped 12, ...)".
fn extract_dropped(line: &str) -> Option<u64> {
    // Find "dropped " and parse the number after it
    let idx = line.find("dropped ")?;
    let after = &line[idx + 8..];
    let num_str = after.split(|c: char| !c.is_ascii_digit()).next()?;
    num_str.parse::<u64>().ok()
}

// ─── Result Assembly ──────────────────────────────────────────────────────────

/// Assemble a complete ExperimentResult from all the collected pieces.
/// This is where all the raw numbers become meaningful (or reveal they're garbage).
fn assemble_result(
    cca: &str,
    rtt_ms: u64,
    buffer_bytes: u64,
    config: &ExperimentConfig,
    timestamp: String,
    mice_fcts: Vec<f64>,
    elephant: (Option<f64>, Option<u64>),
    queue: (Option<f64>, Option<u64>),
) -> ExperimentResult {

    // Compute FCT statistics if we have any valid measurements.
    // If mice_fcts is empty, something went very wrong. The error field will say what.
    let mice_fct_mean_s = if mice_fcts.is_empty() {
        None
    } else {
        Some(mice_fcts.iter().sum::<f64>() / mice_fcts.len() as f64)
    };

    let mice_fct_p99_s = percentile(&mice_fcts, 99.0);
    let mice_fct_min_s = mice_fcts.iter().cloned().reduce(f64::min);
    let mice_fct_max_s = mice_fcts.iter().cloned().reduce(f64::max);

    // Average mice throughput — should be (mice_size_mb * 8) / mean_fct Mbps.
    // Under BBR with a 10KB buffer, you'll get something embarrassing instead.
    let mice_throughput_mbps = mice_fct_mean_s.map(|fct| {
        (config.mice_size_mb as f64 * 8.0) / fct
    });

    // Jain's fairness index — measures how fairly bandwidth is shared.
    // Formula: (sum xi)^2 / (n * sum xi^2). Range [1/n, 1.0]. 1.0 = perfect equity.
    // With BBR hogging the link, expect something that makes you uncomfortable.
    let jains_fairness = compute_jains_fairness(&mice_fcts, elephant.0);

    ExperimentResult {
        cca: cca.to_string(),
        rtt_ms,
        buffer_bytes,
        bw_mbps: config.bw_mbps,
        timestamp,
        elephant_goodput_mbps: elephant.0,
        elephant_retransmits: elephant.1,
        mice_fcts_s: mice_fcts,
        mice_fct_mean_s,
        mice_fct_p99_s,
        mice_fct_min_s,
        mice_fct_max_s,
        jains_fairness,
        mice_throughput_mbps,
        queue_avg_packets: queue.0,
        queue_drops: queue.1,
        error: None,
    }
}

/// Compute Jain's fairness index across all flows (mice + elephant).
/// JFI = (Σxi)² / (n × Σxi²) where xi is throughput of flow i.
/// This is the same formula used in the Python analysis scripts.
/// We include it in Rust so the HTML report can show it without calling Python.
fn compute_jains_fairness(mice_fcts: &[f64], elephant_mbps: Option<f64>) -> Option<f64> {
    let mice_size_mb = 1.0_f64; // 1MB per mouse flow — hardcoded because it's always 1MB
    let mut throughputs: Vec<f64> = mice_fcts
        .iter()
        .filter(|&&fct| fct > 0.0)
        .map(|&fct| (mice_size_mb * 8.0) / fct)
        .collect();

    if let Some(e) = elephant_mbps {
        throughputs.push(e);
    }

    if throughputs.is_empty() {
        return None;
    }

    let n = throughputs.len() as f64;
    let sum: f64 = throughputs.iter().sum();
    let sum_sq: f64 = throughputs.iter().map(|x| x * x).sum();

    if sum_sq == 0.0 {
        return None;
    }

    Some((sum * sum) / (n * sum_sq))
}

/// Compute a percentile from a sorted slice.
/// Uses nearest-rank method — simple and reproducible.
/// "p99" sounds impressive in a paper. It's just the second-worst value if n=100.
fn percentile(values: &[f64], p: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let idx = ((p / 100.0) * sorted.len() as f64).ceil() as usize;
    let idx = idx.saturating_sub(1).min(sorted.len() - 1);
    Some(sorted[idx])
}

// ─── Persistence ──────────────────────────────────────────────────────────────

/// Save one experiment result to a JSON file immediately after it completes.
/// Naming: {cca}_{buf}B_{rtt}ms_{timestamp}.json — same scheme as the Python scripts.
/// This way MiceWatch results and Python results can live in the same directory without
/// confusing the analysis scripts. Probably. No promises.
pub fn save_result_json(result: &ExperimentResult, output_dir: &str) -> anyhow::Result<()> {
    let ts = result.timestamp.replace(':', "-").replace('.', "-");
    let filename = format!(
        "{}/{}_{}B_{}ms_{}.json",
        output_dir, result.cca, result.buffer_bytes, result.rtt_ms, ts
    );

    let json = serde_json::to_string_pretty(result)?;
    fs::write(&filename, json)?;
    println!("  [saved] {}", filename);
    Ok(())
}

/// Load existing results from a directory full of JSON files.
/// Used by --report-only mode — reads all .json files and deserializes them.
/// Silently skips files that fail to parse. They're probably corrupt. Move on.
pub async fn load_existing_results(output_dir: &str) -> anyhow::Result<Vec<ExperimentResult>> {
    let mut results = Vec::new();

    let entries = fs::read_dir(output_dir)
        .map_err(|e| anyhow::anyhow!("Cannot read output directory '{}': {}", output_dir, e))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map(|e| e == "json").unwrap_or(false) {
            match fs::read_to_string(&path) {
                Ok(content) => {
                    match serde_json::from_str::<ExperimentResult>(&content) {
                        Ok(result) => results.push(result),
                        Err(e) => eprintln!("[warn] skipping {:?}: parse error: {}", path, e),
                    }
                }
                Err(e) => eprintln!("[warn] cannot read {:?}: {}", path, e),
            }
        }
    }

    println!("[loaded] {} result files from '{}'", results.len(), output_dir);
    Ok(results)
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/// Build a failed experiment result when something actually exploded.
/// We record the error so the HTML report can show it instead of just leaving a gap.
fn make_error_result(
    cca: &str,
    rtt_ms: u64,
    buffer_bytes: u64,
    config: &ExperimentConfig,
    error: &str,
) -> ExperimentResult {
    ExperimentResult {
        cca: cca.to_string(),
        rtt_ms,
        buffer_bytes,
        bw_mbps: config.bw_mbps,
        timestamp: chrono_timestamp(),
        elephant_goodput_mbps: None,
        elephant_retransmits: None,
        mice_fcts_s: vec![],
        mice_fct_mean_s: None,
        mice_fct_p99_s: None,
        mice_fct_min_s: None,
        mice_fct_max_s: None,
        jains_fairness: None,
        mice_throughput_mbps: None,
        queue_avg_packets: None,
        queue_drops: None,
        error: Some(error.to_string()),
    }
}

/// Get current timestamp as a sortable string.
/// Used for filenames. Not using chrono crate — std::time is enough for this.
fn chrono_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    // Format as YYYYMMDD-HHMMSS — sortable, no colons, no drama
    let s = secs % 86400;
    let d = secs / 86400;
    format!("{:05}-{:05}", d, s)
}

/// Format bytes into a human-readable label.
/// Duplicated from main.rs because the alternative is a shared util module
/// and that's more ceremony than this function deserves.
fn format_bytes(bytes: u64) -> String {
    if bytes >= 1_000_000 {
        format!("{}MB", bytes / 1_000_000)
    } else if bytes >= 1_000 {
        format!("{}KB", bytes / 1_000)
    } else {
        format!("{}B", bytes)
    }
}
