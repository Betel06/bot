import os

ATIVOS = [
    {"symbol": "COLLECTUSDT", "timeframe": "3m"},
    {"symbol": "BTWUSDT", "timeframe": "15m"},
]

BB_LENGTH = 20
BB_MULT = 2.0
VOL_MULTIPLIER = 1.2
CHECK_INTERVAL_SECONDS = 15

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
