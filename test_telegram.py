import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

if not token:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN first.")
if not chat_id:
    raise SystemExit("Set TELEGRAM_CHAT_ID first.")

url = f"https://api.telegram.org/bot{token}/sendMessage"

r = requests.post(
    url,
    json={
        "chat_id": chat_id,
        "text": "DAS Eero sauna monitor: Telegram notifications are working.",
    },
    timeout=20,
)

print(r.status_code)
print(r.text)
r.raise_for_status()
