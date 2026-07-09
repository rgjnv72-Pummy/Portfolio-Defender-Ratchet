import os
import sys
import gc
import json
import warnings
import http.client
import numpy as np
import pandas as pd
from tqdm import tqdm

# --- UTF-8 CONSOLE ENCODING FIX (Windows Support) ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- ENVIRONMENT & WARNINGS ---
warnings.filterwarnings("ignore")

# Safe imports for cross-platform portability
try:
    from IPython.display import clear_output, display
except ImportError:
    clear_output = lambda: None
    display = print

# --- CONFIGURATION ---
CSV_NAME = "ind_nifty500list.csv"
CACHE_FILE = "nifty500_data.pkl"

# --- MATHEMATICAL MODEL CONSTANTS ---
EMA_TREND_PERIOD = 112   # Trend factor lookback
VOLATILITY_PERIOD = 40   # Volatility normalization lookback
MIN_AVG_VOLUME = 500000  # Liquidity floor

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

def check_paper_trend_filter(df):
    """
    Applies the mathematical framework of volatility-normalized returns
    fed into a robust 112-day exponential moving average filter.
    """
    try:
        df_clean = df.copy()
        
        # Safe column extraction (handles potential MultiIndex structures cleanly)
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        if "Close" not in df_clean.columns or "Volume" not in df_clean.columns:
            return False, 0.0, 0.0, "Missing Columns"

        close = df_clean["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
            
        volume = df_clean["Volume"]
        if isinstance(volume, pd.DataFrame):
            volume = volume.iloc[:, 0]

        required_bars = max(EMA_TREND_PERIOD, VOLATILITY_PERIOD) + 20
        if len(close) < required_bars:
            return False, 0.0, 0.0, "Insufficient History"

        # --- INSTITUTIONAL LIQUIDITY FILTER ---
        avg_volume_20d = volume.iloc[-20:].mean()
        if pd.isna(avg_volume_20d) or avg_volume_20d < MIN_AVG_VOLUME:
            return False, 0.0, 0.0, "Failed Liquidity Filter"

        # --- REGIME TRANSITION NORMALIZATION ENGINE ---
        daily_returns = np.log(close / close.shift(1))
        rolling_vol = daily_returns.rolling(window=VOLATILITY_PERIOD).std()

        # Volatility normalization (returns scaled by rolling standard deviation)
        normalized_returns = daily_returns / rolling_vol
        normalized_returns = normalized_returns.replace([np.inf, -np.inf], np.nan).fillna(0)

        # Replacing pandas_ta with native pandas EWM for robustness and speed
        ema_signal = normalized_returns.ewm(span=EMA_TREND_PERIOD, adjust=False).mean()

        if ema_signal is None or ema_signal.empty or pd.isna(ema_signal.iloc[-1]):
            return False, 0.0, 0.0, "Signal Generation Error"

        eta = 1.0 / EMA_TREND_PERIOD
        scaled_signal = float(ema_signal.iloc[-1] * np.sqrt(eta))

        # --- LINEAR SIZING BASES & DRIFT FILTER ---
        if scaled_signal <= 0:
            return False, 0.0, 0.0, "Negative Structural Trend Drift"

        signal_strength = round(scaled_signal * 100, 2)
        current_price = float(close.iloc[-1])

        return True, signal_strength, current_price, "PASSED"
    
    except Exception as e:
        return False, 0.0, 0.0, f"System Processing Error: {str(e)}"

def dispatch_telegram_broadcast(df):
    token = os.getenv('TELEGRAM_TOKEN', '').strip()
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    
    if not token or not chat_id or "YOUR" in token:
        print("[CONSOLE LOG] Telegram credentials not configured. Skipping broadcast.")
        return
        
    text_message = "🪐 *KRONOS QUANT SYSTEM: CTA TREND DRIFT DEPLOYMENT*\n"
    text_message += "=========================================\n\n"
    
    # Take top 15 results to avoid hitting Telegram message length limits
    display_df = df.head(15)
    
    for _, row in display_df.iterrows():
        text_message += f"🔹 *{row['Ticker']}* | {row['Sector']}\n"
        text_message += f" ├ Price: *₹{row['Price']}*\n"
        text_message += f" └ Signal Strength: *{row['Signal_Strength']}*\n\n"
        
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": chat_id, "text": text_message, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{token}/sendMessage", payload, headers)
        response = conn.getresponse()
        if response.status == 200:
            print("✅ Telegram notification dispatched successfully.")
        else:
            print(f"❌ Telegram Error Status: {response.status}")
    except Exception as e:
        print(f"❌ Telegram Transmission Error: {e}")
    finally:
        conn.close()

def run_stable_analysis(df_watchlist):
    results = []
    
    sym_col = next((c for c in df_watchlist.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_watchlist.columns[0])
    sec_col = next((c for c in df_watchlist.columns if "sector" in c.lower() or "industry" in c.lower()), None)

    print(f"[INFO] Preparing tickers from watchlist...")
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

    if os.path.exists(CACHE_FILE):
        print(f"💾 Loading cached historical market data from '{CACHE_FILE}'...")
        try:
            master_data = pd.read_pickle(CACHE_FILE)
        except Exception as e:
            print(f"❌ Failed to load cache: {e}. Downloading dynamically instead.")
            master_data = None
    else:
        master_data = None
        
    if master_data is None:
        print(f"[ERROR] Cache file '{CACHE_FILE}' is missing. Cannot perform scan. Please run unified data fetcher first.")
        return pd.DataFrame()

    print(f"[INFO] Running Volatility-Normalized CTA Trend Scans...")
    for idx, sym in enumerate(tqdm(tickers, desc="Scanning Assets")):
        try:
            if sym in master_data.columns.levels[0]:
                df_history = master_data[sym].dropna(subset=["Close"])
            else:
                continue

            if df_history.empty or len(df_history) < EMA_TREND_PERIOD:
                continue

            passed, signal_strength, current_price, reason = check_paper_trend_filter(df_history)

            if passed:
                results.append({
                    "Ticker": sym.replace(".NS", ""),
                    "Sector": ticker_to_sector[sym],
                    "Price": round(current_price, 2),
                    "Signal_Strength": signal_strength
                })

        except Exception:
            continue
        finally:
            if idx % 50 == 0:
                gc.collect()

    gc.collect()
    
    if not results:
        print("[INFO] No assets passed the volatility-normalized trend parameters.")
        return pd.DataFrame()
        
    final_df = pd.DataFrame(results)
    # Sort by signal strength descending
    final_df = final_df.sort_values(by="Signal_Strength", ascending=False)
    return final_df

if __name__ == "__main__":
    if os.path.exists(CSV_NAME):
        watchlist = pd.read_csv(CSV_NAME)
        output_df = run_stable_analysis(watchlist)
        if not output_df.empty:
            print("\n[INFO] PROCESSED TARGET WATCHLIST ACQUISITIONS")
            print("==========================================================")
            print(output_df.to_string(index=False))
            dispatch_telegram_broadcast(output_df)
        else:
            print("[INFO] Scan complete. No CTA trend setups identified today.")
    else:
        print(f"[ERROR] Target watchlist file '{CSV_NAME}' not found.")
