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
    "PREMIERENE.NS": [150, 943.30, "2026-04-07", "Infrastructure"],
    "NATCOPHARM.NS": [150, 1066.00, "2026-04-07", "Pharma"],
    "ORIENTELEC.NS": [700, 184.00, "2026-04-21", "Consumer Durables"],
    "POWERINDIA.NS": [4, 32905.00, "2026-04-29", "Infrastructure"],
    "KIRLOSENG.NS": [60, 1694.80, "2026-04-30", "Capital Goods"],
    "BHEL.NS": [300, 349.00, "2026-04-30", "Infrastructure"],
    "ADANIPORTS.NS": [70, 1702.00, "2026-05-04", "Infrastructure"],
    "TENNIND.NS": [145, 635.00, "2026-05-04", "Auto Components"],
    "HFCL.NS": [1000, 122.50, "2026-05-04", "Telecommunication"],
    "NETWEB.NS": [25, 4344.00, "2026-05-06", "IT - Hardware"],
    "LALPATHLAB.NS": [65, 1570.50, "2026-05-06", "Healthcare"],
    "HAL.NS": [21, 4700.90, "2026-05-07", "Defense"],
    "GET&D.NS": [25, 4700.00, "2026-05-07", "Infrastructure"],
    "LAURUSLABS.NS": [68, 1211.20, "2026-05-07", "Pharma"],
    "HINDZINC.NS": [160, 641.70, "2026-05-07", "Metals"],
    "GALLANTT.NS": [100, 906.00, "2026-05-11", "Metals"],
    "ATHERENERG.NS": [100, 943.00, "2026-05-11", "Auto Components"],
    "APARINDS.NS": [9, 12905.00, "2026-05-12", "Capital Goods"],
    "CARBORUNIV.NS": [100, 1026.00, "2026-05-12", "Capital Goods"],
    "JAINREC.NS": [200, 560.00, "2026-05-12", "Infrastructure"]
}




# --- MOMENTUM LOGIC ---
def get_momentum_status(df):
    try:
        # RSI 14
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain/loss))).iloc[-1]
        
        # ROC (Rate of Change) - Speed of last 5 days vs previous 5 days
        roc_now = ((df['Close'].iloc[-1] - df['Close'].iloc[-5]) / df['Close'].iloc[-5]) * 100
        roc_prev = ((df['Close'].iloc[-2] - df['Close'].iloc[-6]) / df['Close'].iloc[-6]) * 100
        
        # Priority Weight: Red (1) -> Orange (2) -> Green (3)
        if rsi > 70 and roc_now < roc_prev:
            return "🔴", 1 
        elif rsi > 60 and roc_now > roc_prev:
            return "🟢", 3 
        else:
            return "🟠", 2 
    except:
        return "⚪", 4

def send_msg(text):
    token = MY_TOKEN.strip() if MY_TOKEN else None
    chat_id = MY_CHAT_ID.strip() if MY_CHAT_ID else None
    if not token or not chat_id: return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{token}/sendMessage", payload, headers)
        conn.getresponse()
    except: pass

def run_advanced_guardian():
    tickers = list(MY_HOLDINGS.keys()) + ["^NSEI"]
    data = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    if data.empty: return

    nifty_close = data['Close']['^NSEI'].iloc[-1]
    nifty_chg = ((nifty_close - data['Close']['^NSEI'].iloc[-2]) / data['Close']['^NSEI'].iloc[-2]) * 100

    results, total_val, daily_gain_sum, sector_values = [], 0, 0, {}

    for ticker, (qty, buy_p, buy_date, sector) in MY_HOLDINGS.items():
        try:
            df = data.iloc[:, data.columns.get_level_values(1) == ticker].copy()
            df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            
            close_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2]
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            # Get Momentum status and rank for sorting
            m_icon, m_rank = get_momentum_status(df)
            
            # --- Original Ratchet Logic ---
            std = df['Close'].pct_change().std()
            mult = 1.0 if pnl_pct > 30 else 1.5 if pnl_pct > 15 else (2.5 if std > 0.025 else 2.0)
            tr = pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift(1)).abs(), (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            valid_df = df[df.index >= buy_date].copy()
            ratchet = (valid_df['High'] - (mult * atr.reindex(valid_df.index))).cummax().iloc[-1]
            
            total_val += (close_p * qty)
            daily_gain_sum += (close_p - prev_p) * qty
            sector_values[sector] = sector_values.get(sector, 0) + (close_p * qty)

            status_icon = "🚨 *EXIT*" if close_p < ratchet else "✅"
            ticker_name = ticker.replace('.NS','')
            pretty_date = datetime.strptime(buy_date, '%Y-%m-%d').strftime('%d-%b-%y')
            
            line_text = f"*{ticker_name}({pretty_date}) {pnl_pct:+.1f}%* | {status_icon} {m_icon}\n"
            line_text += f"_Stop: ₹{ratchet:.1f} ({((close_p - ratchet) / close_p) * 100:.1f}% cushion)_\n\n"
            
            # Weighted Sort: 
            # 0: EXIT Alerts (Always First)
            # 1: Red Momentum (Fading)
            # 2: Orange Momentum (Middle)
            # 3: Green Momentum (Full)
            sort_weight = 0 if close_p < ratchet else m_rank
            results.append({'text': line_text, 'weight': sort_weight})
        except: continue

    report = f"🚀 *PORTFOLIO RATCHET: {datetime.now().strftime('%d %b')}*\nNifty 50: {nifty_chg:+.2f}% 🏛️\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Sort results by weight (EXIT -> Red -> Orange -> Green)
    for res in sorted(results, key=lambda x: x['weight']): report += res['text']

    report += "🏗️ *SECTOR EXPOSURE*\n"
    for sec, val in sorted(sector_values.items(), key=lambda item: item, reverse=True):
        report += f"• {sec}: {(val/total_val)*100:.1f}%\n"

    port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if (total_val - daily_gain_sum) != 0 else 0
    report += f"\n📊 *SUMMARY*\nValue: ₹{total_val:,.0f}\nDaily: ₹{daily_gain_sum:,.0f} ({port_daily_pct:+.2f}%)\nAlpha: {port_daily_pct - nifty_chg:+.2f}% {'🔥' if (port_daily_pct - nifty_chg) > 0 else '❄️'}"
    
    send_msg(report)

if __name__ == "__main__":
    run_advanced_guardian()

