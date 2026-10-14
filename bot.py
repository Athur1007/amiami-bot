import sqlite3
import re
import requests
import time
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

# DÁN WEBHOOK URL CỦA BẠN VÀO ĐÂY
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# CẤU HÌNH SỐ TRANG MUỐN QUÉT (Mỗi trang 60 figure)
MAX_PAGES = 3 

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
    # 1. Xử lý giới hạn 256 ký tự của Discord cho tiêu đề
    safe_title = f"🔔 {title_vi}"
    if len(safe_title) > 250:
        safe_title = safe_title[:247] + "..." 
        
    # 2. Xử lý giới hạn 1024 ký tự cho phần tên gốc
    safe_title_ja = title_ja
    if len(safe_title_ja) > 1000:
        safe_title_ja = safe_title_ja[:997] + "..."

    # 3. Vá lỗi thiếu https: trong link ảnh
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
        browser = p.chromium.launch(headless=False) 
        page = browser.new_page()

        # Vòng lặp chạy qua từng trang (Từ trang 1 đến MAX_PAGES)
        for page_num in range(1, MAX_PAGES + 1):
            print(f"\n=================== ĐANG QUÉT TRANG {page_num}/{MAX_PAGES} ===================")
            
            # Đã thêm &s_cate_tag=1 (Chỉ lấy Figure), s_sortkey=regtimed (Mới nhất) và pagemax=60
            url = f"https://slist.amiami.jp/top/search/list?s_st_list_preorder_available=1&s_cate_tag=1&s_sortkey=regtimed&pagemax=60&getcnt=0&pagecnt={page_num}"
            page.goto(url)

            try:
                page.wait_for_selector('.product_box', timeout=15000)
            except Exception:
                print(f"Trang {page_num} tải quá chậm hoặc không còn sản phẩm. Dừng quét!")
                break

            products = page.locator('.product_box > a')
            count = products.count()
            print(f"Tìm thấy {count} figure trên trang {page_num}. Đang đối chiếu Database...\n")

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
                        print("   -> Lỗi dịch thuật. Dùng tạm tên gốc!")
                        title_vi = title_ja

                    print(f"🌟 [MỚI - Trang {page_num}] {title_vi}")
                    
                    send_to_discord(title_vi, title_ja, price, link, img_url)
                    
                    cursor.execute(
                        "INSERT INTO amiami_preorder (gcode, title_ja, title_vi, price, link, image_url) VALUES (?, ?, ?, ?, ?, ?)", 
                        (gcode, title_ja, title_vi, price, link, img_url)
                    )
                    conn.commit()
                else:
                    print(f"➖ [Đã quét] {title_ja[:30]}... (Bỏ qua)")

            # Nghỉ 3 giây trước khi lật sang trang tiếp theo
            if page_num < MAX_PAGES:
                print(f"\nĐã xong trang {page_num}. Nghỉ 3 giây trước khi sang trang {page_num + 1}...")
                time.sleep(3)

        print("\nHoàn tất toàn bộ quá trình! Đóng trình duyệt.")
        browser.close()
        conn.close()

if __name__ == "__main__":
    scrape_amiami_jp()
