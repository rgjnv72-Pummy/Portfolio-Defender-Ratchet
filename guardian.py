import yfinance as yf
import pandas as pd
import numpy as np
import http.client, json, os
from datetime import datetime

yf.set_tz_cache_location("cache")

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- DYNAMIC ASSET REGISTRY SYNC LAYER ---
def load_live_portfolio():
    """Dynamically reads your live position matrix from your common JSON database file."""
    # Robust path detection: check script dir, then parent, then specific Ratchet-System folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_check = [
        os.path.join(script_dir, "portfolio.json"),
        os.path.join(os.path.dirname(script_dir), "Ratchet-System", "portfolio.json"),
        "portfolio.json"
    ]
    
    portfolio_path = None
    for p in paths_to_check:
        if os.path.exists(p):
            portfolio_path = p
            break
    
    # Ultimate Fallback Core if file isn't written yet
    # --- START FALLBACK ---
    fallback_holdings = {
        "PREMIERENE.NS": [150, 943.30, "2026-04-07", "Infrastructure", 943.30, "swing"],
        "ADANIPORTS.NS": [70, 1702.00, "2026-05-04", "Infrastructure", 1702.00, "swing"],
        "HFCL.NS": [1000, 122.50, "2026-05-04", "Telecommunication", 122.50, "swing"],
        "LAURUSLABS.NS": [118, 1278.50, "2026-05-30", "Pharma", 1278.50, "swing"],
        "BHARATFORG.NS": [39, 1959.00, "2026-05-15", "Industrial Manufacturing", 1959.00, "swing"],
        "ATHERENERG.NS": [100, 943.00, "2026-05-11", "Auto Components", 943.00, "swing"],
        "CARBORUNIV.NS": [111, 1024.71, "2026-05-12", "Capital Goods", 1024.71, "swing"],
        "RAINBOW.NS": [80, 1341.00, "2026-05-18", "Healthcare", 1341.00, "swing"],
        "SYRMA.NS": [100, 1238.00, "2026-06-09", "Capital Goods", 1238.00, "swing"],
        "WELCORP.NS": [100, 1406.00, "2026-06-09", "Capital Goods", 1406.00, "swing"],
        "FEDERALBNK.NS": [595, 305.57, "2026-06-10", "Financial Services", 305.57, "swing"],
        "RADICO.NS": [46, 3618.00, "2026-06-18", "Fast Moving Consumer Goods", 3618.00, "swing"],
        "BELRISE.NS": [834, 232.00, "2026-07-07", "Auto Components", 232.00, "swing"],
        "OFSS.NS": [17, 11260.00, "2026-07-07", "Information Technology", 11260.00, "swing"],
        "CHOICEIN.NS": [175, 828.00, "2026-07-13", "Financial Services", 828.00, "swing"]
    }
    # --- END FALLBACK ---
    
    if not portfolio_path:
        return fallback_holdings
        
    try:
        with open(portfolio_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        holdings = data.get("holdings", {})
        if not holdings: return fallback_holdings
        
        # Format custom configuration vectors to integrate seamlessly with your watchdog loops
        formatted_holdings = {}
        for ticker, info in holdings.items():
            formatted_holdings[ticker] = [
                info.get("quantity", 1),
                info.get("avg_cost", 1.0),
                info.get("buy_date", "2026-05-01"),
                info.get("sector", "General"),
                info.get("current_price", info.get("avg_cost", 1.0)),
                info.get("strategy", "swing")
            ]
        return formatted_holdings
    except:
        return fallback_holdings

def send_msg(text):
    token = MY_TOKEN.strip() if MY_TOKEN else None
    chat_id = MY_CHAT_ID.strip() if MY_CHAT_ID else None
    if not token or not chat_id:
        try:
            print(text)
        except UnicodeEncodeError:
            try:
                print(text.encode('ascii', 'ignore').decode('ascii'))
            except Exception:
                pass
        return
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{token}/sendMessage", payload, headers)
        conn.getresponse()  # Fixed multiple-assignment assignment typo string
        conn.close()
    except Exception as e:
        try:
            print(f"❌ Telegram Error: {e}")
        except UnicodeEncodeError:
            print(f"Telegram Error: {e}")
def compute_historical_ratchet(df, buy_date_str, buy_p, strategy="swing"):
    df = df.copy()
    buy_date = pd.to_datetime(buy_date_str)
    
    # Calculate ATR (14)
    tr = pd.concat([
        df['High'] - df['Low'], 
        (df['High'] - df['Close'].shift(1)).abs(), 
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    
    # Pre-entry ATR (60 days prior to buy_date)
    atr_pre_entry = atr[atr.index <= buy_date].tail(60)
    if not atr_pre_entry.empty:
        entry_atr = float(atr_pre_entry.max())
    else:
        entry_atr = float(atr.iloc[0]) if not atr.empty else 0.0
        
    initial_atr_floor = buy_p - (1.5 * entry_atr)
    
    # We only compute ratchet starting from the buy_date onwards
    valid_df = df[df.index >= buy_date].copy()
    if valid_df.empty:
        return pd.Series(dtype='float64'), pd.Series(dtype='float64'), 0.0, 0, 1.5, 40
        
    valid_atr = atr.reindex(valid_df.index)
    
    # Historical returns standard dev (60 days lookback)
    hist_vol = df['Close'].pct_change().tail(60).std()
    if hist_vol >= 0.030:
        lookback_days = 15
    elif hist_vol >= 0.018:
        lookback_days = 25
    else:
        lookback_days = 40
        
    ratchet_history = []
    hard_floor_history = []
    
    # Peak price tracker
    peak_price = 0.0
    milestones_achieved = 0
    mult = 2.0
    
    # Generate milestone thresholds
    milestone_levels = []
    m_val = buy_p
    for i in range(1, 15):
        m_val = m_val * 1.30
        milestone_levels.append(m_val)
        
    for idx, row in valid_df.iterrows():
        close_p = row['Close']
        
        # Determine milestones achieved by the peak price up to this index
        running_df = valid_df.loc[valid_df.index <= idx]
        peak_price = float(running_df['Close'].max())
        
        milestones_achieved = 0
        active_base = buy_p
        
        if strategy == "swing":
            for i, level in enumerate(milestone_levels):
                if peak_price >= level:
                    milestones_achieved = i + 1
                    active_base = level
                else:
                    break
        
        # treating active_base like entry price for P&L-based multiplier
        pnl_pct = ((close_p - active_base) / active_base) * 100
        
        # Dynamic Multiplier
        if pnl_pct > 20.0:
            mult = 2.5
        elif pnl_pct < 0.0:
            mult = 1.5
        else:
            mult = 2.0
            
        # Calculate lookback raw ratchet
        history_so_far = valid_df.loc[valid_df.index <= idx].tail(lookback_days)
        history_atr = valid_atr.reindex(history_so_far.index)
        
        # Calculate PnL for each day in lookback window relative to active_base
        hist_pnl = ((history_so_far['Close'] - active_base) / active_base) * 100
        hist_mult = hist_pnl.apply(lambda x: 2.5 if x > 20.0 else (1.5 if x < 0.0 else 2.0))
        hist_raw_ratchets = history_so_far['Close'] - (hist_mult * history_atr)
        rolling_ratchet = hist_raw_ratchets.max()
        
        # Hard Floor determination
        if strategy == "swing" and milestones_achieved >= 1:
            # 1. Lock in half of the milestone gains achieved so far
            profit_lock = buy_p * (1.0 + (1.30**milestones_achieved - 1.0) / 2.0)
            
            # 2. Strict tight trailing stop: 1.5x ATR from running peak price
            running_valid_df = valid_df.loc[valid_df.index <= idx]
            running_atr = valid_atr.reindex(running_valid_df.index)
            peak_stops = running_valid_df['Close'].cummax() - (1.5 * running_atr)
            tight_trailing = float(peak_stops.max())
            
            # Dynamic floor is the highest of profit lock and tight trailing stop
            hard_floor = max(profit_lock, tight_trailing)
        else:
            hard_floor = initial_atr_floor
            
        # Guardrails: soft trailing stop retreats during pullbacks to avoid shakeouts,
        # but is strictly bounded by hard_floor and close_p * 0.97
        final_ratchet = min(rolling_ratchet, close_p * 0.97)
        final_ratchet = max(final_ratchet, hard_floor)
        
        ratchet_history.append(final_ratchet)
        hard_floor_history.append(hard_floor)
        
    return pd.Series(ratchet_history, index=valid_df.index), pd.Series(hard_floor_history, index=valid_df.index), peak_price, milestones_achieved, mult, lookback_days

def run_simplified_watchdog():
    CURRENT_HOLDINGS = load_live_portfolio()
    try:
        tickers = list(CURRENT_HOLDINGS.keys()) + ["^NSEI"]
        data = yf.download(tickers, period="1y", interval="1d", progress=False, auto_adjust=True)
    except Exception:
        data = pd.DataFrame()

    try:
        nifty_close = data['Close']['^NSEI'].dropna()
        nifty_chg = ((nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2]) * 100
    except Exception:
        nifty_chg = 0.0

    results = []
    total_val, daily_gain_sum, total_cost = 0.0, 0.0, 0.0
    skipped_tickers = []
    sector_values = {}
    total_scrips = len(CURRENT_HOLDINGS)

    # --- FIRST PASS: GLOBAL VALUATION & SECTOR SUMMARY ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p, strategy) in CURRENT_HOLDINGS.items():
        try:
            if (not data.empty) and ('Close' in data.columns) and (ticker in data['Close'].columns):
                df_ticker = data.xs(ticker, axis=1, level=1).dropna()
                if len(df_ticker) >= 2:
                    latest_close = float(df_ticker['Close'].iloc[-1])
                    yesterday_close = float(df_ticker['Close'].iloc[-2])
                    
                    current_value = (latest_close * qty)
                    total_val += current_value
                    total_cost += (buy_p * qty)
                    daily_gain_sum += (latest_close - yesterday_close) * qty
                    sector_values[sector] = sector_values.get(sector, 0.0) + current_value
                    continue
            raise ValueError()
        except Exception:
            current_fallback_value = (fallback_p * qty)
            total_val += current_fallback_value
            total_cost += (buy_p * qty)
            daily_gain_sum += 0.0 
            sector_values[sector] = sector_values.get(sector, 0.0) + current_fallback_value
            skipped_tickers.append(ticker.replace('.NS', ''))

    # --- SECOND PASS: EXTREME DUAL-ENGINE RISK ANALYSIS ---
    for ticker, (qty, buy_p, buy_date, sector, fallback_p, strategy) in CURRENT_HOLDINGS.items():
        try:
            if (data.empty) or ('Close' not in data.columns) or (ticker not in data['Close'].columns):
                continue
                
            df = data.xs(ticker, axis=1, level=1).dropna().copy()
            if len(df) < 60: 
                continue
            
            close_p = float(df['Close'].iloc[-1])
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            ratchet_series, floor_series, peak_p, milestones, mult, lookback_days = compute_historical_ratchet(
                df, buy_date, buy_p, strategy
            )
            
            if ratchet_series.empty:
                continue
                
            ratchet = ratchet_series.iloc[-1]
            hard_floor = floor_series.iloc[-1]
            
            # Check for milestone achievement alerts
            if strategy == "swing":
                milestone_levels = []
                m_val = buy_p
                for i in range(1, 15):
                    m_val = m_val * 1.30
                    milestone_levels.append(m_val)
                
                # Check today's milestone count vs yesterday's
                valid_df = df[df.index >= buy_date].copy()
                if valid_df.empty:
                    valid_df = df.iloc[-5:]
                    
                peak_price_today = float(valid_df['Close'].max())
                milestones_today = 0
                active_base_today = buy_p
                for i, level in enumerate(milestone_levels):
                    if peak_price_today >= level:
                        milestones_today = i + 1
                        active_base_today = level
                    else:
                        break
                        
                if len(valid_df) >= 2:
                    peak_price_yesterday = float(valid_df['Close'].iloc[:-2].max()) if len(valid_df) > 2 else float(valid_df['Close'].iloc[0])
                else:
                    peak_price_yesterday = buy_p
                    
                milestones_yesterday = 0
                for i, level in enumerate(milestone_levels):
                    if peak_price_yesterday >= level:
                        milestones_yesterday = i + 1
                    else:
                        break
                        
                if milestones_today > milestones_yesterday:
                    locked_in_profit_pct = ((active_base_today - buy_p) / buy_p) * 100
                    msg = (f"🏆 *KRONOS MILESTONE ACHIEVED:* `{ticker.replace('.NS','')}` has achieved the "
                           f"*{milestones_today}* hard-floor milestone (CMP: ₹{close_p:.2f}). "
                           f"Hard stop-floor elevated to lock in *+{locked_in_profit_pct:.1f}%* profit (₹{active_base_today:.2f}).")
                    send_msg(msg)
            
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            
            if dist_to_stop > 3.0:
                continue

            is_triggered = close_p <= (ratchet + 0.05)
            status_icon = "🚨 *BREAK*" if is_triggered else "⚠️ *RISK*"
            
            clean_name = ticker.replace('.NS','').replace('ENERG','')
            line_text = f"*{clean_name}* | Price: ₹{close_p:.1f} ({pnl_pct:+.1f}%) | {status_icon}\n"
            line_text += f"_Stop Floor: ₹{ratchet:.1f} ({dist_to_stop:.1f}% cushion) | Config: {strategy.capitalize()} | {lookback_days}D Lookback / {mult}x Mult_\n\n"
            
            results.append({'text': line_text, 'cushion': dist_to_stop})
        except Exception:
            continue

    # --- REPORT COMPOSITION ---
    if results:
        report = f"📋 *LIVE RISK WATCHDOG (<3% Cushion): {datetime.now().strftime('%d %b')}*\n"
        report += f"Nifty 50 Index: {nifty_chg:+.2f}%\n"
        report += f"Total Active Scrips: {total_scrips}\n"
        report += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        sorted_results = sorted(results, key=lambda x: x['cushion'])
        for res in sorted_results: 
            report += res['text']
    
        report += "🏗️ *SECTOR EXPOSURE SUMMARY*\n"
        for sec, val in sorted(sector_values.items(), key=lambda item: item[1], reverse=True): 
            allocation_pct = (val / total_val) * 100 if total_val > 0 else 0
            report += f"• {sec}: {allocation_pct:.1f}%\n"
        report += "\n"
    
        if skipped_tickers:
            report += f"ℹ️ *Skipped Risk Charts*: {', '.join(skipped_tickers)}\n\n"
    
        port_daily_pct = (daily_gain_sum / (total_val - daily_gain_sum)) * 100 if (total_val - daily_gain_sum) > 0 else 0
        total_pnl_pct = ((total_val - total_cost) / total_cost) * 100 if total_cost > 0 else 0
        
        alpha_metric = port_daily_pct - nifty_chg
        alpha_icon = "🔥" if alpha_metric > 0 else "❄️"
        
        val_lakhs = total_val / 100000
        gain_lakhs = daily_gain_sum / 100000
        
        report += "━━━━━━━━━━━━━━━━━━━━\n"
        report += f"📊 *SUMMARY*\n"
        report += f"Live Account Value: ₹{val_lakhs:.2f}L\n"
        report += f"Open Book Profit: {total_pnl_pct:+.2f}%\n"
        report += f"Session Change: ₹{gain_lakhs:+.2f}L ({port_daily_pct:+.2f}%)\n"
        report += f"Session Alpha: {alpha_metric:+.2f}% {alpha_icon}"
        
        send_msg(report)
    else:
        report = f"📋 *LIVE RISK WATCHDOG: {datetime.now().strftime('%d %b')}*\n"
        report += f"Nifty 50 Index: {nifty_chg:+.2f}%\n"
        report += "━━━━━━━━━━━━━━━━━━━━\n"
        report += "✅ All open positions currently have a healthy cushion (>3%)."
        send_msg(report)

if __name__ == "__main__":
    run_simplified_watchdog()
