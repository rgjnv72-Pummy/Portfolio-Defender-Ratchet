import http.client, json, os, pandas as pd, numpy as np, yfinance as yf
from datetime import datetime, timedelta

# --- CONFIG (Matches Whale Pattern exactly) ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
MANUAL_N500_CSV = 'ind_nifty500list.csv'

def send_telegram(text):
    if not TOKEN or not CHAT_ID: return
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
    finally: conn.close()

def scan_vcp_setup(ticker_symbol):
    """
    Applies the image constraints to filter for active Element 4 consolidations.
    """
    try:
        ticker = yf.Ticker(ticker_symbol + ".NS")
        df = ticker.history(period="60d")
        if len(df) < 50:
            return None
        
        # Calculate moving baselines
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['Vol_SMA50'] = df['Volume'].rolling(window=50).mean()
        df['Range_Pct'] = (df['High'] - df['Low']) / df['Low']
        
        # Analyze right side of the base (4-day pivot zone)
        pivot_zone = df.tail(4)
        highest_high = pivot_zone['High'].max()
        lowest_low = pivot_zone['Low'].min()
        
        # Core Rules Verification (From your uploaded images)
        total_compression = (highest_high - lowest_low) / lowest_low
        avg_candle_tightness = pivot_zone['Range_Pct'].mean()
        volume_dryness = pivot_zone['Volume'].mean() / df['Vol_SMA50'].iloc[-1]
        
        is_compressed = total_compression < 0.035 and avg_candle_tightness < 0.02
        is_volume_dried = volume_dryness < 0.65
        is_in_uptrend = df['Close'].iloc[-1] >= df['SMA_20'].iloc[-1]
        
        if is_compressed and is_volume_dried and is_in_uptrend:
            # Format trade metrics (using Indian Rupee tick sizes)
            entry = round(highest_high + 0.05, 2) # Buffer above high
            stop = round(lowest_low - 0.05, 2)   # Buffer below low
            risk = entry - stop
            risk_pct = (risk / entry) * 100
            target = round(entry + (risk * 3), 2)
            
            return {
                "Symbol": ticker_symbol,
                "Entry": entry,
                "Stop": stop,
                "Risk": f"₹{risk:.2f} ({risk_pct:.2f}%)",
                "Target": target,
                "Range": f"{total_compression * 100:.1f}%",
                "Volume": f"{volume_dryness * 100:.0f}%"
            }
    except:
        return None 
    return None

def run_scan():
    print("🚀 Running Minervini VCP Element 4 Scan...")
    n500_list = pd.read_csv(MANUAL_N500_CSV)['Symbol'].dropna().unique().tolist()
    
    matches = []
    for sym in n500_list:
        res = scan_vcp_setup(sym)
        if res:
            matches.append(res)
            
    if not matches:
        print("✅ Analysis Complete: No VCP setups found today.")
        return

    # Build Report (Formatted strictly to match Whale Monospace markdown alignment layout)
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🔥 *VCP ELEMENT 4 SCANNER ({target_date})*\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += "`Ticker      Entry     Stop      Target`\n"

    for row in matches:
        sym = row['Symbol']
        entry = row['Entry']
        stop = row['Stop']
        target = row['Target']
        
        msg += f"`{sym:<11} {entry:<9} {stop:<9} {target:<9}` 📈\n"
        msg += f"↳ _Pivot Range: {row['Range']} | Vol: {row['Volume']} of normal_\n\n"

    msg += "━━━━━━━━━━━━━━━━━━━━\n🎯 *Focus:* Tight Final Contraction + Dry Volume"
    send_telegram(msg)
    print("✅ Analysis Sent.")

if __name__ == "__main__":
    run_scan()
