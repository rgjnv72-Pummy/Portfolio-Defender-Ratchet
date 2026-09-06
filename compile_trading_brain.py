"""
================================================================================
🪐 KRONOS QUANTITATIVE ECOSYSTEM: TRADING KNOWLEDGE COMPILER
================================================================================
Architecture Inspired by Andrej Karpathy's LLM Wiki (April 2026)
"RAG re-derives knowledge on every query. A compiled wiki derives it once
and keeps it current."

Functionality:
1. Dynamic Ingestion: Reads active holdings, closed trades, and scanner confluences.
2. Thesis Contradiction Engine: Compares live price/volume action against entry hypotheses.
3. Dead-Money / Stale Momentum Flagger: Flags positions held >=10 days with <1.5% drift.
4. Ratchet Health Audit: Evaluates 14D ATR ratchets, hard shield floors, and cushion %.
5. Playbook Compiler: Derives cumulative quantitative rules from all closed trade exits.
6. Obsidian Vault Compilation: Continuously updates individual ticker dossiers in
   Obsidian-Journal/Ticker-Research/<TICKER>.md and compiles Playbook-Rules.md.
7. Morning Executive Dispatch: Sends high-conviction decision brief via Telegram.
================================================================================
"""

import os
import sys
import json
import datetime
import requests
import numpy as np
import pandas as pd
import yfinance as yf

# Configure UTF-8 stdout for cross-platform compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# --- DIRECTORY SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OBSIDIAN_DIR = os.path.join(BASE_DIR, "Obsidian-Journal")
TICKER_RESEARCH_DIR = os.path.join(OBSIDIAN_DIR, "Ticker-Research")
os.makedirs(TICKER_RESEARCH_DIR, exist_ok=True)

# Custom dotenv loader
def load_custom_dotenv(dotenv_path):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'").strip('"')

load_custom_dotenv(os.path.join(BASE_DIR, ".env"))
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- FALLBACK HOLDINGS (15 ACTIVE POSITIONS AS OF 2026-09-04) ---
FALLBACK_HOLDINGS = {
    "OFSS.NS": {"quantity": 17, "avg_cost": 11260.00, "buy_date": "2026-07-07", "sector": "Information Technology", "strategy": "swing"},
    "SONACOMS.NS": {"quantity": 231, "avg_cost": 775.00, "buy_date": "2026-08-03", "sector": "Auto Components", "strategy": "swing"},
    "NEULANDLAB.NS": {"quantity": 7, "avg_cost": 23180.57, "buy_date": "2026-08-17", "sector": "Pharma", "strategy": "swing"},
    "ANANDRATHI.NS": {"quantity": 75, "avg_cost": 2195.00, "buy_date": "2026-08-18", "sector": "Financial Services", "strategy": "swing"},
    "BOSCHLTD.NS": {"quantity": 3, "avg_cost": 48606.67, "buy_date": "2026-08-20", "sector": "Auto Components", "strategy": "swing"},
    "DIVISLAB.NS": {"quantity": 20, "avg_cost": 8818.00, "buy_date": "2026-08-26", "sector": "Pharma", "strategy": "swing"},
    "AUBANK.NS": {"quantity": 150, "avg_cost": 1123.00, "buy_date": "2026-08-27", "sector": "Financial Services", "strategy": "swing"},
    "BHEL.NS": {"quantity": 352, "avg_cost": 430.00, "buy_date": "2026-08-31", "sector": "Capital Goods", "strategy": "swing"},
    "CPPLUS.NS": {"quantity": 45, "avg_cost": 3555.00, "buy_date": "2026-09-01", "sector": "Electronics", "strategy": "swing"},
    "HONASA.NS": {"quantity": 350, "avg_cost": 485.00, "buy_date": "2026-09-01", "sector": "Fast Moving Consumer Goods", "strategy": "swing"},
    "WELCORP.NS": {"quantity": 70, "avg_cost": 2420.00, "buy_date": "2026-09-01", "sector": "Metals & Mining", "strategy": "swing"},
    "FEDERALBNK.NS": {"quantity": 300, "avg_cost": 356.00, "buy_date": "2026-09-03", "sector": "Financial Services", "strategy": "swing"},
    "LTFOODS.NS": {"quantity": 250, "avg_cost": 445.00, "buy_date": "2026-09-03", "sector": "Fast Moving Consumer Goods", "strategy": "swing"},
    "SAIL.NS": {"quantity": 500, "avg_cost": 197.00, "buy_date": "2026-09-04", "sector": "Metals & Mining", "strategy": "swing"},
    "ZYDUSWELL.NS": {"quantity": 200, "avg_cost": 540.00, "buy_date": "2026-09-04", "sector": "Fast Moving Consumer Goods", "strategy": "swing"}
}

def send_telegram_alert(text):
    if not TOKEN or not CHAT_ID:
        print("[WARNING] Telegram credentials not configured. Skipping alert.")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("[SUCCESS] Telegram compilation brief dispatched.")
        else:
            print(f"[WARNING] Telegram dispatch status: {r.status_code}")
    except Exception as e:
        print(f"[ERROR] Failed sending Telegram message: {e}")

def load_live_portfolio():
    """Dynamically locates and loads the authoritative portfolio matrix."""
    paths_to_check = [
        os.path.join(BASE_DIR, "Ratchet-System", "portfolio.json"),
        os.path.join(BASE_DIR, "Scanner-Scripts", "portfolio.json"),
        os.path.join(BASE_DIR, "portfolio.json"),
        os.path.join(BASE_DIR, "latest_portfolio_positions.json")
    ]
    for p in paths_to_check:
        if os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                holdings_raw = data.get("holdings", {})
                if holdings_raw:
                    formatted = {}
                    if isinstance(holdings_raw, dict):
                        for t, info in holdings_raw.items():
                            clean_t = t if t.endswith(".NS") or t.startswith("^") else f"{t}.NS"
                            if isinstance(info, dict):
                                formatted[clean_t] = {
                                    "quantity": info.get("quantity", info.get("qty", 1)),
                                    "avg_cost": float(info.get("avg_cost", 1.0)),
                                    "buy_date": info.get("buy_date", "2026-05-01"),
                                    "sector": info.get("sector", "General"),
                                    "strategy": info.get("strategy", "swing")
                                }
                    elif isinstance(holdings_raw, list):
                        for item in holdings_raw:
                            if isinstance(item, dict):
                                t = item.get("full_ticker") or item.get("ticker", "")
                                clean_t = t if t.endswith(".NS") or t.startswith("^") else f"{t}.NS"
                                formatted[clean_t] = {
                                    "quantity": item.get("qty", item.get("quantity", 1)),
                                    "avg_cost": float(item.get("avg_cost", 1.0)),
                                    "buy_date": item.get("buy_date", "2026-05-01"),
                                    "sector": item.get("sector", "General"),
                                    "strategy": item.get("strategy", "swing")
                                }
                    if formatted:
                        print(f"[INFO] Loaded {len(formatted)} positions from: {p}")
                        return formatted
            except Exception:
                continue
    print("[INFO] Utilizing embedded fallback holdings.")
    return FALLBACK_HOLDINGS

def load_closed_trades():
    paths = [
        os.path.join(BASE_DIR, "Ratchet-System", "closed_trades.json"),
        os.path.join(BASE_DIR, "Scanner-Scripts", "closed_trades.json"),
        os.path.join(BASE_DIR, "closed_trades.json")
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return []

def load_scanner_origins():
    """Parses Obsidian-Journal/Portfolio-Active-Positions.md for scanner origins."""
    map_origins = {}
    note_path = os.path.join(OBSIDIAN_DIR, "Portfolio-Active-Positions.md")
    if not os.path.exists(note_path):
        return map_origins
    try:
        with open(note_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("- **[[") and "Entry Scanners:" in line:
                    parts = line.split("]]**:")
                    ticker_part = parts[0].replace("- **[[", "").strip()
                    tail = parts[1]
                    scanners = tail.split("Entry Scanners:")[1].strip()
                    clean_t = f"{ticker_part}.NS"
                    map_origins[clean_t] = scanners
    except Exception as e:
        print(f"[WARNING] Could not parse scanner origins: {e}")
    return map_origins

def compute_historical_ratchet(df, buy_date_str, buy_p, strategy="swing"):
    """Authoritative KRONOS Dual-Engine Trailing Stop-Loss Ratchet."""
    df = df.copy()
    buy_date = pd.to_datetime(buy_date_str)
    
    if not df.empty and buy_date not in df.index:
        prior_dates = df.index[df.index <= buy_date]
        effective_buy_date = prior_dates[-1] if not prior_dates.empty else df.index[0]
    else:
        effective_buy_date = buy_date
        
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    
    atr_pre_entry = atr[atr.index <= effective_buy_date].tail(60)
    entry_atr = float(atr_pre_entry.max()) if not atr_pre_entry.empty else (float(atr.iloc[0]) if not atr.empty else 0.0)
    initial_atr_floor = buy_p - (1.5 * entry_atr)
    
    valid_df = df[df.index >= effective_buy_date].copy()
    if valid_df.empty:
        return pd.Series(dtype='float64'), pd.Series(dtype='float64'), 0.0, 0, 1.5, 40
        
    valid_atr = atr.reindex(valid_df.index)
    hist_vol = df['Close'].pct_change().tail(60).std()
    lookback_days = 15 if hist_vol >= 0.030 else (25 if hist_vol >= 0.018 else 40)
    
    ratchet_history, hard_floor_history = [], []
    milestone_levels = [buy_p * (1.30 ** i) for i in range(1, 15)]
    
    for idx, row in valid_df.iterrows():
        close_p = row['Close']
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
                    
        pnl_pct = ((close_p - active_base) / active_base) * 100
        mult = 2.5 if pnl_pct > 20.0 else (1.5 if pnl_pct < 0.0 else 2.0)
        
        history_so_far = valid_df.loc[valid_df.index <= idx].tail(lookback_days)
        history_atr = valid_atr.reindex(history_so_far.index)
        hist_pnl = ((history_so_far['Close'] - active_base) / active_base) * 100
        hist_mult = hist_pnl.apply(lambda x: 2.5 if x > 20.0 else (1.5 if x < 0.0 else 2.0))
        hist_raw_ratchets = history_so_far['Close'] - (hist_mult * history_atr)
        rolling_ratchet = hist_raw_ratchets.max()
        
        if strategy == "swing" and milestones_achieved >= 1:
            profit_lock = buy_p * (1.0 + (1.30**milestones_achieved - 1.0) / 2.0)
            running_atr = valid_atr.reindex(running_df.index)
            peak_stops = running_df['Close'].cummax() - (1.5 * running_atr)
            hard_floor = max(profit_lock, float(peak_stops.max()))
        else:
            hard_floor = initial_atr_floor
            
        candidate_ratchet = max(rolling_ratchet, hard_floor)
        final_ratchet = max(ratchet_history[-1], candidate_ratchet) if ratchet_history else candidate_ratchet
        ratchet_history.append(final_ratchet)
        hard_floor_history.append(hard_floor)
        
    return pd.Series(ratchet_history, index=valid_df.index), pd.Series(hard_floor_history, index=valid_df.index), peak_price, milestones_achieved, mult, lookback_days

def evaluate_thesis_contradictions(ticker, df, buy_date_str, buy_p, cmp, ratchet_stop, hard_floor, cushion_pct, below_days):
    """
    Evaluates Trade Thesis Contradictions, Stale Capital, and Momentum Health:
    1. Hard Capital Floor Breach
    2. Confirmed 2-Day Ratchet Breach
    3. Stale Capital / Dead Money (>10 days with <1.5% drift)
    4. Heavy Volume Distribution Day
    5. Loss of 20-Day SMA support
    """
    buy_date = pd.to_datetime(buy_date_str)
    sessions_since_buy = len(df[df.index >= buy_date])
    pnl_pct = ((cmp - buy_p) / buy_p) * 100
    
    contradictions = []
    warnings = []
    
    # 1. Hard Floor Breach
    if cmp <= hard_floor:
        contradictions.append(f"🚨 CRITICAL HARD FLOOR BREACH: CMP ₹{cmp:.2f} is at or below non-retractable floor ₹{hard_floor:.2f}.")
        
    # 2. Confirmed 2-Day Ratchet Invalidation
    if below_days >= 2:
        contradictions.append(f"🚨 CONFIRMED RATCHET FAILURE: Closed below trailing ratchet for {below_days} consecutive sessions (Cushion: {cushion_pct:.2f}%).")
    elif below_days == 1:
        warnings.append(f"⚠️ PROVISIONAL RATCHET BREACH: Day 1 close below ratchet line (Cushion: {cushion_pct:.2f}%). Watch for Day 2 confirmation.")
        
    # 3. Dead Money / Stale Momentum Clock (>=10 sessions with <1.5% progress)
    if sessions_since_buy >= 10 and pnl_pct < 1.5:
        warnings.append(f"⏳ STALE CAPITAL / DEAD MONEY: Held {sessions_since_buy} sessions with drift of {pnl_pct:+.2f}%. Momentum stalled; consider rotation.")
        
    # 4. Moving Average Trend Alignment
    sma_20 = float(df['Close'].rolling(20).mean().iloc[-1]) if len(df) >= 20 else cmp
    if cmp < sma_20:
        pct_below_sma = ((sma_20 - cmp) / sma_20) * 100
        if pct_below_sma > 2.0:
            contradictions.append(f"📉 STRUCTURAL TREND BREAK: Trading {pct_below_sma:.1f}% below 20-day SMA (₹{sma_20:.2f}).")
        else:
            warnings.append(f"⚠️ SMA TEST: Trading marginally below 20-day SMA (₹{sma_20:.2f}).")
            
    # 5. Volume Distribution Analysis (Volume > 1.3x 20-SMA on down session)
    if 'Volume' in df.columns and len(df) >= 21:
        vol_sma20 = float(df['Volume'].rolling(20).mean().iloc[-1])
        last_vol = float(df['Volume'].iloc[-1])
        yesterday_c = float(df['Close'].iloc[-2])
        if cmp < yesterday_c and vol_sma20 > 0 and (last_vol / vol_sma20) >= 1.3:
            warnings.append(f"⚠️ INSTITUTIONAL DISTRIBUTION: Last session volume was {last_vol/vol_sma20:.1f}x 20-day SMA on a red bar.")
            
    # Classification Status
    if contradictions:
        status_category = "🚨 CONTRADICTION / ACTION"
    elif warnings:
        status_category = "⚠️ AT-RISK / MONITOR"
    else:
        status_category = "🛡️ HEALTHY / COMPOUNDING"
        
    return status_category, contradictions, warnings, sessions_since_buy, sma_20

def compile_playbook_rules(closed_trades):
    """Compiles cumulative historical lessons into Obsidian-Journal/Playbook-Rules.md."""
    if not closed_trades:
        return
        
    total_trades = len(closed_trades)
    wins = [t for t in closed_trades if float(t.get('exit_price', 0)) > float(t.get('entry_price', 0))]
    losses = [t for t in closed_trades if float(t.get('exit_price', 0)) <= float(t.get('entry_price', 0))]
    
    win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0.0
    total_realized = sum((float(t.get('exit_price', 0)) - float(t.get('entry_price', 0))) * int(t.get('quantity', 0)) for t in closed_trades)
    
    gross_gains = sum((float(t.get('exit_price', 0)) - float(t.get('entry_price', 0))) * int(t.get('quantity', 0)) for t in wins)
    gross_losses = abs(sum((float(t.get('exit_price', 0)) - float(t.get('entry_price', 0))) * int(t.get('quantity', 0)) for t in losses))
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else 99.9
    
    playbook_file = os.path.join(OBSIDIAN_DIR, "Playbook-Rules.md")
    
    lines = [
        "# 📘 KRONOS Quantitative Playbook: Evergreen Execution Rules",
        f"**Compiled:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"**Authoritative Ledger:** Based on `{total_trades} Closed Historical Transactions` (`Ratchet-System/closed_trades.json`)\n",
        "## 📊 1. Core Mathematical Metrics",
        f"- **Total Closed Trades:** `{total_trades}`",
        f"- **Win Rate:** `{win_rate:.1f}%` ({len(wins)} Wins / {len(losses)} Losses)",
        f"- **Total Realized Capital P&L:** **+₹{total_realized:,.2f}**",
        f"- **Profit Factor:** `{profit_factor:.2f}` (Gross Gains: ₹{gross_gains:,.2f} | Losses: ₹{gross_losses:,.2f})\n",
        "---",
        "## 🛡️ 2. Core Execution Invariants (Derived from Postmortems)",
        "### Invariant A: The 2-Day Consecutive Close Ratchet Rule",
        "- **Context:** Derived from noise whipsaws in `HFCL` and `SYRMA` (2026-07-27).",
        "- **Rule:** A trailing stop ratchet exit requires **two consecutive daily closes** below the ratchet line before executing liquidation.",
        "- **Exception:** If price breaches the **Hard Capital Shield Floor (Initial 1.5 ATR Floor)**, liquidation is immediate on Day 1.",
        "",
        "### Invariant B: Emergency Promoter & Block Deal Liquidation",
        "- **Context:** Validated by `WELCORP` exit @ ₹2,217 on 2026-08-26 (+57.68% gain saved) when promoters offloaded via bulk deals.",
        "- **Rule:** If sudden promoter offloading or structural negative corporate actions occur with >5% intraday drop, liquidate immediately regardless of ratchet distance.",
        "",
        "### Invariant C: Milestone-Based Profit Lock-in (+30% Rule)",
        "- **Context:** Validated by `ATHERENERG` (+72.11%) and `LAURUSLABS` (+32.87%).",
        "- **Rule:** Once peak price reaches +30% from cost basis, Hard Floor is immediately ratcheted to lock in half the gains (Cost + 15%), and trailing stop switches to 1.5x tight ATR from peak.",
        "",
        "### Invariant D: Dead-Money & Stale Capital Rotation Clock",
        "- **Context:** Derived from `EXIDEIND` and `CHOICEIN` postmortems.",
        "- **Rule:** If a swing setup spends >= 10 trading sessions with < 1.5% net drift from entry cost, flag for systematic capital reallocation into top-ranked Outperformer scanner setups.",
        "",
        "---",
        "## 📜 3. Historical Exit Reasons Breakdown",
        "| Ticker | Entry Date | Exit Date | Qty | Realized P&L | Realized % | Qualitative System Exit Reason |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
    ]
    
    for t in reversed(closed_trades[-12:]):
        entry_p = float(t.get('entry_price', 0))
        exit_p = float(t.get('exit_price', 0))
        qty = int(t.get('quantity', 0))
        pnl = (exit_p - entry_p) * qty
        pct = ((exit_p - entry_p) / entry_p) * 100 if entry_p > 0 else 0.0
        pct_str = f"**+{pct:.1f}%**" if pct >= 0 else f"*{pct:.1f}%*"
        pnl_str = f"+₹{pnl:,.2f}" if pnl >= 0 else f"-₹{abs(pnl):,.2f}"
        lines.append(f"| **{t.get('ticker','').replace('.NS','')}** | {t.get('entry_date')} | {t.get('exit_date')} | {qty} | {pnl_str} | {pct_str} | {t.get('reason','')} |")
        
    with open(playbook_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[SUCCESS] Compiled Playbook Rules saved: {playbook_file}")

def compile_individual_dossiers(metrics_list, scanner_origins):
    """Compiles and updates evergreen atomic ticker dossiers in Obsidian-Journal/Ticker-Research/<TICKER>.md."""
    for m in metrics_list:
        clean_t = m['clean_ticker']
        ticker_file = os.path.join(TICKER_RESEARCH_DIR, f"{clean_t}.md")
        
        # Read existing content to preserve historical scanner flags
        existing_notes = []
        if os.path.exists(ticker_file):
            try:
                with open(ticker_file, "r", encoding="utf-8") as ef:
                    in_scanner_section = False
                    for line in ef:
                        if "## 📡 Scanner Confluence History" in line:
                            in_scanner_section = True
                            continue
                        if in_scanner_section:
                            if line.startswith("#"):
                                in_scanner_section = False
                            elif line.strip().startswith("- [["):
                                existing_notes.append(line.strip())
            except Exception:
                pass
                
        # Build refreshed compiled dossier
        lines = [
            f"# 🔍 Compiled Ticker Dossier: [[{clean_t}]]",
            f"- **Symbol:** `{clean_t}`",
            f"- **Full Instrument:** `{m['ticker']}`",
            f"- **Sector:** *{m['sector']}*",
            f"- **Compiler Timestamp:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- **Originating Scanners:** {scanner_origins.get(m['ticker'], '[[Outperformer Pipeline]], [[Dynamic-Confluence]]')}",
            "",
            "## 💼 1. Live Position & Risk Status",
            "| Metric | Value | System Assessment |",
            "| :--- | :---: | :--- |",
            f"| **Current Market Price (CMP)** | **₹{m['cmp']:,.2f}** | Session change: {m['chg_pct']:+.2f}% |",
            f"| **Average Cost Basis** | ₹{m['buy_p']:,.2f} | Purchased on [[{m['buy_date']}]] |",
            f"| **Position Quantity** | `{m['qty']} Shares` | Invested Capital: ₹{m['cost_val']:,.2f} |",
            f"| **Current Market Value** | **₹{m['curr_val']:,.2f}** | Total Weight: {m['weight_pct']:.2f}% |",
            f"| **Unrealized P&L** | **{m['pnl_val']:+,.2f} ({m['pnl_pct']:+.2f}%)** | {'🔥 Profitable' if m['pnl_pct'] >= 0 else '⚠️ In Drawdown'} |",
            f"| **Active Ratchet Stop** | **₹{m['r_val']:,.2f}** | Trailing Cushion: **{m['cushion_pct']:+.2f}%** |",
            f"| **Hard Capital Shield Floor** | **₹{m['f_val']:,.2f}** | Non-retractable safety boundary |",
            f"| **Closes Below Ratchet** | `{m['below_days']} Sessions` | {'🚨 Confirm Exit' if m['below_days']>=2 else ('⚠️ Watch' if m['below_days']==1 else '✅ Above Ratchet')} |",
            f"| **Holding Tenure** | `{m['tenure_days']} Sessions` | {'⏳ Stale Capital' if (m['tenure_days']>=10 and m['pnl_pct']<1.5) else '🚀 Normal Active'} |",
            "",
            "## 🛡️ 2. Thesis Health & Contradiction Radar",
            f"- **Overall Status:** **{m['status_category']}**",
        ]
        
        if m['contradictions']:
            lines.append("### 🚨 Detected Contradictions:")
            for c in m['contradictions']:
                lines.append(f"- {c}")
        if m['warnings']:
            lines.append("### ⚠️ Active Watchdog Warnings:")
            for w in m['warnings']:
                lines.append(f"- {w}")
        if not m['contradictions'] and not m['warnings']:
            lines.append("- ✅ **Zero Contradictions:** Momentum structure, volume participation, and trailing ratchets remain fully aligned.")
            
        lines.extend([
            "",
            "## 📊 3. Quantitative Indicator Signature",
            f"- **14-Day ATR:** ₹{m['atr14']:.2f} ({m['atr14']/m['cmp']*100:.2f}% of price)",
            f"- **20-Day SMA Support:** ₹{m['sma20']:.2f} ({((m['cmp']-m['sma20'])/m['sma20'])*100:+.2f}% vs SMA)",
            f"- **60-Day Alpha vs Nifty 50:** {m['alpha_60d']:+.2f}%",
            f"- **Active Lookback Window:** `{m['lookback']} Days` | Multiplier: `{m['mult']}x`",
            "",
            "## 🎯 4. Strategic Next Action Directive",
            f"- **Action:** **{m['action_directive']}**",
            f"- **Plan:** {m['action_notes']}",
            "",
            "## 📡 Scanner Confluence History"
        ])
        
        # Re-append preserved notes (avoid duplicates and double dashes)
        today_stamp = datetime.date.today().strftime('%Y-%m-%d')
        seen_notes = set()
        clean_existing = []
        for note in existing_notes:
            cleaned = note.lstrip("- ").strip()
            if cleaned and cleaned not in seen_notes:
                seen_notes.add(cleaned)
                clean_existing.append(cleaned)
                
        today_entry = f"[[{today_stamp}]]: Compiled audit: Status {m['status_category']}, Cushion {m['cushion_pct']:+.2f}%, PnL {m['pnl_pct']:+.2f}%"
        
        if not clean_existing:
            init_entry = f"[[{m['buy_date']}]]: Position initiated @ ₹{m['buy_p']:,.2f} via {scanner_origins.get(m['ticker'], '[[Outperformer Pipeline]]')}"
            lines.append(f"- {init_entry}")
            lines.append(f"- {today_entry}")
        else:
            filtered = [n for n in clean_existing if not n.startswith(f"[[{today_stamp}]]: Compiled audit")]
            for n in filtered:
                lines.append(f"- {n}")
            lines.append(f"- {today_entry}")
        
        with open(ticker_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
    print(f"[SUCCESS] Compiled {len(metrics_list)} atomic ticker dossiers in Obsidian Vault.")

def run_compiler():
    print(f"\n========================================================")
    print(f"🧠 KRONOS KNOWLEDGE COMPILER: COMPILING TRADING ENGINE")
    print(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"========================================================\n")
    
    # 1. Load Data Layers
    holdings = load_live_portfolio()
    closed_trades = load_closed_trades()
    scanner_origins = load_scanner_origins()
    
    tickers = list(holdings.keys())
    print(f"[1/5] Ingesting market series for {len(tickers)} active holdings + Nifty 50...")
    
    # 2. Download Market Data
    fetch_list = tickers + ["^NSEI"]
    try:
        data = yf.download(fetch_list, period="2y", interval="1d", progress=False, auto_adjust=True)
    except Exception as e:
        print(f"[WARNING] Bulk download failed: {e}")
        data = pd.DataFrame()
        
    nifty_close = pd.Series(dtype='float64')
    if not data.empty and ('Close', '^NSEI') in data.columns:
        nifty_close = data['Close']['^NSEI'].dropna()
    else:
        nifty_close = yf.Ticker('^NSEI').history(period="2y", auto_adjust=True)['Close'].dropna()
        
    nifty_perf_60d = (nifty_close.iloc[-1] - nifty_close.iloc[-60]) / nifty_close.iloc[-60] if len(nifty_close) >= 60 else 0.0
    
    # 3. Calculate Multi-Factor Health
    print(f"[2/5] Running Thesis Contradiction & Ratchet Analysis...")
    metrics_list = []
    total_val = 0.0
    total_cost = 0.0
    
    for t, info in holdings.items():
        qty = info['quantity']
        buy_p = info['avg_cost']
        buy_date = info['buy_date']
        sector = info['sector']
        strategy = info.get('strategy', 'swing')
        
        df = pd.Series(dtype='float64')
        if not data.empty and ('Close', t) in data.columns:
            df_full = data.xs(t, axis=1, level=1).dropna()
        else:
            df_full = yf.Ticker(t).history(period="2y", auto_adjust=True)
            
        if df_full.empty:
            continue
            
        cmp = float(df_full['Close'].iloc[-1])
        yesterday_c = float(df_full['Close'].iloc[-2]) if len(df_full) >= 2 else cmp
        chg_pct = ((cmp - yesterday_c) / yesterday_c) * 100
        cost_val = qty * buy_p
        curr_val = qty * cmp
        pnl_val = curr_val - cost_val
        pnl_pct = (pnl_val / cost_val) * 100
        total_val += curr_val
        total_cost += cost_val
        
        ratchet_s, floor_s, peak_p, milestones, mult, lookback = compute_historical_ratchet(df_full, buy_date, buy_p, strategy)
        r_val = float(ratchet_s.iloc[-1]) if not ratchet_s.empty else (buy_p * 0.90)
        f_val = float(floor_s.iloc[-1]) if not floor_s.empty else (buy_p * 0.90)
        cushion_pct = ((cmp - r_val) / cmp) * 100 if cmp > 0 else 0.0
        
        tr = pd.concat([df_full['High'] - df_full['Low'], (df_full['High'] - df_full['Close'].shift(1)).abs(), (df_full['Low'] - df_full['Close'].shift(1)).abs()], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
        
        below_days = 0
        if not ratchet_s.empty:
            for i in range(1, min(len(ratchet_s) + 1, 10)):
                if df_full.loc[ratchet_s.index, 'Close'].iloc[-i] <= ratchet_s.iloc[-i]:
                    below_days += 1
                else:
                    break
                    
        # 60D Alpha vs Nifty 50
        stock_perf_60d = (cmp - float(df_full['Close'].iloc[-60])) / float(df_full['Close'].iloc[-60]) if len(df_full) >= 60 else 0.0
        alpha_60d = (stock_perf_60d - nifty_perf_60d) * 100
        
        status_cat, contradictions, warnings, tenure_days, sma20 = evaluate_thesis_contradictions(
            t, df_full, buy_date, buy_p, cmp, r_val, f_val, cushion_pct, below_days
        )
        
        # Determine actionable directive
        if cmp <= f_val or below_days >= 2:
            action_dir = "🚨 EXECUTE SYSTEMATIC EXIT"
            action_notes = f"Breached risk threshold ({below_days} closes below ratchet or below Hard Floor). Liquidate on Monday open to safeguard capital."
        elif below_days == 1:
            action_dir = "⚠️ 2-DAY CONFIRMATION MONITOR"
            action_notes = "Day 1 breach. If price does not reclaim ratchet stop by Monday close, execute liquidation."
        elif tenure_days >= 10 and pnl_pct < 1.5:
            action_dir = "⏳ STALE MOMENTUM ROTATION"
            action_notes = "Capital stalled. Consider reallocating to top Outperformer scanner picks if breakout does not emerge within 2 sessions."
        elif cushion_pct < 3.0:
            action_dir = "⚠️ TIGHT MONITORING"
            action_notes = "Operating in compressed volatility band (<3% cushion). Keep ratchet active; do not widen stops."
        else:
            action_dir = "🛡️ HOLD & COMPOUND"
            action_notes = "Healthy buffer (>3% cushion). Trail ratchet upward as price expands."
            
        metrics_list.append({
            'ticker': t,
            'clean_ticker': t.replace('.NS', ''),
            'sector': sector,
            'qty': qty,
            'buy_p': buy_p,
            'buy_date': buy_date,
            'cmp': cmp,
            'chg_pct': chg_pct,
            'cost_val': cost_val,
            'curr_val': curr_val,
            'pnl_val': pnl_val,
            'pnl_pct': pnl_pct,
            'r_val': r_val,
            'f_val': f_val,
            'cushion_pct': cushion_pct,
            'below_days': below_days,
            'atr14': atr14,
            'sma20': sma20,
            'alpha_60d': alpha_60d,
            'lookback': lookback,
            'mult': mult,
            'tenure_days': tenure_days,
            'status_category': status_cat,
            'contradictions': contradictions,
            'warnings': warnings,
            'action_directive': action_dir,
            'action_notes': action_notes
        })
        
    for m in metrics_list:
        m['weight_pct'] = (m['curr_val'] / total_val * 100) if total_val > 0 else 0.0
        
    # 4. Compile Playbook & Dossiers
    print(f"[3/5] Compiling Cumulative Playbook Rules from {len(closed_trades)} historical exits...")
    compile_playbook_rules(closed_trades)
    
    print(f"[4/5] Compiling Atomic Ticker Dossiers for {len(metrics_list)} active holdings...")
    compile_individual_dossiers(metrics_list, scanner_origins)
    
    # 5. Compile Master Brain Synthesis Brief
    print(f"[5/5] Generating Master Compiled Synthesis Report...")
    report_file = os.path.join(TICKER_RESEARCH_DIR, "Compiled-Trading-Brain-Brief.md")
    audit_file = os.path.join(BASE_DIR, f"compiled_trading_brain_audit_report_{datetime.date.today().strftime('%Y%m%d')}.md")
    
    contradiction_items = [m for m in metrics_list if "CONTRADICTION" in m['status_category']]
    stale_items = [m for m in metrics_list if "STALE" in m['action_directive']]
    healthy_items = [m for m in metrics_list if "HOLD" in m['action_directive']]
    
    lines = [
        "# 🧠 KRONOS Compiled Trading Brain: Synthesis Brief",
        f"**Date:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"**Engine Architecture:** Compiled Knowledge Graph (Ingestion $\\rightarrow$ Synthesis $\\rightarrow$ Living Dossiers)",
        f"**Benchmark (Nifty 50 60D):** `{nifty_perf_60d*100:+.2f}%`\n",
        "---",
        "## 📈 Executive Portfolio Snapshot",
        f"- **Active Holdings Count:** `{len(metrics_list)} Positions`",
        f"- **Total Invested Capital:** `₹{total_cost:,.2f}`",
        f"- **Current Portfolio Value:** `₹{total_val:,.2f}` (**{total_val - total_cost:+,.2f} / {((total_val-total_cost)/total_cost)*100:+.2f}%**)",
        f"- **Liquid Cash Reserve:** `₹1,51,005.00` | **Total NAV:** `₹{total_val + 151005:,.2f}`\n",
        "---",
        "## 🚨 1. Trade Thesis Contradictions & Action Required",
    ]
    
    if contradiction_items:
        lines.append("| Ticker | CMP | Cost | Unrealized P&L | Ratchet | Hard Floor | Below (Days) | Contradiction Diagnosis | Action Directive |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |")
        for c in contradiction_items:
            diag = "<br>".join(c['contradictions'] + c['warnings'])
            lines.append(f"| **[[{c['clean_ticker']}]]** | ₹{c['cmp']:,.2f} | ₹{c['buy_p']:,.2f} | {c['pnl_val']:+,.2f} ({c['pnl_pct']:+.2f}%) | ₹{c['r_val']:,.2f} | ₹{c['f_val']:,.2f} | `{c['below_days']}` | {diag} | **{c['action_directive']}** |")
    else:
        lines.append("✅ **Zero Active Contradictions Detected.** All open positions conform to their underlying technical breakout thesis.")
        
    lines.extend([
        "",
        "---",
        "## ⏳ 2. Stale Capital & Dead-Money Watchlist (>10 Sessions / <1.5% Drift)",
    ])
    
    if stale_items:
        lines.append("| Ticker | Tenure | Entry Date | Cost Basis | CMP | Drift P&L | 60D Alpha vs Nifty | Action Recommendation |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
        for s in stale_items:
            lines.append(f"| **[[{s['clean_ticker']}]]** | `{s['tenure_days']} Days` | {s['buy_date']} | ₹{s['buy_p']:,.2f} | ₹{s['cmp']:,.2f} | {s['pnl_pct']:+.2f}% | {s['alpha_60d']:+.2f}% | Stalled velocity. Prepare rotation into top Outperformer scan setup. |")
    else:
        lines.append("✅ **Zero Stale Capital.** All positions are actively demonstrating directional expansion or are newly initiated.")
        
    lines.extend([
        "",
        "---",
        "## 📋 3. Complete Active Holdings Health Grid",
        "| Ticker | Sector | Qty | CMP (₹) | Avg Cost (₹) | Value (₹) | P&L (%) | Cushion (%) | Status Category | Next Action |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |"
    ])
    
    sorted_metrics = sorted(metrics_list, key=lambda x: x['cushion_pct'])
    for m in sorted_metrics:
        lines.append(f"| **[[{m['clean_ticker']}]]** | {m['sector']} | {m['qty']} | ₹{m['cmp']:,.2f} | ₹{m['buy_p']:,.2f} | ₹{m['curr_val']:,.2f} | {m['pnl_pct']:+.2f}% | **{m['cushion_pct']:+.2f}%** | {m['status_category']} | {m['action_directive']} |")
        
    report_content = "\n".join(lines)
    
    for target in [report_file, audit_file]:
        with open(target, "w", encoding="utf-8") as f:
            f.write(report_content)
    print(f"[SUCCESS] Synthesis reports written to:\n  - {report_file}\n  - {audit_file}")
    
    # 6. Telegram Morning Dispatch
    tele_msg = f"🧠 *KRONOS Compiled Trading Brain:* {datetime.date.today().strftime('%d-%b-%Y')}\n"
    tele_msg += f"NAV: ₹{(total_val + 151005)/100000:.2f}L | Open P&L: {((total_val-total_cost)/total_cost)*100:+.2f}%\n"
    tele_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if contradiction_items:
        tele_msg += "🚨 *CRITICAL CONTRADICTIONS / EXITS:*\n"
        for c in contradiction_items:
            tele_msg += f"• *{c['clean_ticker']}*: CMP ₹{c['cmp']:.1f} ({c['pnl_pct']:+.1f}%) | Below Ratchet: {c['below_days']}d | {c['action_directive']}\n"
        tele_msg += "\n"
        
    if stale_items:
        tele_msg += "⏳ *STALE CAPITAL / DEAD MONEY:*\n"
        for s in stale_items:
            tele_msg += f"• *{s['clean_ticker']}*: Tenure {s['tenure_days']}d | Drift {s['pnl_pct']:+.1f}% | Flag: Opportunity Cost\n"
        tele_msg += "\n"
        
    top_leaders = [m for m in sorted(metrics_list, key=lambda x: x['alpha_60d'], reverse=True) if m['alpha_60d'] > 20][:3]
    if top_leaders:
        tele_msg += "🔥 *TOP ALPHA LEADERS:*\n"
        for l in top_leaders:
            tele_msg += f"• *{l['clean_ticker']}*: Cushion {l['cushion_pct']:+.1f}% | 60D Alpha +{l['alpha_60d']:.1f}%\n"
        tele_msg += "\n"
        
    tele_msg += "👉 Check Obsidian: `Compiled-Trading-Brain-Brief.md` & `Playbook-Rules.md`"
    send_telegram_alert(tele_msg)
    
    print("\n========================================================")
    print("✅ COMPILATION COMPLETE: Vault, Playbook & Dossiers Synced!")
    print("========================================================\n")

if __name__ == "__main__":
    run_compiler()
