import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# Core Path Setup
script_dir = os.path.dirname(os.path.abspath(__file__))
CLOSED_TRADES_PATH = os.path.join(script_dir, "closed_trades.json")

def run_exit_audit():
    print("==========================================================")
    print("🪐 KRONOS QUANTITATIVE SYSTEM: POST-EXIT PERFORMANCE AUDIT")
    print("==========================================================\n")
    
    # 1. Load the database safely
    if not os.path.exists(CLOSED_TRADES_PATH):
        print(f"❌ Database not found at: {CLOSED_TRADES_PATH}")
        return
        
    with open(CLOSED_TRADES_PATH, "r", encoding="utf-8") as f:
        closed_trades = json.load(f)
        
    print(f"📊 Loaded {len(closed_trades)} historical exits for analysis...\n")
    
    # 2. Process each trade item mechanically
    for trade in closed_trades:
        ticker = trade['ticker']
        name = trade['company_name']
        exit_p = trade['exit_price']
        exit_d_str = trade['exit_date']
        
        print(f"🔍 Analyzing {name} ({ticker}) -- Exited on {exit_d_str} at ₹{exit_p}")
        
        # Calculate 30-day window dates for post-exit tracking
        exit_date_obj = datetime.strptime(exit_d_str, "%Y-%m-%d")
        end_date_obj = exit_date_obj + timedelta(days=30)
        
        start_search = exit_date_obj.strftime("%Y-%m-%d")
        end_search = end_date_obj.strftime("%Y-%m-%d")
        
        try:
            # Download market history data for that specific past time frame
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start_search, end=end_search, progress=False)
            
            if hist.empty:
                print(f"⚠️ No historical price data found for {ticker} within that window.\n")
                continue
                
            # Compute system comparison metrics
            max_rallied = hist['High'].max()
            min_crashed = hist['Low'].min()
            
            perf_pct_high = ((max_rallied - exit_p) / exit_p) * 100
            perf_pct_low = ((min_crashed - exit_p) / exit_p) * 100
            
            # 3. Print evaluation feedback using dynamic structural criteria
            print(f"   📈 Post-Exit Max Peak reached: ₹{max_rallied:.2f} ({perf_pct_high:+.2%})")
            print(f"   📉 Post-Exit Max Drop reached: ₹{min_crashed:.2f} ({perf_pct_low:+.2%})")
            
            # SCENARIO A: Wasted potential / Early shakeout
            if perf_pct_high >= 15.0:
                print("   🚨 [SHAKEOUT DETECTED]: The stock jumped heavily after you left!")
                print("      👉 FIX: Increase your ATR multiplier or widen lookback windows on this sector.")
                
            # SCENARIO B: Perfect defensive execution
            elif perf_pct_low <= -10.0:
                print("   🛡️ [PERFECT RISK PROTECTION]: The stock crashed lower immediately after exit!")
                print("      👉 VERDICT: The Ratchet stop successfully saved your capital.")
                
            # SCENARIO C: Balanced consolidation / Stable floor
            else:
                print("   ✅ [OPTIMIZED EXIT]: The price stayed stable. Exit structure was highly efficient.")
                
            print("-" * 58)
            
        except Exception as e:
            print(f"   ❌ Could not process analysis data for {ticker}: {e}\n")

if __name__ == "__main__":
    run_exit_audit()
