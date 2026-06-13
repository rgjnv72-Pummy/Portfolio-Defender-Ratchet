import os
import json
import http.client
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
    """Fetches and isolates the true percentage column from NSE data."""
    try:
        raw_df = capital_market.price_volume_and_deliverable_position_data(symbol=symbol, period='1M')
        if raw_df is None or raw_df.empty:
            return "N/A"
            
        raw_df.columns = raw_df.columns.str.strip()
        
        # FIXED: Targets the true percentage ratio column instead of raw share volume
        pct_col = [c for c in raw_df.columns if '%' in c or 'ToTradedQty' in c or 'Percentage' in c]
        
        if not pct_col:
            # Fallback strategy if column structures change
            pct_col = [c for c in raw_df.columns if 'Dly' in c or 'Deliverable' in c]
            if len(pct_col) > 1:
                pct_col = [pct_col[-1]] # Usually percentage is the last column layout
                
        target_col = pct_col[0]
        raw_df[target_col] = pd.to_numeric(raw_df[target_col], errors='coerce')
        recent_delivery = raw_df[target_col].dropna().tail(days)
        
        if recent_delivery.empty:
            return "N/A"
            
        final_val = round(recent_delivery.mean(), 1)
        # Final safety catch to prevent raw share volume leakages
        return final_val if final_val <= 100.0 else "N/A"
    except:
        return "N/A"

# --- SCANNER CORE ---
def scan_confluence(item):
    try:
        symbol = str(item['Symbol']).strip()
        sector = str(item['Industry']).strip()
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

        # 6. VIB (Vibrancy - Log Spread skew)
        ret = np.log(c / c.shift(1))
        # Captures the bullish skew in volatility over a 3-month (63-day) lookback
        v_spread = ret.clip(lower=0).tail(63).std() - ret.clip(upper=0).tail(63).std()
        if v_spread > 0.01:
            score += 1
            signals.append("VIB")

        drift = (((c.iloc[-1] / c.iloc[-250]) - 1) / 250 * 0.7) + (((c.iloc[-1] / c.iloc[-20]) - 1) / 20 * 0.3)
        upside = round(((c.iloc[-1] * (1 + (drift * 30)) - c.iloc[-1]) / c.iloc[-1]) * 100, 2)

        if upside > 0 and score >= 2:
            del_pct = fetch_delivery_percentage(symbol, days=5)
            return {'s': symbol, 'sc': score, 'up': upside, 'sig': "+".join(signals), 'sec': sector, 'del': del_pct}
    except: 
        return None

def run_master():
    send_msg(f"🛰 *KRONOS:* Friday Master Scan started (Delivery Column Ratio Fix)...")
    
    try:
        df_csv = pd.read_csv(CSV_NAME)
        df_csv.columns = df_csv.columns.str.strip()
        
        # FIXED: Comprehensive header detection to support standard NSE CSV variations
        s_col = [c for c in df_csv.columns if 'Symbol' in c or 'Ticker' in c][0]
        i_col = [c for c in df_csv.columns if 'Industry' in c or 'Sector' in c or 'Category' in c][0]
        
        tickers_df = df_csv[[s_col, i_col]].rename(columns={s_col: 'Symbol', i_col: 'Industry'})
        items_list = tickers_df.to_dict(orient='records')
    except Exception as e:
        send_msg(f"⚠️ *KRONOS ERROR:* Could not parse CSV headers. Verify 'Symbol' and 'Industry' columns exist.")
        return

    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for res in executor.map(scan_confluence, items_list):
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
        icon = "💎" if r['sc'] >= 4 else "🔥"
        
        if isinstance(r['del'], (int, float)):
            if r['del'] >= 50.0:
                del_alert = f" | 🚀 *5D Del: {r['del']}%*"
            else:
                del_alert = f" | 📦 *5D Del: {r['del']}%*"
        else:
            del_alert = f" | 📦 *5D Del: {r['del']}*"
            
        report += f"{icon} `{r['s']}`: *Score {r['sc']}* | {r['up']}% Est | {r['sig']}{del_alert}\n"

    tv_list = ",".join([f"NSE:{s}" for s in final_df['s'].head(25)])
    report += f"\n📺 *WATCHLIST*\n`{tv_list}`"
    
    send_msg(report)

if __name__ == "__main__":
    run_master()
