# ###########################################################
# ###########################################################
# ####  FILE 1: main.py  (Cloud Function - Data Gen)     ####
# ####  BATCH PROCESSING + SCHEDULER READY + NO OOM      ####
# ####  🔥 FIX: Velocity burst engine + naming cleanup   ####
# ####  🔥 v17 UPGRADE: 5 Behavior Features Added        ####
# ####  🔥 HYBRID: Full Rebuild (reset=True) or          ####
# ####           Incremental Last 2 Days (reset=False)   ####
# ####  🔥 FIX: RANGE with UNIX_SECONDS & no DISTINCT   ####
# ###########################################################
# ###########################################################

import pandas as pd
from faker import Faker
import random
import uuid
from datetime import datetime, timedelta
from google.cloud import bigquery
import functions_framework
import numpy as np
import time

bq_client = bigquery.Client(project="live-fraud-detection")

# =========================================================
# 🌍 1. STATIC WORLD (Customers locked with SEED)
# =========================================================
SEED = 42
_customer_rng = random.Random(SEED)
_customer_fk = Faker()
_customer_fk.seed_instance(SEED)

BAD_IPS      = [_customer_fk.ipv4() for _ in range(200)]
DROP_HOUSES  = [_customer_fk.address().replace("\n", ", ") for _ in range(40)]
TARGET_BINS  = ["411111", "424242", "455951", "521729", "601100"]

MCC_ALL   = ["5411", "5812", "7995", "5732"]
COUNTRIES = ["USA", "UK", "IND", "CAN", "RU", "CH"]
CARD_NETWORKS = ["VISA", "MASTERCARD", "AMEX", "DISCOVER"]

NUM_CUSTOMERS = 8000
WINDOW_DAYS = 90
STATIC_NOW = datetime.now()

def _make_customer():
    home_country = _customer_rng.choices(COUNTRIES, weights=[35, 15, 20, 15, 8, 7])[0]
    return {
        "customer_id": str(uuid.UUID(int=_customer_rng.getrandbits(128))),
        "first_name": _customer_fk.first_name(),
        "last_name": _customer_fk.last_name(),
        "email": _customer_fk.email(),
        "phone": _customer_fk.phone_number(),
        "home_country": home_country,
        "home_ip": _customer_fk.ipv4(),
        "device": _customer_fk.user_agent(),
        "device_id": str(uuid.UUID(int=_customer_rng.getrandbits(128)))[:18],
        "billing_address": _customer_fk.address().replace("\n", ", "),
        "billing_zip": _customer_fk.zipcode(),
        "card_bin": _customer_rng.choice(["411111", "424242", "531000", "601100", "371449"]),
        "card_last4": f"{_customer_rng.randint(0, 9999):04d}",
        "card_network": _customer_rng.choice(CARD_NETWORKS),
        "card_type": _customer_rng.choice(["credit", "debit"]),
        "preferred_mcc": _customer_rng.choices(MCC_ALL, weights=[40, 30, 10, 20])[0],
        "avg_ticket": _customer_rng.uniform(20, 150),
        "usual_hours": _customer_rng.sample(range(7, 23), 6),
        "acct_created": STATIC_NOW - timedelta(days=_customer_rng.randint(1, 900), minutes=_customer_rng.randint(0, 1439)),
        "balance": _customer_rng.uniform(200, 15000),
        "risk_weight": _customer_rng.choices([1, 4, 10], weights=[88, 9, 3])[0],
    }

CUSTOMER_POOL = [_make_customer() for _ in range(NUM_CUSTOMERS)]
COMPROMISED = CUSTOMER_POOL[:60]
for c in COMPROMISED[:20]:
    c["acct_created"] = STATIC_NOW - timedelta(days=_customer_rng.randint(0, 3), minutes=_customer_rng.randint(0, 1439))

# =========================================================
# 🔥 VELOCITY BURST ENGINE
# =========================================================
_active_velocity_bursts = []

def _get_velocity_burst_txn(real_time_now):
    global _active_velocity_bursts
    if _active_velocity_bursts and random.random() < 0.7:
        burst = _active_velocity_bursts[0]
    else:
        anchor = real_time_now - timedelta(days=random.randint(0, WINDOW_DAYS - 1),
                                            minutes=random.randint(0, 1439))
        burst = {"victim": random.choice(COMPROMISED), "anchor": anchor, "remaining": random.randint(5, 9)}
        _active_velocity_bursts.insert(0, burst)
    ts = burst["anchor"] + timedelta(seconds=random.randint(0, 2700))
    burst["remaining"] -= 1
    if burst["remaining"] <= 0:
        _active_velocity_bursts.remove(burst)
    return burst["victim"], ts

dynamic_fake = Faker()

# =========================================================
# 🧪 MESSINESS HELPERS
# =========================================================
def _messy_amount(amount):
    style = random.random()
    if style < 0.25: return f"${amount:,.2f}"
    elif style < 0.45: return f"${amount:.2f}"
    elif style < 0.65: return f"{amount:.2f} "
    elif style < 0.80: return str(round(amount, 2))
    elif style < 0.90: return f"  {amount:.2f}"
    else: return f"USD {amount:.2f}"

def _messy_country(country):
    variants = {
        "USA": ["USA", "US", "United States", "usa", "U.S.A"],
        "UK":  ["UK", "GB", "United Kingdom", "uk"],
        "IND": ["IND", "IN", "India", "ind"],
        "CAN": ["CAN", "CA", "Canada"],
        "RU":  ["RU", "RUS", "Russia"],
        "CH":  ["CH", "CHE", "Switzerland"],
    }
    return random.choice(variants.get(country, [country]))

def _messy_name(name):
    r = random.random()
    if r < 0.25: return name.upper()
    elif r < 0.45: return name.lower()
    elif r < 0.60: return f"  {name} "
    return name

def _maybe_null(value, p=0.05, placeholder=None):
    if random.random() < p:
        return random.choice([None, "", "N/A", "null", "NULL", "None"]) if placeholder is None else placeholder
    return value

def _mask_email(email):
    if random.random() < 0.4 and "@" in email:
        u, d = email.split("@", 1)
        return (u[0] + "***@" + d) if u else email
    return email

def _mask_phone(phone):
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if random.random() < 0.4 and len(digits) >= 4:
        return "****" + digits[-4:]
    return phone

# =========================================================
# 🎯 FRAUD SKEW
# =========================================================
TARGET_FRAUD_RATE = 0.03
AVG_RISK_WEIGHT = sum(c["risk_weight"] for c in CUSTOMER_POOL) / len(CUSTOMER_POOL)
ATTACK_TYPES   = ['VELOCITY_ATTACK', 'IP_ATTACK', 'DROP_HOUSE_ATTACK', 'BIN_ATTACK', 'SMART_EVADE']
ATTACK_WEIGHTS = [0.30, 0.18, 0.17, 0.15, 0.20]

# =========================================================
# 🕒 TIMESTAMP HELPERS
# =========================================================
def _spread_timestamp(hour=None, real_time_now=None):
    base = real_time_now - timedelta(days=random.randint(0, WINDOW_DAYS - 1),
                                     minutes=random.randint(0, 1439),
                                     seconds=random.randint(0, 59))
    if hour is not None:
        base = base.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
    return base

def _messy_timestamp_str(dt):
    r = random.random()
    if r < 0.60: return dt.strftime("%Y-%m-%d %H:%M:%S")
    elif r < 0.80: return dt.strftime("%m/%d/%Y %H:%M")
    elif r < 0.95: return dt.isoformat()
    else: return dt.strftime("%d-%b-%Y %I:%M %p")

# =========================================================
# 💳 TRANSACTION GENERATOR
# =========================================================
def generate_ultimate_transaction(real_time_now):
    customer = random.choice(CUSTOMER_POOL)

    p_fraud = min(0.90, TARGET_FRAUD_RATE * (customer["risk_weight"] / AVG_RISK_WEIGHT))
    is_fraud = 1 if random.random() < p_fraud else 0
    attack_type = random.choices(ATTACK_TYPES, weights=ATTACK_WEIGHTS)[0] if is_fraud else 'NORMAL'

    ip_address       = customer["home_ip"]
    user_agent       = customer["device"]
    device_id        = customer["device_id"]
    merchant_country = customer["home_country"]
    mcc              = customer["preferred_mcc"]
    billing_address  = customer["billing_address"]
    billing_zip      = customer["billing_zip"]
    shipping_address = billing_address
    shipping_zip     = billing_zip
    customer_id      = customer["customer_id"]
    first_name       = customer["first_name"]
    last_name        = customer["last_name"]
    balance          = customer["balance"]
    card_bin         = customer["card_bin"]
    card_last4       = customer["card_last4"]
    card_network     = customer["card_network"]
    card_type        = customer["card_type"]

    normal_hour = random.choice(customer["usual_hours"]) if random.random() < 0.80 else random.randint(0, 23)

    if attack_type == 'SMART_EVADE':
        now = _spread_timestamp(hour=normal_hour, real_time_now=real_time_now)
        amount = customer["avg_ticket"] * random.uniform(0.8, 1.4)
        auth_response = random.choices(["00", "00", "05"], weights=[70, 20, 10])[0]
        avs_response = random.choice(["Y", "Z", "N"])
        txn_status = "approved"

    elif attack_type == 'NORMAL':
        now = _spread_timestamp(hour=normal_hour, real_time_now=real_time_now)
        amount = max(5.0, round(np.random.normal(customer["avg_ticket"], customer["avg_ticket"]*0.35), 2))
        if random.random() < 0.06: amount = random.uniform(600, 2200)
        if random.random() < 0.30: mcc = random.choices(MCC_ALL, weights=[40, 30, 10, 20])[0]
        if random.random() < 0.08: merchant_country = random.choice(COUNTRIES)
        if random.random() < 0.10:
            ip_address = random.choice(BAD_IPS) if random.random() < 0.5 else dynamic_fake.ipv4()
            amount = random.uniform(1500, 4000)
            now = now.replace(hour=random.randint(1, 4))
            shipping_zip = dynamic_fake.zipcode()
        auth_response = random.choices(["00", "05", "51"], weights=[90, 6, 4])[0]
        avs_response = random.choices(["Y", "Z", "A", "N"], weights=[75, 10, 8, 7])[0]
        txn_status = random.choices(["approved", "declined"], weights=[92, 8])[0]

    else:
        mcc = random.choices(MCC_ALL, weights=[5, 10, 50, 35])[0]
        merchant_country = random.choices(COUNTRIES, weights=[22, 12, 12, 10, 24, 20])[0]
        hour = random.randint(0, 5) if random.random() < 0.55 else random.randint(6, 23)
        now = _spread_timestamp(hour=hour, real_time_now=real_time_now)
        ip_address = dynamic_fake.ipv4()
        user_agent = dynamic_fake.user_agent()
        device_id = str(uuid.uuid4())[:18]

        if random.random() < 0.40: amount = customer["avg_ticket"] * random.uniform(0.8, 2.2)
        else: amount = random.uniform(350, 3000)

        auth_response = random.choices(["00", "05", "51", "14"], weights=[42, 26, 19, 13])[0]
        avs_response = random.choices(["N", "A", "Z", "Y"], weights=[42, 25, 18, 15])[0]
        txn_status = random.choices(["approved", "declined", "pending"], weights=[60, 30, 10])[0]

        if attack_type == 'VELOCITY_ATTACK':
            victim, now = _get_velocity_burst_txn(real_time_now)
            customer_id, first_name, last_name = victim["customer_id"], victim["first_name"], victim["last_name"]
            balance, card_bin, card_last4 = victim["balance"], victim["card_bin"], victim["card_last4"]
        elif attack_type == 'IP_ATTACK':
            ip_address, user_agent = random.choice(BAD_IPS), "python-requests/2.26.0"
            now = _spread_timestamp(real_time_now=real_time_now) - timedelta(minutes=random.randint(0, 5))
        elif attack_type == 'DROP_HOUSE_ATTACK':
            shipping_address, shipping_zip = random.choice(DROP_HOUSES), dynamic_fake.zipcode()
            amount = random.uniform(2000, 5000)
        elif attack_type == 'BIN_ATTACK':
            card_bin = random.choice(TARGET_BINS)
            victim = random.choice(COMPROMISED)
            customer_id, first_name, last_name = victim["customer_id"], victim["first_name"], victim["last_name"]
            balance, card_last4 = victim["balance"], victim["card_last4"]
            amount = random.uniform(1.00, 3.00)
            now = _spread_timestamp(real_time_now=real_time_now) - timedelta(minutes=random.randint(0, 2))

    acct_timestamp = customer["acct_created"]

    if amount > balance and random.random() < 0.4: balance = amount * random.uniform(0.3, 1.5)
    if (not is_fraud) and random.random() < 0.05: balance = amount * random.uniform(0.2, 0.9)

    if is_fraud:
        cvv = random.choices(["M", "N", "P"], weights=[45, 38, 17])[0]
        tds = random.choices(["verified", "failed", "bypassed", "pending"], weights=[35, 32, 23, 10])[0]
    else:
        cvv = random.choices(["M", "N", "P"], weights=[82, 14, 4])[0]
        tds = random.choices(["verified", "failed", "bypassed", "pending"], weights=[74, 12, 4, 10])[0]

    channel = random.choices(["web", "mobile", "pos"], weights=[50, 40, 10])[0]
    entry_mode = random.choice(["online", "chip", "swipe", "contactless"])
    merchant_name = dynamic_fake.company().upper() + " *WEB" if random.random() > 0.8 else dynamic_fake.company()

    return {
        "transaction_id": str(uuid.uuid4()),
        "transaction_timestamp": _messy_timestamp_str(now),
        "account_creation_date": acct_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "ingested_at": real_time_now.strftime("%Y-%m-%d %H:%M:%S"),
        "amount_raw": _maybe_null(_messy_amount(amount), p=0.03),
        "current_balance_raw": _messy_amount(balance),
        "currency_code": _maybe_null(random.choice(["USD", "usd", "EUR", "GBP", "INR", "Usd"]), p=0.04),
        "transaction_type": random.choice(["credit_card", "debit_card", "wallet_transfer", "CREDIT_CARD"]),
        "transaction_status": txn_status,
        "customer_id": customer_id,
        "first_name": _messy_name(first_name),
        "last_name": _maybe_null(_messy_name(last_name), p=0.04),
        "email_address": _maybe_null(_mask_email(customer["email"]), p=0.06),
        "phone_number": _maybe_null(_mask_phone(customer["phone"]), p=0.06),
        "billing_address": billing_address,
        "billing_zip": _maybe_null(billing_zip, p=0.05),
        "shipping_address": shipping_address,
        "shipping_zip": _maybe_null(shipping_zip, p=0.05),
        "card_bin": card_bin,
        "card_last4": card_last4,
        "card_network": _messy_name(card_network),
        "card_type": card_type,
        "merchant_id": dynamic_fake.swift(),
        "merchant_name": merchant_name,
        "merchant_category_code": mcc,
        "merchant_country": _messy_country(merchant_country),
        "ip_address": ip_address,
        "user_agent": user_agent,
        "device_id": device_id,
        "channel": channel,
        "entry_mode": entry_mode,
        "cvv_response_code": cvv,
        "avs_response": avs_response,
        "auth_response_code": auth_response,
        "three_d_secure_status": tds,
        "is_fraud": is_fraud,
        "attack_type": attack_type,
    }

# =========================================================
# 🚀 SMART PIPELINE (Batching + Hybrid Medallion)
# =========================================================
@functions_framework.http
def run_pipeline(request):
    request_json = request.get_json(silent=True) or {}
    total_rows = request_json.get("total_rows", 500)
    batch_size = request_json.get("batch_size", 10000)
    reset_data = request_json.get("reset_data", False)

    raw_table_id = "live-fraud-detection.fraud_data_lake.raw_transactions"
    real_time_now = datetime.now()

    print(f"🚀 Starting Pipeline: Generating {total_rows} rows in batches of {batch_size}. Reset: {reset_data}")

    current_write_mode = "WRITE_TRUNCATE" if reset_data else "WRITE_APPEND"
    rows_generated = 0

    while rows_generated < total_rows:
        current_batch_size = min(batch_size, total_rows - rows_generated)

        batch_records = [generate_ultimate_transaction(real_time_now) for _ in range(current_batch_size)]
        df = pd.DataFrame(batch_records).astype(str)

        job_config = bigquery.LoadJobConfig(write_disposition=current_write_mode)
        bq_client.load_table_from_dataframe(df, raw_table_id, job_config=job_config).result()

        rows_generated += current_batch_size
        print(f"✅ Batch inserted! Total so far: {rows_generated}/{total_rows}")

        current_write_mode = "WRITE_APPEND"

        del df
        del batch_records

    bad_ip_list = ", ".join(f'"{ip}"' for ip in BAD_IPS)
    drop_list   = ", ".join(f'"{a}"'  for a in DROP_HOUSES)
    bin_list    = ", ".join(f'"{b}"'  for b in TARGET_BINS)

    # =============================================================
    # 🔥 HYBRID LOGIC: reset_data=True => Full Rebuild
    #                 reset_data=False => Incremental Last 2 Days
    # 🔥 FIX: UNIX_SECONDS for RANGE (numeric required) & no DISTINCT
    # =============================================================

    if reset_data:
        print("🔥 Running FULL REBUILD (reset_data=True) ...")
        sql_query = f"""
        CREATE OR REPLACE TABLE `live-fraud-detection.fraud_data_lake.silver_transactions` AS
        WITH cleaned AS (
            SELECT
                transaction_id,
                INITCAP(TRIM(CONCAT(COALESCE(TRIM(first_name), ""), " ", COALESCE(TRIM(last_name), "")))) AS full_name,
                NULLIF(NULLIF(NULLIF(TRIM(LOWER(email_address)), "n/a"), "null"), "none") AS email_address,
                NULLIF(NULLIF(TRIM(phone_number), "n/a"), "null") AS phone_number,
                SAFE_CAST(REGEXP_REPLACE(CAST(amount_raw AS STRING), r'[^0-9.]', '') AS FLOAT64) AS amount_clean,
                SAFE_CAST(REGEXP_REPLACE(CAST(current_balance_raw AS STRING), r'[^0-9.]', '') AS FLOAT64) AS balance_clean,
                UPPER(TRIM(currency_code)) AS currency_code,
                LOWER(TRIM(transaction_type)) AS transaction_type,
                LOWER(TRIM(transaction_status)) AS transaction_status,
                CASE
                  WHEN UPPER(TRIM(merchant_country)) IN ('USA','US','UNITED STATES','U.S.A') THEN 'USA'
                  WHEN UPPER(TRIM(merchant_country)) IN ('UK','GB','UNITED KINGDOM') THEN 'UK'
                  WHEN UPPER(TRIM(merchant_country)) IN ('IND','IN','INDIA') THEN 'IND'
                  WHEN UPPER(TRIM(merchant_country)) IN ('CAN','CA','CANADA') THEN 'CAN'
                  WHEN UPPER(TRIM(merchant_country)) IN ('RU','RUS','RUSSIA') THEN 'RU'
                  WHEN UPPER(TRIM(merchant_country)) IN ('CH','CHE','SWITZERLAND') THEN 'CH'
                  ELSE UPPER(TRIM(merchant_country))
                END AS merchant_country,
                billing_zip, shipping_zip, billing_address, shipping_address,
                card_bin, card_last4, UPPER(TRIM(card_network)) AS card_network, card_type,
                merchant_id, merchant_name, merchant_category_code,
                ip_address, user_agent, device_id,
                LOWER(TRIM(channel)) AS channel, LOWER(TRIM(entry_mode)) AS entry_mode,
                UPPER(TRIM(cvv_response_code)) AS cvv_response_code,
                UPPER(TRIM(avs_response)) AS avs_response,
                TRIM(auth_response_code) AS auth_response_code,
                LOWER(TRIM(three_d_secure_status)) AS three_d_secure_status,
                COALESCE(
                  SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%m/%d/%Y %H:%M', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%d-%b-%Y %I:%M %p', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S', transaction_timestamp)
                ) AS transaction_timestamp,
                SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', account_creation_date) AS account_creation_date,
                customer_id, attack_type,
                SAFE_CAST(is_fraud AS INT64) AS is_fraud,
                SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', ingested_at) AS ingested_at
            FROM `live-fraud-detection.fraud_data_lake.raw_transactions`
        )
        SELECT * FROM cleaned
        WHERE amount_clean IS NOT NULL AND transaction_timestamp IS NOT NULL;

        -- 🔥 GOLD TABLE with FIXED window functions (UNIX_SECONDS, no DISTINCT)
        CREATE OR REPLACE TABLE `live-fraud-detection.fraud_data_lake.gold_fraud_mart` AS
        WITH base AS (
            SELECT *,
                TIMESTAMP_DIFF(transaction_timestamp, account_creation_date, MINUTE) AS account_age_minutes,
                EXTRACT(HOUR FROM transaction_timestamp) AS hour_of_day,
                EXTRACT(DAYOFWEEK FROM transaction_timestamp) AS day_of_week,
                SAFE_DIVIDE(amount_clean, NULLIF(balance_clean, 0)) AS amount_to_balance_ratio,
                LOG(GREATEST(amount_clean, 1)) AS log_amount,
                CAST(billing_zip != shipping_zip AS INT64) AS zip_mismatch,
                CAST(merchant_country IN ('RU','CH') AS INT64) AS is_high_risk_country,
                CAST(TIMESTAMP_DIFF(transaction_timestamp, account_creation_date, MINUTE) < 4320 AS INT64) AS is_fresh_account,

                -- 🔥 FIX: UNIX_SECONDS(transaction_timestamp) + Numeric RANGE (3600 = 1 hour, 86400 = 24 hours)
                IFNULL(
                    COUNT(transaction_id) OVER (
                        PARTITION BY customer_id 
                        ORDER BY UNIX_SECONDS(transaction_timestamp) 
                        RANGE BETWEEN 3600 PRECEDING AND CURRENT ROW
                    ) - 1, 0
                ) AS velocity_1h,
                IFNULL(
                    COUNT(transaction_id) OVER (
                        PARTITION BY customer_id 
                        ORDER BY UNIX_SECONDS(transaction_timestamp) 
                        RANGE BETWEEN 86400 PRECEDING AND CURRENT ROW
                    ) - 1, 0
                ) AS velocity_24h,
                TIMESTAMP_DIFF(
                    transaction_timestamp,
                    LAG(transaction_timestamp) OVER (PARTITION BY customer_id ORDER BY transaction_timestamp),
                    MINUTE
                ) AS time_since_last_txn,
                SAFE_DIVIDE(
                    amount_clean,
                    AVG(amount_clean) OVER (
                        PARTITION BY customer_id 
                        ORDER BY transaction_timestamp 
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) AS avg_amount_deviation,
                -- 🔥 FIX: removed DISTINCT, using COUNT(transaction_id) instead
                COUNT(transaction_id) OVER (
                    PARTITION BY device_id 
                    ORDER BY UNIX_SECONDS(transaction_timestamp) 
                    RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) - 1 AS device_risk_score
            FROM `live-fraud-detection.fraud_data_lake.silver_transactions`
        ),
        threat_flags AS (
            SELECT *,
                CASE WHEN user_agent = "python-requests/2.26.0" THEN 1 ELSE 0 END AS is_bot_agent,
                CASE WHEN ip_address IN ({bad_ip_list}) THEN 1 ELSE 0 END AS is_bad_ip,
                CASE WHEN shipping_address IN ({drop_list}) THEN 1 ELSE 0 END AS is_drop_house,
                CASE WHEN card_bin IN ({bin_list}) AND amount_clean < 5 THEN 1 ELSE 0 END AS is_bin_attack,
                CASE WHEN hour_of_day BETWEEN 0 AND 5 THEN 1 ELSE 0 END AS is_midnight_ghost
            FROM base
        )
        SELECT *,
            CASE
                WHEN (is_bot_agent + is_bad_ip + is_drop_house + is_bin_attack) > 0 THEN 'DEFCON 1: CRITICAL BLOCK'
                WHEN zip_mismatch = 1 OR is_midnight_ghost = 1 THEN 'DEFCON 2: REQUIRE OTP'
                WHEN amount_clean > 2500 THEN 'DEFCON 3: MANUAL REVIEW'
                ELSE 'DEFCON 4: CLEAR'
            END AS sql_baseline_flag
        FROM threat_flags;
        """
        bq_client.query(sql_query).result()
        print("✅ Full Rebuild Done.")

    else:
        print("🔥 Running INCREMENTAL (reset_data=False) – Last 2 days rebuild ...")
        # Silver table create if not exists
        silver_create_sql = f"""
        CREATE TABLE IF NOT EXISTS `live-fraud-detection.fraud_data_lake.silver_transactions` (
            transaction_id STRING,
            full_name STRING,
            email_address STRING,
            phone_number STRING,
            amount_clean FLOAT64,
            balance_clean FLOAT64,
            currency_code STRING,
            transaction_type STRING,
            transaction_status STRING,
            merchant_country STRING,
            billing_zip STRING,
            shipping_zip STRING,
            billing_address STRING,
            shipping_address STRING,
            card_bin STRING,
            card_last4 STRING,
            card_network STRING,
            card_type STRING,
            merchant_id STRING,
            merchant_name STRING,
            merchant_category_code STRING,
            ip_address STRING,
            user_agent STRING,
            device_id STRING,
            channel STRING,
            entry_mode STRING,
            cvv_response_code STRING,
            avs_response STRING,
            auth_response_code STRING,
            three_d_secure_status STRING,
            transaction_timestamp TIMESTAMP,
            account_creation_date TIMESTAMP,
            customer_id STRING,
            attack_type STRING,
            is_fraud INT64,
            ingested_at TIMESTAMP
        );
        """
        bq_client.query(silver_create_sql).result()

        silver_insert_sql = f"""
        INSERT INTO `live-fraud-detection.fraud_data_lake.silver_transactions`
        WITH cleaned AS (
            SELECT
                transaction_id,
                INITCAP(TRIM(CONCAT(COALESCE(TRIM(first_name), ""), " ", COALESCE(TRIM(last_name), "")))) AS full_name,
                NULLIF(NULLIF(NULLIF(TRIM(LOWER(email_address)), "n/a"), "null"), "none") AS email_address,
                NULLIF(NULLIF(TRIM(phone_number), "n/a"), "null") AS phone_number,
                SAFE_CAST(REGEXP_REPLACE(CAST(amount_raw AS STRING), r'[^0-9.]', '') AS FLOAT64) AS amount_clean,
                SAFE_CAST(REGEXP_REPLACE(CAST(current_balance_raw AS STRING), r'[^0-9.]', '') AS FLOAT64) AS balance_clean,
                UPPER(TRIM(currency_code)) AS currency_code,
                LOWER(TRIM(transaction_type)) AS transaction_type,
                LOWER(TRIM(transaction_status)) AS transaction_status,
                CASE
                  WHEN UPPER(TRIM(merchant_country)) IN ('USA','US','UNITED STATES','U.S.A') THEN 'USA'
                  WHEN UPPER(TRIM(merchant_country)) IN ('UK','GB','UNITED KINGDOM') THEN 'UK'
                  WHEN UPPER(TRIM(merchant_country)) IN ('IND','IN','INDIA') THEN 'IND'
                  WHEN UPPER(TRIM(merchant_country)) IN ('CAN','CA','CANADA') THEN 'CAN'
                  WHEN UPPER(TRIM(merchant_country)) IN ('RU','RUS','RUSSIA') THEN 'RU'
                  WHEN UPPER(TRIM(merchant_country)) IN ('CH','CHE','SWITZERLAND') THEN 'CH'
                  ELSE UPPER(TRIM(merchant_country))
                END AS merchant_country,
                billing_zip, shipping_zip, billing_address, shipping_address,
                card_bin, card_last4, UPPER(TRIM(card_network)) AS card_network, card_type,
                merchant_id, merchant_name, merchant_category_code,
                ip_address, user_agent, device_id,
                LOWER(TRIM(channel)) AS channel, LOWER(TRIM(entry_mode)) AS entry_mode,
                UPPER(TRIM(cvv_response_code)) AS cvv_response_code,
                UPPER(TRIM(avs_response)) AS avs_response,
                TRIM(auth_response_code) AS auth_response_code,
                LOWER(TRIM(three_d_secure_status)) AS three_d_secure_status,
                COALESCE(
                  SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%m/%d/%Y %H:%M', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%d-%b-%Y %I:%M %p', transaction_timestamp),
                  SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S', transaction_timestamp)
                ) AS transaction_timestamp,
                SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', account_creation_date) AS account_creation_date,
                customer_id, attack_type,
                SAFE_CAST(is_fraud AS INT64) AS is_fraud,
                SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', ingested_at) AS ingested_at
            FROM `live-fraud-detection.fraud_data_lake.raw_transactions`
            WHERE amount_raw IS NOT NULL AND transaction_timestamp IS NOT NULL
        )
        SELECT * FROM cleaned
        WHERE ingested_at > (SELECT COALESCE(MAX(ingested_at), TIMESTAMP('1900-01-01')) FROM `live-fraud-detection.fraud_data_lake.silver_transactions`);
        """
        bq_client.query(silver_insert_sql).result()
        print("✅ Silver Incremental Insert Done.")

        # Gold table create if not exists
        gold_create_sql = """
        CREATE TABLE IF NOT EXISTS `live-fraud-detection.fraud_data_lake.gold_fraud_mart` (
            transaction_id STRING,
            full_name STRING,
            email_address STRING,
            phone_number STRING,
            amount_clean FLOAT64,
            balance_clean FLOAT64,
            currency_code STRING,
            transaction_type STRING,
            transaction_status STRING,
            merchant_country STRING,
            billing_zip STRING,
            shipping_zip STRING,
            billing_address STRING,
            shipping_address STRING,
            card_bin STRING,
            card_last4 STRING,
            card_network STRING,
            card_type STRING,
            merchant_id STRING,
            merchant_name STRING,
            merchant_category_code STRING,
            ip_address STRING,
            user_agent STRING,
            device_id STRING,
            channel STRING,
            entry_mode STRING,
            cvv_response_code STRING,
            avs_response STRING,
            auth_response_code STRING,
            three_d_secure_status STRING,
            transaction_timestamp TIMESTAMP,
            account_creation_date TIMESTAMP,
            customer_id STRING,
            attack_type STRING,
            is_fraud INT64,
            ingested_at TIMESTAMP,
            account_age_minutes INT64,
            hour_of_day INT64,
            day_of_week INT64,
            amount_to_balance_ratio FLOAT64,
            log_amount FLOAT64,
            zip_mismatch INT64,
            is_high_risk_country INT64,
            is_fresh_account INT64,
            velocity_1h INT64,
            velocity_24h INT64,
            time_since_last_txn INT64,
            avg_amount_deviation FLOAT64,
            device_risk_score INT64,
            is_bot_agent INT64,
            is_bad_ip INT64,
            is_drop_house INT64,
            is_bin_attack INT64,
            is_midnight_ghost INT64,
            sql_baseline_flag STRING
        );
        """
        bq_client.query(gold_create_sql).result()

        # 🔥 Gold Incremental with FIXED window functions (UNIX_SECONDS, no DISTINCT)
        gold_insert_sql = f"""
        INSERT INTO `live-fraud-detection.fraud_data_lake.gold_fraud_mart`
        WITH context AS (
            SELECT * FROM `live-fraud-detection.fraud_data_lake.silver_transactions`
            WHERE ingested_at > (SELECT COALESCE(TIMESTAMP_SUB(MAX(ingested_at), INTERVAL 2 DAY), TIMESTAMP('1900-01-01')) FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`)
        ),
        new_rows AS (
            SELECT * FROM `live-fraud-detection.fraud_data_lake.silver_transactions`
            WHERE ingested_at > (SELECT COALESCE(MAX(ingested_at), TIMESTAMP('1900-01-01')) FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`)
        ),
        combined AS (
            SELECT * FROM context
            UNION ALL
            SELECT * FROM new_rows
        ),
        base AS (
            SELECT *,
                TIMESTAMP_DIFF(transaction_timestamp, account_creation_date, MINUTE) AS account_age_minutes,
                EXTRACT(HOUR FROM transaction_timestamp) AS hour_of_day,
                EXTRACT(DAYOFWEEK FROM transaction_timestamp) AS day_of_week,
                SAFE_DIVIDE(amount_clean, NULLIF(balance_clean, 0)) AS amount_to_balance_ratio,
                LOG(GREATEST(amount_clean, 1)) AS log_amount,
                CAST(billing_zip != shipping_zip AS INT64) AS zip_mismatch,
                CAST(merchant_country IN ('RU','CH') AS INT64) AS is_high_risk_country,
                CAST(TIMESTAMP_DIFF(transaction_timestamp, account_creation_date, MINUTE) < 4320 AS INT64) AS is_fresh_account,

                IFNULL(
                    COUNT(transaction_id) OVER (
                        PARTITION BY customer_id 
                        ORDER BY UNIX_SECONDS(transaction_timestamp) 
                        RANGE BETWEEN 3600 PRECEDING AND CURRENT ROW
                    ) - 1, 0
                ) AS velocity_1h,
                IFNULL(
                    COUNT(transaction_id) OVER (
                        PARTITION BY customer_id 
                        ORDER BY UNIX_SECONDS(transaction_timestamp) 
                        RANGE BETWEEN 86400 PRECEDING AND CURRENT ROW
                    ) - 1, 0
                ) AS velocity_24h,
                TIMESTAMP_DIFF(
                    transaction_timestamp,
                    LAG(transaction_timestamp) OVER (PARTITION BY customer_id ORDER BY transaction_timestamp),
                    MINUTE
                ) AS time_since_last_txn,
                SAFE_DIVIDE(
                    amount_clean,
                    AVG(amount_clean) OVER (
                        PARTITION BY customer_id 
                        ORDER BY transaction_timestamp 
                        ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                    )
                ) AS avg_amount_deviation,
                -- 🔥 FIX: removed DISTINCT
                COUNT(transaction_id) OVER (
                    PARTITION BY device_id 
                    ORDER BY UNIX_SECONDS(transaction_timestamp) 
                    RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) - 1 AS device_risk_score
            FROM combined
        ),
        threat_flags AS (
            SELECT *,
                CASE WHEN user_agent = "python-requests/2.26.0" THEN 1 ELSE 0 END AS is_bot_agent,
                CASE WHEN ip_address IN ({bad_ip_list}) THEN 1 ELSE 0 END AS is_bad_ip,
                CASE WHEN shipping_address IN ({drop_list}) THEN 1 ELSE 0 END AS is_drop_house,
                CASE WHEN card_bin IN ({bin_list}) AND amount_clean < 5 THEN 1 ELSE 0 END AS is_bin_attack,
                CASE WHEN hour_of_day BETWEEN 0 AND 5 THEN 1 ELSE 0 END AS is_midnight_ghost
            FROM base
        )
        SELECT *,
            CASE
                WHEN (is_bot_agent + is_bad_ip + is_drop_house + is_bin_attack) > 0 THEN 'DEFCON 1: CRITICAL BLOCK'
                WHEN zip_mismatch = 1 OR is_midnight_ghost = 1 THEN 'DEFCON 2: REQUIRE OTP'
                WHEN amount_clean > 2500 THEN 'DEFCON 3: MANUAL REVIEW'
                ELSE 'DEFCON 4: CLEAR'
            END AS sql_baseline_flag
        FROM threat_flags
        WHERE ingested_at > (SELECT COALESCE(MAX(ingested_at), TIMESTAMP('1900-01-01')) FROM `live-fraud-detection.fraud_data_lake.gold_fraud_mart`);
        """
        bq_client.query(gold_insert_sql).result()
        print("✅ Gold Incremental Insert Done.")

    print(f"✨ Success! Medallion Layer Updated with {rows_generated} new rows.")
    return f"Pipeline Executed Successfully. Generated {rows_generated} rows.", 200
    
