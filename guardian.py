import yfinance as yf
import pandas as pd
import numpy as np
import http.client, json, os
from datetime import datetime

yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- CURRENT ACTIVE HOLDINGS ---
MY_HOLDINGS = {
    "ADANIPOWER.NS": [1000, 163.36, "2026-04-07", "Energy"],
    "PREMIERENE.NS": [150, 943.30, "2026-04-07", "Infrastructure"],
    "NATCOPHARM.NS": [150, 1066.00, "2026-04-07", "Pharma"],
    "ORIENTELEC.NS": [700, 184.00, "2026-04-21", "Consumer Durables"],
    "SKYGOLD.NS": [218, 417.00, "2026-04-22", "Consumer Durables"],
    "AARTIIND.NS": [218, 459.54, "2026-04-22", "Chemicals"],
    "ABB.NS": [15, 7432.00, "2026-04-28", "Infrastructure"],
    "POWERINDIA.NS": [4, 32905.00, "2026-04-29", "Infrastructure"],
    "KIRLOSENG.NS": [60, 1694.80, "2026-04-30", "Capital Goods"],
    "BHEL.NS": [300, 349.00, "2026-04-30", "Infrastructure"],
    "HFCL.NS": [1000, 122.50, "2026-05-04", "Telecommunication"],
    "ADANIPORTS.NS": [70, 1702.00, "2026-05-04", "Infrastructure"],
    "TENNIND.NS": [145, 635.00, "2026-05-04", "Auto Components"],
    "LALPATHLAB.NS": [65, 1570.50, "2026-05-06", "Healthcare"],
    "NETWEB.NS": [25, 4344.00, "2026-05-06", "IT - Hardware"],
    "LAURUSLABS.NS": [68, 1211.20, "2026-05-07", "Pharma"],
    "HINDZINC.NS": [160, 641.70, "2026-05-07", "Metals"],
    "GVT&D.NS": [25, 4700.00, "2026-05-07", "Infrastructure"],
    "HAL.NS": [21, 4700.90, "2026-05-07", "Defense"]
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
        print(f"❌ Telegram Failed: {e}")

def run_advanced_guardian():
    tickers = list(MY_HOLDINGS.keys()) + ["^NSEI"]
    data = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    
    if data.empty:
        print("❌ No data returned from yfinance.")
        return

    try:
        nifty_close = data['Close']['^NSEI'].dropna()
        nifty_chg = ((nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2]) * 100
        nifty_20d_ret = ((nifty_close.iloc[-1] - nifty_close.iloc[-20]) / nifty_close.iloc[-20]) * 100
    except Exception:
        nifty_chg, nifty_20d_ret = 0.0, 0.0

    results = []
    total_val, daily_gain_sum, total_cost = 0.0, 0.0, 0.0
    sector_values = {}

    for ticker, (qty, buy_p, buy_date, sector) in MY_HOLDINGS.items():
        try:
            # Safely cross-section MultiIndex DataFrame
            df = data.xs(ticker, axis=1, level=1).dropna().copy()
            if len(df) < 20: 
                continue
            
            close_p = float(df['Close'].iloc[-1])
            prev_p = float(df['Close'].iloc[-2])
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            # Volatility Multiplier
            std_20d = df['Close'].pct_change().tail(20).std()
            base_mult = 2.5 if std_20d > 0.025 else 2.0
            mult = max(1.5, base_mult - (0.5 if pnl_pct > 30 else 0.25 if pnl_pct > 15 else 0.0))
            
            # True Range and ATR (14-period)
            tr = pd.concat([
                df['High'] - df['Low'], 
                (df['High'] - df['Close'].shift(1)).abs(), 
                (df['Low'] - df['Close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            
            valid_df = df[df.index >= buy_date].copy()
            if valid_df.empty: 
                valid_df = df.iloc[-5:]
            
            # Alpha vs Benchmark
            stock_20d_ret = ((close_p - df['Close'].iloc[-20]) / df['Close'].iloc[-20]) * 100
            pure_alpha_metric = stock_20d_ret - nifty_20d_ret

            # Dynamic Trailing Stop (Based on Close prices to limit extreme single-day spikes)
            valid_atr = atr.reindex(valid_df.index)
            ratchet_series = valid_df['Close'] - (mult * valid_atr)
            ratchet = ratchet_series.cummax().iloc[-1]
            
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            
            # Metrics aggregation
            total_val += (close_p * qty)
            total_cost += (buy_p * qty)
            daily_gain_sum += (close_p - prev_p) * qty
            sector_values[sector] = sector_values.get(sector, 0.0) + (close_p * qty)

            dt_obj = datetime.strptime(buy_date, '%Y-%m-%d')
            pretty_date = dt_obj.strftime('%d-%b-%y')
            
            is_triggered = close_p < ratchet
            status_icon = "🚨 *TRIGGER*" if is_triggered else "🔥" if pure_alpha_metric > 5.0 else "✅"
            
            ticker_name = ticker.replace('.NS','')
            line_text = f"*{ticker_name} ({pretty_date}) {pnl_pct:+.1f}%* | {status_icon}\n"
            line_text += f"_Stop: ₹{ratchet:.1f} ({dist_to_stop:.1f}% gap) | Alpha: {pure_alpha_metric:+.1f}%_\n\n"
            
            results.append({'text': line_text, 'is_cut': is_triggered, 'alpha_val': pure_alpha_metric})
        except Exception:
            continue

    if not results:
        return

    # Build Telegram Output
    report = f"🚀 *PORTFOLIO WATCHDOG: {datetime.now().strftime('%d %b')}*\n"
    report += f"Nifty 50: {nifty_chg:+.2f}% 🏛️\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Sort triggered items directly to the top of the alert message
    sorted_results = sorted(results, key=lambda x: (x['is_cut'], x['alpha_val']), reverse=True)
    for res in sorted_results: 
        report += res['text']

    report += "🏗️ *SECTOR EXPOSURE*\n"
    for sec, val in sorted(sector_values.items(), key=lambda item: item[1], reverse=True):
        allocation_pct = (val / total_val) * 100 if total_val > 0 else 0
        risk_flag = " ⚠️ *HIGH*" if allocation_pct > 25.0 else ""
        report += f"• {sec}: {allocation_pct:.1f}%{risk_flag}\n"

    port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if (total_val - daily_gain_sum) > 0 else 0
    alpha = port_daily_pct - nifty_chg
    total_pnl_pct = ((total_val - total_cost) / total_cost) * 100 if total_cost > 0 else 0
    
    report += f"\n📊 *SUMMARY*\nValue: ₹{total_val:,.0f} (Total Return: {total_pnl_pct:+.2f}%)\n"
    report += f"Daily: ₹{daily_gain_sum:,.0f} ({port_daily_pct:+.2f}%)\n"
    report += f"Alpha: {alpha:+.2f}% {'🔥' if alpha > 0 else '❄️'}"
    
    send_msg(report)

if __name__ == "__main__":
    run_advanced_guardian()
