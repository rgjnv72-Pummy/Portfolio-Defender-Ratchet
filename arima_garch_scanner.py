import json
import os
import urllib3
import warnings
import numpy as np
import pandas as pd
import requests
from arch import arch_model
from statsmodels.tsa.arima.model import ARIMA
from tqdm import tqdm

# --- WARNING FILTERS (Cleans environment log output clutter) ---
warnings.filterwarnings("ignore")

# --- CONFIGURATION & STATISTICAL PARAMETERS ---
TKN = os.getenv("TELEGRAM_TOKEN", "").strip()
UID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DRIVE_FOLDER = "."  # Directs engine to look straight into repository root space

# SWING PERFORMANCE CONFIGURATIONS
LOOKBACK_WINDOW = 252       # 1-year baseline for historical regression training
SWING_HORIZON = 20          # 20-day forward-looking tactical swing hold timeframe
MIN_20D_HURDLE = 5.0        # Alpha Gatekeeper: Minimum expected 20-day return (%)
MIN_AVG_VOLUME = 500000     # Minimum 20-day Average Daily Volume for liquidity

try:
    import yfinance as yf
except ImportError:
    print("❌ Critical dependency yfinance missing.")
    exit(1)

def check_arima_garch_filter(df):
    """
    Applies Liquidity checks and executes a 20-day compounded time-series projection
    designed to identify institutional-grade bullish swing breakout candidates.
    """
    try:
        df_clean = df.copy()
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        close = df_clean["Close"].squeeze()
        volume = df_clean["Volume"].squeeze()

        # Minimum bar check required for rolling history initialization
        if len(close) < LOOKBACK_WINDOW + 2:
            return False, 0.0, 0.0, "Insufficient History"

        # --- FILTER 1: LIQUIDITY CHECK ---
        avg_volume_20d = volume.iloc[-20:].mean()
        if avg_volume_20d < MIN_AVG_VOLUME:
            return False, 0.0, 0.0, "Failed Liquidity Filter"

        # --- CORE QUANT ENGINE: 20-DAY TIMEFRAME UPGRADE ---
        window_prices = close.tail(LOOKBACK_WINDOW + 1)
        returns = np.log(window_prices / window_prices.shift(1)).dropna() * 100

        # Fit ARIMA(1,0,1) model to isolate conditional structural trends
        arima = ARIMA(returns, order=(1, 0, 1)).fit()

        # Project a full 20-day trading month into the future
        forecast_array = arima.forecast(steps=SWING_HORIZON)

        # Compounded geometric return over the 20-day holding vector
        cumulative_swing_forecast = float(np.sum(forecast_array))

        # High Momentum Alpha Hurdle (Target >= 5% growth over 20 days)
        if cumulative_swing_forecast < MIN_20D_HURDLE:
            return False, 0.0, 0.0, "Fails 20D Bullish Hurdle Rate"

        # Fit GARCH(1,1) onto ARIMA residuals to discover multi-week latent risk
        garch = arch_model(arima.resid, vol="Garch", p=1, q=1).fit(disp="off")

        # Accumulate forecasted variance across all 20 unique trading dates
        garch_forecast = garch.forecast(horizon=SWING_HORIZON)
        variance_forecasts = garch_forecast.variance.values[-1]

        # Integrated 20-day volatility is the square root of the accumulated variance
        integrated_vol_forecast = float(np.sqrt(np.sum(variance_forecasts)))

        # Position Sizing calibrated for long-duration risk profiles
        position_size = min(1.0, 4.0 / max(integrated_vol_forecast, 0.4))

        if np.isnan(cumulative_swing_forecast) or np.isnan(integrated_vol_forecast):
            return False, 0.0, 0.0, "Corrupted Math Engine Values"

        return True, round(cumulative_swing_forecast, 4), round(position_size, 4), "PASSED"
    except:
        return False, 0.0, 0.0, "System Processing Error"

def run_stable_analysis(tickers):
    results = []
    print(f"[INFO] Downloading historical data in batch for {len(tickers)} assets...")
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    
    try:
        master_data = yf.download(tickers, period="2y", interval="1d", group_by="ticker", progress=False, auto_adjust=True, session=session)
    except Exception as e:
        print(f"[ERROR] Batch download failed: {e}. Falling back to sequential execution.")
        master_data = None

    is_multi = isinstance(master_data.columns, pd.MultiIndex) if master_data is not None else False

    for sym in tqdm(tickers, desc="Analyzing Assets"):
        try:
            if master_data is not None and is_multi and sym in master_data.columns.levels[0]:
                d_df = master_data[sym].dropna(subset=["Close"])
            else:
                tk = yf.Ticker(sym)
                d_df = tk.history(period="2y", interval="1d", raise_errors=False, auto_adjust=True)

            if d_df.empty or len(d_df) < LOOKBACK_WINDOW:
                continue

            filter_passed, forecast, position_size, reason = check_arima_garch_filter(d_df)

            if filter_passed:
                current_price = float(d_df["Close"].squeeze().iloc[-1])
                results.append(
                    {
                        "Ticker": sym.replace(".NS", ""),
                        "Price": round(current_price, 2),
                        "Forecast_20D_Return": forecast,
                        "Position_Size": position_size,
                    }
                )
        except Exception as e:
            continue
    return pd.DataFrame(results)

def main():
    # Scan for your root level asset file ind_nifty500list.csv
    csv_files = sorted([f for f in os.listdir(DRIVE_FOLDER) if f.endswith('nifty500list.csv')])
    if not csv_files:
        print(f"❌ Error: Data target file 'ind_nifty500list.csv' not found in root path.")
        return

    selected_file = csv_files[0]
    csv_path = os.path.join(DRIVE_FOLDER, selected_file)
    
    try:
        df_csv = pd.read_csv(csv_path)
    except Exception as e:
        print(f"❌ Read Failure on file {selected_file}: {e}")
        return

    col = next((c for c in df_csv.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_csv.columns[0])
    raw_tickers = df_csv[col].dropna().unique().tolist()
    
    formatted_tickers = []
    for t in raw_tickers:
        sym = str(t).strip().split()[0].replace(",", "")
        if not sym or "NAN" in sym.upper() or "SYMBOL" in sym.upper():
            continue
        if not sym.endswith(".NS"):
            sym += ".NS"
        formatted_tickers.append(sym)

    print(f"🚀 Running ARIMA-GARCH 20-Day Swing Analysis on {len(formatted_tickers)} stocks...")
    print(f"⚙️ Constraints: 20d Avg Vol > {MIN_AVG_VOLUME:,} shares | Expected Target > {MIN_20D_HURDLE}%\n")
    
    res = run_stable_analysis(formatted_tickers)

    if not res.empty:
        # Sort descending to expose the highest potential alpha returns over the 20-day swing horizon
        res = res.sort_values(by="Forecast_20D_Return", ascending=False).reset_index(drop=True)
        print(res.head(20).to_string())

        # BUILD OUTBOUND TELEGRAM PAYLOAD
        msg = f"🏆 *ARIMA-GARCH 20-DAY BULLISH SWING REPORT*\n_Multi-Week Compounded Drift | Volatility-Scaled Sizing_\n\n"
        for _, r in res.head(20).iterrows():
            msg += f"• `{r['Ticker']}`: *{r['Price']}* | 20D Swing Return: `+{r['Forecast_20D_Return']}%` | Risk Allocation: {int(r['Position_Size']*100)}%\n"

        tv_list = ",".join([f"NSE:{r['Ticker']}" for _, r in res.head(20).iterrows()])
        msg += f"\n📺 *WATCHLIST*\n`{tv_list}`"

        if not TKN or not UID:
            print("⚠️ Telegram configurations missing in Environment Secrets setup.")
            return

        print("📤 Transmitting dispatch telemetry payload to Telegram...")
        api_domain = "api.telegram.org"
        http_client = urllib3.PoolManager()
        try:
            full_url = f"https://{api_domain}/bot{TKN}/sendMessage"
            encoded_msg = json.dumps({"chat_id": UID, "text": msg, "parse_mode": "Markdown"})
            r = http_client.request("POST", full_url, body=encoded_msg, headers={"Content-Type": "application/json"})

            if r.status == 200:
                print("✅ SUCCESS! Distinct ARIMA-GARCH report sent to Telegram.")
            else:
                print(f"❌ REJECTED: {r.status} - {r.data.decode()}")
        except Exception as e:
            print(f"❌ CONNECTION ERROR: {str(e)}")
    else:
        print("✅ Analysis Complete: Zero stocks met the model criteria thresholds today.")

if __name__ == "__main__":
    main()
