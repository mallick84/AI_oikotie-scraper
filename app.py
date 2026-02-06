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

# --- Utility for ZIP ---
import zipfile

def create_zip(directory_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, directory_path)
                z.write(filepath, arcname)
    return buf.getvalue()

# --- Utility for Excel ---
import io

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Properties')
    processed_data = output.getvalue()
    return processed_data

# Inputs
with st.sidebar:
    st.header("Settings")
    num_properties = st.number_input("Number of properties", min_value=1, max_value=50, value=5)
    
    # Cross-platform default Downloads folder
    from pathlib import Path
    try:
        # Try system Downloads folder
        suggested_default = str(Path.home() / "Downloads" / "oikotie_scraped_data")
        # If on Streamlit Cloud, this might be restricted. Check if writable.
        test_path = Path.home() / "Downloads"
        if not os.access(str(test_path), os.W_OK):
            suggested_default = "scraped_data"
    except Exception:
        suggested_default = "scraped_data"

    destination_folder = st.text_input("Destination Folder", value=suggested_default)
    
    # Sanitize: if the path is absolute but doesn't exist on this server environment
    if os.path.isabs(destination_folder):
        parent = os.path.dirname(destination_folder)
        if not os.path.exists(parent):
            st.warning(f"Defaulting to relative path because '{parent}' is not accessible on this server.")
            destination_folder = "scraped_data"

    st.divider()
    st.markdown("### Search & Filter")
    search_query = st.text_input("Search in results", "")

if st.button("🚀 Start Scraping"):
    st.info("Starting scraper... This might take a moment to initialize the browser.")
    
    # Ensure the destination folder exists relative to the current working directory
    if not os.path.exists(destination_folder):
        try:
            os.makedirs(destination_folder, exist_ok=True)
        except Exception as e:
            st.error(f"Could not create destination folder: {e}. Defaulting to 'data'.")
            destination_folder = "data"
            os.makedirs(destination_folder, exist_ok=True)

    # Progress containers
    progress_bar = st.progress(0)
    status_text = st.empty()
    data_container = st.empty()
    
    scraper = OikotieScraper()
    results = []
    
    try:
        with st.spinner("Initializing browser..."):
            scraper.start_browser(headless=True)
            
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
                # Ensure path is relative and safe
                prop_folder = os.path.join(destination_folder, prop_id)
                
                # Download images (Categorized)
                status_text.text(f"Downloading images for {prop_id} (Sorting normal vs floor plans)...")
                img_count = scraper.download_images(details.get("image_data", []), prop_folder)
                details["images_downloaded"] = img_count
                details["local_folder"] = prop_folder
                
                # Clean up complex data for CSV/Table
                row_data = details.copy()
                if "image_data" in row_data: del row_data["image_data"]
                if "image_urls" in row_data: del row_data["image_urls"]
                results.append(row_data)
                
            except Exception as e:
                st.error(f"Error processing {link}: {e}")
            
            # Update progress
            progress = (i + 1) / len(links)
            progress_bar.progress(progress)
            
            # Update dashboard table
            if results:
                df = pd.DataFrame(results)
                # Filter if search query exists
                if search_query:
                    df = df[df.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)]
                # Removing use_container_width=True or specifically handling it to force scroll
                data_container.dataframe(df)

        # Final Dashboard & Export
        if results:
            st.divider()
            st.header("📊 Results Dashboard")
            
            final_df = pd.DataFrame(results)
            
            # Search filter again for final display
            display_df = final_df.copy()
            if search_query:
                display_df = display_df[display_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)]
            
            # Displaying both tables with explicit configuration for scrolling
            st.dataframe(display_df)
            
            col_export_1, col_export_2, col_export_3 = st.columns(3)
            with col_export_1:
                excel_data = to_excel(final_df)
                st.download_button(
                    label="📥 Download Excel",
                    data=excel_data,
                    file_name="oikotie_properties.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_export_2:
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📄 Download CSV",
                    data=csv,
                    file_name="oikotie_properties.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            with col_export_3:
                zip_data = create_zip(destination_folder)
                st.download_button(
                    label="📦 Download All (ZIP)",
                    data=zip_data,
                    file_name="scraped_oikotie_data.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            st.divider()
            st.balloons()
            st.success("🎉 SCRAPING COMPLETE! All data and images have been processed.")
            st.write(f"📁 Files saved in the relative folder: `{destination_folder}`")
            
    except Exception as e:
        st.error(f"An error occurred: {e}")
    finally:
        status_text.text("Closing browser...")
        scraper.close_browser()
