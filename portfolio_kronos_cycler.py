import os
import sys
import yfinance as yf
import numpy as np
import pandas as pd
import json
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
PARENT_DIR = os.path.dirname(SCRIPT_DIR)

# Determine primary and secondary Obsidian directories
OBSIDIAN_DIR = os.path.join(PARENT_DIR, "Obsidian-Journal", "Ticker-Research")
if not os.path.exists(os.path.join(PARENT_DIR, "Obsidian-Journal")):
    OBSIDIAN_DIR = os.path.join(SCRIPT_DIR, "Obsidian-Journal", "Ticker-Research")
os.makedirs(OBSIDIAN_DIR, exist_ok=True)

# Custom dotenv loader to avoid external package dependencies
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

# Load credentials from local parent or script directory
load_custom_dotenv(os.path.join(PARENT_DIR, ".env"))
load_custom_dotenv(os.path.join(SCRIPT_DIR, ".env"))

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- START FALLBACK HOLDINGS (15 ACTIVE POSITIONS) ---
FALLBACK_HOLDINGS = {
    "OFSS.NS": {"quantity": 17, "avg_cost": 11260.00, "buy_date": "2026-07-07", "sector": "Information Technology", "strategy": "swing"},
    "SONACOMS.NS": {"quantity": 231, "avg_cost": 775.00, "buy_date": "2026-08-03", "sector": "Auto Components", "strategy": "swing"},
    "NEULANDLAB.NS": {"quantity": 7, "avg_cost": 23180.57, "buy_date": "2026-08-17", "sector": "Pharma", "strategy": "swing"},
    "ANANDRATHI.NS": {"quantity": 75, "avg_cost": 2195.00, "buy_date": "2026-08-18", "sector": "Financial Services", "strategy": "swing"},
    "BOSCHLTD.NS": {"quantity": 3, "avg_cost": 48606.67, "buy_date": "2026-08-20", "sector": "Auto Components", "strategy": "swing"},
    "DIVISLAB.NS": {"quantity": 20, "avg_cost": 8818.00, "buy_date": "2026-08-26", "sector": "Pharma", "strategy": "swing"},
    "AUBANK.NS": {"quantity": 150, "avg_cost": 1123.00, "buy_date": "2026-08-27", "sector": "Financial Services", "strategy": "swing"},
    "BHEL.NS": {"quantity": 352, "avg_cost": 430.00, "buy_date": "2026-08-31", "sector": "Capital Goods", "strategy": "swing"},
    "CPPLUS.NS": {"quantity": 45, "avg_cost": 3555.00, "buy_date": "2026-09-01", "sector": "Electronics", "strategy": "swing"},
    "HONASA.NS": {"quantity": 350, "avg_cost": 485.00, "buy_date": "2026-09-01", "sector": "Fast Moving Consumer Goods", "strategy": "swing"},
    "WELCORP.NS": {"quantity": 70, "avg_cost": 2420.00, "buy_date": "2026-09-01", "sector": "Metals & Mining", "strategy": "swing"},
    "FEDERALBNK.NS": {"quantity": 300, "avg_cost": 356.00, "buy_date": "2026-09-03", "sector": "Financial Services", "strategy": "swing"},
    "LTFOODS.NS": {"quantity": 250, "avg_cost": 445.00, "buy_date": "2026-09-03", "sector": "Fast Moving Consumer Goods", "strategy": "swing"},
    "SAIL.NS": {"quantity": 500, "avg_cost": 197.00, "buy_date": "2026-09-04", "sector": "Metals & Mining", "strategy": "swing"},
    "ZYDUSWELL.NS": {"quantity": 200, "avg_cost": 540.00, "buy_date": "2026-09-04", "sector": "Fast Moving Consumer Goods", "strategy": "swing"}
}
# --- END FALLBACK HOLDINGS ---

def load_live_portfolio():
    """Robust multi-path dynamic portfolio loader with schema normalization and resilient fallback."""
    paths_to_check = [
        os.path.join(SCRIPT_DIR, "portfolio.json"),
        os.path.join(PARENT_DIR, "Ratchet-System", "portfolio.json"),
        os.path.join(PARENT_DIR, "Scanner-Scripts", "portfolio.json"),
        os.path.join(SCRIPT_DIR, "latest_portfolio_positions.json"),
        os.path.join(PARENT_DIR, "latest_portfolio_positions.json"),
        os.path.join(os.getcwd(), "portfolio.json"),
        os.path.join(os.getcwd(), "Ratchet-System", "portfolio.json"),
        os.path.join(os.getcwd(), "Scanner-Scripts", "portfolio.json"),
        "portfolio.json"
    ]
    
    portfolio_path = None
    for p in paths_to_check:
        if os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as test_f:
                    test_d = json.load(test_f)
                    if test_d.get("holdings"):
                        portfolio_path = p
                        break
            except Exception:
                continue
                
    if not portfolio_path:
        print("[INFO] Utilizing high-conviction embedded fallback holdings.")
        return FALLBACK_HOLDINGS
        
    try:
        with open(portfolio_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        holdings_raw = data.get("holdings", {})
        if not holdings_raw:
            return FALLBACK_HOLDINGS
            
        formatted = {}
        # Case A: Dictionary format: {"TICKER.NS": {"avg_cost": ..., ...}}
        if isinstance(holdings_raw, dict):
            for t, info in holdings_raw.items():
                clean_t = t if t.endswith(".NS") or t.startswith("^") else f"{t}.NS"
                if isinstance(info, dict):
                    formatted[clean_t] = {
                        "quantity": info.get("quantity", info.get("qty", 1)),
                        "avg_cost": float(info.get("avg_cost", 1.0)),
                        "buy_date": info.get("buy_date", "2026-05-01"),
                        "sector": info.get("sector", "General"),
                        "strategy": info.get("strategy", "swing")
                    }
                elif isinstance(info, list) and len(info) >= 2:
                    formatted[clean_t] = {
                        "quantity": info[0],
                        "avg_cost": float(info[1]),
                        "buy_date": info[2] if len(info) > 2 else "2026-05-01",
                        "sector": info[3] if len(info) > 3 else "General",
                        "strategy": info[5] if len(info) > 5 else "swing"
                    }
        # Case B: List format: [{"full_ticker": "...", "avg_cost": ..., ...}]
        elif isinstance(holdings_raw, list):
            for item in holdings_raw:
                if isinstance(item, dict):
                    t = item.get("full_ticker") or item.get("ticker", "")
                    clean_t = t if t.endswith(".NS") or t.startswith("^") else f"{t}.NS"
                    formatted[clean_t] = {
                        "quantity": item.get("qty", item.get("quantity", 1)),
                        "avg_cost": float(item.get("avg_cost", 1.0)),
                        "buy_date": item.get("buy_date", "2026-05-01"),
                        "sector": item.get("sector", "General"),
                        "strategy": item.get("strategy", "swing")
                    }
                    
        print(f"[SUCCESS] Successfully loaded {len(formatted)} live positions from: {portfolio_path}")
        return formatted if formatted else FALLBACK_HOLDINGS
    except Exception as e:
        print(f"[WARNING] Failed parsing {portfolio_path}: {e}. Utilizing embedded fallback.")
        return FALLBACK_HOLDINGS

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
    
    holdings = load_live_portfolio()
    tickers = list(holdings.keys())
    print(f"[INFO] Monitoring {len(tickers)} active portfolio holdings against Nifty 50 (^NSEI)...")
    
    # Bulk Download with individual fallback
    tickers_to_fetch = tickers + ["^NSEI"]
    try:
        data = yf.download(tickers_to_fetch, period="2y", interval="1d", progress=False, auto_adjust=True)
    except Exception as e:
        print(f"[WARNING] Bulk yfinance download failed: {e}. Switching to per-ticker queries.")
        data = pd.DataFrame()
        
    # Extract Benchmark Nifty 50 Series
    nifty_close = pd.Series(dtype='float64')
    try:
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex) and ('Close', '^NSEI') in data.columns:
                nifty_close = data['Close']['^NSEI'].dropna()
            elif '^NSEI' in data.columns:
                nifty_close = data['^NSEI'].dropna()
    except Exception:
        pass
        
    if nifty_close.empty or len(nifty_close) < 60:
        try:
            nifty_df = yf.Ticker('^NSEI').history(period='2y', auto_adjust=True)
            if not nifty_df.empty and 'Close' in nifty_df.columns:
                nifty_close = nifty_df['Close'].dropna()
        except Exception as e:
            print(f"[WARNING] Could not fetch Nifty benchmark: {e}")
            
    nifty_perf_60d = 0.0
    if len(nifty_close) >= 60:
        nifty_perf_60d = (nifty_close.iloc[-1] - nifty_close.iloc[-60]) / nifty_close.iloc[-60]
    
    results = []
    
    for ticker in tickers:
        try:
            df = pd.Series(dtype='float64')
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex) and ('Close', ticker) in data.columns:
                    df = data['Close'][ticker].dropna()
                elif ticker in data.columns:
                    df = data[ticker].dropna()
                    
            if df.empty or len(df) < 60:
                hist = yf.Ticker(ticker).history(period="2y", auto_adjust=True)
                if not hist.empty and 'Close' in hist.columns:
                    df = hist['Close'].dropna()
                    
            if len(df) < 60:
                print(f"[WARNING] {ticker} has insufficient data ({len(df)} sessions, min 60 required). Skipping.")
                continue
                
            price = float(df.iloc[-1])
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
    
    # Segment data for display
    leaders = [r for r in sorted_results if "LEADER" in r["classification"]]
    laggards = [r for r in sorted_results if "LAGGARD" in r["classification"]]
    holds = [r for r in sorted_results if "HOLD" in r["classification"]]
    
    # Write report to Obsidian target directories
    obsidian_paths = [os.path.join(OBSIDIAN_DIR, "Portfolio-Analysis.md")]
    te_obsidian = r"C:\Users\Principal\Trading-Engine\Obsidian-Journal\Ticker-Research\Portfolio-Analysis.md"
    if os.path.exists(os.path.dirname(te_obsidian)) and te_obsidian not in obsidian_paths:
        obsidian_paths.append(te_obsidian)
        
    for report_file in obsidian_paths:
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(f"# 🪐 Portfolio Cycles & Rebalancing Report\n")
                f.write(f"**Generated:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n")
                f.write(f"### 📈 Summary Dashboard\n")
                f.write(f"- **Total Active Holdings Analyzed:** {len(sorted_results)} / {len(tickers)}\n")
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
                    f.write(f"| **{r['ticker']}** | Rs. {r['price']} | Rs. {r['avg_cost']} | {ret_style} | {r['confidence']}% | Rs. {r['target']} | {r['volatility']}% | Rs. {r['var_95']} | {alpha_style} | **{r['classification']}** |\n")
                    
                f.write("\n\n*Note: Calculations utilize a 10,000-run Geometric Brownian Motion (GBM) Monte Carlo simulation aligned to a 60-day historical drift and volatility window.*")
            print(f"[SUCCESS] Obsidian report compiled and saved: {report_file}")
        except Exception as e:
            print(f"[WARNING] Could not write report to {report_file}: {e}")
    
    # Compile Telegram Alert Message
    tele_msg = f"📊 *Portfolio Leaders & Laggards:* {datetime.date.today().strftime('%d-%b-%Y')} ({len(sorted_results)} Scrips)\n"
    tele_msg += f"Benchmark (Nifty 50 60D): {nifty_perf_60d*100:+.2f}%\n"
    tele_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if leaders:
        tele_msg += f"🔥 *Leaders ({len(leaders)} Outperforming / High Confidence):*\n"
        for l in leaders:
            tele_msg += f"• *{l['ticker'].replace('.NS', '')}*: CMP Rs. {l['price']} | 5D Target Rs. {l['target']} | Conf {l['confidence']}% | Alpha +{l['relative_perf']}%\n"
        tele_msg += "\n"
        
    if holds:
        tele_msg += f"⏳ *Holds ({len(holds)} Neutral / Peer Alignment):*\n"
        for h in holds:
            tele_msg += f"• *{h['ticker'].replace('.NS', '')}*: CMP Rs. {h['price']} | 5D Target Rs. {h['target']} | Conf {h['confidence']}% | Alpha +{h['relative_perf']}%\n"
        tele_msg += "\n"
        
    if laggards:
        tele_msg += f"⚠️ *Laggards ({len(laggards)} Underperforming / Low Confidence):*\n"
        for lg in laggards:
            alpha_sign = "+" if lg['relative_perf'] >= 0 else ""
            tele_msg += f"• *{lg['ticker'].replace('.NS', '')}*: CMP Rs. {lg['price']} | Conf {lg['confidence']}% | Alpha {alpha_sign}{lg['relative_perf']}%\n"
        tele_msg += "\n"
        
    tele_msg += "👉 Check Obsidian: `Portfolio-Analysis.md` for complete simulation metrics."
    send_telegram_message(tele_msg)
    print("[SUCCESS] Dispatch completed via Telegram.")

def scheduler_loop(hour=18, minute=0):
    print(f"[INFO] Background daemon started. Scheduled to scan every Friday at {hour:02}:{minute:02} IST.")
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
            run_portfolio_analysis()
        except Exception as e:
            print(f"[ERROR] Error during scheduled execution: {e}")
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kronos Portfolio Cycler Scanner")
    parser.add_argument("--scheduler", action="store_true", help="Run in continuous background daemon scheduler mode")
    args = parser.parse_args()
    
    if args.scheduler:
        scheduler_loop(hour=18, minute=0)
    else:
        run_portfolio_analysis()
