import os, json, http.client, numpy as np, pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- AUTH & CONFIG ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
CSV_NAME = "ind_nifty500list.csv"

def send_msg(text):
    if not MY_TOKEN or not MY_CHAT_ID: return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
        conn.close()
    except: pass

# --- INDICATORS ---
def get_atr(df, n=14):
    tr = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift(1)), abs(df['Low']-df['Close'].shift(1))], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def get_rsi(s, n=14):
    d = s.diff(); g = d.where(d > 0, 0).rolling(n).mean(); l = d.where(d < 0, 0).abs().rolling(n).mean()
    return 100 - (100 / (1 + (g/(l + 1e-9))))

# --- SCANNER CORE ---
def scan_stock(symbol, sector):
    try:
        t = f"{symbol.strip()}.NS"
        df = yf.download(t, period="1y", progress=False, auto_adjust=True)
        if len(df) < 100: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        c = df['Close']
        score, signals = 0, []
        
        # 1. SQZ (Squeeze)
        sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
        if (sma20 + (2*std20)).iloc[-1] < (sma20 + (1.5*get_atr(df, 20))).iloc[-1]:
            score += 1; signals.append("SQZ")
            
        # 2. ULT (Ultimate Volatility/Relative Narrowness)
        bw = (std20 * 4) / sma20
        if bw.iloc[-1] <= bw.tail(20).min():
            score += 1; signals.append("ULT")

        # 3. RSI (Strength)
        if get_rsi(c).iloc[-1] > 55:
            score += 1; signals.append("RSI")

        # 4. GUP (Guppy Breakout)
        if c.ewm(span=8).mean().iloc[-1] > c.ewm(span=21).mean().iloc[-1]:
            score += 1; signals.append("GUP")

        # 5. VAM (Volatility Adjusted Momentum)
        if c.iloc[-1] > (sma20.iloc[-1] + (get_atr(df, 20).iloc[-1] * 2.0)):
            score += 1; signals.append("VAM")

        # Upside Calculation
        drift = (((c.iloc[-1]/c.iloc[0])-1)/250 * 0.7) + (((c.iloc[-1]/c.iloc[-20])-1)/20 * 0.3)
        upside = round(((c.iloc[-1] * (1 + (drift * 30)) - c.iloc[-1]) / c.iloc[-1]) * 100, 2)

        return {'s': symbol, 'sc': score, 'up': upside, 'sig': "+".join(signals), 'sec': sector}
    except: return None

def run_master():
    send_msg("🛰 *KRONOS:* Connection verified. Running Nifty 500 Confluence Scan...")
    
    try:
        df_csv = pd.read_csv(CSV_NAME)
        df_csv.columns = df_csv.columns.str.strip()
        # Ensure your CSV has 'Symbol' and 'Industry' or 'Sector'
        tickers = df_csv[['Symbol', 'Industry']].values.tolist()
    except:
        send_msg("❌ CSV Error: Ensure 'Symbol' and 'Industry' columns exist.")
        return

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        for res in executor.map(lambda x: scan_stock(x[0], x[1]), tickers):
            if res and res['sc'] >= 3: results.append(res)

    if not results:
        send_msg("📡 Scan complete. 0 stocks found.")
        return

    # Build Report
    final_df = pd.DataFrame(results).sort_values(['sc', 'up'], ascending=False)
    
    report = f"🏆 *KRONOS CONFLUENCE MASTER: {datetime.now().strftime('%d %b')}*\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Sector Flow (Top 3)
    report += "🔥 *SECTOR FLOW*\n"
    sec_counts = final_df['sec'].value_counts(normalize=True).head(3) * 100
    for sec, val in sec_counts.items():
        report += f"• {sec}: {val:.1f}%\n"
    report += "\n"

    # Stock List
    for _, r in final_df.head(20).iterrows():
        icon = "💎" if r['sc'] >= 4 else "🔥"
        report += f"{icon} `{r['s']}`: Score {r['sc']} | {r['up']}% Up | {r['sig']}\n"

    # TV List
    tv_list = ",".join([f"NSE:{s}" for s in final_df['s'].head(25)])
    report += f"\n📺 *TV LIST*\n`{tv_list}`"
    
    send_msg(report)

if __name__ == "__main__":
    run_master()
