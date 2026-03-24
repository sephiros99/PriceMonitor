import os
import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    if not TOKEN or not CHAT_ID:
        print("텔레그램 환경변수가 설정되지 않았습니다. (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = requests.get(url, params={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        if response.status_code == 200:
            return True

        print(f"텔레그램 전송 실패: status_code={response.status_code}, response={response.text}")
        return False
    except Exception as e:
        print(f"텔레그램 전송 실패: 예외 발생 - {e}")
        return False
