import os, json, http.client, numpy as np, pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
CSV_NAME = "ind_nifty500list.csv"

def send_msg(text):
    if not MY_TOKEN or not MY_CHAT_ID:
        print("❌ ERROR: Secrets not found")
        return
    try:
        # Clean text for basic Markdown safety
        clean_text = text.replace("_", "\\_").replace("*", "\\*") if "```" not in text else text
        
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
        payload = json.dumps({
            "chat_id": str(MY_CHAT_ID).strip(),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN.strip()}/sendMessage", payload, headers)
        resp = conn.getresponse()
        print(f"📡 Telegram Status: {resp.status} {resp.reason}")
        conn.close()
    except Exception as e:
        print(f"❌ Telegram Failed: {e}")

# --- MATH ---
def get_atr(df, n=14):
    tr = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift(1)), abs(df['Low']-df['Close'].shift(1))], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def get_rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = d.where(d < 0, 0).abs().rolling(n).mean()
    return 100 - (100 / (1 + (g/(l + 1e-9))))

# --- ENGINE ---
def scan_confluence(row):
    try:
        symbol, sector = row[0], row[1]
        ticker = f"{str(symbol).strip()}.NS"
        
        # Download data (shorter period for speed in GH Actions)
        df = yf.download(ticker, period="1y", progress=False, auto_adjust=True)
        if df is None or len(df) < 50: return None
        
        # Flatten Multi-Index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        c = df['Close'].astype(float)
        score, signals = 0, []
        
        # 1. SQZ (Squeeze)
        sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
        if (sma20 + (2*std20)).iloc[-1] < (sma20 + (1.5*get_atr(df, 20))).iloc[-1]:
            score += 1; signals.append("SQZ")
            
        # 2. RSI (Strength)
        if get_rsi(c).iloc[-1] > 55:
            score += 1; signals.append("RSI")

        # 3. GUP (Guppy)
        if c.ewm(span=8).mean().iloc[-1] > c.ewm(span=21).mean().iloc[-1]:
            score += 1; signals.append("GUP")

        # 4. Momentum (Simple VAM)
        if c.iloc[-1] > sma20.iloc[-1]:
            score += 1; signals.append("MOM")

        # Upside Estimation
        drift = ((c.iloc[-1]/c.iloc[0])-1)/len(df)
        upside = round(drift * 30 * 100, 2)

        if score >= 2:
            return {'s': symbol, 'sc': score, 'up': upside, 'sig': "+".join(signals), 'sec': sector}
    except Exception as e:
        return None

def run_master():
    start_time = datetime.now()
    send_msg(f"🛰 *KRONOS:* Scan started at {start_time.strftime('%H:%M')} IST")
    
    try:
        df_csv = pd.read_csv(CSV_NAME)
        df_csv.columns = df_csv.columns.str.strip()
        # Fallback for column names
        s_col = 'Symbol' if 'Symbol' in df_csv.columns else df_csv.columns[0]
        i_col = 'Industry' if 'Industry' in df_csv.columns else df_csv.columns[-1]
        tickers = df_csv[[s_col, i_col]].values.tolist()
    except Exception as e:
        send_msg(f"❌ *CSV Error:* {str(e)}")
        return

    results = []
    # Using 10 workers to stay under GitHub rate limits
    with ThreadPoolExecutor(max_workers=10) as executor:
        for res in executor.map(scan_confluence, tickers):
            if res: 
                results.append(res)
                print(f"Match: {res['s']} ({res['sc']})")

    if not results:
        send_msg("📡 *KRONOS:* Scan complete. No high-confluence setups found.")
        return

    # Create Report
    final_df = pd.DataFrame(results).sort_values(['sc', 'up'], ascending=False)
    
    report = f"🏆 *KRONOS MASTER SCAN: {datetime.now().strftime('%d %b')}*\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Sector Exposure
    report += "🔥 *SECTOR FLOW*\n"
    sec_data = final_df['sec'].value_counts(normalize=True).head(3) * 100
    for sec, val in sec_data.items():
        report += f"• {sec}: {val:.1f}%\n"
    report += "\n"

    # Top 20 Stocks
    for _, r in final_df.head(20).iterrows():
        icon = "💎" if r['sc'] >= 4 else "🔥"
        report += f"{icon} `{r['s']}`: *Score {r['sc']}* | {r['up']}% Est | {r['sig']}\n"

    # TradingView List
    tv_list = ",".join([f"NSE:{s}" for s in final_df['s'].head(25)])
    report += f"\n📺 *WATCHLIST*\n`{tv_list}`"
    
    send_msg(report)

if __name__ == "__main__":
    run_master()
