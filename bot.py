import os
import sqlite3
import re
import requests
import time
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

# Lấy Webhook từ GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

MAX_PAGES = 2 

def setup_database():
    conn = sqlite3.connect('figures.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS amiami_preorder (
            gcode TEXT PRIMARY KEY,
            title_ja TEXT,
            title_vi TEXT,
            price TEXT,
            link TEXT,
            image_url TEXT
        )
    ''')
    conn.commit()
    return conn

def send_to_discord(title_vi, title_ja, price, link, img_url):
    safe_title = f"🔔 {title_vi}"
    if len(safe_title) > 250:
        safe_title = safe_title[:247] + "..." 
        
    safe_title_ja = title_ja
    if len(safe_title_ja) > 1000:
        safe_title_ja = safe_title_ja[:997] + "..."

    if img_url and img_url.startswith("//"):
        img_url = "https:" + img_url

    data = {
        "embeds": [
            {
                "title": safe_title,
                "url": link,
                "color": 16744192, 
                "fields": [
                    {"name": "💰 Giá", "value": f"**{price}** Yên", "inline": True},
                    {"name": "🇯🇵 Tên gốc", "value": safe_title_ja, "inline": False}
                ],
                "image": {"url": img_url},
                "footer": {"text": "AmiAmi Pre-order Bot"}
            }
        ]
    }
    
    response = requests.post(DISCORD_WEBHOOK_URL, json=data)
    if response.status_code == 204:
        print("   -> Đã gửi thông báo Discord thành công!")
    else:
        print(f"   -> Lỗi gửi Discord: {response.status_code}\n{response.text}")

def scrape_amiami_jp():
    conn = setup_database()
    cursor = conn.cursor()
    translator = GoogleTranslator(source='ja', target='vi')

    with sync_playwright() as p:
        # Bắt buộc để headless=True trên GitHub Actions
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for page_num in range(1, MAX_PAGES + 1):
            print(f"\n=================== ĐANG QUÉT TRANG {page_num}/{MAX_PAGES} ===================")
            url = f"https://slist.amiami.jp/top/search/list?s_st_list_preorder_available=1&s_cate_tag=1&s_sortkey=regtimed&pagemax=60&getcnt=0&pagecnt={page_num}"
            page.goto(url)

            try:
                page.wait_for_selector('.product_box', timeout=20000)
            except Exception:
                print(f"Trang {page_num} tải quá chậm hoặc không có dữ liệu. Dừng quét!")
                break

            products = page.locator('.product_box > a')
            count = products.count()
            print(f"Tìm thấy {count} figure trên trang {page_num}.\n")

            for i in range(count):
                item = products.nth(i)
                title_ja = item.locator('.product_name_inner').inner_text().strip()
                price = item.locator('.product_price').inner_text().strip()
                link = item.get_attribute('href')
                
                if link and not link.startswith('http'):
                    link = f"https://www.amiami.jp{link}"
                
                img_element = item.locator('.product_img img')
                img_url = img_element.get_attribute('data-src') or img_element.get_attribute('src')
                
                match = re.search(r'gcode=([^&]+)', link)
                gcode = match.group(1) if match else f"UNKNOWN-{page_num}-{i}"
                
                cursor.execute("SELECT gcode FROM amiami_preorder WHERE gcode = ?", (gcode,))
                exists = cursor.fetchone()
                
                if not exists:
                    try:
                        time.sleep(3) 
                        title_vi = translator.translate(title_ja)
                    except Exception:
                        title_vi = title_ja

                    print(f"🌟 [MỚI] {title_vi}")
                    send_to_discord(title_vi, title_ja, price, link, img_url)
                    
                    cursor.execute(
                        "INSERT INTO amiami_preorder (gcode, title_ja, title_vi, price, link, image_url) VALUES (?, ?, ?, ?, ?, ?)", 
                        (gcode, title_ja, title_vi, price, link, img_url)
                    )
                    conn.commit()
                else:
                    print(f"➖ [Đã quét] {title_ja[:30]}...")

            if page_num < MAX_PAGES:
                time.sleep(3)

        browser.close()
        conn.close()

if __name__ == "__main__":
    scrape_amiami_jp()
