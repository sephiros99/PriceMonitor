import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re  # 정규표현식 추가
from decimal import Decimal, InvalidOperation
import os
import json
import random
import time
from urllib.parse import urlparse
from telegram_notifier import send_telegram
INPUT_FILE = "Input.json"
ALERT_STATE_FILE = "mule_alert_state.json"
MULE_ERROR_FILE_PREFIX = "mule_item_error_notified"

def clean_price(price_str):
    """
    '21만원', '8,000원', '가격미정' 등의 문자열을 정수(int)로 변환
    """
    if not price_str or "미정" in price_str or "협의" in price_str:
        return 0
    
    # 1. '만원' 단위 처리 (예: 21만원 -> 210000, 1.5만원 -> 15000)
    if '만원' in price_str:
        # 소수점을 포함한 숫자 추출
        match = re.search(r'(\d+(?:\.\d+)?)\s*만\s*원?', price_str)
        if match:
            try:
                return int((Decimal(match.group(1)) * 10000).to_integral_value())
            except (InvalidOperation, ValueError):
                return 0

        # 보조 처리: 불필요 문자를 제거한 뒤 숫자 변환 시도
        normalized = re.sub(r'[^0-9.]', '', price_str)
        if normalized:
            try:
                return int((Decimal(normalized) * 10000).to_integral_value())
            except (InvalidOperation, ValueError):
                return 0
        return 0
    
    # 2. 일반 숫자+원 처리 (예: 210,000원 -> 210000)
    num = re.sub(r'[^0-9]', '', price_str)
    return int(num) if num else 0

def parse_mule_list(soup):
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    target_dates = [
        now.strftime("%m.%d"), now.strftime("%Y-%m-%d"),
        yesterday.strftime("%m.%d"), yesterday.strftime("%Y-%m-%d")
    ]
    
    rows = soup.select('tr')
    results = []
    
    for row in rows:
        if 'notice' in row.get('class', []):
            continue
            
        regdt_td = row.select_one('td.regdt')
        if not regdt_td:
            continue
        reg_date = regdt_td.get_text(strip=True)
        
        if reg_date not in target_dates and ':' not in reg_date:
            continue
            
        title_td = row.select_one('td.title')
        if not title_td or title_td.select_one('.header-soldout'):
            continue
            
        title_a = title_td.select_one('a')
        if title_a:
            for junk in title_a.select('.mobile, .pc'):
                junk.decompose()
            
            clean_title = title_a.get_text(strip=True)
            writer_td = row.select_one("td.writer")
            writer = writer_td.get_text(strip=True) if writer_td else ""
            
            # 🌟 가격 변환 적용
            raw_price = row.select_one('td.price').get_text(strip=True) if row.select_one('td.price') else "0"
            numeric_price = clean_price(raw_price)

            results.append({
                "title": clean_title,
                "writer": writer,
                "price": numeric_price,  # 210000 형태로 저장
                "date": reg_date
            })

    return results

def get_unfiltered_market_count(soup):
    rows = soup.select("tr")
    count = 0

    for row in rows:
        if "notice" in row.get("class", []):
            continue

        title_td = row.select_one("td.title")
        regdt_td = row.select_one("td.regdt")
        if title_td and regdt_td and title_td.select_one("a"):
            count += 1

    return count

def load_alert_state():
    if not os.path.exists(ALERT_STATE_FILE):
        return {}

    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"알림 상태 파일 저장 실패: {e}")
    return {}

def save_alert_state(state):
    try:
        with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"알림 상태 파일 저장 실패: {e}")

def is_mule_url(url):
    try:
        parsed = urlparse(str(url))
        return parsed.scheme in ("http", "https") and parsed.netloc.lower() == "www.mule.co.kr"
    except Exception:
        return False

def get_item_error_file(name):
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    if not safe_name:
        safe_name = "item"
    return f"{MULE_ERROR_FILE_PREFIX}_{safe_name}.flag"

def notify_item_error_once(item_name, target_url, reason, telegram_sender):
    error_file = get_item_error_file(item_name)
    if os.path.exists(error_file):
        print(f"{item_name} 오류 알림 미전송: 이미 이전 실패에서 오류 알림을 전송했습니다.")
        return

    msg = f"{item_name} 오류: {reason}\n{target_url}"
    sent = telegram_sender(msg)
    if sent:
        with open(error_file, "w", encoding="utf-8") as f:
            f.write("1")
        print(f"{item_name} 오류 알림 전송: {reason}")
    else:
        print(f"{item_name} 오류 알림 전송 실패: 다음 실행에서 다시 시도합니다.")

def clear_item_error_notified(item_name):
    error_file = get_item_error_file(item_name)
    if os.path.exists(error_file):
        os.remove(error_file)
        print(f"{item_name} 성공 실행 감지: 오류 알림 상태를 초기화합니다.")

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

        name = item.get("name")
        url = item.get("url")
        threshold = item.get("threshold")

        if not name or not url or threshold is None:
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목에 name, url, threshold가 모두 필요합니다.")
            continue

        try:
            if not is_mule_url(url):
                print(f"입력 파일 형식 오류: {idx + 1}번째 항목의 url은 www.mule.co.kr 주소만 허용됩니다.")
                continue
        except Exception:
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목의 url 파싱에 실패했습니다.")
            continue

        try:
            threshold = int(threshold)
        except Exception:
            print(f"입력 파일 형식 오류: {idx + 1}번째 항목의 threshold는 숫자여야 합니다.")
            continue

        items.append({
            "name": str(name),
            "url": str(url),
            "threshold": threshold
        })

    if len(items) == 0:
        print("처리 가능한 입력 항목이 없습니다.")
        return None

    return items

def process_item(item, alert_state, telegram_sender):
    
    sleep_seconds = random.randint(30, 60)
    print(f"ITEM 시작 전 랜덤 대기: {sleep_seconds}초")
    time.sleep(sleep_seconds)
    
    item_name = item["name"]
    url = item["url"]
    threshold = item["threshold"]

    if threshold <= 0:
        print(f"{item_name} 처리 건너뜀: threshold는 0보다 커야 합니다.")
        return

    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    }

    scraper = cloudscraper.create_scraper() 
    try:
        res = scraper.get(url, headers=mobile_headers, timeout=10)
        
        if res.status_code != 200:
            reason = f"페이지 접근 실패(status_code={res.status_code})"
            print(f"{item_name} 알람 미전송: {reason}")
            notify_item_error_once(item_name, url, reason, telegram_sender)
            return

        soup = BeautifulSoup(res.text, 'html.parser')
        unfiltered_count = get_unfiltered_market_count(soup)
        if unfiltered_count == 0:
            reason = "파싱 실패: URL 결과 원본 목록이 0개입니다."
            print(f"{item_name} 알람 미전송: {reason}")
            notify_item_error_once(item_name, url, reason, telegram_sender)
            return

        clear_item_error_notified(item_name)

        valid_items = parse_mule_list(soup)
        if item_name not in alert_state or not isinstance(alert_state[item_name], dict):
            alert_state[item_name] = {}

        if not valid_items:
            print(f"{item_name}: 조건에 맞는 새로운 매물이 없습니다.")
        else:
            for market_item in valid_items:
                # 출력 시 천 단위 콤마를 찍고 싶으시면 {item['price']:,} 를 사용하세요.
                print(f"{item_name} [{market_item['date']}] {market_item['title']} / {market_item['writer']} -> {market_item['price']}")

                current_price = market_item["price"]
                title = market_item["title"]
                writer = market_item.get("writer", "")
                title_writer_key = f"{title}||{writer}"
                if current_price <= 0 or current_price > threshold:
                    continue

                last_notified_price = alert_state[item_name].get(title_writer_key)
                should_send = False
                if last_notified_price is None:
                    should_send = True
                elif current_price < int(last_notified_price):
                    should_send = True

                if not should_send:
                    print(
                        f"{item_name} 알림 미전송: '{title}' / '{writer}'는 이전 알림가({int(last_notified_price):,}원) 이하로 내려가지 않았습니다."
                    )
                    continue

                msg = (
                        f"[MuleMonitor] {item_name}\n"
                        f"{title}\n"
                        f"작성자: {writer}\n"
                        f"가격: {current_price:,}원 (기준가: {threshold:,}원)\n"
                        f"등록일: {market_item['date']}\n"
                        f"{url}"
                    )
                sent = telegram_sender(msg)
                if sent:
                    print(f"{item_name} 알림 전송: '{title}' / '{writer}' / {current_price:,}원")
                    alert_state[item_name][title_writer_key] = current_price
                else:
                    print(f"{item_name} 알림 전송 실패: '{title}' / '{writer}'")
            
    except Exception as e:
        reason = f"요청/파싱 중 예외 발생: {e}"
        print(f"{item_name} 알람 미전송: {reason}")
        notify_item_error_once(item_name, url, reason, telegram_sender)

def process_items(input_items, telegram_sender=send_telegram):
    if input_items is None:
        return

    mule_items = []
    for item in input_items:
        if not isinstance(item, dict):
            continue
        if is_mule_url(item.get("url")):
            mule_items.append(item)

    if len(mule_items) == 0:
        return

    alert_state = load_alert_state()
    for item in mule_items:
        process_item(item, alert_state, telegram_sender)
    save_alert_state(alert_state)

def main():
    input_items = load_input()
    if input_items is None:
        return

    process_items(input_items)

if __name__ == "__main__":
    main()
