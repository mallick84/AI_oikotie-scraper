import streamlit as st
import pandas as pd
import os
from scraper import OikotieScraper

st.set_page_config(page_title="Oikotie Scraper POC", page_icon="🏠")

st.title("🏠 Oikotie Property Scraper")
st.markdown("Download property images and details from Oikotie.")

# --- Browser Setup for Cloud Deployment ---
import subprocess
import shutil

@st.cache_resource
def install_playwright_browsers():
    # check if chromium is installed
    try:
        # Just run the install command, it's fast if already installed
        # st.info("Checking/Installing browser drivers...")
        subprocess.run(["playwright", "install", "chromium"], check=True)
        # st.success("Browser drivers ready.")
    except Exception as e:
        st.error(f"Failed to install browser drivers: {e}")

install_playwright_browsers()
# ------------------------------------------

# Inputs
col1, col2 = st.columns(2)
with col1:
    num_properties = st.number_input("Number of properties", min_value=1, max_value=50, value=5)
with col2:
    destination_folder = st.text_input("Destination Folder", value="./scraped_data")

if st.button("Start Scraping"):
    st.info("Starting scraper... This might take a moment to initialize the browser.")
    
    # Progress containers
    progress_bar = st.progress(0)
    status_text = st.empty()
    data_container = st.empty()
    
    scraper = OikotieScraper()
    results = []
    
    try:
        with st.spinner("Initializing browser..."):
            scraper.start_browser(headless=True) # Run headless for speed/background
            
        status_text.text("Fetching property links...")
        links = scraper.get_property_links(limit=num_properties)
        st.write(f"Found {len(links)} properties.")
        
        for i, link in enumerate(links):
            status_text.text(f"Processing property {i+1}/{len(links)}: {link}")
            
            # Scrape details
            try:
                details = scraper.extract_property_details(link)
                
                # Basic ID from URL
                prop_id = link.split('/')[-1]
                prop_folder = os.path.join(destination_folder, prop_id)
                
                # Download images
                status_text.text(f"Downloading images for {prop_id}...")
                img_count = scraper.download_images(details.get("image_urls", []), prop_folder)
                details["images_downloaded"] = img_count
                details["local_folder"] = prop_folder
                
                # Remove raw image urls from CSV data to keep it clean
                csv_details = details.copy()
                del csv_details["image_urls"]
                results.append(csv_details)
                
            except Exception as e:
                st.error(f"Error processing {link}: {e}")
            
            # Update progress
            progress = (i + 1) / len(links)
            progress_bar.progress(progress)
            
            # Update dataframe preview
            if results:
                df = pd.DataFrame(results)
                data_container.dataframe(df)

        # Save Final CSV
        if results:
            df = pd.DataFrame(results)
            csv_path = os.path.join(destination_folder, "properties.csv")
            if not os.path.exists(destination_folder):
                os.makedirs(destination_folder)
            df.to_csv(csv_path, index=False)
            
            st.success("Scraping Completed!")
            st.write(f"Data saved to: `{csv_path}`")
            st.write(f"Images saved to: `{destination_folder}/<property_id>/`")
            
    except Exception as e:
        st.error(f"An error occurred: {e}")
    finally:
        status_text.text("Closing browser...")
        scraper.close_browser()
