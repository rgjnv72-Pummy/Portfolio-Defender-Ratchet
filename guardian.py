import yfinance as yf
import pandas as pd
import numpy as np
import http.client, json, os
from datetime import datetime

yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- CURRENT OPEN HOLDINGS (Ticker Strings Standardized to Yahoo Finance Master) ---
# Format: "YFinance_Ticker": [Total_Qty, Weighted_Avg_Buy_Price, Base_Date, "Sector", Manual_Current_Price_Fallback]
CURRENT_HOLDINGS = {
    "PREMIERENE.NS": [150, 943.30, "2026-04-07", "Infrastructure", 970.70],
    "NATCOPHARM.NS": [150, 1066.00, "2026-04-07", "Pharma", 1175.60],
    "ORIENTELEC.NS": [700, 184.00, "2026-04-21", "Consumer Durables", 188.40],
    "POWERINDIA.NS": [4, 32905.00, "2026-04-29", "Infrastructure", 31905.00],  # Hitachi Energy
    "BHEL.NS": [300, 349.00, "2026-04-30", "Infrastructure", 405.30],
    "ADANIPORTS.NS": [70, 1702.00, "2026-05-04", "Infrastructure", 1767.20],
    "TENNIND.NS": [145, 635.00, "2026-05-04", "Auto Components", 604.55],
    "HFCL.NS": [1000, 122.50, "2026-05-04", "Telecommunication", 142.44],
    "NETWEB.NS": [25, 4344.00, "2026-05-06", "IT - Hardware", 3901.30],
    "LALPATHLAB.NS": [65, 1570.50, "2026-05-06", "Healthcare", 1582.00],
    "HAL.NS": [21, 4700.90, "2026-05-07", "Defense", 4585.20],
    "LAURUSLABS.NS": [68, 1211.20, "2026-05-07", "Pharma", 1299.70],
    "HINDZINC.NS": [160, 641.70, "2026-05-07", "Metals", 670.30],
    "GALLANTT.NS": [100, 906.00, "2026-05-11", "Metals", 763.50],
    "ATHERENERG.NS": [100, 943.00, "2026-05-11", "Auto Components", 943.30],   # Fixed Exchange Identifier
    "APARINDS.NS": [9, 12905.00, "2026-05-12", "Capital Goods", 12461.00],
    "CARBORUNIV.NS": [111, 1024.71, "2026-05-12", "Capital Goods", 1040.00],
    "JRRESOURCES.NS": [200, 560.00, "2026-05-12", "Mining / Resources", 566.85], # Fixed Exchange Identifier
    "HINDCOPPER.NS": [198, 598.64, "2026-05-13", "Metals", 609.00],
    "APTUS.NS": [300, 270.25, "2026-05-13", "Financial Services", 269.25]
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
        conn.getresponse()
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

    # --- FIRST PASS: GLOBAL VALUATION ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p) in CURRENT_HOLDINGS.items():
        try:
            if (not data.empty) and ('Close' in data.columns) and (ticker in data['Close'].columns):
                df_ticker = data.xs(ticker, axis=1, level=1).dropna()
                if len(df_ticker) >= 2:
                    latest_close = float(df_ticker['Close'].iloc[-1])
                    yesterday_close = float(df_ticker['Close'].iloc[-2])
                    
                    total_val += (latest_close * qty)
                    total_cost += (buy_p * qty)
                    daily_gain_sum += (latest_close - yesterday_close) * qty
                    continue
            raise ValueError()
        except Exception:
            total_val += (fallback_p * qty)
            total_cost += (buy_p * qty)
            daily_gain_sum += 0.0 
            skipped_tickers.append(ticker.replace('.NS', ''))

    # --- SECOND PASS: EXTREME RISK ANALYSIS ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p) in CURRENT_HOLDINGS.items():
        try:
            if (data.empty) or ('Close' not in data.columns) or (ticker not in data['Close'].columns):
                continue
                
            df = data.xs(ticker, axis=1, level=1).dropna().copy()
            if len(df) < 15: 
                continue
            
            close_p = float(df['Close'].iloc[-1])
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            tr = pd.concat([
                df['High'] - df['Low'], 
                (df['High'] - df['Close'].shift(1)).abs(), 
                (df['Low'] - df['Close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            
            valid_df = df[df.index >= buy_date].copy()
            if valid_df.empty: 
                valid_df = df.iloc[-5:]
                
            valid_atr = atr.reindex(valid_df.index)
            ratchet_series = valid_df['Close'] - (2.0 * valid_atr)
            ratchet = ratchet_series.rolling(20, min_periods=1).max().iloc[-1]
            
            ratchet = min(ratchet, close_p * 0.97)
            ratchet = max(ratchet, buy_p * 0.88)
            
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            
            if dist_to_stop > 6.0:
                continue

            is_triggered = close_p <= (ratchet + 0.05)
            status_icon = "🚨 *BREAK*" if is_triggered else "⚠️ *RISK*"
            
            clean_name = ticker.replace('.NS','').replace('ENERG','')
            line_text = f"*{clean_name}* | Price: ₹{close_p:.1f} ({pnl_pct:+.1f}%) | {status_icon}\n"
            line_text += f"_Stop Floor: ₹{ratchet:.1f} ({dist_to_stop:.1f}% cushion)_\n\n"
            
            results.append({'text': line_text, 'cushion': dist_to_stop})
        except Exception:
            continue

    # --- REPORT COMPOSITION ---
    report = f"📋 *LIVE RISK WATCHDOG (<6% Cushion): {datetime.now().strftime('%d %b')}*\n"
    report += f"Nifty 50 Index: {nifty_chg:+.2f}%\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if results:
        sorted_results = sorted(results, key=lambda x: x['cushion'])
        for res in sorted_results: 
            report += res['text']
    else:
        report += "✅ All open positions currently have a healthy cushion (>6%).\n\n"

    if skipped_tickers:
        report += f"ℹ️ *Skipped Risk Charts*: {', '.join(skipped_tickers)}\n\n"

    port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if (total_val - daily_gain_sum) > 0 else 0
    total_pnl_pct = ((total_val - total_cost) / total_cost) * 100 if total_cost > 0 else 0
    
    val_lakhs = total_val / 100000
    gain_lakhs = daily_gain_sum / 100000
    
    report += "━━━━━━━━━━━━━━━━━━━━\n"
    report += f"📊 *SUMMARY*\n"
    report += f"Live Account Value: ₹{val_lakhs:.2f}L\n"
    report += f"Open Book Profit: {total_pnl_pct:+.2f}%\n"
    report += f"Session Change: ₹{gain_lakhs:+.2f}L ({port_daily_pct:+.2f}%)"
    
    send_msg(report)

if __name__ == "__main__":
    run_simplified_watchdog()
