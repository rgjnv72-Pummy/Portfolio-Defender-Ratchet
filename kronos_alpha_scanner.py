from beast_standards import check_beast_liquidity_standards
import os
import json
import http.client
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from nselib import capital_market

# --- SYSTEM INITIALIZATION ---
yf.set_tz_cache_location("cache")

# --- ENVIRONMENT & TELEGRAM AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
CSV_NAME = "ind_nifty500list.csv"

def send_msg(text):
    if not MY_TOKEN or not MY_CHAT_ID: 
        print(text)  # Fallback to terminal output if environment tokens are empty
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=15)
        payload = json.dumps({
            "chat_id": str(MY_CHAT_ID).strip(),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN.strip()}/sendMessage", payload, headers)
        conn.getresponse()
        conn.close()
    except: 
        pass

# --- TECHNICAL MATHEMATICAL INDICATORS ---
def get_atr(df, n=14):
    tr = pd.concat([
        df['High'] - df['Low'], 
        abs(df['High'] - df['Close'].shift(1)), 
        abs(df['Low'] - df['Close'].shift(1))
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def get_rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = d.where(d < 0, 0).abs().rolling(n).mean()
    return 100 - (100 / (1 + (g / (l + 1e-9))))

def fetch_delivery_percentage(symbol, days=5):
    """Extracts institutional 5-day delivery percentage from NSE."""
    try:
        raw_df = capital_market.price_volume_and_deliverable_position_data(symbol=symbol, period='1M')
        if raw_df is None or raw_df.empty: 
            return "N/A"
        raw_df.columns = raw_df.columns.str.strip()
        pct_col = [c for c in raw_df.columns if '%' in c or 'ToTradedQty' in c or 'Percentage' in c]
        if not pct_col:
            pct_col = [c for c in raw_df.columns if 'Dly' in c or 'Deliverable' in c]
            if len(pct_col) > 1: 
                pct_col = [pct_col[-1]]
        target_col = pct_col[0]
        raw_df[target_col] = pd.to_numeric(raw_df[target_col], errors='coerce')
        recent_delivery = raw_df[target_col].dropna().tail(days)
        if recent_delivery.empty: 
            return "N/A"
        final_val = round(recent_delivery.mean(), 1)
        return final_val if final_val <= 100.0 else "N/A"
    except:
        return "N/A"

# --- SCANNED CONFLUENCE MATH & RISK ENGINE ---
def scan_confluence_optimized(item, benchmark_close):
    try:
        symbol = str(item['Symbol']).strip()
        sector = str(item['Industry']).strip()
        ticker = f"{symbol}.NS"
        
        df = yf.download(ticker, period="2y", progress=False, auto_adjust=True, timeout=15)
        if df is None or len(df) < 250: 
            return None
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
            
        c = df['Close'].squeeze().astype(float)
        
        # 1. Volatility Scaling Calculations
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        atr20 = get_atr(df, 20)
        
        last_close = float(c.iloc[-1])
        last_atr = float(atr20.iloc[-1])
        volatility_pct = (last_atr / last_close) * 100 
        if volatility_pct == 0: 
            return None

        # 2. Cross-Sectional Alpha Calculation (Vs Nifty 500 Index)
        stock_ret_20d = (last_close / c.iloc[-20]) - 1
        bench_ret_20d = (benchmark_close.iloc[-1] / benchmark_close.iloc[-20]) - 1
        relative_alpha_20d = stock_ret_20d - bench_ret_20d

        # 3. Factor Analysis Scoring Matrix
        score, signals = 0, []
        if (sma20 + (2 * std20)).iloc[-1] < (sma20 + (1.5 * atr20)).iloc[-1]:
            score += 1; signals.append("SQZ")
        bw = (std20 * 4) / (sma20 + 1e-9)
        if bw.iloc[-1] <= bw.tail(21).min():
            score += 1; signals.append("ULT")
        if get_rsi(c).iloc[-1] > 55:
            score += 1; signals.append("RSI")
        if c.ewm(span=8).mean().iloc[-1] > c.ewm(span=21).mean().iloc[-1]:
            score += 1; signals.append("GUP")
        if last_close > (sma20.iloc[-1] + (last_atr * 1.5)):
            score += 1; signals.append("VAM")

        # 4. Volatility-Adjusted Ranking Score
        risk_adjusted_score = round(score / (volatility_pct + 1e-9), 3)

        # 5. Dynamic Swing Risk Management Model
        stop_loss = round(last_close - (1.5 * last_atr), 1)
        target_price = round(last_close + (3.0 * last_atr), 1)  # 1:2 Risk-to-Reward Ratio
        risk_percentage = round(((last_close - stop_loss) / last_close) * 100, 1)

        # Only pass stocks beating the benchmark index with healthy momentum confluence
        if relative_alpha_20d > 0 and score >= 2:
            del_pct = fetch_delivery_percentage(symbol, days=5)
            return {
                's': symbol, 'sc': score, 'alpha': round(relative_alpha_20d * 100, 2), 
                'ras': risk_adjusted_score, 'sig': "+".join(signals), 'sec': sector, 'del': del_pct,
                'price': round(last_close, 1), 'sl': stop_loss, 'target': target_price, 'risk_pct': risk_percentage
            }
    except: 
        return None

# --- SCANNER RUN EXECUTION CONTROLLER ---
def run_master():
    send_msg("🛰 *KRONOS TRADING AUTOMATION:* Initializing separate Nifty 500 Alpha Breakout Engine...")
    try:
        df_csv = pd.read_csv(CSV_NAME)
        df_csv.columns = df_csv.columns.str.strip()
        s_col = [c for c in df_csv.columns if 'Symbol' in c or 'Ticker' in c][0]
        i_col = [c for c in df_csv.columns if 'Industry' in c or 'Sector' in c or 'Category' in c][0]
        tickers_df = df_csv[[s_col, i_col]].rename(columns={s_col: 'Symbol', i_col: 'Industry'})
        items_list = tickers_df.to_dict(orient='records')
    except Exception as e:
        send_msg(f"⚠️ *KRONOS ERROR:* Could not read '{CSV_NAME}'. Ensure it is in the root directory.")
        return

    try:
        # Download Nifty 500 index structure tracking parameters (^CRSLDX)
        benchmark_df = yf.download("^CRSLDX", period="2y", progress=False, auto_adjust=True, timeout=20)
        if isinstance(benchmark_df.columns, pd.MultiIndex):
            benchmark_df.columns = benchmark_df.columns.get_level_values(0)
        benchmark_close = benchmark_df['Close'].squeeze().astype(float)
    except Exception as e:
        send_msg(f"⚠️ *KRONOS ERROR:* Broad market index connection failed: {e}")
        return

    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(scan_confluence_optimized, item, benchmark_close) for item in items_list]
        for future in futures:
            res = future.result()
            if res: 
                results.append(res)

    if not results:
        send_msg("📡 *KRONOS:* Scan completed. No outperforming configurations matching filters.")
        return

    # Sort results by Risk-Adjusted Score first, and then by raw index outperformance
    final_df = pd.DataFrame(results).sort_values(['ras', 'alpha'], ascending=[False, False])
    
    report = f"🏆 *KRONOS AUTOMATED SWING ALPHAS: {datetime.now().strftime('%d %b')}*\n"
    report += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    report += "🔥 *TOP SECTORS BY INSTFLOW*\n"
    sec_data = final_df['sec'].value_counts(normalize=True).head(3) * 100
    for sec, val in sec_data.items():
        report += f"• {sec}: {val:.1f}%\n"
    report += "\n"

    for _, r in final_df.head(15).iterrows():
        icon = "💎" if r['sc'] >= 4 else "🔥"
        del_alert = f"🚀 Del: {r['del']}%" if isinstance(r['del'], (int, float)) and r['del'] >= 50.0 else f"📦 Del: {r['del']}%" if isinstance(r['del'], (int, float)) else f"Del: {r['del']}"
        
        report += f"{icon} `{r['s']}` (Score: {r['sc']} | RAS: {r['ras']})\n"
        report += f" ├ 📈 Alpha vs Index: +{r['alpha']}%\n"
        report += f" ├ 🎯 Entry Close: ₹{r['price']} | *SL: ₹{r['sl']}* (-{r['risk_pct']}%)\n"
        report += f" └ 🚀 *Target: ₹{r['target']}* | {r['sig']} | {del_alert}\n\n"

    tv_list = ",".join([f"NSE:{s}" for s in final_df['s'].head(25)])
    report += f"📺 *WATCHLIST STRING FOR TRADINGVIEW*\n`{tv_list}`"
    send_msg(report)

if __name__ == "__main__":
    run_master()
