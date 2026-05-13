import os
import json
import http.client
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from nselib import capital_market

# --- SYSTEM FIX ---
yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
CSV_NAME = "ind_nifty500list.csv"

def send_msg(text):
    if not MY_TOKEN or not MY_CHAT_ID: 
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
        payload = json.dumps({
            "chat_id": str(MY_CHAT_ID).strip(),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN.strip()}/sendMessage", payload, headers)
        conn.getresponse()
        conn.close()
    except: 
        pass

# --- INDICATORS ---
def get_atr(df, n=14):
    tr = pd.concat([
        df['High'] - df['Low'], 
        abs(df['High'] - df['Close'].shift(1)), 
        abs(df['Low'] - df['Close'].shift(1))
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def get_rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = d.where(d < 0, 0).abs().rolling(n).mean()
    return 100 - (100 / (1 + (g / (l + 1e-9))))

def fetch_delivery_percentage(symbol, days=5):
    """Fetches historical deliverable data directly from the NSE website."""
    try:
        end_dt = datetime.now()
        # 14 calendar days buffer ensures we find 5 active trading sessions
        start_dt = end_dt - timedelta(days=14) 
        
        from_str = start_dt.strftime('%d-%m-%Y')
        to_str = end_dt.strftime('%d-%m-%Y')
        
        raw_df = capital_market.price_volume_and_deliverable_position_data(
            symbol=symbol, from_date=from_str, to_date=to_str
        )
        if raw_df is None or raw_df.empty:
            return 0.0
            
        raw_df.columns = raw_df.columns.str.strip()
        del_col = [c for c in raw_df.columns if 'Dly' in c or 'Deliverable' in c]
        if not del_col:
            return 0.0
            
        raw_df[del_col] = pd.to_numeric(raw_df[del_col], errors='coerce')
        recent_delivery = raw_df[del_col].dropna().tail(days)
        
        return round(recent_delivery.mean(), 1) if not recent_delivery.empty else 0.0
    except:
        return 0.0

# --- SCANNER CORE ---
def scan_confluence(row):
    try:
        # FIXED: Proper indexing to unpack the ticker list correctly
        symbol = str(row[0]).strip()
        sector = str(row[1]).strip()
        ticker = f"{symbol}.NS"
        
        df = yf.download(ticker, period="2y", progress=False, auto_adjust=True, timeout=15)
        if df is None or len(df) < 250: 
            return None
            
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
            
        c = df['Close'].squeeze()
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        c = c.astype(float)
        
        score, signals = 0, []
        sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
        atr20 = get_atr(df, 20)

        # 1. SQZ (Squeeze)
        if (sma20 + (2 * std20)).iloc[-1] < (sma20 + (1.5 * atr20)).iloc[-1]:
            score += 1
            signals.append("SQZ")
            
        # 2. ULT (Volatility Compression)
        bw = (std20 * 4) / (sma20 + 1e-9)
        if bw.iloc[-1] <= bw.tail(21).min():
            score += 1
            signals.append("ULT")

        # 3. RSI (Strength)
        if get_rsi(c).iloc[-1] > 55:
            score += 1
            signals.append("RSI")

        # 4. GUP (Guppy Breakout)
        if c.ewm(span=8).mean().iloc[-1] > c.ewm(span=21).mean().iloc[-1]:
            score += 1
            signals.append("GUP")

        # 5. VAM (Volatility Adjusted Momentum)
        if c.iloc[-1] > (sma20.iloc[-1] + (atr20.iloc[-1] * 1.5)):
            score += 1
            signals.append("VAM")

        drift = (((c.iloc[-1] / c.iloc[-250]) - 1) / 250 * 0.7) + (((c.iloc[-1] / c.iloc[-20]) - 1) / 20 * 0.3)
        upside = round(((c.iloc[-1] * (1 + (drift * 30)) - c.iloc[-1]) / c.iloc[-1]) * 100, 2)

        if upside > 0 and score >= 2:
            del_pct = fetch_delivery_percentage(symbol, days=5)
            return {'s': symbol, 'sc': score, 'up': upside, 'sig': "+".join(signals), 'sec': sector, 'del': del_pct}
    except: 
        return None

def run_master():
    send_msg(f"🛰 *KRONOS:* Friday Master Scan started (2Y History + 5D Delivery Highlighting)...")
    
    try:
        df_csv = pd.read_csv(CSV_NAME)
        df_csv.columns = df_csv.columns.str.strip()
        s_col = 'Symbol' if 'Symbol' in df_csv.columns else df_csv.columns[0]
        i_col = 'Industry' if 'Industry' in df_csv.columns else df_csv.columns[-1]
        tickers = df_csv[[s_col, i_col]].values.tolist()
    except Exception as e:
        send_msg(f"⚠️ *KRONOS ERROR:* Could not read CSV file `{CSV_NAME}`. Exiting scan.")
        return

    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        for res in executor.map(scan_confluence, tickers):
            if res: 
                results.append(res)

    if not results:
        send_msg("📡 *KRONOS:* Scan complete. No positive-upside setups found.")
        return

    final_df = pd.DataFrame(results).sort_values(['sc', 'up'], ascending=False)
    
    report = f"🏆 *KRONOS MASTER SCAN: {datetime.now().strftime('%d %b')}*\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    report += "🔥 *SECTOR FLOW*\n"
    sec_data = final_df['sec'].value_counts(normalize=True).head(3) * 100
    for sec, val in sec_data.items():
        report += f"• {sec}: {val:.1f}%\n"
    report += "\n"

    for _, r in final_df.head(20).iterrows():
        # Choose baseline icon based on confluence score
        icon = "💎" if r['sc'] >= 4 else "🔥"
        
        # ADDED FEATURE: Highlight strong accumulation targets with over 50% 5D Delivery
        if r['del'] >= 50.0:
            del_alert = f" | 🚀 *5D Del: {r['del']}%*"
        elif r['del'] > 0:
            del_alert = f" | 📦 *5D Del: {r['del']}%*"
        else:
            del_alert = ""
            
        report += f"{icon} `{r['s']}`: *Score {r['sc']}* | {r['up']}% Est | {r['sig']}{del_alert}\n"

    tv_list = ",".join([f"NSE:{s}" for s in final_df['s'].head(25)])
    report += f"\n📺 *WATCHLIST*\n`{tv_list}`"
    
    send_msg(report)

if __name__ == "__main__":
    run_master()
