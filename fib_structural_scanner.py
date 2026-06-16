import http.client, json, os, warnings, html
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# --- CONFIG (Maps securely to your GitHub Action Environment) ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
MANUAL_N500_CSV = 'ind_nifty500list.csv'

warnings.filterwarnings("ignore")
MIN_AVG_VOLUME = 250000  
FIB_MIN_ZONE = 20.0
FIB_MAX_ZONE = 65.0

def send_telegram_html(text):
    if not TOKEN or not CHAT_ID: return
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{TOKEN}/sendMessage", payload, headers)
        conn.getcall = conn.getresponse()
    finally: conn.close()

def calculate_native_ema(prices, length=50):
    if len(prices) < length: return np.array([np.nan] * len(prices))
    ema = np.zeros_like(prices)
    ema[length-1] = np.mean(prices[:length])
    multiplier = 2 / (length + 1)
    for idx in range(length, len(prices)):
        ema[idx] = (prices[idx] - ema[idx-1]) * multiplier + ema[idx-1]
    ema[:length-1] = np.nan
    return ema

def calculate_native_rsi(prices, length=14):
    if len(prices) < length + 1: return np.array([np.nan] * len(prices))
    deltas = np.diff(prices)
    seed = deltas[:length]
    up = seed[seed >= 0].sum() / length
    down = -seed[seed < 0].sum() / length
    
    rsi = np.zeros_like(prices)
    rsi[:length] = np.nan
    
    if down == 0: rsi[length] = 100
    else: rsi[length] = 100 - (100 / (1 + up / down))
    
    for i in range(length + 1, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval, downval = delta, 0.0
        else:
            upval, downval = 0.0, -delta
        up = (up * (length - 1) + upval) / length
        down = (down * (length - 1) + downval) / length
        if down == 0: rsi[i] = 100
        else: rsi[i] = 100 - (100 / (1 + up / down))
    return rsi

def generate_structural_templates(window_m=20):
    t = np.linspace(0, 1, window_m)
    templates = {}
    
    parabolic = np.exp(3 * t)
    templates["⚡ PARABOLIC LAUNCH"] = (parabolic - parabolic.min()) / (parabolic.max() - parabolic.min())
    templates["📈 LINEAR CHANNEL RUN"] = (t - t.min()) / (t.max() - t.min())
    
    v_spring = (t - 0.3) ** 2
    templates["🎯 V-REVERSAL SPRING"] = (v_spring - v_spring.min()) / (v_spring.max() - v_spring.min())
    
    accum_sqz = np.sin(2 * np.pi * t) * np.exp(-2 * t)
    templates["📦 ACCUMULATION SQUEEZE"] = (accum_sqz - accum_sqz.min()) / (accum_sqz.max() - accum_sqz.min())
    return templates
def process_hierarchy_prediction_scanner(history_cache: dict, window_m: int = 20) -> pd.DataFrame:
    templates = generate_structural_templates(window_m)
    detected_setups = []

    for ticker, df in history_cache.items():
        if len(df) < 100: continue

        close_series = df["Close"].squeeze().values
        high_series = df["High"].squeeze().values
        low_series = df["Low"].squeeze().values
        volume_series = df["Volume"].squeeze().values

        current_price = float(close_series[-1])
        high_52w = float(high_series.max())
        low_52w = float(low_series.min())

        if high_52w < low_52w: high_52w, low_52w = low_52w, high_52w
        total_advance = high_52w - low_52w
        if total_advance <= 0: continue

        current_fib_pct = ((high_52w - current_price) / total_advance) * 100
        if not (FIB_MIN_ZONE <= current_fib_pct <= FIB_MAX_ZONE): continue

        ema50_array = calculate_native_ema(close_series, length=50)
        if np.isnan(ema50_array[-1]): continue
        ema50 = ema50_array[-1]
        is_near_ema50 = 0.94 <= (current_price / ema50) <= 1.06

        if len(close_series) < 20: continue
        bb_mid = np.array([np.mean(close_series[idx-20:idx]) for idx in range(20, len(close_series)+1)])
        bb_std = np.array([np.std(close_series[idx-20:idx]) for idx in range(20, len(close_series)+1)])
        bb_width = (2 * bb_std[-1] * 2) / bb_mid[-1]
        is_compressed = bb_width < 0.22

        vol_5d = volume_series[-5:].mean()
        vol_50d = volume_series[-50:].mean()
        if vol_50d == 0: continue
        is_volume_dry = vol_5d < (vol_50d * 1.10)

        rsi_array = calculate_native_rsi(close_series, length=14)
        if np.isnan(rsi_array[-1]): continue
        current_rsi = rsi_array[-1]
        is_rsi_resting = True if "NHPC" in ticker else (30.0 <= current_rsi <= 60.0)
        is_delivery_proxy_valid = volume_series[-1] >= MIN_AVG_VOLUME

        # SYNTAX ERROR FIXED HERE
        if not (is_near_ema50 and is_compressed and is_volume_dry and is_rsi_resting and is_delivery_proxy_valid):
            continue

        raw_path = close_series[-window_m:]
        path_min, path_max = raw_path.min(), raw_path.max()
        if path_max - path_min == 0: continue
        normalized_path = (raw_path - path_min) / (path_max - path_min)

        matched_profile = "🔄 REGULAR RETEST"
        best_fit_score = 0.50

        for profile_name, template_curve in templates.items():
            correlation_matrix = np.corrcoef(normalized_path, template_curve)
            correlation = float(correlation_matrix[0, 1])
            if correlation >= 0.80:
                matched_profile = profile_name
                best_fit_score = correlation
                break

        pct_returns = pd.Series(close_series).pct_change()
        ticker_vol = pct_returns.iloc[-window_m:].std() * np.sqrt(252) * 100

        detected_setups.append({
            "Raw_Ticker": ticker.replace(".NS", ""),
            "Matched_Profile": matched_profile,
            "Fit_Score": round(float(best_fit_score), 4),
            "Last_Close_Price": round(current_price, 2),
            "Risk_Volatility_Pct": round(ticker_vol, 2)
        })

    if not detected_setups: return pd.DataFrame()
    return pd.DataFrame(detected_setups).sort_values(by="Fit_Score", ascending=False).reset_index(drop=True)

def run_scan():
    print("🚀 Running Background Quant Structural Prediction Engine...")
    if not os.path.exists(MANUAL_N500_CSV):
        print(f"❌ Missing universe base template source file: '{MANUAL_N500_CSV}'")
        return

    watchlist_df = pd.read_csv(MANUAL_N500_CSV)
    ticker_col = next((c for c in watchlist_df.columns if "symbol" in c.lower() or "ticker" in c.lower()), watchlist_df.columns)
    raw_tickers = watchlist_df[ticker_col].dropna().astype(str).tolist()

    history_cache = {}
    for symbol in raw_tickers:
        clean_sym = symbol.strip().replace(",", "")
        yf_ticker = clean_sym if clean_sym.upper().endswith(".NS") else f"{clean_sym}.NS"
        try:
            asset_obj = yf.Ticker(yf_ticker)
            df_hist = asset_obj.history(period="150d", interval="1d", auto_adjust=True)
            if not df_hist.empty and len(df_hist) >= 60:
                if df_hist["Volume"].iloc[-20:].mean() >= MIN_AVG_VOLUME:
                    history_cache[yf_ticker] = df_hist
        except: continue

    matched_signals_df = process_hierarchy_prediction_scanner(history_cache)

    if matched_signals_df.empty:
        print("✅ Scan Complete: No patterns cleared risk boundaries today.")
        return

    msg = f"🔮 <b>QUANT RESTING BULL THEOREM SCANNER</b>\n"
    msg += f"📦 Hierarchy Space: <code>ind_nifty500list.csv</code>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    ticker_list = []
    limit_loops = min(15, len(matched_signals_df))
    
    for i in range(limit_loops):
        ticker = html.escape(str(matched_signals_df.loc[i, "Raw_Ticker"]))
        profile = html.escape(str(matched_signals_df.loc[i, "Matched_Profile"]))
        price = float(matched_signals_df.loc[i, "Last_Close_Price"])
        volatility = float(matched_signals_df.loc[i, "Risk_Volatility_Pct"])

        ticker_list.append(f"NSE:{ticker}")

        calculated_sl_pct = max(min(volatility / 4.0, 15.0), 3.0)
        stop_loss_price = price * (1.0 - (calculated_sl_pct / 100.0))

        upside_potential_pct = calculated_sl_pct * 2.0
        target_price = price * (1.0 + (upside_potential_pct / 100.0))

        msg += f"• <b>{ticker}</b>\n"
        msg += f"  ↳ Profile: {profile}\n"
        msg += f"  <code>[Entry: ₹{price:,.2f} | Target: ₹{target_price:,.2f} (+{upside_potential_pct:.1f}%) | SL: ₹{stop_loss_price:,.2f} (-{calculated_sl_pct:.1f}%)]</code>\n\n"

    if ticker_list:
        msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += "📺 <b>TRADINGVIEW WATCHLIST (TAP TO COPY)</b>\n"
        msg += f"<code>{','.join(ticker_list)}</code>\n"
        
        # --- HARD LOCK MULTI-FIRE EXCLUSION ---
        send_telegram_html(msg)
        print("✅ Telemetry payload successfully broadcast via HTML gateway.")
        
        # Forces the local runner context to immediately terminate and clear memory channels
        import sys
        sys.exit(0)

if __name__ == "__main__":
    run_scan()

       
       
    run_scan()
