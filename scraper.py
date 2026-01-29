import os
import time
import requests
from playwright.sync_api import sync_playwright

class OikotieScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start_browser(self, headless=True):
        self.playwright = sync_playwright().start()
        try:
            # Launch options - sometimes args help
            self.browser = self.playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
            )
        except Exception as e:
            print(f"Failed to launch browser: {e}")
            raise e
        # Use a real user agent
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        self.page = self.context.new_page()

    def close_browser(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def accept_cookies(self):
        try:
            # Wait a bit for banner
            time.sleep(3)
            
            # Common pattern: check for button with text
            try:
                # Try locating deeply or in frames if needed, but start simple
                # Using a more generic selector might help if 'button' is not the specific tag
                consent_btn = self.page.get_by_text("Hyväksy kaikki", exact=False).first
                if consent_btn.is_visible():
                    consent_btn.click()
                    print("Cookies accepted (via get_by_text).")
                    return
            except Exception:
                pass
                
            # Fallback: specific input/button selector if text fails (could be ID based in future)
            # For now, just continue if not found.
            print("Cookie banner not found or could not be clicked.")
            
        except Exception as e:
            print(f"Error handling cookies: {e}")

    def get_property_links(self, limit=5):
        url = "https://asunnot.oikotie.fi/myytavat-asunnot?cardType=100"
        try:
            self.page.goto(url, timeout=60000)
        except Exception as e:
            print(f"Navigation timeout/error: {e}")
            self.page.screenshot(path="debug_nav_error.png")
            return []

        self.accept_cookies()
        
        links = set()
        retries = 0
        
        while len(links) < limit and retries < 5:
            # Wait for cards to likely appear
            try:
                self.page.wait_for_selector("a.ot-card-v3", timeout=10000)
            except:
                print("Waiting for cards timed out.")
                # self.page.screenshot(path=f"debug_list_timeout_{retries}.png")
            
            # Scroll to load more
            self.page.mouse.wheel(0, 1000)
            time.sleep(2) 
            
            # Extract links
            cards = self.page.query_selector_all("a.ot-card-v3")
            for card in cards:
                href = card.get_attribute("href")
                if href:
                    links.add(href)
                if len(links) >= limit:
                    break
            
            print(f"Found {len(links)} links so far...")
            
            if not cards:
                retries += 1
                print(f"No cards found, retrying scroll... ({retries}/5)")
            else:
                retries = 0 # Reset retries if we found something
            
        return list(links)[:limit]

    def extract_property_details(self, url):
        self.page.goto(url)
        time.sleep(2) # Wait for potential dynamic content
        
        details = {"url": url}
        
        # Helper to find value by label
        # The structure is often dt -> dd. We look for the dt with specific text.
        text_fields = {
            "Velaton hinta": "price",
            "Asuinpinta-ala": "area",
            "Huoneita": "rooms",
            "Kerroksia": "floor",
            "Rakennusvuosi": "year",
            "Rakennuksen tyyppi": "type",
            "Kaupunginosa": "district",
            "Kaupunki": "city"
        }

        for label, key in text_fields.items():
            try:
                # Find dt containing the label
                # We use XPath to find the dt that contains the text, then get following sibling
                xpath = f"//dt[contains(., '{label}')]/following-sibling::dd[1]"
                element = self.page.query_selector(xpath)
                if element:
                    details[key] = element.inner_text().strip()
                else:
                    details[key] = "N/A"
            except Exception:
                details[key] = "Error"

        # Images
        image_urls = []
        try:
            # Click gallery button to ensure all loads, but don't crash if it fails
            try:
                # Wait briefly for button
                gallery_btn = self.page.wait_for_selector("button.open-galleria", timeout=3000)
                if gallery_btn and gallery_btn.is_visible():
                    gallery_btn.click(timeout=3000)
                    time.sleep(1) # Allow gallery to render
            except Exception as e:
                print(f"Gallery button interaction failed: {e}")
            
            # Extract high-res images from prod mediabank
            # We scan all imgs on page (including inside gallery if opened)
            # Use JS to grab all srcs quickly
            imgs = self.page.evaluate("""() => {
                return Array.from(document.querySelectorAll('img')).map(img => img.src);
            }""")
            
            for src in imgs:
                if src and "ot-real-estate-mediabank-prod" in src:
                    # Filter out small thumbnails if possible
                    # Clean up URL parameters if needed, but usually src is enough
                    if src not in image_urls:
                        image_urls.append(src)
                        
            print(f"Found {len(image_urls)} images.")
            
        except Exception as e:
            print(f"Error extracting images: {e}")
            
        details["image_urls"] = image_urls
        return details

    def download_images(self, image_urls, folder):
        if not os.path.exists(folder):
            os.makedirs(folder)
            
        count = 0
        for i, url in enumerate(image_urls):
            try:
                response = requests.get(url, stream=True)
                if response.status_code == 200:
                    ext = url.split('.')[-1].split('?')[0]
                    if len(ext) > 4 or not ext: ext = "jpg"
                    
                    filename = f"image_{i+1}.{ext}"
                    filepath = os.path.join(folder, filename)
                    
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    count += 1
            except Exception as e:
                print(f"Failed to download {url}: {e}")
        return count
