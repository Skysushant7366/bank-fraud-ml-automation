# 🏦 Bank Fraud Detection & MLOps Pipeline

**Author:** Sushant Kumar Yadav  
**Domain:** Financial Crime Analytics, MLOps, Data Engineering & Cloud Architecture  

[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Platform-4285F4?logo=googlecloud)](https://cloud.google.com/)
[![BigQuery ML](https://img.shields.io/badge/BigQuery-In--Warehouse%20ML-blue?logo=googlebigquery)](https://cloud.google.com/bigquery)
[![Python](https://img.shields.io/badge/Python-Forensic%20Engine-3776AB?logo=python)](https://www.python.org/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-CI%2FCD-black?logo=githubactions)](https://github.com/features/actions)
[![Looker Studio](https://img.shields.io/badge/Looker%20Studio-Live%20Dashboard-orange?logo=looker)](https://lookerstudio.google.com/)
[![Security](https://img.shields.io/badge/Auth-OIDC%20Keyless-green?logo=openid)](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments)

---

## 📑 Executive Summary

Traditional fraud detection relies heavily on static CSV files and manual, rule-based reviews. This project introduces a **Cloud-Native, Fully Automated Fraud Architecture** designed to identify anomalous banking transactions continuously. 

By avoiding heavy data extraction, this pipeline leverages **In-Warehouse Machine Learning (BigQuery ML)** combined with a **Python Forensic Ensemble Engine** (Isolation Forest, Statistical Scoring). Orchestrated securely via **GitHub Actions** using **OIDC Workload Identity Federation (Zero Static Keys)**, the system updates a live Looker Studio Command Center daily, enabling a highly scalable, 100% hands-off threat detection environment.

---

## 📊 CISO Command Center & Business Impact

The pipeline feeds directly into a dark-themed Looker Studio dashboard designed for security analysts, surfacing critical risk metrics for immediate executive action.

<p align="center">
  <img src="dashboard/dashboard_preview_page1.png" width="49%" />
  <img src="dashboard/dashboard_preview_page2.png" width="49%" />
</p>

*Above: The Live Fraud Analytics Dashboard tracking financial loss, attack vectors, risk band distributions, and automated CISO decisions.*

### 🎯 Key Performance Metrics
* **Automated CISO Decisions:** Re-engineered the decision matrix to eliminate "Manual Reviews." The system now operates strictly on **DEFCON 1 (Critical Block)** and **DEFCON 2 (Require OTP)**, freeing up the fraud team entirely.
* **High-Precision Blocking:** Achieved an automated **68.2% Block Rate** on suspicious activities. Out of 44 actual frauds in the latest holdout set, the engine successfully caught 40 (90.9% overall recall).
* **Threat Diagnostics:** Live tracking of over **$588.75K** in transactional volume across multiple threat vectors including Velocity Attacks, Drop House Networks, and Bin Attacks.
* **Geospatial & Category Risk:** Real-time global heatmaps expose high-risk corridors and merchant-category vulnerabilities (e.g., Gambling/Gaming vs. Electronics).

---

## ⚙️ Technical Architecture & Core Engine (Deep Dive)

### 1. The Medallion Data Lake (Synthetic Generation)
A highly sophisticated custom Python pipeline (`data_pipeline/main.py`) simulates 300K+ transactional records across an 8,000-customer static pool. It intentionally injects real-world anomalies (messy data, PII masking, date formatting) to stress-test the ELT logic. 
* **5 Attack Vectors Simulated:** Velocity Attacks, IP Attacks, Drop House Networks, BIN Attacks, and Smart Evade tactics.
* **Hybrid Execution Engine:** Dynamically switches between a *Full Rebuild* (`WRITE_TRUNCATE`) and an *Incremental Last-2-Day* update (`WRITE_APPEND`). It optimizes BigQuery compute by utilizing `UNIX_SECONDS` within numeric `RANGE` window functions to prevent Out-Of-Memory (OOM) errors.

### 2. In-Warehouse ML (First Line of Defense)
An XGBoost Classifier (`sushant_xgboost_fraud_model_v17`) is trained directly inside BigQuery using SQL (`bq_ml_model/xgboost_v17_ai_model.sql`).
* **Feature Engineering:** Evaluates newly engineered, real-time behavioral features (`velocity_1h`, `velocity_24h`, `time_since_last_txn`, `avg_amount_deviation`, `device_risk_score`) without extracting the data.
* **Imbalance Handling:** Natively handles severe class imbalance via `auto_class_weights = TRUE` and uses the `HIST` tree method with 150 max iterations while retaining global explainability (SHAP).

### 3. Python Forensic Engine & CISO Decision (Second Line of Defense)
A daily cron job pulls the last 15 days of BQML predictions and passes them through the advanced Python forensic pipeline located in `Colab/fraud_ml_pipeline.py`. This engine applies **15 leakage-free, past-only statistical tests** to catch zero-day anomalies:
* **Outlier Detection:** Z-Score, Median Absolute Deviation (MAD), and Interquartile Range (IQR).
* **Probabilistic Models:** Poisson distribution for improbable transactional bursts and Benford's Law for first-digit manipulation.
* **Behavioral Context:** Shannon Entropy for merchant category randomness, Markov Chains for rare behavior transition paths, Time-of-Day deviations, and Structuring (round amount) detection.
* **Multivariate & Graph-Based:** Mahalanobis Distance, Cosine Similarity (amount vs. balance vector), Fraud Ring detection (shared device/IP tracking), and an unsupervised Scikit-Learn `IsolationForest`.
* **Zero-Manual-Review Matrix:** The engine fuses the XGBoost AI score with the 15 forensic signals into a final `composite_risk_score`. It then implements a strict, 100% automated decision matrix: **DEFCON 1 (Critical Block)** and **DEFCON 2 (Require OTP)**.

### 4. DevSecOps & Keyless CI/CD
Scheduled via `.github/workflows/run_ml.yml`, the pipeline executes securely on an `ubuntu-latest` runner using **GCP Workload Identity Federation (OIDC)**. This strictly adheres to enterprise DevSecOps best practices by eliminating the need to store long-lived, vulnerable JSON service account keys in GitHub Secrets.

---

## 📂 Repository Structure

```text
bank-fraud-ml-automation/
├── .github/workflows/
│   └── run_ml.yml                     # GitHub Actions CI/CD cron job (OIDC configured)
│
├── Colab/
│   ├── readme_colab_jupyter.md        # Deep dive into the 15-factor Forensic Engine
│   └── fraud_ml_pipeline.py           # Core Python engine (Isolation Forest + BQ Client)
│
├── bq_ml_model/
│   ├── readme_ai_model.md             # Deep dive into XGBoost Hyperparameters & Features
│   └── xgboost_v17_ai_model.sql       # BigQuery ML model creation & training script
│
├── dashboard/
│   ├── CISO_Command_Center__Enterprise_Fraud_Engine.pdf
│   ├── dashboard_preview_page1.png    # CISO Command Center KPIs
│   └── dashboard_preview_page2.png    # Risk band distribution & Financial Loss metrics
│
├── data_pipeline/
│   ├── readme_mainpy.md               # Details on Medallion Architecture & Synthetic Gen
│   ├── main.py                        # Python/Faker data generator (Raw->Silver->Gold)
│   └── requirements.txt               # Dependencies for data generation
│
└── README.md                          # Project Documentation (You're here)
