import os
import json
import warnings
import urllib3
import html
import datetime
import numpy as np
import pandas as pd
from tqdm import tqdm
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '1280803679').strip()
MY_TOKEN = os.getenv('TELEGRAM_TOKEN', '8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o').strip()
CSV_NAME = "ind_nifty500list.csv"
LOGS_FOLDER = "Execution_Logs"
MIN_AVG_VOLUME = 250000  # Elevated liquidity ceiling for breakout validity

# -------------------------------------------------------------------------
# THE COHESIVE SYSTEM STRUCTURAL HIERARCHY MATCHING ENGINE
# -------------------------------------------------------------------------
def generate_structural_templates(window_m=20):
    """
    Creates a well-ordered, normalized hypothesis space of explosive price shapes.
    All curves are scaled between 0 and 1 for perfect shape cross-correlation.
    """
    t = np.linspace(0, 1, window_m)
    templates = {}

    # Priority 1: Parabolic Launch Curve (Accelerating Breakout Momentum)
    p_curve = np.exp(3 * t)
    templates["PARABOLIC LAUNCH"] = (p_curve - p_curve.min()) / (p_curve.max() - p_curve.min())

    # Priority 2: Steady Linear Channel Runaway
    l_curve = t
    templates["LINEAR CHANNEL RUN"] = (l_curve - l_curve.min()) / (l_curve.max() - l_curve.min())

    # Priority 3: V-Bottom Reversal Spring
    v_curve = (t - 0.3) ** 2
    templates["V-REVERSAL SPRING"] = (v_curve - v_curve.min()) / (v_curve.max() - v_curve.min())

    # Priority 4: Flat Accumulation Squeeze (Coiling for expansion)
    s_curve = np.sin(2 * np.pi * t) * np.exp(-2 * t)
    templates["ACCUMULATION SQUEEZE"] = (s_curve - s_curve.min()) / (s_curve.max() - s_curve.min())

    return templates

def process_hierarchy_prediction_scanner(price_matrix: pd.DataFrame, window_m: int = 20) -> pd.DataFrame:
    if price_matrix.empty or len(price_matrix) < window_m:
        return pd.DataFrame()

    templates = generate_structural_templates(window_m)
    detected_setups = []

    # Extract the absolute last 20 days for all assets
    recent_matrix = price_matrix.iloc[-window_m:]
    last_prices = price_matrix.iloc[-1]

    # Compute rolling asset volatility over lookback for dynamic adaptive risk sizing
    pct_returns = price_matrix.pct_change()
    volatility_series = pct_returns.iloc[-window_m:].std() * np.sqrt(252) * 100

    for ticker in price_matrix.columns:
        # Get raw historical price slice and normalize it to a 0-1 scale to evaluate shape
        raw_path = recent_matrix[ticker].values
        path_min, path_max = raw_path.min(), raw_path.max()
        if path_max - path_min == 0:
            continue
        normalized_path = (raw_path - path_min) / (path_max - path_min)

        # Search the well-ordered structural hierarchy sequentially (Axiom of Choice simulation)
        matched_profile = None
        best_fit_score = 0.0

        for profile_name, template_curve in templates.items():
            # Measure similarity using Pearson Cross-Correlation Coefficient
            correlation = np.corrcoef(normalized_path, template_curve)[0, 1]

            # Strict institutional fit rule: Correlation must beat 0.88 to trigger an entry
            if correlation >= 0.88:
                matched_profile = profile_name
                best_fit_score = correlation
                break  # The core theorem mechanic: Take the FIRST matching model in the hierarchy

        if matched_profile:
            ticker_vol = volatility_series[ticker]
            # Safeguard profile risk if data calculation returns NaN
            if np.isnan(ticker_vol) or ticker_vol == 0:
                ticker_vol = 10.0

            detected_setups.append({
                "Raw_Ticker": ticker.replace(".NS", ""),
                "Matched_Profile": matched_profile,
                "Fit_Score": best_fit_score,
                "Last_Close_Price": last_prices[ticker],
                "Risk_Volatility_Pct": ticker_vol
            })

    if not detected_setups:
        return pd.DataFrame()

    return pd.DataFrame(detected_setups).sort_values(by="Fit_Score", ascending=False).reset_index(drop=True)

def download_single_ticker(symbol, tracking_days):
    clean_sym = symbol.strip().replace(",", "")
    yf_ticker = clean_sym if clean_sym.upper().endswith(".NS") else f"{clean_sym}.NS"
    try:
        asset_obj = yf.Ticker(yf_ticker)
        df_hist = asset_obj.history(period=f"{tracking_days}d", interval="1d", auto_adjust=True)
        if not df_hist.empty and len(df_hist) >= (tracking_days - 15):
            # Apply volume liquidity threshold
            if df_hist["Volume"].iloc[-20:].mean() >= MIN_AVG_VOLUME:
                return yf_ticker, df_hist["Close"].squeeze()
    except Exception:
        pass
    return None

def load_universe_matrix(watchlist_df: pd.DataFrame, tracking_days: int = 60) -> pd.DataFrame:
    ticker_col = next((c for c in watchlist_df.columns if "symbol" in c.lower() or "ticker" in c.lower()), watchlist_df.columns[0])
    raw_tickers = watchlist_df[ticker_col].dropna().astype(str).tolist()
    historical_close_map = {}
    print(f"[INFO] Compiling timeseries paths for {len(raw_tickers)} assets...")

    # Concurrently extract historical price feeds
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(download_single_ticker, sym, tracking_days) for sym in raw_tickers]
        for f in tqdm(futures, desc="Data Matrix Extraction"):
            res = f.result()
            if res is not None:
                yf_ticker, close_series = res
                historical_close_map[yf_ticker] = close_series

    if not historical_close_map:
        return pd.DataFrame()

    raw_df = pd.DataFrame(historical_close_map).dropna(axis=1, how='any')
    print(f"[INFO] Matrix Alignment: Retained {len(raw_df.columns)} stocks with perfect historical records.")
    return raw_df.ffill().dropna()

def execute_pipeline():
    if not os.path.exists(CSV_NAME):
        print(f"[ERROR] Watchlist file missing: Check if '{CSV_NAME}' is in the root directory.")
        return

    print(f"[INFO] Activating Watchlist Document: {CSV_NAME}")
    try:
        watchlist_df = pd.read_csv(CSV_NAME)
    except Exception as e:
        print(f"[ERROR] Read Failure on file {CSV_NAME}: {e}")
        return

    price_data_matrix = load_universe_matrix(watchlist_df, tracking_days=60)

    if not price_data_matrix.empty:
        print("[INFO] Processing Hierarchical Path-Matching Engine...")
        matched_signals_df = process_hierarchy_prediction_scanner(price_data_matrix)

        if not matched_signals_df.empty:
            print("\n[INFO] Top Matched Path Signals:")
            print(matched_signals_df.head(10).to_string(index=False))

            # --- AUTOMATIC HARD DRIVE EXECUTION LOGGER ---
            if not os.path.exists(LOGS_FOLDER):
                os.makedirs(LOGS_FOLDER)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_name = CSV_NAME.replace(".csv", "")
            log_filename = f"HierarchyLog_{clean_name}_{timestamp}.csv"
            log_save_path = os.path.join(LOGS_FOLDER, log_filename)

            matched_signals_df.to_csv(log_save_path, index=False)
            print(f"[INFO] Snapshot Log compiled and saved securely: {log_filename}")

            # --- CONSTRUCT THE CLEAN TELEGRAM DISPATCH ---
            clean_filename = html.escape(CSV_NAME)
            msg = f"🔮 <b>THE NEARLY PERFECT THEOREM SCANNER</b>\n"
            msg += f"📦 Hierarchy Space: <code>{clean_filename}</code>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            ticker_list = []
            for i in range(min(10, len(matched_signals_df))):
                ticker = html.escape(str(matched_signals_df.loc[i, "Raw_Ticker"]))
                profile_raw = str(matched_signals_df.loc[i, "Matched_Profile"])
                price = float(matched_signals_df.loc[i, "Last_Close_Price"])
                volatility = float(matched_signals_df.loc[i, "Risk_Volatility_Pct"])

                # Prepend emojis for rich Telegram display
                emoji_map = {
                    "PARABOLIC LAUNCH": "⚡",
                    "LINEAR CHANNEL RUN": "📈",
                    "V-REVERSAL SPRING": "🎯",
                    "ACCUMULATION SQUEEZE": "📦"
                }
                profile = f"{emoji_map.get(profile_raw, '')} {profile_raw}"

                ticker_list.append(f"NSE:{ticker}")

                # Dynamic Volatility Risk Calibration (Dynamic Stop Limit)
                # Maps a stop distance using annualized volatility components bounded cleanly between 3% and 15%
                calculated_sl_pct = max(min(volatility / 4.0, 15.0), 3.0)
                stop_loss_price = price * (1.0 - (calculated_sl_pct / 100.0))

                # Build 2:1 Reward-Risk Target Projection
                upside_potential_pct = calculated_sl_pct * 2.0
                target_price = price * (1.0 + (upside_potential_pct / 100.0))

                # MONOSPACED TAP-TO-COPY TELEMETRY WINDOW
                msg += f"• <b>{ticker}</b>\n"
                msg += f"  ↳ Profile: {profile}\n"
                msg += f"  <code>[Entry: ₹{price:,.2f} | Target: ₹{target_price:,.2f} (+{upside_potential_pct:.1f}%) | SL: ₹{stop_loss_price:,.2f} (-{calculated_sl_pct:.1f}%)]</code>\n\n"

            if ticker_list:
                msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                msg += "📺 <b>TRADINGVIEW WATCHLIST (TAP TO COPY)</b>\n"
                msg += f"<code>{','.join(ticker_list)}</code>\n"

                # --- EXACT TELEGRAM TRANSMISSION ROUTE ---
                print("[INFO] Transmitting breakout telemetry payload to Telegram...")
                http_client = urllib3.PoolManager()
                try:
                    full_url = f"https://api.telegram.org/bot{MY_TOKEN}/sendMessage"
                    encoded_msg = json.dumps({"chat_id": str(MY_CHAT_ID), "text": msg, "parse_mode": "HTML"})
                    r = http_client.request("POST", full_url, body=encoded_msg, headers={"Content-Type": "application/json"})

                    if r.status == 200:
                        print("[SUCCESS] Hierarchy pattern report sent to Telegram.")
                    else:
                        print(f"[ERROR] Telegram submission fault {r.status}: {r.data.decode()}")
                except Exception as e:
                    print(f"[WARNING] Network error while dispatching Telegram alert: {e}")
            else:
                print("[INFO] No structural path configurations detected matching the hierarchy models today.")
        else:
            print("[INFO] No matching structural profiles tracked in the current database frame.")
    else:
        print("[ERROR] Data processing aborted: Matrix returned 0 matching stock indices.")


if __name__ == "__main__":
    execute_pipeline()
