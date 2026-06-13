import os
import json
import math
import warnings
import urllib3
import numpy as np
import pandas as pd
import scipy.linalg as la
import yfinance as yf
from sklearn.covariance import ledoit_wolf

# --- WARNING FILTERS ---
warnings.filterwarnings("ignore")

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '1280803679').strip()
MY_TOKEN = os.getenv('TELEGRAM_TOKEN', '8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o').strip()
CSV_NAME = "ind_nifty500list.csv"

# STRATEGY & ENGINE PARAMETERS (Frictionless Grebenkov Model + Ledoit-Wolf)
ETA = 1 / 112         # Optimal mathematical smoothing factor derived in the paper
VOL_LOOKBACK = 40     # Asset-level historical volatility lookback window
COV_LOOKBACK = 750    # Covariance historical window used for eigenvalue cleaning
TARGET_VOL = 0.10     # Target absolute annualised portfolio volatility (10%)


def compute_frictionless_arp_cleaned(returns_df):
    """Executes cross-asset matrix transformations using Ledoit-Wolf shrinkage.

    Protects allocations against financial noise maximization and small eigenvalue explosions.
    """
    try:
        # Step 1: Initialize rolling variance and continuous trend vectors
        sigma2 = returns_df.pow(2).ewm(alpha=ETA, adjust=False).mean()
        sigma = np.sqrt(sigma2)
        
        # Avoid division by zero by replacing zero/NaN volatility with small number or filling NaNs
        sigma_shifted = sigma.shift(1).fillna(0.00001)
        sigma_shifted = np.where(sigma_shifted == 0, 0.00001, sigma_shifted)
        norm_returns = (returns_df / sigma_shifted).fillna(0.0)

        phi = pd.DataFrame(0.0, index=returns_df.index, columns=returns_df.columns)
        for t in range(1, len(returns_df)):
            phi.iloc[t] = (1 - ETA) * phi.iloc[t - 1] + np.sqrt(ETA) * norm_returns.iloc[t]

        phi = phi.fillna(0.0)

        # Step 2: Extract latest day operational vector parameters
        latest_date = returns_df.index[-1]
        phi_t = phi.loc[latest_date].fillna(0.0).values
        asset_vol = returns_df.tail(VOL_LOOKBACK).std().values

        # Ensure no divisions by zero in asset risk scaling matrix (Sigma^-1)
        asset_vol = np.nan_to_num(asset_vol, nan=0.00001)
        asset_vol = np.where(asset_vol == 0, 0.00001, asset_vol)
        std_devs = np.diag(1.0 / asset_vol)

        # Step 3: CORE UPGRADE — Ledoit-Wolf Shrinkage Eigenvalue Cleaning
        # Automatically shrinks noise out of the historical covariance window
        historical_returns_slice = returns_df.tail(COV_LOOKBACK).values
        historical_returns_slice = np.nan_to_num(historical_returns_slice, nan=0.0)
        cov_matrix, shrinkage_coeff = ledoit_wolf(historical_returns_slice)

        # Step 4: Deconstruct Cleaned Covariance to Correlation Matrix C
        diag_sqrt = np.sqrt(np.diag(cov_matrix))
        diag_sqrt = np.where(diag_sqrt == 0, 0.00001, diag_sqrt)
        v_inv = np.diag(1.0 / diag_sqrt)
        C = v_inv @ cov_matrix @ v_inv

        # Step 5: Core Matrix Fractional Power Operator (C^-0.5)
        # Apply np.real to clean SciPy numerical complex residuals (e.g. 1e-16j)
        C_minus_half = np.real(la.inv(la.sqrtm(C)))

        # Compute instant frictionless target weights
        w_raw = std_devs @ C_minus_half @ phi_t

        # Step 6: Direct Sizing Scale to constant target volatility
        portfolio_variance = w_raw.T @ cov_matrix @ w_raw
        if portfolio_variance <= 0:
            return None, None, 0.0

        scale_factor = TARGET_VOL / (np.sqrt(portfolio_variance) * np.sqrt(252))
        final_weights = w_raw * scale_factor

        return final_weights, phi_t, shrinkage_coeff

    except Exception as e:
        print(f"⚠️ Cleaned Engine Execution Failure: {str(e)}")
        return None, None, 0.0


def run_stable_analysis(tickers):
    """Downloads historical data and triggers the Ledoit-Wolf-optimized ARP engine."""
    cleaned_tickers = []
    for t in tickers:
        sym = str(t).strip().split()[0].replace(",", "")
        if not sym.endswith(".NS"):
            sym += ".NS"
        cleaned_tickers.append(sym)

    print(f"[INFO] Downloading market matrices from Yahoo Finance for {len(cleaned_tickers)} assets...")
    data = yf.download(cleaned_tickers, period="4y", interval="1d", progress=False, auto_adjust=True)

    if data.empty or "Close" not in data:
        print("[ERROR] Financial feed download returned empty dataframe matrices.")
        return pd.DataFrame()

    close_df = data["Close"]
    if isinstance(close_df.columns, pd.MultiIndex):
        close_df.columns = close_df.columns.get_level_values(0)

    # Clean data panel: drop assets missing significant chunks of history
    close_df = close_df.dropna(axis=1, thresh=int(len(close_df) * 0.8))

    if len(close_df) < COV_LOOKBACK:
        print(f"[ERROR] Available historical dates ({len(close_df)}) less than required threshold ({COV_LOOKBACK}).")
        return pd.DataFrame()

    close_df = close_df.ffill().bfill()
    daily_returns = close_df.pct_change().dropna(how="all")

    print("[INFO] Optimizing covariance structure via Ledoit-Wolf Regularization...")
    weights, current_signals, shrinkage = compute_frictionless_arp_cleaned(daily_returns)

    if weights is None:
        return pd.DataFrame()

    print(f"[INFO] Eigenvalue Shrunk: Applied {round(shrinkage * 100, 2)}% regularizing weight to the target covariance matrix.\n")

    latest_prices = close_df.iloc[-1]
    results = []
    for i, col in enumerate(daily_returns.columns):
        ticker_clean = col.replace(".NS", "")
        results.append({
            "Ticker": ticker_clean,
            "Price": round(float(latest_prices[col]), 2),
            "Signal_Strength": round(float(current_signals[i]), 4),
            "Target_Weight%": round(float(weights[i]) * 100, 2),
            "Direction": "LONG" if current_signals[i] > 0 else "SHORT"
        })

    return pd.DataFrame(results)


def dispatch_telegram_broadcast(res):
    """Builds and delivers outbound Telegram payload."""
    if not MY_TOKEN or not MY_CHAT_ID or "YOUR" in MY_TOKEN:
        print("[WARNING] Telegram skipped: Bot Token configuration invalid.")
        return

    msg = f"🏛️ *SHRUNK AGNOSTIC RISK PARITY REPORT: {CSV_NAME}*\n_Pure Frictionless Allocation | Ledoit-Wolf Eigen-Cleaned_\n\n"
    for _, r in res.head(20).iterrows():
        emoji_dir = "🟢" if r['Direction'] == "LONG" else "🔴"
        msg += f"• `{r['Ticker']}`: *₹{r['Price']}* | Weight: `{r['Target_Weight%']}%` | Signal: {r['Signal_Strength']} {r['Direction']} {emoji_dir}\n"

    tv_list = ",".join([f"NSE:{r['Ticker']}" for _, r in res.head(20).iterrows()])
    msg += f"\n📺 *WATCHLIST*\n`{tv_list}`"

    print("[INFO] Broadcasting portfolio configurations to Telegram Matrix...")
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
            print("[SUCCESS] Shrunk portfolio configurations successfully delivered to Telegram!")
        else:
            print(f"[ERROR] Telegram submission fault {r.status}: {r.data.decode('utf-8')}")
    except Exception as e:
        print(f"[WARNING] Network error while dispatching Telegram alert: {e}")


if __name__ == "__main__":
    if os.path.exists(CSV_NAME):
        df_csv = pd.read_csv(CSV_NAME)
        
        col = next((c for c in df_csv.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_csv.columns[0])
        tickers = df_csv[col].dropna().unique()

        print(f"[INFO] Initializing ARP Matrix Scanner on {len(tickers)} assets from {CSV_NAME}...")
        print(f"[INFO] Constraints: Frictionless Allocation | Ledoit-Wolf Cleaned | Target Vol: {TARGET_VOL*100}%\n")

        res = run_stable_analysis(tickers)

        if not res.empty:
            res["Abs_Weight"] = res["Target_Weight%"].abs()
            res = res.sort_values(by="Abs_Weight", ascending=False).drop(columns=["Abs_Weight"]).reset_index(drop=True)

            print("\n[INFO] Top 20 Shrunk Portfolio Allocations:")
            print(res.head(20).to_string(index=False))

            # Deliver report
            dispatch_telegram_broadcast(res)
        else:
            print("[ERROR] Engine completed with zero valid asset allocations.")
    else:
        print(f"[ERROR] Target watchlist CSV missing: Check if '{CSV_NAME}' is in the root directory.")
