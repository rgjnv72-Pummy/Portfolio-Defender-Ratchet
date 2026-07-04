import http.client
import json
import os
import sys
import warnings
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import requests

# --- WARNING FILTERS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=UserWarning)

# --- UTF-8 CONSOLE ENCODING FIX (Windows Support) ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- AUTO-INSTALL DEPENDENCIES (Fallback) ---
try:
    import pandas_ta as ta
except ImportError:
    print("Installing required quant library pandas-ta... Please wait.")
    os.system(f"{sys.executable} -m pip install pandas-ta-classic==0.3.15 --no-deps --quiet")
    import pandas_ta as ta

# --- CONFIGURATION ---
TOKEN = (os.getenv('TELEGRAM_TOKEN') or '').strip()
CHAT_ID = (os.getenv('TELEGRAM_CHAT_ID') or '').strip()
TICKERS_CSV = 'ind_nifty500list.csv'
MIN_AVG_TRADED_VALUE = 20000000  # ₹2 Crores minimum daily liquidity

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
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

def evaluate_strategies(df, nifty_close=None):
    """
    Evaluates a single stock's historical DataFrame against all 11 strategies.
    Returns: (list_of_passed_strategy_names, trigger_entry_level)
    """
    passed_strategies = []
    entry_trigger = 0.0

    try:
        close = df["Close"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        if len(close) < 200:
            return [], 0.0

        # --- MANDATORY FILTER: MONETARY LIQUIDITY ---
        daily_traded_value = close * volume
        avg_value_20d = daily_traded_value.iloc[-20:].mean()
        if avg_value_20d < MIN_AVG_TRADED_VALUE:
            return [], 0.0

        # Core Indicators
        ema200 = ta.ema(close, length=200)
        atr40 = ta.atr(high=high, low=low, close=close, length=40)

        if ema200 is None or atr40 is None:
            return [], 0.0

        current_close = float(close.iloc[-1])
        current_low = float(low.iloc[-1])
        current_atr = float(atr40.iloc[-1])

        # 1. cont3_liqflow_oscillator (Liquidity Flow Oscillator / Mean Reversion)
        cmf = ta.cmf(high, low, close, volume, length=20)
        rsi = ta.rsi(close, length=14)
        if cmf is not None and rsi is not None:
            if cmf.iloc[-1] > 0.10 and rsi.iloc[-1] < 35:
                passed_strategies.append("cont3_liqflow_oscillator")
                entry_trigger = current_low + (0.8 * current_atr)

        # 2. cont5_relspike_confirmed (Volume Spike + MACD Breakout)
        vol_ma20 = volume.rolling(window=20).mean()
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        if vol_ma20 is not None and macd is not None:
            last_vol = volume.iloc[-1]
            last_vol_ma = vol_ma20.iloc[-1]
            macd_cols = [c for c in macd.columns if "MACD_" in str(c)]
            sig_cols = [c for c in macd.columns if "MACDs_" in str(c)]
            if macd_cols and sig_cols:
                macd_col = macd_cols[0]
                sig_col = sig_cols[0]
                if last_vol > (last_vol_ma * 2.0) and macd[macd_col].iloc[-1] > macd[sig_col].iloc[-1]:
                    passed_strategies.append("cont5_relspike_confirmed")
                    entry_trigger = float(high.iloc[-3:].max())

        # 3. cont2_trendgated_asym (Trend-Gated Pullback)
        if current_close > ema200.iloc[-1]:
            rsi_fast = ta.rsi(close, length=9)
            if rsi_fast is not None and rsi_fast.iloc[-1] < 25:
                passed_strategies.append("cont2_trendgated_asym")
                entry_trigger = float(close.iloc[-2])

        # 4. cont4_pyramid_cascade_rider (ADX Trend Rider)
        adx = ta.adx(high, low, close, length=14)
        if adx is not None:
            adx_cols = [c for c in adx.columns if "ADX_" in str(c)]
            plus_di_cols = [c for c in adx.columns if "DMP_" in str(c)]
            minus_di_cols = [c for c in adx.columns if "DMN_" in str(c)]
            if adx_cols and plus_di_cols and minus_di_cols:
                adx_col = adx_cols[0]
                plus_di = plus_di_cols[0]
                minus_di = minus_di_cols[0]
                if adx[adx_col].iloc[-1] > 25 and adx[plus_di].iloc[-1] > adx[minus_di].iloc[-1]:
                    passed_strategies.append("cont4_pyramid_cascade_rider")
                    entry_trigger = float(high.iloc[-1])

        # 5. cont1_cascade_zscore (Z-Score Mean Reversion with Trend Filter)
        # Modified to filter by EMA200 to avoid structural bear-trend traps
        if current_close > ema200.iloc[-1]:
            ma20 = close.rolling(window=20).mean()
            std20 = close.rolling(window=20).std()
            if not ma20.isna().all() and not std20.isna().all():
                zscore = (current_close - ma20.iloc[-1]) / std20.iloc[-1]
                if zscore < -2.0:
                    passed_strategies.append("cont1_cascade_zscore")
                    entry_trigger = float(ma20.iloc[-1] - (2 * std20.iloc[-1]))

        # 6. stealth_accumulation (Wyckoff Base)
        # Price consolidation baseline (15 days) + Stealth Volume absorption check
        last_15_close = close.iloc[-15:]
        min_15 = last_15_close.min()
        max_15 = last_15_close.max()
        price_range_pct = (max_15 - min_15) / min_15
        
        volume_20 = volume.iloc[-20:]
        avg_vol_20 = volume_20.mean()
        std_vol_20 = volume_20.std()
        
        is_consolidating = price_range_pct < 0.04
        stealth_volume = (volume.iloc[-1] > avg_vol_20) and (volume.iloc[-1] < avg_vol_20 + (1.5 * std_vol_20))
        
        if is_consolidating and stealth_volume:
            passed_strategies.append("stealth_accumulation")
            entry_trigger = float(min_15)

        # 7. catalyst_acceleration (Institutional Volume Launch)
        # 3-day volume ramp + structural volume spike + price still near 15-day base floor
        vol_ramp = (volume.iloc[-1] > volume.iloc[-2]) and (volume.iloc[-2] > volume.iloc[-3])
        vol_spike = volume.iloc[-1] > (avg_vol_20 + (2.5 * std_vol_20))
        price_near_floor = current_close <= min_15 * 1.03
        
        if vol_ramp and vol_spike and price_near_floor:
            passed_strategies.append("catalyst_acceleration")
            entry_trigger = float(high.iloc[-1])

        # 8. rs_line_breakout (Relative Strength Line Breakout vs Nifty 50)
        if nifty_close is not None:
            nifty_reindexed = nifty_close.reindex(df.index).ffill()
            if not nifty_reindexed.isna().all():
                rs_line = df['Close'] / nifty_reindexed
                rs_max_252 = rs_line.rolling(252, min_periods=100).max()
                price_max_252 = df['Close'].rolling(252, min_periods=100).max()
                
                if rs_line.iloc[-1] >= rs_max_252.iloc[-1] and current_close < (price_max_252.iloc[-1] * 0.95):
                    passed_strategies.append("rs_line_breakout")
                    if entry_trigger == 0.0:
                        entry_trigger = float(high.iloc[-1])

        # 9. pocket_pivot (Morales Pocket Pivot Volume Accumulation)
        if len(close) >= 12:
            is_up_day = current_close > float(close.iloc[-2])
            down_days_vol = []
            for i in range(-11, -1):
                if float(close.iloc[i]) < float(close.iloc[i-1]):
                    down_days_vol.append(float(volume.iloc[i]))
            max_down_vol = max(down_days_vol) if down_days_vol else 0.0
            
            if is_up_day and float(volume.iloc[-1]) > max_down_vol and current_close > ema200.iloc[-1]:
                passed_strategies.append("pocket_pivot")
                if entry_trigger == 0.0:
                    entry_trigger = float(high.iloc[-1])

        # 10. vol_compression (Volatility Compression Index / Squeeze)
        if len(close) >= 100:
            returns = close.pct_change()
            hv_10 = returns.tail(10).std()
            hv_100 = returns.tail(100).std()
            if hv_100 > 0:
                vci_ratio = hv_10 / hv_100
                if vci_ratio < 0.15 and current_close > ema200.iloc[-1]:
                    passed_strategies.append("vol_compression")
                    if entry_trigger == 0.0:
                        entry_trigger = float(high.iloc[-1])

        # 11. ema_pullback (EMA Anchor Mean Reversion Pullback)
        ema21 = ta.ema(close, length=21)
        ema50 = ta.ema(close, length=50)
        if ema21 is not None and ema50 is not None:
            in_uptrend = current_close > ema21.iloc[-1] and ema21.iloc[-1] > ema50.iloc[-1] and ema50.iloc[-1] > ema200.iloc[-1]
            touched_ema = float(low.iloc[-1]) <= ema21.iloc[-1] and current_close > ema21.iloc[-1]
            green_candle = current_close > float(df['Open'].iloc[-1])
            
            if in_uptrend and touched_ema and green_candle:
                passed_strategies.append("ema_pullback")
                if entry_trigger == 0.0:
                    entry_trigger = float(high.iloc[-1])

    except Exception:
        pass

    return passed_strategies, round(entry_trigger, 2)

def run_scan():
    print("🚀 Running Multi-Strategy Quant Scanner Engine...")
    
    if not os.path.exists(TICKERS_CSV):
        print(f"❌ Error: {TICKERS_CSV} not found.")
        return
        
    df_csv = pd.read_csv(TICKERS_CSV)
    n500_list = df_csv['Symbol'].dropna().unique().tolist()
    print(f"📊 Processing {len(n500_list)} active tickers from Nifty 500...")
    
    # Format symbols for yfinance batch download (including Nifty index)
    formatted_tickers = [f"{sym}.NS" for sym in n500_list] + ["^NSEI"]
    symbol_map = {f"{sym}.NS": sym for sym in n500_list}
    symbol_map["^NSEI"] = "^NSEI"
    
    CACHE_FILE = 'nifty500_data.pkl'
    if os.path.exists(CACHE_FILE):
        print(f"💾 Loading cached historical market data from '{CACHE_FILE}'...")
        try:
            master_data = pd.read_pickle(CACHE_FILE)
        except Exception as e:
            print(f"❌ Failed to load cache: {e}. Downloading instead.")
            master_data = pd.DataFrame()
    else:
        master_data = pd.DataFrame()
        
    if master_data.empty:
        # Download data in batch (prevents rate throttling) using a custom browser User-Agent session
        print("📥 Downloading historical market data...")
        session = None
        if os.getenv("GITHUB_ACTIONS"):
            session = requests.Session()
            session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
        try:
            master_data = yf.download(formatted_tickers, period="2y", interval="1d", group_by="ticker", progress=False, auto_adjust=True, session=session)
        except Exception as e:
            print(f"❌ Error during batch download: {e}")
            master_data = pd.DataFrame()
    
    results = {
        "cont1_cascade_zscore": [],
        "cont2_trendgated_asym": [],
        "cont3_liqflow_oscillator": [],
        "cont4_pyramid_cascade_rider": [],
        "cont5_relspike_confirmed": [],
        "stealth_accumulation": [],
        "catalyst_acceleration": [],
        "rs_line_breakout": [],
        "pocket_pivot": [],
        "vol_compression": [],
        "ema_pullback": []
    }
    confluences = []
    
    if master_data.empty:
        print("❌ Error: No data downloaded from Yahoo Finance.")
        return
        
    is_multi = isinstance(master_data.columns, pd.MultiIndex)
    
    # Extract Nifty index close series for relative strength checks
    nifty_close = None
    try:
        if is_multi:
            if "^NSEI" in master_data.columns.levels[0]:
                nifty_close = master_data["^NSEI"]["Close"].dropna()
        else:
            if "Close" in master_data.columns:
                nifty_close = master_data["Close"]
    except Exception as e:
        print(f"⚠️ Warning: Could not extract Nifty 50 close: {e}")
    
    for sym_ns in formatted_tickers:
        if sym_ns == "^NSEI":
            continue
        try:
            if is_multi:
                if sym_ns not in master_data.columns.levels[0]:
                    continue
                d_df = master_data[sym_ns].dropna(subset=["Close"])
            else:
                d_df = master_data.dropna(subset=["Close"])
            if d_df.empty or len(d_df) < 200:
                continue
                
            passed_strats, entry_level = evaluate_strategies(d_df, nifty_close)
            if not passed_strats:
                continue
                
            current_close = float(d_df["Close"].squeeze().iloc[-1])
            cl = d_df["Close"].squeeze()
            
            # Project momentum score (drift projected 30 days)
            drift = (((cl.iloc[-1] / cl.iloc[-250]) - 1) / 250 * 0.7) + (
                ((cl.iloc[-1] / cl.iloc[-20]) - 1) / 20 * 0.3
            )
            momentum_upside = drift * 30 * 100
            
            ticker = symbol_map[sym_ns]
            item = {
                "Ticker": ticker,
                "Price": round(current_close, 2),
                "Trigger": entry_level,
                "Momentum_Score": round(momentum_upside, 1)
            }
            
            for strat in passed_strats:
                results[strat].append(item)
                
            if len(passed_strats) >= 2:
                confluences.append({
                    "Ticker": ticker,
                    "Price": round(current_close, 2),
                    "Strategies": passed_strats,
                    "Momentum_Score": round(momentum_upside, 1)
                })
                
        except Exception:
            continue
            
    # Format and dispatch Telegram report
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🪐 *MULTI-STRATEGY QUANT SCANNER ({target_date})*\n"
    msg += f"📊 _Processed Tickers: {len(n500_list)}_\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    strat_short_names = {
        "cont1_cascade_zscore": "Z-Score",
        "cont2_trendgated_asym": "Trend-Pullback",
        "cont3_liqflow_oscillator": "Money-Flow",
        "cont4_pyramid_cascade_rider": "ADX-Rider",
        "cont5_relspike_confirmed": "Vol-Spike",
        "stealth_accumulation": "Stealth-Base",
        "catalyst_acceleration": "Catalyst-Accel",
        "rs_line_breakout": "RS-Breakout",
        "pocket_pivot": "Pocket-Pivot",
        "vol_compression": "Vol-Compression",
        "ema_pullback": "EMA-Pullback"
    }
    
    if confluences:
        msg += "🔥 *CONFLUENCE SETUPS (2+ STRATEGIES)*\n"
        msg += "`Ticker      Price     Strategies`\n"
        sorted_conf = sorted(confluences, key=lambda x: x['Momentum_Score'], reverse=True)
        for row in sorted_conf:
            short_names = [strat_short_names[s] for s in row['Strategies']]
            msg += f"`{row['Ticker']:<11} {row['Price']:<9.1f} {', '.join(short_names)}`\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
    strategy_titles = {
        "cont1_cascade_zscore": "📊 1. Cascade Z-Score (Mean Reversion)",
        "cont2_trendgated_asym": "🟢 2. Trend-Gated Pullback (Buy Dip)",
        "cont3_liqflow_oscillator": "💧 3. Liquidity Flow Oscillator",
        "cont4_pyramid_cascade_rider": "🚀 4. Pyramid Cascade Rider (Trend)",
        "cont5_relspike_confirmed": "🔥 5. Relative Volume Spike Breakout",
        "stealth_accumulation": "📦 6. Stealth Accumulation Base (Wyckoff)",
        "catalyst_acceleration": "⚡ 7. Catalyst Acceleration (Volume Launch)",
        "rs_line_breakout": "🏆 8. RS Line Breakout (Index Outperformance)",
        "pocket_pivot": "💎 9. Institutional Pocket Pivot (Accumulation)",
        "vol_compression": "🤐 10. Volatility Compression Index (Squeeze)",
        "ema_pullback": "🎣 11. EMA Anchor Pullback (Mean Reversion)"
    }
    
    total_signals = 0
    for strat, matches in results.items():
        if not matches:
            continue
            
        total_signals += len(matches)
        msg += f"*{strategy_titles[strat]}*\n"
        msg += "`Ticker      Price     Trigger   M-Score`\n"
        
        # Sort by Momentum Score descending and limit to top 5
        sorted_matches = sorted(matches, key=lambda x: x['Momentum_Score'], reverse=True)[:5]
        for row in sorted_matches:
            msg += f"`{row['Ticker']:<11} {row['Price']:<9.1f} {row['Trigger']:<9.1f} {row['Momentum_Score']:>+5.1f}%`\n"
        msg += "\n"
        
    if total_signals == 0:
        msg += "✅ No actionable strategy setups detected today."
    else:
        msg += "━━━━━━━━━━━━━━━━━━━━\n🎯 *Focus:* Top 5 setups per strategy sorted by momentum score."
        
    send_telegram(msg)
    print("✅ Analysis sent.")

if __name__ == "__main__":
    run_scan()
