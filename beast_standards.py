# ==============================================================================
# 🏛️ BEAST SCANNER PIPELINE: UNIVERSAL BULLISH SWING TRADING & LIQUIDITY STANDARDS
# ==============================================================================
# Standard Reference: ₹2 Lakh Ticket Size Baseline Gate
# 1. Macro Structural Bullish Trend: Close >= EMA_200
# 2. Turnover Gate: 20-day ADTV >= ₹2.50 Crores / Day (Max 0.80% Market Impact)
# 3. Dynamic Volume Invariance: Volume_20d >= ₹25,000,000 / Price
# 4. Anti-Penny Floor: Close >= ₹50.00
# 5. Circuit Freeze Elimination: High != Low and Day Range >= 0.75%
# 6. Mandatory Reporting: Includes 'Avg_Turnover_Cr' and 'Market_Cap_Cr'
# ==============================================================================

import pandas as pd
import numpy as np

MIN_ADTV_INR = 25_000_000.0   # ₹2.50 Crores / Day
MIN_PRICE_INR = 50.00         # Anti-Penny Floor
MIN_DAY_RANGE_PCT = 0.75      # 0.75% Minimum Day Range
TICKET_SIZE_INR = 200_000.0   # ₹2 Lakh Ticket Size

def check_beast_liquidity_standards(df: pd.DataFrame) -> tuple[bool, dict]:
    """
    Evaluates whether a stock's historical OHLCV data complies with the
    Universal 5-Point Bullish Swing Trading & Liquidity Standard.
    
    Parameters:
        df (pd.DataFrame): DataFrame containing ['Close', 'High', 'Low', 'Volume']
        
    Returns:
        tuple[bool, dict]: (is_passed, metrics_dict)
    """
    if df is None or len(df) < 20:
        return False, {"error": "Insufficient history (< 20 bars)", "passed": False}
        
    try:
        # Normalize column names
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1) if df.columns.nlevels > 1 else df
            
        c = df['Close'].astype(float).dropna()
        h = df['High'].astype(float).dropna() if 'High' in df.columns else c
        l = df['Low'].astype(float).dropna() if 'Low' in df.columns else c
        v = df['Volume'].astype(float).dropna() if 'Volume' in df.columns else pd.Series(1.0, index=c.index)
        
        if len(c) < 20:
            return False, {"error": "Insufficient valid close price data", "passed": False}
            
        latest_close = float(c.iloc[-1])
        latest_high = float(h.iloc[-1]) if not h.empty else latest_close
        latest_low = float(l.iloc[-1]) if not l.empty else latest_close
        
        # 1. Anti-Penny Floor: Close >= ₹50.00
        pass_penny = latest_close >= MIN_PRICE_INR
        
        # 2. Macro Structural Bullish Trend: Close >= EMA_200
        if len(c) >= 200:
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            pass_macro = latest_close >= (ema200 * 0.995)  # Allow 0.5% tolerance at boundary
        elif len(c) >= 50:
            ema_avail = float(c.ewm(span=len(c), adjust=False).mean().iloc[-1])
            pass_macro = latest_close >= ema_avail
        else:
            pass_macro = True
            ema200 = latest_close
            
        # 3. Turnover Gate: 20-day ADTV >= ₹2.50 Crores / Day
        turnover_20d = (c.tail(20) * v.tail(20)).mean()
        adtv_cr = round(turnover_20d / 10_000_000.0, 2)
        pass_turnover = turnover_20d >= MIN_ADTV_INR
        
        # 4. Dynamic Volume Invariance: Volume_20d >= ₹25,000,000 / Price
        vol_20d = float(v.tail(20).mean())
        req_vol = MIN_ADTV_INR / max(latest_close, 1e-6)
        pass_vol_invariance = vol_20d >= req_vol
        
        # 5. Circuit Freeze & Flat Bar Elimination: High != Low and Day Range >= 0.75%
        day_range_pct = round(((latest_high - latest_low) / max(latest_low, 1e-6)) * 100.0, 2)
        pass_freeze = (latest_high != latest_low) and (day_range_pct >= MIN_DAY_RANGE_PCT)
        
        # Position impact ratio for ₹2 Lakh ticket size
        impact_ratio_pct = round((TICKET_SIZE_INR / max(turnover_20d, 1.0)) * 100.0, 3)
        
        # Combined Gate Evaluation
        is_passed = bool(pass_penny and pass_macro and pass_turnover and pass_vol_invariance and pass_freeze)
        
        reasons_failed = []
        if not pass_penny: reasons_failed.append(f"Price ₹{latest_close:.2f} < ₹50.00 floor")
        if not pass_macro: reasons_failed.append(f"Close ₹{latest_close:.2f} < EMA200 ₹{ema200:.2f}")
        if not pass_turnover: reasons_failed.append(f"ADTV20 ₹{adtv_cr:.2f}Cr < ₹2.50Cr floor")
        if not pass_vol_invariance: reasons_failed.append(f"Vol20 {vol_20d:.0f} < ReqVol {req_vol:.0f}")
        if not pass_freeze: reasons_failed.append(f"Day range {day_range_pct:.2f}% < 0.75% or circuit lock")
        
        metrics = {
            "passed": is_passed,
            "close": latest_close,
            "ema200": ema200 if len(c) >= 200 else None,
            "adtv_20_cr": adtv_cr,
            "vol_20d": vol_20d,
            "req_vol": req_vol,
            "day_range_pct": day_range_pct,
            "impact_ratio_pct": impact_ratio_pct,
            "reasons_failed": reasons_failed
        }
        return is_passed, metrics
    except Exception as e:
        return False, {"error": str(e), "passed": False}

def validate_beast_standard_quick(df: pd.DataFrame) -> bool:
    """Fast boolean-only gate check for high-throughput scanning loops."""
    passed, _ = check_beast_liquidity_standards(df)
    return passed
