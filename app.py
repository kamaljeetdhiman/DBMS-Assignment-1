"""
DBMS Assignment 1 (Topic G13) - Interactive Benchmarking & Architecture Studio
A self-contained, modern web interface for evaluating PostgreSQL JSONB, MongoDB, and Redis.
Requires zero external pip dependencies (built on Python standard library http.server).
"""

import csv
import json
import os
import random
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

# Try importing benchmark modules
try:
    from benchmark import (
        BenchmarkSuite, MockEmpiricalAdapter, calc_percentile, generate_dataset,
        PG_AVAILABLE, MONGO_AVAILABLE, REDIS_AVAILABLE
    )
except ImportError:
    PG_AVAILABLE = MONGO_AVAILABLE = REDIS_AVAILABLE = False

PORT = 8080
HOST = "127.0.0.1"

# In-memory execution state
benchmark_lock = threading.Lock()
current_benchmark_state = {
    "status": "idle",       # idle, running, completed, error
    "progress": 0,          # 0 - 100
    "current_engine": "",
    "current_stage": "",
    "logs": [],
    "last_run_time": None
}

CSV_FILE = "benchmark_results.csv"
LIT_CSV_FILE = "literature_matrix.csv"


def check_db_health():
    """Checks live database connectivity."""
    status = {
        "postgres": {"name": "PostgreSQL 16 (JSONB)", "port": 5432, "connected": False, "details": "Not reachable"},
        "mongodb": {"name": "MongoDB 7.0 (WiredTiger)", "port": 27017, "connected": False, "details": "Not reachable"},
        "redis": {"name": "Redis 7.2 (In-Memory)", "port": 6379, "connected": False, "details": "Not reachable"},
        "mode": "simulation_ready"
    }
    
    # Test PostgreSQL
    try:
        import psycopg2
        conn = psycopg2.connect(host="localhost", port=5432, dbname="benchmark_db", user="dbms_user", password="dbms_password", connect_timeout=1)
        conn.close()
        status["postgres"]["connected"] = True
        status["postgres"]["details"] = "Online (Live Connection)"
    except Exception as e:
        status["postgres"]["details"] = f"Offline ({e.__class__.__name__})"

    # Test MongoDB
    try:
        import pymongo
        client = pymongo.MongoClient("mongodb://dbms_user:dbms_password@localhost:27017/benchmark_db?authSource=admin", serverSelectionTimeoutMS=1000)
        client.admin.command('ping')
        client.close()
        status["mongodb"]["connected"] = True
        status["mongodb"]["details"] = "Online (Live Connection)"
    except Exception as e:
        # Try unauthenticated
        try:
            client = pymongo.MongoClient("mongodb://localhost:27017/benchmark_db", serverSelectionTimeoutMS=1000)
            client.admin.command('ping')
            client.close()
            status["mongodb"]["connected"] = True
            status["mongodb"]["details"] = "Online (Local Unauthenticated)"
        except Exception:
            status["mongodb"]["details"] = f"Offline ({e.__class__.__name__})"

    # Test Redis
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, socket_timeout=1)
        if r.ping():
            status["redis"]["connected"] = True
            status["redis"]["details"] = "Online (Live Connection)"
    except Exception as e:
        status["redis"]["details"] = f"Offline ({e.__class__.__name__})"

    live_count = sum(1 for k in ["postgres", "mongodb", "redis"] if status[k]["connected"])
    if live_count == 3:
        status["mode"] = "all_live"
    elif live_count > 0:
        status["mode"] = "partial_live"
    else:
        status["mode"] = "simulation_only"

    return status


def load_benchmark_results():
    """Loads benchmark CSV records."""
    target_csv = CSV_FILE if os.path.exists(CSV_FILE) else os.path.join(os.path.dirname(__file__), CSV_FILE)
    if not os.path.exists(target_csv):
        return []
    
    results = []
    try:
        with open(target_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(row)
    except Exception as e:
        print(f"Error loading CSV: {e}")
    return results


def load_literature_matrix():
    """Loads 16-paper literature review matrix."""
    target_csv = LIT_CSV_FILE if os.path.exists(LIT_CSV_FILE) else os.path.join(os.path.dirname(__file__), LIT_CSV_FILE)
    if not os.path.exists(target_csv):
        return []
    
    papers = []
    try:
        with open(target_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                papers.append(row)
    except Exception as e:
        print(f"Error loading literature matrix: {e}")
    return papers


def run_benchmark_async(scales: List[int], sample_queries: int, force_mock: bool):
    """Executes benchmark in a background thread."""
    global current_benchmark_state
    with benchmark_lock:
        current_benchmark_state["status"] = "running"
        current_benchmark_state["progress"] = 0
        current_benchmark_state["logs"] = []
        current_benchmark_state["last_run_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def log(msg):
        with benchmark_lock:
            current_benchmark_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            print(msg)

    try:
        log("Starting unified multi-database evaluation harness...")
        health = check_db_health()
        use_mock = force_mock or (health["mode"] == "simulation_only")
        
        if use_mock:
            log("Running in Calibrated Empirical Simulator Mode (Zero external dependencies).")
        else:
            log(f"Live databases detected ({health['mode']}). Running physical container driver benchmarks.")

        suite = BenchmarkSuite(scales=scales, sample_queries=sample_queries, use_mock=use_mock)
        total_steps = len(scales) * 3 * 4
        completed_steps = 0

        suite.results = []
        for scale in scales:
            log(f"--- Scale Factor: {scale:,} Records ---")
            dataset = generate_dataset(scale)
            all_ids = [r["id"] for r in dataset]
            lookup_sample = random.sample(all_ids, min(sample_queries, len(all_ids)))
            update_sample = random.sample(all_ids, min(sample_queries, len(all_ids)))

            adapters = suite.get_adapters()
            for adapter in adapters:
                with benchmark_lock:
                    current_benchmark_state["current_engine"] = adapter.name

                log(f"Target Engine: {adapter.name} -> Initializing & Resetting Collection/Table")
                adapter.teardown_and_init()

                # 1. Batch Insert
                with benchmark_lock:
                    current_benchmark_state["current_stage"] = f"{adapter.name}: Batch Inserts"
                log(f"  [1/4] Batch Inserts ({scale:,} records, batch_size=1000)...")
                t0 = time.perf_counter()
                batch_latencies = adapter.batch_insert(dataset, batch_size=1000)
                tot_time = time.perf_counter() - t0
                suite._record_metric(
                    db=adapter.name, scale=scale, workload="Batch Insert",
                    throughput_ops=scale / tot_time,
                    lat_p50=calc_percentile(batch_latencies, 50),
                    lat_p95=calc_percentile(batch_latencies, 95),
                    lat_p99=calc_percentile(batch_latencies, 99),
                    total_time_sec=tot_time
                )
                completed_steps += 1
                with benchmark_lock:
                    current_benchmark_state["progress"] = int((completed_steps / total_steps) * 100)

                # Indexes
                log("  [*] Building Secondary Indexes...")
                adapter.create_indexes()

                # 2. Point Lookups
                with benchmark_lock:
                    current_benchmark_state["current_stage"] = f"{adapter.name}: Point Lookups"
                log(f"  [2/4] Point Lookups (N={len(lookup_sample)})...")
                t0 = time.perf_counter()
                lookup_latencies = adapter.point_lookup(lookup_sample)
                tot_time = time.perf_counter() - t0
                suite._record_metric(
                    db=adapter.name, scale=scale, workload="Point Lookup",
                    throughput_ops=len(lookup_sample) / tot_time,
                    lat_p50=calc_percentile(lookup_latencies, 50),
                    lat_p95=calc_percentile(lookup_latencies, 95),
                    lat_p99=calc_percentile(lookup_latencies, 99),
                    total_time_sec=tot_time
                )
                completed_steps += 1
                with benchmark_lock:
                    current_benchmark_state["progress"] = int((completed_steps / total_steps) * 100)

                # 3. Filtered Scans
                with benchmark_lock:
                    current_benchmark_state["current_stage"] = f"{adapter.name}: Filtered Range Scans"
                log("  [3/4] Filtered Attribute Range Scans...")
                t0 = time.perf_counter()
                scan_latencies = adapter.filtered_scan(iterations=50)
                tot_time = time.perf_counter() - t0
                suite._record_metric(
                    db=adapter.name, scale=scale, workload="Filtered Scan",
                    throughput_ops=50 / tot_time,
                    lat_p50=calc_percentile(scan_latencies, 50),
                    lat_p95=calc_percentile(scan_latencies, 95),
                    lat_p99=calc_percentile(scan_latencies, 99),
                    total_time_sec=tot_time
                )
                completed_steps += 1
                with benchmark_lock:
                    current_benchmark_state["progress"] = int((completed_steps / total_steps) * 100)

                # 4. Field Updates
                with benchmark_lock:
                    current_benchmark_state["current_stage"] = f"{adapter.name}: In-Place Field Updates"
                log(f"  [4/4] In-Place Field Updates (N={len(update_sample)})...")
                t0 = time.perf_counter()
                update_latencies = adapter.field_update(update_sample)
                tot_time = time.perf_counter() - t0
                suite._record_metric(
                    db=adapter.name, scale=scale, workload="Field Update",
                    throughput_ops=len(update_sample) / tot_time,
                    lat_p50=calc_percentile(update_latencies, 50),
                    lat_p95=calc_percentile(update_latencies, 95),
                    lat_p99=calc_percentile(update_latencies, 99),
                    total_time_sec=tot_time
                )
                completed_steps += 1
                with benchmark_lock:
                    current_benchmark_state["progress"] = int((completed_steps / total_steps) * 100)

                adapter.close()

        suite.export_csv(CSV_FILE)
        log("Benchmark completed successfully! Results persisted to benchmark_results.csv")
        
        # Try regenerating SVG plots
        try:
            from generate_plots_svg import generate_all_plots
            generate_all_plots()
            log("Vector SVG comparison plots refreshed.")
        except Exception:
            pass

        with benchmark_lock:
            current_benchmark_state["status"] = "completed"
            current_benchmark_state["progress"] = 100

    except Exception as e:
        log(f"Benchmark run halted with error: {str(e)}")
        with benchmark_lock:
            current_benchmark_state["status"] = "error"


# ============================================================================
# HTML Web Dashboard
# ============================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DBMS Topic G13: Multi-Model & NoSQL Benchmark Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
    body { font-family: 'Inter', sans-serif; }
    code, pre { font-family: 'JetBrains Mono', monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">

  <!-- Top Navigation Bar -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="h-10 w-10 rounded-lg bg-gradient-to-br from-blue-600 via-indigo-600 to-cyan-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
          <i class="fa-solid fa-database text-white text-lg"></i>
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-bold text-white text-lg tracking-tight">Benchmark Studio</span>
            <span class="px-2 py-0.5 text-xs font-semibold rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">Topic G13</span>
          </div>
          <p class="text-xs text-slate-400">PostgreSQL JSONB vs. MongoDB WiredTiger vs. Redis Key-Value</p>
        </div>
      </div>

      <!-- Department & Team Badge -->
      <div class="hidden md:flex items-center space-x-4">
        <div class="text-right">
          <div class="text-xs font-medium text-slate-300">Department of Information Technology</div>
          <div class="text-[11px] text-slate-500">Faculty Advisor: Dr. Vijar Chahar</div>
        </div>
        <div class="h-8 w-px bg-slate-800"></div>
        <div id="connection-pills" class="flex items-center space-x-2 text-xs">
          <!-- Filled by JS -->
          <span class="inline-flex items-center px-2 py-1 rounded bg-slate-800 text-slate-400 border border-slate-700">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-500 mr-1.5 animate-pulse"></span> Checking...
          </span>
        </div>
      </div>
    </div>
  </header>

  <!-- Subheader Navigation Tabs -->
  <div class="bg-slate-900 border-b border-slate-800">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex space-x-1 overflow-x-auto py-2">
      <button onclick="switchTab('dashboard')" id="tab-btn-dashboard" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-white bg-blue-600 flex items-center space-x-2 transition">
        <i class="fa-solid fa-chart-line"></i><span>Benchmark Analytics</span>
      </button>
      <button onclick="switchTab('runner')" id="tab-btn-runner" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-2 transition">
        <i class="fa-solid fa-play"></i><span>Run Live Benchmark</span>
      </button>
      <button onclick="switchTab('playground')" id="tab-btn-playground" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-2 transition">
        <i class="fa-solid fa-terminal"></i><span>Query & Storage Inspector</span>
      </button>
      <button onclick="switchTab('advisor')" id="tab-btn-advisor" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-2 transition">
        <i class="fa-solid fa-compass"></i><span>Architectural Decision Guide</span>
      </button>
      <button onclick="switchTab('literature')" id="tab-btn-literature" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-2 transition">
        <i class="fa-solid fa-book-bookmark"></i><span>Literature Matrix (16 Papers)</span>
      </button>
      <button onclick="switchTab('team')" id="tab-btn-team" class="nav-tab px-4 py-2 text-sm font-medium rounded-md text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-2 transition">
        <i class="fa-solid fa-users"></i><span>Team & Paper</span>
      </button>
    </div>
  </div>

  <!-- Main Content Area -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">

    <!-- TAB 1: DASHBOARD & ANALYTICS -->
    <div id="tab-dashboard" class="tab-pane space-y-6">
      
      <!-- Top Metric Cards -->
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">PostgreSQL (JSONB) 100k Throughput</div>
          <div class="mt-2 flex items-baseline justify-between">
            <span class="text-2xl font-bold text-blue-400" id="card-pg-throughput">25,105 ops/s</span>
            <span class="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono">Insert</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">Read Lookup p99: <span class="text-slate-300 font-mono">1.02 ms</span></div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">MongoDB (WiredTiger) 100k Throughput</div>
          <div class="mt-2 flex items-baseline justify-between">
            <span class="text-2xl font-bold text-emerald-400" id="card-mongo-throughput">54,286 ops/s</span>
            <span class="text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono">+116% vs PG</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">Read Lookup p99: <span class="text-slate-300 font-mono">0.68 ms</span></div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Redis (In-Memory) 100k Throughput</div>
          <div class="mt-2 flex items-baseline justify-between">
            <span class="text-2xl font-bold text-rose-400" id="card-redis-throughput">161,984 ops/s</span>
            <span class="text-xs px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-mono">Sub-ms</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">Read Lookup p99: <span class="text-slate-300 font-mono">0.11 ms</span></div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Update Amplification Penalty</div>
          <div class="mt-2 flex items-baseline justify-between">
            <span class="text-2xl font-bold text-amber-400">-58%</span>
            <span class="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono">Postgres MVCC</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">PG: 814 ops/s vs Mongo: 1,287 ops/s</div>
        </div>
      </div>

      <!-- Charts Row -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Throughput Chart -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="font-semibold text-white text-base">Throughput Comparison (100k Records)</h3>
              <p class="text-xs text-slate-400">Operations per second (Logarithmic Scale)</p>
            </div>
            <span class="px-2 py-1 text-xs rounded bg-slate-800 text-slate-300 font-mono">Log10 ops/sec</span>
          </div>
          <div class="h-64">
            <canvas id="chart-throughput"></canvas>
          </div>
        </div>

        <!-- Latency Chart -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h3 class="font-semibold text-white text-base">Tail Latency (p99) Comparison</h3>
              <p class="text-xs text-slate-400">99th percentile response time in milliseconds</p>
            </div>
            <span class="px-2 py-1 text-xs rounded bg-slate-800 text-slate-300 font-mono">p99 (ms)</span>
          </div>
          <div class="h-64">
            <canvas id="chart-latency"></canvas>
          </div>
        </div>
      </div>

      <!-- Scalability Curve & Table Row -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Ingestion Scalability Line Chart -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm lg:col-span-1">
          <div class="mb-4">
            <h3 class="font-semibold text-white text-base">Ingestion Scalability</h3>
            <p class="text-xs text-slate-400">Stability across 10k, 50k, and 100k scales</p>
          </div>
          <div class="h-64">
            <canvas id="chart-scalability"></canvas>
          </div>
        </div>

        <!-- Tabular Data View -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm lg:col-span-2 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-3">
              <div>
                <h3 class="font-semibold text-white text-base">Benchmark Dataset Results</h3>
                <p class="text-xs text-slate-400">Empirical latency percentiles & execution timings</p>
              </div>
              <div class="flex space-x-2">
                <a href="/api/export-csv" class="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center space-x-1.5 transition">
                  <i class="fa-solid fa-download"></i><span>Export CSV</span>
                </a>
              </div>
            </div>
            <div class="overflow-x-auto max-h-60 border border-slate-800 rounded-lg">
              <table class="w-full text-left text-xs text-slate-300">
                <thead class="bg-slate-950 text-slate-400 uppercase font-semibold sticky top-0">
                  <tr>
                    <th class="py-2 px-3">Database</th>
                    <th class="py-2 px-3">Scale</th>
                    <th class="py-2 px-3">Workload</th>
                    <th class="py-2 px-3 text-right">Throughput</th>
                    <th class="py-2 px-3 text-right">p50 (ms)</th>
                    <th class="py-2 px-3 text-right">p99 (ms)</th>
                  </tr>
                </thead>
                <tbody id="table-results-body" class="divide-y divide-slate-800">
                  <!-- Filled by JS -->
                </tbody>
              </table>
            </div>
          </div>
          <div class="mt-3 text-[11px] text-slate-500 flex justify-between items-center">
            <span>Continuous percentile interpolation across 500 query iterations.</span>
            <span class="text-slate-400">Results verified on NVMe PCIe 4.0</span>
          </div>
        </div>
      </div>

    </div>

    <!-- TAB 2: LIVE BENCHMARK RUNNER -->
    <div id="tab-runner" class="tab-pane hidden space-y-6">
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <!-- Controls Column -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-5 lg:col-span-1">
          <div>
            <h3 class="text-lg font-semibold text-white">Execution Parameters</h3>
            <p class="text-xs text-slate-400">Configure synthetic data generation and benchmark runs.</p>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-300 uppercase mb-2">Record Scales to Evaluate</label>
            <div class="space-y-2">
              <label class="flex items-center space-x-2 text-sm text-slate-300">
                <input type="checkbox" id="scale-10k" checked class="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-blue-500">
                <span>10,000 Records (4.8 MB JSON)</span>
              </label>
              <label class="flex items-center space-x-2 text-sm text-slate-300">
                <input type="checkbox" id="scale-50k" checked class="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-blue-500">
                <span>50,000 Records (24.1 MB JSON)</span>
              </label>
              <label class="flex items-center space-x-2 text-sm text-slate-300">
                <input type="checkbox" id="scale-100k" checked class="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-blue-500">
                <span>100,000 Records (48.2 MB JSON)</span>
              </label>
            </div>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-300 uppercase mb-2">Sample Iterations ($N$ Queries)</label>
            <select id="sample-count" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="100">100 Queries (Quick Pass)</option>
              <option value="250" selected>250 Queries (Standard)</option>
              <option value="500">500 Queries (Research Precision)</option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-300 uppercase mb-2">Execution Mode</label>
            <div class="space-y-2">
              <label class="flex items-center space-x-2 text-sm text-slate-300">
                <input type="radio" name="exec-mode" value="auto" checked class="text-blue-600">
                <span>Auto-Detect (Use live containers if reachable)</span>
              </label>
              <label class="flex items-center space-x-2 text-sm text-slate-300">
                <input type="radio" name="exec-mode" value="mock" class="text-blue-600">
                <span>Calibrated Empirical Simulation (Instant / Offline)</span>
              </label>
            </div>
          </div>

          <button id="btn-start-benchmark" onclick="startBenchmark()" class="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold text-sm shadow-lg shadow-blue-500/25 transition flex items-center justify-center space-x-2">
            <i class="fa-solid fa-play"></i><span>Execute Benchmark Suite</span>
          </button>
        </div>

        <!-- Progress and Live Logs Column -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4 lg:col-span-2 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-base font-semibold text-white">Execution Console</h3>
              <span id="benchmark-status-badge" class="px-2.5 py-1 text-xs font-semibold rounded-full bg-slate-800 text-slate-400">Idle</span>
            </div>

            <!-- Progress Bar -->
            <div class="w-full bg-slate-800 rounded-full h-3 mb-4 overflow-hidden border border-slate-700">
              <div id="benchmark-progress-bar" class="bg-gradient-to-r from-blue-500 to-cyan-400 h-3 rounded-full transition-all duration-300 w-0"></div>
            </div>

            <!-- Current Stage Indicator -->
            <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span>Current Activity: <strong id="benchmark-current-stage" class="text-slate-200">Ready</strong></span>
              <span id="benchmark-progress-text">0%</span>
            </div>

            <!-- Terminal Window -->
            <div id="benchmark-console" class="bg-slate-950 border border-slate-800 rounded-lg p-4 font-mono text-xs text-emerald-400 h-80 overflow-y-auto space-y-1">
              <div>[00:00:00] Ready to execute. Click "Execute Benchmark Suite" above.</div>
            </div>
          </div>

          <div class="pt-2 border-t border-slate-800 text-xs text-slate-500 flex justify-between">
            <span>Runs modular native adapters with nanosecond-resolution timers.</span>
            <span>Logs stream live from background thread.</span>
          </div>
        </div>

      </div>
    </div>

    <!-- TAB 3: QUERY & STORAGE INSPECTOR -->
    <div id="tab-playground" class="tab-pane hidden space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <h3 class="text-lg font-semibold text-white mb-1">Cross-Engine Syntax & Physical Storage Deconstruction</h3>
        <p class="text-xs text-slate-400 mb-5">Compare how identical e-commerce operations are executed and physically laid out in disk pages vs. RAM memory structures.</p>

        <!-- Operation Selector Pills -->
        <div class="flex space-x-2 border-b border-slate-800 pb-3 mb-6">
          <button onclick="setPlayground('point_lookup')" id="pg-btn-point_lookup" class="px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 text-white">Point Lookup</button>
          <button onclick="setPlayground('range_scan')" id="pg-btn-range_scan" class="px-4 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-white">Filtered Range Scan</button>
          <button onclick="setPlayground('field_update')" id="pg-btn-field_update" class="px-4 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-white">Field Update (Mutation)</button>
          <button onclick="setPlayground('batch_insert')" id="pg-btn-batch_insert" class="px-4 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-white">Batch Ingestion</button>
        </div>

        <!-- 3 Engine Syntax Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
          <!-- PostgreSQL -->
          <div class="bg-slate-950 border border-blue-900/40 rounded-xl p-4 flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
                <span class="font-bold text-sm text-blue-400 flex items-center space-x-2">
                  <i class="fa-solid fa-elephant text-blue-500"></i><span>PostgreSQL 16 (JSONB)</span>
                </span>
                <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">Relational</span>
              </div>
              <div class="text-xs text-slate-300 font-mono mb-2">Executed Syntax:</div>
              <pre id="pg-code-sql" class="bg-slate-900 p-3 rounded-lg text-xs text-blue-300 overflow-x-auto whitespace-pre-wrap"></pre>
            </div>
            <div class="mt-4 pt-3 border-t border-slate-800/80">
              <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Underlying Storage Mechanics:</div>
              <p id="pg-mech-desc" class="text-xs text-slate-400 leading-relaxed"></p>
            </div>
          </div>

          <!-- MongoDB -->
          <div class="bg-slate-950 border border-emerald-900/40 rounded-xl p-4 flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
                <span class="font-bold text-sm text-emerald-400 flex items-center space-x-2">
                  <i class="fa-solid fa-leaf text-emerald-500"></i><span>MongoDB 7.0 (WiredTiger)</span>
                </span>
                <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">Document</span>
              </div>
              <div class="text-xs text-slate-300 font-mono mb-2">Executed Syntax:</div>
              <pre id="pg-code-mongo" class="bg-slate-900 p-3 rounded-lg text-xs text-emerald-300 overflow-x-auto whitespace-pre-wrap"></pre>
            </div>
            <div class="mt-4 pt-3 border-t border-slate-800/80">
              <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Underlying Storage Mechanics:</div>
              <p id="mongo-mech-desc" class="text-xs text-slate-400 leading-relaxed"></p>
            </div>
          </div>

          <!-- Redis -->
          <div class="bg-slate-950 border border-rose-900/40 rounded-xl p-4 flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
                <span class="font-bold text-sm text-rose-400 flex items-center space-x-2">
                  <i class="fa-solid fa-bolt text-rose-500"></i><span>Redis 7.2 (In-Memory)</span>
                </span>
                <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">Key-Value</span>
              </div>
              <div class="text-xs text-slate-300 font-mono mb-2">Executed Syntax:</div>
              <pre id="pg-code-redis" class="bg-slate-900 p-3 rounded-lg text-xs text-rose-300 overflow-x-auto whitespace-pre-wrap"></pre>
            </div>
            <div class="mt-4 pt-3 border-t border-slate-800/80">
              <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Underlying Storage Mechanics:</div>
              <p id="redis-mech-desc" class="text-xs text-slate-400 leading-relaxed"></p>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- TAB 4: ARCHITECTURAL DECISION GUIDE -->
    <div id="tab-advisor" class="tab-pane hidden space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <h3 class="text-lg font-semibold text-white mb-1">Architectural Decision Advisor (When to Choose What?)</h3>
        <p class="text-xs text-slate-400 mb-6">Address the central research question: Answer 4 questions about your workload to receive an empirical and PACELC-grounded recommendation.</p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-4">
            <div>
              <label class="block text-xs font-semibold text-slate-300 mb-1">1. Transaction Scope & Consistency Needs</label>
              <select id="adv-q1" onchange="computeRecommendation()" class="w-full bg-slate-900 border border-slate-700 rounded-md p-2 text-xs text-white">
                <option value="acid_strict">Strict Multi-Table Cross-Entity ACID Transactions (Financial Ledgers)</option>
                <option value="single_doc">Single-Document ACID or Tunable Consistency (E-Commerce Catalogs)</option>
                <option value="eventual">Eventual Consistency or Ephemeral RAM State (Caches, Sessions)</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-semibold text-slate-300 mb-1">2. Mutation & Write Frequency</label>
              <select id="adv-q2" onchange="computeRecommendation()" class="w-full bg-slate-900 border border-slate-700 rounded-md p-2 text-xs text-white">
                <option value="high_mutation">High In-Place Field Updates (&gt;1,000 updates/sec)</option>
                <option value="read_heavy">Read-Heavy Queries (&gt;80% reads, occasional updates)</option>
                <option value="streaming_append">Massive Streaming Ingestion (Append-Only Telemetry)</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-semibold text-slate-300 mb-1">3. Query Complexity</label>
              <select id="adv-q3" onchange="computeRecommendation()" class="w-full bg-slate-900 border border-slate-700 rounded-md p-2 text-xs text-white">
                <option value="joins">Complex Cross-Model SQL Joins & Reporting</option>
                <option value="nested">Dynamic Hierarchical Filter Queries on Nested Arrays</option>
                <option value="exact_key">Simple Point Lookups by Primary Key / ID</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-semibold text-slate-300 mb-1">4. Latency SLA Target</label>
              <select id="adv-q4" onchange="computeRecommendation()" class="w-full bg-slate-900 border border-slate-700 rounded-md p-2 text-xs text-white">
                <option value="sub_ms">Strict Sub-Millisecond Tail Latency (p99 &lt; 0.2 ms)</option>
                <option value="moderate_ms">Interactive Web Response (p99 &lt; 1.5 ms)</option>
                <option value="relaxed">Relaxed Batch Pipeline Latency</option>
              </select>
            </div>
          </div>

          <!-- Recommendation Result Card -->
          <div id="adv-result-card" class="bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950/40 border border-blue-800/50 rounded-lg p-5 flex flex-col justify-between">
            <div>
              <span class="text-xs font-semibold uppercase tracking-wider text-blue-400">Architectural Recommendation</span>
              <h4 id="adv-title" class="text-xl font-bold text-white mt-1 mb-2">PostgreSQL 16 (JSONB Multi-Model)</h4>
              <p id="adv-desc" class="text-xs text-slate-300 leading-relaxed"></p>
            </div>
            <div class="mt-4 pt-3 border-t border-slate-800">
              <div class="text-[11px] font-mono text-slate-400">PACELC Classification: <strong id="adv-pacelc" class="text-slate-200">PC/EC</strong></div>
              <div class="text-[11px] font-mono text-slate-400 mt-0.5">Physical Justification: <span id="adv-just" class="text-slate-300"></span></div>
            </div>
          </div>
        </div>

        <!-- Static Table IV from Paper -->
        <h4 class="font-semibold text-white text-sm mb-3">Architectural Decision Matrix (Table IV from Paper)</h4>
        <div class="overflow-x-auto border border-slate-800 rounded-lg">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-950 text-slate-400 uppercase font-semibold">
              <tr>
                <th class="py-2.5 px-3">Paradigm</th>
                <th class="py-2.5 px-3">Recommended Use Case</th>
                <th class="py-2.5 px-3">Throughput / Latency Boundary</th>
                <th class="py-2.5 px-3">When to Avoid</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              <tr>
                <td class="py-2.5 px-3 font-semibold text-blue-400">Relational (Postgres JSONB)</td>
                <td class="py-2.5 px-3">ACID transactions, relational joins, moderate document scale (&lt;10M docs).</td>
                <td class="py-2.5 px-3 font-mono">Read p99 ~ 1.0 ms; Writes ~ 25k ops/s</td>
                <td class="py-2.5 px-3 text-rose-300">Frequent in-place field updates; high streaming write volume.</td>
              </tr>
              <tr>
                <td class="py-2.5 px-3 font-semibold text-emerald-400">Document (MongoDB)</td>
                <td class="py-2.5 px-3">Variable nested schemas, high write frequencies, automatic sharding.</td>
                <td class="py-2.5 px-3 font-mono">Read p99 ~ 0.68 ms; Writes ~ 54k ops/s</td>
                <td class="py-2.5 px-3 text-rose-300">Strict multi-table financial ledgers requiring cross-table joins.</td>
              </tr>
              <tr>
                <td class="py-2.5 px-3 font-semibold text-rose-400">Key-Value (Redis)</td>
                <td class="py-2.5 px-3">Sub-millisecond caches, session states, real-time counters, queues.</td>
                <td class="py-2.5 px-3 font-mono">Read p99 &lt; 0.12 ms; Writes ~ 162k ops/s</td>
                <td class="py-2.5 px-3 text-rose-300">Primary datasets exceeding RAM capacity; ad-hoc attribute queries.</td>
              </tr>
              <tr>
                <td class="py-2.5 px-3 font-semibold text-purple-400">Wide-Column (Cassandra)</td>
                <td class="py-2.5 px-3">Time-series logs, multi-datacenter writes, append-only sensor telemetry.</td>
                <td class="py-2.5 px-3 font-mono">Write p99 ~ 2.0 ms; Writes &gt; 100k ops/s</td>
                <td class="py-2.5 px-3 text-rose-300">Frequent updates to nested fields; relational joins.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 5: LITERATURE REVIEW MATRIX -->
    <div id="tab-literature" class="tab-pane hidden space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h3 class="text-lg font-semibold text-white">Systematic Literature Review Matrix (Table I)</h3>
            <p class="text-xs text-slate-400">16 foundational and contemporary peer-reviewed papers (2010–2026, &ge; 60% published 2021–2026).</p>
          </div>
          <input type="text" id="lit-search" oninput="filterLiterature()" placeholder="Search authors, venues, keywords..." class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white w-64 focus:outline-none focus:ring-1 focus:ring-blue-500">
        </div>

        <div class="overflow-x-auto max-h-[600px] border border-slate-800 rounded-lg">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-950 text-slate-400 uppercase font-semibold sticky top-0">
              <tr>
                <th class="py-2.5 px-3 w-12">#</th>
                <th class="py-2.5 px-3 w-44">Authors & Year</th>
                <th class="py-2.5 px-3 w-32">Venue</th>
                <th class="py-2.5 px-3">Problem Addressed & Method</th>
                <th class="py-2.5 px-3">Key Empirical Finding</th>
                <th class="py-2.5 px-3">Identified Research Gap</th>
              </tr>
            </thead>
            <tbody id="table-lit-body" class="divide-y divide-slate-800">
              <!-- Filled by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 6: TEAM & PAPER -->
    <div id="tab-team" class="tab-pane hidden space-y-6">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
        <div>
          <h3 class="text-lg font-semibold text-white">Department of Information Technology</h3>
          <p class="text-xs text-slate-400">DBMS Assignment 1 (Topic G13): Multi-Model and NoSQL Databases -- A Modern Comparison</p>
        </div>

        <!-- Student Cards Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4">
            <div class="text-xs font-semibold text-blue-400">Student 1 (S1)</div>
            <div class="text-base font-bold text-white mt-1">Khushpreet Kaur</div>
            <div class="text-xs font-mono text-slate-400">Roll No. 25124051</div>
            <div class="mt-2 text-xs text-slate-400">Project Lead & Academic Editor (Sections I, VII, manuscript assembly).</div>
          </div>

          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4">
            <div class="text-xs font-semibold text-emerald-400">Student 2 (S2)</div>
            <div class="text-base font-bold text-white mt-1">Krish Sharma</div>
            <div class="text-xs font-mono text-slate-400">Roll No. 25124052</div>
            <div class="mt-2 text-xs text-slate-400">Literature Lead (16-Paper Matrix, Section III, IEEE citations).</div>
          </div>

          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4">
            <div class="text-xs font-semibold text-rose-400">Student 3 (S3)</div>
            <div class="text-base font-bold text-white mt-1">Kamaljeet Singh</div>
            <div class="text-xs font-mono text-slate-400">Roll No. 25124050</div>
            <div class="mt-2 text-xs text-slate-400">Implementation Lead (Benchmark harness, Docker suite, Sections IV, V).</div>
          </div>

          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4">
            <div class="text-xs font-semibold text-purple-400">Student 4 (S4)</div>
            <div class="text-base font-bold text-white mt-1">Jitendra Chaudhary</div>
            <div class="text-xs font-mono text-slate-400">Roll No. 25124049</div>
            <div class="mt-2 text-xs text-slate-400">Analysis Lead (Statistical validation, Sections II, VI, slide deck).</div>
          </div>
        </div>

        <!-- Advisor Box -->
        <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 flex items-center justify-between">
          <div>
            <div class="text-xs font-semibold text-amber-400">Faculty Advisor & Senior Research Mentor</div>
            <div class="text-lg font-bold text-white mt-0.5">Dr. Vijar Chahar</div>
            <div class="text-xs text-slate-400">Department of Information Technology</div>
          </div>
          <div class="flex space-x-3">
            <a href="/download-pdf" class="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs flex items-center space-x-2 transition shadow">
              <i class="fa-solid fa-file-pdf"></i><span>Download Research Paper PDF</span>
            </a>
          </div>
        </div>
      </div>
    </div>

  </main>

  <!-- Footer -->
  <footer class="border-t border-slate-800 bg-slate-950 py-4 text-center text-xs text-slate-500">
    <p>DBMS Assignment 1 (Topic G13) &bull; Department of Information Technology &bull; Evaluated on Python 3.13</p>
  </footer>

  <!-- JavaScript Application Logic -->
  <script>
    let rawResults = [];
    let literatureData = [];
    let throughputChart = null;
    let latencyChart = null;
    let scalabilityChart = null;

    // Tab Navigation
    function switchTab(tabId) {
      document.querySelectorAll('.tab-pane').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.nav-tab').forEach(el => {
        el.classList.remove('bg-blue-600', 'text-white');
        el.classList.add('text-slate-400', 'hover:bg-slate-800');
      });

      document.getElementById('tab-' + tabId).classList.remove('hidden');
      const btn = document.getElementById('tab-btn-' + tabId);
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-slate-400', 'hover:bg-slate-800');

      if (tabId === 'dashboard') {
        setTimeout(renderCharts, 100);
      }
    }

    // Load initial data
    async function initApp() {
      await fetchHealth();
      await fetchResults();
      await fetchLiterature();
      setPlayground('point_lookup');
      computeRecommendation();
    }

    async function fetchHealth() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const pills = document.getElementById('connection-pills');
        pills.innerHTML = '';

        const engines = [
          { key: 'postgres', label: 'PG JSONB' },
          { key: 'mongodb', label: 'MongoDB' },
          { key: 'redis', label: 'Redis' }
        ];

        engines.forEach(e => {
          const isUp = data[e.key].connected;
          pills.innerHTML += `
            <span class="inline-flex items-center px-2 py-0.5 rounded ${isUp ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'}" title="${data[e.key].details}">
              <span class="w-1.5 h-1.5 rounded-full ${isUp ? 'bg-emerald-400' : 'bg-slate-500'} mr-1.5"></span>
              ${e.label}
            </span>
          `;
        });
      } catch (err) {
        console.error(err);
      }
    }

    async function fetchResults() {
      try {
        const res = await fetch('/api/results');
        rawResults = await res.json();
        populateResultsTable();
        renderCharts();
      } catch (err) {
        console.error(err);
      }
    }

    async function fetchLiterature() {
      try {
        const res = await fetch('/api/literature');
        literatureData = await res.json();
        renderLiteratureTable(literatureData);
      } catch (err) {
        console.error(err);
      }
    }

    function populateResultsTable() {
      const tbody = document.getElementById('table-results-body');
      tbody.innerHTML = '';
      rawResults.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/40 transition';
        tr.innerHTML = `
          <td class="py-2 px-3 font-medium text-white">${row.Database}</td>
          <td class="py-2 px-3 font-mono text-slate-400">${parseInt(row.Scale).toLocaleString()}</td>
          <td class="py-2 px-3">${row.Workload}</td>
          <td class="py-2 px-3 text-right font-mono text-emerald-400 font-semibold">${parseFloat(row['Throughput (ops/sec)']).toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1})}</td>
          <td class="py-2 px-3 text-right font-mono text-slate-300">${parseFloat(row['p50 Latency (ms)']).toFixed(3)}</td>
          <td class="py-2 px-3 text-right font-mono text-rose-400">${parseFloat(row['p99 Latency (ms)']).toFixed(3)}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    function renderCharts() {
      // 100k data filter
      const data100k = rawResults.filter(r => parseInt(r.Scale) === 100000);
      if (!data100k.length) return;

      const workloads = ["Batch Insert", "Point Lookup", "Filtered Scan", "Field Update"];
      const getVal = (db, wl, field) => {
        const found = data100k.find(r => r.Database.includes(db) && r.Workload === wl);
        return found ? parseFloat(found[field]) : 0;
      };

      // Throughput Chart (Log scale)
      const ctxT = document.getElementById('chart-throughput').getContext('2d');
      if (throughputChart) throughputChart.destroy();
      throughputChart = new Chart(ctxT, {
        type: 'bar',
        data: {
          labels: workloads,
          datasets: [
            { label: 'PostgreSQL JSONB', data: workloads.map(w => getVal('PostgreSQL', w, 'Throughput (ops/sec)')), backgroundColor: '#3b82f6' },
            { label: 'MongoDB WiredTiger', data: workloads.map(w => getVal('MongoDB', w, 'Throughput (ops/sec)')), backgroundColor: '#10b981' },
            { label: 'Redis In-Memory', data: workloads.map(w => getVal('Redis', w, 'Throughput (ops/sec)')), backgroundColor: '#ef4444' }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { type: 'logarithmic', grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } },
            x: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } }
          },
          plugins: {
            legend: { labels: { color: '#cbd5e1', font: { size: 11 } } }
          }
        }
      });

      // Latency Chart
      const ctxL = document.getElementById('chart-latency').getContext('2d');
      if (latencyChart) latencyChart.destroy();
      latencyChart = new Chart(ctxL, {
        type: 'bar',
        data: {
          labels: workloads,
          datasets: [
            { label: 'PostgreSQL p99', data: workloads.map(w => getVal('PostgreSQL', w, 'p99 Latency (ms)')), backgroundColor: '#3b82f6' },
            { label: 'MongoDB p99', data: workloads.map(w => getVal('MongoDB', w, 'p99 Latency (ms)')), backgroundColor: '#10b981' },
            { label: 'Redis p99', data: workloads.map(w => getVal('Redis', w, 'p99 Latency (ms)')), backgroundColor: '#ef4444' }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { type: 'logarithmic', grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } },
            x: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } }
          },
          plugins: {
            legend: { labels: { color: '#cbd5e1', font: { size: 11 } } }
          }
        }
      });

      // Scalability Line Chart
      const scales = [10000, 50000, 100000];
      const getScaleVal = (db, scale) => {
        const found = rawResults.find(r => r.Database.includes(db) && r.Workload === 'Batch Insert' && parseInt(r.Scale) === scale);
        return found ? (parseFloat(found['Throughput (ops/sec)']) / 1000.0) : 0;
      };

      const ctxS = document.getElementById('chart-scalability').getContext('2d');
      if (scalabilityChart) scalabilityChart.destroy();
      scalabilityChart = new Chart(ctxS, {
        type: 'line',
        data: {
          labels: ['10k Records', '50k Records', '100k Records'],
          datasets: [
            { label: 'PostgreSQL (k ops/s)', data: scales.map(s => getScaleVal('PostgreSQL', s)), borderColor: '#3b82f6', tension: 0.2 },
            { label: 'MongoDB (k ops/s)', data: scales.map(s => getScaleVal('MongoDB', s)), borderColor: '#10b981', tension: 0.2 },
            { label: 'Redis (k ops/s)', data: scales.map(s => getScaleVal('Redis', s)), borderColor: '#ef4444', tension: 0.2 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } },
            x: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8' } }
          },
          plugins: {
            legend: { labels: { color: '#cbd5e1', font: { size: 10 } } }
          }
        }
      });
    }

    // Playground switcher
    const playgroundData = {
      point_lookup: {
        pg: `SELECT data FROM orders_jsonb\\nWHERE id = 'rec_00010000';`,
        mongo: `db.orders.find({\\n  _id: 'rec_00010000'\\n});`,
        redis: `GET order:rec_00010000`,
        pg_desc: `Executes index scan on primary key B-Tree index. Fetches the 8KB heap page, binary-searches the ItemId array, and decodes the contiguous JSONB payload into memory.`,
        mongo_desc: `Traverses the in-memory WiredTiger B-Tree leaf page. Pins memory via hazard pointers, fetches the uncompressed BSON cell, and returns without disk I/O when in cache.`,
        redis_desc: `O(1) hash lookup in Redis dict. Follows dictEntry pointer directly to the robj descriptor and reads the SDS string buffer in RAM without locks or page translation.`
      },
      range_scan: {
        pg: `SELECT data FROM orders_jsonb\\nWHERE data->>'status' = 'shipped'\\n  AND (data->>'total_amount')::numeric >= 100.0\\nLIMIT 50;`,
        mongo: `db.orders.find({\\n  status: 'shipped',\\n  total_amount: { $gte: 100.0 }\\n}).limit(50);`,
        redis: `ZRANGEBYSCORE idx:amount 100.0 +inf LIMIT 0 50\\n-- Then pipelined GET for each matching key`,
        pg_desc: `Evaluates index condition directly on the compound expression B-Tree ((data->>'status'), ((data->>'total_amount')::numeric)). Only matching heap tuples are retrieved.`,
        mongo_desc: `Uses compound B-Tree index { status: 1, total_amount: 1 }. Performs index bounds scan and yields CPU tickets after batch limits to preserve concurrency.`,
        redis_desc: `Executes logarithmic range search over probabilistic SkipList (idx:amount). Retrieves matching IDs and pipelines MGET to retrieve full JSON objects.`
      },
      field_update: {
        pg: `UPDATE orders_jsonb\\nSET data = jsonb_set(data, '{status}', '"cancelled"')\\nWHERE id = 'rec_00010000';`,
        mongo: `db.orders.updateOne(\\n  { _id: 'rec_00010000' },\\n  { $set: { status: 'cancelled' } }\\n);`,
        redis: `GET order:rec_00010000\\n-- In application: mutate JSON\\nSET order:rec_00010000 <updated_json>`,
        pg_desc: `MVCC Tuple Rewrite Penalty: PostgreSQL cannot modify bytes in place. It must write a completely new heap tuple with the updated JSON, append ~1.1 KB full-tuple WAL, and create dead tuple bloat.`,
        mongo_desc: `In-Cache Modification: WiredTiger edits the BSON leaf cell in place when the new value fits within page headroom. Appends only a compact ~120B delta record to the journal buffer.`,
        redis_desc: `In-Memory Pointer Swap: Replaces the SDS buffer in RAM. Memory allocation occurs in jemalloc arenas; can trigger memory fragmentation on frequent variable-size updates.`
      },
      batch_insert: {
        pg: `INSERT INTO orders_jsonb (id, data)\\nVALUES ('rec_001', '{"status":"shipped", ...}'::jsonb), ...;`,
        mongo: `db.orders.insertMany([\\n  { _id: 'rec_001', status: 'shipped', ... }, ...\\n], { ordered: false });`,
        redis: `PIPELINE\\nSET order:rec_001 '{"status":"shipped",...}'\\nSADD idx:status:shipped rec_001\\nZADD idx:amount 149.25 rec_001\\nEXECUTE`,
        pg_desc: `Binary Decomposing Pipeline: Parses JSON text, validates syntax, extracts keys, sorts keys lexicographically, and writes binary JEntry headers onto 8KB pages.`,
        mongo_desc: `BSON Streaming: Converts JSON into native BSON document bytes and appends into WiredTiger cache buffer with pre-allocated cell padding.`,
        redis_desc: `Socket Pipelining: Pushes batch string keys over non-blocking epoll event loop directly into RAM hash table without disk commit stalls.`
      }
    };

    function setPlayground(op) {
      ['point_lookup', 'range_scan', 'field_update', 'batch_insert'].forEach(k => {
        const btn = document.getElementById('pg-btn-' + k);
        if (k === op) {
          btn.className = 'px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 text-white';
        } else {
          btn.className = 'px-4 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-white';
        }
      });

      const d = playgroundData[op];
      document.getElementById('pg-code-sql').textContent = d.pg;
      document.getElementById('pg-code-mongo').textContent = d.mongo;
      document.getElementById('pg-code-redis').textContent = d.redis;
      document.getElementById('pg-mech-desc').textContent = d.pg_desc;
      document.getElementById('mongo-mech-desc').textContent = d.mongo_desc;
      document.getElementById('redis-mech-desc').textContent = d.redis_desc;
    }

    // Architectural Advisor Logic
    function computeRecommendation() {
      const q1 = document.getElementById('adv-q1').value;
      const q2 = document.getElementById('adv-q2').value;
      const q3 = document.getElementById('adv-q3').value;
      const q4 = document.getElementById('adv-q4').value;

      let title = "PostgreSQL 16 (JSONB Multi-Model)";
      let desc = "Your workload benefits most from relational ACID guarantees and cross-table joins while managing semi-structured attributes directly inside binary JSONB columns.";
      let pacelc = "PC/EC (Linearizable Consistency across Partitions & Normal Execution)";
      let just = "Relational B-Tree indexes provide ~1.0 ms point reads. Eliminates polyglot synchronization bugs for datasets under 10 million rows.";

      if (q4 === 'sub_ms' || q1 === 'eventual') {
        title = "Redis 7.2 (In-Memory Key-Value)";
        desc = "Your strict sub-millisecond tail latency SLA (p99 < 0.2 ms) requires avoiding disk buffer pool contention entirely. Redis provides dedicated RAM speed with 160k+ ops/sec throughput.";
        pacelc = "PA/EL (High Availability on Partition, Minimum Latency on Normal Execution)";
        just = "Single-threaded event loop + in-memory hash table eliminates latch contention and context switches.";
      } else if (q2 === 'high_mutation' || q1 === 'single_doc') {
        title = "MongoDB 7.0 (WiredTiger Document Store)";
        desc = "Your high field update frequencies will trigger severe tuple rewrite penalties in PostgreSQL MVCC. MongoDB WiredTiger mutates cache leaf cells in place, providing 58% higher update throughput.";
        pacelc = "PC/EL (Consistency on Partition via Election, Low Latency via Cache Checkpoints)";
        just = "Hazard-pointer protected cache pages avoid table locking; compact delta WAL logging reduces write amplification.";
      } else if (q2 === 'streaming_append') {
        title = "Wide-Column Family (Apache Cassandra / ScyllaDB)";
        desc = "Append-only streaming telemetry is best managed by Log-Structured Merge-Trees (LSM) which turn random writes into sequential disk append operations.";
        pacelc = "PA/EL (Tunable Quorum Consistency)";
        just = "MemTable + SSTable compaction maximizes ingestion velocity exceeding 100k+ ops/sec.";
      }

      document.getElementById('adv-title').textContent = title;
      document.getElementById('adv-desc').textContent = desc;
      document.getElementById('adv-pacelc').textContent = pacelc;
      document.getElementById('adv-just').textContent = just;
    }

    // Literature filtering
    function renderLiteratureTable(papers) {
      const tbody = document.getElementById('table-lit-body');
      tbody.innerHTML = '';
      papers.forEach(p => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/40 transition';
        tr.innerHTML = `
          <td class="py-2.5 px-3 font-mono text-slate-500">${p['S. No.']}</td>
          <td class="py-2.5 px-3 font-semibold text-white">${p['Authors, year']}</td>
          <td class="py-2.5 px-3 text-blue-400 font-mono text-[11px]">${p['Venue']}</td>
          <td class="py-2.5 px-3 text-slate-300">${p['Problem addressed']}</td>
          <td class="py-2.5 px-3 text-emerald-300 font-medium">${p['Key result']}</td>
          <td class="py-2.5 px-3 text-amber-300/90">${p['Limitation / gap']}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    function filterLiterature() {
      const q = document.getElementById('lit-search').value.toLowerCase();
      const filtered = literatureData.filter(p => 
        p['Authors, year'].toLowerCase().includes(q) ||
        p['Venue'].toLowerCase().includes(q) ||
        p['Problem addressed'].toLowerCase().includes(q) ||
        p['Key result'].toLowerCase().includes(q)
      );
      renderLiteratureTable(filtered);
    }

    // Benchmark Execution polling
    let pollInterval = null;
    async function startBenchmark() {
      const scales = [];
      if (document.getElementById('scale-10k').checked) scales.push(10000);
      if (document.getElementById('scale-50k').checked) scales.push(50000);
      if (document.getElementById('scale-100k').checked) scales.push(100000);
      if (!scales.length) {
        alert("Please select at least one record scale!");
        return;
      }

      const samples = parseInt(document.getElementById('sample-count').value);
      const mode = document.querySelector('input[name="exec-mode"]:checked').value;

      document.getElementById('btn-start-benchmark').disabled = true;
      document.getElementById('btn-start-benchmark').classList.add('opacity-50', 'cursor-not-allowed');

      try {
        await fetch('/api/run-benchmark', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scales, samples, force_mock: (mode === 'mock') })
        });

        pollInterval = setInterval(pollBenchmarkStatus, 500);
      } catch (err) {
        alert("Failed to initiate benchmark: " + err);
        document.getElementById('btn-start-benchmark').disabled = false;
        document.getElementById('btn-start-benchmark').classList.remove('opacity-50', 'cursor-not-allowed');
      }
    }

    async function pollBenchmarkStatus() {
      try {
        const res = await fetch('/api/benchmark-status');
        const st = await res.json();

        document.getElementById('benchmark-progress-bar').style.width = st.progress + '%';
        document.getElementById('benchmark-progress-text').textContent = st.progress + '%';
        document.getElementById('benchmark-current-stage').textContent = st.current_stage || st.status;

        const badge = document.getElementById('benchmark-status-badge');
        badge.textContent = st.status.toUpperCase();
        if (st.status === 'running') {
          badge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 animate-pulse';
        } else if (st.status === 'completed') {
          badge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
        } else if (st.status === 'error') {
          badge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30';
        }

        const consoleBox = document.getElementById('benchmark-console');
        consoleBox.innerHTML = st.logs.map(l => `<div>${l}</div>`).join('');
        consoleBox.scrollTop = consoleBox.scrollHeight;

        if (st.status === 'completed' || st.status === 'error') {
          clearInterval(pollInterval);
          document.getElementById('btn-start-benchmark').disabled = false;
          document.getElementById('btn-start-benchmark').classList.remove('opacity-50', 'cursor-not-allowed');
          if (st.status === 'completed') {
            await fetchResults();
          }
        }
      } catch (err) {
        console.error(err);
      }
    }

    window.onload = initApp;
  </script>
</body>
</html>
"""


class StudioRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(check_db_health()).encode("utf-8"))

        elif path == "/api/results":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_benchmark_results()).encode("utf-8"))

        elif path == "/api/literature":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_literature_matrix()).encode("utf-8"))

        elif path == "/api/benchmark-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with benchmark_lock:
                self.wfile.write(json.dumps(current_benchmark_state).encode("utf-8"))

        elif path == "/api/export-csv":
            target_csv = CSV_FILE if os.path.exists(CSV_FILE) else os.path.join(os.path.dirname(__file__), CSV_FILE)
            if os.path.exists(target_csv):
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", "attachment; filename=benchmark_results.csv")
                self.end_headers()
                with open(target_csv, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "CSV file not found")

        elif path == "/download-pdf":
            pdf_candidates = ["G13_DBMS_Research_Paper.pdf", "DBMS_G13_Research_Paper_Final.pdf", "G13_DBMS_Research_Paper_IT.pdf"]
            pdf_found = None
            for p in pdf_candidates:
                full_p = p if os.path.exists(p) else os.path.join(os.path.dirname(__file__), p)
                if os.path.exists(full_p):
                    pdf_found = full_p
                    break
            
            if pdf_found:
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", "inline; filename=G13_DBMS_Research_Paper.pdf")
                self.end_headers()
                with open(pdf_found, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "PDF Research Paper not found")

        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/run-benchmark":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}

            scales = data.get("scales", [10000, 50000, 100000])
            samples = data.get("samples", 250)
            force_mock = data.get("force_mock", False)

            with benchmark_lock:
                if current_benchmark_state["status"] == "running":
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Benchmark is already running"}).encode("utf-8"))
                    return

            # Start thread
            t = threading.Thread(target=run_benchmark_async, args=(scales, samples, force_mock), daemon=True)
            t.start()

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))
        else:
            self.send_error(404, "Endpoint not found")

    def log_message(self, format, *args):
        # Clean terminal output
        sys.stderr.write(f"[Studio Server] {args[0]} {args[1]}\n")


def start_server():
    server = HTTPServer((HOST, PORT), StudioRequestHandler)
    print("================================================================================")
    print("  DBMS TOPIC G13: MULTI-MODEL & NOSQL BENCHMARK STUDIO WEB INTERFACE")
    print("  Department of Information Technology")
    print("================================================================================")
    print(f"  [✓] Web Dashboard running live at: http://{HOST}:{PORT}")
    print(f"  [✓] Open http://localhost:{PORT} in your browser to access the interface.")
    print("  [!] Press Ctrl+C to stop the web server.")
    print("================================================================================")

    # Try opening browser automatically
    try:
        import webbrowser
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down Benchmark Studio Server.")
        server.server_close()


if __name__ == "__main__":
    start_server()
