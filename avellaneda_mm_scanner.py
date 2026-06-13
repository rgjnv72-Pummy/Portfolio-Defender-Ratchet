import os
import json
import math
import time
import urllib3
import warnings
import numpy as np
import pandas as pd
from tqdm import tqdm
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

# --- WARNING FILTERS ---
warnings.filterwarnings("ignore")

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '1280803679').strip()
MY_TOKEN = os.getenv('TELEGRAM_TOKEN', '8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o').strip()
CSV_NAME = "ind_nifty500list.csv"

# STRATEGY HYPERPARAMETERS
GAMMA = 0.1          # Risk aversion parameter
K_DECAY = 1.5        # Order book liquidity density factor
SIGMA_START = 0.30   # Default annualized volatility (30%)
HORIZON_T = 1.0      # Trading horizon scaling factor
LIQUIDITY_A = 150.0  # Order arrival multiplier constant
VOL_WINDOW = 50      # Lookback rolling frame window for realized tracking
CB_MULTIPLIER = 4.5  # Scaling margin factor to prevent false pauses

class StructuralAvellanedaEngine:
    def __init__(self, gamma=GAMMA, k=K_DECAY, sigma=SIGMA_START, T=HORIZON_T, A=LIQUIDITY_A):
        self.gamma = gamma
        self.k = k
        self.sigma = sigma
        self.T = T
        self.A = A

    def process_and_quote(self, df_prices, step, n_steps, current_inventory):
        try:
            if len(df_prices) < 5:
                return False, {}, "Insufficient History"

            # Parse structural series tracking properties cleanly as a 1D float vector
            prices = np.array(df_prices[-VOL_WINDOW:], dtype=float).flatten()
            mid_price = float(prices[-1])
            dt = self.T / n_steps
            t = step * dt

            # --- MODULE 1: ADAPTIVE REALIZED VOLATILITY STEPPING ---
            returns = np.diff(prices)
            step_vol = returns.std()
            if step_vol > 0:
                self.sigma = step_vol / math.sqrt(dt)

            if np.isnan(self.sigma) or np.isinf(self.sigma) or self.sigma <= 0:
                return False, {}, "Corrupted Math Engine Volatility"

            # --- MODULE 2: VOLATILITY CIRCUIT BREAKER ---
            recent_window = list(prices)[-5:]
            price_movement = abs(recent_window[-1] - recent_window[0])
            breaker_threshold = CB_MULTIPLIER * step_vol * math.sqrt(5)

            if price_movement > breaker_threshold:
                return False, {}, "Circuit Breaker Tripped"

            # --- MODULE 3: RESERVATION & SPREAD DERIVATION ---
            r = mid_price - current_inventory * self.gamma * (self.sigma ** 2) * (self.T - t)

            risk_term = self.gamma * (self.sigma ** 2) * (self.T - t)
            arrival_term = (2.0 / self.gamma) * math.log(1.0 + self.gamma / self.k)
            spread = risk_term + arrival_term

            half_spread = spread / 2.0
            bid = r - half_spread
            ask = r + half_spread

            intensity = self.A * math.exp(-self.k * half_spread)

            payload = {
                "Mid": round(mid_price, 4), "Reservation": round(r, 4),
                "Bid": round(bid, 4), "Ask": round(ask, 4), "Spread": round(spread, 4),
                "Intensity": round(intensity, 2), "Sigma_Annual": round(self.sigma, 4)
            }
            return True, payload, "PASSED"
        except Exception as e:
            return False, {}, f"Execution System Failure: {str(e)}"


def run_simulation_session(price_series, n_steps=200, seed=42):
    rng = np.random.default_rng(seed)
    engine = StructuralAvellanedaEngine()

    inventory = 0.0
    cash = 0.0
    paused_steps = 0
    records = []

    total_available = len(price_series)
    start_idx = max(0, total_available - n_steps)
    active_series = price_series[start_idx:]
    dt = engine.T / max(1, len(active_series))

    for step in range(len(active_series)):
        current_history = active_series[:step + 1]
        s = float(current_history[-1])

        success, metrics, reason = engine.process_and_quote(current_history, step, len(active_series), inventory)

        if not success:
            paused_steps += 1
            records.append({
                "Step": step, "Mid": s, "Reservation": np.nan, "Bid": np.nan, "Ask": np.nan,
                "Spread": np.nan, "Inventory": inventory, "PnL": cash + inventory * s, "Paused": True
            })
            continue

        sell_arrived = rng.poisson(metrics["Intensity"] * dt)
        buy_arrived = rng.poisson(metrics["Intensity"] * dt)

        if sell_arrived > 0:
            inventory += 1.0
            cash -= metrics["Bid"]

        if buy_arrived > 0:
            inventory -= 1.0
            cash += metrics["Ask"]

        current_pnl = cash + inventory * s

        records.append({
            "Step": step, "Mid": metrics["Mid"], "Reservation": metrics["Reservation"],
            "Bid": metrics["Bid"], "Ask": metrics["Ask"], "Spread": metrics["Spread"],
            "Inventory": inventory, "PnL": round(current_pnl, 4), "Paused": False
        })

    df_res = pd.DataFrame(records).set_index("Step")
    return df_res, paused_steps, len(active_series)


def scan_single_asset(sym, sector):
    try:
        ticker_handler = yf.Ticker(sym)
        historical_df = ticker_handler.history(period="1y", interval="1d", raise_errors=False, auto_adjust=True)

        if historical_df.empty or len(historical_df) < (VOL_WINDOW + 10):
            return None

        df_clean = historical_df.copy()
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        raw_price_feed = df_clean["Close"].squeeze().dropna().values
        if len(raw_price_feed) < (VOL_WINDOW + 10):
            return None

        # CRITICAL QUANT ALIGNMENT: Normalize price to base 100 to scale daily absolute volatility.
        # This keeps spreads proportional to the asset price and enables actual fill events.
        price_feed = raw_price_feed / raw_price_feed[0] * 100

        df_sim, paused, total_steps = run_simulation_session(price_feed)

        if df_sim.empty:
            return None

        active_frames = df_sim[~df_sim["Paused"]]
        pnl_diffs = active_frames["PnL"].diff().dropna()

        if pnl_diffs.std() > 0:
            sharpe = (pnl_diffs.mean() / pnl_diffs.std()) * math.sqrt(total_steps / HORIZON_T)
        else:
            sharpe = 0.0

        final_pnl = float(df_sim["PnL"].iloc[-1])
        max_inv = float(df_sim["Inventory"].abs().max())
        trades = (df_sim['Inventory'].diff().fillna(0) != 0).sum()

        # Only select assets that actually had trading activity in the simulation
        if trades == 0:
            return None

        return {
            "Ticker": sym.replace(".NS", ""),
            "Sector": sector,
            "Final_PnL": round(final_pnl, 2),
            "Max_Inventory": max_inv,
            "Steps_Paused": paused,
            "Horizon_Sharpe": round(sharpe, 4),
            "Total_Trades": int(trades),
            "Last_Price_INR": round(float(raw_price_feed[-1]), 2)
        }
    except:
        return None


def dispatch_telegram_broadcast(df_final):
    """Broadcasts top market making candidates to Telegram."""
    if not MY_TOKEN or not MY_CHAT_ID or "YOUR" in MY_TOKEN:
        print("[WARNING] Telegram skipped: Bot Token configuration invalid.")
        return

    print("[INFO] Broadcasting configurations to Telegram Matrix...")
    http = urllib3.PoolManager()

    text_message = f"🤖 *STRUCTURAL AVELLANEDA MARKET-MAKING* 🤖\n"
    text_message += f"📋 Source List: `{CSV_NAME}` | Normalization: *Base 100*\n"
    text_message += f"📊 Viable MM Setups Found: *{len(df_final)}*\n"
    text_message += "═══════════════════════\n\n"

    for idx, row in df_final.head(10).iterrows():
        text_message += f"{idx+1}️⃣ *{row['Ticker']}* | {row['Sector']}\n"
        text_message += f" ├ Last Price: *₹{row['Last_Price_INR']}*\n"
        text_message += f" ├ Sharpe Ratio: *{row['Horizon_Sharpe']}*\n"
        text_message += f" ├ Simulated PnL: *{row['Final_PnL']}%*\n"
        text_message += f" ├ Trades Executed: {row['Total_Trades']}\n"
        text_message += f" └ Max inventory: {row['Max_Inventory']} units\n\n"

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
    sym_col = next((c for c in df_watchlist.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_watchlist.columns[0])
    sec_col = next((c for c in df_watchlist.columns if "sector" in c.lower() or "industry" in c.lower()), None)

    print(f"[INFO] Ingesting watchlist and scanning unique assets...")
    
    tasks = []
    for _, row in df_watchlist.iterrows():
        raw_sym = str(row[sym_col]).strip().replace(",", "")
        if not raw_sym or "NAN" in raw_sym.upper() or "SYMBOL" in raw_sym.upper():
            continue
        sym = raw_sym if ".NS" in raw_sym.upper() else f"{raw_sym}.NS"
        sector = str(row[sec_col]).strip() if sec_col else "UNKNOWN"
        tasks.append((sym, sector))

    results = []
    # Utilize multithreading to speed up the 500-ticker batch scan
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(scan_single_asset, t[0], t[1]) for t in tasks]
        for f in tqdm(futures, desc="Running Avellaneda-Stoikov Simulations"):
            res = f.result()
            if res is not None:
                results.append(res)

    if not results:
        print("[INFO] No assets completed the simulation with active trades.")
        return pd.DataFrame()

    final_df = pd.DataFrame(results)
    # Sort primarily by Sharpe ratio and secondarily by PnL (both descending)
    final_df = final_df.sort_values(by=["Horizon_Sharpe", "Final_PnL"], ascending=[False, False]).reset_index(drop=True)
    return final_df


if __name__ == "__main__":
    if os.path.exists(CSV_NAME):
        watchlist_matrix = pd.read_csv(CSV_NAME)
        output_dashboard = run_stable_analysis(watchlist_matrix)

        if not output_dashboard.empty:
            print(f"\n[INFO] PROCESSED TARGET WATCHLIST ACQUISITIONS: {CSV_NAME}")
            print("==========================================================================")
            print(output_dashboard.head(10).to_string(index=False))

            # Forward metrics to messaging API
            dispatch_telegram_broadcast(output_dashboard)
        else:
            print("[INFO] Scan complete. No viable market making opportunities identified.")
    else:
        print(f"[ERROR] Target path CSV missing: Check if '{CSV_NAME}' is in the root directory.")
