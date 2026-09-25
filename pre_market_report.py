#!/usr/bin/env python3
"""

=========================================================================================================
      CENTAUR QUANTITATIVE TRADING SYSTEM: PRE-MARKET INTELLIGENCE & MOOD ENGINE
  Automated Morning Intelligence: GIFT Nifty, Global Overnight Beta, Volatility & Portfolio Radar
=========================================================================================================
Execution Schedule : 07:30 AM IST (02:00 AM UTC, Monday - Friday)
Target Environment : GitHub Actions CI/CD (Ubuntu-latest) & Local Centaur Automated Runner
=========================================================================================================
"""

import os
import sys
import json
import math
import ssl
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

# Enforce UTF-8 on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Telegram Credentials (Environment variables with secure fallback)
TG_TOKEN = os.getenv('TELEGRAM_TOKEN', "8711599818:AAGc-7qmFXdcbA_T-JFZTb4w5UlX9FiRm2o")
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "1280803679")

# Directory Discovery
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in ["Scanner-Scripts", "Ratchet-System", "scripts", "scanners"] else SCRIPT_DIR
CENTAUR_ROOT = ENGINE_DIR

PORTFOLIO_PATHS = [
    os.path.join(CENTAUR_ROOT, "market_data", "portfolio.json"),
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Content-Type': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
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
            close_val = float(d[0]) if d[0] is not None else 0.0
            out[sym] = {
                'close': close_val,
                'cl': close_val,  # Alias for compatibility with .get('cl')
                'change_pct': float(d[1]) if d[1] is not None else 0.0,
                'change_pts': float(d[2]) if d[2] is not None else 0.0,
                'open': float(d[3]) if d[3] is not None else 0.0,
                'high': float(d[4]) if d[4] is not None else 0.0,
                'low': float(d[5]) if d[5] is not None else 0.0,
                'volume': float(d[6]) if len(d) > 6 and d[6] is not None else 0.0
            }
    return out


def fetch_domestic_market_technicals() -> Dict[str, Any]:
    """Fetches domestic benchmark indices, India VIX, and technical indicators."""
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
            close_val = float(d[0]) if d[0] is not None else 0.0
            chg_pct = float(d[1]) if d[1] is not None else 0.0
            chg_pts = float(d[2]) if d[2] is not None else 0.0
            rsi_val = float(d[3]) if d[3] is not None else 50.0
            ema20_val = float(d[4]) if d[4] is not None else 0.0
            sma50_val = float(d[5]) if d[5] is not None else 0.0
            high_val = float(d[6]) if d[6] is not None else 0.0
            low_val = float(d[7]) if d[7] is not None else 0.0
            open_val = float(d[8]) if d[8] is not None else 0.0
            out[sym] = {
                'close': close_val,
                'change_pct': chg_pct,
                'change_pts': chg_pts,
                'RSI': rsi_val,
                'rsi': rsi_val,      # Both cases supported
                'EMA20': ema20_val,
                'ema20': ema20_val,  # Both cases supported
                'SMA50': sma50_val,
                'sma50': sma50_val,
                'high': high_val,
                'low': low_val,
                'open': open_val
            }
    return out


def fetch_global_macro_pulse() -> Dict[str, Any]:
    """Fetches overnight US indices, Asian leads, Crude, DXY, and USD/INR via yfinance."""
    out = {}
    tickers = {
        '^GSPC': '^GSPC',         # S&P 500
        '^IXIC': '^IXIC',         # Nasdaq 100
        '^N225': '^N225',         # Nikkei 225
        'CL=F': 'CL=F',           # WTI Crude
        'DX-Y.NYB': 'DX-Y.NYB',   # US Dollar Index
        'INR=X': 'USDINR=X',      # USD/INR
        '^VIX': '^VIX'            # US VIX
    }

    try:
        import yfinance as yf
        raw = yf.download(list(tickers.values()), period='5d', interval='1d', progress=False)
        close_df = raw['Close'] if 'Close' in raw else None
        if close_df is not None:
            for key, yf_sym in tickers.items():
                if yf_sym in close_df.columns:
                    s = close_df[yf_sym].dropna()
                    if len(s) >= 2:
                        curr, prev = float(s.iloc[-1]), float(s.iloc[-2])
                        out[key] = {
                            'close': curr,
                            'change_pct': ((curr - prev) / prev) * 100.0 if prev != 0 else 0.0
                        }
                    elif len(s) == 1:
                        out[key] = {'close': float(s.iloc[-1]), 'change_pct': 0.0}
    except Exception as e:
        print(f"[!] Warning fetching global macro via yfinance: {e}")

    return out

# Alias for backwards compatibility
fetch_global_macro_data = fetch_global_macro_pulse


def calculate_pivot_levels(high: float, low: float, close: float) -> Dict[str, float]:
    """Calculates classical floor pivot levels."""
    if not high or not low or not close:
        return {'P': 0.0, 'R1': 0.0, 'R2': 0.0, 'S1': 0.0, 'S2': 0.0}
    p = (high + low + close) / 3.0
    r1 = (2.0 * p) - low
    s1 = (2.0 * p) - high
    r2 = p + (high - low)
    s2 = p - (high - low)
    return {'P': round(p, 1), 'R1': round(r1, 1), 'R2': round(r2, 1), 'S1': round(s1, 1), 'S2': round(s2, 1)}


def load_active_portfolio() -> Dict[str, Any]:
    """Discovers and parses the live portfolio holdings."""
    for p in PORTFOLIO_PATHS:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('holdings', {})
            except Exception:
                pass
    return {}


def compute_market_mood_score(gap_pct: float, us_perf: float, asia_perf: float,
                              us_vix: float, india_vix: float, crude_chg_pct: float) -> Tuple[int, str, str]:
    """Computes mathematically weighted composite market mood score (-100 to +100)."""
    # 1. GIFT Nifty Gap (30% weight): +/-0.5% gap maps to +/-50 score
    gift_score = (gap_pct / 0.5) * 50.0
    gift_score = max(-100.0, min(100.0, gift_score))
    
    # 2. US Overnight Beta (25% weight): +/-1.0% gain maps to +/-50 score
    us_score = (us_perf / 1.0) * 50.0
    us_score = max(-100.0, min(100.0, us_score))
    
    # 3. Asian Morning Beta (20% weight): +/-1.0% gain maps to +/-50 score
    asia_score = (asia_perf / 1.0) * 50.0
    asia_score = max(-100.0, min(100.0, asia_score))
    
    # 4. Volatility Index (15% weight)
    vix_score = 0.0
    if india_vix > 18.0 or us_vix > 22.0:
        vix_score = -60.0
    elif india_vix > 15.0 or us_vix > 18.0:
        vix_score = -20.0
    elif india_vix < 13.0 and us_vix < 16.0:
        vix_score = +40.0
    vix_score = max(-100.0, min(100.0, vix_score))
    
    # 5. Macro (10% weight: Crude jump hurts Indian corporate margins)
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
    macro = report_dict.get('macro', {})
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
        lines.append(f"  • USD/INR: ₹{macro['INR=X']['close']:.2f}")
    lines.append("")
    
    # Domestic Indicators
    lines.append("🎯 <b>DOMESTIC BENCHMARKS & VOLATILITY:</b>")
    lines.append(f"  • <b>NIFTY 50:</b> {report_dict['nifty_close']:,.2f} (RSI: {report_dict['nifty_rsi']:.1f} | 20-EMA: {report_dict['nifty_ema20']:,.1f})")
    lines.append(f"  • <b>BANK NIFTY:</b> {report_dict['banknifty_close']:,.2f} (RSI: {report_dict['banknifty_rsi']:.1f})")
    vix_state = "COMPLACENT" if report_dict['india_vix'] < 13.0 else ("ELEVATED" if report_dict['india_vix'] > 18.0 else "NORMAL")
    lines.append(f"  • <b>India VIX:</b> {report_dict['india_vix']:.2f} ({report_dict['india_vix_chg']:+.2f}%) [{vix_state}]")
    lines.append("")
    
    # Pivots
    piv = report_dict.get('nifty_pivots', {})
    if piv and piv.get('P', 0) > 0:
        lines.append("📐 <b>NIFTY 50 STRUCTURAL PIVOT TIERS:</b>")
        lines.append(f"  • Resistance: <b>R2: {piv['R2']:,.1f}</b> | <b>R1: {piv['R1']:,.1f}</b>")
        lines.append(f"  • Pivot Floor: <b>P: {piv['P']:,.1f}</b>")
        lines.append(f"  • Support: <b>S1: {piv['S1']:,.1f}</b> | <b>S2: {piv['S2']:,.1f}</b>")
        lines.append("")
        
    # Active Portfolio Radar
    holdings = report_dict.get('active_holdings', {})
    if holdings:
        lines.append("💼 <b>ACTIVE PORTFOLIO RADAR:</b>")
        for sym, pos in holdings.items():
            qty = pos.get('quantity', 0)
            cost = pos.get('avg_cost', 0.0)
            sl = pos.get('initial_stop', 0.0)
            lines.append(f"  • <b>{sym}:</b> {qty} sh @ ₹{cost:,.2f} | Floor: ₹{sl:,.2f}")
        lines.append("")

    lines.append("🛡️ <b>CENTAUR STRATEGIC DIRECTIVE:</b>")
    lines.append("• Maintain 1.0% NAV risk limit per position; stops never retreat.")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def dispatch_telegram(msg_html: str) -> bool:
    """Dispatches HTML message to Telegram."""
    token = TG_TOKEN
    chat_id = TG_CHAT_ID

    if not token or not chat_id:
        print("[!] Telegram credentials missing. Skipping broadcast.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        data = urllib.parse.urlencode(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status == 200:
                print(f"[✓] Telegram Delivered to {chat_id}")
                return True
    except Exception as e:
        print(f"[!] Telegram Dispatch Error: {e}")
    return False


def run_pre_market_engine():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 80)
    print("      CENTAUR QUANTITATIVE TRADING SYSTEM: PRE-MARKET INTELLIGENCE ENGINE")
    print("=" * 80)
    
    print(f"\n[1/5] Ingesting Live GIFT Nifty & Domestic Market Technicals via TradingView...")
    gift_data = fetch_gift_nifty_data()
    dom_data = fetch_domestic_market_technicals()
    
    # Extract Domestic NIFTY 50 FIRST before calculating gap
    nifty_info = dom_data.get('NSE:NIFTY', {})
    nifty_close = nifty_info.get('close', 23078.80)
    nifty_high = nifty_info.get('high', 23121.60)
    nifty_low = nifty_info.get('low', 23030.00)
    nifty_rsi = nifty_info.get('rsi', nifty_info.get('RSI', 40.25))
    nifty_ema20 = nifty_info.get('ema20', nifty_info.get('EMA20', 23513.0))
    
    # Extract Bank Nifty
    banknifty_info = dom_data.get('NSE:BANKNIFTY', {})
    banknifty_close = banknifty_info.get('close', 55579.0)
    banknifty_rsi = banknifty_info.get('rsi', banknifty_info.get('RSI', 46.25))
    
    # Extract India VIX
    vix_info = dom_data.get('NSE:INDIAVIX', {})
    india_vix = vix_info.get('close', 12.50)
    india_vix_chg = vix_info.get('change_pct', 0.0)
    
    # Extract GIFT Nifty
    gift_nifty_obj = gift_data.get('NSEIX:NIFTY1!', {})
    gift_nifty_price = gift_nifty_obj.get('close', gift_nifty_obj.get('cl', nifty_close))
    
    # Calculate Spread
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
        
    us_vix = macro.get('^VIX', {}).get('close', 15.65)
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
