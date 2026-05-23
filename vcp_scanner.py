import http.client, json, os, pandas as pd, numpy as np, yfinance as yf
from datetime import datetime, timedelta

# --- CONFIG (Matches Whale Environment Pattern) ---
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

def run_kronos_upside(ticker_symbol):
    """Calculates a 30-day projected Upside % using random path drifting."""
    try:
        df = yf.download(ticker_symbol + ".NS", period="2y", progress=False, auto_adjust=True)
        if df.empty: return 0.0
        close = df['Close'].squeeze()
        cp = float(close.iloc[-1])
        vol, drift = close.pct_change().dropna().std(), (cp - close.iloc[-60]) / (close.iloc[-60] * 60)
        paths = [cp * np.cumprod(1 + np.random.normal(drift, vol, 30)) for _ in range(100)]
        upside = ((np.mean([p[-1] for p in paths]) - cp) / cp) * 100
        return round(upside, 1)
    except: 
        return 0.0

def scan_vcp_setup(ticker_symbol):
    """
    Applies strict visual image constraints to isolate Element 4 tight consolidations.
    """
    try:
        ticker = yf.Ticker(ticker_symbol + ".NS")
        df = ticker.history(period="252d") # Expanded lookback to extract true 52-week metrics
        if len(df) < 50:
            return None
        
        # Calculate structural trends and volatility baselines
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['Vol_SMA50'] = df['Volume'].rolling(window=50).mean()
        df['Range_Pct'] = (df['High'] - df['Low']) / df['Low']
        
        # Filter 1: Isolate the rightmost 4-day contraction pivot zone
        pivot_zone = df.tail(4)
        highest_high = pivot_zone['High'].max()
        lowest_low = pivot_zone['Low'].min()
        
        # Core Formula Metrics
        total_compression = (highest_high - lowest_low) / lowest_low
        avg_candle_tightness = pivot_zone['Range_Pct'].mean()
        volume_dryness = pivot_zone['Volume'].mean() / df['Vol_SMA50'].iloc[-1]
        
        # Filter 2: Evaluation Rules (Image constraints)
        is_compressed = total_compression < 0.035 and avg_candle_tightness < 0.02
        is_volume_dried = volume_dryness < 0.65
        is_in_uptrend = df['Close'].iloc[-1] >= df['SMA_20'].iloc[-1]
        
        # Filter 3: Minervini structural filter (Must sit within 5% of its 52-week High ceiling)
        fifty_two_week_high = df['High'].max()
        is_near_high = (df['Close'].iloc[-1] / fifty_two_week_high) >= 0.95
        
        if is_compressed and is_volume_dried and is_in_uptrend and is_near_high:
            # Set protective entry/stop execution thresholds (Indian Rupee offsets)
            entry = round(highest_high + 0.05, 2)
            stop = round(lowest_low - 0.05, 2)
            
            # Run the Upside Projection Engine instead of a fixed target calculation
            upside_pct = run_kronos_upside(ticker_symbol)
            
            return {
                "Symbol": ticker_symbol,
                "Entry": entry,
                "Stop": stop,
                "Upside": f"{upside_pct:>+5}%",
                "Range": f"{total_compression * 100:.1f}%",
                "Volume": f"{volume_dryness * 100:.0f}%"
            }
    except:
        return None 
    return None

def run_scan():
    print("🚀 Running Minervini VCP Element 4 + Kronos Upside Scan...")
    n500_list = pd.read_csv(MANUAL_N500_CSV)['Symbol'].dropna().unique().tolist()
    
    matches = []
    for sym in n500_list:
        res = scan_vcp_setup(sym)
        if res:
            matches.append(res)
            
    if not matches:
        print("✅ Analysis Complete: No VCP setups found today.")
        return

    # Build Report matching your Monospace layout exactly
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🔥 *VCP ELEMENT 4 SCANNER ({target_date})*\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += "`Ticker      Entry     Stop      Upside`\n"

    for row in matches:
        sym = row['Symbol']
        entry = row['Entry']
        stop = row['Stop']
        upside = row['Upside']
        
        msg += f"`{sym:<11} {entry:<9} {stop:<9} {upside:<9}` 📈\n"
        msg += f"↳ _Pivot Range: {row['Range']} | Vol: {row['Volume']} of normal_\n\n"

    msg += "━━━━━━━━━━━━━━━━━━━━\n🎯 *Focus:* Tight Final Contraction + Projected Upside %"
    send_telegram(msg)
    print("✅ Analysis Sent.")

if __name__ == "__main__":
    run_scan()
