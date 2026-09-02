# 🏦 End-to-End Bank Fraud Detection & MLOps Pipeline

![Google Cloud](https://img.shields.io/badge/Google_Cloud-BigQuery-4285F4?style=flat-square&logo=googlecloud)
![BigQuery ML](https://img.shields.io/badge/BQML-In--Warehouse_ML-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-Faker_%7C_Pandas-3776AB?style=flat-square&logo=python)
![Looker](https://img.shields.io/badge/Looker_Studio-Live_Dashboard-F9AB00?style=flat-square&logo=looker)

## 📌 Executive Summary
An automated, cloud-native fraud detection architecture designed to identify anomalous banking transactions. Instead of relying on static CSV files, I engineered a complete Data Pipeline from synthetic data generation to in-warehouse Machine Learning (BigQuery ML) and live dashboarding.

---

## 💼 The Architecture Flow (How It Works)

### 1. Data Ingestion (The Generator)
* Built a custom Python script (`main.py`) using the `Faker` library inside the **BigQuery Cloud Terminal**.
* Continuously generates and streams realistic banking transactional data directly into BigQuery.

### 2. The Medallion Data Warehouse (SQL)
* **Raw Layer:** Lands the incoming JSON/CSV payloads.
* **Silver Layer:** Cleanses, deduplicates, and standardizes timestamps and currencies.
* **Gold Layer:** Aggregates user-level financial behavior and flags historical anomalies for training.

### 3. In-Warehouse Machine Learning (BQML)
* **Why BQML?** To avoid the high cloud compute costs and latency of moving massive datasets out of the warehouse, I trained the `v17_fraud_model` *directly* inside BigQuery using SQL.
* The model learns from the Gold table to detect high-risk transaction patterns.

### 4. MLOps & Advanced Orchestration (Google Colab)
* Used Google Colab as the orchestration layer to bridge the BQ Model and the live Gold table.
* Applied advanced statistical filtering to isolate and predict only the **Last 15 Days** of transaction data.
* Pushed the final, highly accurate predictive dataset back into a new BigQuery output table.

### 5. BI & Visualization
* Connected the final predictive table directly to **Looker Studio**.
* Created a live Executive Dashboard that allows Bank Managers to monitor Real-Time Fraud Alerts and transaction velocity without interacting with the code.

---

## ⚙️ Tech Stack
* **Cloud Infrastructure:** Google Cloud Platform (GCP Cloud Shell)
* **Data Generation:** Python (`Faker`)
* **Data Engineering (DWH):** BigQuery (Raw, Silver, Gold Architecture)
* **Machine Learning:** BigQuery ML (BQML)
* **Orchestration:** Google Colab, Pandas
* **Visualization:** Looker Studio
