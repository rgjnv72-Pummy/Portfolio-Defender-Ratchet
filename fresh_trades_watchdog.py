import os
import json
import warnings
import http.client
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- WARNING FILTERS ---
warnings.filterwarnings("ignore")

# --- DYNAMIC CONFIGURATION FOR LOCAL VS GITHUB RUN ---
script_dir = os.path.dirname(os.path.abspath(__file__))
if "Trading-Engine" in script_dir:
    BASE_DIR = r"C:\Users\rgjnv\Trading-Engine"
    CANDIDATES_REPORT = os.path.join(BASE_DIR, "Obsidian-Journal", "Ticker-Research", "Master-Fresh-Trades-Scan.md")
    STATE_FILE = os.path.join(BASE_DIR, "Scanner-Scripts", "watchdog_state.json")
else:
    BASE_DIR = script_dir
    CANDIDATES_REPORT = os.path.join(BASE_DIR, "Master-Fresh-Trades-Scan.md")
    STATE_FILE = os.path.join(BASE_DIR, "watchdog_state.json")

MY_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
if MY_CHAT_ID:
    MY_CHAT_ID = MY_CHAT_ID.strip()
MY_TOKEN = os.getenv('TELEGRAM_TOKEN')
if MY_TOKEN:
    MY_TOKEN = MY_TOKEN.strip()

def send_telegram(text):
    if not MY_TOKEN or not MY_CHAT_ID or "YOUR" in MY_TOKEN:
        print(f"[CONSOLE LOG] {text}")
        return
    conn = http.client.HTTPSConnection("api.telegram.org")
    payload = json.dumps({"chat_id": MY_CHAT_ID, "text": text, "parse_mode": "Markdown"})
    headers = {"Content-Type": "application/json"}
    try:
        conn.request("POST", f"/bot{MY_TOKEN}/sendMessage", payload, headers)
        conn.getresponse()
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
    finally:
        conn.close()

def parse_candidates_from_md():
    if not os.path.exists(CANDIDATES_REPORT):
        return []
        
    candidates = []
    try:
        with open(CANDIDATES_REPORT, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        table_started = False
        for line in lines:
            if "| Ticker |" in line:
                table_started = True
                continue
            if table_started and line.startswith("|"):
                if ":---" in line or "Ticker" in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 8:
                    ticker = parts[1].replace("**", "").strip()
                    strategy = parts[2].replace("`", "").strip()
                    grade = parts[3].strip()
                    price = float(parts[4].replace("**", "").replace("₹", "").replace(",", "").strip())
                    entry = float(parts[5].replace("**", "").replace("₹", "").replace(",", "").strip())
                    stop = float(parts[6].replace("**", "").replace("₹", "").replace(",", "").strip())
                    risk = parts[7].strip()
                    
                    candidates.append({
                        "Ticker": ticker,
                        "Strategy": strategy,
                        "Grade": grade,
                        "Price_At_Scan": price,
                        "Entry_Trigger": entry,
                        "Stop_Loss": stop,
                        "Risk": risk
                    })
    except Exception as e:
        print(f"Error parsing candidates: {e}")
    return candidates

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"Error saving state: {e}")

def run_live_watchdog():
    candidates = parse_candidates_from_md()
    if not candidates:
        print("[WARNING] No active candidates loaded from Obsidian report.")
        return
        
    state = load_state()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if today_str not in state:
        state[today_str] = []
        
    triggered_list = state[today_str]
    tickers = [f"{c['Ticker']}.NS" for c in candidates]
    
    print(f"[INFO] Fetching real-time quotes for {len(tickers)} watchlist tickers...")
    try:
        data = yf.download(tickers, period="1d", interval="1m", progress=False, auto_adjust=True)
    except Exception as e:
        print(f"[ERROR] Failed to fetch quotes: {e}")
        return
        
    alerts = []
    
    for c in candidates:
        ticker = c['Ticker']
        ticker_ns = f"{ticker}.NS"
        
        if ticker in triggered_list:
            continue
            
        try:
            if len(tickers) == 1:
                latest_price = float(data['Close'].iloc[-1])
            else:
                latest_price = float(data['Close'][ticker_ns].dropna().iloc[-1])
                
            entry_trigger = c['Entry_Trigger']
            strategy = c['Strategy']
            
            if "VCP" in strategy:
                if latest_price >= entry_trigger:
                    msg = f"🚀 *WATCHDOG SIGNAL: BREAKOUT TRIGGERED* 🚀\n" \
                          f"🔹 Ticker: *{ticker}* (Minervini VCP)\n" \
                          f"🔹 Current Price: ₹{latest_price:.2f} (Triggered above ₹{entry_trigger:.2f})\n" \
                          f"🔹 Stop Loss: *₹{c['Stop_Loss']:.2f}* ({c['Risk']} cushion)\n" \
                          f"🎯 Action: Place market/limit buy order with strict stop loss."
                    alerts.append((ticker, msg))
                    
            elif "FVG" in strategy:
                if latest_price <= entry_trigger:
                    msg = f"🟢 *WATCHDOG SIGNAL: PULLBACK TRIGGERED* 🟢\n" \
                          f"🔹 Ticker: *{ticker}* (SMC FVG Pullback)\n" \
                          f"🔹 Current Price: ₹{latest_price:.2f} (Triggered below ₹{entry_trigger:.2f})\n" \
                          f"🔹 Stop Loss: *₹{c['Stop_Loss']:.2f}* ({c['Risk']} cushion)\n" \
                          f"🎯 Action: Enter pullback long position inside FVG zone."
                    alerts.append((ticker, msg))
                    
        except Exception:
            pass
            
    if alerts:
        for ticker, msg in alerts:
            send_telegram(msg)
            triggered_list.append(ticker)
        state[today_str] = triggered_list
        save_state(state)
        print(f"[SUCCESS] Dispatched {len(alerts)} alerts to Telegram Bot.")
    else:
        print("[INFO] Live scan complete. No entry trigger levels hit.")

if __name__ == "__main__":
    run_live_watchdog()
