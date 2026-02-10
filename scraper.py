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
        # Set TESSDATA_PREFIX if local folder exists (Fix for missing system lang data)
        local_tessdata = os.path.join(os.getcwd(), 'tessdata')
        if os.path.exists(local_tessdata):
            os.environ['TESSDATA_PREFIX'] = local_tessdata
            # print(f"Using local Tesseract data: {local_tessdata}")

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

    def analyze_floor_plan_content(self, filepath):
        """
        Analyzes image content using OCR and applies specific rules for Finnish floor plans.
        Returns: (is_floor_plan: bool, reason: str)
        """
        try:
            import pytesseract
            from PIL import Image, ImageEnhance
            import re
            
            img = Image.open(filepath)
            
            # Preprocessing: Upscale if small (helps with small text)
            if img.width < 1500:
                scale = 1500 / img.width
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                
            # Convert to greyscale for better OCR
            img = img.convert('L')
            
            # Multi-pass OCR Strategy
            # Pass 1: Finnish, Sparse Text (PSM 11) - Good for labels scattered around
            # Pass 2: Finnish, Block Text (PSM 6) - Good if labels are blocks
            # Pass 3: English (fallback)
            
            # Try to use finnish if available, else English
            langs = ["fin", "eng"]
            configs = [
                r'--psm 11', # Sparse text
                r'--psm 6'   # Block text
            ]
            
            full_text = ""
            
            for lang in langs:
                for config in configs:
                    try:
                        text_chunk = pytesseract.image_to_string(img, lang=lang, config=config)
                        full_text += "\n" + text_chunk
                    except:
                        # Fallback if language not found
                        continue
            
            # If nothing worked (e.g. lang error), try default
            if not full_text.strip():
                full_text = pytesseract.image_to_string(img, config='--psm 11')
                
            text = full_text.upper()
            
            # Rule 1: Room Labels (Need 2+)
            # Patterns allowing for optional punctuation/spaces
            room_labels = [
                r'\bOH\b', r'\bOLOHUONE\b', 
                r'\bMH\b', r'\bMAKUUHUONE\b',
                r'\bH\b', r'\bHUONE\b', 
                r'\bK\b', r'\bKEITTI[ÖO]\b', r'\bKT\b', r'\bKEITTOTILA\b', 
                r'\bKK\b', r'\bKEITTOKOMERO\b', # Added KK
                r'\bKPH\b', r'\bKH\b', r'\bKYLPYHUONE\b',
                r'\bWC\b',
                r'\bET\b', r'\bETEINEN\b',
                r'\bS\b', r'\bSAUNA\b',
                r'\bVH\b', r'\bVAATEHUONE\b',
                r'\bKHH\b', r'\bKODINHOITOHUONE\b',
                r'\bTK\b', r'\bTEKNINEN\b', r'\bTUULIKAAPPI\b', # Added TK/Tuulikaappi
                r'\bVAR\b', r'\bVARASTO\b',
                r'\bP\b', r'\bPARVEKE\b', r'\bLASITETTU\b', r'\bTERASSI\b', r'\bPARVI\b',
                r'\bRT\b', r'\bRUOKAILUTILA\b', # Added RT
                r'\bAULA\b', # Added AULA
                r'\bALK\b', r'\bALKOVI\b', # Added ALK
                r'\bSK\b', r'\bSIIVOUSKOMERO\b' # Added SK
            ]
            
            label_matches = 0
            found_labels = []
            for pattern in room_labels:
                if re.search(pattern, text):
                    label_matches += 1
                    found_labels.append(pattern.replace(r'\b', '').replace(r'\b', ''))
            
            # Rule 2: Dimensions (X.xx m x Y.yy m)
            # Regex for "number[.,]number m x number[.,]number m"
            # Allowing some flexibility for OCR errors (e.g. 'm' might be missing slightly)
            dim_pattern = r'\d+[.,]\d+\s*m?\s*[xX]\s*\d+[.,]\d+\s*m?'
            has_dimensions = bool(re.search(dim_pattern, text))
            
            # Rule 3: Area Patterns (43,0 m2)
            area_pattern = r'\d+[.,]?\d*\s*(m²|m2|M2|M²)'
            has_area = bool(re.search(area_pattern, text))
            
            # Rule 4: Floor/Location Keywords
            keywords = [
                r'\d+\.?\s*KERROS', r'SIJAINTIKAAVIO', r'POHJAKUVA', r'HUONEISTO',
                r'ASUNTO', r'TALO', r'PINTA-ALA', r'ASEMAPIIRROS', r'PIIRUSTUS', 
                r'SUUNTAA\s*ANTAVA'
            ]
            has_keyword = any(re.search(k, text) for k in keywords)
            
            # Rule 5: Apartment ID (AS + number)
            has_apt_id = bool(re.search(r'\bAS\d+\b', text))
            
            # Rule 6: Layout Codes (2H+KT)
            # Structure: Number + H + ...
            layout_pattern = r'\d+H\s*\+'
            has_layout_code = bool(re.search(layout_pattern, text))
            
            # Decision Logic
            # Condition A: 2+ Room Labels (Medium Confidence Baseline)
            cond_a_medium = label_matches >= 2
            
            # Condition B: Dimensions OR Information Bucket
            cond_b = has_dimensions or has_area or has_keyword or has_apt_id or has_layout_code
            
            # Condition C: High Confidence Labels (3+) - Ignore Condition B
            cond_a_high = label_matches >= 3
            
            details = []
            if has_dimensions: details.append("Dimensions")
            if has_area: details.append("Area")
            if has_keyword: details.append("Keywords")
            if has_apt_id: details.append("AptID")
            if has_layout_code: details.append("LayoutCode")
            
            # Logic 1: High Label Count -> Auto Pass
            if cond_a_high:
                 return True, f"Matched (High Confidence): {label_matches} labels found ({', '.join(found_labels[:3])}...)"
            
            # Logic 2: Medium Label Count + Context -> Pass
            if cond_a_medium and cond_b:
                return True, f"Matched (Medium Confidence): {label_matches} labels + ({', '.join(details)})"
            
            # Logic 3: Strong Context -> Pass (Layout Code + Metrics)
            if has_layout_code and (has_area or has_dimensions):
                 return True, "Matched (Context): Layout Code + Dimensions/Area"

            return False, f"Labels: {label_matches}, Dim: {has_dimensions}, Info: {cond_b}"

        except Exception as e:
            msg = f"OCR Error: {str(e)}"
            return False, msg

    def download_images(self, image_data, base_folder, status_callback=None):
        """
        image_data: list of dicts {"src": url, "isFloorPlan": bool}
        base_folder: destination folder for this property
        status_callback: function(msg) to report status to UI
        """
        normal_folder = os.path.join(base_folder, "normal_images")
        floor_plan_folder = os.path.join(base_folder, "floor_plans")
        
        for folder in [normal_folder, floor_plan_folder]:
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            
        count = 0
        total_images = len(image_data)
        
        for i, item in enumerate(image_data):
            url = item["src"]
            initial_fp = item["isFloorPlan"]
            
            if status_callback:
                status_callback({
                    "type": "progress",
                    "current": i + 1,
                    "total": total_images,
                    "msg": f"Downloading {i+1}/{total_images}..."
                })
            
            try:
                response = requests.get(url, stream=True, timeout=20)
                if response.status_code == 200:
                    ext = "jpg"
                    if "." in url.split('?')[0]:
                        potential_ext = url.split('?')[0].split('.')[-1]
                        if len(potential_ext) <= 4: ext = potential_ext
                    
                    filename = f"image_{i+1}.{ext}"
                    # Temporary save to check color/OCR
                    temp_path = os.path.join(base_folder, filename)
                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(4096):
                            f.write(chunk)
                    
                    # Refine classification
                    # 1. Color Check (Filter 1)
                    if status_callback:
                        status_callback({
                            "type": "filter",
                            "step": 1,
                            "msg": f"Img {i+1}: Analyzing color (B&W check)..."
                        })
                    is_bw = self.is_image_grayscale(temp_path)
                    
                    # 2. Advanced Content Analysis (Filter 2)
                    is_advanced_match = False
                    match_reason = ""
                    
                    if status_callback:
                        status_callback({
                            "type": "filter",
                            "step": 2,
                            "msg": f"Img {i+1}: Analyzing content (Advanced Rules)..."
                        })
                    try:
                        is_advanced_match, match_reason = self.analyze_floor_plan_content(temp_path)
                        print(f"Image {i+1} analysis: {match_reason}") # Debug log
                    except Exception as e:
                        print(f"Analysis failed: {e}")

                    # Decision Logic based on double filter + Rules
                    # If it's B&W AND Advanced Match -> Very High confidence Floor Plan
                    # Rule relaxations:
                    # - If matches advanced rules strongly, color matters less (some floor plans have color)
                    # - If strict B&W and has *some* content, we might still count it, but let's trust the advanced rules more.
                    
                    is_floor_plan = False
                    reason_log = ""
                    
                    if initial_fp:
                        is_floor_plan = True
                        reason_log = "Metadata"
                    elif is_advanced_match:
                        # Strong rule match overrides color (some floor plans are colored)
                        is_floor_plan = True
                        reason_log = f"Advanced Rule ({match_reason})"
                    elif is_bw and "Labels" in match_reason: 
                        # If it was B&W but missed some strict rule, but had *some* data? 
                        # Actually analyze_floor_plan_content returns False if rules aren't met.
                        # We can fallback to B&W only if we are desperate, but the user complained about accuracy.
                        # So let's stick to the rules for "Floor Plan" classification to improve precision.
                        # OR: If is_bw is True, we might look for weak signals?
                        # For now, let's respect the "Accuracy" request and reply on the Rule Set + Metadata.
                        # But wait, previous logic was "is_bw AND has_numbers". 
                        # The new rules are much better than "has_numbers".
                        pass
                    
                    # send final decision to UI for debug/info if needed
                    if status_callback and is_floor_plan:
                         status_callback({
                            "type": "filter",
                            "step": 3,
                            "msg": f"Img {i+1}: Classified as Floor Plan! ({reason_log})"
                        })
                    
                    final_folder = floor_plan_folder if is_floor_plan else normal_folder
                    final_path = os.path.join(final_folder, filename)
                    
                    # Move to final destination
                    if os.path.exists(final_path): os.remove(final_path)
                    os.rename(temp_path, final_path)
                    
                    count += 1
            except Exception as e:
                print(f"Failed to download {url}: {e}")
                
        return count
