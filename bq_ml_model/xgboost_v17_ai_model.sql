-- ==============================================================
--  MODEL NAME          : sushant_xgboost_fraud_model_v17
--  DESCRIPTION         : XGBoost with 5 new behavioral features
--  CREATED ON          : 2026-07-27
-- ==============================================================

CREATE OR REPLACE MODEL `live-fraud-detection.fraud_data_lake.sushant_xgboost_fraud_model_v17`
OPTIONS(
    model_type            = 'BOOSTED_TREE_CLASSIFIER',
    input_label_cols      = ['is_fraud'],
    auto_class_weights    = TRUE,
    data_split_method     = 'AUTO_SPLIT',
    min_split_loss        = 0.1,
    l1_reg                = 0.1,
    l2_reg                = 0.2,
    colsample_bytree      = 0.8,   -- ⬅️ TYPO FIXED
    subsample             = 0.8,
    max_iterations        = 150,
    learn_rate            = 0.1,
    max_tree_depth        = 6,
    tree_method           = 'HIST',
    early_stop            = TRUE,
    enable_global_explain = TRUE
) AS
SELECT
    -- 🔐 Target
    is_fraud,

    -- 📊 Old Features
    amount_clean,
    balance_clean,
    currency_code,
    transaction_type,
    merchant_category_code,
    merchant_country,
    card_network,
    card_type,
    channel,
    entry_mode,
    account_age_minutes,
    amount_to_balance_ratio,
    hour_of_day,
    day_of_week,
    zip_mismatch,
    is_fresh_account,

    -- 🚀 New Behavioral Features (v17)
    velocity_1h,
    velocity_24h,
    time_since_last_txn,
    avg_amount_deviation,
    device_risk_score

FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
WHERE transaction_timestamp < (
    SELECT TIMESTAMP_SUB(MAX(transaction_timestamp), INTERVAL 15 DAY)
    FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
)
AND is_fraud IS NOT NULL
AND amount_clean IS NOT NULL
AND balance_clean IS NOT NULL;
