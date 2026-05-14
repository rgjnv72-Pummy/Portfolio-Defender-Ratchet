    results = []
    total_val, daily_gain_sum, total_cost = 0.0, 0.0, 0.0
    skipped_tickers = []

    # --- FIRST PASS: CALCULATE LIVE VALUE FOR ALL TICKERS ---
    for ticker, (qty, buy_p, buy_date, sector) in CURRENT_HOLDINGS.items():
        try:
            # Isolate today's price immediately to secure valuation accuracy
            df_ticker = data.xs(ticker, axis=1, level=1)
            latest_close = float(df_ticker['Close'].dropna().iloc[-1])
            yesterday_close = float(df_ticker['Close'].dropna().iloc[-2])
            
            total_val += (latest_close * qty)
            total_cost += (buy_p * qty)
            daily_gain_sum += (latest_close - yesterday_close) * qty
        except Exception:
            # If yfinance completely fails a ticker, preserve its cost basis as a safety fallback
            total_val += (buy_p * qty)
            total_cost += (buy_p * qty)
            skipped_tickers.append(ticker.replace('.NS',''))

    # --- SECOND PASS: CALCULATE RISK AND TRAILING STOPS ---
    for ticker, (qty, buy_p, buy_date, sector) in CURRENT_HOLDINGS.items():
        try:
            df = data.xs(ticker, axis=1, level=1).dropna().copy()
            
            # Historical check only affects trailing stop text generation, not portfolio value
            if len(df) < 15: 
                continue
            
            close_p = float(df['Close'].iloc[-1])
            pnl_pct = ((close_p - buy_p) / buy_p) * 100
            
            tr = pd.concat([
                df['High'] - df['Low'], 
                (df['High'] - df['Close'].shift(1)).abs(), 
                (df['Low'] - df['Close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            
            valid_df = df[df.index >= buy_date].copy()
            if valid_df.empty: 
                valid_df = df.iloc[-5:]
                
            valid_atr = atr.reindex(valid_df.index)
            ratchet_series = valid_df['Close'] - (2.0 * valid_atr)
            ratchet = ratchet_series.rolling(20, min_periods=1).max().iloc[-1]
            
            ratchet = min(ratchet, close_p * 0.97)
            ratchet = max(ratchet, buy_p * 0.88)
            dist_to_stop = ((close_p - ratchet) / close_p) * 100
            
            if dist_to_stop > 6.0:
                continue

            is_triggered = close_p <= (ratchet + 0.05)
            status_icon = "🚨 *BREAK*" if is_triggered else "⚠️ *RISK*"
            
            ticker_name = ticker.replace('.NS','')
            line_text = f"*{ticker_name}* | Price: ₹{close_p:.1f} ({pnl_pct:+.1f}%) | {status_icon}\n"
            line_text += f"_Stop Floor: ₹{ratchet:.1f} ({dist_to_stop:.1f}% cushion)_\n\n"
            
            results.append({'text': line_text, 'cushion': dist_to_stop})
        except Exception:
            continue
