import yfinance as yf
import pandas as pd
import numpy as np
import http.client, json, os
from datetime import datetime

yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- CURRENT OPEN HOLDINGS ---
CURRENT_HOLDINGS = {
    "PREMIERENE.NS": [150, 943.30, "2026-04-07", "Infrastructure", 970.70],
    "ORIENTELEC.NS": [700, 184.00, "2026-04-21", "Consumer Durables", 188.40],
    "POWERINDIA.NS": [4, 32905.00, "2026-04-29", "Infrastructure", 31905.00],
    "ADANIPORTS.NS": [70, 1702.00, "2026-05-04", "Infrastructure", 1767.20],
    "HFCL.NS": [1000, 122.50, "2026-05-04", "Telecommunication", 142.44],
    "HINDZINC.NS": [160, 641.70, "2026-05-07", "Metals", 670.30],
    "BHARATFORG.NS": [39, 1959.00, "2026-05-15", "Industrial Manufacturing", 1934.00],
    "ATHERENERG.NS": [100, 943.00, "2026-05-11", "Auto Components", 943.30],
    "APARINDS.NS": [9, 12905.00, "2026-05-12", "Capital Goods", 12461.00],
    "CARBORUNIV.NS": [111, 1024.71, "2026-05-12", "Capital Goods", 1040.00],
    "APTUS.NS": [300, 270.25, "2026-05-13", "Financial Services", 269.25],
    "RAINBOW.NS": [80, 1341.00, "2026-05-18", "Healthcare", 1341.00],
    "INDUSTOWER.NS": [250, 430.00, "2026-05-18", "Telecommunication", 430.00],
    "SAIL.NS": [382, 198.00, "2026-05-19", "Metals", 198.00],
    "NLCINDIA.NS": [300, 355.00, "2026-05-19", "Power & Energy", 355.00],
    "BHEL.NS": [250, 420.00, "2026-05-29", "Capital Goods", 425.00],
    "NATIONALUM.NS": [300, 435.00, "2026-05-29", "Metals", 440.00],
    
    # --- Latest Additions ---
    "LAURUSLABS.NS": [118, 1278.50, "2026-05-30", "Pharma", 1299.70],   # 68@1211.20 + 50@1370 (blended avg)
    "GVT&D.NS": [31, 4770.00, "2026-05-31", "UNKNOWN", 4800.00]         # New addition
}
   
    


def send_msg(text):
    token = MY_TOKEN.strip() if MY_TOKEN else None
    chat_id = MY_CHAT_ID.strip() if MY_CHAT_ID else None
    if not token or not chat_id:
        print(text)
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{token}/sendMessage", payload, headers)
        conn.getresponse()  # Fixed multiple-assignment assignment typo string
        conn.close()
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def run_simplified_watchdog():
    try:
        tickers = list(CURRENT_HOLDINGS.keys()) + ["^NSEI"]
        data = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    except Exception:
        data = pd.DataFrame()

    try:
        nifty_close = data['Close']['^NSEI'].dropna()
        nifty_chg = ((nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2]) * 100
    except Exception:
        nifty_chg = 0.0

    results = []
    total_val, daily_gain_sum, total_cost = 0.0, 0.0, 0.0
    skipped_tickers = []
    sector_values = {}
    total_scrips = len(CURRENT_HOLDINGS)

    # --- FIRST PASS: GLOBAL VALUATION & SECTOR SUMMARY ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p) in CURRENT_HOLDINGS.items():
        try:
            if (not data.empty) and ('Close' in data.columns) and (ticker in data['Close'].columns):
                df_ticker = data.xs(ticker, axis=1, level=1).dropna()
                if len(df_ticker) >= 2:
                    latest_close = float(df_ticker['Close'].iloc[-1])
                    yesterday_close = float(df_ticker['Close'].iloc[-2])
                    
                    current_value = (latest_close * qty)
                    total_val += current_value
                    total_cost += (buy_p * qty)
                    daily_gain_sum += (latest_close - yesterday_close) * qty
                    sector_values[sector] = sector_values.get(sector, 0.0) + current_value
                    continue
            raise ValueError()
        except Exception:
            current_fallback_value = (fallback_p * qty)
            total_val += current_fallback_value
            total_cost += (buy_p * qty)
            daily_gain_sum += 0.0 
            sector_values[sector] = sector_values.get(sector, 0.0) + current_fallback_value
            skipped_tickers.append(ticker.replace('.NS', ''))

    # --- SECOND PASS: EXTREME DUAL-ENGINE RISK ANALYSIS ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p) in CURRENT_HOLDINGS.items():
        try:
            if (data.empty) or ('Close' not in data.columns) or (ticker not in data['Close'].columns):
                continue
                
            df = data.xs(ticker, axis=1, level=1).dropna().copy()
            if len(df) < 60: 
                continue
            
            close_p = float(df['Close'].iloc[-1])
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            tr = pd.concat([
                df['High'] - df['Low'], 
                (df['High'] - df['Close'].shift(1)).abs(), 
                (df['Low'] - df['Close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            
            # --- SQUEEZE BREAKOUT ENTRY ENGINE LAYER ---
            # Capture peak volatility prior to entry to avoid the compressed 'Squeeze trap'
            atr_pre_entry = atr[(atr.index <= buy_date)].tail(60)
            if not atr_pre_entry.empty:
                entry_atr = float(atr_pre_entry.max())  # Maximum historical pre-burst structural baseline
            else:
                entry_atr = float(atr.iloc[-1])
            
            initial_atr_floor = buy_p - (1.5 * entry_atr)
            
            valid_df = df[df.index >= buy_date].copy()
            if valid_df.empty: 
                valid_df = df.iloc[-5:]
                
            # --- ENGINE A: DYNAMIC TRAILING MULTIPLIER CONFIGURATION ---
            if pnl_pct > 20.0:  
                mult = 2.5     # Protect large winners early from deep profit-taking pullbacks
            elif pnl_pct < 0.0:
                mult = 1.5     # Tight capital restriction for entry phases
            else:
                mult = 2.0     # Standard trailing metric
                
            valid_atr = atr.reindex(valid_df.index)
            ratchet_series = valid_df['Close'] - (mult * valid_atr)
            
            # --- ENGINE B: STOCK-SPECIFIC VOLATILITY TIME ENGINE ---
            hist_vol = df['Close'].pct_change().tail(60).std()
            
            if hist_vol >= 0.030:
                lookback_days = 15   # High Volatility Breakouts: Fast profit locking
            elif hist_vol >= 0.018:
                lookback_days = 25   
            else:
                lookback_days = 40   # Clean Institutional Trends: Maximum macro breathing room
            
            ratchet = ratchet_series.rolling(lookback_days, min_periods=1).max().iloc[-1]
            
            # Dynamic Guardrails
            ratchet = min(ratchet, close_p * 0.97)
            ratchet = max(ratchet, initial_atr_floor)
            
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            
            if dist_to_stop > 3.0:
                continue

            is_triggered = close_p <= (ratchet + 0.05)
            status_icon = "🚨 *BREAK*" if is_triggered else "⚠️ *RISK*"
            
            clean_name = ticker.replace('.NS','').replace('ENERG','')
            line_text = f"*{clean_name}* | Price: ₹{close_p:.1f} ({pnl_pct:+.1f}%) | {status_icon}\n"
            line_text += f"_Stop Floor: ₹{ratchet:.1f} ({dist_to_stop:.1f}% cushion) | Config: {lookback_days}D Lookback / {mult}x Mult_\n\n"
            
            results.append({'text': line_text, 'cushion': dist_to_stop})
        except Exception:
            continue

    # --- REPORT COMPOSITION ---
    report = f"📋 *LIVE RISK WATCHDOG (<3% Cushion): {datetime.now().strftime('%d %b')}*\n"
    report += f"Nifty 50 Index: {nifty_chg:+.2f}%\n"
    report += f"Total Active Scrips: {total_scrips}\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if results:
        sorted_results = sorted(results, key=lambda x: x['cushion'])
        for res in sorted_results: 
            report += res['text']
    else:
        report += "✅ All open positions currently have a healthy cushion (>6%).\n\n"

    report += "🏗️ *SECTOR EXPOSURE SUMMARY*\n"
    for sec, val in sorted(sector_values.items(), key=lambda item: item[1], reverse=True): 
        allocation_pct = (val / total_val) * 100 if total_val > 0 else 0
        report += f"• {sec}: {allocation_pct:.1f}%\n"
    report += "\n"

    if skipped_tickers:
        report += f"ℹ️ *Skipped Risk Charts*: {', '.join(skipped_tickers)}\n\n"

    port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if (total_val - daily_gain_sum) > 0 else 0
    total_pnl_pct = ((total_val - total_cost) / total_cost) * 100 if total_cost > 0 else 0
    
    alpha_metric = port_daily_pct - nifty_chg
    alpha_icon = "🔥" if alpha_metric > 0 else "❄️"
    
    val_lakhs = total_val / 100000
    gain_lakhs = daily_gain_sum / 100000
    
    report += "━━━━━━━━━━━━━━━━━━━━\n"
    report += f"📊 *SUMMARY*\n"
    report += f"Live Account Value: ₹{val_lakhs:.2f}L\n"
    report += f"Open Book Profit: {total_pnl_pct:+.2f}%\n"
    report += f"Session Change: ₹{gain_lakhs:+.2f}L ({port_daily_pct:+.2f}%)\n"
    report += f"Session Alpha: {alpha_metric:+.2f}% {alpha_icon}"
    
    send_msg(report)

if __name__ == "__main__":
    run_simplified_watchdog()
