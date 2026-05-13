import os
import json
import http.client
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from nselib import capital_market

# --- SYSTEM FIX ---
# Prevents yfinance from flooding requests and erroring on timezone lookups
yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
CSV_NAME = "ind_nifty500list.csv"

def send_msg(text):
    if not MY_TOKEN or not MY_CHAT_ID: 
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
        payload = json.dumps({
            "chat_id": str(MY_CHAT_ID).strip(),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN.strip()}/sendMessage", payload, headers)
        conn.get
