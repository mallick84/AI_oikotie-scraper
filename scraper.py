import os
import time
import requests
import logging
import json
import re
from playwright.sync_api import sync_playwright

# Configure logging to file
logging.basicConfig(
    filename='scraper_debug.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)

class OikotieScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start_browser(self, headless=True):
        # Set TESSDATA_PREFIX if local folder exists (Fix for missing system lang data)
        local_tessdata = os.path.join(os.getcwd(), 'tessdata')
        if os.path.exists(local_tessdata):
            os.environ['TESSDATA_PREFIX'] = local_tessdata

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
        """
        Robust cookie acceptance logic handling both iframes and main page buttons.
        """
        try:
            # Short wait for any overlay
            time.sleep(2)
            
            # Strategy 1: Main Page Button (Common in recent updates)
            # Look for "Hyväksy" or "Accept" in buttons
            consent_btn = self.page.locator('button:has-text("Hyväksy"), button:has-text("Accept all"), button:has-text("OK")').first
            if consent_btn.is_visible():
                print("Found cookie button on main page, clicking...")
                consent_btn.click()
                time.sleep(1)
                return

            # Strategy 2: Iframe (CMP)
            # iframe src often contains 'cmpv2', 'privacy', 'consent'
            frames = self.page.frames
            for frame in frames:
                if any(x in frame.url for x in ['cmpv2', 'privacy', 'consent']):
                    try:
                        accept_btn = frame.locator('button:has-text("Hyväksy"), div[role="button"]:has-text("Hyväksy")').first
                        if accept_btn.is_visible():
                            print("Found cookie button in iframe, clicking...")
                            accept_btn.click()
                            time.sleep(1)
                            return
                    except:
                        continue

            # print("No cookie banner found or already accepted.")

        except Exception as e:
            print(f"Warning: Cookie handling encountered an error (ignoring): {e}")


    def get_property_links(self, limit=5):
        url = "https://asunnot.oikotie.fi/myytavat-asunnot?cardType=100"
        try:
            self.page.goto(url, timeout=60000)
        except Exception as e:
            print(f"Navigation timeout/error: {e}")
            return []

        self.accept_cookies()
        
        links = set()
        retries = 0
        
        while len(links) < limit and retries < 5:
            # Extract links
            cards = self.page.query_selector_all("a.ot-card-v3")
            for card in cards:
                href = card.get_attribute("href")
                if href:
                    links.add(href)
                if len(links) >= limit:
                    break
            
            print(f"Found {len(links)} links so far...")
            
            if len(links) < limit:
                # Scroll to load more
                self.page.mouse.wheel(0, 1000)
                time.sleep(2)
                retries += 1
            else:
                break
            
        return list(links)[:limit]

    def extract_property_details(self, url):
        print(f"Navigating to {url}...")
        self.page.goto(url, timeout=60000)
        time.sleep(2) 
        self.accept_cookies()
        
        details = {"url": url}
        
        # --- Metadata Extraction (Basic Info) ---
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
            "Putkiremontti": "plumbing_renovation", # Often requested
            "Rakennusmateriaali": "building_material",
            "Kattomateriaali": "roof_material",
            "Kattotyyppi": "roof_type",
            "Energiatodistus": "energy_certificate",
            "Energialuokka": "energy_class",
            "Lämmitys": "heating"
        }

        # 1. Extract text fields from DL/DT/DD lists
        for label, key in text_fields.items():
            try:
                # Find dt containing the label accurately
                # Use a reliable XPath to find the label and get the immediate next value
                xpath = f"//dt[contains(., '{label}')]/following-sibling::dd[1]"
                element = self.page.query_selector(xpath)
                if element:
                    details[key] = element.inner_text().strip()
                else:
                    details[key] = "N/A"
            except Exception:
                details[key] = "Error"
        
        # 2. Extract Contact Info
        self._extract_contact_info(details)

        # 3. Extract Images (Priority: JSON, Fallback: UI)
        image_data = self._extract_images()
        details["image_data"] = image_data
        details["image_urls"] = [item["src"] for item in image_data]
        
        return details

    def _extract_contact_info(self, details):
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
            
            # Phone (try to reveal)
            try:
                phone_btn = self.page.get_by_text("Näytä numero", exact=False).first
                if phone_btn.count() > 0 and phone_btn.is_visible():
                    phone_btn.click()
                    time.sleep(1.0)
                
                # Grab whatever is in the phone field now
                phone_el = self.page.locator(".listing-person__phone-button, .listing-agent__phone").first
                if phone_el.count() > 0:
                     details["contact_phone"] = phone_el.inner_text().strip()
                else:
                     details["contact_phone"] = "N/A"
            except:
                details["contact_phone"] = "N/A"
                
        except Exception as e:
            print(f"Error extracting contact info: {e}")

    def _extract_images(self):
        """
        Prioritize extraction from __NEXT_DATA__ JSON.
        Fallback to UI gallery interaction if JSON is missing or empty.
        """
        image_data = []
        seen_urls = set()
        
        print("--- IMAGE EXTRACTION START ---")

        # --- Method A: JSON Extraction (Reliable, high-res) ---
        try:
            print("Attempting JSON extraction from __NEXT_DATA__...")
            json_images = self.page.evaluate("""() => {
                const nextData = document.getElementById('__NEXT_DATA__');
                if (!nextData) return null;
                try {
                    const data = JSON.parse(nextData.textContent);
                    // Standard Oikotie path (may vary slightly, so we check a few spots)
                    // Usually: props.pageProps.card.images OR props.pageProps.listing.images
                    const props = data.props?.pageProps || {};
                    const listing = props.card || props.listing || {};
                    return listing.images || [];
                } catch(e) { return null; }
            }""")

            if json_images and len(json_images) > 0:
                print(f"Found {len(json_images)} images in JSON data.")
                for img in json_images:
                    # JSON structure usually has 'url', 'largeUrl', or 'formats'
                    # Prefer the largest format
                    src = None
                    if isinstance(img, str):
                        src = img
                    elif isinstance(img, dict):
                        # Try standard keys
                        src = img.get('largeUrl') or img.get('url') or img.get('contentUrl')
                        # If formats exist, get the largest
                        if not src and 'formats' in img:
                            formats = img['formats']
                            # simplistic: pick the last one (usually largest) or specific key
                            if formats:
                                src = list(formats.values())[-1]
                    
                    if src:
                        self._add_image(src, image_data, seen_urls, source="JSON")
                
                if len(image_data) > 0:
                     print("JSON extraction successful.")
                     return image_data

        except Exception as e:
            print(f"JSON extraction error: {e}")


        # --- Method B: Static HTML Gallery (Angular/Server-Side) ---
        if not image_data:
            try:
                print("JSON extraction failed. Attempting static HTML gallery extraction...")
                html_images = self._extract_from_galleria_html()
                if html_images:
                    print(f"Found {len(html_images)} images in static HTML.")
                    for src in html_images:
                         self._add_image(src, image_data, seen_urls, source="StaticHTML")
                    
                    if len(image_data) > 0:
                        print("Static HTML extraction successful.")
                        return image_data
            except Exception as e:
                print(f"Static HTML extraction error: {e}")

        # --- Method C: UI Gallery Interaction (Fallback) ---
        if not image_data:
            print("Static HTML extraction yielded no results. Falling back to UI interaction.")
            try:
                # 1. Open Gallery
                # Newer Oikotie uses specific button classes
                gallery_btn = self.page.locator('button.open-galleria, button:has-text("Katso kaikki kuvat"), .listing-hero__all-images').first
                
                if gallery_btn.is_visible():
                    print("Found gallery button, clicking...")
                    gallery_btn.click()
                    time.sleep(2) # Wait for lightbox
                    
                    # 2. Iterate through gallery
                    # We need to click "Next" to trigger lazy loading of high-res images
                    # Limit safety to 50 images to prevent infinite loops
                    
                    for _ in range(50):
                        # Scrape current visible image
                        # Selector for lightbox image
                        curr_img = self.page.locator('.galleria-image img, .lightbox img').first
                        if curr_img.is_visible():
                             src = curr_img.get_attribute("src")
                             self._add_image(src, image_data, seen_urls, source="GalleryUI")
                        
                        # Click Next
                        next_btn = self.page.locator('.galleria-image-nav-right, [class*="next"], button[aria-label="Next"]').first
                        if next_btn.is_visible():
                            next_btn.click()
                            time.sleep(0.4) # Small delay for transition
                        else:
                            print("No next button found, end of gallery.")
                            break

                        # If we cycled back to the first image, stop (check simplistic logic or rely on set)
                        # For now relies on seen_urls to just not add duplicates
                else:
                    print("Gallery button not found. Using fallback DOM scrape.")
                    # 3. Last Resort: Scrape whatever is in the DOM (Hero + thumbnails)
                    imgs = self.page.query_selector_all("img")
                    for img in imgs:
                        src = img.get_attribute("src")
                        if src:
                            self._add_image(src, image_data, seen_urls, source="DOM_Fallback")

            except Exception as e:
                 print(f"UI extraction error: {e}")

        print(f"Total unique images collected: {len(image_data)}")
        return image_data

    def _extract_from_galleria_html(self):
        """
        Extracts images from the static structure of the /kuvat subpage.
        This is used for Angular-based listings where the main page lazy-loads images.
        """
        urls = []
        try:
            # Construct the /kuvat URL
            # It's usually base_url/kuvat
            current_url = self.page.url
            if not current_url.endswith('/kuvat'):
                kuvat_url = f"{current_url.rstrip('/')}/kuvat"
                print(f"Navigating to gallery subpage: {kuvat_url}")
                
                # Navigate to the subpage
                try:
                    self.page.goto(kuvat_url, timeout=30000)
                    self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception as e:
                    print(f"Failed to navigate to {kuvat_url}: {e}")
                    return []

            # Extract anchors from the /kuvat page
            # The structure is usually a grid of <a> tags pointing to the big images
            urls = self.page.evaluate("""() => {
                const results = [];
                // Find all anchors with 'mediabank' in href or data-big
                const anchors = document.querySelectorAll('a');
                
                anchors.forEach(a => {
                    let src = null;
                    if (a.href && a.href.includes('mediabank')) {
                        src = a.href;
                    } else {
                        const img = a.querySelector('img');
                        if (img) {
                            src = img.getAttribute('data-big') || (img.src && img.src.includes('mediabank') ? img.src : null);
                        }
                    }
                    
                    if (src) results.push(src);
                });
                
                return results;
            }""")
            
            # Navigate back to main page to restore state for any further processing?
            # Actually, we don't need to go back since we've already extracted metadata.
            # But good practice if this method was called in middle of things.
            # self.page.go_back() 
            
        except Exception as e:
            print(f"Error in _extract_from_galleria_html: {e}")
        
        return urls

    def _add_image(self, url, image_data, seen_urls, source="Unknown"):
        if not url or not url.startswith('http'):
            return

        # --- FILTER: Exclude Icons/Logos/Placeholders ---
        # Keywords to SKIP
        skip_keywords = [
            'logo', 'icon', 'avatar', 'placeholder', 'blank', 
            'danske', 'vend', 'valokuitunen', 'schibsted', 
            'twitter', 'facebook', 'linkedin', 'instagram', 
            'marker', 'leaflet', 'double-arrow'
        ]
        
        # Specific check for Oikotie hosted images
        # Real images usually contain 'ot-real-estate-mediabank-prod' or similar hashes
        # If it's a generic CDN asset, it might be an icon.
        
        url_lower = url.lower()
        if any(k in url_lower for k in skip_keywords):
            # print(f"Skipping icon/irrelevant image ({source}): {url}")
            return
            
        # Optional: Skip small SVGs if detected by extension
        if url_lower.endswith('.svg'):
            return

        # Deduplication based on base URL (ignoring some query params if needed)
        # Using full URL for now
        if url not in seen_urls:
            seen_urls.add(url)
            
            # Check for Floor Plan keywords in the URL itself
            is_fp = any(k in url_lower for k in ['pohja', 'floor', 'plan'])
            
            image_data.append({"src": url, "isFloorPlan": is_fp, "source": source})
            
    def is_image_grayscale(self, filepath, threshold=10):
        """
        Detects if an image is grayscale (likely a floor plan).
        """
        try:
            from PIL import Image, ImageStat
            with Image.open(filepath) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                stat = ImageStat.Stat(img)
                means = stat.mean
                if len(means) < 3: return True
                
                diff = abs(means[0] - means[1]) + abs(means[1] - means[2]) + abs(means[0] - means[2])
                return diff < threshold
        except Exception as e:
            # print(f"Color analysis failed: {e}")
            return False

    def download_images(self, image_data, base_folder, status_callback=None):
        normal_folder = os.path.join(base_folder, "normal_images")
        floor_plan_folder = os.path.join(base_folder, "floor_plans")
        
        for folder in [normal_folder, floor_plan_folder]:
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            
        count = 0
        total_images = len(image_data)
        
        for i, item in enumerate(image_data):
            url = item["src"]
            
            if status_callback:
                status_callback({
                    "type": "progress", "current": i + 1, "total": total_images
                })
            
            try:
                response = requests.get(url, stream=True, timeout=20)
                if response.status_code == 200:
                    # File Extension Logic
                    ext = "jpg"
                    if "." in url.split('?')[0]:
                        potential_ext = url.split('?')[0].split('.')[-1]
                        if len(potential_ext) <= 4: ext = potential_ext
                    
                    filename = f"image_{i+1}.{ext}"
                    temp_path = os.path.join(normal_folder, filename)
                    
                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(4096):
                            f.write(chunk)
                            
                    # --- SIZE FILTER ---
                    # Ignore tiny files (< 10KB) that might be missed icons
                    file_size = os.path.getsize(temp_path)
                    if file_size < 10 * 1024:
                        # print(f"Removing tiny file ({file_size} bytes): {filename}")
                        os.remove(temp_path)
                        continue

                    # --- Classification Logic (B&W Only) ---
                    is_floor_plan = False
                    reason = "Color"
                    
                    if ext.lower() != "svg":
                        if self.is_image_grayscale(temp_path, threshold=5):
                            is_floor_plan = True
                            reason = "Grayscale"
                    
                    if is_floor_plan:
                        final_path = os.path.join(floor_plan_folder, filename)
                        os.rename(temp_path, final_path)
                        
                    # UI Status Update
                    if status_callback:
                        status_callback({
                            "type": "filter",
                            "step": 3 if is_floor_plan else 2,
                            "msg": f"Img {i+1}: {'✅ Floor Plan' if is_floor_plan else '📷 Normal Image'}"
                        })
                    
                    count += 1
            except Exception as e:
                print(f"Failed to download {url}: {e}")
                
        return count
