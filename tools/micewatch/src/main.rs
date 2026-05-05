// main.rs — MiceWatch CLI entry point
// If you're reading this, congratulations: you found the one file that actually
// does something useful instead of just parsing YAML for a living.

mod runner;
mod report;

use clap::Parser;
use runner::{ExperimentConfig, SweepConfig, run_sweep};

/// MiceWatch — characterizes BBR's latency impact on short flows.
/// Because someone had to measure how badly BBR crushes your tiny HTTP requests.
#[derive(Parser, Debug)]
#[command(
    name = "micewatch",
    version = "0.1.0",
    author = "Adri Katyayan",
    about = "Orchestrates Mininet experiments to characterize BBR/CUBIC/Reno \
             FCT degradation under mixed elephant+mice workloads. \
             Extends Cao et al. IMC 2019. Yes, this is a resume project. \
             No, that doesn't make the measurements less real."
)]
struct Cli {
    /// Bottleneck bandwidth in Mbps. 100 is the sweet spot — fast enough to matter,
    /// slow enough that BBR's standing queue actually shows up.
    #[arg(long, default_value_t = 100)]
    bw_mbps: u64,

    /// RTT values to sweep in milliseconds, comma-separated.
    /// 10ms = datacenter, 40ms = cross-country, 100ms = "why is my ping so bad".
    #[arg(long, default_value = "10,40,100")]
    rtts_ms: String,

    /// Buffer sizes to sweep in bytes, comma-separated.
    /// 10000 = "lol no buffer", 200000 = realistic, 10000000 = "I have trust issues".
    #[arg(long, default_value = "10000,200000,10000000")]
    buffers_bytes: String,

    /// Congestion control algorithms to test, comma-separated.
    /// bbr, cubic, reno — the holy trinity of TCP arguments on the internet.
    #[arg(long, default_value = "bbr,cubic,reno")]
    ccas: String,

    /// Duration of the elephant (bulk) flow in seconds.
    /// 120s because you need enough time to grab a coffee and come back.
    #[arg(long, default_value_t = 120)]
    elephant_duration_s: u64,

    /// Number of sequential mice (short) flows per experiment.
    /// Each is exactly 1MB — small enough to be a "request", big enough to measure.
    #[arg(long, default_value_t = 10)]
    num_mice: u32,

    /// Size of each mouse flow in megabytes. 1MB. Don't change this.
    /// The whole point is that 1MB should finish in ~80ms at 100Mbps. It won't.
    #[arg(long, default_value_t = 1)]
    mice_size_mb: u32,

    /// Output directory for results JSON and the HTML report.
    /// Will be created if it doesn't exist, because we're not animals.
    #[arg(long, default_value = "results/micewatch")]
    output_dir: String,

    /// iperf3 server port for the elephant flow.
    #[arg(long, default_value_t = 5201)]
    elephant_port: u16,

    /// iperf3 server port for mice flows.
    #[arg(long, default_value_t = 5202)]
    mice_port: u16,

    /// Skip the actual Mininet experiments and just regenerate the HTML report
    /// from an existing results directory. Useful when your Mininet is broken
    /// (which is always) but your data is intact.
    #[arg(long, default_value_t = false)]
    report_only: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Parse CLI args. clap does the heavy lifting so we don't have to write
    // another hand-rolled argument parser like it's 1995.
    let cli = Cli::parse();

    // Parse the comma-separated sweep parameters.
    // Yes, this is manual. No, clap doesn't do this automatically. Yes, it's annoying.
    let rtts_ms: Vec<u64> = parse_csv_u64(&cli.rtts_ms)
        .expect("--rtts-ms must be comma-separated integers like '10,40,100'");

    let buffers_bytes: Vec<u64> = parse_csv_u64(&cli.buffers_bytes)
        .expect("--buffers-bytes must be comma-separated integers like '10000,200000,10000000'");

    let ccas: Vec<String> = cli.ccas
        .split(',')
        .map(|s| s.trim().to_string())
        .collect();

    // Validate CCAs — only these three exist in a vanilla kernel.
    // If you want bbr3, compile the google/bbr module yourself. We're not doing that here.
    for cca in &ccas {
        match cca.as_str() {
            "bbr" | "cubic" | "reno" => {},
            other => {
                eprintln!("[ERROR] Unknown CCA '{}'. Supported: bbr, cubic, reno.", other);
                eprintln!("        BBRv3 requires a custom kernel module. MiceWatch doesn't handle that.");
                std::process::exit(1);
            }
        }
    }

    // Print the sweep summary so the user knows what they're in for.
    let total_configs = ccas.len() * rtts_ms.len() * buffers_bytes.len();
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║                    MiceWatch v0.1.0                         ║");
    println!("║   Characterizing BBR's latency impact on short flows        ║");
    println!("╚══════════════════════════════════════════════════════════════╝");
    println!();
    println!("  CCAs:        {}", ccas.join(", "));
    println!("  RTTs (ms):   {}", rtts_ms.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(", "));
    println!("  Buffers:     {}", buffers_bytes.iter().map(|v| format_bytes(*v)).collect::<Vec<_>>().join(", "));
    println!("  Elephant:    {}s, port {}", cli.elephant_duration_s, cli.elephant_port);
    println!("  Mice:        {} × {}MB, port {}", cli.num_mice, cli.mice_size_mb, cli.mice_port);
    println!("  Total runs:  {}", total_configs);
    println!("  Est. time:   ~{} minutes (go touch grass)", total_configs * 2);
    println!("  Output:      {}", cli.output_dir);
    println!();

    if cli.report_only {
        // Skip experiments, just regenerate the report from existing data.
        println!("[mode] report-only — skipping experiments, reading existing results");
        let results = runner::load_existing_results(&cli.output_dir).await?;
        report::generate_html_report(&results, &cli.output_dir)?;
        println!("[done] report regenerated at {}/report.html", cli.output_dir);
        return Ok(());
    }

    // Build the sweep config — this is the struct that runner.rs consumes.
    let sweep = SweepConfig {
        ccas,
        rtts_ms,
        buffers_bytes,
        experiment: ExperimentConfig {
            bw_mbps: cli.bw_mbps,
            elephant_duration_s: cli.elephant_duration_s,
            num_mice: cli.num_mice,
            mice_size_mb: cli.mice_size_mb,
            elephant_port: cli.elephant_port,
            mice_port: cli.mice_port,
            output_dir: cli.output_dir.clone(),
        },
    };

    // Run the full sweep. This is where all the actual work happens.
    // main.rs is just the bouncer; runner.rs is the nightclub.
    let results = run_sweep(sweep).await?;

    // Generate the HTML report from collected results.
    println!("\n[report] generating HTML report...");
    report::generate_html_report(&results, &cli.output_dir)?;

    println!("\n╔══════════════════════════════════════════════════════════════╗");
    println!("║  All experiments complete.                                   ║");
    println!("║  Open {}/report.html in a browser.      ║", cli.output_dir);
    println!("╚══════════════════════════════════════════════════════════════╝");

    Ok(())
}

/// Parse a comma-separated string of u64 values.
/// Shockingly, this is not in std. Shockingly.
fn parse_csv_u64(s: &str) -> Result<Vec<u64>, String> {
    s.split(',')
        .map(|v| {
            v.trim()
                .parse::<u64>()
                .map_err(|e| format!("'{}' is not a valid integer: {}", v.trim(), e))
        })
        .collect()
}

/// Format bytes into a human-readable string because 10000000 is not legible.
/// This is the one function in this file that genuinely sparks joy.
fn format_bytes(bytes: u64) -> String {
    if bytes >= 1_000_000 {
        format!("{}MB", bytes / 1_000_000)
    } else if bytes >= 1_000 {
        format!("{}KB", bytes / 1_000)
    } else {
        format!("{}B", bytes)
    }
}
