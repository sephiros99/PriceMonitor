import requests
from bs4 import BeautifulSoup
import os
import json
import re

# 환경 변수 (GitHub Secrets에서 설정)
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
INPUT_FILE = "Input.json"
PRICE_FILE_PREFIX = "last_price"

def get_11st_price(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        meta_tag = soup.find("meta", property="og:description")
        if meta_tag:
            content = meta_tag["content"] # "..., 가격 : 59,900원"
            match = re.search(r"가격\s*:\s*([\d,]+)", content)
            if match:
                price_text = match.group(1).replace(",", "")
                price = int(price_text)
                print(price) # 59900
                return price
            print("정규식으로 가격을 찾지 못했습니다.")
            return None
        else:
            print("가격을 찾을 수 없습니다. HTML 구조를 다시 확인해주세요.")
            return None
            
    except Exception as e:
        print(f"오류 발생: {e}")
        return None

def send_telegram(msg):
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

def get_price_file(name):
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    if not safe_name:
        safe_name = "item"
    return f"{PRICE_FILE_PREFIX}_{safe_name}.txt"

def process_item(item):
    target_url = item["url"]
    threshold = item["threshold"]
    product_name = item["name"]
    price_file = get_price_file(product_name)

    print(f"\n처리 시작: {product_name}")

    current_price = None
    if "11st.co.kr" in target_url:
        current_price = get_11st_price(target_url)
    else:
        print(f"{product_name} 알람 미전송: 11번가 URL이 아니어서 가격 조회를 건너뜁니다.")
        return

    if current_price is None:
        print(f"{product_name} 알람 미전송: 현재 가격을 가져오지 못했습니다.")
        return

    # 이전 가격 읽기 (없거나 읽기 실패 시 None)
    last_price = None
    if os.path.exists(price_file):
        try:
            with open(price_file, "r") as f:
                last_price = int(f.read().strip())
        except Exception:
            print(f"{product_name} last_price 파일을 읽지 못해 이전 가격을 None으로 처리합니다.")
            last_price = None

    print(f"{product_name} 디버그: current_price={current_price}, threshold={threshold}, last_price={last_price}")

    # 1) 현재 가격이 기준가보다 낮을 때
    if current_price < threshold:
        should_send = False
        if last_price is None:
            should_send = True
        elif current_price < last_price:
            should_send = True

        if should_send:
            msg = f"{product_name} : {current_price}원\n{target_url}"
            sent = send_telegram(msg)
            if sent:
                print(f"{product_name} 알람 전송: 기준가 이하이며 알림 조건을 만족했습니다.")
                with open(price_file, "w") as f:
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

    # 2) 현재 가격이 기준가보다 높을 때 + 마지막 가격이 있으면 삭제
    if current_price > threshold:
        if last_price is not None and os.path.exists(price_file):
            os.remove(price_file)
            print(f"{product_name} 알람 미전송: 기준가보다 높아 last_price 파일을 삭제했습니다.")
        else:
            print(f"{product_name} 알람 미전송: 기준가보다 높고 삭제할 last_price 파일이 없습니다.")
        return

    # 현재 가격이 기준가와 같은 경우에는 아무 작업도 하지 않음
    print(f"{product_name} 알람 미전송: 현재 가격이 기준가와 같습니다.")

def main():
    input_items = load_input()
    if input_items is None:
        return

    for item in input_items:
        process_item(item)

if __name__ == "__main__":
    main()
