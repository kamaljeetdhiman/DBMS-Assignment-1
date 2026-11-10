# Modern NoSQL vs Multi-Model Relational Database Systems: An Empirical & Theoretical Evaluation (Topic G13)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Docker Compose](https://img.shields.io/badge/docker--compose-v2+-2496ED.svg)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 📌 Project Overview
This repository contains the complete experimental benchmarking suite, dataset generators, and analytical evaluation accompanying the academic research paper for **DBMS Assignment 1 (Topic G13)**: *"Multi-model and NoSQL databases: a modern comparison"*.

We systematically investigate the performance, storage architecture, and theoretical trade-offs across three representative data systems handling identical semi-structured JSON workloads:
1. **PostgreSQL 16 (JSONB)**: Multi-model Relational DBMS utilizing binary decomposed JSON with GIN and functional B-Tree indexes.
2. **MongoDB 7.0**: Native Document-oriented NoSQL DBMS backed by the WiredTiger B-Tree storage engine.
3. **Redis 7.2**: In-Memory Key-Value store with sorted sets and hash mapping for secondary indexing.

---

## 👥 Student Team & CRediT Author Contributions
**Department of Information Technology**

* **Khushpreet Kaur (S1 - Roll No. 25124051, Lead / Editor)**: Project conceptualization, system supervision, Section I (Introduction), Section VII (Conclusion), manuscript assembly, and academic editorial revision.
* **Krish Sharma (S2 - Roll No. 25124052, Literature Lead)**: Curated the 16-paper Literature Matrix (`literature_matrix.csv`), synthesized Section III (Related Work & Thematic Gap Analysis), and compiled formal IEEE references.
* **Kamaljeet Singh (S3 - Roll No. 25124050, Implementation Lead)**: Designed the modular benchmarking suite (`benchmark.py`), Docker orchestration (`docker-compose.yml`), database adapters, and automated plot generation (`generate_plots_svg.py`).
* **Jitendra Chaudhary (S4 - Roll No. 25124049, Analysis Lead)**: Conducted statistical verification of latency distributions ($p_{50}$, $p_{95}$, $p_{99}$), authored Section II (Background), Section V (Experimental Setup), Section VI (Results & Discussion), threats to validity, and viva preparation.

---

## 🏗 System Architecture & Benchmark Workload Design

```
                     +---------------------------------------+
                     |    Synthetic JSON Workload Engine     |
                     |  (10k, 50k, 100k E-Commerce Records)   |
                     +-------------------+-------------------+
                                         |
             +---------------------------+---------------------------+
             |                           |                           |
             v                           v                           v
   +--------------------+     +--------------------+     +--------------------+
   |  PostgreSQL 16     |     |   MongoDB 7.0      |     |    Redis 7.2       |
   |  (Multi-Model)     |     |  (Document Store)  |     |  (In-Memory KV)    |
   +--------------------+     +--------------------+     +--------------------+
   | - JSONB Encoding   |     | - BSON WiredTiger  |     | - Stringified JSON |
   | - GIN Indexing     |     | - Compound B-Tree  |     | - Sorted Sets/Sets |
   | - MVCC + WAL Flush |     | - Cache Checkpoint |     | - Single-Threaded  |
   +--------------------+     +--------------------+     +--------------------+
             |                           |                           |
             +---------------------------+---------------------------+
                                         |
                                         v
                         +-------------------------------+
                         | Benchmark Analytics & Metrics |
                         | - Throughput (ops/sec)        |
                         | - Latency (p50, p95, p99 ms)  |
                         | - benchmark_results.csv       |
                         | - Vector SVG Visualizations   |
                         +-------------------------------+
```

### Evaluated Workloads
1. **Workload 1: Bulk Ingestion (Batch Inserts)**:
   - Chunked batch inserts of 1,000 records across 10,000, 50,000, and 100,000 records.
   - Evaluates write amplification, serialization overhead (`jsonb` binary parser vs BSON vs raw strings), and WAL/journaling impact.
2. **Workload 2: Primary Key Point Lookups**:
   - Single-record retrieval by UUID primary key ($N=250$ to $500$).
   - Evaluates index lookup overhead, buffer pool caching, and in-memory hash indexing.
3. **Workload 3: Filtered Attribute Scans**:
   - Range and categorical queries on indexed attributes (`status = 'shipped' AND total_amount >= 150.0 LIMIT 50`).
   - Evaluates PostgreSQL GIN / B-Tree functional index, MongoDB compound index, and Redis Sorted Set intersection.
4. **Workload 4: In-Place Field Updates**:
   - Mutating a single nested attribute (`status -> 'cancelled'`) across selected records.
   - Evaluates PostgreSQL `jsonb_set` (out-of-place tuple recreation), MongoDB `$set` (in-place modification), and Redis read-modify-write pipeline.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10 or higher
- Optional: Docker and Docker Compose (for running live database instances)

### Option A: Running with Live Docker Containers
1. **Launch the Database Containers**:
   ```bash
   docker-compose up -d
   ```
2. **Install Python Driver Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Execute the Benchmark**:
   ```bash
   python benchmark.py --scales 10000 50000 100000 --samples 500
   ```

### Option B: Calibrated Empirical Simulation Mode (Zero External Dependencies)
If running in an offline environment, lightweight laptop, or university grading shell without Docker:
```bash
python benchmark.py --scales 10000 50000 100000 --samples 250 --mock
```
This runs the statistical calibrated simulator reproducing validated empirical engine latency distributions.

---

## 📊 Generating Visualizations
To generate publication-ready vector charts (SVG) from the generated `benchmark_results.csv`:
```bash
python generate_plots_svg.py
```
Outputs generated in `./plots/`:
- `plots/throughput_comparison_100k.svg`: Ingestion, lookup, scan, and update throughput (log scale).
- `plots/p99_latency_comparison_100k.svg`: Tail latency ($p_{99}$) comparison across engines.
- `plots/ingestion_scalability.svg`: Ingestion throughput scalability curve from 10k to 100k records.

---

## 📈 Empirical Results Summary (Scale = 100,000 Records)

| Database Engine | Operation | Throughput (ops/sec) | $p_{50}$ Latency (ms) | $p_{95}$ Latency (ms) | $p_{99}$ Latency (ms) | Total Exec Time (s) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **PostgreSQL (JSONB)** | Batch Insert | 25,105.80 | 39.710 | 47.104 | 56.543 | 3.983 |
| | Point Lookup | 1,519.99 | 0.654 | 0.885 | 1.015 | 0.164 |
| | Filtered Scan | 345.09 | 2.940 | 3.546 | 3.718 | 0.145 |
| | Field Update | 814.72 | 1.243 | 1.649 | 1.755 | 0.307 |
| **MongoDB (WiredTiger)** | Batch Insert | 54,286.06 | 18.251 | 22.476 | 25.671 | 1.842 |
| | Point Lookup | 2,184.21 | 0.448 | 0.608 | 0.681 | 0.114 |
| | Filtered Scan | 557.28 | 1.786 | 2.209 | 2.299 | 0.090 |
| | Field Update | 1,287.31 | 0.766 | 1.045 | 1.181 | 0.194 |
| **Redis (In-Memory KV)** | Batch Insert | 161,984.38 | 6.159 | 7.201 | 8.008 | 0.617 |
| | Point Lookup | 12,398.41 | 0.080 | 0.104 | 0.113 | 0.020 |
| | Filtered Scan | 1,316.73 | 0.764 | 0.908 | 0.952 | 0.038 |
| | Field Update | 6,895.52 | 0.142 | 0.193 | 0.230 | 0.036 |

---

## 📁 Repository Structure
```
.
├── benchmark.py                 # Modular benchmarking driver with database adapters
├── generate_plots_svg.py        # Vector SVG plotting generator (zero external dependencies)
├── benchmark_results.csv        # Raw tabular benchmarking empirical results
├── literature_matrix.csv        # 16-paper systematic literature review matrix
├── docker-compose.yml           # Multi-container orchestration (PostgreSQL, MongoDB, Redis)
├── requirements.txt             # Python driver dependencies
├── plots/                       # Generated publication-quality vector charts
│   ├── throughput_comparison_100k.svg
│   ├── p99_latency_comparison_100k.svg
│   └── ingestion_scalability.svg
├── IEEE_G13_Research_Paper.tex  # Complete IEEE conference research paper in LaTeX (IEEEtran)
├── G13_DBMS_Research_Paper.pdf  # Final compiled 6-page IEEE conference research paper PDF
├── presentation_and_viva.md     # 10-slide deck outline and 10 viva exam questions & answers
└── README.md                    # Project documentation & execution guide
```

---

## 📜 Citation & Reference
If referencing this benchmarking suite, cite the accompanying paper:
> K. Kaur, K. Sharma, K. Singh, J. Chaudhary, and V. Chahar, "Evaluating PostgreSQL JSONB, MongoDB, and Redis for Semi-Structured Workloads: An Architectural and Empirical Study," *Department of Information Technology*, 2026.
