import os, json, urllib3, numpy as np, pandas as pd
import yfinance as yf
import pandas_ta as ta
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- CONFIG ---
CSV_FILE = "ind_nifty500list.csv" # Ensure this is in your repo
TOP_N = 25

def send_msg(text):
    try:
        conn = http_client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
        conn.close()
    except: pass

def get_confluence_score(symbol):
    try:
        df = yf.download(f"{symbol}.NS", period="2y", progress=False, auto_adjust=True, threads=False)
        if df is None or len(df) < 250: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        c = df['Close'].astype(float)
        h, l = df['High'].astype(float), df['Low'].astype(float)
        score = 0
        signals = []

        # 1. KRONOS DRIFT
        drift = (((c.iloc[-1]/c.iloc[-250])-1)/250 * 0.7) + (((c.iloc[-1]/c.iloc[-20])-1)/20 * 0.3)
        upside = ((c.iloc[-1] * (1 + (drift * 30)) - c.iloc[-1]) / c.iloc[-1]) * 100
        if not (1.5 < upside < 30): return None

        # 2. LOGIC MODULES
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
        
        if (sma20 + (2*std20)).iloc[-1] < (sma20 + (1.5*tr.rolling(20).mean())).iloc[-1]:
            score += 1; signals.append("SQZ")
        if (std20*4/sma20*100).iloc[-1] <= (std20*4/sma20*100).tail(21).min():
            score += 1; signals.append("ULT")
        if ta.hma(c, length=55).iloc[-1] > ta.hma(c, length=55).iloc[-2]:
            score += 1; signals.append("HUL")
        if ta.rsi(c, length=14).iloc[-1] > 55:
            score += 1; signals.append("RSI")

        return {'Symbol': symbol, 'Score': score, 'Upside%': round(upside, 2), 'Signals': "+".join(signals)}
    except: return None

def run_master_scan():
    df_nse = pd.read_csv(CSV_FILE)
    tickers = df_nse.iloc[:, 2].unique().tolist()
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for res in executor.map(get_confluence_score, tickers):
            if res: results.append(res)
    
    if not results: return
    
    final_df = pd.DataFrame(results).sort_values(by=['Score', 'Upside%'], ascending=False).head(TOP_N)
    
    msg = f"🏆 *KRONOS WEEKLY SCAN: {datetime.now().strftime('%d-%b')}*\n"
    msg += "_Full-Proof Confluence Dashboard_\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for _, r in final_df.head(15).iterrows():
        icon = "💎" if r['Score'] >= 3 else "🔥"
        msg += f"{icon} `{r['Symbol']}`: *Score {r['Score']}* | {r['Upside%']}% Up\n"
    
    tv_list = ",".join([f"NSE:{s}" for s in final_df['Symbol']])
    msg += f"\n📺 *TV LIST*\n`{tv_list}`"
    
    send_msg(msg)

if __name__ == "__main__":
    import http.client
    http_client = http.client
    run_master_scan()
