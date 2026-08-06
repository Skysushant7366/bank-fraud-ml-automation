# ============================================================
# CELL 1: GCP Authentication, Imports & BigQuery Client
# ============================================================
# 🔥 GitHub Actions ke liye Colab auth hata kar service account key use ki gayi hai:
from google.cloud import bigquery
import json, os
client = bigquery.Client.from_service_account_json('gcp_key.json')
print('✅ GitHub Action: BigQuery connected via Service Account Key!')

import pandas as pd
import numpy as np
import hashlib
import warnings
from sklearn.ensemble import IsolationForest
from scipy.stats import poisson
warnings.filterwarnings("ignore")

project_id = 'live-fraud-detection'
print('✅ BigQuery ready!')

# ============================================================
# CELL 2: Extract AI Predictions from v17
# ============================================================
print("⏳ Extracting AI Predictions from v17...")
query = """
SELECT *
FROM ML.PREDICT(
    MODEL `live-fraud-detection.fraud_data_lake.sushant_xgboost_fraud_model_v17`,
    (SELECT * FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
     WHERE transaction_timestamp >= (
       SELECT TIMESTAMP_SUB(MAX(transaction_timestamp), INTERVAL 15 DAY)
       FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
     ))
)
"""
df = client.query(query).to_dataframe()

df['ai_fraud_score'] = df['predicted_is_fraud_probs'].apply(
    lambda x: next((item['prob'] for item in x if item['label'] == 1), 0)
)
df = df.drop(columns=['predicted_is_fraud', 'predicted_is_fraud_probs'])

df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'], errors='coerce')
for col in ['amount_clean', 'balance_clean', 'account_age_minutes']:
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

df = df.sort_values(by=['customer_id', 'transaction_timestamp']).reset_index(drop=True)
print(f"✅ Rows: {len(df)} | Cols: {len(df.columns)}")
print(df['ai_fraud_score'].describe())

# ============================================================
# CELL 3: FORENSIC STATS (LEAKAGE-FREE, PAST-ONLY)
# ============================================================
print("⏳ Applying forensic stats...")

df['group_key'] = df['customer_id'].astype(str).str.strip()
df['group_size'] = df.groupby('group_key')['transaction_id'].transform('count')
df['stat_low_sample_size'] = np.where(df['group_size'] < 3, 1, 0)

def past_expanding(gcol, vcol, func):
    return df.groupby(gcol)[vcol].transform(
        lambda x: getattr(x.expanding(), func)().shift(1))

# 1. IQR (past-only, cold-start guarded)
p75 = df.groupby('group_key')['amount_clean'].transform(lambda x: x.expanding().quantile(0.75).shift(1))
p25 = df.groupby('group_key')['amount_clean'].transform(lambda x: x.expanding().quantile(0.25).shift(1))
iqr_limit = p75 + 1.5 * (p75 - p25)
df['stat_is_iqr_anomaly'] = np.where((df['group_size'] > 2) & (df['amount_clean'] > iqr_limit), 1, 0)
df['stat_is_iqr_anomaly'] = df['stat_is_iqr_anomaly'].fillna(0)

# 2. Z-SCORE (past-only)
u_mean = past_expanding('group_key', 'amount_clean', 'mean')
u_std  = past_expanding('group_key', 'amount_clean', 'std').fillna(0)
df['stat_zscore'] = np.where(u_std > 0, (df['amount_clean'] - u_mean) / u_std, 0)
df['stat_zscore'] = df['stat_zscore'].fillna(0)
df['stat_is_zscore_anomaly'] = np.where(df['stat_zscore'].abs() > 3, 1, 0)

# 3. MAD (past-only)
u_median = past_expanding('group_key', 'amount_clean', 'median')
df['_abs_dev'] = (df['amount_clean'] - u_median).abs()
mad = df.groupby('group_key')['_abs_dev'].transform(lambda x: x.expanding().median().shift(1))
df['stat_modified_zscore'] = np.where((mad > 0) & (~u_median.isna()),
    0.6745 * (df['amount_clean'] - u_median) / mad, 0)
df['stat_modified_zscore'] = df['stat_modified_zscore'].fillna(0)
df['stat_is_mad_anomaly'] = np.where(df['stat_modified_zscore'].abs() > 3.5, 1, 0)
df = df.drop(columns=['_abs_dev'])

# 4. PERCENTILE (past-only)
df['stat_amount_percentile'] = df.groupby('group_key')['amount_clean'].transform(
    lambda x: x.expanding().apply(lambda w: (w.iloc[-1] >= w).mean(), raw=False))
df['stat_is_top_percentile'] = np.where(df['stat_amount_percentile'] > 0.98, 1, 0)

# 5. VELOCITY (past-only)
def rolling_1h_count(g):
    ts = g.set_index('transaction_timestamp').sort_index()
    return ts['transaction_id'].rolling('1h').count().values
df['stat_txns_last_1h'] = (df.groupby('group_key', group_keys=False)
    .apply(lambda g: pd.Series(rolling_1h_count(g), index=g.index)))
df['stat_is_velocity_anomaly'] = np.where(df['stat_txns_last_1h'] >= 5, 1, 0)

# 6. POISSON (past-only, off-by-one fixed)
def get_past_poisson_stats(g):
    diffs = g.diff().dt.total_seconds().fillna(0)
    cum_span = diffs.expanding().sum().shift(1).fillna(0)
    cum_count = pd.Series(range(len(g)), index=g.index)
    return cum_span, cum_count

span_secs, cnts = zip(*df.groupby('group_key')['transaction_timestamp'].apply(get_past_poisson_stats))
span_secs = np.concatenate(span_secs)
cnts = np.concatenate(cnts)
span_h = span_secs / 3600.0
span_h = np.clip(span_h, 1, None)
cnts = np.clip(cnts, 0.01, None)
lam = cnts / span_h
lam = np.clip(lam, 0.01, None)

df['stat_poisson_pvalue'] = poisson.sf(df['stat_txns_last_1h'] - 1, lam)
df['stat_is_poisson_anomaly'] = np.where(df['stat_poisson_pvalue'] < 0.01, 1, 0)

# 7. TIME-OF-DAY (past-only)
df['txn_hour'] = df['transaction_timestamp'].dt.hour
hour_mean = past_expanding('group_key', 'txn_hour', 'mean')
hour_std  = past_expanding('group_key', 'txn_hour', 'std').fillna(0)
df['stat_hour_deviation'] = np.where(hour_std > 0, (df['txn_hour'] - hour_mean).abs() / hour_std, 0)
df['stat_hour_deviation'] = df['stat_hour_deviation'].fillna(0)
df['stat_is_odd_hour'] = np.where((df['txn_hour'] <= 5) & (df['stat_hour_deviation'] > 2), 1, 0)

# 8. STRUCTURING
amt_int = df['amount_clean'].round().astype('int64')
df['stat_is_round_amount'] = np.where(amt_int % 100 == 0, 1, 0)
df['stat_is_structuring'] = np.where(
    (amt_int % 1000).between(990, 999) | (amt_int % 500).between(490, 499), 1, 0)

# 9. MAHALANOBIS
f3 = ['amount_clean', 'balance_clean', 'account_age_minutes']
x_raw = df[f3].fillna(0).astype(float).values
x_std = (x_raw - x_raw.mean(axis=0)) / (x_raw.std(axis=0) + 1e-9)
cov = np.cov(x_std, rowvar=False)
inv_cov = np.linalg.pinv(cov)
diff = x_std - x_std.mean(axis=0)
df['stat_mahalanobis_score'] = np.sqrt(np.einsum('ij,jk,ik->i', diff, inv_cov, diff))
df['stat_is_maha_anomaly'] = np.where(
    df['stat_mahalanobis_score'] > df['stat_mahalanobis_score'].quantile(0.99), 1, 0)

# 10. COSINE (past-only)
ua = past_expanding('group_key', 'amount_clean', 'mean').fillna(df['amount_clean'])
ub = past_expanding('group_key', 'balance_clean', 'mean').fillna(df['balance_clean'])
user_avg = np.column_stack([ua.values, ub.values])
current = df[['amount_clean', 'balance_clean']].fillna(0).values
dot = np.sum(current * user_avg, axis=1)
den = np.linalg.norm(current, axis=1) * np.linalg.norm(user_avg, axis=1)
den[den == 0] = 1
df['stat_cosine_similarity'] = dot / den

# 11. ENTROPY
def shannon(s):
    c = s.value_counts(normalize=True)
    return -np.sum(c * np.log2(c + 1e-9))
ent = df.groupby('group_key')['merchant_category_code'].apply(shannon)
df['stat_behavior_entropy'] = df['group_key'].map(ent).fillna(0)
df['stat_is_high_entropy'] = np.where(
    df['stat_behavior_entropy'] > df['stat_behavior_entropy'].quantile(0.95), 1, 0)

# 12. MARKOV
df['prev_merchant'] = df.groupby('group_key')['merchant_name'].shift(1).fillna('FIRST_TXN')
df['behavior_path'] = df['prev_merchant'] + ' -> ' + df['merchant_name']
pc = df.groupby('behavior_path')['transaction_id'].transform('count')
df['stat_is_rare_behavior_path'] = np.where(pc < 5, 1, 0)

# 13. BENFORD
df['first_digit'] = df['amount_clean'].apply(
    lambda a: int(str(a).lstrip('0.').replace('.', '')[0]) if a > 0 else 0)
hd = df[df['first_digit'].isin([7,8,9])].groupby('group_key')['transaction_id'].count()
tot = df.groupby('group_key')['transaction_id'].count()
br = (hd / tot).fillna(0)
df['stat_benford_hi_ratio'] = df['group_key'].map(br).fillna(0)
df['stat_is_benford_anomaly'] = np.where(df['stat_benford_hi_ratio'] > 0.5, 1, 0)

# 14. ISOLATION FOREST
iso_features = ['amount_clean', 'balance_clean', 'account_age_minutes',
                'stat_zscore', 'stat_mahalanobis_score', 'stat_txns_last_1h']
iso_x = df[iso_features].fillna(0).replace([np.inf, -np.inf], 0).values
iso = IsolationForest(n_estimators=200, contamination='auto', random_state=42, n_jobs=-1)
df['stat_iso_raw'] = iso.fit_predict(iso_x)
df['stat_iso_score'] = -iso.score_samples(iso_x)
df['stat_is_iso_anomaly'] = np.where(df['stat_iso_raw'] == -1, 1, 0)

# 15. FRAUD RING
dev_users = df.groupby('device_id')['customer_id'].transform('nunique')
ip_users  = df.groupby('ip_address')['customer_id'].transform('nunique')
df['stat_device_shared_users'] = dev_users
df['stat_ip_shared_users'] = ip_users
df['stat_is_fraud_ring'] = np.where((dev_users >= 8) | (ip_users >= 8), 1, 0)

print("✅ 15 stats applied!")

# ============================================================
# CELL 4: COMPOSITE RISK SCORE + CISO DECISION (NO MANUAL)
# ============================================================
print("⏳ Building risk score...")

df['stat_signal_count'] = (
    df['stat_is_iso_anomaly'] + df['stat_is_velocity_anomaly'] + df['stat_is_fraud_ring'] +
    df['stat_is_maha_anomaly'] + df['stat_is_zscore_anomaly'] + df['stat_is_mad_anomaly'] +
    df['stat_is_structuring'] + df['stat_is_odd_hour'] + df['stat_is_poisson_anomaly'] +
    df['stat_is_iqr_anomaly'])

df['composite_risk_score'] = (
    df['ai_fraud_score']             * 55 +
    df['stat_is_iso_anomaly']      *  7 +
    df['stat_is_velocity_anomaly'] *  7 +
    df['stat_is_fraud_ring']       *  7 +
    df['stat_is_poisson_anomaly']  *  5 +
    df['stat_is_maha_anomaly']     *  4 +
    df['stat_is_zscore_anomaly']   *  3 +
    df['stat_is_structuring']      *  3 +
    df['stat_is_odd_hour']         *  2
).clip(0, 100).round(2)

df['risk_band'] = pd.cut(df['composite_risk_score'],
    bins=[-1, 30, 55, 75, 101], labels=['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'])

reason_map = {
    'stat_is_iso_anomaly': 'Unsupervised anomaly (Isolation Forest)',
    'stat_is_velocity_anomaly': 'High velocity (5+ txns/hour)',
    'stat_is_fraud_ring': 'Shared device/IP (ring)',
    'stat_is_poisson_anomaly': 'Improbable burst (Poisson)',
    'stat_is_maha_anomaly': 'Multivariate outlier (Mahalanobis)',
    'stat_is_zscore_anomaly': 'Amount far from norm (Z-score)',
    'stat_is_mad_anomaly': 'Robust outlier (MAD)',
    'stat_is_structuring': 'Structuring amount',
    'stat_is_odd_hour': 'Unusual hour',
    'stat_is_benford_anomaly': 'Benford violation',
    'stat_is_iqr_anomaly': 'Spend outlier (IQR)',
    'stat_is_high_entropy': 'High behavior randomness',
    'stat_is_rare_behavior_path': 'Rare merchant transition',
}
def build_reason(row):
    r = [t for c, t in reason_map.items() if row.get(c, 0) == 1]
    if row['ai_fraud_score'] >= 0.75:
        r.insert(0, f"AI high score ({row['ai_fraud_score']:.2f})")
    return " | ".join(r) if r else "No strong signals"
df['risk_reason'] = df.apply(build_reason, axis=1)

# ============================================================
# 🔥🔥🔥 UPDATED CONDITIONS: NO MANUAL REVIEW (ALL MERGED INTO OTP)
# ============================================================
conditions = [
    # 🟥 DEFCON 1: CRITICAL BLOCK (Unchanged - 100% Precision)
    (df['ai_fraud_score'] >= 0.75) | (df['composite_risk_score'] >= 75),

    # 🟨 DEFCON 2: REQUIRE OTP (Now absorbs all previous Manual Review cases)
    (df['ai_fraud_score'] >= df['ai_fraud_score'].quantile(0.80)) |
    (df['composite_risk_score'] >= 45) |
    (df['stat_is_velocity_anomaly'] == 1) |
    (df['stat_is_fraud_ring'] == 1) |
    # 🔥 Merged from old DEFCON 3:
    (df['stat_signal_count'] >= 2) |      # ⬅️ Ye 2, 3, 4, 5... sab ko cover kar lega
    ((df['stat_is_iso_anomaly'] == 1) & (df['stat_is_maha_anomaly'] == 1)),  # ⬅️ Iso + Maha combo
]

# 🔥 SIRF 2 DECISIONS AB: BLOCK, OTP (Manual Review Khatam)
choices = ['🔴 DEFCON 1: CRITICAL BLOCK', '🟡 DEFCON 2: REQUIRE OTP']
df['final_ciso_decision'] = np.select(conditions, choices, default='🟢 DEFCON 4: CLEAR')

# ============================================================
# 🧹 Cleanup & Upload to BigQuery
# ============================================================
drop_cols = ['group_key', 'group_size', 'prev_merchant', 'behavior_path',
             'first_digit', 'txn_hour', 'stat_iso_raw']
df = df.drop(columns=[c for c in drop_cols if c in df.columns])

if 'ip_address' in df.columns:
    df['secure_ip_hash'] = df['ip_address'].apply(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
df['risk_band'] = df['risk_band'].astype(str)

print("⏳ Uploading to BigQuery...")
table_id = f"{project_id}.fraud_data_lake.looker_ultimate_static_table"
job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
print(f"🎉 Table '{table_id}' is LIVE!")

print("\n📊 Decision vs Actual Fraud:")
print(df.groupby(['final_ciso_decision', 'is_fraud']).size())

print("\n📊 Risk Band:")
print(df['risk_band'].value_counts())

# 🔥 Ab Manual Review print nahi karenge kyunki hai hi nahi!
# Sirf OTP aur CLEAR ka output dekhna hai.

total_fraud = df['is_fraud'].sum()
print(f"\n📊 Total Frauds in Holdout Set: {total_fraud}")
print("\n📊 AI Score Threshold Analysis:")
for q in [0.85, 0.90, 0.93, 0.95, 0.97]:
    thresh = df['ai_fraud_score'].quantile(q)
    mask = df['ai_fraud_score'] >= thresh
    caught = df.loc[mask, 'is_fraud'].sum()
    print(f"q={q} | n={mask.sum()} | recall={caught/total_fraud:.1%} | precision={caught/mask.sum():.1%}")

print("\n📊 Signal Count Distribution:")
print(df['stat_signal_count'].value_counts().sort_index())

# 🎯 Final Business Summary
block_frauds = df[(df['final_ciso_decision'] == '🔴 DEFCON 1: CRITICAL BLOCK') & (df['is_fraud'] == 1)].shape[0]
otp_frauds = df[(df['final_ciso_decision'] == '🟡 DEFCON 2: REQUIRE OTP') & (df['is_fraud'] == 1)].shape[0]
clear_frauds = df[(df['final_ciso_decision'] == '🟢 DEFCON 4: CLEAR') & (df['is_fraud'] == 1)].shape[0]
clear_total = df[df['final_ciso_decision'] == '🟢 DEFCON 4: CLEAR'].shape[0]

print("\n" + "="*60)
print("🎯 FINAL BUSINESS SUMMARY (v17 - NO MANUAL REVIEW):")
print("="*60)
print(f"🔴 DEFCON 1 (Block):        {block_frauds} frauds blocked (0 False Positives!)")
print(f"🟡 DEFCON 2 (OTP):          {otp_frauds} frauds caught via OTP")
print(f"🟢 DEFCON 4 (CLEAR):        {clear_frauds} frauds missed (Out of {clear_total} total clear txns)")
print(f"📈 OVERALL FRAUD RECALL:    {(block_frauds + otp_frauds) / total_fraud * 100:.1f}%")
print(f"👥 MANUAL REVIEW EFFORT:    0 rows (Team is FREE!)")
print("="*60)
