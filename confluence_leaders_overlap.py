import os
import re
import datetime
import importlib
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)

# Determine Obsidian dir (works locally and on GitHub VM)
OBSIDIAN_DIR = os.path.join(PARENT_DIR, "Obsidian-Journal", "Ticker-Research")
if not os.path.exists(os.path.join(PARENT_DIR, "Obsidian-Journal")):
    OBSIDIAN_DIR = os.path.join(SCRIPT_DIR, "Obsidian-Journal", "Ticker-Research")
os.makedirs(OBSIDIAN_DIR, exist_ok=True)

# Custom dotenv loader to avoid package dependencies
def load_custom_dotenv(dotenv_path):
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip("'").strip('"')
                    os.environ[key.strip()] = val

# Load env variables
load_custom_dotenv(os.path.join(PARENT_DIR, ".env"))
load_custom_dotenv(os.path.join(SCRIPT_DIR, ".env"))

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    if not TOKEN or not CHAT_ID:
        print("[WARNING] Telegram configurations not found in env. Skipping notification.")
        print("Telegram Message Content:\n", text)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            print(f"[WARNING] Telegram returned status code {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram alert: {e}")

def run_overlap_analysis():
    print("[INFO] Running Consolidated Scanners...")
    
    # 1. Run Leaders Scanner
    print("[INFO] Executing NSE 500 Leaders Scanner...")
    try:
        import nse500_leaders_scanner
        # Reload just in case
        importlib.reload(nse500_leaders_scanner)
        nse500_leaders_scanner.run_nse500_scanner()
    except Exception as e:
        print(f"[ERROR] Leaders scanner execution failed: {e}")
        
    # 2. Run Confluence Scanner
    print("[INFO] Executing Cross-Scanner Confluence Audit...")
    try:
        import confluence_analyzer
        importlib.reload(confluence_analyzer)
        confluence_analyzer.run_confluence_audit()
    except Exception as e:
        print(f"[ERROR] Confluence analyzer execution failed: {e}")

    # Paths to generated files
    leaders_path = os.path.join(OBSIDIAN_DIR, "NSE500-Leaders.md")
    confluence_path = os.path.join(OBSIDIAN_DIR, "Confluence-Report.md")
    overlap_report_path = os.path.join(OBSIDIAN_DIR, "Confluence-NSE500-Leaders-Overlap.md")
    
    if not os.path.exists(leaders_path) or not os.path.exists(confluence_path):
        print(f"[ERROR] Required input files not found. Leaders: {os.path.exists(leaders_path)}, Confluence: {os.path.exists(confluence_path)}")
        return
        
    # Read files
    with open(leaders_path, "r", encoding="utf-8") as f:
        leaders_content = f.read()
    with open(confluence_path, "r", encoding="utf-8") as f:
        confluence_content = f.read()
        
    # Extract tickers
    leaders_tickers = re.findall(r"\|\s*#\d+\s*\|\s*\*\*([A-Z0-9_\-]+)\*\*", leaders_content)
    raw_confluence_tickers = re.findall(r"\|\s*\*\*([A-Z0-9_\-]+)\*\*\s*\|", confluence_content)
    confluence_tickers = [t for t in raw_confluence_tickers if not t.isdigit()]
    
    overlap = set(leaders_tickers).intersection(set(confluence_tickers))
    
    if not overlap:
        print("[INFO] No overlapping tickers found.")
        send_telegram_message("📊 *NSE 500 Leaders & Confluence Overlap*\n\nNo overlapping high-conviction setups found this week.")
        return
        
    # Collect details
    overlap_details = []
    for ticker in sorted(overlap):
        # Leaders details
        leader_row = re.search(rf"\|\s*(#\d+)\s*\|\s*\*\*{ticker}\*\*\s*\|\s*([^|]+)\|\s*\*\*([0-9.]+%)\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", leaders_content)
        if leader_row:
            rank = leader_row.group(1).strip()
            price = leader_row.group(2).strip()
            confidence = leader_row.group(3).strip()
            target = leader_row.group(4).strip()
            volatility = leader_row.group(5).strip()
            alpha = leader_row.group(6).strip()
        else:
            rank, price, confidence, target, volatility, alpha = "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"
            
        # Confluence details
        confluence_row = re.search(rf"\|\s*\*\*{ticker}\*\*\s*\|\s*([^|]+)\|\s*\*\*(\d+)\*\*\s*\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|", confluence_content)
        if confluence_row:
            conf_price = confluence_row.group(1).strip()
            unique_domains = int(confluence_row.group(2))
            total_signals = int(confluence_row.group(3))
            domains = confluence_row.group(4).strip()
            signals = confluence_row.group(5).strip()
        else:
            conf_price, unique_domains, total_signals, domains, signals = "N/A", 0, 0, "N/A", "N/A"
            
        overlap_details.append({
            "ticker": ticker,
            "rank": rank,
            "price": price,
            "confidence": confidence,
            "target": target,
            "volatility": volatility,
            "alpha": alpha,
            "domains_count": unique_domains,
            "signals_count": total_signals,
            "domains": domains,
            "signals": signals
        })
        
    # Sort: Tier 1 (3+ domains), then Tier 2 (2 domains), then by Leaderboard Rank (1, 2, 3...)
    def get_sort_key(item):
        r_num = 99
        match = re.search(r'\d+', item['rank'])
        if match:
            r_num = int(match.group())
        return (-item['domains_count'], -item['signals_count'], r_num)
        
    overlap_details.sort(key=get_sort_key)
    
    # Non-overlap leaders
    non_overlap_leaders = [t for t in leaders_tickers if t not in overlap]
    
    # Write Overlap Report
    report_date = datetime.datetime.now().strftime('%Y-%m-%d')
    report_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with open(overlap_report_path, "w", encoding="utf-8") as f:
        f.write(f"# 📊 Cross-Report Analysis: NSE 500 Leaders & Cross-Scanner Confluence\n\n")
        f.write(f"This report analyzes the intersection of two key intelligence reports in the trading engine:\n")
        f.write(f"1. **[Top 20 NSE 500 Leaders Report](NSE500-Leaders.md)** (Generated: `{report_time}`)\n")
        f.write(f"2. **[Cross-Scanner Confluence Report](Confluence-Report.md)** (Generated: `{report_date}`)\n\n")
        
        f.write("> [gradient-style-note]\n")
        f.write("> **NSE 500 Leaders Report** ranks stocks by upward confidence and 60D alpha against Nifty using Monte Carlo GBM simulations.\n")
        f.write("> **Confluence Report** identifies stocks triggering multiple indicators across unique quantitative domains (Breakout, Pullback, Value, Volume/ML).\n\n")
        
        f.write("---\n\n")
        f.write("## 📈 Executive Summary\n\n")
        overlap_pct = (len(overlap) / len(leaders_tickers)) * 100
        f.write(f"There is a **remarkable {overlap_pct:.0f}% convergence** between the two reports: **{len(overlap)} out of the {len(leaders_tickers)} Leaders** also trigger multiple signals in the Confluence report.\n\n")
        
        f.write("## 🏆 Overlapping Stocks: Tier Classification\n\n")
        
        # Tier 1
        tier_1 = [d for d in overlap_details if d['domains_count'] >= 3]
        f.write("### 🌟 Tier 1: Super-Confluence Leaders (3+ Domains Triggered)\n")
        f.write("| Ticker | Leader Rank | GBM Confidence | 60D Alpha vs Nifty | Active Scanners / Triggers | Price |\n")
        f.write("| :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for d in tier_1:
            f.write(f"| **{d['ticker']}** | **{d['rank']}** | **{d['confidence']}** | {d['alpha']} | {d['signals']} | {d['price']} |\n")
        f.write("\n")
        
        # Tier 2
        tier_2 = [d for d in overlap_details if d['domains_count'] < 3]
        f.write("### ✨ Tier 2: Strong Confluence Leaders (2 Domains Triggered)\n")
        f.write("| Ticker | Leader Rank | GBM Confidence | 60D Alpha vs Nifty | Active Scanners / Triggers | Price |\n")
        f.write("| :--- | :---: | :---: | :---: | :--- | :--- |\n")
        for d in tier_2:
            f.write(f"| **{d['ticker']}** | **{d['rank']}** | **{d['confidence']}** | {d['alpha']} | {d['signals']} | {d['price']} |\n")
        f.write("\n---\n\n")
        
        f.write("## 🚫 Non-Overlapping Stocks\n\n")
        for ticker in non_overlap_leaders:
            conf_str = "N/A"
            match = re.search(rf"\|\s*(#\d+)\s*\|\s*\*\*{ticker}\*\*\s*\|\s*([^|]+)\|\s*\*\*([0-9.]+%)\*\*", leaders_content)
            if match:
                conf_str = f"Rank {match.group(1)} ({match.group(3)} Confidence)"
            f.write(f"- **{ticker}** ({conf_str}): Still strong momentum but might be single-factor trends rather than structured technical setups.\n")
            
    print(f"[SUCCESS] Overlap Report written to {overlap_report_path}")
    
    # Compile Telegram message
    tg_msg = f"📊 *NSE 500 Leaders & Confluence Overlap ({report_date})*\n"
    tg_msg += f"Convergence rate: *{overlap_pct:.0f}%* ({len(overlap)}/{len(leaders_tickers)} stocks)\n"
    tg_msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if tier_1:
        tg_msg += "🌟 *TIER 1: SUPER-CONFLUENCE (3+ Domains)*\n"
        for d in tier_1:
            tg_msg += f"• *{d['ticker']}* ({d['rank']}) | Conf: *{d['confidence']}* | Price: {d['price'].replace('₹', 'Rs')}\n"
            tg_msg += f"  └ Scanners: _{d['signals']}_\n"
        tg_msg += "\n"
        
    if tier_2:
        tg_msg += "✨ *TIER 2: STRONG CONFLUENCE (2 Domains)*\n"
        for d in tier_2[:8]:
            tg_msg += f"• *{d['ticker']}* ({d['rank']}) | Conf: *{d['confidence']}*\n"
        if len(tier_2) > 8:
            tg_msg += f"and {len(tier_2) - 8} more...\n"
            
    tg_msg += "\n━━━━━━━━━━━━━━━━━━━━\n👉 Full details written to `Confluence-NSE500-Leaders-Overlap.md` in Obsidian."
    
    send_telegram_message(tg_msg)
    print("[SUCCESS] Dispatch completed via Telegram.")

if __name__ == "__main__":
    run_overlap_analysis()
