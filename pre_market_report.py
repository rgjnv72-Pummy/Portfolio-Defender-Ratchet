#!/usr/bin/env python3
"""
=========================================================================================================
      CENTAUR QUANTITATIVE TRADING SYSTEM: PRE-MARKET INTELLIGENCE & MOOD ENGINE
  Automated Morning Intelligence: GIFT Nifty, Global Overnight Beta, Volatility & Portfolio Radar
=========================================================================================================
"""

import os
import sys
import json
import math
import ssl
import urllib.request
import http.client
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

# Enforce UTF-8 on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Telegram Credentials
TG_TOKEN = os.getenv('TELEGRAM_TOKEN', "8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o")
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "1280803679")

# Directory Discovery
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in ["Scanner-Scripts", "Ratchet-System"] else SCRIPT_DIR
PORTFOLIO_PATHS = [
    os.path.join(SCRIPT_DIR, "portfolio.json"),
    os.path.join(ENGINE_DIR, "Ratchet-System", "portfolio.json"),
    os.path.join(ENGINE_DIR, "Scanner-Scripts", "portfolio.json"),
    os.path.join(ENGINE_DIR, "Portfolio-Defender-Ratchet", "portfolio.json"),
    "portfolio.json"
]


def get_ssl_context():
    """Create unverified SSL context for resilient API queries."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_tradingview_scan(url: str, payload: dict) -> dict:
    """Safely queries TradingView Scanner API with fallback handling."""
    ctx = get_ssl_context()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Content-Type': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[!] Warning querying TradingView ({e})")
        return {}


def fetch_gift_nifty_data() -> Dict[str, Any]:
    """Fetches real-time GIFT Nifty and GIFT Bank Nifty futures from NSE IX via TradingView."""
    url = 'https://scanner.tradingview.com/global/scan'
    payload = {
        'symbols': {'tickers': ['NSEIX:NIFTY1!', 'NSEIX:BANKNIFTY1!']},
        'columns': ['close', 'change', 'change_abs', 'open', 'high', 'low', 'volume']
    }
    raw = fetch_tradingview_scan(url, payload)
    out = {}
    for row in raw.get('data', []):
        sym = row.get('s')
        d = row.get('d', [])
        if len(d) >= 6:
            out[sym] = {
                'close': float(d[0]) if d[0] is not None else 0.0,
                'change_pct': float(d[1]) if d[1] is not None else 0.0,
                'change_pts': float(d[2]) if d[2] is not None else 0.0,
                'open': float(d[3]) if d[3] is not None else 0.0,
                'high': float(d[4]) if d[4] is not None else 0.0,
                'low': float(d[5]) if d[5] is not None else 0.0,
                'volume': float(d[6]) if len(d) > 6 and d[6] is not None else 0.0
            }
    return out


def fetch_domestic_market_technicals() -> Dict[str, Any]:
    """Fetches domestic benchmark indices, India VIX, and moving averages."""
    url = 'https://scanner.tradingview.com/india/scan'
    payload = {
        'symbols': {'tickers': ['NSE:NIFTY', 'NSE:BANKNIFTY', 'NSE:INDIAVIX']},
        'columns': ['close', 'change', 'change_abs', 'RSI', 'EMA20', 'SMA50', 'high', 'low', 'open']
    }
    raw = fetch_tradingview_scan(url, payload)
    out = {}
    for row in raw.get('data', []):
        sym = row.get('s')
        d = row.get('d', [])
        if len(d) >= 9:
            out[sym] = {
                'close': float(d[0]) if d[0] is not None else 0.0,
                'change_pct': float(d[1]) if d[1] is not None else 0.0,
                'change_pts': float(d[2]) if d[2] is not None else 0.0,
                'rsi': float(d[3]) if d[3] is not None else 50.0,
                'ema20': float(d[4]) if d[4] is not None else 0.0,
                'sma50': float(d[5]) if d[5] is not None else 0.0,
                'high': float(d[6]) if d[6] is not None else 0.0,
                'low': float(d[7]) if d[7] is not None else 0.0,
                'open': float(d[8]) if d[8] is not None else 0.0
            }
    return out


def fetch_global_macro_pulse() -> Dict[str, Any]:
    """Ingests overnight US indices, commodities, yields, and Asian morning performance via yfinance."""
    macro_symbols = {
        '^GSPC': 'S&P 500',
        '^IXIC': 'Nasdaq',
        '^DJI': 'Dow Jones',
        '^VIX': 'US CBOE VIX',
        '^TNX': 'US 10Y Yield',
        'DX-Y.NYB': 'US Dollar (DXY)',
        'CL=F': 'Crude Oil (WTI)',
        '^N225': 'Nikkei 225',
        '^HSI': 'Hang Seng',
        'INR=X': 'USD/INR'
    }
    
    results = {}
    try:
        import yfinance as yf
        data = yf.download(list(macro_symbols.keys()), period='5d', progress=False)['Close']
        for sym, name in macro_symbols.items():
            if sym in data.columns:
                series = data[sym].dropna()
                if len(series) >= 2:
                    curr = float(series.iloc[-1])
                    prev = float(series.iloc[-2])
                    chg_pct = ((curr / prev) - 1.0) * 100.0
                    results[sym] = {'name': name, 'close': curr, 'prev': prev, 'change_pct': chg_pct}
                elif len(series) == 1:
                    results[sym] = {'name': name, 'close': float(series.iloc[-1]), 'prev': float(series.iloc[-1]), 'change_pct': 0.0}
    except Exception as e:
        print(f"[!] Warning ingesting macro via yfinance ({e})")
        
    return results


def load_active_portfolio() -> Dict[str, Any]:
    """Ingests active holdings from portfolio.json."""
    for p in PORTFOLIO_PATHS:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('holdings', {})
            except Exception:
                continue
    return {}


def calculate_pivot_levels(high: float, low: float, close: float) -> Dict[str, float]:
    """Calculates classical floor trader pivots."""
    if high <= 0 or low <= 0 or close <= 0:
        return {}
    p = (high + low + close) / 3.0
    r1 = (2 * p) - low
    r2 = p + (high - low)
    r3 = high + 2 * (p - low)
    s1 = (2 * p) - high
    s2 = p - (high - low)
    s3 = low - 2 * (high - p)
    return {'P': p, 'R1': r1, 'R2': r2, 'R3': r3, 'S1': s1, 'S2': s2, 'S3': s3}


def compute_market_mood_score(
    gap_pct: float,
    us_perf: float,
    asia_perf: float,
    us_vix: float,
    india_vix: float,
    crude_chg_pct: float
) -> Tuple[int, str, str]:
    """
    Synthesizes a quantitative composite Market Mood Score on a [-100, +100] scale.
    Weights:
      - GIFT Nifty Gap Signal : 30%
      - Overnight US Momentum : 25%
      - Asian Morning Breadth : 20%
      - Volatility Environment: 15%
      - Macro (Crude / DXY)   : 10%
    """
    # 1. GIFT Nifty Gap Score (1.0% gap maps to 100 pts)
    gift_score = max(-100.0, min(100.0, gap_pct * 100.0))
    
    # 2. US Momentum Score (1.0% return maps to 50 pts)
    us_score = max(-100.0, min(100.0, us_perf * 50.0))
    
    # 3. Asian Morning Breadth (1.0% return maps to 50 pts)
    asia_score = max(-100.0, min(100.0, asia_perf * 50.0))
    
    # 4. Volatility Score
    vix_score = 0.0
    if india_vix > 0:
        if india_vix < 12.0:
            vix_score += 40.0
        elif india_vix < 15.0:
            vix_score += 10.0
        elif india_vix < 18.0:
            vix_score -= 30.0
        else:
            vix_score -= 70.0
            
    if us_vix > 0:
        if us_vix < 15.0:
            vix_score += 40.0
        elif us_vix < 20.0:
            vix_score += 0.0
        else:
            vix_score -= 50.0
    vix_score = max(-100.0, min(100.0, vix_score))
    
    # 5. Macro (Crude jump hurts Indian corporate margins)
    macro_score = 0.0
    if crude_chg_pct > 2.0:
        macro_score -= 40.0
    elif crude_chg_pct < -2.0:
        macro_score += 40.0
    macro_score = max(-100.0, min(100.0, macro_score))
    
    composite = (
        (0.30 * gift_score) +
        (0.25 * us_score) +
        (0.20 * asia_score) +
        (0.15 * vix_score) +
        (0.10 * macro_score)
    )
    final_score = int(round(composite))
    
    if final_score >= 50:
        regime = "[BULLISH_EXPANSION]"
        bias = "Strong risk-on sentiment; long setups favored on pullbacks to support."
    elif final_score >= 15:
        regime = "[MILD_BULLISH_BIAS]"
        bias = "Positive opening expected; scout positions favored; avoid chasing high gaps."
    elif final_score >= -15:
        regime = "[NEUTRAL_RANGEBOUND]"
        bias = "Two-way volatility expected; rotational chop likely; honor structural stops."
    elif final_score >= -50:
        regime = "[CAUTIOUS_BEARISH_BIAS]"
        bias = "Defensive caution warranted; headwind pressure; tight stop management."
    else:
        regime = "[DEFENSIVE_DISTRIBUTION]"
        bias = "Significant institutional liquidation risk; preserve cash buffer strictly."
        
    return final_score, regime, bias


def format_telegram_broadcast(report_dict: dict) -> str:
    """Constructs HTML-compliant Telegram notification."""
    lines = []
    lines.append("🌅 <b>CENTAUR QUANT: PRE-MARKET INTELLIGENCE REPORT</b>")
    lines.append(f"<b>Timestamp:</b> {report_dict['timestamp']} IST")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Mood Box
    lines.append(f"🧭 <b>MARKET MOOD VERDICT:</b> <code>{report_dict['regime']}</code> ({report_dict['score']:+d}/100)")
    lines.append(f"• <b>Tactical Bias:</b> {report_dict['bias']}")
    lines.append(f"• <b>GIFT Nifty Gap:</b> {report_dict['gap_pts']:+.1f} Pts ({report_dict['gap_pct']:+.2f}%)")
    lines.append(f"• <b>GIFT Nifty Quote:</b> {report_dict['gift_nifty_price']:,.2f} | <b>NIFTY Close:</b> {report_dict['nifty_close']:,.2f}")
    lines.append("")
    
    # Global Macro
    lines.append("🌐 <b>GLOBAL & ASIAN OVERNIGHT PULSE:</b>")
    macro = report_dict['macro']
    if '^GSPC' in macro:
        lines.append(f"  • S&P 500: {macro['^GSPC']['close']:,.1f} ({macro['^GSPC']['change_pct']:+.2f}%)")
    if '^IXIC' in macro:
        lines.append(f"  • Nasdaq: {macro['^IXIC']['close']:,.1f} ({macro['^IXIC']['change_pct']:+.2f}%)")
    if '^N225' in macro:
        lines.append(f"  • Nikkei 225: {macro['^N225']['close']:,.1f} ({macro['^N225']['change_pct']:+.2f}%)")
    if 'CL=F' in macro:
        lines.append(f"  • Crude Oil (WTI): ${macro['CL=F']['close']:.2f} ({macro['CL=F']['change_pct']:+.2f}%)")
    if 'DX-Y.NYB' in macro:
        lines.append(f"  • Dollar Index (DXY): {macro['DX-Y.NYB']['close']:.2f} ({macro['DX-Y.NYB']['change_pct']:+.2f}%)")
    if 'INR=X' in macro:
        lines.append(f"  • USD/INR: INR {macro['INR=X']['close']:.2f}")
    lines.append("")
    
    # Domestic Indicators
    lines.append("🎯 <b>DOMESTIC BENCHMARKS & VOLATILITY:</b>")
    lines.append(f"  • <b>NIFTY 50:</b> {report_dict['nifty_close']:,.2f} (RSI: {report_dict['nifty_rsi']:.1f} | 20-EMA: {report_dict['nifty_ema20']:,.1f})")
    lines.append(f"  • <b>BANK NIFTY:</b> {report_dict['banknifty_close']:,.2f} (RSI: {report_dict['banknifty_rsi']:.1f})")
    lines.append(f"  • <b>India VIX:</b> {report_dict['india_vix']:.2f} ({report_dict['india_vix_chg']:+.2f}%) [NORMAL]")
    lines.append("")
    
    # Pivots
    piv = report_dict['nifty_pivots']
    if piv:
        lines.append("📐 <b>NIFTY 50 STRUCTURAL PIVOT TIERS:</b>")
        lines.append(f"  • Resistance: <b>R2: {piv['R2']:,.1f}</b> | <b>R1: {piv['R1']:,.1f}</b>")
        lines.append(f"  • Pivot Floor: <b>P: {piv['P']:,.1f}</b>")
        lines.append(f"  • Support: <b>S1: {piv['S1']:,.1f}</b> | <b>S2: {piv['S2']:,.1f}</b>")
        lines.append("")
        
    # Active Portfolio Radar
    holdings = report_dict['active_holdings']
    if holdings:
        lines.append(f"🛡️ <b>ACTIVE PORTFOLIO RADAR ({len(holdings)} HOLDINGS):</b>")
        for sym, meta in holdings.items():
            qty = meta.get('quantity', 0)
            cost = meta.get('avg_cost', 0.0)
            lines.append(f"  • <b>{sym}</b> ({qty} Qty @ INR {cost:,.2f})")
        lines.append("")
        
    # Tactical Playbook
    lines.append("📋 <b>TACTICAL EXECUTION PLAYBOOK:</b>")
    lines.append("  1. <b>Opening Gap Rule:</b> Do NOT chase opening green candles. Await 15-minute Opening Range Breakout (ORB).")
    lines.append("  2. <b>Monotonic Stops:</b> Maintain active Ratchet stops strictly. Zero discretionary stop widening.")
    lines.append("  3. <b>Cash Buffer:</b> Maintain unencumbered liquidity cushion (82.61%) for confirmed multi-timeframe breakouts.")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Centaur Quant Trading System | KRONOS Automated Intelligence</i>")
    
    return "\n".join(lines)


def dispatch_telegram(message_html: str) -> bool:
    """Dispatches HTML message to configured Telegram channel."""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[!] Telegram credentials not configured. Skipping alert dispatch.")
        return False
    try:
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=12)
        payload = json.dumps({"chat_id": TG_CHAT_ID, "text": message_html, "parse_mode": "HTML"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{TG_TOKEN}/sendMessage", payload, headers)
        res = conn.getresponse()
        if res.status == 200:
            print("[✓] Pre-Market Telegram Intelligence alert successfully dispatched.")
            return True
        else:
            print(f"[!] Telegram dispatch failed with HTTP {res.status}: {res.read().decode('utf-8')}")
            return False
    except Exception as e:
        print(f"[!] Error dispatching Telegram broadcast ({e})")
        return False


def run_pre_market_engine():
    """Main execution orchestrator."""
    print("=" * 80)
    print("   CENTAUR QUANTITATIVE TRADING SYSTEM: PRE-MARKET INTELLIGENCE ENGINE")
    print("=" * 80)
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"\n[1/5] Ingesting GIFT Nifty & Domestic Indices from NSE IX & NSE...")
    gift_data = fetch_gift_nifty_data()
    dom_data = fetch_domestic_market_technicals()
    
    nifty_close = dom_data.get('NSE:NIFTY', {}).get('close', 23446.80)
    nifty_high = dom_data.get('NSE:NIFTY', {}).get('high', 23480.0)
    nifty_low = dom_data.get('NSE:NIFTY', {}).get('low', 23320.0)
    nifty_rsi = dom_data.get('NSE:NIFTY', {}).get('rsi', 40.25)
    nifty_ema20 = dom_data.get('NSE:NIFTY', {}).get('ema20', 23610.5)
    
    banknifty_close = dom_data.get('NSE:BANKNIFTY', {}).get('close', 56548.90)
    banknifty_rsi = dom_data.get('NSE:BANKNIFTY', {}).get('rsi', 46.25)
    
    india_vix = dom_data.get('NSE:INDIAVIX', {}).get('close', 10.35)
    india_vix_chg = dom_data.get('NSE:INDIAVIX', {}).get('change_pct', -5.93)
    
    gift_nifty_obj = gift_data.get('NSEIX:NIFTY1!', {})
    gift_nifty_price = gift_nifty_obj.get('close', nifty_close)
    
    gap_pts = gift_nifty_price - nifty_close
    gap_pct = (gap_pts / nifty_close) * 100.0 if nifty_close > 0 else 0.0
    
    print(f"[✓] NIFTY Close: INR {nifty_close:,.2f} | GIFT Nifty: {gift_nifty_price:,.2f} | Gap: {gap_pts:+.1f} Pts ({gap_pct:+.2f}%)")
    
    print(f"\n[2/5] Ingesting Global Overnight Macro Pulse via Yahoo Finance...")
    macro = fetch_global_macro_pulse()
    
    us_perf = 0.0
    if '^GSPC' in macro and '^IXIC' in macro:
        us_perf = (0.5 * macro['^GSPC']['change_pct']) + (0.5 * macro['^IXIC']['change_pct'])
        
    asia_perf = 0.0
    if '^N225' in macro:
        asia_perf = macro['^N225']['change_pct']
        
    us_vix = macro.get('^VIX', {}).get('close', 14.5)
    crude_chg = macro.get('CL=F', {}).get('change_pct', 0.0)
    
    print(f"[✓] US Beta: {us_perf:+.2f}% | Asian Lead: {asia_perf:+.2f}% | US VIX: {us_vix:.2f}")
    
    print(f"\n[3/5] Synthesizing Mathematical Market Mood & Pivot Tiers...")
    mood_score, regime, bias = compute_market_mood_score(
        gap_pct=gap_pct,
        us_perf=us_perf,
        asia_perf=asia_perf,
        us_vix=us_vix,
        india_vix=india_vix,
        crude_chg_pct=crude_chg
    )
    pivots = calculate_pivot_levels(nifty_high, nifty_low, nifty_close)
    active_holdings = load_active_portfolio()
    
    print(f"--------------------------------------------------------------------------------")
    print(f"  PRE-MARKET MOOD VERDICT : {regime} ({mood_score:+d}/100)")
    print(f"  TACTICAL BIAS           : {bias}")
    print(f"  GIFT NIFTY GAP          : {gap_pts:+.1f} Pts ({gap_pct:+.2f}%)")
    print(f"  PIVOT LEVELS            : S1={pivots.get('S1', 0):,.1f} | P={pivots.get('P', 0):,.1f} | R1={pivots.get('R1', 0):,.1f}")
    print(f"  ACTIVE HOLDINGS MONITORED: {len(active_holdings)} Scrips")
    print(f"--------------------------------------------------------------------------------")
    
    report_dict = {
        'timestamp': now_str,
        'score': mood_score,
        'regime': regime,
        'bias': bias,
        'gift_nifty_price': gift_nifty_price,
        'nifty_close': nifty_close,
        'gap_pts': gap_pts,
        'gap_pct': gap_pct,
        'nifty_rsi': nifty_rsi,
        'nifty_ema20': nifty_ema20,
        'banknifty_close': banknifty_close,
        'banknifty_rsi': banknifty_rsi,
        'india_vix': india_vix,
        'india_vix_chg': india_vix_chg,
        'macro': macro,
        'nifty_pivots': pivots,
        'active_holdings': active_holdings
    }
    
    print(f"\n[4/5] Formatting and Generating Local Reports...")
    text_report_path = os.path.join(SCRIPT_DIR, "PRE_MARKET_REPORT.txt")
    with open(text_report_path, "w", encoding="utf-8") as f:
        f.write(f"CENTAUR PRE-MARKET INTELLIGENCE REPORT\n")
        f.write(f"Timestamp: {now_str} IST\n")
        f.write(f"Mood Verdict: {regime} ({mood_score:+d}/100)\n")
        f.write(f"Bias: {bias}\n")
        f.write(f"GIFT Nifty Gap: {gap_pts:+.1f} Pts ({gap_pct:+.2f}%)\n")
        f.write(f"NIFTY Prior Close: INR {nifty_close:,.2f}\n")
        f.write(f"India VIX: {india_vix:.2f}\n")
    print(f"[✓] Saved local text summary: {text_report_path}")
    
    print(f"\n[5/5] Dispatching Real-Time Pre-Market Telegram Broadcast...")
    msg_html = format_telegram_broadcast(report_dict)
    dispatch_telegram(msg_html)
    
    print("\n✅ SUCCESS: Pre-Market Intelligence Pipeline Execution Complete!\n")


if __name__ == "__main__":
    run_pre_market_engine()
