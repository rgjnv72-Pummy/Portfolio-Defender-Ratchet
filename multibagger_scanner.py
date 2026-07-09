import os
import sys
import json
import http.client
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# --- UTF-8 CONSOLE ENCODING FIX ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
TOKEN = (os.getenv('TELEGRAM_TOKEN') or '').strip()
CHAT_ID = (os.getenv('TELEGRAM_CHAT_ID') or '').strip()
TICKERS_CSV = 'ind_nifty500list.csv'
CACHE_FILE = 'nifty500_data.pkl'

def get_row_safely(df, potential_keys):
    """Dynamic index matcher to avoid KeyErrors from yfinance format drift."""
    if df is None or df.empty:
        return None
    normalized_index = [str(x).strip().lower().replace(" ", "").replace("_", "") for x in df.index]
    for key in potential_keys:
        target = key.strip().lower().replace(" ", "").replace("_", "")
        # Try exact match
        if target in normalized_index:
            idx = normalized_index.index(target)
            return df.iloc[idx]
        # Try substring match
        for i, idx_val in enumerate(normalized_index):
            if target in idx_val:
                return df.iloc[i]
    return None

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
        conn.getcall = conn.getcall = conn.getresponse()
        print("✅ Telegram notification dispatched successfully.")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
    finally:
        conn.close()

def main():
    print("🚀 Initializing Production Multi-Bagger Scanner...")
    
    # 1. Load Tickers
    if not os.path.exists(TICKERS_CSV):
        print(f"❌ Target watchlist {TICKERS_CSV} not found.")
        return
    df_csv = pd.read_csv(TICKERS_CSV)
    raw_tickers = df_csv['Symbol'].dropna().unique().tolist()
    formatted_tickers = [f"{t}.NS" for t in raw_tickers]
    
    # 2. Stage 1: Batch technical filtering (Instant)
    master_data = pd.DataFrame()
    if os.path.exists(CACHE_FILE):
        print(f"💾 Loading cached data from '{CACHE_FILE}'...")
        try:
            master_data = pd.read_pickle(CACHE_FILE)
        except Exception as e:
            print(f"⚠️ Failed to load cache: {e}. Downloading fresh.")

    if master_data.empty:
        print("📥 Downloading batch historical prices...")
        master_data = yf.download(formatted_tickers, period="1y", interval="1d", group_by="ticker", progress=False)

    if master_data.empty:
        print("❌ No historical market data available.")
        return

    is_multi = isinstance(master_data.columns, pd.MultiIndex)
    passed_stage1 = []

    print("📊 Stage 1: Filtering stocks on technical regime (Price Range < 35% & 6M Momentum < 0)...")
    for ticker in formatted_tickers:
        try:
            if is_multi:
                if ticker not in master_data.columns.levels[0]:
                    continue
                hist = master_data[ticker].dropna(subset=["Close"])
            else:
                continue
                
            if len(hist) < 252:
                continue
                
            current_price = hist["Close"].iloc[-1]
            one_year_high = hist["Close"].max()
            one_year_low = hist["Close"].min()
            
            # 12-Month Price Range position
            denom = (one_year_high - one_year_low)
            price_range_pct = ((current_price - one_year_low) / denom * 100) if denom > 0 else 100.0
            
            # 6-Month Momentum Trend
            six_months_ago_price = hist["Close"].iloc[-126]
            six_month_momentum = ((current_price - six_months_ago_price) / six_months_ago_price) if six_months_ago_price > 0 else 0.0
            
            # TECHNICAL GATES
            if price_range_pct < 35.0 and six_month_momentum < 0:
                passed_stage1.append({
                    "ticker": ticker,
                    "price": current_price,
                    "price_range_pct": price_range_pct,
                    "6m_momentum": six_month_momentum
                })
        except:
            continue

    print(f"🎯 Stage 1 complete. {len(passed_stage1)} of {len(formatted_tickers)} stocks passed technical screening.")
    if not passed_stage1:
        print("✅ Analysis Complete: Zero stocks met Stage 1 criteria.")
        return

    # 3. Stage 2: Deep Fundamental Extraction (Only for passed candidates)
    results = []
    print("🔬 Stage 2: Fetching deep fundamentals (ROA, Book-to-Market, FCF Yield, Investment Penalty)...")
    for item in passed_stage1:
        ticker = item["ticker"]
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            market_cap = info.get("marketCap")
            if not market_cap or market_cap <= 0:
                continue
                
            total_enterprise_value = info.get("enterpriseValue") or market_cap
            
            # Fetch financials
            financials = stock.financials
            balance_sheet = stock.balance_sheet
            cashflow = stock.cashflow
            
            if financials.empty or balance_sheet.empty or cashflow.empty:
                continue

            # Free Cash Flow Yield
            fcf_row = get_row_safely(cashflow, ["free cash flow"])
            if fcf_row is None:
                continue
            fcf_yield = fcf_row.iloc[0] / market_cap

            # Profitability (ROA)
            net_income_row = get_row_safely(financials, ["net income"])
            assets_row = get_row_safely(balance_sheet, ["total assets"])
            if net_income_row is None or assets_row is None or len(assets_row) < 2:
                continue
            roa = net_income_row.iloc[0] / assets_row.iloc[0]

            # Book-to-Market
            equity_row = get_row_safely(balance_sheet, ["stockholders equity", "total equity", "common stock equity"])
            if equity_row is None:
                continue
            book_to_market = equity_row.iloc[0] / market_cap

            # Investment Regularization (Asset Growth vs EBITDA Growth)
            asset_growth = (assets_row.iloc[0] - assets_row.iloc[1]) / assets_row.iloc[1]
            
            ebitda_row = get_row_safely(financials, ["ebitda"])
            if ebitda_row is not None and len(ebitda_row) >= 2 and ebitda_row.iloc[1] != 0:
                ebitda_growth = (ebitda_row.iloc[0] - ebitda_row.iloc[1]) / abs(ebitda_row.iloc[1])
            else:
                ebitda_growth = 0.0

            # Inv Dummy Penalty: Penalty if Asset growth outpaces EBITDA growth
            inv_dummy = 1 if asset_growth > ebitda_growth else 0

            # FUNDAMENTAL GATES (FCF Yield > 5% & B/M Ratio > 0.4 & Penalty == 0)
            if fcf_yield > 0.05 and book_to_market > 0.4 and inv_dummy == 0:
                results.append({
                    "Ticker": ticker.replace(".NS", ""),
                    "Price": round(item["price"], 2),
                    "TEV_Billion": round(total_enterprise_value / 1e9, 2),
                    "FCF_Yield": round(fcf_yield * 100, 2),
                    "B_M_Ratio": round(book_to_market, 2),
                    "ROA": round(roa * 100, 2),
                    "Price_Range_Pct": round(item["price_range_pct"], 2),
                    "6M_Momentum": round(item["6m_momentum"] * 100, 2),
                })
        except:
            continue

    # 4. Compile & Sort
    df_results = pd.DataFrame(results)
    if df_results.empty:
        msg = "🏆 *QUANT MULTI-BAGGER REPORT*\n\n✅ Zero stocks passed all fundamental screening rules this week."
        send_telegram(msg)
        return

    df_results = df_results.sort_values(by="FCF_Yield", ascending=False).reset_index(drop=True)
    
    # 5. Format & Dispatch Telegram
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🏆 *QUANT MULTI-BAGGER REPORT ({target_date})*\n"
    msg += "_FCF Yield & Value Anomaly | Under-priced Turnarounds_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += "`Ticker      Price      FCF-Yld   B/M    ROA`\n"
    for _, r in df_results.iterrows():
        msg += f"`{r['Ticker']:<11} ₹{r['Price']:<9.1f} {r['FCF_Yield']:<7.1f}% {r['B_M_Ratio']:<6.1f} {r['ROA']:>4.1f}%`\n"
    msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 *Core Methodology:*\n"
    msg += "• *Rule A*: Free Cash Flow Yield > 5% & Book-to-Market > 0.4\n"
    msg += "• *Rule B*: Assets grew slower than EBITDA (No capital bloating)\n"
    msg += "• *Rule C*: Trading in the bottom 35% of its 1Y range with negative 6M momentum."
    
    send_telegram(msg)
    print("✅ Multi-bagger scanner execution complete.")

if __name__ == "__main__":
    main()
