import os
import sys
import math
import yfinance as yf
import numpy as np
import pandas as pd
import datetime
import time
import requests
import argparse

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NIFTY500_CSV_PATH = os.path.join(SCRIPT_DIR, "ind_nifty500list.csv")

PARENT_DIR = os.path.dirname(SCRIPT_DIR)
OBSIDIAN_DIR = os.path.join(PARENT_DIR, "Obsidian-Journal", "Ticker-Research")
if not os.path.exists(os.path.join(PARENT_DIR, "Obsidian-Journal")):
    OBSIDIAN_DIR = os.path.join(SCRIPT_DIR, "Obsidian-Journal", "Ticker-Research")
os.makedirs(OBSIDIAN_DIR, exist_ok=True)

# Custom dotenv loader
def load_custom_dotenv(dotenv_path):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip("'").strip('"')
                    os.environ[key.strip()] = val

load_custom_dotenv(os.path.join(PARENT_DIR, ".env"))
load_custom_dotenv(os.path.join(SCRIPT_DIR, ".env"))
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

def norm_cdf(x):
    """Standard Normal Cumulative Distribution Function"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def calculate_gbm_metrics(df_series, price, days=5):
    """
    Computes GBM metrics using exact analytical probability and expected drift.
    Deterministic, zero noise, high performance.
    """
    log_rets = np.log(df_series / df_series.shift(1)).dropna()
    recent = log_rets.iloc[-60:] if len(log_rets) >= 60 else log_rets
    if len(recent) < 10:
        return 50.0, price, 0.0
        
    vol = float(recent.std())
    drift = float(recent.mean())
    
    if vol <= 1e-6:
        return 50.0, price, 0.0
        
    variance_drift = drift - 0.5 * (vol ** 2)
    z = (variance_drift * days) / (vol * math.sqrt(days))
    confidence = norm_cdf(z) * 100.0
    target_p = price * math.exp(drift * days)
    
    return confidence, target_p, vol * 100.0

def safe_batch_download(tickers, period="1y", interval="1d"):
    """
    Fast batch download for NSE 500 universe with automated forward/backfill.
    """
    data = yf.download(tickers, period=period, interval=interval, progress=False, auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex) and 'Close' in data:
        downloaded = set(data['Close'].columns)
        missing = [t for t in tickers if t not in downloaded or data['Close'][t].dropna().empty]
        if missing and len(missing) < 30:
            print(f"[INFO] Batch download skipped {len(missing)} tickers. Running fallback downloads...")
            for t in missing:
                try:
                    sdf = yf.download(t, period=period, interval=interval, progress=False, auto_adjust=True)
                    if not sdf.empty:
                        if isinstance(sdf.columns, pd.MultiIndex):
                            sdf.columns = sdf.columns.get_level_values(0)
                        if 'Close' in sdf and not sdf['Close'].dropna().empty:
                            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                                if col in sdf:
                                    data[(col, t)] = sdf[col]
                except Exception:
                    pass
    return data

def run_nse500_scanner(scan_target="all"):
    """
    Executes 4 distinct weekend market leaders & momentum scans:
      1. Weekly Leaders (5D) -> NSE500-Leaders-Weekly.md & NSE500-Leaders.md
      2. Monthly Leaders (20D) -> NSE500-Leaders-Monthly.md
      3. 3-Month Top Gainers (63D) -> NSE500-Leaders-3Month.md
      4. 52-Week High Leaders (252D) -> NSE500-Leaders-52WeekHigh.md
    """
    print(f"\n[INFO] [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting KRONOS NSE 500 Leaders & Momentum Engine (Target: {scan_target.upper()})...")
    
    if not os.path.exists(NIFTY500_CSV_PATH):
        print(f"[ERROR] Nifty 500 CSV not found at: {NIFTY500_CSV_PATH}")
        return
        
    try:
        df_list = pd.read_csv(NIFTY500_CSV_PATH)
        symbols = df_list['Symbol'].dropna().tolist()
        tickers = [f"{sym.strip()}.NS" for sym in symbols if isinstance(sym, str) and sym.strip()]
    except Exception as e:
        print(f"[ERROR] Error reading Nifty 500 CSV: {e}")
        return
        
    print(f"[INFO] Loaded {len(tickers)} symbols from universe registry. Fetching 1-Year OHLCV data...")
    tickers_to_fetch = tickers + ["^NSEI"]
    
    raw_data = safe_batch_download(tickers_to_fetch, period="1y", interval="1d")
    data = raw_data.ffill().bfill()
    
    close_df = data['Close']
    high_df = data['High'] if 'High' in data else close_df
    low_df = data['Low'] if 'Low' in data else close_df
    
    if '^NSEI' not in close_df or close_df['^NSEI'].dropna().empty:
        print("[ERROR] Benchmark index ^NSEI missing from price data.")
        return
        
    nifty_close = close_df['^NSEI'].dropna()
    total_bars = len(nifty_close)
    gen_time_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # -------------------------------------------------------------------------
    # 1. WEEKLY LEADERS SCAN (5 Trading Days Lookback & Forecast)
    # -------------------------------------------------------------------------
    if scan_target in ["all", "weekly"]:
        print("\n[INFO] Running Scan 1/4: Top 20 Weekly Leaders (5D)...")
        days = 5
        nifty_perf = (nifty_close.iloc[-1] - nifty_close.iloc[-days]) / nifty_close.iloc[-days]
        weekly_res = []
        
        for ticker in tickers:
            if ticker not in close_df: continue
            s = close_df[ticker].dropna()
            if len(s) < 60: continue
            price = float(s.iloc[-1])
            perf_stk = (price - float(s.iloc[-days])) / float(s.iloc[-days])
            alpha = perf_stk - nifty_perf
            conf, target_p, vol_pct = calculate_gbm_metrics(s, price, days=days)
            if conf >= 60.0 and alpha > 0:
                weekly_res.append({
                    "ticker": ticker.replace(".NS", ""),
                    "price": round(price, 2),
                    "return_pct": round(perf_stk * 100, 2),
                    "alpha": round(alpha * 100, 2),
                    "confidence": round(conf, 1),
                    "target": round(target_p, 2),
                    "volatility": round(vol_pct, 2)
                })
                
        weekly_top = sorted(weekly_res, key=lambda x: (-x["confidence"], -x["alpha"]))[:20]
        
        # Save both NSE500-Leaders-Weekly.md and NSE500-Leaders.md
        for filename in ["NSE500-Leaders-Weekly.md", "NSE500-Leaders.md"]:
            report_file = os.path.join(OBSIDIAN_DIR, filename)
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(f"# 🏆 Top 20 NSE 500 Leaders Report (Weekly - 5D)\n")
                f.write(f"**Generated:** `{gen_time_str}`\n\n")
                f.write("This report highlights the top 20 strongest leaders in the NSE 500 universe over a **5-day weekly horizon**. ")
                f.write(f"Selection criteria requires a **GBM upward confidence $\\ge 60\\%$** and **positive alpha against Nifty 50** ({nifty_perf*100:+.2f}% benchmark return).\n\n")
                f.write("### 📋 Leaderboard Grid\n")
                f.write("| Rank | Ticker | Price | Upward Confidence | Target (5D) | Volatility (60D) | 5D Alpha vs Nifty |\n")
                f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
                for idx, r in enumerate(weekly_top, 1):
                    alpha_str = f"+{r['alpha']}%" if r['alpha'] >= 0 else f"{r['alpha']}%"
                    f.write(f"| #{idx} | **{r['ticker']}** | ₹{r['price']} | **{r['confidence']}%** | ₹{r['target']} | {r['volatility']}% | {alpha_str} |\n")
                f.write("\n\n*Note: Calculations utilize a Geometric Brownian Motion (GBM) model aligned to 60-day historical volatility and drift.*")
        print(f"[SUCCESS] Weekly report written to: NSE500-Leaders-Weekly.md")
        
        # Telegram dispatch
        tele_msg = f"🏆 *NSE 500 Top 20 Leaders (Weekly - 5D):* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
        for idx, l in enumerate(weekly_top[:10], 1):
            tele_msg += f"#{idx} *{l['ticker']}*: Price ₹{l['price']} | Conf {l['confidence']}% | Target ₹{l['target']} | Alpha +{l['alpha']}%\n"
        tele_msg += f"\n👉 Full 20 Scrips saved in Obsidian: `NSE500-Leaders-Weekly.md`"
        send_telegram_message(tele_msg)

    # -------------------------------------------------------------------------
    # 2. MONTHLY LEADERS SCAN (20 Trading Days Lookback & Forecast)
    # -------------------------------------------------------------------------
    if scan_target in ["all", "monthly"]:
        print("\n[INFO] Running Scan 2/4: Top 20 Monthly Leaders (20D)...")
        days = 20
        nifty_perf = (nifty_close.iloc[-1] - nifty_close.iloc[-days]) / nifty_close.iloc[-days]
        monthly_res = []
        
        for ticker in tickers:
            if ticker not in close_df: continue
            s = close_df[ticker].dropna()
            if len(s) < 60: continue
            price = float(s.iloc[-1])
            perf_stk = (price - float(s.iloc[-days])) / float(s.iloc[-days])
            alpha = perf_stk - nifty_perf
            conf, target_p, vol_pct = calculate_gbm_metrics(s, price, days=days)
            if conf >= 60.0 and alpha > 0:
                monthly_res.append({
                    "ticker": ticker.replace(".NS", ""),
                    "price": round(price, 2),
                    "return_pct": round(perf_stk * 100, 2),
                    "alpha": round(alpha * 100, 2),
                    "confidence": round(conf, 1),
                    "target": round(target_p, 2),
                    "volatility": round(vol_pct, 2)
                })
                
        monthly_top = sorted(monthly_res, key=lambda x: (-x["confidence"], -x["alpha"]))[:20]
        
        report_file = os.path.join(OBSIDIAN_DIR, "NSE500-Leaders-Monthly.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# 🏆 Top 20 NSE 500 Leaders Report (Monthly - 20D)\n")
            f.write(f"**Generated:** `{gen_time_str}`\n\n")
            f.write("This report highlights the top 20 strongest momentum leaders in the NSE 500 universe over a **20-day monthly horizon**. ")
            f.write(f"Selection criteria requires a **GBM upward confidence $\\ge 60\\%$** and **positive alpha against Nifty 50** ({nifty_perf*100:+.2f}% benchmark return).\n\n")
            f.write("### 📋 Leaderboard Grid\n")
            f.write("| Rank | Ticker | Price | Upward Confidence | Target (20D) | Volatility (60D) | 20D Alpha vs Nifty |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            for idx, r in enumerate(monthly_top, 1):
                alpha_str = f"+{r['alpha']}%" if r['alpha'] >= 0 else f"{r['alpha']}%"
                f.write(f"| #{idx} | **{r['ticker']}** | ₹{r['price']} | **{r['confidence']}%** | ₹{r['target']} | {r['volatility']}% | {alpha_str} |\n")
            f.write("\n\n*Note: Calculations utilize a Geometric Brownian Motion (GBM) model aligned to 60-day historical volatility and drift.*")
        print(f"[SUCCESS] Monthly report written to: NSE500-Leaders-Monthly.md")
        
        tele_msg = f"🏆 *NSE 500 Top 20 Leaders (Monthly - 20D):* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
        for idx, l in enumerate(monthly_top[:10], 1):
            tele_msg += f"#{idx} *{l['ticker']}*: Price ₹{l['price']} | Conf {l['confidence']}% | Target ₹{l['target']} | Alpha +{l['alpha']}%\n"
        tele_msg += f"\n👉 Full 20 Scrips saved in Obsidian: `NSE500-Leaders-Monthly.md`"
        send_telegram_message(tele_msg)

    # -------------------------------------------------------------------------
    # 3. 3-MONTH TOP GAINERS SCAN (63 Trading Days / Quarterly Horizon)
    # -------------------------------------------------------------------------
    if scan_target in ["all", "3month", "quarterly"]:
        print("\n[INFO] Running Scan 3/4: Top 20 3-Month Gainers (Quarterly - 63D)...")
        days = min(63, total_bars - 1)
        nifty_perf = (nifty_close.iloc[-1] - nifty_close.iloc[-days]) / nifty_close.iloc[-days]
        three_m_res = []
        
        for ticker in tickers:
            if ticker not in close_df: continue
            s = close_df[ticker].dropna()
            if len(s) < days: continue
            price = float(s.iloc[-1])
            perf_stk = (price - float(s.iloc[-days])) / float(s.iloc[-days])
            alpha = perf_stk - nifty_perf
            conf, target_p, vol_pct = calculate_gbm_metrics(s, price, days=20)
            if perf_stk > 0 and alpha > 0:
                three_m_res.append({
                    "ticker": ticker.replace(".NS", ""),
                    "price": round(price, 2),
                    "return_3m": round(perf_stk * 100, 2),
                    "alpha_3m": round(alpha * 100, 2),
                    "confidence": round(conf, 1),
                    "target_20d": round(target_p, 2),
                    "volatility": round(vol_pct, 2)
                })
                
        three_m_top = sorted(three_m_res, key=lambda x: (-x["return_3m"], -x["alpha_3m"]))[:20]
        
        report_file = os.path.join(OBSIDIAN_DIR, "NSE500-Leaders-3Month.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# 🚀 Top 20 NSE 500 3-Month Gainers (Quarterly - 63D)\n")
            f.write(f"**Generated:** `{gen_time_str}`\n\n")
            f.write("This report highlights the top 20 highest-performing stocks in the NSE 500 universe over a **3-month (63 trading days) quarterly horizon**. ")
            f.write(f"Ranked by absolute return and alpha outperformance against the Nifty 50 benchmark ({nifty_perf*100:+.2f}% 3-month return).\n\n")
            f.write("### 📋 3-Month Leaderboard Grid\n")
            f.write("| Rank | Ticker | Price | 3M Return | 3M Alpha vs Nifty | Upward Confidence | Target (20D) | Volatility (60D) |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
            for idx, r in enumerate(three_m_top, 1):
                alpha_str = f"+{r['alpha_3m']}%" if r['alpha_3m'] >= 0 else f"{r['alpha_3m']}%"
                f.write(f"| #{idx} | **{r['ticker']}** | ₹{r['price']} | **+{r['return_3m']}%** | {alpha_str} | {r['confidence']}% | ₹{r['target_20d']} | {r['volatility']}% |\n")
            f.write("\n\n*Note: Focuses on established medium-term trend strength and institutional momentum persistence over a rolling 63-day window.*")
        print(f"[SUCCESS] 3-Month report written to: NSE500-Leaders-3Month.md")
        
        tele_msg = f"🚀 *NSE 500 Top 20 3-Month Gainers:* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
        for idx, l in enumerate(three_m_top[:10], 1):
            tele_msg += f"#{idx} *{l['ticker']}*: Price ₹{l['price']} | 3M Return +{l['return_3m']}% | Alpha +{l['alpha_3m']}%\n"
        tele_msg += f"\n👉 Full 20 Scrips saved in Obsidian: `NSE500-Leaders-3Month.md`"
        send_telegram_message(tele_msg)

    # -------------------------------------------------------------------------
    # 4. 52-WEEK HIGH LEADERS SCAN (Proximity <= 5% & Strong 1Y Alpha)
    # -------------------------------------------------------------------------
    if scan_target in ["all", "52week_high", "52w"]:
        print("\n[INFO] Running Scan 4/4: Top 20 52-Week High Breakouts & Proximity Leaders...")
        nifty_1y_perf = (nifty_close.iloc[-1] - nifty_close.iloc[0]) / nifty_close.iloc[0]
        high_res = []
        
        for ticker in tickers:
            if ticker not in close_df: continue
            s_close = close_df[ticker].dropna()
            if len(s_close) < 120: continue
            s_high = high_df[ticker].dropna() if ticker in high_df else s_close
            
            price = float(s_close.iloc[-1])
            h52 = float(s_high.max())
            dist_to_high = ((price - h52) / h52) * 100.0
            
            p_start = float(s_close.iloc[0])
            perf_1y = ((price - p_start) / p_start) * 100.0
            alpha_1y = perf_1y - (nifty_1y_perf * 100.0)
            
            conf, target_p, vol_pct = calculate_gbm_metrics(s_close, price, days=20)
            
            # Criteria: Within 5.0% of 52W High and positive 1-Year Alpha
            if dist_to_high >= -5.0 and alpha_1y > 0:
                high_res.append({
                    "ticker": ticker.replace(".NS", ""),
                    "price": round(price, 2),
                    "high_52w": round(h52, 2),
                    "dist_to_high": round(dist_to_high, 2),
                    "return_1y": round(perf_1y, 2),
                    "alpha_1y": round(alpha_1y, 2),
                    "confidence": round(conf, 1),
                    "target_20d": round(target_p, 2),
                    "volatility": round(vol_pct, 2)
                })
                
        # Sort by proximity to 52W High (closest to 0.0% / new high), then 1-Year Alpha
        high_top = sorted(high_res, key=lambda x: (-x["dist_to_high"], -x["alpha_1y"]))[:20]
        
        report_file = os.path.join(OBSIDIAN_DIR, "NSE500-Leaders-52WeekHigh.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# 🏔️ Top 20 NSE 500 52-Week High Breakouts & Momentum Report\n")
            f.write(f"**Generated:** `{gen_time_str}`\n\n")
            f.write("This report highlights the top 20 structural market leaders in the NSE 500 universe trading **within $\\le 5\\%$ of their 52-week highs** with positive 1-year alpha against Nifty 50. ")
            f.write(f"Benchmark 1-Year Nifty 50 Return: **{nifty_1y_perf*100:+.2f}%**.\n\n")
            f.write("### 📋 52-Week High Leaderboard Grid\n")
            f.write("| Rank | Ticker | Price | 52W High | Distance to High | 1Y Return | 1Y Alpha vs Nifty | Upward Conf (20D) | Target (20D) |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
            for idx, r in enumerate(high_top, 1):
                dist_str = f"**AT HIGH**" if r['dist_to_high'] >= -0.05 else f"**{r['dist_to_high']}%**"
                alpha_str = f"+{r['alpha_1y']}%" if r['alpha_1y'] >= 0 else f"{r['alpha_1y']}%"
                f.write(f"| #{idx} | **{r['ticker']}** | ₹{r['price']} | ₹{r['high_52w']} | {dist_str} | +{r['return_1y']}% | {alpha_str} | {r['confidence']}% | ₹{r['target_20d']} |\n")
            f.write("\n\n*Note: Proximity to 52-week highs is one of the strongest statistical indicators of institutional accumulation and long-term trend continuation.*")
        print(f"[SUCCESS] 52-Week High report written to: NSE500-Leaders-52WeekHigh.md")
        
        tele_msg = f"🏔️ *NSE 500 Top 20 52-Week High Leaders:* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
        for idx, l in enumerate(high_top[:10], 1):
            dist_tag = "AT HIGH" if l['dist_to_high'] >= -0.05 else f"{l['dist_to_high']}% to ATH"
            tele_msg += f"#{idx} *{l['ticker']}*: Price ₹{l['price']} | 52W High ₹{l['high_52w']} ({dist_tag}) | 1Y Return +{l['return_1y']}%\n"
        tele_msg += f"\n👉 Full 20 Scrips saved in Obsidian: `NSE500-Leaders-52WeekHigh.md`"
        send_telegram_message(tele_msg)

    print(f"\n[INFO] [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] All 4 NSE 500 scans completed and dispatches finalized successfully.")

def scheduler_loop(hour=18, minute=30):
    print(f"[INFO] Background daemon started. Scheduled to scan NSE 500 every Friday at {hour:02}:{minute:02} IST.")
    while True:
        now = datetime.datetime.now()
        days_ahead = (4 - now.weekday()) % 7
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if days_ahead == 0 and now >= target:
            days_ahead = 7
            
        target += datetime.timedelta(days=days_ahead)
        delta = (target - now).total_seconds()
        
        print(f"[INFO] Sleeping for {delta/3600:.2f} hours (until Friday, {target.strftime('%Y-%m-%d %H:%M:%S')} IST)")
        
        sleep_interval = 1800
        while delta > 0:
            time.sleep(min(delta, sleep_interval))
            now = datetime.datetime.now()
            delta = (target - now).total_seconds()
            
        try:
            run_nse500_scanner(scan_target="all")
        except Exception as e:
            print(f"[ERROR] Error during scheduled execution: {e}")
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KRONOS NSE 500 4-Way Leaders & Momentum Scanner")
    parser.add_argument("--scheduler", action="store_true", help="Run in continuous background daemon scheduler mode")
    parser.add_argument("--scan", type=str, default="all", choices=["all", "weekly", "monthly", "3month", "quarterly", "52week_high", "52w"], help="Scan category to execute")
    args = parser.parse_args()
    
    if args.scheduler:
        scheduler_loop(hour=18, minute=30)
    else:
        run_nse500_scanner(scan_target=args.scan)
