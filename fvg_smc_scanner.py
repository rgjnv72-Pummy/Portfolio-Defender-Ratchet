from beast_standards import check_beast_liquidity_standards
import http.client, json, os, warnings
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# --- CONFIG (Maps securely to your GitHub Action Environment) ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
MANUAL_N500_CSV = 'ind_nifty500list.csv'

warnings.filterwarnings("ignore")
MIN_AVG_VOLUME = 100000
EMA_TREND_PERIOD = 200
SWEEP_LOOKBACK = 12
MSS_LOOKBACK = 7
MAX_STOCKS_PER_SECTOR = 5
LOOKBACK_DAYS_FOR_FVG = 5

SECTOR_INDEX_MAP = {
    "BANK": "^NSEBANK",
    "FINANCE": "NIFTY_FIN_SERVICE.NS",
    "IT": "^CNXIT",
    "PHARMA": "^CNXPHARMA",
    "AUTO": "^CNXAUTO",
    "METAL": "^CNXMETAL",
    "REALTY": "^CNXREALTY",
    "FMCG": "^CNXFMCG",
    "INFRA": "^CNXINFRA",
    "ENERGY": "^CNXENERGY",
    "MEDIA": "^CNXMEDIA",
    "COMMODITIES": "^CNXCMDT"
}

def send_telegram(text):
    if not TOKEN or not CHAT_ID: return
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
    finally: conn.close()

def normalize_nse_industry(raw_industry_str):
    raw = str(raw_industry_str).upper().strip()
    if "BANK" in raw: return "BANK"
    if "FINAN" in raw or "INSUR" in raw: return "FINANCE"
    if "IT " in raw or "TECHNOLOGY" in raw or "SOFTWARE" in raw or "TELECOM" in raw: return "IT"
    if "HEALTH" in raw or "PHARMA" in raw or "BIOTECH" in raw: return "PHARMA"
    if "AUTO" in raw or "VEHICLE" in raw: return "AUTO"
    if "METALS" in raw or "MINING" in raw or "STEEL" in raw: return "METAL"
    if "REALTY" in raw or "REAL ESTATE" in raw: return "REALTY"
    if "FMCG" in raw or "CONSUMER GOODS" in raw or "FOOD" in raw or "BEVERAGE" in raw or "PAINT" in raw: return "FMCG"
    if "CONSTRUCT" in raw or "INFRA" in raw or "PORT" in raw or "SERVICES" in raw: return "INFRA"
    if "POWER" in raw or "ENERGY" in raw or "OIL" in raw or "GAS" in raw or "FUEL" in raw: return "ENERGY"
    if "MEDIA" in raw or "ENTERTAIN" in raw: return "MEDIA"
    if "CHEMI" in raw or "COMMODIT" in raw or "TEXTI" in raw or "PAPER" in raw or "INDUSTRIALS" in raw: return "COMMODITIES"
    return "UNKNOWN"

def calculate_momentum_drift(close_series):
    try:
        cl = close_series.squeeze()
        if len(cl) < 251: return -999.0
        drift = (((cl.iloc[-1] / cl.iloc[-250]) - 1) / 250 * 0.7) + (((cl.iloc[-1] / cl.iloc[-20]) - 1) / 20 * 0.3)
        return float(drift)
    except: return -999.0

def rank_sector_momentum():
    sector_ranks = {}
    print("📊 Calculating Dynamic Sector Momentum Rankings...")
    for sector_name, index_ticker in SECTOR_INDEX_MAP.items():
        try:
            tk = yf.Ticker(index_ticker)
            df_index = tk.history(period="2y", interval="1d", auto_adjust=True)
            if not df_index.empty and len(df_index) >= EMA_TREND_PERIOD:
                close = df_index["Close"].squeeze()
                drift = calculate_momentum_drift(close)
                
                close_prices = close.values
                ema = np.zeros_like(close_prices)
                ema[EMA_TREND_PERIOD-1] = np.mean(close_prices[:EMA_TREND_PERIOD])
                multiplier = 2 / (EMA_TREND_PERIOD + 1)
                for idx in range(EMA_TREND_PERIOD, len(close_prices)):
                    ema[idx] = (close_prices[idx] - ema[idx-1]) * multiplier + ema[idx-1]
                
                is_healthy = close_prices[-1] > ema[-1]
                sector_ranks[sector_name] = {"drift": drift, "healthy": is_healthy}
            else:
                sector_ranks[sector_name] = {"drift": 0.0, "healthy": True}
        except:
            sector_ranks[sector_name] = {"drift": 0.0, "healthy": True}
    return sector_ranks

def scan_recent_bullish_fvgs(df):
    is_passed, beast_metrics = check_beast_liquidity_standards(df)
    if not is_passed:
        return None
    try:
        df_clean = df.copy()
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = df_clean.columns.get_level_values(0)

        close = df_clean["Close"].squeeze()
        high = df_clean["High"].squeeze()
        low = df_clean["Low"].squeeze()
        open_p = df_clean["Open"].squeeze()
        volume = df_clean["Volume"].squeeze()

        if len(close) < EMA_TREND_PERIOD:
            return False, {}, "Insufficient History"

        avg_volume_20d = volume.iloc[-20:].mean()
        if avg_volume_20d < MIN_AVG_VOLUME:
            return False, {}, "Failed Liquidity Filter"

        close_prices = close.values
        ema = np.zeros_like(close_prices)
        ema[EMA_TREND_PERIOD-1] = np.mean(close_prices[:EMA_TREND_PERIOD])
        multiplier = 2 / (EMA_TREND_PERIOD + 1)
        for idx in range(EMA_TREND_PERIOD, len(close_prices)):
            ema[idx] = (close_prices[idx] - ema[idx-1]) * multiplier + ema[idx-1]

        if close_prices[-1] < ema[-1]:
            return False, {}, "Below 200 EMA"

        current_close = float(close.iloc[-1])
        total_bars = len(df_clean)

        for offset in range(1, LOOKBACK_DAYS_FOR_FVG + 1):
            i = total_bars - offset
            if i < 20: continue

            c1_high, c1_low = float(high.iloc[i-2]), float(low.iloc[i-2])
            c2_open, c2_close = float(open_p.iloc[i-1]), float(close.iloc[i-1])
            c3_low = float(low.iloc[i])

            is_fvg = c3_low > c1_high
            is_displacement = c2_close > c2_open

            if is_fvg and is_displacement:
                fvg_top = c3_low
                fvg_bottom = c1_high
                fvg_50 = fvg_bottom + (fvg_top - fvg_bottom) * 0.5
                stop_loss = c1_low - 0.05

                if current_close < fvg_bottom: continue

                post_fvg_closes = close.iloc[i+1:]
                if len(post_fvg_closes) > 0 and (post_fvg_closes < fvg_bottom).any(): continue

                prior_lows = low.iloc[i-SWEEP_LOOKBACK:i-2]
                lowest_prior_low = prior_lows.min() if len(prior_lows) > 0 else np.inf
                has_sweep = (c1_low < lowest_prior_low) or (float(low.iloc[i-1]) < lowest_prior_low)

                prior_highs = high.iloc[i-MSS_LOOKBACK:i-2]
                highest_prior_high = prior_highs.max() if len(prior_highs) > 0 else -np.inf
                has_mss = (c2_close > highest_prior_high) or (float(close.iloc[i]) > highest_prior_high)

                if has_sweep and has_mss:
                    setup_grade, sort_rank = "A+", 1
                elif has_mss:
                    setup_grade, sort_rank = "A", 2
                else:
                    setup_grade, sort_rank = "B", 3

                metrics = {
                    "Grade": f"{setup_grade} [{offset-1}d Ago]",
                    "Raw_Grade": setup_grade,
                    "Sort_Rank": sort_rank,
                    "Aggressive_Entry": round(fvg_top, 2),
                    "Conservative_Entry": round(fvg_50, 2),
                    "Stop_Loss": round(stop_loss, 2),
                }
                return True, metrics, "PASSED"
        return False, {}, "No FVG"
    except:
        return False, {}, "Error"
def run_stable_analysis(df_watchlist, sector_ranks):
    results = []
    sym_col = next((c for c in df_watchlist.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_watchlist.columns)
    sec_col = next((c for c in df_watchlist.columns if "sector" in c.lower() or "industry" in c.lower()), None)

    print("⚙️ Constraints: Price > 200 EMA | Vol > 100,000 | Active 5d Lookback")
    for _, row in df_watchlist.iterrows():
        try:
            ticker_raw = str(row[sym_col]).strip().replace(",", "")
            sym = ticker_raw + ".NS" if not ticker_raw.endswith(".NS") else ticker_raw

            raw_sector = row[sec_col] if sec_col else "UNKNOWN"
            sector = normalize_nse_industry(raw_sector)

            if sector in sector_ranks and not sector_ranks[sector]["healthy"]:
                continue

            tk = yf.Ticker(sym)
            d_df = tk.history(period="2y", interval="1d", auto_adjust=True)

            if d_df.empty or len(d_df) < EMA_TREND_PERIOD:
                continue

            filter_passed, metrics, _ = scan_recent_bullish_fvgs(d_df)

            if filter_passed:
                current_price = float(d_df["Close"].squeeze().iloc[-1])
                cl = d_df["Close"].squeeze()

                drift = calculate_momentum_drift(cl)
                target = current_price * (1 + (drift * 30))
                upside = ((target - current_price) / current_price) * 100

                dist_to_agg = ((current_price - metrics["Aggressive_Entry"]) / metrics["Aggressive_Entry"]) * 100
                dist_to_cons = ((current_price - metrics["Conservative_Entry"]) / metrics["Conservative_Entry"]) * 100

                # DYNAMIC STATISTICAL RISK-TO-REWARD MATRICES
                risk_amt = metrics["Conservative_Entry"] - metrics["Stop_Loss"]
                reward_amt = target - metrics["Conservative_Entry"]
                rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 0.0

                if -50 < upside < 100:
                    results.append(
                        {
                            "Ticker": ticker_raw,
                            "Sector": sector,
                            "Price": round(current_price, 2),
                            "Grade": metrics["Grade"],
                            "Raw_Grade": metrics["Raw_Grade"],
                            "Sort_Rank": metrics["Sort_Rank"],
                            "Agg_Entry": metrics["Aggressive_Entry"],
                            "Dist_To_Agg%": round(dist_to_agg, 2),
                            "Cons_Entry": metrics["Conservative_Entry"],
                            "Dist_To_Cons%": round(dist_to_cons, 2),
                            "Stop_Loss": metrics["Stop_Loss"],
                            "Upside%": round(upside, 2),
                            "RR_Ratio": round(rr_ratio, 2),
                            "Sector_Drift": sector_ranks.get(sector, {}).get("drift", 0.0)
                        }
                    )
        except:
            continue

    df_res = pd.DataFrame(results)
    if df_res.empty: return df_res

    df_res = df_res.sort_values(by=["Sort_Rank", "Upside%"], ascending=[True, False])
    df_res = df_res.groupby("Sector").head(MAX_STOCKS_PER_SECTOR).reset_index(drop=True)
    return df_res.sort_values(by=["Sort_Rank", "Upside%"], ascending=[True, False])

def run_scan():
    print("🚀 Initializing SMC FVG Automated Execution Script...")
    if not os.path.exists(MANUAL_N500_CSV):
        print(f"❌ Missing mandatory underlying file footprint: '{MANUAL_N500_CSV}'")
        return
        
    df_csv = pd.read_csv(MANUAL_N500_CSV)
    sector_ranks = rank_sector_momentum()
    res = run_stable_analysis(df_csv, sector_ranks)

    if not res.empty:
        target_date = datetime.now().strftime('%d-%m-%Y')
        msg = f"🏆 *INSTITUTIONAL HIGH-GRADE FVG REPORT ({target_date})*\n_Grade A+ & A Premium Alerts Only | Vol > 100k | Active Gaps <= 5d_\n\n"

        broadcast_count = 0
        watchlist_tickers = []

        for _, r in res.iterrows():
            if r['Raw_Grade'] == 'B': continue

            broadcast_count += 1
            watchlist_tickers.append(f"NSE:{r['Ticker']}")

            if broadcast_count <= 15:
                msg += f"• `{r['Ticker']}` ({r['Sector']}): *{r['Price']}* | *{r['Grade']}*\n"
                msg += f"  ↳ Agg Limit: `{r['Agg_Entry']}` (Dist: *{r['Dist_To_Agg%']}%*)\n"
                msg += f"  ↳ Cons Limit: `{r['Cons_Entry']}` (Dist: *{r['Dist_To_Cons%']}%*)\n"
                msg += f"  ↳ Stop Loss: `{r['Stop_Loss']}` | Upside: {r['Upside%']}% | R:R: *1:{r['RR_Ratio']}*\n\n"

        if broadcast_count > 0:
            tv_list = ",".join(watchlist_tickers[:15])
            msg += "━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"📺 *PREMIUM WATCHLIST*\n`{tv_list}`"
            send_telegram(msg)
            print("✅ SUCCESS! Premium Quality Grade-Sorted FVG report sent to Telegram.")
        else:
            print("Scan completed. No Grade A+ or Grade A opportunities met filters today.")
    else:
        print("No active, unmitigated multi-day FVG setups found matching your current filters.")

if __name__ == "__main__":
    run_scan()
