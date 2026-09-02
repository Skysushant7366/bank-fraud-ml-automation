# 🧠 DEEP DIVE: main.py (Synthetic Data Gen & Hybrid Medallion Pipeline)

This file is the central nervous system of the data engineering workflow. It is built as a Google Cloud Function (`@functions_framework.http`) that acts as a Data Generator, PII Masker, Fraud Simulator, and BigQuery Medallion Architecture Orchestrator[cite: 4].

Here is the comprehensive, step-by-step breakdown of the logic:

## 1. 🌍 The Static World Configuration (Consistency & Reproducibility)
To ensure the ML models get consistent patterns, the script locks the random generators using `SEED = 42`[cite: 4].
* **Static Customer Pool:** It generates 8,000 baseline customers (`CUSTOMER_POOL`)[cite: 4]. Each customer is assigned fixed, realistic attributes: Name, Email, Phone, Home IP, Device ID, preferred Merchant Category Code (MCC), an average ticket size (`avg_ticket`), usual shopping hours, and a specific `risk_weight`[cite: 4].
* **Compromised Accounts:** Out of 8,000 customers, 60 are pre-selected as "compromised"[cite: 4]. The first 20 of these have their account creation dates forced to be within the last 3 days to simulate "Fresh Account / Bust-Out" fraud[cite: 4].
* **Threat Entities:** Pre-defines arrays for malicious IPs (`BAD_IPS`, 200 IPs), fraudulent shipping addresses (`DROP_HOUSES`, 40 addresses), and highly targeted card BINs (`TARGET_BINS`)[cite: 4].

## 2. 🧪 "Messy Data" Simulators (ELT Preparation)
Real-world data is inherently dirty. The script forces the downstream BigQuery pipeline to perform actual data cleansing by injecting random formatting issues[cite: 4]:
* `_messy_amount`: Randomly formats numbers as `$1,200.00`, `1200.00 `, or `USD 1200.00`[cite: 4].
* `_messy_country`: Randomly injects variations like "USA", "U.S.A", "usa", or "United States"[cite: 4].
* `_messy_timestamp_str`: Randomly outputs timestamps in 4 completely different formats (ISO, MM/DD/YYYY, DD-MMM-YYYY, etc.) to challenge SQL parsing[cite: 4].
* `_maybe_null` & PII Masking: Randomly drops values (inserting `NULL`, `N/A`, or `none`) and occasionally masks emails (`s***@gmail.com`) and phones (`****1234`)[cite: 4].

## 3. 🎯 The 5-Vector Fraud Attack Engine
The script dynamically scales a customer's probability of committing fraud based on their `risk_weight` against the global `TARGET_FRAUD_RATE` (set to 3%)[cite: 4]. When a transaction is flagged as fraud, it triggers 1 of 5 attack vectors[cite: 4]:
1. **SMART_EVADE (20%):** Mimics perfectly normal behavior (usual hours, normal amounts but slightly inflated) to test ML sensitivity[cite: 4].
2. **VELOCITY_ATTACK (30%):** Uses `_get_velocity_burst_txn` to pick a compromised customer and rapidly fire 5 to 9 transactions within a tight time window (seconds/minutes apart)[cite: 4].
3. **IP_ATTACK (18%):** Forces the transaction to originate from the known `BAD_IPS` list using a specific bot user-agent (`python-requests/2.26.0`)[cite: 4].
4. **DROP_HOUSE_ATTACK (17%):** Reroutes the shipping address to a known fraudulent location from `DROP_HOUSES` and spikes the transaction amount between $2,000 and $5,000[cite: 4].
5. **BIN_ATTACK (15%):** Targets specific vulnerable Card BINs with micro-transactions ($1 to $3) to simulate bot-driven card-testing[cite: 4].

## 4. 🚀 Cloud Function Execution & RAM Optimization (No-OOM)
* **Batching:** Reads `total_rows` and `batch_size` from the HTTP payload. It generates data in discrete chunks (e.g., 10,000 rows at a time)[cite: 4].
* **Memory Management:** After pushing a batch to BigQuery, it explicitly triggers garbage collection (`del df`, `del batch_records`) to free up RAM and prevent Out-Of-Memory (OOM) crashes during large runs[cite: 4].
* **Dynamic Disposition:** The first batch respects the `reset_data` boolean (using `WRITE_TRUNCATE`), and all subsequent batches automatically switch to `WRITE_APPEND`[cite: 4].

## 5. 🔥 Hybrid Medallion Architecture (SQL-in-Python Orchestration)
Once the raw data is pushed, the script executes heavy SQL queries directly in BigQuery to build the Silver and Gold layers. It branches based on `reset_data`[cite: 4]:

### Pathway A: Full Rebuild (`reset_data = True`)[cite: 4]
* **Silver Layer (Clean):** Uses `REGEXP_REPLACE` to strip currency symbols, `COALESCE` with `SAFE.PARSE_TIMESTAMP` to normalize the 4 different messy date formats, and `CASE WHEN` to standardize country codes[cite: 4].
* **Gold Layer (Features):** Calculates advanced ML features. 
  * *The UNIX_SECONDS Fix:* Because BigQuery requires numeric types for `RANGE BETWEEN` window functions, it uses `UNIX_SECONDS(transaction_timestamp)` to calculate `velocity_1h` (3600 seconds) and `velocity_24h` (86400 seconds)[cite: 4].
  * *Threat Flags:* Hardcodes 1/0 flags for bot agents, bad IPs, drop houses, and midnight ghosts[cite: 4].

### Pathway B: Incremental Update (`reset_data = False`)[cite: 4]
* **Silver Layer:** Inserts only new records where `ingested_at > MAX(ingested_at)`[cite: 4].
* **Gold Layer (Context Merging):** To calculate rolling window features (e.g., 1-hour velocity) for new transactions, the engine needs historical context[cite: 4]. 
  1. It pulls the *last 2 days of data* (`context` CTE)[cite: 4].
  2. Unions it with the brand new data (`new_rows` CTE)[cite: 4].
  3. Computes the complex window functions over this combined dataset[cite: 4].
  4. Finally, filters and inserts *only* the new, fully-calculated rows into the Gold table[cite: 4]. This is a highly advanced Data Engineering pattern.
