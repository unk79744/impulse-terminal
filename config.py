import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing!")

SUBSCRIPTION_PRICE = 6.0
SUBSCRIPTION_DAYS = 30
TRIAL_DAYS = 7
REFERRAL_TRIAL_DAYS = 9
REFERRER_BONUS_DAYS = 2

DEFAULT_SETTINGS = {
    'interval': 5,
    'threshold': 3.0,
    'signal_type': 'BOTH',
    'exchanges': '["binance", "bybit", "mexc", "okx", "kucoin", "bitget", "gate", "bingx"]',
    'filter_24h_enabled': False,
    'min_24h_growth': 5.0,
    'filter_btc_enabled': True,
    'rsi_enabled': False,
    'rsi_timeframe': '5m',
    'rsi_period': 14,
    'rsi_pump_limit': 70,
    'rsi_dump_limit': 30,
    'show_signal_strength': True,
    'show_volume_anomaly': True,
    'show_volatility': True,
    'show_sr_levels': True,
    'show_funding': True,
    'show_oi_change': True,
    'show_hashtag': True,
    'show_vol24': True,
    'subscription_end_date': None,
    'referrer_id': 0,
    'sleep_enabled': False,
    'sleep_from': 0,
    'sleep_to': 8,
    'is_paused': False
}

DB_NAME = "database.db"