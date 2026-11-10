"""
Zero-dependency SVG Plot Generator for DBMS Assignment 1 (Topic G13)
Generates publication-quality SVG charts from benchmark_results.csv.
Role: S3 (Implementation Lead) & S4 (Analysis Lead)
"""

import csv
import math
import os

def load_data(csv_path="benchmark_results.csv"):
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "Database": r["Database"],
                "Scale": int(r["Scale"]),
                "Workload": r["Workload"],
                "Throughput": float(r["Throughput (ops/sec)"]),
                "p50": float(r["p50 Latency (ms)"]),
                "p95": float(r["p95 Latency (ms)"]),
                "p99": float(r["p99 Latency (ms)"]),
                "Time": float(r["Total Time (s)"])
            })
    return rows


def generate_bar_chart_svg(rows, scale_val, metric_key, title, y_label, filename, log_scale=True):
    sub = [r for r in rows if r["Scale"] == scale_val]
    workloads = ["Batch Insert", "Point Lookup", "Filtered Scan", "Field Update"]
    dbs = ["PostgreSQL (JSONB)", "MongoDB (WiredTiger)", "Redis (In-Memory KV)"]
    colors = {
        "PostgreSQL (JSONB)": "#2b5c8f",
        "MongoDB (WiredTiger)": "#13aa52",
        "Redis (In-Memory KV)": "#d82c20"
    }

    width = 800
    height = 500
    margin_top = 60
    margin_bottom = 80
    margin_left = 90
    margin_right = 40

    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    # Find min/max for scale
    vals = [r[metric_key] for r in sub]
    if log_scale:
        min_v = max(0.01, min(vals) * 0.5)
        max_v = max(vals) * 2.0
        log_min = math.log10(min_v)
        log_max = math.log10(max_v)
    else:
        min_v = 0
        max_v = max(vals) * 1.15

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background-color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif;">')

    # Title
    svg.append(f'<text x="{width/2}" y="32" text-anchor="middle" font-size="18" font-weight="bold" fill="#111827">{title} (Scale = {scale_val:,})</text>')

    # Y-axis ticks & gridlines
    if log_scale:
        start_exp = int(math.floor(log_min))
        end_exp = int(math.ceil(log_max))
        for exp in range(start_exp, end_exp + 1):
            val = 10 ** exp
            if val < min_v or val > max_v:
                continue
            y = margin_top + plot_h - ((exp - log_min) / (log_max - log_min)) * plot_h
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{width - margin_right}" y2="{y}" stroke="#e5e7eb" stroke-dasharray="4,4"/>')
            label = f"10^{exp}" if exp != 0 else "1"
            if exp >= 3:
                label = f"{10**exp:,}"
            elif exp < 0:
                label = f"{val:.2f}"
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-size="11" fill="#6b7280">{label}</text>')
    else:
        num_ticks = 5
        for i in range(num_ticks + 1):
            val = (max_v / num_ticks) * i
            y = margin_top + plot_h - (i / num_ticks) * plot_h
            svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{width - margin_right}" y2="{y}" stroke="#e5e7eb" stroke-dasharray="4,4"/>')
            svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-size="11" fill="#6b7280">{val:,.0f}</text>')

    # Axes
    svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#374151" stroke-width="1.5"/>')
    svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{width - margin_right}" y2="{margin_top + plot_h}" stroke="#374151" stroke-width="1.5"/>')

    # Y-axis Label
    svg.append(f'<text transform="rotate(-90)" x="{-margin_top - plot_h/2}" y="24" text-anchor="middle" font-size="13" font-weight="600" fill="#374151">{y_label}</text>')

    # Bars
    group_width = plot_w / len(workloads)
    bar_w = group_width * 0.22
    for w_idx, w in enumerate(workloads):
        gx = margin_left + w_idx * group_width
        svg.append(f'<text x="{gx + group_width/2}" y="{margin_top + plot_h + 25}" text-anchor="middle" font-size="12" font-weight="600" fill="#1f2937">{w}</text>')
        for d_idx, db in enumerate(dbs):
            item = next((r for r in sub if r["Workload"] == w and r["Database"] == db), None)
            if item:
                val = item[metric_key]
                if log_scale:
                    clamped_v = max(min_v, val)
                    bar_h = ((math.log10(clamped_v) - log_min) / (log_max - log_min)) * plot_h
                else:
                    bar_h = (val / max_v) * plot_h
                
                bx = gx + (group_width - 3 * bar_w) / 2 + d_idx * bar_w
                by = margin_top + plot_h - bar_h
                color = colors[db]
                svg.append(f'<rect x="{bx}" y="{by}" width="{bar_w - 3}" height="{bar_h}" fill="{color}" rx="2"/>')
                # Value label
                val_str = f"{val:.1f}" if val < 100 else f"{val:,.0f}"
                svg.append(f'<text x="{bx + (bar_w-3)/2}" y="{by - 4}" text-anchor="middle" font-size="9" fill="#374151">{val_str}</text>')

    # Legend
    legend_y = margin_top + plot_h + 55
    legend_start = margin_left + 40
    for i, db in enumerate(dbs):
        lx = legend_start + i * 220
        svg.append(f'<rect x="{lx}" y="{legend_y}" width="14" height="14" fill="{colors[db]}" rx="2"/>')
        svg.append(f'<text x="{lx + 20}" y="{legend_y + 11}" font-size="11" font-weight="500" fill="#374151">{db}</text>')

    svg.append('</svg>')

    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"[✓] Generated SVG: {filename}")


def generate_line_chart_svg(rows, metric_key, title, y_label, filename):
    workload = "Batch Insert"
    sub = [r for r in rows if r["Workload"] == workload]
    dbs = ["PostgreSQL (JSONB)", "MongoDB (WiredTiger)", "Redis (In-Memory KV)"]
    scales = sorted(list(set(r["Scale"] for r in sub)))
    colors = {
        "PostgreSQL (JSONB)": "#2b5c8f",
        "MongoDB (WiredTiger)": "#13aa52",
        "Redis (In-Memory KV)": "#d82c20"
    }

    width = 800
    height = 500
    margin_top = 60
    margin_bottom = 80
    margin_left = 90
    margin_right = 40

    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    vals = [r[metric_key] for r in sub]
    max_v = max(vals) * 1.15

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background-color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif;">')
    svg.append(f'<text x="{width/2}" y="32" text-anchor="middle" font-size="18" font-weight="bold" fill="#111827">{title}</text>')

    # Y-axis ticks
    num_ticks = 5
    for i in range(num_ticks + 1):
        val = (max_v / num_ticks) * i
        y = margin_top + plot_h - (i / num_ticks) * plot_h
        svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{width - margin_right}" y2="{y}" stroke="#e5e7eb" stroke-dasharray="4,4"/>')
        svg.append(f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-size="11" fill="#6b7280">{val:,.0f}</text>')

    # Axes
    svg.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#374151" stroke-width="1.5"/>')
    svg.append(f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{width - margin_right}" y2="{margin_top + plot_h}" stroke="#374151" stroke-width="1.5"/>')
    svg.append(f'<text transform="rotate(-90)" x="{-margin_top - plot_h/2}" y="24" text-anchor="middle" font-size="13" font-weight="600" fill="#374151">{y_label}</text>')

    # X-axis ticks
    scale_x = {}
    for s_idx, s in enumerate(scales):
        x = margin_left + (s_idx / (len(scales) - 1)) * (plot_w - 60) + 30
        scale_x[s] = x
        svg.append(f'<text x="{x}" y="{margin_top + plot_h + 25}" text-anchor="middle" font-size="12" font-weight="600" fill="#1f2937">{s:,}</text>')

    svg.append(f'<text x="{margin_left + plot_w/2}" y="{margin_top + plot_h + 48}" text-anchor="middle" font-size="12" fill="#4b5563">Dataset Scale (Records)</text>')

    # Lines and points
    for db in dbs:
        db_pts = []
        for s in scales:
            item = next((r for r in sub if r["Scale"] == s and r["Database"] == db), None)
            if item:
                x = scale_x[s]
                y = margin_top + plot_h - (item[metric_key] / max_v) * plot_h
                db_pts.append((x, y, item[metric_key]))
        
        path_d = " ".join([f"{'M' if idx == 0 else 'L'} {p[0]:.1f} {p[1]:.1f}" for idx, p in enumerate(db_pts)])
        svg.append(f'<path d="{path_d}" fill="none" stroke="{colors[db]}" stroke-width="3"/>')
        for px, py, val in db_pts:
            svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{colors[db]}" stroke="#ffffff" stroke-width="2"/>')
            svg.append(f'<text x="{px:.1f}" y="{py - 10:.1f}" text-anchor="middle" font-size="10" font-weight="600" fill="{colors[db]}">{val:,.0f}</text>')

    # Legend
    legend_y = margin_top + plot_h + 65
    legend_start = margin_left + 40
    for i, db in enumerate(dbs):
        lx = legend_start + i * 220
        svg.append(f'<rect x="{lx}" y="{legend_y}" width="14" height="14" fill="{colors[db]}" rx="2"/>')
        svg.append(f'<text x="{lx + 20}" y="{legend_y + 11}" font-size="11" font-weight="500" fill="#374151">{db}</text>')

    svg.append('</svg>')

    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"[✓] Generated SVG: {filename}")


if __name__ == "__main__":
    data = load_data()
    generate_bar_chart_svg(data, 100000, "Throughput", "Throughput Across Operations", "Throughput (ops/sec, Log Scale)", "plots/throughput_comparison_100k.svg", log_scale=True)
    generate_bar_chart_svg(data, 100000, "p99", "Tail Latency Comparison (p99)", "Latency (ms, Log Scale)", "plots/p99_latency_comparison_100k.svg", log_scale=True)
    generate_line_chart_svg(data, "Throughput", "Batch Ingestion Scalability Trend", "Throughput (records/sec)", "plots/ingestion_scalability.svg")
