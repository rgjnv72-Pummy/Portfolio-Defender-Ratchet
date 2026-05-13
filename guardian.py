import yfinance as yf
import pandas as pd
import numpy as np
import http.client, json, os
from datetime import datetime

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- HOLDINGS ---
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
        print("❌ Secrets Missing!")
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        url = f"/bot{token}/sendMessage"
        conn.request("POST", url, payload, headers)
        res = conn.getresponse()
        conn.close()
    except Exception as e:
        print(f"❌ Telegram Failed: {e}")

def run_advanced_guardian():
    tickers = list(MY_HOLDINGS.keys()) + ["^NSEI"]
    data = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    
    if data.empty:
        return

    try:
        nifty_close = data['Close']['^NSEI'].dropna()
        nifty_chg = ((nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2]) * 100
    except:
        nifty_chg = 0.0

    results = []
    total_val, daily_gain_sum = 0, 0
    sector_values = {}

    for ticker, (qty, buy_p, buy_date, sector) in MY_HOLDINGS.items():
        try:
            df = data.iloc[:, data.columns.get_level_values(1) == ticker].copy()
            df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            
            if len(df) < 1: continue
            
            close_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2]
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            std = df['Close'].pct_change().std()
            mult = 1.0 if pnl_pct > 30 else 1.5 if pnl_pct > 15 else (2.5 if std > 0.025 else 2.0)
            tr = pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift(1)).abs(), (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            
            valid_df = df[df.index >= buy_date].copy()
            if valid_df.empty: valid_df = df.iloc[-5:]
            ratchet = (valid_df['High'] - (mult * atr.reindex(valid_df.index))).cummax().iloc[-1]
            
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            total_val += (close_p * qty)
            daily_gain_sum += (close_p - prev_p) * qty
            sector_values[sector] = sector_values.get(sector, 0) + (close_p * qty)

            # Date Formatting for Message
            dt_obj = datetime.strptime(buy_date, '%Y-%m-%d')
            pretty_date = dt_obj.strftime('%d-%b-%y')
            
            status_icon = "🚨 *EXIT*" if close_p < ratchet else "✅"
            
            # Formatting as requested: CHENNPETRO(12-Mar-26) +22.3
            ticker_name = ticker.replace('.NS','')
            line_text = f"*{ticker_name}({pretty_date}) {pnl_pct:+.1f}%* | {status_icon}\n"
            line_text += f"_Stop: ₹{ratchet:.1f} ({dist_to_stop:.1f}% cushion)_\n\n"
            
            results.append({'text': line_text, 'is_cut': close_p < ratchet})
        except:
            continue

    report = f"🚀 *PORTFOLIO RATCHET: {datetime.now().strftime('%d %b')}*\n"
    report += f"Nifty 50: {nifty_chg:+.2f}% 🏛️\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    sorted_results = sorted(results, key=lambda x: x['is_cut'], reverse=True)
    for res in sorted_results: report += res['text']

    report += "🏗️ *SECTOR EXPOSURE*\n"
    for sec, val in sorted(sector_values.items(), key=lambda item: item[1], reverse=True):
        report += f"• {sec}: {(val/total_val)*100:.1f}%\n"

    port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if total_val > daily_gain_sum else 0
    alpha = port_daily_pct - nifty_chg
    
    report += f"\n📊 *SUMMARY*\nValue: ₹{total_val:,.0f}\n"
    report += f"Daily: ₹{daily_gain_sum:,.0f} ({port_daily_pct:+.2f}%)\n"
    report += f"Alpha: {alpha:+.2f}% {'🔥' if alpha > 0 else '❄️'}"
    
    send_msg(report)

if __name__ == "__main__":
    run_advanced_guardian()
