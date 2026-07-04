import os
import sys
import pandas as pd
import requests

# --- UTF-8 CONSOLE ENCODING FIX (Windows Support) ---
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import yfinance as yf
except ImportError:
    print("❌ Critical dependency yfinance missing.")
    sys.exit(1)

TICKERS_CSV = 'ind_nifty500list.csv'
CACHE_FILE = 'nifty500_data.pkl'

def main():
    print("🚀 Starting Unified Quant Data Fetcher Engine...")
    
    if not os.path.exists(TICKERS_CSV):
        print(f"❌ Error: Watchlist file '{TICKERS_CSV}' not found.")
        sys.exit(1)
        
    try:
        df_csv = pd.read_csv(TICKERS_CSV)
    except Exception as e:
        print(f"❌ Read Failure on file {TICKERS_CSV}: {e}")
        sys.exit(1)

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

    # Include benchmark Nifty index
    if "^NSEI" not in formatted_tickers:
        formatted_tickers.append("^NSEI")

    print(f"📥 Downloading historical data in batch for {len(formatted_tickers)} assets (2y period)...")
    
    session = None
    if os.getenv("GITHUB_ACTIONS"):
        session = requests.Session()
        session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        
    try:
        master_data = yf.download(formatted_tickers, period="2y", interval="1d", group_by="ticker", progress=False, auto_adjust=True, session=session)
    except Exception as e:
        print(f"❌ Batch download failed: {e}")
        sys.exit(1)

    if master_data.empty:
        print("❌ Error: Downloaded dataset is empty.")
        sys.exit(1)

    print(f"💾 Caching dataset to '{CACHE_FILE}'...")
    try:
        master_data.to_pickle(CACHE_FILE)
        print(f"✅ Cache updated successfully: {len(master_data)} rows cached.")
    except Exception as e:
        print(f"❌ Cache save failure: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
