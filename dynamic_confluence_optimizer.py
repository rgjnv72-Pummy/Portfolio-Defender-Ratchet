"""
===============================================================================
KRONOS QUANTITATIVE SYSTEM: DYNAMIC CONFLUENCE OPTIMIZER
===============================================================================
Module Reference: SSRN-6682038 ("Multi-Agent LLMs with Reinforcement Learning
                  for Quant Trading" - Chen & Kawashima)
Purpose: Replaces static signal-counting confluence with continuous,
         rolling-Sharpe risk-adjusted dynamic weighting across quant domains.

Architecture:
- Strategy Domains:
    1. Breakout & Squeeze (VCP, Vol-Compression, 52W High)
    2. Pullback & Structure (FVG, SMC, EMA-Pullback, RSI-Reversal)
    3. Value & Mean Reversion (Z-Score, Money Flow, Kalman)
    4. Volume & Accumulation (Whale/Delivery, Pocket Pivot, Catalyst)
    5. Relative Strength & Momentum (RS-Breakout, Gap Momentum, Leaders)
- Action: Continuous weight vector w_t normalized via L1 scaling
- Objective: Maximize 20-day rolling Sharpe ratio with turnover regularization
===============================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
from scipy.optimize import minimize

# UTF-8 Console Encoding for Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# Domain Definitions matching Kronos Confluence Architecture
DOMAINS = [
    "Breakout & Squeeze",
    "Pullback & Structure",
    "Value & Mean Reversion",
    "Volume & Regime",
    "Relative Strength"
]

DOMAIN_LOOKUP = {
    # 1. Breakout & Squeeze
    "vcp": "Breakout & Squeeze",
    "explosion": "Breakout & Squeeze",
    "kronos": "Breakout & Squeeze",
    "contraction": "Breakout & Squeeze",
    "squeeze": "Breakout & Squeeze",
    "adx-rider": "Breakout & Squeeze",
    "vol-compression": "Breakout & Squeeze",
    "near-52w": "Breakout & Squeeze",
    "vol-spike": "Breakout & Squeeze",
    
    # 2. Pullback & Structure
    "fvg": "Pullback & Structure",
    "smc": "Pullback & Structure",
    "pullback": "Pullback & Structure",
    "fib": "Pullback & Structure",
    "structural": "Pullback & Structure",
    "trend-pullback": "Pullback & Structure",
    "ema-pullback": "Pullback & Structure",
    "rsi-reversal": "Pullback & Structure",
    "cci-breakout": "Pullback & Structure",
    
    # 3. Value & Mean Reversion
    "z-score": "Value & Mean Reversion",
    "money-flow": "Value & Mean Reversion",
    "arima": "Value & Mean Reversion",
    "garch": "Value & Mean Reversion",
    "kalman": "Value & Mean Reversion",
    "avellaneda": "Value & Mean Reversion",
    "clean-room-alpha": "Value & Mean Reversion",
    
    # 4. Volume & Regime
    "whale": "Volume & Regime",
    "delivery": "Volume & Regime",
    "spurt": "Volume & Regime",
    "volume": "Volume & Regime",
    "hmm": "Volume & Regime",
    "regime": "Volume & Regime",
    "vsa": "Volume & Regime",
    "pocket-pivot": "Volume & Regime",
    "stealth-base": "Volume & Regime",
    "catalyst-accel": "Volume & Regime",
    "beast": "Volume & Regime",
    "alpha": "Volume & Regime",
    
    # 5. Relative Strength
    "rs-breakout": "Relative Strength",
    "green-on-red-day": "Relative Strength",
    "gap-up-momentum": "Relative Strength",
    "leaders": "Relative Strength",
    "master-fresh": "Relative Strength",
    "weekly": "Relative Strength",
    "monthly": "Relative Strength",
    "3month": "Relative Strength"

}

def map_signal_to_domain(sig_name: str) -> str:
    """Map any raw strategy or scanner name into one of the 5 quantitative domains."""
    sig_lower = sig_name.lower().strip()
    for key, domain in DOMAIN_LOOKUP.items():
        if key in sig_lower:
            return domain
    return "Relative Strength"

class DynamicConfluenceOptimizer:
    """
    Continuous Risk-Adjusted Optimizer for Multi-Domain Quantitative Strategies.
    Implements L1-norm continuous policy optimization from SSRN 6682038.
    """
    def __init__(self, window_size: int = 20, turnover_penalty: float = 0.05):
        self.window_size = window_size
        self.turnover_penalty = turnover_penalty
        self.domains = DOMAINS
        self.k = len(self.domains)
        # Default prior: Equal weights across domains
        self.current_weights = np.ones(self.k) / self.k

    def calculate_rolling_sharpe(self, weights: np.ndarray, signal_matrix: np.ndarray, future_returns: np.ndarray, prev_weights: np.ndarray = None) -> float:
        """
        SSRN 6682038 Objective Function:
        Computes the negative annualized rolling Sharpe ratio of portfolio returns.
        """
        # L1 Normalization for controlled gross exposure
        l1_norm = np.sum(np.abs(weights)) + 1e-8
        norm_weights = weights / l1_norm
        
        # Raw combined signal z_t = sum(alpha_i * w_i)
        combined_signal = np.dot(signal_matrix, norm_weights)
        
        # Continuous bounded exposure p_t = tanh(z_t) in [-1, 1]
        position = np.tanh(combined_signal)
        
        # Portfolio daily return clipped to [-20%, +20%] for stability
        port_returns = np.clip(position * future_returns, -0.20, 0.20)
        
        mean_ret = np.mean(port_returns)
        std_ret = np.std(port_returns) + 1e-8
        
        # Annualized Sharpe Ratio
        annualized_sharpe = (mean_ret / std_ret) * np.sqrt(252)
        
        # Penalty for excessive weight switching (reduces transaction drag)
        if prev_weights is not None:
            turnover = np.sum((norm_weights - prev_weights)**2)
            annualized_sharpe -= self.turnover_penalty * turnover
            
        # Return negative Sharpe for minimization
        return -float(annualized_sharpe)

    def optimize_weights(self, signal_history_df: pd.DataFrame, return_history: pd.Series) -> dict:
        """
        Solves for the optimal continuous domain weights given recent performance history.
        signal_history_df: DataFrame with columns = self.domains, rows = past W days
        return_history: Series of future 1-day returns over past W days
        """
        if len(signal_history_df) < self.window_size:
            # Fallback to current weights if insufficient data
            norm_w = self.current_weights / np.sum(self.current_weights)
            return {d: round(float(w), 4) for d, w in zip(self.domains, norm_w)}

        # Take the most recent rolling window
        sig_matrix = signal_history_df[self.domains].iloc[-self.window_size:].values
        fut_returns = return_history.iloc[-self.window_size:].values

        # Initial guess
        init_weights = self.current_weights.copy()
        bounds = [(0.0, 1.0) for _ in range(self.k)]  # Long-bias allocation

        res = minimize(
            fun=self.calculate_rolling_sharpe,
            x0=init_weights,
            args=(sig_matrix, fut_returns, self.current_weights),
            method="SLSQP",
            bounds=bounds,
            options={"maxiter": 100, "ftol": 1e-5}
        )

        if res.success:
            optimal_raw = np.maximum(res.x, 0.0)
            norm_w = optimal_raw / (np.sum(optimal_raw) + 1e-8)
            self.current_weights = norm_w
        else:
            norm_w = self.current_weights / np.sum(self.current_weights)

        return {d: round(float(w), 4) for d, w in zip(self.domains, norm_w)}

    def score_setup(self, triggered_signals: list, domain_weights: dict = None) -> dict:
        """
        Computes the Dynamic Risk-Adjusted Confluence Score for a specific stock setup.
        """
        if domain_weights is None:
            domain_weights = {d: round(1.0 / self.k, 4) for d in self.domains}

        # Count signals per domain
        domain_signal_counts = {d: 0 for d in self.domains}
        unique_domains = set()

        for sig in triggered_signals:
            dom = map_signal_to_domain(sig)
            if dom in domain_signal_counts:
                domain_signal_counts[dom] += 1
                unique_domains.add(dom)

        # Compute raw weighted score z_t = sum(alpha_domain * weight_domain)
        # Saturate domain contribution using tanh to reward diversity over single-domain clustering
        raw_weighted_score = 0.0
        for dom, weight in domain_weights.items():
            count = domain_signal_counts[dom]
            # Non-linear diminishing returns for multiple signals in the same domain
            domain_activation = np.tanh(count) 
            raw_weighted_score += domain_activation * weight

        # Dynamic Conviction Index (DCI) scaled to 0 - 100%
        conviction_index = float(np.tanh(raw_weighted_score * 2.5) * 100.0)

        # Determine allocation recommendation tier
        if conviction_index >= 70.0 and len(unique_domains) >= 3:
            allocation_tier = "Tier 1: Maximum Sizing (Multi-Domain Confluence)"
            exposure_scale = 1.00
        elif conviction_index >= 50.0 and len(unique_domains) >= 2:
            allocation_tier = "Tier 2: Standard Sizing (Solid Confluence)"
            exposure_scale = 0.75
        elif conviction_index >= 30.0:
            allocation_tier = "Tier 3: Half Sizing (Moderate / Single Domain)"
            exposure_scale = 0.50
        else:
            allocation_tier = "Tier 4: Veto / Watchlist Only (Low Risk-Adjusted Conviction)"
            exposure_scale = 0.00

        return {
            "dynamic_conviction_score": round(conviction_index, 2),
            "allocation_tier": allocation_tier,
            "exposure_scale": exposure_scale,
            "unique_domain_count": len(unique_domains),
            "triggered_domains": list(unique_domains),
            "domain_breakdown": domain_signal_counts,
            "active_weights": domain_weights
        }

if __name__ == "__main__":
    print("🧠 Testing Dynamic Confluence Optimizer (SSRN 6682038 Engine)...")
    optimizer = DynamicConfluenceOptimizer(window_size=20)
    
    # Simulate sample test case: Stock with FVG (Pullback) + Pocket-Pivot (Volume) + Near-52W (Breakout)
    test_signals = ["FVG-Bullish", "Pocket-Pivot", "Near-52w-High", "RS-Breakout"]
    
    # Active weights favoring Relative Strength & Pullback regimes
    sample_weights = {
        "Breakout & Squeeze": 0.15,
        "Pullback & Structure": 0.35,
        "Value & Mean Reversion": 0.05,
        "Volume & Regime": 0.20,
        "Relative Strength": 0.25
    }
    
    result = optimizer.score_setup(test_signals, sample_weights)
    print("\n--- TEST RUN RESULTS ---")
    print(f"Signals: {test_signals}")
    print(f"Conviction Score: {result['dynamic_conviction_score']}%")
    print(f"Allocation Tier:  {result['allocation_tier']}")
    print(f"Exposure Scale:   {result['exposure_scale'] * 100}%")
    print(f"Unique Domains:   {result['unique_domain_count']} ({result['triggered_domains']})")
    print("✅ Module operational.")
