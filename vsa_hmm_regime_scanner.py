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
from hmmlearn.hmm import GaussianHMM
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '1280803679').strip()
MY_TOKEN = os.getenv('TELEGRAM_TOKEN', '8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o').strip()
CSV_NAME = "ind_nifty500list.csv"

# STRATEGY OPERATIONAL WINDOWS & CONSTANTS
HMM_STATES = 3               # 0: Accumulation Trend, 1: High-Chop Pullback, 2: Heavy Institutional Distribution
LOOKBACK_WINDOW = 252        # 1 Full trading year to fit and optimize the Gaussian emission matrices
MIN_DAILY_TURNOVER_INR = 50000000  # ₹5 Crores minimum daily turnover (Price * Volume) for institutional liquidity

def run_vsa_hmm_engine(df):
    """
    Constructs multi-dimensional VSA features based on Wyckoff's Law of Effort vs Result
    and applies a Hidden Markov Model to classify hidden institutional market states.
    """
    try:
        df_clean = df.copy()
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        open_p = df_clean["Open"].squeeze()
        close = df_clean["Close"].squeeze()
        high = df_clean["High"].squeeze()
        low = df_clean["Low"].squeeze()
        volume = df_clean["Volume"].squeeze()

        if len(close) < LOOKBACK_WINDOW:
            return False, 0, 0.0, "Insufficient History"

        # --- SAFETIES: ADAPTIVE LIQUIDITY VALUE CONSTRAINTS ---
        # Computes ₹ Daily Turnover instead of raw share volume count
        daily_turnover = close * volume
        avg_turnover_20d = daily_turnover.iloc[-20:].mean()
        if avg_turnover_20d < MIN_DAILY_TURNOVER_INR:
            return False, 0, 0.0, "Failed Liquidity Filter"

        # --- FEATURE CONVERSION SUBSPACE ---
        # Feature 1: Directional Velocity (Log Returns)
        log_returns = np.log(close / close.shift(1))

        # Feature 2: High-to-Low Candle Range Spread (Normalized against Close)
        candle_spread = (high - low) / close

        # Feature 3: Institutional Effort Metric (Volume / Normalized Spread Ratio)
        volume_to_spread = volume / (candle_spread + 1e-8)
        # Standardize over a 20-day lookback window to neutralize static scale distortions
        norm_vsa_effort = (volume_to_spread - volume_to_spread.rolling(20).mean()) / (volume_to_spread.rolling(20).std() + 1e-8)

        # Feature 4: Position of the Close within the daily high-low spread matrix
        close_location = (close - low) / ((high - low) + 1e-8)

        # Merge structural arrays and clear initialization NaNs
        features = pd.DataFrame({
            "Returns": log_returns,
            "VSA_Effort": norm_vsa_effort,
            "Close_Loc": close_location
        }).dropna()

        if len(features) < LOOKBACK_WINDOW:
            return False, 0, 0.0, "VSA Matrix Generation Failure"

        # Isolate the core trailing vectors for data mapping
        fit_data = features.iloc[-LOOKBACK_WINDOW:].values

        # --- COGNITIVE MACHINE LEARNING INFERENCE ---
        hmm = GaussianHMM(n_components=HMM_STATES, covariance_type="diagonal", random_state=42, max_iter=150)
        hmm.fit(fit_data)

        # Use the Viterbi algorithm to recover the chronological sequence of structural regimes
        hidden_states = hmm.predict(fit_data)
        current_regime = int(hidden_states[-1])

        # --- MACHINE ACCOUNTABILITY: REGIME IDENTIFICATION ---
        state_means = [hmm.means_[i][0] for i in range(HMM_STATES)] # Sort profiles based on mean returns
        bullish_state_index = int(np.argmax(state_means))
        bearish_state_index = int(np.argmin(state_means))
        sideways_state_index = [i for i in range(HMM_STATES) if i not in (bullish_state_index, bearish_state_index)][0]

        # --- HARD STRATEGY RISK FILTERS ---
        if current_regime == bearish_state_index:
            return False, current_regime, 0.0, "Institutional Distribution/Bearish Regime"

        if current_regime == sideways_state_index:
            return False, current_regime, 0.0, "Low Retail Participation/Chop"

        # --- TARGET ENTRY TRIGGER RULES (Bullish State Verified) ---
        recent_spreads = candle_spread.iloc[-10:]
        current_low = float(low.iloc[-1])
        entry_trigger = current_low * (1 + (np.mean(recent_spreads) * 0.4))

        return True, current_regime, round(entry_trigger, 2), "PASSED"
    except Exception as e:
        return False, 0, 0.0, f"Engine Failure: {str(e)}"


def scan_single_ticker(symbol):
    try:
        sym = str(symbol).strip().replace(",", "")
        if not sym.endswith(".NS"):
            sym += ".NS"

        tk = yf.Ticker(sym)
        d_df = tk.history(period="2y", interval="1d", raise_errors=False, auto_adjust=True)

        if d_df.empty or len(d_df) < LOOKBACK_WINDOW:
            return None

        (
            filter_passed,
            active_regime,
            entry_level,
            reason,
        ) = run_vsa_hmm_engine(d_df)

        if filter_passed:
            current_price = float(d_df["Close"].squeeze().iloc[-1])
            cl = d_df["Close"].squeeze()

            # High-Precision Swing Drift Forecast Math Model
            drift = (((cl.iloc[-1] / cl.iloc[-250]) - 1) / 250 * 0.6) + (
                ((cl.iloc[-1] / cl.iloc[-20]) - 1) / 20 * 0.4
            )
            target = current_price * (1 + (drift * 15)) # 15-day forward target timeline
            upside = ((target - current_price) / current_price) * 100

            if 1.0 < upside < 60.0:  # Loosened anomaly constraints for better capture scope
                return {
                    "Ticker": sym.replace(".NS", ""),
                    "Price": round(current_price, 2),
                    "VSA_Regime": active_regime,
                    "Trigger_Above": entry_level,
                    "Est_Upside%": round(upside, 2),
                }
    except Exception:
        pass
    return None


def run_stable_analysis(tickers):
    results = []
    # Utilize multithreading to concurrently download and simulate GaussianHMM models
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(scan_single_ticker, t) for t in tickers]
        for f in tqdm(futures, desc="Scanning Master Watchlist"):
            res = f.result()
            if res is not None:
                results.append(res)
    return pd.DataFrame(results)


def dispatch_telegram_broadcast(res):
    """Builds and delivers outbound Telegram payload."""
    if not MY_TOKEN or not MY_CHAT_ID or "YOUR" in MY_TOKEN:
        print("[WARNING] Telegram skipped: Bot Token configuration invalid.")
        return

    msg = f"🏆 *VSA REINFORCED HMM REPORT: {CSV_NAME}*\n_State: Confirmed Institutional Trend | Turnover Filter Active_\n\n"
    for _, r in res.head(20).iterrows():
        msg += f"• `{r['Ticker']}`: *₹{r['Price']}* | Trigger > `{r['Trigger_Above']}` | Regime State: {r['VSA_Regime']} | Forecast Swing: +{r['Est_Upside%']}%\n"

    tv_list = ",".join([f"NSE:{r['Ticker']}" for _, r in res.head(20).iterrows()])
    msg += f"\n📺 *WATCHLIST FORMATTER*\n`{tv_list}`"

    print("[INFO] Broadcasting HMM regime setups to Telegram Matrix...")
    http_client = urllib3.PoolManager()
    try:
        full_url = f"https://api.telegram.org/bot{MY_TOKEN}/sendMessage"
        encoded_msg = json.dumps({
            "chat_id": MY_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        r = http_client.request(
            "POST",
            full_url,
            body=encoded_msg,
            headers={"Content-Type": "application/json"},
        )

        if r.status == 200:
            print("[SUCCESS] PIPELINE EXECUTION SUCCESSFUL: VSA-HMM analysis pushed to Telegram.")
        else:
            print(f"[ERROR] TELEGRAM ROUTER REJECTION: {r.status} - {r.data.decode()}")
    except Exception as e:
        print(f"[WARNING] DISPATCH LAYER FAILURE: {str(e)}")


if __name__ == "__main__":
    if os.path.exists(CSV_NAME):
        print(f"[INFO] Parsing VSA Subspaces from: {CSV_NAME}...")
        print(f"[INFO] Constraints: 20d Turnover > INR {(MIN_DAILY_TURNOVER_INR/10000000):,} Cr | Active State == Institutional Accumulation\n")
        
        df_csv = pd.read_csv(CSV_NAME)
        col = next((c for c in df_csv.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_csv.columns[0])
        tickers = df_csv[col].dropna().unique()

        res = run_stable_analysis(tickers)

        if not res.empty:
            res = res.sort_values(by="Est_Upside%", ascending=False).reset_index(drop=True)
            
            print("\n[INFO] Top 20 VSA-HMM Bullish Regimes:")
            print(res.head(20).to_string(index=False))

            # Deliver report
            dispatch_telegram_broadcast(res)
        else:
            print("[WARNING] PROCESS END: No assets match the targeted institutional accumulation patterns today.")
    else:
        print(f"[ERROR] Watchlist file missing: Check if '{CSV_NAME}' is in the root directory.")
