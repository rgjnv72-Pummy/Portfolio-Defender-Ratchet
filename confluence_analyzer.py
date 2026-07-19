import os
import sys
import json
import warnings
import http.client
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

# --- UTF-8 CONSOLE ENCODING FIX (Windows Support) ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# --- WARNING FILTERS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=UserWarning)

# --- AUTO-INSTALL DEPENDENCIES (Fallback) ---
try:
    import pandas_ta as ta
    import statsmodels.api as sm
except ImportError:
    import sys
    os.system(f"{sys.executable} -m pip install pandas-ta-classic==0.3.15 statsmodels --quiet")
    import pandas_ta as ta
    import statsmodels.api as sm

# --- CONFIGURATION ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
BASE_DIR = PARENT_DIR
if not os.path.exists(os.path.join(PARENT_DIR, "Obsidian-Journal")):
    BASE_DIR = SCRIPT_DIR

TICKERS_CSV = os.path.join(SCRIPT_DIR, "ind_nifty500list.csv")
REGISTRY_CSV = os.path.join(BASE_DIR, "Scanner-Scripts", "scanner_performance_registry.csv")
MASTER_FRESH_MD = os.path.join(BASE_DIR, "Obsidian-Journal", "Ticker-Research", "Master-Fresh-Trades-Scan.md")
CONFLUENCE_REPORT_MD = os.path.join(BASE_DIR, "Obsidian-Journal", "Ticker-Research", "Confluence-Report.md")
MIN_AVG_TRADED_VALUE = 20000000  # ₹2 Crores minimum daily liquidity

def load_env_file():
    env_paths = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(BASE_DIR, "Ratchet-System", ".env")
    ]
    for path in env_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            val = val.strip().strip("'").strip('"')
                            os.environ[key.strip()] = val
                break
            except Exception:
                pass

load_env_file()
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()

def send_telegram(text):
    if not TOKEN or not CHAT_ID or "YOUR" in TOKEN:
        print("[CONSOLE LOG] Telegram credentials not configured. Printing output:")
        print(text)
        return
    
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
        print("✅ Telegram notification dispatched successfully.")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
    finally:
        conn.close()

def map_signal_to_domain(sig_name):
    """Maps a raw scanner or strategy name to one of 4 core quantitative domains"""
    sig = sig_name.lower()
    # 1. Breakout & Squeeze
    if any(x in sig for x in ["vcp", "explosion", "kronos", "contraction", "squeeze", "adx-rider", "vol-spike", "stealth-base", "catalyst-acc", "rs-breakout", "vol-compression", "gap-up", "near-52w"]):
        return "Breakout & Squeeze"
    # 2. Pullback & Structure
    if any(x in sig for x in ["fvg", "smc", "pullback", "fib", "structural", "trend-pullback", "ema-pullback", "cci", "rsi-reversal", "green-on-red"]):
        return "Pullback & Structure"
    # 3. Value & Mean Reversion
    if any(x in sig for x in ["z-score", "money-flow", "arima", "garch", "kalman", "avellaneda", "quant", "clean-room-alpha"]):
        return "Value & Mean Reversion"
    # 4. Volume & ML Regime
    if any(x in sig for x in ["whale", "delivery", "spurt", "volume", "hmm", "regime", "vsa", "parity", "arp", "pocket"]):
        return "Volume & ML Regime"
    return "Other Momentum"

def evaluate_strategies(df, nifty_close=None, macro_factors_df=None):
    passed_strategies = []
    try:
        close = df["Close"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        # Handle squeeze return types (DataFrames if duplicates exist)
        close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        high = high.iloc[:, 0] if isinstance(high, pd.DataFrame) else high
        low = low.iloc[:, 0] if isinstance(low, pd.DataFrame) else low
        volume = volume.iloc[:, 0] if isinstance(volume, pd.DataFrame) else volume

        # Need at least 252 rows for high_52w and rolling calculations
        if len(close) < 252:
            return []

        # Monetary Liquidity Check
        daily_traded_value = close * volume
        avg_value_20d = daily_traded_value.iloc[-20:].mean()
        if avg_value_20d < MIN_AVG_TRADED_VALUE:
            return []

        # Indicators
        ema200 = ta.ema(close, length=200)
        if ema200 is None:
            return []

        current_close = float(close.iloc[-1])
        current_low = float(low.iloc[-1])

        # --- PLAYBOOK VECTOR ARRAYS & SCORING ---
        open_series = df["Open"].squeeze()
        open_series = open_series.iloc[:, 0] if isinstance(open_series, pd.DataFrame) else open_series

        ma20_vol = volume.rolling(window=20).mean()
        high_52w = high.rolling(window=252).max()

        cl_prev = close.shift(1)
        ma20_vol_prev = ma20_vol.shift(1)
        high_52w_prev = high_52w.shift(1)
        rolling_res = close.shift(1).rolling(window=19).max()

        # 7 Playbook evaluation streams
        s1_series = (close > cl_prev) & (close > open_series) & (volume > (ma20_vol_prev * 2.0))
        gap_pct_series = ((open_series - cl_prev) / cl_prev) * 100
        s2_series = (gap_pct_series > 1.5) & (low > cl_prev)

        stock_is_green = (close > open_series) & (close > cl_prev)
        if nifty_close is not None:
            nifty_reindexed = nifty_close.reindex(close.index).ffill()
            nifty_prev = nifty_reindexed.shift(1)
            nifty_red = (nifty_reindexed < nifty_prev)
            s3_series = stock_is_green & nifty_red
        else:
            s3_series = pd.Series(False, index=close.index)

        rolling_min = low.rolling(window=252, min_periods=20).min()
        s4_series = close >= (rolling_min * 2.0)
        s5_series = close >= (high_52w_prev * 0.99)
        day_ret_series = ((close - cl_prev) / cl_prev) * 100
        s6_series = day_ret_series >= 4.0
        s7_series = (close > rolling_res) & (volume > ma20_vol_prev)

        # 10-day rolling score
        has_scan1 = int(s1_series.iloc[-10:].max() == 1)
        has_scan2 = int(s2_series.iloc[-10:].max() == 1)
        has_scan3 = int(s3_series.iloc[-10:].max() == 1)
        has_scan4 = int(s4_series.iloc[-10:].max() == 1)
        has_scan5 = int(s5_series.iloc[-10:].max() == 1)
        has_scan6 = int(s6_series.iloc[-10:].max() == 1)
        has_scan7 = int(s7_series.iloc[-10:].max() == 1)

        conf_score = sum([has_scan1, has_scan2, has_scan3, has_scan4, has_scan5, has_scan6, has_scan7])

        # 1. Z-Score Mean Reversion
        if current_close > ema200.iloc[-1]:
            ma20 = close.rolling(window=20).mean()
            std20 = close.rolling(window=20).std()
            if not ma20.isna().all() and not std20.isna().all():
                zscore = (current_close - ma20.iloc[-1]) / std20.iloc[-1]
                if zscore < -2.0:
                    passed_strategies.append("Z-Score")

        # 2. Trend Pullback (RSI-9 < 25)
        if current_close > ema200.iloc[-1]:
            rsi_fast = ta.rsi(close, length=9)
            if rsi_fast is not None and rsi_fast.iloc[-1] < 25:
                passed_strategies.append("Trend-Pullback")

        # 3. Money Flow Oscillator
        cmf = ta.cmf(high, low, close, volume, length=20)
        rsi = ta.rsi(close, length=14)
        if cmf is not None and rsi is not None:
            if cmf.iloc[-1] > 0.10 and rsi.iloc[-1] < 35:
                passed_strategies.append("Money-Flow")

        # 4. ADX Rider
        adx = ta.adx(high, low, close, length=14)
        if adx is not None and not adx.empty:
            adx_cols = [c for c in adx.columns if "ADX_" in str(c)]
            plus_di_cols = [c for c in adx.columns if "DMP_" in str(c)]
            minus_di_cols = [c for c in adx.columns if "DMN_" in str(c)]
            if adx_cols and plus_di_cols and minus_di_cols:
                adx_col = adx_cols[0]
                plus_di = plus_di_cols[0]
                minus_di = minus_di_cols[0]
                if adx[adx_col].iloc[-1] > 25 and adx[plus_di].iloc[-1] > adx[minus_di].iloc[-1]:
                    passed_strategies.append("ADX-Rider")

        # 5. Volume Spike Breakout
        vol_ma20 = volume.rolling(window=20).mean()
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        if vol_ma20 is not None and macd is not None and not macd.empty:
            last_vol = volume.iloc[-1]
            last_vol_ma = vol_ma20.iloc[-1]
            macd_cols = [c for c in macd.columns if "MACD_" in str(c)]
            sig_cols = [c for c in macd.columns if "MACDs_" in str(c)]
            if macd_cols and sig_cols:
                macd_col = macd_cols[0]
                sig_col = sig_cols[0]
                if last_vol > (last_vol_ma * 2.0) and macd[macd_col].iloc[-1] > macd[sig_col].iloc[-1]:
                    passed_strategies.append("Vol-Spike")

        # 6. Stealth Accumulation Base
        last_15_close = close.iloc[-15:]
        min_15 = last_15_close.min()
        max_15 = last_15_close.max()
        price_range_pct = (max_15 - min_15) / min_15
        
        volume_20 = volume.iloc[-20:]
        avg_vol_20 = volume_20.mean()
        std_vol_20 = volume_20.std()
        
        if (price_range_pct < 0.04) and (volume.iloc[-1] > avg_vol_20) and (volume.iloc[-1] < avg_vol_20 + (1.5 * std_vol_20)):
            passed_strategies.append("Stealth-Base")

        # 7. Catalyst Acceleration
        vol_ramp = (volume.iloc[-1] > volume.iloc[-2]) and (volume.iloc[-2] > volume.iloc[-3])
        vol_spike = volume.iloc[-1] > (avg_vol_20 + (2.5 * std_vol_20))
        if vol_ramp and vol_spike and (current_close <= min_15 * 1.03):
            passed_strategies.append("Catalyst-Accel")

        # 8. RS Line Breakout
        if nifty_close is not None:
            nifty_reindexed = nifty_close.reindex(df.index).ffill()
            if not nifty_reindexed.isna().all():
                rs_line = df['Close'] / nifty_reindexed
                rs_max_252 = rs_line.rolling(252, min_periods=100).max()
                price_max_252 = df['Close'].rolling(252, min_periods=100).max()
                if rs_line.iloc[-1] >= rs_max_252.iloc[-1] and current_close < (price_max_252.iloc[-1] * 0.95):
                    passed_strategies.append("RS-Breakout")

        # 9. Pocket Pivot
        if len(close) >= 12:
            is_up_day = current_close > float(close.iloc[-2])
            down_days_vol = []
            for i in range(-11, -1):
                if float(close.iloc[i]) < float(close.iloc[i-1]):
                    down_days_vol.append(float(volume.iloc[i]))
            max_down_vol = max(down_days_vol) if down_days_vol else 0.0
            if is_up_day and float(volume.iloc[-1]) > max_down_vol and current_close > ema200.iloc[-1]:
                passed_strategies.append("Pocket-Pivot")

        # 10. Volatility Compression
        if len(close) >= 100:
            returns = close.pct_change()
            hv_10 = returns.tail(10).std()
            hv_100 = returns.tail(100).std()
            if hv_100 > 0:
                vci_ratio = hv_10 / hv_100
                if vci_ratio < 0.15 and current_close > ema200.iloc[-1]:
                    passed_strategies.append("Vol-Compression")

        # 11. EMA Pullback
        ema21 = ta.ema(close, length=21)
        ema50 = ta.ema(close, length=50)
        if ema21 is not None and ema50 is not None:
            in_uptrend = current_close > ema21.iloc[-1] and ema21.iloc[-1] > ema50.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1]
            touched_ema = float(low.iloc[-1]) <= ema21.iloc[-1] and current_close > ema21.iloc[-1]
            green_candle = current_close > float(df['Open'].iloc[-1])
            if in_uptrend and touched_ema and green_candle:
                passed_strategies.append("EMA-Pullback")

        # 12. CCI Playbook Breakout (CCI-27 dips below -100 in 18d window + Playbook confirmation)
        if current_close > ema200.iloc[-1]:
            cci = ta.cci(high, low, close, length=27)
            if cci is not None and len(cci) >= 18:
                cci_window = cci.iloc[-18:]
                lowest_cci = float(cci_window.min())
                if lowest_cci < -100 and conf_score >= 1:
                    passed_strategies.append("CCI-Breakout")

        # 13. Triple RSI Reversal (RSI-5 declines 3 consecutive days below 30 in macro uptrend)
        if current_close > ema200.iloc[-1]:
            rsi5 = ta.rsi(close, length=5)
            if rsi5 is not None and len(rsi5) >= 4:
                rsi_today = float(rsi5.iloc[-1])
                rsi_1d = float(rsi5.iloc[-2])
                rsi_2d = float(rsi5.iloc[-3])
                rsi_3d = float(rsi5.iloc[-4])
                
                cond1 = rsi_today < 30
                cond2 = rsi_today < rsi_1d < rsi_2d < rsi_3d
                cond3 = rsi_3d < 60
                
                if cond1 and cond2 and cond3:
                    passed_strategies.append("RSI-Reversal")

        # 14. Green on Red Day (Relative Strength: Close green while Nifty index is red)
        if current_close > ema200.iloc[-1]:
            if s3_series.iloc[-1]:
                passed_strategies.append("Green-on-Red-Day")

        # 15. Gap Up Momentum (Urgent buying: Open gap > 1.5% and low stays above yesterday's close)
        if current_close > ema200.iloc[-1]:
            if s2_series.iloc[-1]:
                passed_strategies.append("Gap-Up-Momentum")

        # 16. Near 52-Week High (Bullish Stage 2 consolidation: close within 1% of 52-week high)
        if current_close > ema200.iloc[-1]:
            if s5_series.iloc[-1]:
                passed_strategies.append("Near-52w-High")

        # 17. Clean Room Regression Alpha (OLS multi-factor alpha >= 95% confidence t-stat >= 2.0, R-Squared <= 0.35)
        if macro_factors_df is not None:
            stock_returns = close.pct_change().dropna()
            combined = pd.concat([stock_returns, macro_factors_df], axis=1).dropna()
            if len(combined) >= 252:
                # Validate scale (returns should be decimals, not raw prices)
                scale_ok = True
                for factor in ["MKT", "SMB"]:
                    if combined[factor].abs().mean() > 1.0:
                        scale_ok = False
                if scale_ok:
                    y = combined.iloc[:, 0].values
                    X_factors = combined[["MKT", "SMB"]]
                    X = sm.add_constant(X_factors)
                    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
                    if "const" in model.params and "MKT" in model.params:
                        alpha = model.params["const"]
                        t_stat_alpha = model.tvalues["const"]
                        r_squared = model.rsquared
                        annualised_alpha = alpha * 252 * 100
                        if annualised_alpha > 0 and t_stat_alpha >= 2.0 and r_squared <= 0.35:
                            passed_strategies.append("Clean-Room-Alpha")

    except Exception:
        pass
    return passed_strategies

def run_confluence_audit():
    print("🪐 KRONOS QUANT SYSTEM: CONFLUENCE AUDIT ENGINE")
    print("==========================================================")
    
    # 1. Parse Tickers from Master Fresh Scan report
    fresh_scan_signals = {}
    if os.path.exists(MASTER_FRESH_MD):
        print(f"📖 Parsing active setups from {os.path.basename(MASTER_FRESH_MD)}...")
        try:
            with open(MASTER_FRESH_MD, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("|") and "**" in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3 and not parts[1].startswith("Ticker") and not parts[1].startswith(":---"):
                            ticker = parts[1].replace("**", "").strip()
                            strat = parts[2].replace("`", "").strip()
                            fresh_scan_signals[ticker] = strat
        except Exception as e:
            print(f"   ⚠️ Parsing Error: {e}")
            
    print(f"   ↳ Found {len(fresh_scan_signals)} active setups from Master Fresh report.")
    
    # 2. Parse Tickers from Recent Registry Alerts (last 3 days)
    registry_signals = {}
    if os.path.exists(REGISTRY_CSV):
        print(f"📖 Parsing recent alerts from {os.path.basename(REGISTRY_CSV)}...")
        try:
            df_reg = pd.read_csv(REGISTRY_CSV)
            df_reg['Date'] = pd.to_datetime(df_reg['Date'])
            three_days_ago = datetime.now() - timedelta(days=3)
            recent_alerts = df_reg[df_reg['Date'] > three_days_ago]
            for _, row in recent_alerts.iterrows():
                ticker = str(row['Ticker']).replace(".NS", "").strip()
                source = str(row['Scanner_Source']).strip()
                if ticker not in registry_signals:
                    registry_signals[ticker] = []
                if source not in registry_signals[ticker]:
                    registry_signals[ticker].append(source)
        except Exception as e:
            print(f"   ⚠️ Parsing Error: {e}")
            
    print(f"   ↳ Found {len(registry_signals)} active tickers in the last 3 days alert history.")

    # 3. Load active ticker universe
    if not os.path.exists(TICKERS_CSV):
        print(f"❌ Error: Tickers database not found at {TICKERS_CSV}")
        return
    df_watchlist = pd.read_csv(TICKERS_CSV)
    n500_list = df_watchlist['Symbol'].dropna().unique().tolist()
    
    # 4. Download and Scan Ticker Universe for the 11 Strategies
    print(f"📥 Fetching yfinance batch data for {len(n500_list)} symbols...")
    formatted_tickers = [f"{sym}.NS" for sym in n500_list] + ["^NSEI", "^NSEMDCP50"]
    symbol_map = {f"{sym}.NS": sym for sym in n500_list}
    symbol_map["^NSEI"] = "^NSEI"
    symbol_map["^NSEMDCP50"] = "^NSEMDCP50"
    
    master_data = yf.download(formatted_tickers, period="2y", interval="1d", group_by="ticker", progress=False, auto_adjust=True)
    is_multi = isinstance(master_data.columns, pd.MultiIndex)
    
    # Extract Nifty and Smallcap close series for relative strength and regression checks
    nifty_close = None
    smallcap_close = None
    macro_factors_df = None
    try:
        if is_multi:
            if "^NSEI" in master_data.columns.levels[0]:
                nifty_close = master_data["^NSEI"]["Close"].dropna()
            if "^NSEMDCP50" in master_data.columns.levels[0]:
                smallcap_close = master_data["^NSEMDCP50"]["Close"].dropna()
        else:
            if "Close" in master_data.columns:
                nifty_close = master_data["Close"]

        # Calculate macro factors if both indices are downloaded
        if nifty_close is not None and smallcap_close is not None:
            nifty_ret = nifty_close.pct_change()
            smallcap_ret = smallcap_close.pct_change()
            macro_factors_df = pd.DataFrame(index=nifty_close.index)
            macro_factors_df["MKT"] = nifty_ret
            macro_factors_df["SMB"] = smallcap_ret - nifty_ret
            macro_factors_df.dropna(inplace=True)
    except Exception as e:
        print(f"⚠️ Warning: Could not extract index data / compute factors: {e}")
        
    # 5. Compile Confluences
    confluences = {}
    
    for sym_ns in formatted_tickers:
        if sym_ns in ["^NSEI", "^NSEMDCP50"]:
            continue
        try:
            if is_multi:
                # Use safer matching on column index top-level values
                if sym_ns not in master_data.columns.get_level_values(0):
                    continue
                d_df = master_data[sym_ns].dropna(subset=["Close"])
            else:
                if sym_ns not in master_data.columns:
                    continue
                d_df = master_data[[sym_ns]].dropna(subset=[(sym_ns, "Close")])
                d_df.columns = d_df.columns.get_level_values(1)
                
            if d_df.empty or len(d_df) < 252:
                continue
                
            passed_strats = evaluate_strategies(d_df, nifty_close, macro_factors_df)
            ticker = symbol_map[sym_ns]
            current_close = float(d_df["Close"].squeeze().iloc[-1])
            
            # Aggregate all signal sources
            active_signals = []
            
            # Source A: Master Fresh
            if ticker in fresh_scan_signals:
                active_signals.append(f"Master-Fresh ({fresh_scan_signals[ticker]})")
                
            # Source B: Recent Alert Registry
            if ticker in registry_signals:
                for src in registry_signals[ticker]:
                    active_signals.append(f"Recent-{src}")
                    
            # Source C: Our 7 internal quant strategies
            active_signals.extend(passed_strats)
            
            if len(active_signals) >= 2:
                # Calculate unique domains triggered
                triggered_domains = set()
                for s in active_signals:
                    triggered_domains.add(map_signal_to_domain(s))
                
                confluences[ticker] = {
                    "Price": round(current_close, 2),
                    "Signals": active_signals,
                    "Count": len(active_signals),
                    "Domains": list(triggered_domains),
                    "Domain_Count": len(triggered_domains)
                }
                
        except Exception:
            continue
            
    # 6. Format and Save Report
    target_date = datetime.now().strftime('%Y-%m-%d')
    report_md = f"# 🔥 Cross-Scanner Confluence Report\n"
    report_md += f"- **Generated On:** {target_date}\n"
    report_md += f"- **Threshold:** Stocks triggering 2+ distinct signals simultaneously\n"
    report_md += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if confluences:
        report_md += "## 🏆 High-Conviction Confluence Setups\n"
        report_md += "| Ticker | Price | Unique Domains | Total Signals | Active Domains | Active Signals / Scanners |\n"
        report_md += "| :--- | :---: | :---: | :---: | :--- | :--- |\n"
        
        # Sort confluences by Domain Count (descending) then Total Signals (descending)
        sorted_conf = sorted(confluences.items(), key=lambda x: (x[1]['Domain_Count'], x[1]['Count']), reverse=True)
        for ticker, data in sorted_conf:
            domains_str = ", ".join(data['Domains'])
            signals_str = ", ".join(data['Signals'])
            report_md += f"| **{ticker}** | ₹{data['Price']:.2f} | **{data['Domain_Count']}** | {data['Count']} | {domains_str} | {signals_str} |\n"
            
        # Compile Telegram Alert
        tg_msg = f"🏆 *HIGH-CONVICTION CONFLUENCES ({target_date})*\n"
        tg_msg += "Independent scanners aligned across unique quant domains:\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for ticker, data in sorted_conf[:10]:  # Limit top 10 for TG
            tg_msg += f"🔥 *{ticker}* | Price: ₹{data['Price']:.2f}\n"
            tg_msg += f" ├ Domains: *{data['Domain_Count']}* ({', '.join(data['Domains'])})\n"
            tg_msg += f" └ Signals: _{', '.join(data['Signals'])}_\n\n"
        tg_msg += "━━━━━━━━━━━━━━━━━━━━\n🎯 *Focus:* Multi-domain setups yield the highest win rates."
        send_telegram(tg_msg)
    else:
        report_md += "✅ No cross-scanner confluences detected in the current window.\n"
        print("✅ No confluences found today.")
        
    # Write to Obsidian
    os.makedirs(os.path.dirname(CONFLUENCE_REPORT_MD), exist_ok=True)
    with open(CONFLUENCE_REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"✅ Confluence Analysis Report written: {CONFLUENCE_REPORT_MD}")
    if confluences:
        print("\n--- HIGH-CONVICTION CONFLUENCE REPORT ---")
        for ticker, data in sorted_conf:
            print(f"Ticker: {ticker:<12} Price: ₹{data['Price']:<8} Domains: {data['Domain_Count']} ({data['Domains']}) Signals: {data['Signals']}")

if __name__ == "__main__":
    run_confluence_audit()
