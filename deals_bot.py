import html
import json
import os
import random
import re
import time
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = "@zezosa1"

NOON_MINUTES_MAX_PRICE = 1.0     # نون مينتس: ريال وأقل
NOON_REGULAR_MIN_DISC = 35       # نون العادي: خصم 35% وفوق
NOON_SUPERMALL_MIN_DISC = 30     # نون سوبر مول: خصم 30% وفوق
AMAZON_MIN_DISC = 30             # أمازون السعودية: خصم 30% وفوق

LAT = "24.7136"
LNG = "46.6753"
SENT_FILE = "sent_deals.json"

AMAZON_URLS = [
    "https://www.amazon.sa/s?i=electronics&rh=n%3A12463162031&s=popularity-rank",
    "https://www.amazon.sa/s?k=%D8%B9%D8%B1%D9%88%D8%B6&s=price-asc-rank",
]

NOON_ENDPOINTS = [
    {
        "name": "⚡ نون مينتس (أبو ريال)",
        "url": "https://www.noon.com/_svc/catalog/api/v3/u/minutes-sa/?sort%5Bby%5D=price&sort%5Bdir%5D=asc&limit=50",
        "mp": "minutes",
        "max_price": NOON_MINUTES_MAX_PRICE,
        "min_discount": 0,
    },
    {
        "name": "🟡 نون العادي",
        "url": "https://www.noon.com/_svc/catalog/api/v3/u/deals-sa/?limit=50",
        "mp": "noon",
        "max_price": None,
        "min_discount": NOON_REGULAR_MIN_DISC,
    },
    {
        "name": "🟣 نون سوبر مول",
        "url": "https://www.noon.com/_svc/catalog/api/v3/u/supermall-sa/?limit=50",
        "mp": "supermall",
        "max_price": None,
        "min_discount": NOON_SUPERMALL_MIN_DISC,
    },
]


def load_sent():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_sent(sent_ids):
    trimmed = list(sent_ids)[-2000:]
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False)


def parse_price(text):
    if not text:
        return None
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
    clean = text.translate(arabic_digits).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", clean)
    return float(match.group()) if match else None


def send_telegram(store_label, title, price, old_price, discount, link):
    safe_title = html.escape(title)
    price_line = f"💰 <b>السعر الآن:</b> {price:.2f} ريال"
    if old_price and old_price > price:
        price_line += f"\n❌ <b>قبل الخصم:</b> <s>{old_price:.2f} ريال</s>"
    if discount > 0:
        price_line += f"\n🔥 <b>الخصم:</b> {discount}%"

    msg = (
        f"<b>{store_label}</b>\n\n"
        f"📦 {safe_title}\n\n"
        f"{price_line}\n\n"
        f"🔗 <a href='{link}'>رابط المنتج المباشر</a>"
    )

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            api_url,
            data={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[Telegram Error] {r.status_code}: {r.text}")
        else:
            print(f"[Telegram] تم إرسال: {title[:40]}")
            time.sleep(1.5)
    except Exception as e:
        print(f"[Telegram Exception] {e}")


def check_noon(sent_ids):
    session = cffi_requests.Session(impersonate="chrome")
    for ep in NOON_ENDPOINTS:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "x-locale": "ar-sa",
            "x-platform": "web",
            "x-mp": ep["mp"],
            "x-lat": LAT,
            "x-lng": LNG,
            "Referer": "https://www.noon.com/saudi-ar/",
        }
        try:
            resp = session.get(ep["url"], headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"[Noon Warning] {ep['name']} رجع كود {resp.status_code}")
                continue

            data = resp.json()
            hits = data.get("hits", [])
            print(f"[Noon] {ep['name']} - تم فحص {len(hits)} منتج")

            for item in hits:
                sku = item.get("sku")
                if not sku:
                    continue
                unique_id = f"noon_{ep['mp']}_{sku}"
                if unique_id in sent_ids:
                    continue

                raw_price = item.get("price")
                sale_price = item.get("sale_price")
                if raw_price is None:
                    continue

                old_price = float(raw_price)
                current_price = float(sale_price) if sale_price else old_price

                discount = 0
                if old_price > current_price > 0:
                    discount = round((1 - (current_price / old_price)) * 100)

                matched = False
                if ep["max_price"] is not None:
                    if 0 < current_price <= ep["max_price"]:
                        matched = True
                else:
                    if discount >= ep["min_discount"]:
                        matched = True

                if matched:
                    name = item.get("name", "منتج بدون اسم")
                    slug = item.get("url", "product")
                    link = f"https://www.noon.com/saudi-ar/{slug}/{sku}/p/"
                    send_telegram(ep["name"], name, current_price, old_price, discount, link)
                    sent_ids.add(unique_id)

            time.sleep(random.uniform(2, 5))
        except Exception as e:
            print(f"[Noon Error] {ep['name']}: {e}")


def check_amazon(sent_ids):
    session = cffi_requests.Session(impersonate="chrome")
    for url in AMAZON_URLS:
        headers = {
            "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.amazon.sa/",
        }
        try:
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code != 200 or "captcha" in resp.text.lower():
                print(f"[Amazon Warning] كود {resp.status_code} أو كابتشا")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select('[data-component-type="s-search-result"]')
            print(f"[Amazon] تم فحص {len(cards)} منتج")

            for card in cards:
                asin = card.get("data-asin")
                if not asin:
                    continue
                unique_id = f"amz_{asin}"
                if unique_id in sent_ids:
                    continue

                title_el = card.select_one("h2 span")
                cur_el = card.select_one(".a-price:not(.a-text-price) .a-offscreen")
                old_el = card.select_one(".a-price.a-text-price .a-offscreen")

                if not (title_el and cur_el and old_el):
                    continue

                current_price = parse_price(cur_el.get_text())
                old_price = parse_price(old_el.get_text())

                if not current_price or not old_price or old_price <= current_price:
                    continue

                discount = round((1 - (current_price / old_price)) * 100)
                if discount >= AMAZON_MIN_DISC:
                    title = title_el.get_text(strip=True)
                    link = f"https://www.amazon.sa/dp/{asin}"
                    send_telegram("🟠 أمازون السعودية", title, current_price, old_price, discount, link)
                    sent_ids.add(unique_id)

            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"[Amazon Error] {e}")


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود في Secrets")
        return
    print("🚀 جولة فحص سحابية بدأت...")
    sent_ids = load_sent()
    check_noon(sent_ids)
    check_amazon(sent_ids)
    save_sent(sent_ids)
    print("✅ انتهت الجولة بنجاح")


if __name__ == "__main__":
    main()
