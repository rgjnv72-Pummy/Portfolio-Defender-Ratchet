from beast_standards import check_beast_liquidity_standards
import os
import sys
import json
import warnings
import http.client
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime
import yfinance as yf

# Configure UTF-8 for Windows Console Output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# --- WARNING FILTERS ---
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# --- DYNAMIC CONFIGURATION FOR LOCAL VS GITHUB RUN ---
script_dir = os.path.dirname(os.path.abspath(__file__))
if "Trading-Engine" in script_dir:
    BASE_DIR = r"C:\Users\rgjnv\Trading-Engine"
    CSV_PATH = os.path.join(BASE_DIR, "Ratchet-System", "ind_nifty500list.csv")
    CACHE_DIR = os.path.join(BASE_DIR, "backtest_cache")
    REPORT_PATH = os.path.join(BASE_DIR, "Obsidian-Journal", "Ticker-Research", "Master-Fresh-Trades-Scan.md")
else:
    BASE_DIR = script_dir
    CSV_PATH = os.path.join(BASE_DIR, "ind_nifty500list.csv")
    CACHE_DIR = os.path.join(BASE_DIR, "backtest_cache")
    REPORT_PATH = os.path.join(BASE_DIR, "Master-Fresh-Trades-Scan.md")

# --- ENVIRONMENT & TELEGRAM AUTH ---
def load_env_file():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_paths = [
        os.path.join(script_dir, ".env"),
        os.path.join(os.path.dirname(script_dir), ".env")
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
            except Exception as e:
                pass

load_env_file()
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()

def send_telegram(text):
    if not TOKEN or not CHAT_ID or "YOUR" in TOKEN:
        try:
            print(f"[CONSOLE LOG] {text}")
        except UnicodeEncodeError:
            try:
                print(f"[CONSOLE LOG] {text.encode('ascii', errors='replace').decode('ascii')}")
            except:
                print("[CONSOLE LOG] (Message containing emojis could not be printed due to console encoding limits)")
        return
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
    except Exception as e:
        try:
            print(f"❌ Telegram Error: {e}")
        except UnicodeEncodeError:
            print("Telegram Error (Console print encoding failure)")
    finally:
        conn.close()

def get_macro_regime():
    """
    Fetches Nifty 50 (^NSEI) data to determine the Macro Market Regime ("Go/No-Go" Rule).
    """
    try:
        nifty = yf.download('^NSEI', period='1y', progress=False, auto_adjust=True)
        if isinstance(nifty.columns, pd.MultiIndex):
            nifty.columns = nifty.columns.get_level_values(0)
            
        close = nifty['Close'].dropna()
        if len(close) < 200:
            return {
                "close": 0, "ema50": 0, "ema200": 0,
                "regime": "UNKNOWN (INSUFFICIENT DATA)",
                "sizing_multiplier": 1.0, "status_code": "GO", "emoji": "⚪"
            }
            
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        
        last_close = float(close.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])
        last_ema200 = float(ema200.iloc[-1])
        
        if last_close > last_ema50 and last_ema50 > last_ema200:
            regime = "BULLISH / STRONG TREND (GO)"
            size_mult = 1.0
            status_code = "GO"
            emoji = "🟢"
        elif last_close > last_ema200:
            regime = "CAUTIOUS / SIDEWAYS (SCALE SIZING 50%)"
            size_mult = 0.5
            status_code = "CAUTION"
            emoji = "🟡"
        else:
            regime = "BEARISH / CHOPPY REGIME (NO-GO / PAUSE NEW ENTRIES)"
            size_mult = 0.0
            status_code = "NO-GO"
            emoji = "🔴"
            
        return {
            "close": round(last_close, 2),
            "ema50": round(last_ema50, 2),
            "ema200": round(last_ema200, 2),
            "regime": regime,
            "sizing_multiplier": size_mult,
            "status_code": status_code,
            "emoji": emoji
        }
    except Exception as e:
        print(f"[WARNING] Could not fetch Nifty Macro Regime: {e}")
        return {
            "close": 0, "ema50": 0, "ema200": 0,
            "regime": "UNKNOWN (FETCH ERROR)",
            "sizing_multiplier": 1.0, "status_code": "GO", "emoji": "⚪"
        }

MIN_AVG_VOLUME = 100000
EMA_TREND_PERIOD = 200

def load_watchlist():
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] Nifty 500 CSV not found at {CSV_PATH}")
        return {}
        
    df_watchlist = pd.read_csv(CSV_PATH)
    sym_col = next((c for c in df_watchlist.columns if "symbol" in c.lower() or "ticker" in c.lower()), df_watchlist.columns[0])
    sec_col = next((c for c in df_watchlist.columns if "sector" in c.lower() or "industry" in c.lower()), None)
    
    mapping = {}
    for _, row in df_watchlist.iterrows():
        ticker = str(row[sym_col]).strip().replace(",", "")
        if not ticker or "NAN" in ticker.upper() or "SYMBOL" in ticker.upper():
            continue
        sector = str(row[sec_col]).strip() if sec_col else "General"
        mapping[ticker] = sector
    return mapping

def check_smc_fvg_signal(df):
    is_passed, beast_metrics = check_beast_liquidity_standards(df)
    if not is_passed:
        return None
    n = len(df)
    if n < 30:
        return None
        
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    open_p = df['Open'].values
    
    # Trend and Volume check
    if close[-1] < df['EMA_200'].values[-1] or df['Vol_Avg_20'].values[-1] < MIN_AVG_VOLUME:
        return None
        
    for offset in range(5):
        i = n - 1 - offset
        if i < 15:
            continue
            
        c1_high, c1_low = high[i-2], low[i-2]
        c2_open, c2_close = open_p[i-1], close[i-1]
        c3_low = low[i]
        
        is_fvg = c3_low > c1_high
        is_disp = c2_close > c2_open
        
        highest_prior_high = np.max(high[i-7:i-2])
        has_mss = (c2_close > highest_prior_high) or (close[i] > highest_prior_high)
        
        if is_fvg and is_disp and has_mss:
            fvg_top = c3_low
            fvg_bottom = c1_high
            
            post_fvg_closes = close[i+1:]
            if len(post_fvg_closes) > 0 and (post_fvg_closes < fvg_bottom).any():
                continue
                
            if close[-1] >= fvg_bottom:
                stop_loss = c1_low - 0.05
                risk_pct = ((close[-1] - stop_loss) / close[-1]) * 100
                
                return {
                    "Strategy": "SMC FVG",
                    "Grade": f"A [{offset}d Ago]",
                    "Price": round(close[-1], 2),
                    "Entry_Trigger": round(fvg_top, 2),
                    "Stop_Loss": round(stop_loss, 2),
                    "Risk%": round(risk_pct, 2),
                    "Details": f"FVG Gap: ₹{round(fvg_bottom, 2)} - ₹{round(fvg_top, 2)}"
                }
    return None

def check_vcp_signal(df):
    n = len(df)
    if n < 50:
        return None
        
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    volume = df['Volume'].values
    
    sma20 = df['Close'].rolling(20).mean().values[-1]
    vol_sma50 = df['Volume'].rolling(50).mean().values[-1]
    
    if close[-1] < sma20 or df['Vol_Avg_20'].values[-1] < MIN_AVG_VOLUME:
        return None
        
    range_pct = (df['High'] - df['Low']) / df['Low']
    
    pivot_high = np.max(high[-4:])
    pivot_low = np.min(low[-4:])
    total_compression = (pivot_high - pivot_low) / pivot_low
    avg_candle_tightness = np.mean(range_pct.values[-4:])
    volume_dryness = np.mean(volume[-4:]) / vol_sma50
    
    fifty_two_week_high = np.max(high[-252:])
    
    is_compressed = total_compression < 0.048 and avg_candle_tightness < 0.025
    is_volume_dried = volume_dryness < 0.85
    is_near_high = close[-1] / fifty_two_week_high >= 0.92
    
    if is_compressed and is_volume_dried and is_near_high:
        entry = round(pivot_high + 0.05, 2)
        stop = round(pivot_low - 0.05, 2)
        risk_pct = ((entry - stop) / entry) * 100
        
        return {
            "Strategy": "Minervini VCP",
            "Grade": "Element 4 Tight",
            "Price": round(close[-1], 2),
            "Entry_Trigger": entry,
            "Stop_Loss": stop,
            "Risk%": round(risk_pct, 2),
            "Details": f"Compression: {total_compression*100:.1f}% | Vol Dryness: {volume_dryness*100:.0f}%"
        }
    return None

def scan_fresh_opportunities():
    macro_info = get_macro_regime()
    watchlist = load_watchlist()
    if not watchlist:
        return
        
    print(f"\n[INFO] Macro Market Regime: {macro_info['emoji']} {macro_info['regime']}")
    print(f"       Nifty 50: {macro_info['close']} | 50 EMA: {macro_info['ema50']} | 200 EMA: {macro_info['ema200']}")
    print(f"       Position Sizing Multiplier: {macro_info['sizing_multiplier'] * 100:.0f}%\n")
    print(f"[INFO] Scanning {len(watchlist)} stocks...")
    results = []
    
    for ticker, sector in tqdm(watchlist.items(), desc="Master Scan"):
        df = None
        file_path = os.path.join(CACHE_DIR, f"{ticker}.csv")
        
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, parse_dates=["Date"])
                df.set_index("Date", inplace=True)
            except:
                df = None
                
        # Real-time yfinance downloader fallback (critical for running on GitHub or missing tickers)
        if df is None:
            try:
                ticker_ns = f"{ticker}.NS" if not ticker.endswith(".NS") else ticker
                df = yf.download(ticker_ns, period="2y", progress=False, auto_adjust=True, timeout=10)
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
            except:
                df = None
                
        if df is None or len(df) < EMA_TREND_PERIOD + 10:
            continue
            
        try:
            df['EMA_200'] = df['Close'].ewm(span=EMA_TREND_PERIOD, adjust=False).mean()
            df['Vol_Avg_20'] = df['Volume'].rolling(20).mean()
            
            fvg_res = check_smc_fvg_signal(df)
            if fvg_res:
                fvg_res["Ticker"] = ticker
                fvg_res["Sector"] = sector
                results.append(fvg_res)
                continue
                
            vcp_res = check_vcp_signal(df)
            if vcp_res:
                vcp_res["Ticker"] = ticker
                vcp_res["Sector"] = sector
                results.append(vcp_res)
        except Exception:
            pass
            
    if not results:
        print("[INFO] Scan complete. No fresh trade candidates found matching setup criteria.")
        return
        
    df_res = pd.DataFrame(results)
    df_res = df_res.sort_values(by="Risk%")
    
    print("\n" + "="*85)
    print("   KRONOS QUANT SYSTEM: FRESH ACTIONABLE WATCHLIST DEPLOYMENT")
    print(f"   MACRO REGIME: {macro_info['emoji']} {macro_info['regime']} (SIZING: {macro_info['sizing_multiplier']*100:.0f}%)")
    print("="*85)
    print(f"{'Ticker':<12} {'Strategy':<14} {'Grade':<15} {'Price':<8} {'Entry':<8} {'Stop Loss':<9} {'Risk%':<6}")
    print("-"*85)
    
    for _, row in df_res.iterrows():
        print(f"{row['Ticker']:<12} {row['Strategy']:<14} {row['Grade']:<15} {row['Price']:<8.2f} {row['Entry_Trigger']:<8.2f} {row['Stop_Loss']:<9.2f} {row['Risk%']:>5.1f}%")
    print("="*85)
    
    generate_obsidian_report(df_res, macro_info)
    send_telegram_report(df_res, macro_info)

def generate_obsidian_report(df_res, macro_info):
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    target_date = datetime.now().strftime('%Y-%m-%d')
    
    fvg_df = df_res[df_res['Strategy'] == 'SMC FVG']
    vcp_df = df_res[df_res['Strategy'] == 'Minervini VCP']
    
    report = f"""# 📡 Master Fresh Trades Deployment Report
- **Scan Date:** {target_date}
- **Watchlist Source:** NSE 500 Watchlist
- **Strategies Active:** SMC FVG (Pullbacks) & Minervini VCP (Breakouts)
- **Macro Market Regime:** {macro_info['emoji']} **{macro_info['regime']}**
- **Nifty 50 Benchmark:** Price ₹{macro_info['close']} | 50 EMA: ₹{macro_info['ema50']} | 200 EMA: ₹{macro_info['ema200']}
- **Sizing Multiplier:** **{macro_info['sizing_multiplier']*100:.0f}%** (Recommended Position Sizing)

---

## 🌐 Macro Market Regime Filter ("Go/No-Go" Status)
> {macro_info['emoji']} **System Regime:** `{macro_info['regime']}`  
> **Position Sizing Multiplier:** `{macro_info['sizing_multiplier']*100:.0f}%`  
> *Guidance: {"Full deployment permitted." if macro_info['status_code'] == "GO" else ("Scale cash allocation per trade to 50% due to sideways/choppy market conditions." if macro_info['status_code'] == "CAUTION" else "PAUSE NEW ENTRIES. Market is in a high-risk bearish/choppy regime.")}*

---

## 🏆 Combined Fresh Candidates Dashboard
Sorted by **Lowest Risk %** (Entry-to-Stop cushion). Prioritize setups with Risk < 8% for optimal sizing.

| Ticker | Strategy | Setup Grade | Current Price | Entry Trigger | Stop Loss | Risk Cushion | Sector / Industry |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
"""
    for _, row in df_res.iterrows():
        report += f"| **{row['Ticker']}** | `{row['Strategy']}` | {row['Grade']} | ₹{row['Price']:.2f} | **₹{row['Entry_Trigger']:.2f}** | **₹{row['Stop_Loss']:.2f}** | **{row['Risk%']:.1f}%** | {row['Sector']} |\n"

    report += "\n---\n\n## 🔍 Active Setup Explanations & Details\n"
    
    if not fvg_df.empty:
        report += "\n### 🟢 Smart Money Concept (SMC) FVG Pullbacks\n"
        report += "*These stocks exhibit strong institutional displacement. Buy when the price pullbacks into the Fair Value Gap zone, keeping the stop below the swing low.*\n\n"
        for _, row in fvg_df.iterrows():
            report += f"- **{row['Ticker']}** ({row['Sector']}): Current Price **₹{row['Price']:.2f}** | Entry Trigger **₹{row['Entry_Trigger']:.2f}** | Stop Loss **₹{row['Stop_Loss']:.2f}** ({row['Risk%']:.1f}% Risk)\n"
            report += f"  ↳ _Setup Profile:_ {row['Details']}\n\n"
            
    if not vcp_df.empty:
        report += "\n### 🔵 Minervini Volatility Contraction Pattern (VCP)\n"
        report += "*These stocks are tightly consolidating near 52-week highs with volume drying up. Buy on a breakout above the pivot high.*\n\n"
        for _, row in vcp_df.iterrows():
            report += f"- **{row['Ticker']}** ({row['Sector']}): Current Price **₹{row['Price']:.2f}** | Entry Trigger **₹{row['Entry_Trigger']:.2f}** | Stop Loss **₹{row['Stop_Loss']:.2f}** ({row['Risk%']:.1f}% Risk)\n"
            report += f"  ↳ _Setup Profile:_ {row['Details']}\n\n"
            
    report += f"""
---

## 🛠️ Capital Allocation & Sizing Guidelines
1. **Macro Regime Multiplier**: Apply **{macro_info['sizing_multiplier']*100:.0f}%** to standard sizing. Base allocation = `(Total Portfolio Value * 10%) * {macro_info['sizing_multiplier']}`.
2. **Fractional Sizing**: If your available cash is less than the calculated allocation, sweep the remaining cash into the trade (as long as it exceeds ₹10,000) to avoid missing signals.
3. **Execution**: Place a Buy Stop Limit order at the **Entry Trigger** price. Ensure stop losses are hard-coded in your execution journal.
"""
    
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
        
    print(f"[SUCCESS] Obsidian deployment report saved to: {REPORT_PATH}")

def send_telegram_report(df_res, macro_info):
    top_20 = df_res.head(20)
    
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"📡 *KRONOS FRESH ALERTS REPORT ({target_date})*\n"
    msg += f"Regime: {macro_info['emoji']} *{macro_info['regime']}*\n"
    msg += f"Sizing Multiplier: *{macro_info['sizing_multiplier']*100:.0f}%*\n\n"
    
    watchlist_tickers = []
    for _, r in top_20.iterrows():
        ticker_clean = str(r['Ticker']).replace('.NS', '').strip()
        watchlist_tickers.append(f"NSE:{ticker_clean}")
        msg += f"• `{ticker_clean}` ({r['Sector']}): *₹{r['Price']:.2f}* | `{r['Strategy']}`\n"
        msg += f"  ↳ Trigger: *₹{r['Entry_Trigger']:.2f}* | SL: *₹{r['Stop_Loss']:.2f}* | Risk: *{r['Risk%']:.1f}%*\n\n"
        
    if watchlist_tickers:
        tv_list = ",".join(watchlist_tickers)
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📺 *TRADINGVIEW WATCHLIST*\n`{tv_list}`"
        send_telegram(msg)
        print("Telegram notification sent successfully!")

if __name__ == "__main__":
    scan_fresh_opportunities()

