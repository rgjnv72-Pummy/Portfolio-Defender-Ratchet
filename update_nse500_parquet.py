import os
import sys
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Fix Windows console encoding for Unicode symbols
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import yfinance as yf
except ImportError:
    print("❌ Error: Critical dependency 'yfinance' is not installed.")
    sys.exit(1)

try:
    import pyarrow
except ImportError:
    print("❌ Error: Critical dependency 'pyarrow' is not installed.")
    sys.exit(1)

# Base Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ENGINE_DIR, "data")
BY_TICKER_DIR = os.path.join(DATA_DIR, "by_ticker")
MASTER_PARQUET = os.path.join(DATA_DIR, "nse500_daily.parquet")
CSV_PATH = os.path.join(SCRIPT_DIR, "ind_nifty500list.csv")

os.makedirs(BY_TICKER_DIR, exist_ok=True)

def load_universe_with_meta():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Watchlist file '{CSV_PATH}' not found.")
        
    df_csv = pd.read_csv(CSV_PATH)
    sym_col = next((c for c in df_csv.columns if "symbol" in c.lower() or "ticker" in c.lower()), "Symbol")
    name_col = next((c for c in df_csv.columns if "company" in c.lower() or "name" in c.lower()), "Company Name")
    ind_col = next((c for c in df_csv.columns if "industry" in c.lower() or "sector" in c.lower()), "Industry")
    
    meta_map = {}
    tickers = []
    
    for _, row in df_csv.iterrows():
        sym_raw = str(row[sym_col]).strip().split()[0].replace(",", "")
        if not sym_raw or "NAN" in sym_raw.upper() or "SYMBOL" in sym_raw.upper():
            continue
        ticker = f"{sym_raw}.NS" if not sym_raw.endswith(".NS") else sym_raw
        tickers.append(ticker)
        meta_map[ticker] = {
            "Company": str(row.get(name_col, sym_raw)).strip(),
            "Industry": str(row.get(ind_col, "Unknown")).strip()
        }
        
    # Include Benchmark Index
    if "^NSEI" not in tickers:
        tickers.append("^NSEI")
        meta_map["^NSEI"] = {
            "Company": "Nifty 50 Benchmark Index",
            "Industry": "Benchmark Index"
        }
        
    return sorted(list(set(tickers))), meta_map

def download_in_chunks(tickers, period, chunk_size=75):
    """Download tickers in robust chunks to prevent Yahoo Finance connection drops."""
    all_chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    combined_data = {}
    
    total_chunks = len(all_chunks)
    for idx, chunk in enumerate(all_chunks, 1):
        print(f"   ↳ [Batch {idx}/{total_chunks}] Downloading {len(chunk)} scrips (period={period})...")
        try:
            chunk_data = yf.download(
                chunk,
                period=period,
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                timeout=30
            )
            if not chunk_data.empty:
                for ticker in chunk:
                    try:
                        if isinstance(chunk_data.columns, pd.MultiIndex):
                            if ticker in chunk_data.columns.levels[0]:
                                df_single = chunk_data.xs(ticker, axis=1, level=0).copy()
                            elif ticker in chunk_data.columns.levels[1]:
                                df_single = chunk_data.xs(ticker, axis=1, level=1).copy()
                            else:
                                continue
                        else:
                            df_single = chunk_data.copy()
                            
                        df_single = df_single.dropna(how="all")
                        if not df_single.empty and "Close" in df_single.columns:
                            combined_data[ticker] = df_single
                    except Exception:
                        continue
        except Exception as e:
            print(f"      ⚠️ Batch {idx} error: {e}")
            continue
            
    return combined_data

def sync_nse500_parquet(force_bootstrap=False, history_period="3y"):
    print("=" * 65)
    print("🚀 KRONOS NSE 500 LOCAL PARQUET DATA LAKE SYNC ENGINE")
    print("=" * 65)
    
    tickers, meta_map = load_universe_with_meta()
    print(f"📋 Total Scrips in Universe: {len(tickers)} (from 'ind_nifty500list.csv')")
    
    is_bootstrap = force_bootstrap or not os.path.exists(MASTER_PARQUET)
    
    if is_bootstrap:
        print(f"📥 Mode: FULL INITIAL BOOTSTRAP (Downloading {history_period} of daily OHLCV)...")
        data_dict = download_in_chunks(tickers, period=history_period, chunk_size=80)
    else:
        print("🔄 Mode: INCREMENTAL WEEKEND DELTA (Fetching last 7-10 days)...")
        data_dict = download_in_chunks(tickers, period="10d", chunk_size=80)
        
    if not data_dict:
        print("❌ Error: No valid data retrieved from download engine.")
        return False
        
    print(f"⚙️ Successfully extracted data for {len(data_dict)} scrips. Processing into Parquet format...")
    
    records = []
    updated_count = 0
    
    for ticker, df_single in data_dict.items():
        try:
            df_single = df_single.reset_index()
            date_col = next((c for c in df_single.columns if "date" in str(c).lower()), "index")
            df_single = df_single.rename(columns={date_col: "Date"})
            df_single["Date"] = pd.to_datetime(df_single["Date"])
            
            # Keep core OHLCV
            req_cols = ["Open", "High", "Low", "Close", "Volume"]
            for col in req_cols:
                if col not in df_single.columns:
                    df_single[col] = np.nan
                    
            df_single = df_single.dropna(subset=["Close"])
            if df_single.empty:
                continue
                
            df_single["Ticker"] = ticker
            df_single["Company"] = meta_map.get(ticker, {}).get("Company", ticker)
            df_single["Industry"] = meta_map.get(ticker, {}).get("Industry", "General")
            
            df_single = df_single[["Date", "Ticker", "Company", "Industry", "Open", "High", "Low", "Close", "Volume"]]
            records.append(df_single)
            
            # Update individual ticker parquet
            t_path = os.path.join(BY_TICKER_DIR, f"{ticker}.parquet")
            if os.path.exists(t_path) and not is_bootstrap:
                try:
                    old_t = pd.read_parquet(t_path)
                    old_t["Date"] = pd.to_datetime(old_t["Date"])
                    combined_t = pd.concat([old_t, df_single]).drop_duplicates(subset=["Date"]).sort_values("Date")
                    combined_t.to_parquet(t_path, engine="pyarrow", compression="snappy", index=False)
                except Exception:
                    df_single.sort_values("Date").to_parquet(t_path, engine="pyarrow", compression="snappy", index=False)
            else:
                df_single.sort_values("Date").to_parquet(t_path, engine="pyarrow", compression="snappy", index=False)
                
            updated_count += 1
        except Exception as e:
            continue

    if not records:
        print("❌ Error: No records compiled for master dataset.")
        return False
        
    new_master = pd.concat(records, ignore_index=True)
    new_master["Date"] = pd.to_datetime(new_master["Date"])
    
    if os.path.exists(MASTER_PARQUET) and not is_bootstrap:
        try:
            print("🔗 Merging incremental delta with existing master Parquet lake...")
            old_master = pd.read_parquet(MASTER_PARQUET)
            old_master["Date"] = pd.to_datetime(old_master["Date"])
            final_master = pd.concat([old_master, new_master]).drop_duplicates(subset=["Ticker", "Date"]).sort_values(["Ticker", "Date"])
        except Exception as e:
            print(f"⚠️ Error reading old master ({e}), replacing with new dataset.")
            final_master = new_master.sort_values(["Ticker", "Date"])
    else:
        final_master = new_master.sort_values(["Ticker", "Date"])
        
    print(f"💾 Saving master table to '{MASTER_PARQUET}'...")
    final_master.to_parquet(MASTER_PARQUET, engine="pyarrow", compression="snappy", index=False)
    
    # Quantitative Summary Metrics
    file_size_mb = os.path.getsize(MASTER_PARQUET) / (1024 * 1024)
    total_bars = len(final_master)
    earliest_date = final_master["Date"].min().strftime("%Y-%m-%d")
    latest_date = final_master["Date"].max().strftime("%Y-%m-%d")
    unique_scrips = final_master["Ticker"].nunique()
    
    print("-" * 65)
    print("✨ LOCAL PARQUET DATA LAKE SYNC COMPLETED SUCCESSFULLY!")
    print(f"📊 Total Stored Daily Bars: {total_bars:,} rows")
    print(f"📈 Total Unique Scrips:    {unique_scrips} / {len(tickers)}")
    print(f"📅 Historical Time Span:   {earliest_date}  ➔  {latest_date}")
    print(f"💾 Master Parquet Size:     {file_size_mb:.2f} MB (Snappy compressed)")
    print(f"📁 Per-Scrip Files Saved:   {updated_count} files in 'data/by_ticker/'")
    print("=" * 65)
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync NSE 500 Historical Data to Local Parquet Data Lake")
    parser.add_argument("--bootstrap", action="store_true", help="Force full historical re-download (3 years)")
    parser.add_argument("--period", type=str, default="3y", help="Historical period for bootstrap (e.g. '2y', '3y', '5y')")
    args = parser.parse_args()
    
    sync_nse500_parquet(force_bootstrap=args.bootstrap, history_period=args.period)
