# 🧠 Python Forensic Ensemble & CISO Decision Engine

This module contains the core Python anomaly detection script (`fraud_ml_pipeline.py` / `Ultimate_Creditcard_Fraud_Engine_Master_table.ipynb`). Operating as the **Second Line of Defense**, this engine retrieves the baseline XGBoost probabilities from BigQuery and applies a massive 15-factor statistical and unsupervised learning ensemble to catch sophisticated, zero-day fraud tactics.

---

## 🔬 The 15-Factor Forensic Ensemble

To prevent data leakage, all historical statistical baselines (Mean, Median, Standard Deviation) are calculated strictly on **past data** using Pandas `expanding().shift(1)`. The engine evaluates each transaction against 15 distinct vectors:

### Outlier & Distribution Diagnostics
1. **IQR Anomaly:** Identifies spend outliers beyond the 75th percentile + 1.5*IQR.
2. **Z-Score Anomaly:** Flags amounts deviating by more than 3 standard deviations from the user's historical mean.
3. **MAD Anomaly (Robust Z-Score):** Uses Median Absolute Deviation to detect outliers immune to extreme historical spikes.
4. **Top Percentile:** Flags transactions hitting the 98th percentile of a user's lifetime spend.

### Velocity & Probabilistic Models
5. **Velocity Burst (1h):** Triggers if a user attempts 5+ transactions within a rolling 60-minute window.
6. **Poisson Improbable Burst:** Calculates the expected time between transactions and flags highly improbable bursts (p-value < 0.01) using the Poisson survival function.
7. **Benford's Law Violation:** Analyzes the first digits of transaction amounts to detect artificial human structuring (e.g., an unnatural ratio of amounts starting with 7, 8, or 9).

### Behavioral & Contextual Anomalies
8. **Structuring Detection:** Flags amounts specifically engineered to bypass round-number thresholds (e.g., $990-$999 or $490-$499).
9. **Time-of-Day Deviation:** Identifies transactions occurring during midnight ghost hours (12 AM - 5 AM) that deviate by >2 std devs from the user's usual shopping hours.
10. **Shannon Entropy:** Measures the randomness of merchant category codes; flags highly erratic, high-entropy purchasing behavior.
11. **Markov Chain Rare Paths:** Tracks merchant transition sequences (e.g., *Grocery -> Electronics*); flags transitions that have occurred less than 5 times historically.

### Multivariate & Network Intelligence
12. **Mahalanobis Distance:** Measures the multivariate distance between `amount`, `balance`, and `account_age`, catching subtle combinations of variables that look normal individually but are anomalous together.
13. **Cosine Similarity:** Measures the vector angle between current (amount, balance) and historical averages to detect sudden shifts in financial behavior.
14. **Isolation Forest:** An unsupervised Scikit-Learn model (`n_estimators=200`) trained on 6 composite features to isolate structural anomalies in n-dimensional space.
15. **Fraud Ring Detection:** Tracks device IDs and IP addresses; flags transactions if a single hardware footprint or IP is shared by 8+ distinct customer accounts.

---

## ⚖️ Composite Risk Scoring & DEFCON Matrix

The engine abandons manual review workflows entirely, favoring a 100% automated resolution matrix. It multiplies the AI Probability Score (`ai_fraud_score` × 55) and the forensic flags (weighted between 2 and 7 points each) to generate a `composite_risk_score` (0-100).

### The Zero-Manual-Review Decision Matrix:
* **🔴 DEFCON 1: CRITICAL BLOCK**
  * *Trigger:* AI Score >= 0.75 OR Composite Score >= 75.
  * *Action:* Hard block at the gateway. Achieved 0 False Positives in the holdout set.
* **🟡 DEFCON 2: REQUIRE OTP**
  * *Trigger:* Absorbs all complex edge cases. Triggers on top 20% AI scores, Composite Score >= 45, known Fraud Rings, Velocity anomalies, or any transaction hitting 2+ forensic signals (e.g., Isolation Forest + Mahalanobis).
  * *Action:* Issues a 3D-Secure / OTP challenge.
* **🟢 DEFCON 4: CLEAR**
  * *Action:* Transaction proceeds with zero friction.

### 💾 Data Destination
The final enriched dataset, complete with secure IP hashes, risk bands, and CISO decisions, is pushed back to BigQuery via `WRITE_TRUNCATE` to the `live-fraud-detection.fraud_data_lake.looker_ultimate_static_table` for live Dashboard consumption.
