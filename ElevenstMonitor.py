import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import urlparse
from telegram_notifier import send_telegram

PRICE_FILE_PREFIX = "last_price"
ERROR_FILE_PREFIX = "item_error_notified"

def is_11st_url(url):
    try:
        parsed = urlparse(str(url))
        host = parsed.netloc.lower()
        return parsed.scheme in ("http", "https") and ("11st.co.kr" in host)
    except Exception:
        return False

def get_11st_price(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None, f"페이지 접근 실패(status_code={res.status_code})"

        soup = BeautifulSoup(res.text, "html.parser")

        meta_tag = soup.find("meta", property="og:description")
        if meta_tag:
            content = meta_tag["content"]
            match = re.search(r"가격\s*:\s*([\d,]+)", content)
            if match:
                price_text = match.group(1).replace(",", "")
                price = int(price_text)
                print(price)
                return price, None
            return None, "정규식으로 가격 파싱 실패"
        return None, "가격 메타 태그를 찾지 못함"

    except Exception as e:
        return None, f"요청/파싱 중 예외 발생: {e}"

def get_price_file(name):
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    if not safe_name:
        safe_name = "item"
    return f"{PRICE_FILE_PREFIX}_{safe_name}.txt"

def get_item_error_file(name):
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    if not safe_name:
        safe_name = "item"
    return f"{ERROR_FILE_PREFIX}_{safe_name}.flag"

def notify_item_error_once(product_name, target_url, reason, telegram_sender):
    error_file = get_item_error_file(product_name)
    if os.path.exists(error_file):
        print(f"{product_name} 오류 알림 미전송: 이미 이전 실패에서 오류 알림을 전송했습니다.")
        return

    msg = f"{product_name} 오류: {reason}\n{target_url}"
    sent = telegram_sender(msg)
    if sent:
        with open(error_file, "w", encoding="utf-8") as f:
            f.write("1")
        print(f"{product_name} 오류 알림 전송: {reason}")
    else:
        print(f"{product_name} 오류 알림 전송 실패: 다음 실행에서 다시 시도합니다.")

def clear_item_error_notified(product_name):
    error_file = get_item_error_file(product_name)
    if os.path.exists(error_file):
        os.remove(error_file)
        print(f"{product_name} 성공 실행 감지: 오류 알림 상태를 초기화합니다.")

def process_item(item, telegram_sender):
    target_url = item["url"]
    threshold = item["threshold"]
    product_name = item["name"]
    price_file = get_price_file(product_name)

    print(f"\n처리 시작: {product_name}")

    current_price, price_error = get_11st_price(target_url)
    if current_price is None:
        if price_error is None:
            price_error = "현재 가격을 가져오지 못했습니다."
        print(f"{product_name} 알람 미전송: {price_error}")
        notify_item_error_once(product_name, target_url, price_error, telegram_sender)
        return

    clear_item_error_notified(product_name)

    last_price = None
    if os.path.exists(price_file):
        try:
            with open(price_file, "r", encoding="utf-8") as f:
                last_price = int(f.read().strip())
        except Exception:
            print(f"{product_name} last_price 파일을 읽지 못해 이전 가격을 None으로 처리합니다.")
            last_price = None

    print(f"{product_name} 디버그: current_price={current_price}, threshold={threshold}, last_price={last_price}")

    if current_price < threshold:
        should_send = False
        if last_price is None:
            should_send = True
        elif current_price < last_price:
            should_send = True

        if should_send:
            msg = f"{product_name} : {current_price}원\n{target_url}"
            sent = telegram_sender(msg)
            if sent:
                print(f"{product_name} 알람 전송: 기준가 이하이며 알림 조건을 만족했습니다.")
                with open(price_file, "w", encoding="utf-8") as f:
                    f.write(str(current_price))
                print(f"{product_name} last_price 저장: {current_price}")
            else:
                print(f"{product_name} 알람 미전송: 텔레그램 전송에 실패했습니다.")
        else:
            if last_price is not None and current_price >= last_price:
                print(f"{product_name} 알람 미전송: 기준가 이하지만 이전 알림 가격보다 낮아지지 않았습니다.")
            else:
                print(f"{product_name} 알람 미전송: 알림 조건을 만족하지 않았습니다.")
        return

    if current_price > threshold:
        if last_price is not None and os.path.exists(price_file):
            os.remove(price_file)
            print(f"{product_name} 알람 미전송: 기준가보다 높아 last_price 파일을 삭제했습니다.")
        else:
            print(f"{product_name} 알람 미전송: 기준가보다 높고 삭제할 last_price 파일이 없습니다.")
        return

    print(f"{product_name} 알람 미전송: 현재 가격이 기준가와 같습니다.")

def process_items(input_items, telegram_sender=send_telegram):
    if input_items is None:
        return

    for item in input_items:
        if not isinstance(item, dict):
            continue
        if not is_11st_url(item.get("url")):
            continue
        process_item(item, telegram_sender)
