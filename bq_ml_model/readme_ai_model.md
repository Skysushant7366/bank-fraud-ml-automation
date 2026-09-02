# 🧠 BigQuery ML: XGBoost Fraud Detection Model (v17)

This directory contains the SQL-based Machine Learning training pipeline (`xgboost_v17_ai_model.sql`). By leveraging **BigQuery ML (BQML)**, we train a highly optimized **XGBoost Classifier** directly inside the data warehouse. 

This approach completely eliminates the need to extract large transactional datasets into external Jupyter environments, ensuring maximum security, zero data movement, and seamless MLOps integration.

---

## 🎯 Model Overview & Training Strategy

**Model Name:** `sushant_xgboost_fraud_model_v17`  
**Model Type:** `BOOSTED_TREE_CLASSIFIER` (XGBoost)  
**Target Variable:** `is_fraud` (Binary Classification)  
**Training Data:** `live-fraud-detection.fraud_data_lake.gold_fraud_mart`

### The 15-Day Temporal Holdout Strategy
Fraud patterns evolve rapidly. To ensure the model generalizes well to future, unseen attacks (out-of-time validation), the training data is strictly filtered:
```sql
WHERE transaction_timestamp < (
    SELECT TIMESTAMP_SUB(MAX(transaction_timestamp), INTERVAL 15 DAY)
    FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
)
