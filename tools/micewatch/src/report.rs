// report.rs — generates a self-contained HTML report from experiment results.
// No Python. No external charting library. Just Rust writing HTML with embedded JS.
// Is this the most elegant approach? No. Does it produce a single file you can email
// to your advisor? Yes. Pragmatism wins.

use std::fs;
use std::collections::HashMap;
use crate::runner::ExperimentResult;

/// Generate a self-contained HTML report from all experiment results.
/// Output: {output_dir}/report.html — one file, no dependencies, open in any browser.
/// All charts are rendered with vanilla JS + SVG. Because adding a chart library
/// to a Rust binary that generates HTML is a layer of indirection nobody asked for.
pub fn generate_html_report(results: &[ExperimentResult], output_dir: &str) -> anyhow::Result<()> {
    fs::create_dir_all(output_dir)?;

    let html = build_html(results);
    let report_path = format!("{}/report.html", output_dir);
    fs::write(&report_path, html)?;

    println!("[report] written to {}", report_path);
    Ok(())
}

/// Build the complete HTML document as a String.
/// It's long. It's a report. That's what reports are.
fn build_html(results: &[ExperimentResult]) -> String {
    let summary_table = build_summary_table(results);
    let fct_chart_data = build_fct_chart_data(results);
    let fairness_table = build_fairness_table(results);
    let error_section = build_error_section(results);
    let run_count = results.len();
    let valid_count = results.iter().filter(|r| r.error.is_none()).count();

    format!(r#"<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MiceWatch Report</title>
<style>
  /* The CSS that makes this look like a research tool and not a homework assignment */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242736;
    --border: #2e3347;
    --text: #e2e4f0;
    --muted: #8b90a8;
    --accent: #7c8cf8;
    --green: #4ade80;
    --red: #f87171;
    --amber: #fbbf24;
    --blue: #60a5fa;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 13px;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.6rem; color: var(--accent); margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.1rem; color: var(--text); margin: 2rem 0 0.75rem; padding-bottom: 0.4rem;
        border-bottom: 1px solid var(--border); }}
  .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 2rem; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
             font-size: 0.75rem; font-weight: 600; margin-right: 6px; }}
  .badge-blue {{ background: #1e3a5f; color: var(--blue); }}
  .badge-green {{ background: #14532d; color: var(--green); }}
  .badge-amber {{ background: #451a03; color: var(--amber); }}
  .badge-red {{ background: #450a0a; color: var(--red); }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }}
  th {{ background: var(--surface2); color: var(--muted); font-weight: 600;
        text-align: left; padding: 8px 12px; font-size: 0.75rem;
        text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }}
  td {{ padding: 7px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: var(--surface2); }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .good {{ color: var(--green); }}
  .bad {{ color: var(--red); }}
  .warn {{ color: var(--amber); }}
  .na {{ color: var(--muted); }}
  .chart-container {{ background: var(--surface); border: 1px solid var(--border);
                      border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }}
  .chart-container svg {{ width: 100%; display: block; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 1rem; margin-bottom: 1.5rem; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border);
                border-radius: 8px; padding: 1rem; }}
  .stat-label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase;
                 letter-spacing: 0.05em; margin-bottom: 0.25rem; }}
  .stat-value {{ font-size: 1.4rem; color: var(--text); }}
  .stat-unit {{ font-size: 0.75rem; color: var(--muted); }}
  .error-block {{ background: #1c0a0a; border: 1px solid #7f1d1d;
                  border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 0.75rem; }}
  .error-block code {{ color: var(--red); font-size: 0.8rem; }}
  footer {{ color: var(--muted); font-size: 0.75rem; margin-top: 3rem;
            padding-top: 1rem; border-top: 1px solid var(--border); }}
</style>
</head>
<body>

<h1>MiceWatch</h1>
<p class="subtitle">
  BBR/CUBIC/Reno FCT characterization &mdash; mixed elephant+mice workloads &mdash;
  <span class="badge badge-blue">{run_count} runs</span>
  <span class="badge badge-green">{valid_count} valid</span>
  <span class="badge badge-amber">extends Cao et al. IMC 2019</span>
</p>

<h2>Summary statistics</h2>
<div class="stat-grid">
{stat_cards}
</div>

<h2>Per-run results</h2>
{summary_table}

<h2>FCT by CCA and buffer size</h2>
<p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem;">
  Mean mice FCT in seconds. Lower is better.
  BBR's ProbeBW standing queue inflates FCT under shallow buffers.
  That's not a bug in MiceWatch &mdash; it's the research question.
</p>
<div class="chart-container">
  <canvas id="fctChart" height="320"></canvas>
</div>

<h2>Jain&apos;s fairness index</h2>
<p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem;">
  JFI = 1.0 means perfect bandwidth sharing between elephant and mice.
  Values below 0.5 mean someone is getting crushed. Guess who.
</p>
{fairness_table}

{error_section}

<footer>
  Generated by MiceWatch v0.1.0 &mdash; Adri Katyayan &mdash;
  BBR congestion control research, Stony Brook University CSE 534
</footer>

<script>
// Vanilla JS bar chart — no external libraries, no CDN dependencies, no drama.
// If the recruiter is reading the source: yes, this is hand-rolled. That's the point.
const chartData = {fct_chart_data};

(function() {{
  const canvas = document.getElementById('fctChart');
  if (!canvas || !chartData.length) return;
  const ctx = canvas.getContext('2d');

  const margin = {{ top: 20, right: 20, bottom: 60, left: 60 }};
  const W = canvas.offsetWidth || 900;
  const H = 320;
  canvas.width = W;
  canvas.height = H;

  const innerW = W - margin.left - margin.right;
  const innerH = H - margin.top - margin.bottom;

  // Group by CCA
  const ccas = [...new Set(chartData.map(d => d.cca))];
  const buffers = [...new Set(chartData.map(d => d.buf))].sort((a,b) => a-b);
  const colors = {{ bbr: '#f87171', cubic: '#60a5fa', reno: '#4ade80' }};

  const maxFct = Math.max(...chartData.map(d => d.fct), 0.1) * 1.1;
  const groupW = innerW / buffers.length;
  const barW = groupW / (ccas.length + 1);

  ctx.save();
  ctx.translate(margin.left, margin.top);

  // Draw gridlines — because squinting at unlabeled bars is not research
  ctx.strokeStyle = '#2e3347';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 5; i++) {{
    const y = innerH - (i / 5) * innerH;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(innerW, y);
    ctx.stroke();
    ctx.fillStyle = '#8b90a8';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText((maxFct * i / 5).toFixed(2) + 's', -6, y + 4);
  }}

  // Draw bars
  buffers.forEach((buf, bi) => {{
    const groupX = bi * groupW + barW / 2;
    ccas.forEach((cca, ci) => {{
      const d = chartData.find(x => x.cca === cca && x.buf === buf);
      if (!d) return;
      const barH = (d.fct / maxFct) * innerH;
      const x = groupX + ci * barW;
      const y = innerH - barH;
      ctx.fillStyle = colors[cca] || '#7c8cf8';
      ctx.globalAlpha = 0.85;
      ctx.fillRect(x, y, barW - 2, barH);
      ctx.globalAlpha = 1;
    }});

    // Buffer label on x-axis
    ctx.fillStyle = '#8b90a8';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    const label = buf >= 1000000 ? (buf/1000000)+'MB' : buf >= 1000 ? (buf/1000)+'KB' : buf+'B';
    ctx.fillText(label, groupX + (ccas.length * barW) / 2 - barW/2, innerH + 16);
  }});

  // Legend
  ccas.forEach((cca, i) => {{
    ctx.fillStyle = colors[cca] || '#7c8cf8';
    ctx.fillRect(i * 80, innerH + 32, 12, 12);
    ctx.fillStyle = '#e2e4f0';
    ctx.font = '11px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(cca.toUpperCase(), i * 80 + 16, innerH + 43);
  }});

  ctx.restore();
}})();
</script>

</body>
</html>"#,
        run_count = run_count,
        valid_count = valid_count,
        stat_cards = build_stat_cards(results),
        summary_table = summary_table,
        fct_chart_data = fct_chart_data,
        fairness_table = fairness_table,
        error_section = error_section,
    )
}

// ─── Component Builders ───────────────────────────────────────────────────────

/// Build the top-level stat cards — headline numbers at a glance.
/// These are the numbers a recruiter will screenshot. Make them readable.
fn build_stat_cards(results: &[ExperimentResult]) -> String {
    let valid: Vec<&ExperimentResult> = results.iter().filter(|r| r.error.is_none()).collect();
    if valid.is_empty() {
        return r#"<div class="stat-card"><div class="stat-label">status</div>
                  <div class="stat-value bad">no valid results</div></div>"#.to_string();
    }

    let all_fcts: Vec<f64> = valid.iter()
        .flat_map(|r| r.mice_fcts_s.iter().cloned())
        .collect();

    let mean_fct = if all_fcts.is_empty() { None } else {
        Some(all_fcts.iter().sum::<f64>() / all_fcts.len() as f64)
    };

    // Worst BBR FCT — the headline finding
    let worst_bbr_fct = valid.iter()
        .filter(|r| r.cca == "bbr")
        .filter_map(|r| r.mice_fct_max_s)
        .reduce(f64::max);

    // Best Jain fairness across all runs
    let best_jfi = valid.iter().filter_map(|r| r.jains_fairness).reduce(f64::max);
    let worst_jfi = valid.iter().filter_map(|r| r.jains_fairness).reduce(f64::min);

    let mut cards = String::new();

    if let Some(fct) = mean_fct {
        cards.push_str(&format!(
            r#"<div class="stat-card">
               <div class="stat-label">mean mice FCT (all)</div>
               <div class="stat-value {}">{:.3} <span class="stat-unit">s</span></div>
               </div>"#,
            if fct > 1.0 { "bad" } else if fct > 0.3 { "warn" } else { "good" },
            fct
        ));
    }

    if let Some(fct) = worst_bbr_fct {
        cards.push_str(&format!(
            r#"<div class="stat-card">
               <div class="stat-label">worst BBR mice FCT</div>
               <div class="stat-value bad">{:.3} <span class="stat-unit">s</span></div>
               </div>"#,
            fct
        ));
    }

    if let Some(jfi) = best_jfi {
        cards.push_str(&format!(
            r#"<div class="stat-card">
               <div class="stat-label">best Jain fairness</div>
               <div class="stat-value good">{:.4}</div>
               </div>"#,
            jfi
        ));
    }

    if let Some(jfi) = worst_jfi {
        cards.push_str(&format!(
            r#"<div class="stat-card">
               <div class="stat-label">worst Jain fairness</div>
               <div class="stat-value bad">{:.4}</div>
               </div>"#,
            jfi
        ));
    }

    cards.push_str(&format!(
        r#"<div class="stat-card">
           <div class="stat-label">valid experiments</div>
           <div class="stat-value">{} <span class="stat-unit">/ {}</span></div>
           </div>"#,
        valid.len(),
        results.len()
    ));

    cards
}

/// Build the main per-run results table.
/// Sorted by CCA, then RTT, then buffer size. Consistent with the Python analysis scripts.
fn build_summary_table(results: &[ExperimentResult]) -> String {
    let mut sorted = results.to_vec();
    sorted.sort_by(|a, b| {
        a.cca.cmp(&b.cca)
            .then(a.rtt_ms.cmp(&b.rtt_ms))
            .then(a.buffer_bytes.cmp(&b.buffer_bytes))
    });

    let mut rows = String::new();
    for r in &sorted {
        let fct_cell = match r.mice_fct_mean_s {
            Some(f) => format!(
                r#"<td class="num {}">{:.4}</td>"#,
                if f > 1.0 { "bad" } else if f > 0.3 { "warn" } else { "good" },
                f
            ),
            None => r#"<td class="num na">—</td>"#.to_string(),
        };
        let p99_cell = match r.mice_fct_p99_s {
            Some(f) => format!(r#"<td class="num">{:.4}</td>"#, f),
            None => r#"<td class="num na">—</td>"#.to_string(),
        };
        let elephant_cell = match r.elephant_goodput_mbps {
            Some(g) => format!(r#"<td class="num">{:.1}</td>"#, g),
            None => r#"<td class="num na">—</td>"#.to_string(),
        };
        let jfi_cell = match r.jains_fairness {
            Some(j) => format!(
                r#"<td class="num {}">{:.4}</td>"#,
                if j > 0.8 { "good" } else if j > 0.5 { "warn" } else { "bad" },
                j
            ),
            None => r#"<td class="num na">—</td>"#.to_string(),
        };
        let drops_cell = match r.queue_drops {
            Some(d) => format!(
                r#"<td class="num {}">{}</td>"#,
                if d > 0 { "warn" } else { "" },
                d
            ),
            None => r#"<td class="num na">—</td>"#.to_string(),
        };
        let error_cell = match &r.error {
            Some(e) => format!(r#"<td class="bad" title="{}">[error]</td>"#, e.replace('"', "&quot;")),
            None => r#"<td class="good">ok</td>"#.to_string(),
        };

        rows.push_str(&format!(
            "<tr><td><span class=\"badge badge-{cca_color}\">{cca}</span></td>\
             <td class=\"num\">{rtt}</td>\
             <td class=\"num\">{buf}</td>\
             {fct_cell}{p99_cell}{elephant_cell}{jfi_cell}{drops_cell}{error_cell}</tr>",
            cca_color = match r.cca.as_str() { "bbr" => "red", "cubic" => "blue", _ => "green" },
            cca = r.cca,
            rtt = r.rtt_ms,
            buf = format_bytes(r.buffer_bytes),
        ));
    }

    format!(
        r#"<table>
           <thead><tr>
             <th>CCA</th><th>RTT (ms)</th><th>Buffer</th>
             <th>Mean FCT (s)</th><th>p99 FCT (s)</th>
             <th>Elephant (Mbps)</th><th>JFI</th><th>Drops</th><th>Status</th>
           </tr></thead>
           <tbody>{}</tbody>
           </table>"#,
        rows
    )
}

/// Build chart data as a JSON array for the vanilla JS bar chart.
/// Format: [{cca: "bbr", buf: 10000, fct: 12.3}, ...]
/// RTT is averaged out — the chart shows FCT vs buffer size, not all three dimensions.
/// A 3D chart in vanilla JS is a great way to spend a week. We're not doing that.
fn build_fct_chart_data(results: &[ExperimentResult]) -> String {
    // Group by (cca, buffer) and average FCT across RTTs
    let mut groups: HashMap<(String, u64), Vec<f64>> = HashMap::new();
    for r in results {
        if let Some(fct) = r.mice_fct_mean_s {
            groups
                .entry((r.cca.clone(), r.buffer_bytes))
                .or_default()
                .push(fct);
        }
    }

    let mut entries: Vec<String> = groups
        .iter()
        .map(|((cca, buf), fcts)| {
            let avg = fcts.iter().sum::<f64>() / fcts.len() as f64;
            format!(r#"{{"cca":"{}","buf":{},"fct":{:.4}}}"#, cca, buf, avg)
        })
        .collect();

    entries.sort(); // deterministic order for reproducible reports
    format!("[{}]", entries.join(","))
}

/// Build the Jain's fairness index table.
/// Grouped by CCA for easy comparison. This is the table Mehtaab will reference
/// in Section 4 and Section 5. Keep it readable.
fn build_fairness_table(results: &[ExperimentResult]) -> String {
    let mut sorted = results.to_vec();
    sorted.sort_by(|a, b| {
        a.cca.cmp(&b.cca)
            .then(a.buffer_bytes.cmp(&b.buffer_bytes))
            .then(a.rtt_ms.cmp(&b.rtt_ms))
    });

    let mut rows = String::new();
    for r in sorted.iter().filter(|r| r.jains_fairness.is_some()) {
        let jfi = r.jains_fairness.unwrap();
        rows.push_str(&format!(
            "<tr><td><span class=\"badge badge-{cca_color}\">{cca}</span></td>\
             <td class=\"num\">{buf}</td>\
             <td class=\"num\">{rtt}</td>\
             <td class=\"num {cls}\">{jfi:.4}</td>\
             <td class=\"num\">{mice}</td></tr>",
            cca_color = match r.cca.as_str() { "bbr" => "red", "cubic" => "blue", _ => "green" },
            cca = r.cca,
            buf = format_bytes(r.buffer_bytes),
            rtt = r.rtt_ms,
            cls = if jfi > 0.8 { "good" } else if jfi > 0.5 { "warn" } else { "bad" },
            mice = r.mice_fcts_s.len(),
        ));
    }

    if rows.is_empty() {
        return "<p style=\"color:var(--muted)\">No fairness data available yet. Run experiments first.</p>".to_string();
    }

    format!(
        r#"<table>
           <thead><tr>
             <th>CCA</th><th>Buffer</th><th>RTT (ms)</th>
             <th>Jain Fairness Index</th><th>Mice flows measured</th>
           </tr></thead>
           <tbody>{}</tbody>
           </table>"#,
        rows
    )
}

/// Build the error section — shows failed experiments with their error messages.
/// Hidden if there are no errors, because we're optimists.
fn build_error_section(results: &[ExperimentResult]) -> String {
    let errors: Vec<&ExperimentResult> = results.iter()
        .filter(|r| r.error.is_some())
        .collect();

    if errors.is_empty() {
        return String::new();
    }

    let mut blocks = String::new();
    for r in &errors {
        let err = r.error.as_deref().unwrap_or("unknown error");
        blocks.push_str(&format!(
            r#"<div class="error-block">
               <strong>{cca} / {buf} / {rtt}ms</strong><br>
               <code>{err}</code>
               </div>"#,
            cca = r.cca,
            buf = format_bytes(r.buffer_bytes),
            rtt = r.rtt_ms,
            err = err,
        ));
    }

    format!(
        r#"<h2>Errors ({count})</h2>
           <p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem;">
             These experiments failed. Usually Mininet's fault. Check that mn --test pingall works.
           </p>
           {blocks}"#,
        count = errors.len(),
    )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/// Format bytes for display in the HTML report.
/// Duplicated from runner.rs and main.rs. Third copy of this function.
/// At this point it should be in a utils module. It won't be. Accept it.
fn format_bytes(bytes: u64) -> String {
    if bytes >= 1_000_000 {
        format!("{}MB", bytes / 1_000_000)
    } else if bytes >= 1_000 {
        format!("{}KB", bytes / 1_000)
    } else {
        format!("{}B", bytes)
    }
}