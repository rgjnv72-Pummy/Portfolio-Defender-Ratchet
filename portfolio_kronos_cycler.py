import os
import yfinance as yf
import numpy as np
import pandas as pd
import json
import datetime
import time
import requests
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_PATH = os.path.join(SCRIPT_DIR, "portfolio.json")

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
    # Calculate daily log returns
    log_returns = np.log(df / df.shift(1)).dropna()
    
    # 60-day window for consistent short-term drift and volatility
    recent_rets = log_returns.iloc[-60:]
    if len(recent_rets) < 15:
        # Fallback if too short
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
    
    # Value at Risk (VaR 95%)
    var_95 = price - np.percentile(final_prices, 5)
    
    return confidence, target_p, vol * 100, var_95

def run_portfolio_analysis():
    print(f"\n[INFO] [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Portfolio Cycle Scan...")
    
    if not os.path.exists(PORTFOLIO_PATH):
        print(f"[ERROR] Portfolio database not found at: {PORTFOLIO_PATH}")
        return
        
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        portfolio_data = json.load(f)
        
    holdings = portfolio_data.get("holdings", {})
    if not holdings:
        print("[WARNING] No active holdings found in portfolio.")
        return
        
    tickers = list(holdings.keys())
    print(f"[INFO] Loading data for {len(tickers)} assets and Nifty 50 benchmark...")
    
    # Download data
    tickers_to_fetch = tickers + ["^NSEI"]
    data = yf.download(tickers_to_fetch, period="2y", interval="1d", progress=False, auto_adjust=True)
    
    # Calculate benchmark metrics
    nifty_close = data['Close']['^NSEI'].dropna()
    nifty_perf_60d = (nifty_close.iloc[-1] - nifty_close.iloc[-60]) / nifty_close.iloc[-60]
    
    results = []
    
    for ticker in tickers:
        try:
            df = data['Close'][ticker].dropna()
            if len(df) < 60:
                print(f"[WARNING] {ticker} has insufficient data (min 60 days). Skipping.")
                continue
                
            price = df.iloc[-1]
            perf_60d = (price - df.iloc[-60]) / df.iloc[-60]
            relative_perf = perf_60d - nifty_perf_60d
            
            # Execute GBM Monte Carlo
            confidence, target_p, vol_pct, var_95 = calculate_gbm_simulation(df, price)
            
            # Leader & Laggard classification logic
            # Leader: High probability to rise (>60%) and outperforming benchmark
            # Laggard: Low probability to rise (<50%) or underperforming benchmark
            if confidence >= 60.0 and relative_perf > 0:
                classification = "LEADER 🔥"
            elif confidence < 50.0 or relative_perf < 0:
                classification = "LAGGARD ⚠️"
            else:
                classification = "HOLD ⏳"
                
            results.append({
                "ticker": ticker,
                "price": round(price, 2),
                "avg_cost": holdings[ticker].get("avg_cost", 0.0),
                "quantity": holdings[ticker].get("quantity", 0),
                "confidence": round(confidence, 1),
                "target": round(target_p, 2),
                "volatility": round(vol_pct, 2),
                "var_95": round(var_95, 2),
                "relative_perf": round(relative_perf * 100, 2),
                "classification": classification
            })
        except Exception as e:
            print(f"[ERROR] Error simulating {ticker}: {e}")
            
    # Sort results: Leaders first, then Hold, then Laggards
    classification_order = {"LEADER 🔥": 0, "HOLD ⏳": 1, "LAGGARD ⚠️": 2}
    sorted_results = sorted(results, key=lambda x: (classification_order[x["classification"]], -x["confidence"]))
    
    # Save report to Obsidian
    report_file = os.path.join(OBSIDIAN_DIR, "Portfolio-Analysis.md")
    
    # Segment data for display
    leaders = [r for r in sorted_results if "LEADER" in r["classification"]]
    laggards = [r for r in sorted_results if "LAGGARD" in r["classification"]]
    holds = [r for r in sorted_results if "HOLD" in r["classification"]]
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# 🪐 Portfolio Cycles & Rebalancing Report\n")
        f.write(f"**Generated:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n")
        f.write(f"### 📈 Summary Dashboard\n")
        f.write(f"- **Total Active Holdings Analyzed:** {len(sorted_results)}\n")
        f.write(f"- **Leaders Detected:** {len(leaders)} 🔥\n")
        f.write(f"- **Holds/Neutrals:** {len(holds)} ⏳\n")
        f.write(f"- **Laggards Detected:** {len(laggards)} ⚠️\n\n")
        
        f.write("### 📋 Analysis Grid\n")
        f.write("| Ticker | Price | Cost | Return | Confidence | Target (5D) | Volatility (60D) | VaR 95% (5D) | 60D Alpha vs Nifty | Action |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
        
        for r in sorted_results:
            p_return = ((r["price"] - r["avg_cost"]) / r["avg_cost"]) * 100 if r["avg_cost"] > 0 else 0
            ret_style = f"**{round(p_return, 1)}%**" if p_return >= 0 else f"*{round(p_return, 1)}%*"
            alpha_style = f"+{r['relative_perf']}%" if r['relative_perf'] >= 0 else f"{r['relative_perf']}%"
            f.write(f"| **{r['ticker']}** | ₹{r['price']} | ₹{r['avg_cost']} | {ret_style} | {r['confidence']}% | ₹{r['target']} | {r['volatility']}% | ₹{r['var_95']} | {alpha_style} | **{r['classification']}** |\n")
            
        f.write("\n\n*Note: Calculations utilize a 10,000-run Geometric Brownian Motion (GBM) Monte Carlo simulation aligned to a 60-day historical drift and volatility window.*")
        
    print(f"[SUCCESS] Obsidian report compiled and saved: {report_file}")
    
    # Compile Telegram Message
    tele_msg = f"📊 *Portfolio Cycle Analysis:* {datetime.date.today().strftime('%d-%b-%Y')}\n\n"
    
    if leaders:
        tele_msg += "🔥 *Leaders (Outperforming & High Confidence):*\n"
        for l in leaders:
            tele_msg += f"• {l['ticker'].replace('.NS', '')}: Price ₹{l['price']} | Target ₹{l['target']} | Conf {l['confidence']}%\n"
        tele_msg += "\n"
        
    if laggards:
        tele_msg += "⚠️ *Laggards (Underperforming / Low Confidence):*\n"
        for lg in laggards:
            alpha_sign = "+" if lg['relative_perf'] >= 0 else ""
            tele_msg += f"• {lg['ticker'].replace('.NS', '')}: Price ₹{lg['price']} | Conf {lg['confidence']}% | Alpha {alpha_sign}{lg['relative_perf']}%\n"
        tele_msg += "\n"
        
    tele_msg += "👉 Check Obsidian: `Portfolio-Analysis.md` for complete simulation metrics."
    send_telegram_message(tele_msg)
    print("[SUCCESS] Dispatch completed via Telegram.")

def scheduler_loop(hour=18, minute=0):
    print(f"[INFO] Background daemon started. Scheduled to scan every Friday at {hour:02}:{minute:02} IST.")
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
            run_portfolio_analysis()
        except Exception as e:
            print(f"[ERROR] Error during scheduled execution: {e}")
        # Give it a short sleep to avoid double-triggering
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kronos Portfolio Cycler Scanner")
    parser.add_argument("--scheduler", action="store_true", help="Run in continuous background daemon scheduler mode")
    args = parser.parse_args()
    
    if args.scheduler:
        scheduler_loop(hour=18, minute=0)
    else:
        run_portfolio_analysis()
