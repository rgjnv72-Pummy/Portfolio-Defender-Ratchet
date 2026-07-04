import json
import os
import urllib3
import warnings
import numpy as np
import pandas as pd
import requests
from tqdm import tqdm
import yfinance as yf
import pandas_ta as ta

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = (os.getenv('TELEGRAM_CHAT_ID') or '1280803679').strip()
MY_TOKEN = (os.getenv('TELEGRAM_TOKEN') or '8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o').strip()
CSV_NAME = "ind_nifty500list.csv"

# --- STRATEGY PARAMETERS ---
EMA_TREND_PERIOD = 200
MIN_AVG_VOLUME = 100000
MAX_STOCKS_PER_SECTOR = 5

class AdvancedKalmanFilter:
    def __init__(self, process_noise=1e-4, measurement_noise=1e-2):
        self.Q = process_noise
        self.R = measurement_noise

    def execute_estimation(self, prices):
        n = len(prices)
        state_means = np.zeros(n)
        state_vars = np.zeros(n)
        # Fix: Ensure current_x is initialized to a scalar (the first price) instead of the entire array
        current_x = prices[0] if len(prices) > 0 else 0
        current_P = self.R

        for t in range(n):
            predicted_x = current_x
            predicted_P = current_P + self.Q

            innovation = prices[t] - predicted_x
            innovation_var = predicted_P + self.R
            kalman_gain = predicted_P / innovation_var

            current_x = predicted_x + kalman_gain * innovation
            current_P = (1 - kalman_gain) * predicted_P

            state_means[t] = current_x
            state_vars[t] = current_P

        return state_means, state_vars

def normalize_nse_industry(raw_industry_str):
    raw = str(raw_industry_str).upper().strip()
    if "BANK" in raw: return "BANK"
    if "FINAN" in raw or "INSUR" in raw: return "FINANCE"
    if "IT " in raw or "TECHNOLOGY" in raw or "SOFTWARE" in raw: return "IT"
    if "HEALTH" in raw or "PHARMA" in raw or "BIOTECH" in raw: return "PHARMA"
    if "AUTO" in raw or "VEHICLE" in raw: return "AUTO"
    if "METALS" in raw or "MINING" in raw or "STEEL" in raw: return "METAL"
    if "REALTY" in raw or "REAL ESTATE" in raw: return "REALTY"
    if "FMCG" in raw or "CONSUMER GOODS" in raw or "FOOD" in raw or "BEVERAGE" in raw: return "FMCG"
    if "CONSTRUCT" in raw or "INFRA" in raw: return "INFRA"
    if "POWER" in raw or "ENERGY" in raw or "OIL" in raw or "GAS" in raw or "FUEL" in raw: return "ENERGY"
    if "MEDIA" in raw or "ENTERTAIN" in raw: return "MEDIA"
    if "CHEMI" in raw or "COMMODIT" in raw or "TEXTI" in raw or "PAPER" in raw: return "COMMODITIES"
    return "UNKNOWN"

def scan_kalman_bullish_deviations(df):
    """Processes clean historical structures using the Kalman Filter model."""
    try:
        df_clean = df.copy()
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        close = df_clean["Close"].squeeze()
        volume = df_clean["Volume"].squeeze()

        if len(close) < EMA_TREND_PERIOD:
            return False, {}, "Insufficient History"

        # --- LIQUIDITY FILTER ---
        avg_volume_20d = volume.iloc[-20:].mean()
        if avg_volume_20d < MIN_AVG_VOLUME:
            return False, {}, "Failed Liquidity Filter"

        # --- LONG-TERM STRUCTURAL UPTREND FILTER ---
        ema_trend = ta.ema(close, length=EMA_TREND_PERIOD)
        if ema_trend is None or close.iloc[-1] < ema_trend.iloc[-1]:
            return False, {}, "Below Active EMA Trend"

        # Run State Space estimation arrays
        kf = AdvancedKalmanFilter(process_noise=1e-4, measurement_noise=1e-2)
        closes_array = close.values.flatten().astype(float)
        state_means, state_vars = kf.execute_estimation(closes_array)

        current_price = float(closes_array[-1])
        fair_value = float(state_means[-1])
        kalman_std = np.sqrt(state_vars[-1])

        deviation = current_price - fair_value
        z_score = deviation / (kalman_std + 1e-8)
        pct_discount = (abs(deviation) / fair_value) * 100

        # Reject premiums or flat pricing profiles
        if deviation >= 0:
            return False, {}, "Premium Value Asset"

        if z_score <= -1.2:
            grade = "DEEP VALUE (Oversold)"
            sort_rank = 1
        elif z_score <= -0.5:
            grade = "BULLISH SWING (High Probability)"
            sort_rank = 2
        else:
            grade = "MILD ACCUMULATION"
            sort_rank = 3

        metrics = {
            "Grade": grade,
            "Sort_Rank": sort_rank,
            "Live_Price": round(current_price, 2),
            "Kalman_Fair_Value": round(fair_value, 2),
            "Discount_Pct": round(pct_discount, 2),
            "Z_Score": round(z_score, 2)
        }
        return True, metrics, "PASSED"
    except Exception as e:
        return False, {}, f"Algorithmic Step Fault: {str(e)}"

def dispatch_telegram_broadcast(df_final):
    """Encodes details and pushes notification updates using Telegram API."""
    if not MY_TOKEN or not MY_CHAT_ID or "YOUR" in MY_TOKEN:
        print("[WARNING] Telegram skipped: Bot Token configuration invalid.")
        return

    print("[INFO] Broadcasting configurations to Telegram Matrix...")
    http = urllib3.PoolManager()

    text_message = f"🚀 *KALMAN FILTER: RECOVERY BREAKOUTS* 🚀\n"
    text_message += f"📋 Source List: `{CSV_NAME}` | Trend Base: *{EMA_TREND_PERIOD} EMA*\n"
    text_message += f"📊 Actionable Setups Found: *{len(df_final)}*\n"
    text_message += "═══════════════════════\n\n"

    for _, row in df_final.head(10).iterrows():
        signal = row['Action Signal']
        emoji_prefix = ""
        if "DEEP VALUE" in signal:
            emoji_prefix = "🔥 "
        elif "BULLISH SWING" in signal:
            emoji_prefix = "🟢 "
        elif "MILD ACCUMULATION" in signal:
            emoji_prefix = "🌱 "

        text_message += f"🔹 *{row['Ticker']}* | {row['Sector']}\n"
        text_message += f" ├ Price: *₹{row['Price (INR)']}*\n"
        text_message += f" ├ Fair Value: ₹{row['Kalman Value (INR)']}\n"
        text_message += f" ├ Z-Score: *{row['Z-Score']}*\n"
        text_message += f" ├ Value Gap: -{row['Discount (%)']}%\n"
        text_message += f" └ Signal: {emoji_prefix}{signal}\n\n"

    # Fix: Correct Telegram API endpoint pathing
    telegram_url = f"https://api.telegram.org/bot{MY_TOKEN}/sendMessage"
    payload = {
        "chat_id": str(MY_CHAT_ID),
        "text": text_message,
        "parse_mode": "Markdown"
    }

    try:
        encoded_data = json.dumps(payload).encode('utf-8')
        response = http.request(
            'POST',
            telegram_url,
            body=encoded_data,
            headers={'Content-Type': 'application/json'}
        )
        if response.status == 200:
            print("[SUCCESS] Telegram notification transmitted successfully!")
        else:
            print(f"[ERROR] Telegram submission fault {response.status}: {response.data.decode('utf-8')}")
    except Exception as e:
        print(f"[WARNING] Network error while dispatching Telegram alert: {e}")

def run_stable_analysis(df_watchlist):
    results = []
    sym_col = next((c for c in df_watchlist.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_watchlist.columns[0])
    sec_col = next((c for c in df_watchlist.columns if "sector" in c.lower() or "industry" in c.lower()), None)

    print(f"[INFO] Preparing tickers for batch download...")
    tickers = []
    ticker_to_sector = {}
    
    for _, row in df_watchlist.iterrows():
        raw_sym = str(row[sym_col]).strip().replace(",", "")
        if not raw_sym or "NAN" in raw_sym.upper() or "SYMBOL" in raw_sym.upper():
            continue
        
        if ".NS" in raw_sym.upper():
            sym = raw_sym
        else:
            sym = f"{raw_sym}.NS"
            
        raw_sector = row[sec_col] if sec_col else "UNKNOWN"
        sector = normalize_nse_industry(raw_sector)
        
        tickers.append(sym)
        ticker_to_sector[sym] = sector

    print(f"[INFO] Downloading historical data in batch for {len(tickers)} assets...")
    session = None
    if os.getenv("GITHUB_ACTIONS"):
        session = requests.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    try:
        master_data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False, auto_adjust=True, session=session)
    except Exception as e:
        print(f"[ERROR] Batch download failed: {e}. Falling back to sequential execution.")
        master_data = None

    print(f"[INFO] Running Kalman State Space Scans...")
    for sym in tqdm(tickers, desc="Scanning Assets"):
        try:
            if master_data is not None and sym in master_data.columns.levels[0]:
                df_history = master_data[sym].dropna(subset=["Close"])
            else:
                # Fallback to sequential ticker fetch if batch is missing this symbol
                tk = yf.Ticker(sym)
                df_history = tk.history(period="1y", interval="1d", auto_adjust=True, raise_errors=False)

            if df_history.empty or len(df_history) < EMA_TREND_PERIOD:
                continue

            passed, data_metrics, log_reason = scan_kalman_bullish_deviations(df_history)

            if passed:
                results.append({
                    "Ticker": sym.replace(".NS", ""),
                    "Sector": ticker_to_sector[sym],
                    "Price (INR)": data_metrics["Live_Price"],
                    "Kalman Value (INR)": data_metrics["Kalman_Fair_Value"],
                    "Discount (%)": data_metrics["Discount_Pct"],
                    "Z-Score": data_metrics["Z_Score"],
                    "Sort_Order": data_metrics["Sort_Rank"],
                    "Action Signal": data_metrics["Grade"]
                })
        except Exception:
            continue

    if not results:
        print("[INFO] No equities parsed match the long-term uptrend + value-discount parameters.")
        return pd.DataFrame()

    final_df = pd.DataFrame(results)

    # Fix: Sort before calling head() so we pick the best candidates per sector instead of index-order
    final_df = final_df.sort_values(by=["Sort_Order", "Z-Score"], ascending=[True, True])
    final_df = final_df.groupby("Sector").head(MAX_STOCKS_PER_SECTOR)
    final_df = final_df.drop(columns=["Sort_Order"])
    
    return final_df

if __name__ == "__main__":
    if os.path.exists(CSV_NAME):
        watchlist_matrix = pd.read_csv(CSV_NAME)
        output_dashboard = run_stable_analysis(watchlist_matrix)

        if not output_dashboard.empty:
            print(f"\n[INFO] PROCESSED TARGET WATCHLIST ACQUISITIONS: {CSV_NAME}")
            print(f"[INFO] Filter Configuration -> Trend Base: {EMA_TREND_PERIOD} EMA | Min Vol: {MIN_AVG_VOLUME}")
            print("==========================================================================")
            print(output_dashboard.to_string(index=False))

            # Forward metrics to messaging API
            dispatch_telegram_broadcast(output_dashboard)
        else:
            print("[INFO] Scan complete. No structural value opportunities identified today.")
    else:
        print(f"[ERROR] Target path array missing: Check if '{CSV_NAME}' is in the root directory.")
