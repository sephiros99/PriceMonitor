import os
import json
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo
import MuleMonitor
import ElevenstMonitor
from telegram_notifier import send_telegram

INPUT_FILE = "Input.json"
ERROR_STATE_FILE = "error_notified.flag"

def is_error_notified():
    return os.path.exists(ERROR_STATE_FILE)

def mark_error_notified():
    with open(ERROR_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("1")

def clear_error_notified():
    if os.path.exists(ERROR_STATE_FILE):
        os.remove(ERROR_STATE_FILE)

def load_input():
    if not os.path.exists(INPUT_FILE):
        print(f"입력 파일이 없습니다: {INPUT_FILE}")
        return None

    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"입력 파일을 읽지 못했습니다: {e}")
        return None

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        print("입력 파일 형식 오류: 객체 또는 객체 배열이어야 합니다.")
        return None

    items = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목이 객체가 아닙니다.")
            continue

        url = item.get("url")
        threshold = item.get("threshold")
        name = item.get("name")

        if not url or threshold is None or not name:
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목에 url, threshold, name이 모두 필요합니다.")
            continue

        try:
            threshold = int(threshold)
        except Exception:
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목의 threshold는 숫자여야 합니다.")
            continue

        items.append(
            {
                "url": url,
                "threshold": threshold,
                "name": name
            }
        )

    if len(items) == 0:
        print("처리 가능한 입력 항목이 없습니다.")
        return None

    return items


def main():
    seoul_now = datetime.now(ZoneInfo("Asia/Seoul"))
    if seoul_now.hour >= 23 or seoul_now.hour < 8:
        print(f"서울 시간 {seoul_now.strftime('%Y-%m-%d %H:%M:%S')} - 비작동 시간대(23:00~08:00)라서 종료합니다.")
        return

    sleep_seconds = random.randint(1, 10)
    print(f"시작 전 랜덤 대기: {sleep_seconds}초")
    time.sleep(sleep_seconds)

    input_items = load_input()
    if input_items is None:
        return

    eleven_st_items = []
    mule_items = []
    for item in input_items:
        if ElevenstMonitor.is_11st_url(item["url"]):
            eleven_st_items.append(item)
        elif MuleMonitor.is_mule_url(item["url"]):
            mule_items.append(item)

    ElevenstMonitor.process_items(eleven_st_items, send_telegram)
    MuleMonitor.process_items(mule_items, send_telegram)

if __name__ == "__main__":
    try:
        main()
        if is_error_notified():
            print("성공 실행 감지: 오류 알림 상태를 초기화합니다.")
            clear_error_notified()
    except Exception as e:
        error_msg = f"실행 오류 발생: {e}"
        print(error_msg)

        if is_error_notified():
            print("오류 알림 미전송: 이미 이전 실패에서 오류 알림을 전송했습니다.")
        else:
            sent = send_telegram(error_msg)
            if sent:
                print("오류 알림 전송: 텔레그램으로 오류 메시지를 보냈습니다.")
                mark_error_notified()
            else:
                print("오류 알림 전송 실패: 다음 실행에서 다시 시도합니다.")
