import os
import sys
import json
import http.client
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import requests

# --- UTF-8 CONSOLE ENCODING FIX ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURATION ---
TOKEN = (os.getenv('TELEGRAM_TOKEN') or '').strip()
CHAT_ID = (os.getenv('TELEGRAM_CHAT_ID') or '').strip()
TICKERS_CSV = 'ind_nifty500list.csv'
CACHE_FILE = 'nifty500_data.pkl'

SECTOR_MAP = {
    "BANK": "^NSEBANK",
    "IT": "^CNXIT",
    "AUTO": "^CNXAUTO",
    "METAL": "^CNXMETAL",
    "REALTY": "^CNXREALTY",
    "FMCG": "^CNXFMCG",
    "PHARMA": "^CNXPHARMA",
    "PSU-BANK": "^CNXPSUBANK",
    "INFRA": "^CNXINFRA",
    "ENERGY": "^CNXENERGY",
    "MEDIA": "^CNXMEDIA",
    "FINANCE": "^NSEBANK"  # Fallback to Bank Nifty
}

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

def normalize_nse_industry(raw_industry_str):
    raw = str(raw_industry_str).upper().strip()
    if "BANK" in raw: return "BANK"
    if "FINAN" in raw or "INSUR" in raw: return "FINANCE"
    if "IT " in raw or "TECHNOLOGY" in raw or "SOFTWARE" in raw: return "IT"
    if "HEALTH" in raw or "PHARMA" in raw or "BIOTECH" in raw: return "PHARMA"
    if "AUTO" in raw or "VEHICLE" in raw: return "AUTO"
    if "METALS" in raw or "MINING" in raw or "STEEL" in raw: return "METAL"
    if "REALTY" in raw or "REAL ESTATE" in raw: return "REALTY"
    if "FMCG" in raw or "CONSUMER GOODS" in raw or "FOOD" in raw or "BEVERAGE" in raw: return "FMCG"
    if "CONSTRUCT" in raw or "INFRA" in raw: return "INFRA"
    if "POWER" in raw or "ENERGY" in raw or "OIL" in raw or "GAS" in raw or "FUEL" in raw: return "ENERGY"
    if "MEDIA" in raw or "ENTERTAIN" in raw: return "MEDIA"
    return "UNKNOWN"

def main():
    print("🚀 Starting Sectoral Leader & Rotation Scanner...")
    
    if not os.path.exists(TICKERS_CSV):
        print(f"❌ Watchlist {TICKERS_CSV} not found.")
        return
        
    df_csv = pd.read_csv(TICKERS_CSV)
    
    # 1. Map stocks to sectors
    stock_to_sector = {}
    sector_to_stocks = {}
    for _, row in df_csv.iterrows():
        sym = row['Symbol']
        raw_ind = row.get('Industry', 'UNKNOWN')
        sector = normalize_nse_industry(raw_ind)
        if sector == "UNKNOWN":
            continue
        ticker = f"{sym}.NS"
        stock_to_sector[ticker] = sector
        if sector not in sector_to_stocks:
            sector_to_stocks[sector] = []
        sector_to_stocks[sector].append(ticker)
        
    # 2. Download Sectoral Indices and Benchmark (Nifty 50)
    index_tickers = list(set(SECTOR_MAP.values())) + ["^NSEI"]
    print("📥 Downloading index historical data (3 months)...")
    try:
        indices_data = yf.download(index_tickers, period="3mo", interval="1d", group_by="ticker", progress=False)
    except Exception as e:
        print(f"❌ Failed to download index data: {e}")
        return
        
    if indices_data.empty:
        print("❌ Failed to download index data from Yahoo Finance.")
        return
        
    # Calculate returns for Nifty 50 (^NSEI)
    nifty_df = indices_data["^NSEI"].dropna(subset=["Close"])
    if len(nifty_df) < 5:
        print("❌ Insufficient data for Nifty 50.")
        return
    nifty_1w_ret = (nifty_df["Close"].iloc[-1] / nifty_df["Close"].iloc[-5]) - 1
    nifty_3m_ret = (nifty_df["Close"].iloc[-1] / nifty_df["Close"].iloc[0]) - 1
    
    # Calculate returns for Sectoral Indices
    sector_index_perf = {}
    for sector, index_ticker in SECTOR_MAP.items():
        try:
            idx_df = indices_data[index_ticker].dropna(subset=["Close"])
            if len(idx_df) < 5:
                continue
            idx_1w_ret = (idx_df["Close"].iloc[-1] / idx_df["Close"].iloc[-5]) - 1
            idx_3m_ret = (idx_df["Close"].iloc[-1] / idx_df["Close"].iloc[0]) - 1
            
            sector_index_perf[sector] = {
                "ticker": index_ticker,
                "1w_return": idx_1w_ret,
                "3m_return": idx_3m_ret,
                "1w_outperf": idx_1w_ret - nifty_1w_ret
            }
        except:
            continue
            
    # Identify outperforming sectors (1-week outperformance > 0)
    outperforming_sectors = {sec: info for sec, info in sector_index_perf.items() if info["1w_outperf"] > 0}
    
    # Sort outperforming sectors by 1-week return descending
    sorted_sectors = sorted(outperforming_sectors.items(), key=lambda x: x[1]["1w_return"], reverse=True)
    
    # 3. Load Stock Data
    master_data = pd.DataFrame()
    if os.path.exists(CACHE_FILE):
        print(f"💾 Loading cached stock data from '{CACHE_FILE}'...")
        try:
            master_data = pd.read_pickle(CACHE_FILE)
        except Exception as e:
            print(f"⚠️ Failed to load cache: {e}. Downloading fresh.")
            
    if master_data.empty:
        # If cache doesn't exist, download 500 stocks
        tickers_list = list(stock_to_sector.keys()) + ["^NSEI"]
        print("📥 Cache empty. Downloading all stocks in batch...")
        master_data = yf.download(tickers_list, period="3mo", interval="1d", group_by="ticker", progress=False)
        
    if master_data.empty:
        print("❌ No stock data available.")
        return
        
    is_multi = isinstance(master_data.columns, pd.MultiIndex)
    
    report_data = []
    
    # 4. Analyze stocks within each outperforming sector
    for sector, sec_info in sorted_sectors:
        sec_ticker = sec_info["ticker"]
        sec_1w_ret = sec_info["1w_return"]
        sec_stocks = sector_to_stocks.get(sector, [])
        
        stock_perf_list = []
        for ticker in sec_stocks:
            try:
                # Extract stock dataframe
                if is_multi:
                    if ticker not in master_data.columns.levels[0]:
                        continue
                    stock_df = master_data[ticker].dropna(subset=["Close"])
                else:
                    continue
                    
                if len(stock_df) < 5:
                    continue
                    
                # Calculate returns
                stk_1w_ret = (stock_df["Close"].iloc[-1] / stock_df["Close"].iloc[-5]) - 1
                stk_3m_ret = (stock_df["Close"].iloc[-1] / stock_df["Close"].iloc[0]) - 1
                
                # Check outperformance over its sector index
                stk_outperf_sec = stk_1w_ret - sec_1w_ret
                stk_outperf_nifty_3m = stk_3m_ret - nifty_3m_ret  # 3-Month Structural RS
                
                if stk_outperf_sec > 0:
                    stock_perf_list.append({
                        "ticker": ticker.replace(".NS", ""),
                        "1w_return": stk_1w_ret,
                        "3m_return": stk_3m_ret,
                        "1w_outperf": stk_outperf_sec,
                        "3m_rs": stk_outperf_nifty_3m
                    })
            except:
                continue
                
        if not stock_perf_list:
            continue
            
        # Sort stocks: Filter for structurally strong stocks (3-month return > nifty 3-month return)
        leaders = [s for s in stock_perf_list if s["3m_rs"] > 0]
        if not leaders:
            # If no stock has positive 3-month RS, take the raw list
            leaders = stock_perf_list
            
        # Sort by 1-week return descending
        leaders_sorted = sorted(leaders, key=lambda x: x["1w_return"], reverse=True)[:5] # Top 5 leaders
        
        report_data.append({
            "sector": sector,
            "index_ticker": sec_ticker,
            "index_1w_ret": sec_1w_ret * 100,
            "leaders": leaders_sorted
        })
        
    # 5. Format and send Telegram message
    target_date = datetime.now().strftime('%d-%m-%Y')
    msg = f"🪐 *SECTORAL ROTATION & LEADERS ({target_date})*\n"
    msg += f"📊 _Nifty 50 Weekly Return: {nifty_1w_ret*100:+.2f}%_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if not report_data:
        msg += "✅ No sectors outperformed the Nifty 50 benchmark this week."
    else:
        msg += "🔥 *OUTPERFORMING SECTORS & THEIR LEADERS*\n\n"
        for item in report_data:
            msg += f"📁 *Nifty {item['sector']}* (Weekly: `{item['index_1w_ret']:+.2f}%`)\n"
            msg += "`Ticker      1W-Ret    3M-Ret    RS-3M`\n"
            for s in item["leaders"]:
                rs_indicator = "🟢" if s["3m_rs"] > 0 else "⚪"
                msg += f"`{s['ticker']:<11} {s['1w_return']*100:<+8.1f}% {s['3m_return']*100:<+8.1f}% {s['3m_rs']*100:>+5.1f}%` {rs_indicator}\n"
            msg += "\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += "💡 *Legend:*\n"
        msg += "`1W-Ret`: 1-Week absolute return\n"
        msg += "`RS-3M` : 3-Month outperformance vs Nifty 50\n"
        msg += "🟢 : Structurally strong (Outperforming Nifty 50 over 3 months)\n"
        
    send_telegram(msg)
    print("✅ Sectoral report sent.")

if __name__ == "__main__":
    main()
