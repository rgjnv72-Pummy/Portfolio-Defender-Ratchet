import os, json, http.client, numpy as np, pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- AUTH ---
MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- CONFIG ---
CSV_FILE = "ind_nifty500list.csv" 
TOP_N = 25

# --- INDICATOR MATH (Replaces pandas_ta) ---
def get_hma(series, length):
    """Calculates Hull Moving Average without external libraries"""
    def wma(s, period):
        weights = np.arange(1, period + 1)
        return s.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    
    half_length = int(length / 2)
    sqrt_length = int(np.sqrt(length))
    # HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
    raw_hma = 2 * wma(series, half_length) - wma(series, length)
    return wma(raw_hma, sqrt_length)

def get_rsi(series, length=14):
    """Calculates Relative Strength Index"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def send_msg(text):
    try:
        conn = http.client.HTTPSConnection("api.telegram.org")
        payload = json.dumps({"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"})
        headers = {"Content-Type": "application/json"}
        conn.request("POST", f"/bot{MY_TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
        conn.close()
    except: pass

def get_confluence_score(symbol):
    try:
        # Download data
        df = yf.download(f"{symbol}.NS", period="2y", progress=False, auto_adjust=True, threads=False)
        if df is None or len(df) < 250: return None
        
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        
        c = df['Close'].astype(float)
        h, l = df['High'].astype(float), df['Low'].astype(float)
        score = 0
        signals = []

        # 1. KRONOS DRIFT (Original Logic)
        drift = (((c.iloc[-1]/c.iloc[-250])-1)/250 * 0.7) + (((c.iloc[-1]/c.iloc[-20])-1)/20 * 0.3)
        upside = ((c.iloc[-1] * (1 + (drift * 30)) - c.iloc[-1]) / c.iloc[-1]) * 100
        if not (1.5 < upside < 30): return None

        # 2. LOGIC MODULES
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
        
        # SQZ Signal
        if (sma20 + (2*std20)).iloc[-1] < (sma20 + (1.5*tr.rolling(20).mean())).iloc[-1]:
            score += 1; signals.append("SQZ")
        
        # ULT Signal
        cv = (std20 * 4 / sma20 * 100)
        if cv.iloc[-1] <= cv.tail(21).min():
            score += 1; signals.append("ULT")
            
        # HUL Signal (Replaced ta.hma)
        hma55 = get_hma(c, length=55)
        if hma55.iloc[-1] > hma55.iloc[-2]:
            score += 1; signals.append("HUL")
            
        # RSI Signal (Replaced ta.rsi)
        rsi14 = get_rsi(c, length=14)
        if rsi14.iloc[-1] > 55:
            score += 1; signals.append("RSI")

        return {'Symbol': symbol, 'Score': score, 'Upside%': round(upside, 2), 'Signals': "+".join(signals)}
    except: return None

def run_master_scan():
    try:
        df_nse = pd.read_csv(CSV_FILE)
        # Use column index 2 as per your original code
        tickers = df_nse.iloc[:, 2].unique().tolist()
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return
    
    results = []
    # Using workers to stay within yfinance limits
    with ThreadPoolExecutor(max_workers=5) as executor:
        for res in tqdm(executor.map(get_confluence_score, tickers), total=len(tickers)):
            if res: results.append(res)
    
    if not results: 
        print("No results found.")
        return
    
    final_df = pd.DataFrame(results).sort_values(by=['Score', 'Upside%'], ascending=False).head(TOP_N)
    
    msg = f"🏆 *KRONOS MASTER SCAN: {datetime.now().strftime('%d-%b')}*\n"
    msg += "_Full-Proof Confluence Dashboard_\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for _, r in final_df.head(15).iterrows():
        icon = "💎" if r['Score'] >= 3 else "🔥"
        msg += f"{icon} `{r['Symbol']}`: *Score {r['Score']}* | {r['Upside%']}% Up\n"
    
    # Generate TradingView Watchlist string
    tv_list = ",".join([f"NSE:{s}" for s in final_df['Symbol']])
    msg += f"\n📺 *TV LIST*\n`{tv_list}`"
    
    send_msg(msg)

if __name__ == "__main__":
    from tqdm import tqdm
    run_master_scan()
