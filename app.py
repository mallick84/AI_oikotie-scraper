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

    # Path Hints Section
    with st.expander("ℹ️ How to provide a path?"):
        st.markdown("""
        **Local Mac/Linux**: 
        `/Users/username/Downloads/oikotie`
        
        **Local Windows**: 
        `C:\\Users\\username\\Downloads\\oikotie`
        
        **Streamlit Cloud**: 
        Leave as `scraped_data`. (Note: Cloud servers cannot access your local computer's folders).
        """)

    destination_folder = st.text_input(
        "Destination Folder", 
        value=suggested_default,
        help="Where images will be saved on the server. Local users can provide an absolute path."
    )
    
    # Sanitize and warn
    is_cloud = False
    if os.path.isabs(destination_folder):
        parent = os.path.dirname(destination_folder)
        if not os.path.exists(parent):
            st.warning("⚠️ Absolute path not found. If you are on Streamlit Cloud, please use a simple folder name like 'scraped_data'.")
            is_cloud = True
    
    if is_cloud or "share.streamlit.io" in st.experimental_get_query_params().keys(): # Basic cloud detection
        st.info("☁️ **Running on Cloud**: You won't find files on your local Mac yet. After scraping, click the **ZIP Download** button at the bottom.")

    st.divider()
    st.markdown("### Search & Filter")
    search_query = st.text_input("Search in results", "")

import tempfile

if st.button("🚀 Start Scraping"):
    # Determine safe storage
    # If it's an absolute path provided by user, try to use it (local mode)
    # If it's relative or fails, or we are on cloud, use temp storage
    storage_is_temporary = False
    final_dest = destination_folder
    
    if os.path.isabs(destination_folder) and os.path.exists(os.path.dirname(destination_folder)):
        # Local mode with valid path
        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder, exist_ok=True)
    else:
        # Fallback to temporary storage for safety and cloud hygiene
        storage_is_temporary = True

    st.info(f"Starting scraper... {'(Using Temporary Cloud Storage)' if storage_is_temporary else f'Saving to: `{destination_folder}`'}")

    try:
        # We use a context manager for temp dir so it cleans up automatically
        with tempfile.TemporaryDirectory() if storage_is_temporary else open(__file__) as temp_dir:
            # If open(__file__) was used, temp_dir is just a file object, we ignore it
            if storage_is_temporary:
                working_dest = temp_dir
            else:
                working_dest = destination_folder

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
                        # Use the working destination (could be temp or local)
                        prop_folder = os.path.join(working_dest, prop_id)
                        
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
                        # Create ZIP from the working destination
                        zip_data = create_zip(working_dest)
                        st.download_button(
                            label="📦 Download All (ZIP)",
                            data=zip_data,
                            file_name="scraped_oikotie_data.zip",
                            mime="application/zip",
                            use_container_width=True
                        )

                    st.divider()
                    st.balloons()
                    st.success("🎉 SCRAPING COMPLETE!")
                    if storage_is_temporary:
                        st.warning("⚠️ **Cloud Storage Notice**: These files are in temporary storage and will be DELETED when you refresh or close this page. Please download the ZIP now!")
                    else:
                        st.write(f"📁 Files saved in: `{working_dest}`")
                
            except Exception as e:
                st.error(f"An error occurred during extraction: {e}")
            
    except Exception as e:
        st.error(f"An error occurred: {e}")
    finally:
        status_text.text("Closing browser...")
        scraper.close_browser()
