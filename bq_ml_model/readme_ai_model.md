# 🧠 BigQuery ML: XGBoost Fraud Detection Model (v17)

**Model Name:** `sushant_xgboost_fraud_model_v17`  
**Framework:** BigQuery ML (BQML)  
**Algorithm:** `BOOSTED_TREE_CLASSIFIER` (XGBoost)  
**Target Variable:** `is_fraud` (Binary Classification)  

---

## 📑 Overview

This directory contains the SQL-based Machine Learning training pipeline (`xgboost_v17_ai_model.sql`). By leveraging **BigQuery ML (BQML)**, we train a highly optimized XGBoost Classifier directly inside the data warehouse. 

**Why In-Warehouse ML?**
* **Zero Data Movement:** Eliminates the need to export massive transactional datasets to external Jupyter/Vertex AI environments.
* **Enhanced Security:** Sensitive PII and financial data never leave the secure BigQuery perimeter.
* **Seamless MLOps:** Model training, evaluation, and inference (`ML.PREDICT`) are executed using standard SQL, making CI/CD automation via GitHub Actions frictionless.

---

## ⚙️ Hyperparameter Engineering & Model Tuning

Fraud detection is notoriously difficult due to extreme class imbalance and dynamic attack vectors. The `OPTIONS` block in this model is explicitly tuned to combat these challenges:

### 1. Handling Class Imbalance
* **`auto_class_weights = TRUE`**: Fraud transactions are rare (approx. 3%). This parameter automatically balances class weights, heavily penalizing the model for missing minority class (fraud) instances without requiring manual SMOTE or oversampling.

### 2. Regularization & Overfitting Prevention
* **`l1_reg = 0.1` (Lasso) & `l2_reg = 0.2` (Ridge)**: Adds penalty terms to the loss function. This forces the model to ignore noisy, irrelevant features and focus only on robust fraud indicators.
* **`colsample_bytree = 0.8` & `subsample = 0.8`**: Implements stochastic gradient boosting. Every tree is trained on a random 80% subset of the data and 80% of the features, drastically reducing variance and preventing the ensemble from memorizing the training set.
* **`max_tree_depth = 6`**: Restricts the maximum depth of individual decision trees to prevent overfitting on highly specific, non-generalizable transaction paths.

### 3. Training Mechanics & Optimization
* **`tree_method = 'HIST'`**: Utilizes histogram-based approximations for tree building. This significantly accelerates training speed on large-scale data lake tables.
* **`learn_rate = 0.1` & `max_iterations = 150`**: Ensures steady, stable convergence.
* **`early_stop = TRUE`**: Automatically monitors validation loss and halts training early if the model stops improving, optimizing BigQuery compute costs.
* **`enable_global_explain = TRUE`**: Crucial for enterprise compliance. This generates global feature attributions (SHAP values), allowing the CISO and risk teams to understand exactly *why* the model makes specific block/allow decisions.

---

## 🧬 Feature Space (v17 Upgrade)

Version 17 introduces a major shift from static transactional data to dynamic, real-time behavioral analytics. 

### 🚀 New Behavioral Features (Engineered via Window Functions)
1. **`velocity_1h`**: Identifies rapid transaction bursts by counting attempts in the last 60 minutes.
2. **`velocity_24h`**: Daily transaction volume tracking.
3. **`time_since_last_txn`**: Time elapsed (in minutes) since the customer's previous transaction.
4. **`avg_amount_deviation`**: Ratio comparing the current transaction amount against the customer's rolling 10-transaction average.
5. **`device_risk_score`**: Tracks distinct transactions originating from the exact same physical device footprint.

### 📊 Baseline & Contextual Features (16 Variables)
* **Financial Vectors:** `amount_clean`, `balance_clean`, `amount_to_balance_ratio`, `currency_code`.
* **Geospatial Vectors:** `merchant_country`, `zip_mismatch` (Billing vs. Shipping discrepancies).
* **Payment Modality:** `transaction_type`, `card_network`, `card_type`, `channel`, `entry_mode`.
* **Temporal Context:** `account_age_minutes`, `hour_of_day`, `day_of_week`.
* **Risk Flags:** `is_fresh_account` (Strong indicator for Bust-out fraud), `merchant_category_code`.

---

## ⏳ The 15-Day Temporal Holdout Strategy

To rigorously test how the model performs on *future, unseen attacks* (Out-of-Time validation), the training data is strictly time-filtered:
```sql
WHERE transaction_timestamp < (
    SELECT TIMESTAMP_SUB(MAX(transaction_timestamp), INTERVAL 15 DAY)
    FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
)
