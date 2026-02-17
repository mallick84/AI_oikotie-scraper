import streamlit as st
import pandas as pd
import os
from scraper import OikotieScraper

st.set_page_config(page_title="Oikotie Scraper POC", page_icon="🏠")

# --- Browser Setup for Cloud Deployment ---
import subprocess
import shutil

# Custom Layout: Main Panel Only
st.title("🏠 Oikotie Property Scraper")
st.markdown("Download property images and details from Oikotie.")

# --- Session State for Metrics ---
if "processed_ids" not in st.session_state:
    st.session_state.processed_ids = set()
if "skipped_count" not in st.session_state:
    st.session_state.skipped_count = 0
if "floor_plan_count" not in st.session_state:
    st.session_state.floor_plan_count = 0
if "downloaded_count" not in st.session_state:
    st.session_state.downloaded_count = 0
if "total_images_count" not in st.session_state:
    st.session_state.total_images_count = 0
if "storage_usage" not in st.session_state:
    st.session_state.storage_usage = 0.0

@st.cache_resource
def install_playwright_browsers():
    # check if chromium is installed
    try:
        # Just run the install command, it's fast if already installed
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Failed to install browser drivers: {e}")

install_playwright_browsers()
# ------------------------------------------

# --- Utility for ZIP & Excel ---
import zipfile
import io

def get_dir_size(path):
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_dir_size(entry.path)
    except Exception:
        pass
    return total / (1024 * 1024) # MB

def create_zip(directory_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, directory_path)
                z.write(filepath, arcname)
    return buf.getvalue()

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Properties')
    processed_data = output.getvalue()
    return processed_data

# Inputs
with st.sidebar:
    st.header("Settings")
    num_properties = st.number_input(
        "Number of properties", 
        min_value=1, 
        max_value=50, 
        value=2,
        help="Try to give minimum number of properties since it will be first download at cloud then you can download the zip."
    )
    st.warning("⚠️ **Note**: Since it will be first download at cloud then you can download the zip, so try by giving minimum number of properties.")
    
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
            # If it's an absolute path from a different OS (like /Users on Linux)
            # just silently use a safe relative folder to avoid the Errno 13 error.
            destination_folder = "scraped_data"
            is_cloud = True
    
    # Detection: try accessing st.query_params safely
    is_streamlit_cloud = False
    try:
        # Modern way to check for cloud/query params
        if "share.streamlit.io" in str(st.query_params):
            is_streamlit_cloud = True
    except:
        pass

    if is_streamlit_cloud or is_cloud:
        st.info("☁️ **Running on Cloud**: You won't find files on your local Mac yet. After scraping, click the **ZIP Download** button at the bottom.")

    st.divider()
    st.markdown("### Search & Filter")
    search_query = st.text_input("Search in results", "")

import tempfile

# --- Live Status Table (Main Panel) ---
st.markdown("### 📊 Live Scraper Status")
status_table_placeholder = st.empty()

# Initialize/Show Table
def get_status_df():
    return pd.DataFrame([{
        "Status": "Ready",
        "Floor Plans": st.session_state.floor_plan_count,
        "Images": f"{st.session_state.downloaded_count}",
        "Storage (MB)": f"{st.session_state.storage_usage:.2f}",
        "Duplicates Skipped": st.session_state.skipped_count
    }])

status_table_placeholder.dataframe(get_status_df(), hide_index=True, use_container_width=True)


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
                # Create a timestamped subfolder for this run to isolate data
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                working_dest = os.path.join(destination_folder, f"run_{timestamp}")
                os.makedirs(working_dest, exist_ok=True)

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
                    # Basic ID from URL
                    prop_id = link.split('/')[-1]

                    # Duplicate Check
                    if prop_id in st.session_state.processed_ids:
                        st.session_state.skipped_count += 1
                        
                        # Update Table
                        live_df = pd.DataFrame([{
                            "Status": f"Skipped Duplicate: {prop_id}",
                            "Floor Plans": st.session_state.floor_plan_count,
                            "Images": f"{st.session_state.downloaded_count}/{st.session_state.total_images_count}",
                            "Storage (MB)": f"{st.session_state.storage_usage:.2f}",
                            "Duplicates Skipped": st.session_state.skipped_count
                        }])
                        status_table_placeholder.dataframe(live_df, hide_index=True, use_container_width=True)
                        
                        status_text.text(f"Skipping duplicate {i+1}/{len(links)}: {prop_id}")
                        continue
                    
                    status_text.text(f"Processing property {i+1}/{len(links)}: {link}")
                    
                    # Scrape details
                    try:
                        details = scraper.extract_property_details(link)
                        
                        # Use the working destination (could be temp or local)
                        prop_folder = os.path.join(working_dest, prop_id)
                        
                        # Define status update callback
                        def update_status(data):
                            current_status_msg = "Running..."
                            
                            if data["type"] == "progress":
                                st.session_state.downloaded_count = data['current']
                                st.session_state.total_images_count = data['total']
                                current_status_msg = f"Downloading Image {data['current']}/{data['total']}"
                                
                                # Update memory usage periodically
                                try:
                                    if data['current'] % 2 == 0 or data['current'] == data['total']:
                                        usage = get_dir_size(working_dest)
                                        st.session_state.storage_usage = usage
                                except:
                                    pass
                                    
                            elif data["type"] == "filter":
                                step = data.get("step")
                                msg = data.get("msg")
                                current_status_msg = f"Filter: {msg}"
                                
                                if step == 3:
                                    st.session_state.floor_plan_count += 1
                                    current_status_msg = "✅ Match Found!"

                            # Update Table
                            live_df = pd.DataFrame([{
                                "Status": current_status_msg,
                                "Floor Plans": st.session_state.floor_plan_count,
                                "Images": f"{st.session_state.downloaded_count}/{st.session_state.total_images_count}",
                                "Storage (MB)": f"{st.session_state.storage_usage:.2f}",
                                "Duplicates Skipped": st.session_state.skipped_count
                            }])
                            status_table_placeholder.dataframe(live_df, hide_index=True, use_container_width=True)

                        # Download images (Categorized) with callback
                        status_text.text(f"Downloading images for {prop_id}...")
                        img_count = scraper.download_images(details.get("image_data", []), prop_folder, status_callback=update_status)
                        details["images_downloaded"] = img_count
                        details["local_folder"] = prop_folder
                        
                        # Clean up complex data for CSV/Table
                        row_data = details.copy()
                        if "image_data" in row_data: del row_data["image_data"]
                        if "image_urls" in row_data: del row_data["image_urls"]
                        results.append(row_data)

                        # Mark as processed
                        st.session_state.processed_ids.add(prop_id)
                        
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
                    
                    # Save Excel to the working folder so it gets zipped
                    excel_path = os.path.join(working_dest, "oikotie_properties.xlsx")
                    final_df.to_excel(excel_path, index=False)
                    
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
