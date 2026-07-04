import os
import sys
import json
import warnings
import urllib3
import html
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# --- UTF-8 CONSOLE ENCODING FIX (Windows Support) ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- WARNING FILTERS (Cleans environment log output) ---
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# --- CONFIG (Aligned to Your Root Repository Layout) ---
TKN = os.getenv("TELEGRAM_TOKEN", "").strip()
UID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DATA_FOLDER = "."  # Target the root repository folder directly
MIN_AVG_VOLUME = 100000

try:
    import yfinance as yf
except ImportError:
    print("❌ Critical dependency yfinance missing.")
    exit(1)

# -------------------------------------------------------------------------
# THE COHESIVE 12-POINT QUANT MATHEMATICAL PIPELINE ENGINE
# -------------------------------------------------------------------------
def process_twelve_point_pipeline(price_matrix: pd.DataFrame, window_m: int = 20, window_d: int = 5) -> pd.DataFrame:
    if price_matrix.empty or len(price_matrix) < window_m:
        return pd.DataFrame()
        
    R = price_matrix.pct_change().dropna(how='all')
    X = R - R.rolling(window=window_m).mean()
    sigma_squared = (X ** 2).rolling(window=window_m).mean()
    sigma = np.sqrt(sigma_squared)
    Y = X / (sigma + 1e-8)
    Y_truncated = Y.iloc[-(window_m - 1):]
    cross_market_mean = Y_truncated.mean(axis=1)
    A = Y_truncated.sub(cross_market_mean, axis=0)
    E = R.iloc[-window_d:].mean()
    current_sigma = sigma.iloc[-1]
    E_norm = E / (current_sigma + 1e-8)
    current_A = A.iloc[-1]
    valid_assets = E_norm.dropna().index.intersection(current_A.dropna().index)

    residuals = {}
    if len(valid_assets) > 2:
        X_reg = current_A[valid_assets].values.reshape(-1, 1)
        y_reg = E_norm[valid_assets].values
        reg = LinearRegression().fit(X_reg, y_reg)
        predicted = reg.predict(X_reg)
        raw_residuals = y_reg - predicted
        for idx, stock in enumerate(valid_assets):
            residuals[stock] = raw_residuals[idx]
    else:
        for stock in price_matrix.columns:
            residuals[stock] = E_norm.get(stock, 0.0)

    epsilon = pd.Series(residuals)
    raw_weights = epsilon / (current_sigma + 1e-8)
    absolute_sum = raw_weights.abs().sum()
    final_weights = raw_weights / absolute_sum if absolute_sum > 0 else raw_weights

    return pd.DataFrame({
        "Raw_Ticker": [s.replace(".NS", "") for s in final_weights.index],
        "Idiosyncratic_Alpha": epsilon,
        "Optimal_Weight_Pct": final_weights * 100,
        "Risk_Volatility_Pct": current_sigma * 100
    }).dropna().sort_values(by="Idiosyncratic_Alpha", ascending=False).reset_index(drop=True)

def load_universe_matrix(watchlist_df: pd.DataFrame, tracking_days: int = 60) -> pd.DataFrame:
    ticker_col = next((c for c in watchlist_df.columns if "symbol" in c.lower() or "ticker" in c.lower()), watchlist_df.columns)
    raw_tickers = watchlist_df[ticker_col].dropna().astype(str).tolist()
    historical_close_map = {}
    
    CACHE_FILE = 'nifty500_data.pkl'
    if os.path.exists(CACHE_FILE):
        print(f"💾 Loading cached historical market data from '{CACHE_FILE}' for 12-point pipeline...")
        try:
            master_data = pd.read_pickle(CACHE_FILE)
            is_multi = isinstance(master_data.columns, pd.MultiIndex)
        except Exception as e:
            print(f"❌ Failed to load cache in pipeline: {e}. Falling back to downloads.")
            master_data = None
            is_multi = False
    else:
        master_data = None
        is_multi = False

    print(f"📥 Compiling timeseries tracking data for {len(raw_tickers)} assets...")

    for symbol in raw_tickers:
        clean_sym = symbol.strip().replace(",", "")
        if not clean_sym:
            continue
        yf_ticker = clean_sym if clean_sym.upper().endswith(".NS") else f"{clean_sym}.NS"
        try:
            if master_data is not None and is_multi and yf_ticker in master_data.columns.levels[0]:
                df_hist = master_data[yf_ticker].dropna(subset=["Close"])
            else:
                asset_obj = yf.Ticker(yf_ticker)
                df_hist = asset_obj.history(period=f"{tracking_days + 30}d", interval="1d", auto_adjust=True, raise_errors=False)
                
            if not df_hist.empty and len(df_hist) >= (tracking_days - 15):
                if df_hist["Volume"].iloc[-20:].mean() >= MIN_AVG_VOLUME:
                    historical_close_map[yf_ticker] = df_hist["Close"].tail(tracking_days).squeeze()
        except Exception:
            continue
            
    if not historical_close_map:
        return pd.DataFrame()

    raw_df = pd.DataFrame(historical_close_map).dropna(axis=1, how='any')
    print(f"🛡️ Matrix Alignment: Retained {len(raw_df.columns)} stocks with valid history.")
    return raw_df.ffill().dropna()

# -------------------------------------------------------------------------
# FILE PROCESSING AUTOMATION EXECUTIVE
# -------------------------------------------------------------------------
def run_pipeline_for_file(selected_file):
    target_path = os.path.join(DATA_FOLDER, selected_file)
    print(f"\n📂 Activating Watchlist Document: {selected_file}")

    try:
        watchlist_df = pd.read_csv(target_path)
    except Exception as e:
        print(f"❌ Read Failure on file {selected_file}: {e}")
        return

    price_data_matrix = load_universe_matrix(watchlist_df, tracking_days=60)

    if not price_data_matrix.empty:
        print("🧮 Processing 12-Point Quant Mathematical Engine...")
        alpha_signals_df = process_twelve_point_pipeline(price_data_matrix)

        if not alpha_signals_df.empty:
            print(alpha_signals_df.head(10).to_string())

            # --- CONSTRUCT SAFE HTML REPORT MESSAGE ---
            clean_filename = html.escape(selected_file)
            msg = f"🏆 <b>INSTITUTIONAL 12-POINT QUANT ALPHA REPORT:</b> {clean_filename}\n"
            msg += f"Sorted by Idiosyncratic Alpha | Vol &gt; 100k | Window: 20m, 5d\n\n"

            ticker_list = []
            for i in range(min(10, len(alpha_signals_df))):
                ticker = html.escape(str(alpha_signals_df.loc[i, "Raw_Ticker"]))
                alpha = round(float(alpha_signals_df.loc[i, "Idiosyncratic_Alpha"]), 4)
                weight = round(float(alpha_signals_df.loc[i, "Optimal_Weight_Pct"]), 2)
                volatility = round(float(alpha_signals_df.loc[i, "Risk_Volatility_Pct"]), 2)

                ticker_list.append(f"NSE:{ticker}")
                msg += f"• <b>{ticker}</b>:\n"
                msg += f"  ↳ Idiosyncratic Alpha: {alpha}\n"
                msg += f"  ↳ Optimal Weight Allocation: {weight}%\n"
                msg += f"  ↳ Risk Volatility: {volatility}%\n\n"

            msg += "📺 <b>WATCHLIST</b>\n"
            msg += ",".join(ticker_list)

            # --- TELEGRAM TRANSMISSION ---
            if not TKN or not UID:
                print("⚠️ Telegram configurations missing in Action Env. Transmission aborted.")
                return

            print("📤 Transmitting dispatch telemetry payload to Telegram...")
            api_domain = "api.telegram.org"
            http_client = urllib3.PoolManager()
            try:
                full_url = f"https://{api_domain}/bot{TKN}/sendMessage"
                encoded_msg = json.dumps({"chat_id": str(UID), "text": msg, "parse_mode": "HTML"})
                r = http_client.request("POST", full_url, body=encoded_msg, headers={"Content-Type": "application/json"})

                if r.status == 200:
                    print("✅ SUCCESS! Premium Quality Grade-Sorted Quant report sent.")
                else:
                    print(f"❌ REJECTED: {r.status} - {r.data.decode()}")
            except Exception as e:
                print(f"⚠️ FAILED: {str(e)}")
        else:
            print("Converted data structure frames are empty.")
    else:
        print("❌ Data processing aborted: Matrix returned 0 matching stock indices.")

def main():
    # Automatically scan for files ending with nifty500list.csv in the root folder
    csv_files = sorted([f for f in os.listdir(DATA_FOLDER) if f.endswith('nifty500list.csv')])
    if not csv_files:
        print(f"⚠️ Target portfolio data file not found in root path.")
        return

    print(f"📋 Found {len(csv_files)} portfolio documents to evaluate sequentially.")
    for file in csv_files:
        run_pipeline_for_file(file)

if __name__ == "__main__":
    main()
