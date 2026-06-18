import http.client, json, os, pandas as pd, numpy as np, yfinance as yf
import warnings
from datetime import datetime, timedelta

# --- WARNING FILTERS (Cleans log clutter in environment) ---
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

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
    """Calculates a 30-day projected Upside % and Stop-Loss Hit Probability using decayed drift."""
    try:
        df = yf.download(ticker_symbol + ".NS", period="2y", progress=False, auto_adjust=True)
        if df.empty or len(df) < 30: return 0.0, 0.0
        close = df['Close'].squeeze().astype(float)
        high = df['High'].squeeze().astype(float)
        low = df['Low'].squeeze().astype(float)
        cp = float(close.iloc[-1])
        
        # 1. Compute ATR to establish stop floor
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        stop_loss = cp - (1.5 * atr)
        
        # 2. Compute drift and volatility
        vol = close.pct_change().dropna().std()
        drift = (cp - close.iloc[-60]) / (close.iloc[-60] * 60)
        
        # 3. Path simulation with exponential drift decay
        paths = []
        stopped_out_count = 0
        num_paths = 100
        days = 30
        
        for _ in range(num_paths):
            path = np.zeros(days)
            current_sim_price = cp
            path_stopped = False
            
            for t in range(days):
                decayed_drift = drift * np.exp(-t / 10.0)
                shock = np.random.normal(decayed_drift, vol)
                current_sim_price *= (1 + shock)
                path[t] = current_sim_price
                if current_sim_price <= stop_loss:
                    path_stopped = True
            
            paths.append(path)
            if path_stopped:
                stopped_out_count += 1
                
        final_prices = [p[-1] for p in paths]
        mean_final = np.mean(final_prices)
        upside = ((mean_final - cp) / cp) * 100
        stop_hit_prob = (stopped_out_count / num_paths) * 100
        return round(upside, 1), round(stop_hit_prob, 1)
    except: 
        return 0.0, 0.0

def scan_vcp_setup(ticker_symbol):
    """
    Applies strict visual image constraints to isolate Element 4 tight consolidations.
    Returns (result_dict, is_near_miss).
    """
    try:
        ticker = yf.Ticker(ticker_symbol + ".NS")
        df = ticker.history(period="252d")
        if len(df) < 50:
            return None, False
        
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['Vol_SMA50'] = df['Volume'].rolling(window=50).mean()
        df['Range_Pct'] = (df['High'] - df['Low']) / df['Low']
        
        pivot_zone = df.tail(4)
        highest_high = pivot_zone['High'].max()
        lowest_low = pivot_zone['Low'].min()
        
        total_compression = (highest_high - lowest_low) / lowest_low
        avg_candle_tightness = pivot_zone['Range_Pct'].mean()
        volume_dryness = pivot_zone['Volume'].mean() / df['Vol_SMA50'].iloc[-1]
        
        # --- Strict Core Rules ---
        is_compressed = total_compression < 0.035 and avg_candle_tightness < 0.02
        is_volume_dried = volume_dryness < 0.65
        is_in_uptrend = df['Close'].iloc[-1] >= df['SMA_20'].iloc[-1]
        
        fifty_two_week_high = df['High'].max()
        is_near_high = (df['Close'].iloc[-1] / fifty_two_week_high) >= 0.95
        
        # --- Near Miss Relaxed Rules ---
        near_compressed = total_compression < 0.048 and avg_candle_tightness < 0.025
        near_volume = volume_dryness < 0.85
        near_high = (df['Close'].iloc[-1] / fifty_two_week_high) >= 0.92
        
        entry = round(highest_high + 0.05, 2)
        stop = round(lowest_low - 0.05, 2)
        
        # Check Strict Criteria First
        if is_compressed and is_volume_dried and is_in_uptrend and is_near_high:
            upside_pct, stop_hit_prob = run_kronos_upside(ticker_symbol)
            return {
                "Symbol": ticker_symbol, "Entry": entry, "Stop": stop,
                "Upside": f"{upside_pct:>+5}%", "SHP": f"{stop_hit_prob}%", "Range": f"{total_compression * 100:.1f}%",
                "Volume": f"{volume_dryness * 100:.0f}%"
            }, False
            
        # Check Near Miss Filter Next
        if near_compressed and near_volume and is_in_uptrend and near_high:
            upside_pct, stop_hit_prob = run_kronos_upside(ticker_symbol)
            return {
                "Symbol": ticker_symbol, "Entry": entry, "Stop": stop,
                "Upside": f"{upside_pct:>+5}%", "SHP": f"{stop_hit_prob}%", "Range": f"{total_compression * 100:.1f}%",
                "Volume": f"{volume_dryness * 100:.0f}%"
            }, True
            
    except:
        return None, False 
    return None, False

def run_scan():
    print("🚀 Running Minervini VCP Element 4 + Kronos Upside Scan...")
    
    if not os.path.exists(MANUAL_N500_CSV):
        print(f"❌ Error: {MANUAL_N500_CSV} not found.")
        return
        
    df_csv = pd.read_csv(MANUAL_N500_CSV)
    n500_list = df_csv['Symbol'].dropna().unique().tolist()
    print(f"📊 Verified Input Database: Processing {len(n500_list)} active tickers.")
    
    strict_matches = []
    near_matches = []
    
    for sym in n500_list:
        res, is_miss = scan_vcp_setup(sym)
        if res:
            if is_miss:
                near_matches.append(res)
            else:
                strict_matches.append(res)
            
    if not strict_matches and not near_matches:
        print("✅ Analysis Complete: No matching setups detected.")
        return

    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🔥 *VCP ELEMENT 4 SCANNER ({target_date})*\n"
    msg += f"📊 _Processed Tickers: {len(n500_list)}_\n━━━━━━━━━━━━━━━━━━━━\n"
    
    if strict_matches:
        msg += "`Ticker      Entry     Stop      Upside`\n"
        for row in strict_matches:
            msg += f"`{row['Symbol']:<11} {row['Entry']:<9} {row['Stop']:<9} {row['Upside']:<9}` 📈\n"
            msg += f"↳ _Pivot Range: {row['Range']} | Vol: {row['Volume']} of normal | SHP: {row['SHP']}_\n\n"
    else:
        msg += "⚠️ _No pristine Element 4 setups met all strict parameters._\n\n"

    # Fallback Mechanism Activation
    if near_matches and len(strict_matches) < 3:
        msg += "⏳ *NEAR MISS RUNNER-UPS (Relaxed Filters)*\n━━━━━━━━━━━━━━━━━━━━\n"
        msg += "`Ticker      Entry     Stop      Upside`\n"
        # Display up to 5 best near matches to avoid Telegram text truncation
        for row in near_matches[:5]:
            msg += f"`{row['Symbol']:<11} {row['Entry']:<9} {row['Stop']:<9} {row['Upside']:<9}` 👀\n"
            msg += f"↳ _Pivot Range: {row['Range']} | Vol: {row['Volume']} of normal | SHP: {row['SHP']}_\n\n"

    msg += "━━━━━━━━━━━━━━━━━━━━\n🎯 *Focus:* Tight Final Contraction + Projected Upside %"
    send_telegram(msg)
    print("✅ Analysis Sent to Telegram.")

if __name__ == "__main__":
    run_scan()
