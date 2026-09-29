import io
import zipfile
import streamlit as st
import pandas as pd
from PIL import Image

# 1. Page Setup & Configuration
st.set_page_config(
    page_title="Our Shopee Image Assistant",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Styling (Apple Aesthetic: Soft Light, Clean Glassmorphic Cards, Green/Orange Accents)
st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }
    .stApp {
        background-color: #FAFAFA;
    }
    /* Top Banner Card */
    .header-card {
        background: rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(0, 0, 0, 0.06);
        padding: 2rem;
        border-radius: 24px;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.02);
        margin-bottom: 2rem;
    }
    .header-title {
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        background: linear-gradient(135deg, #10B981 0%, #FF6B00 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.4rem;
    }
    .header-subtitle {
        color: #6E6E73;
        font-size: 1.05rem;
        margin-bottom: 1rem;
    }
    .spec-chip-green {
        background-color: rgba(16, 185, 129, 0.1);
        color: #059669;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        border: 1px solid rgba(16, 185, 129, 0.2);
        display: inline-block;
        margin: 2px;
    }
    .spec-chip-orange {
        background-color: rgba(255, 107, 0, 0.1);
        color: #D95300;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        border: 1px solid rgba(255, 107, 0, 0.2);
        display: inline-block;
        margin: 2px;
    }
    /* Stat KPI Widgets */
    .metric-card {
        background: #FFFFFF;
        border-radius: 20px;
        padding: 1.25rem 1rem;
        border: 1px solid #E5E7EB;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.02);
        text-align: center;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #111827;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #6B7280;
        font-weight: 500;
        margin-top: 4px;
    }
    /* Custom Green / Orange Highlights for Cards */
    .card-accent-green { border-bottom: 4px solid #10B981; }
    .card-accent-orange { border-bottom: 4px solid #FF6B00; }
    .card-accent-warning { border-bottom: 4px solid #EF4444; }

    /* Button Styling */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
        color: white !important;
        border-radius: 14px !important;
        border: none !important;
        padding: 0.65rem 1.4rem !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3) !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease !important;
    }
    .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4) !important;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


# 3. Dynamic WebP Processing Engine
def process_single_image(image_bytes, target_size=(1000, 1000), max_kb=50):
    """Processes a single raw image byte stream and converts/compresses it."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        orig_w, orig_h = img.size
        orig_format = img.format or "UNKNOWN"
        is_low_res = bool(orig_w < 500 or orig_h < 500)

        # Ensure compatibility across RGB formats
        if img.mode in ("RGBA", "P", "CMYK"):
            img = img.convert("RGB")

        # Resize to Shopee target 1000x1000
        resized_img = img.resize(target_size, Image.Resampling.LANCZOS)

        # Dynamic quality search algorithm
        quality = 95
        step = 5
        buffer = io.BytesIO()

        while quality >= 10:
            buffer.seek(0)
            buffer.truncate(0)
            resized_img.save(buffer, format="WEBP", quality=quality, optimize=True)
            size_kb = buffer.tell() / 1024
            if size_kb <= max_kb:
                break
            quality -= step

        buffer.seek(0)
        under_target = bool(size_kb <= max_kb)

        # Status note for log reporting
        notes = []
        if is_low_res:
            notes.append("Low Resolution Source (<500px)")
        if not under_target:
            notes.append("Exceeds 50KB Limit")
        if not notes:
            notes.append("Optimal Optimization")

        return {
            "status": "success",
            "buffer": buffer.getvalue(),
            "orig_width": orig_w,
            "orig_height": orig_h,
            "orig_format": orig_format,
            "final_size_kb": round(size_kb, 2),
            "final_quality": quality,
            "is_low_res": is_low_res,
            "under_target_kb": under_target,
            "notes": ", ".join(notes)
        }
    except Exception as e:
        return {"status": "error", "error_msg": str(e)}


# 4. Header Section
st.markdown("""
    <div class="header-card">
        <div class="header-title">Our Shopee Image Assistant</div>
        <div class="header-subtitle">Bulk Image Resizing, WebP Conversion & Intelligent 50 KB Compression Tool</div>
        <div>
            <span class="spec-chip-green">📐 Target: 1000 x 1000 px</span>
            <span class="spec-chip-orange">⚡ Format: .WEBP</span>
            <span class="spec-chip-green">📦 Max File Size: &lt; 50 KB</span>
            <span class="spec-chip-orange">📊 Auto Excel Audit Logging</span>
        </div>
    </div>
""", unsafe_allow_html=True)


# 5. File Upload Section
uploaded_files = st.file_uploader(
    "Upload Images or ZIP archive (supports JPG, PNG, WEBP, ZIP)",
    type=["png", "jpg", "jpeg", "webp", "zip"],
    accept_multiple_files=True
)

if uploaded_files:
    # Read files list and unpack ZIPs if provided
    raw_images_list = []
    
    for file in uploaded_files:
        if file.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(file, "r") as z:
                    for filename in z.namelist():
                        if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and not filename.startswith("__MACOSX"):
                            raw_images_list.append((filename, z.read(filename)))
            except Exception as e:
                st.error(f"Error extracting ZIP file {file.name}: {e}")
        else:
            raw_images_list.append((file.name, file.read()))

    total_images_loaded = len(raw_images_list)

    if total_images_loaded > 0:
        st.info(f"Loaded **{total_images_loaded}** image(s) for processing.")
        
        start_processing = st.button("🚀 Process Batch Now", type="primary", use_container_width=True)

        if start_processing or "processed_batch_data" in st.session_state:
            
            # Execute batch conversion once if not already stored
            if start_processing or "processed_batch_data" not in st.session_state:
                processed_results = []
                log_entries = []
                
                output_zip_buffer = io.BytesIO()
                progress_bar = st.progress(0)
                status_text = st.empty()

                with zipfile.ZipFile(output_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_out:
                    for index, (filename, img_bytes) in enumerate(raw_images_list):
                        status_text.text(f"Processing image {index+1} of {total_images_loaded}: {filename}")
                        
                        result = process_single_image(img_bytes)
                        
                        if result["status"] == "success":
                            base_name = filename.rsplit(".", 1)[0]
                            clean_filename = f"{base_name}_1000x1000.webp"
                            
                            # Add to ZIP stream
                            zip_out.writestr(clean_filename, result["buffer"])

                            processed_results.append(result)
                            
                            # Logging entry for Excel output
                            log_entries.append({
                                "Original File Name": filename,
                                "Converted File Name": clean_filename,
                                "Original Dimensions": f"{result['orig_width']}x{result['orig_height']} px",
                                "Target Dimensions": "1000x1000 px",
                                "Original Format": result['orig_format'],
                                "Target Format": "WEBP",
                                "Final Size (KB)": result['final_size_kb'],
                                "Target Under 50KB": "Yes" if result['under_target_kb'] else "No",
                                "Compression Quality Level (%)": result['final_quality'],
                                "Low Quality Flag (<500px)": "Yes" if result['is_low_res'] else "No",
                                "Audit Notes": result['notes']
                            })
                        progress_bar.progress((index + 1) / total_images_loaded)

                status_text.empty()
                progress_bar.empty()

                # Generate DataFrame for Excel export
                log_df = pd.DataFrame(log_entries)
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                    log_df.to_excel(writer, index=False, sheet_name="Image_Processing_Log")
                
                # Store in session state
                st.session_state["processed_batch_data"] = {
                    "total_loaded": total_images_loaded,
                    "converted_res": len(processed_results),
                    "converted_webp": len(processed_results),
                    "under_50kb": sum(1 for r in processed_results if r["under_target_kb"]),
                    "low_res_count": sum(1 for r in processed_results if r["is_low_res"]),
                    "zip_bytes": output_zip_buffer.getvalue(),
                    "excel_bytes": excel_buffer.getvalue(),
                    "log_df": log_df
                }

            # Retrieve processed state
            data = st.session_state["processed_batch_data"]

            # 6. Analytics Dashboard Section
            st.write("---")
            st.subheader("📊 Batch Processing Dashboard")

            m1, m2, m3, m4, m5 = st.columns(5)
            
            with m1:
                st.markdown(f"""
                    <div class="metric-card card-accent-green">
                        <div class="metric-value">{data['total_loaded']}</div>
                        <div class="metric-label">Images Loaded</div>
                    </div>
                """, unsafe_allow_html=True)
            with m2:
                st.markdown(f"""
                    <div class="metric-card card-accent-green">
                        <div class="metric-value">{data['converted_res']}</div>
                        <div class="metric-label">1000x1000 Converted</div>
                    </div>
                """, unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                    <div class="metric-card card-accent-green">
                        <div class="metric-value">{data['converted_webp']}</div>
                        <div class="metric-label">WebP Converted</div>
                    </div>
                """, unsafe_allow_html=True)
            with m4:
                st.markdown(f"""
                    <div class="metric-card card-accent-orange">
                        <div class="metric-value">{data['under_50kb']}</div>
                        <div class="metric-label">Under 50 KB</div>
                    </div>
                """, unsafe_allow_html=True)
            with m5:
                st.markdown(f"""
                    <div class="metric-card card-accent-warning">
                        <div class="metric-value" style="color: {'#EF4444' if data['low_res_count'] > 0 else '#10B981'};">{data['low_res_count']}</div>
                        <div class="metric-label">Low Quality (&lt;500px)</div>
                    </div>
                """, unsafe_allow_html=True)

            st.write("")
            
            # Low Quality Warning Box
            if data['low_res_count'] > 0:
                st.warning(f"⚠️ **Attention Needed:** {data['low_res_count']} image(s) were identified with an original resolution below 500px. Rescaling these images to 1000x1000 may affect pixel clarity. Review these items using the Excel log below.")

            # 7. Downloads & Audit Logs Interface
            st.write("---")
            d_col1, d_col2 = st.columns(2)

            with d_col1:
                st.download_button(
                    label="📦 Download Optimized WebP Archive (.zip)",
                    data=data["zip_bytes"],
                    file_name="shopee_optimized_images.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            with d_col2:
                st.download_button(
                    label="📊 Download Batch Audit Report (.xlsx)",
                    data=data["excel_bytes"],
                    file_name="shopee_image_assistant_log.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            # Interactive Log Preview
            with st.expander("📋 View Image Processing Log Table"):
                st.dataframe(data["log_df"], use_container_width=True)
    else:
        st.error("No valid image files were detected in your upload.")