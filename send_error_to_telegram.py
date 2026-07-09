import os
import requests

def main():
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    
    if not token or not chat_id:
        print("Telegram credentials not configured in env.")
        return
        
    if not os.path.exists("run.log"):
        print("run.log not found.")
        return
        
    with open("run.log", "r", encoding="utf-8") as f:
        log_content = f.read()
        
    # Take the last 3500 characters to fit inside Telegram's 4096 character limit
    tail_log = log_content[-3500:]
    
    message = f"🚨 *GitHub Action Failed: Multi-Strategy Scanner*\n\n*Error/Traceback Log tail:*\n```\n{tail_log}\n```"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response status: {r.status_code}")
        if r.status_code != 200:
            print(r.text)
    except Exception as e:
        print(f"Failed to dispatch Telegram error message: {e}")

if __name__ == "__main__":
    main()
