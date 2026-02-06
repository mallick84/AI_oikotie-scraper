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
        
        # Mapping of requested fields to Finnish labels found during research
        text_fields = {
            "Rakennusvuosi": "year",
            "Rakennuksen tyyppi": "type",
            "Asuinpinta-ala": "area",
            "Kaupunginosa": "district",
            "Kaupunki": "city",
            "Sijainti": "address", # Osoite mapping
            "Myyntihinta": "sale_price",
            "Velaton hinta": "price",
            "Tehdyt remontit": "renovations",
            "Kiinteistötunnus": "property_id",
            "Rakennusmateriaali": "building_material",
            "Kattomateriaali": "roof_material",
            "Kattotyyppi": "roof_type",
            "Energiatodistus": "energy_certificate",
            "Energialuokka": "energy_class",
            "Lämmitys": "heating",
            "Lisätietoja lämmityksestä": "heat_distribution"
        }

        # Extract text fields
        for label, key in text_fields.items():
            try:
                # Find dt containing the label accurately
                xpath = f"//dt[contains(., '{label}')]/following-sibling::dd[1]"
                element = self.page.query_selector(xpath)
                if element:
                    details[key] = element.inner_text().strip()
                else:
                    details[key] = "N/A"
            except Exception:
                details[key] = "Error"

        # Contact Info
        try:
            # Name
            name_el = self.page.locator(".listing-person__details-item, .listing-person__name").first
            details["contact_name"] = name_el.inner_text().strip() if name_el.count() > 0 else "N/A"
            
            # Agency Info
            agency_addr = self.page.locator(".listing-agency__address, .company-info").first
            details["contact_agency_address"] = agency_addr.inner_text().strip() if agency_addr.count() > 0 else "N/A"
            
            # Email (search for mailto)
            email_el = self.page.locator("a[href^='mailto:']").first
            details["contact_email"] = email_el.get_attribute("href").replace("mailto:", "") if email_el.count() > 0 else "N/A"
            
            # Phone (requires click)
            phone_btn = self.page.get_by_text("Näytä numero", exact=False).first
            if phone_btn.count() > 0 and phone_btn.is_visible():
                phone_btn.click()
                time.sleep(1.5)
                # After click, look for the revealed number
                phone_val = self.page.locator(".listing-person__phone-button, .listing-agent__phone, .button--expand").first.inner_text().strip()
                # Clean up if it still says "Näytä numero"
                if "Näytä numero" in phone_val:
                    # Try getting from any text that looks like a phone number
                    phone_val = self.page.evaluate("""() => {
                        const text = document.body.innerText;
                        const match = text.match(/(\\+358|0)\\d{1,3}[\\s-]?\\d{3,4}[\\s-]?\\d{3,4}/);
                        return match ? match[0] : "N/A";
                    }""")
                details["contact_phone"] = phone_val
            else:
                details["contact_phone"] = "N/A"
        except Exception as e:
            print(f"Error extracting contact info: {e}")
            details["contact_name"] = details.get("contact_name", "Error")

        # Images and Categorization using __INITIAL_STATE__
        image_data = [] # List of dicts: {"src": url, "isFloorPlan": bool}
        try:
            # Extract high-res images from the preloaded state which is very reliable
            state_data = self.page.evaluate("""() => {
                return window.__INITIAL_STATE__ ? window.__INITIAL_STATE__.listing : null;
            }""")
            
            if state_data and "images" in state_data:
                for img in state_data["images"]:
                    src = img.get("url")
                    if src:
                        # Oikotie explicitly types images
                        is_fp = img.get("type") == "FLOORPLAN" or "pohja" in (img.get("caption") or "").toLowerCase()
                        image_data.append({"src": src, "isFloorPlan": is_fp})
            
            # Fallback to DOM if state fails or is empty
            if not image_data:
                imgs = self.page.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.src;
                        if (src && src.includes('ot-real-estate-mediabank-prod')) {
                            const alt = (img.alt || "").toLowerCase();
                            const isFloorPlan = alt.includes('pohja');
                            results.push({ src, isFloorPlan });
                        }
                    });
                    return results;
                }""")
                seen = set()
                for item in imgs:
                    if item["src"] not in seen:
                        image_data.append(item)
                        seen.add(item["src"])
                    
            print(f"Found {len(image_data)} images.")
            
        except Exception as e:
            print(f"Error extracting images: {e}")
            
        details["image_data"] = image_data
        details["image_urls"] = [item["src"] for item in image_data]
        return details

    def is_image_grayscale(self, filepath, threshold=10):
        """
        Detects if an image is grayscale (likely a floor plan) or colorful.
        Uses a threshold for the saturation/color difference.
        """
        try:
            from PIL import Image, ImageStat
            with Image.open(filepath) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Sample a few pixels or use statistics
                stat = ImageStat.Stat(img)
                # stat.diff is the average absolute difference between bands (R, G, B)
                # If R, G, and B are very similar, it's grayscale.
                # In PIL ImageStat, 'mean' is [meanR, meanG, meanB]
                means = stat.mean
                if len(means) < 3: return True
                
                diff = abs(means[0] - means[1]) + abs(means[1] - means[2]) + abs(means[0] - means[2])
                return diff < threshold # Very low difference means grayscale
        except Exception as e:
            print(f"Color analysis failed for {filepath}: {e}")
            return False

    def download_images(self, image_data, base_folder):
        """
        image_data: list of dicts {"src": url, "isFloorPlan": bool}
        base_folder: destination folder for this property
        """
        normal_folder = os.path.join(base_folder, "normal_images")
        floor_plan_folder = os.path.join(base_folder, "floor_plans")
        
        for folder in [normal_folder, floor_plan_folder]:
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            
        count = 0
        for i, item in enumerate(image_data):
            url = item["src"]
            initial_fp = item["isFloorPlan"]
            
            try:
                response = requests.get(url, stream=True, timeout=20)
                if response.status_code == 200:
                    ext = "jpg"
                    if "." in url.split('?')[0]:
                        potential_ext = url.split('?')[0].split('.')[-1]
                        if len(potential_ext) <= 4: ext = potential_ext
                    
                    filename = f"image_{i+1}.{ext}"
                    # Temporary save to check color
                    temp_path = os.path.join(base_folder, filename)
                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(4096):
                            f.write(chunk)
                    
                    # Refine classification based on color (Black & White detection)
                    is_bw = self.is_image_grayscale(temp_path)
                    
                    # If it's B&W OR already marked as floor plan, put it in floor_plans
                    final_folder = floor_plan_folder if (is_bw or initial_fp) else normal_folder
                    final_path = os.path.join(final_folder, filename)
                    
                    # Move to final destination
                    if os.path.exists(final_path): os.remove(final_path)
                    os.rename(temp_path, final_path)
                    
                    count += 1
            except Exception as e:
                print(f"Failed to download {url}: {e}")
        return count
