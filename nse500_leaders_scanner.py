import os
import yfinance as yf
import numpy as np
import pandas as pd
import datetime
import time
import requests
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_CSV_PATH = os.path.join(SCRIPT_DIR, "ind_nifty500list.csv")

# Determine parent and Obsidian dir (works locally and on GitHub VM)
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
OBSIDIAN_DIR = os.path.join(PARENT_DIR, "Obsidian-Journal", "Ticker-Research")
if not os.path.exists(os.path.join(PARENT_DIR, "Obsidian-Journal")):
    OBSIDIAN_DIR = os.path.join(SCRIPT_DIR, "Obsidian-Journal", "Ticker-Research")
os.makedirs(OBSIDIAN_DIR, exist_ok=True)

# Custom dotenv loader to avoid package dependencies
def load_custom_dotenv(dotenv_path):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

# Load env variables (only needed for local running; GitHub Actions injects env directly)
load_custom_dotenv(os.path.join(PARENT_DIR, ".env"))
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    if not TOKEN or not CHAT_ID:
        print("[WARNING] Telegram configurations not found in env. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            print(f"[WARNING] Telegram returned status code {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram alert: {e}")

def calculate_gbm_simulation(df, price, days=5, simulations=10000):
    """Calculates forecasting metrics using Geometric Brownian Motion (GBM) Monte Carlo"""
    log_returns = np.log(df / df.shift(1)).dropna()
    
    # Use the 60-day window
    recent_rets = log_returns.iloc[-60:]
    if len(recent_rets) < 15:
        recent_rets = log_returns
        
    vol = recent_rets.std()
    drift = recent_rets.mean()
    
    # GBM drift formulation
    variance_drift = drift - 0.5 * (vol ** 2)
    
    # Generate random paths
    Z = np.random.normal(0, 1, simulations)
    final_prices = price * np.exp(variance_drift * days + vol * np.sqrt(days) * Z)
    
    confidence = (np.sum(final_prices > price) / simulations) * 100
    target_p = np.mean(final_prices)
    
    return confidence, target_p, vol * 100

def run_nse500_scanner():
    print(f"\n[INFO] [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting NSE 500 Leaders Scan...")
    
    if not os.path.exists(NIFTY500_CSV_PATH):
        print(f"[ERROR] Nifty 500 CSV not found at: {NIFTY500_CSV_PATH}")
        return
        
    # Read tickers from Nifty 500 list
    try:
        df_list = pd.read_csv(NIFTY500_CSV_PATH)
        symbols = df_list['Symbol'].dropna().tolist()
        tickers = [f"{sym.strip()}.NS" for sym in symbols if isinstance(sym, str) and sym.strip()]
    except Exception as e:
        print(f"[ERROR] Error reading Nifty 500 CSV: {e}")
        return
        
    print(f"[INFO] Loaded {len(tickers)} symbols from CSV. Preparing data download...")
    
    # Add benchmark
    tickers_to_fetch = tickers + ["^NSEI"]
    
    # Batch download to save time (changed from 60d to 6mo to ensure at least 60 trading days)
    data = yf.download(tickers_to_fetch, period="6mo", interval="1d", progress=False, auto_adjust=True)
    
    nifty_close = data['Close']['^NSEI'].dropna()
    if len(nifty_close) < 60:
        print(f"[ERROR] Benchmark index ^NSEI has insufficient data ({len(nifty_close)} days).")
        return
        
    nifty_perf_60d = (nifty_close.iloc[-1] - nifty_close.iloc[-60]) / nifty_close.iloc[-60]
    
    results = []
    
    for ticker in tickers:
        try:
            # Safely extract close series
            if ticker not in data['Close']:
                continue
            df = data['Close'][ticker].dropna()
            if len(df) < 60: # Ensure we have at least 60 trading days of data
                continue
                
            price = df.iloc[-1]
            perf_60d = (price - df.iloc[-60]) / df.iloc[-60]
            relative_perf = perf_60d - nifty_perf_60d
            
            # Execute GBM Monte Carlo
            confidence, target_p, vol_pct = calculate_gbm_simulation(df, price)
            
            # Leader Criteria: Confidence >= 60% and Relative Performance (Alpha) > 0
            if confidence >= 60.0 and relative_perf > 0:
                results.append({
                    "ticker": ticker,
                    "price": round(price, 2),
                    "confidence": round(confidence, 1),
                    "target": round(target_p, 2),
                    "volatility": round(vol_pct, 2),
                    "relative_perf": round(relative_perf * 100, 2)
                })
        except Exception:
            continue # Silently skip errors for batch processing stability
            
    # Sort by Confidence (descending), then Relative Performance (descending)
    sorted_leaders = sorted(results, key=lambda x: (-x["confidence"], -x["relative_perf"]))
    top_20 = sorted_leaders[:20]
    
    # Save report to Obsidian
    report_file = os.path.join(OBSIDIAN_DIR, "NSE500-Leaders.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# 🏆 Top 20 NSE 500 Leaders Report\n")
        f.write(f"**Generated:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n")
        f.write(f"This report highlights the top 20 strongest leaders in the NSE 500 universe. ")
        f.write(f"Selection criteria requires a **GBM upward confidence $\ge 60\%$** and **outperformance against the Nifty 50 benchmark** over the last 60 trading days.\n\n")
        
        f.write("### 📋 Leaderboard Grid\n")
        f.write("| Rank | Ticker | Price | Upward Confidence | Target (5D) | Volatility (60D) | 60D Alpha vs Nifty |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        
        for idx, r in enumerate(top_20, 1):
            alpha_style = f"+{r['relative_perf']}%" if r['relative_perf'] >= 0 else f"{r['relative_perf']}%"
            f.write(f"| #{idx} | **{r['ticker'].replace('.NS', '')}** | ₹{r['price']} | **{r['confidence']}%** | ₹{r['target']} | {r['volatility']}% | {alpha_style} |\n")
            
        f.write("\n\n*Note: Calculations utilize a 10,000-run Geometric Brownian Motion (GBM) Monte Carlo simulation aligned to a 60-day historical drift and volatility window.*")
        
    print(f"[SUCCESS] Obsidian report compiled and saved: {report_file}")
    
    # Compile Telegram Message
    tele_msg = f"🏆 *NSE 500 Top 20 Leaders:* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
    if top_20:
        for idx, l in enumerate(top_20, 1):
            alpha_sign = "+" if l['relative_perf'] >= 0 else ""
            tele_msg += f"#{idx} *{l['ticker'].replace('.NS', '')}*: Price ₹{l['price']} | Conf {l['confidence']}% | Alpha {alpha_sign}{l['relative_perf']}%\n"
    else:
        tele_msg += "No leaders met the criteria this week."
        
    tele_msg += "\n👉 Check Obsidian: `NSE500-Leaders.md` for full metrics."
    send_telegram_message(tele_msg)
    print("[SUCCESS] Dispatch completed via Telegram.")

def scheduler_loop(hour=18, minute=30):
    print(f"[INFO] Background daemon started. Scheduled to scan NSE 500 every Friday at {hour:02}:{minute:02} IST.")
    while True:
        now = datetime.datetime.now()
        # Find next Friday (weekday 4)
        days_ahead = (4 - now.weekday()) % 7
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if days_ahead == 0 and now >= target:
            # Already passed target time on Friday, schedule for next Friday
            days_ahead = 7
            
        target += datetime.timedelta(days=days_ahead)
        delta = (target - now).total_seconds()
        
        print(f"[INFO] Sleeping for {delta/3600:.2f} hours (until Friday, {target.strftime('%Y-%m-%d %H:%M:%S')} IST)")
        
        # Sleep in intervals of 30 minutes to remain responsive to interruptions
        sleep_interval = 1800
        while delta > 0:
            time.sleep(min(delta, sleep_interval))
            now = datetime.datetime.now()
            delta = (target - now).total_seconds()
            
        try:
            run_nse500_scanner()
        except Exception as e:
            print(f"[ERROR] Error during scheduled execution: {e}")
        # Give it a short sleep to avoid double-triggering
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NSE 500 Leaders Scanner")
    parser.add_argument("--scheduler", action="store_true", help="Run in continuous background daemon scheduler mode")
    args = parser.parse_args()
    
    if args.scheduler:
        scheduler_loop(hour=18, minute=30)
    else:
        run_nse500_scanner()
