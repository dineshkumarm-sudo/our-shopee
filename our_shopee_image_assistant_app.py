import streamlit as st
import streamlit.components.v1 as components

# 1. Page Configuration
st.set_page_config(
    page_title="Our Shopee Image Assistant",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Server-side Excel import: bypasses browser CORS restrictions for image URLs.
import csv
import io
import ipaddress
import socket
import zipfile
import json
import os
import subprocess
import tempfile
from urllib.parse import urlparse, urljoin

import requests
from PIL import Image, ImageOps, ImageFilter

MAX_IMAGE_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT = (10, 30)
MAX_REDIRECTS = 5


def _validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only valid HTTP/HTTPS image URLs are supported.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Local network URLs are not allowed.")
    try:
        addresses = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except socket.gaierror as exc:
            raise ValueError("Could not resolve the image host.") from exc
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ValueError("Private or non-public network addresses are not allowed.")
    return parsed


def _download_image(url):
    current_url = url
    headers = {"User-Agent": "OurShopeeImageAssistant/1.0"}
    for _ in range(MAX_REDIRECTS + 1):
        parsed = _validate_public_url(current_url)
        with requests.get(current_url, headers=headers, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=False) as response:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Image host returned a redirect without a destination.")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            if content_type and not content_type.startswith("image/"):
                raise ValueError("The URL did not return an image (Content-Type: " + content_type + ").")
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError("Image exceeds the 20 MB download limit.")
                chunks.append(chunk)
            data = b"".join(chunks)
            if not data:
                raise ValueError("Downloaded file is empty.")
            return data
    raise ValueError("Image URL exceeded the redirect limit.")


def _safe_output_name(value, fallback):
    name = str(value or "").strip()
    name = __import__("re").sub(r"\.[^./\\]+$", "", name)
    name = __import__("re").sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).rstrip(". ").strip()
    return name or fallback


def _optimize_image_bytes(image_bytes, output_name):
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        orig_w, orig_h = image.size
        # Enlarge low-resolution images to at least 1000 px on their longest side.
        # LANCZOS interpolation and mild sharpening improve perceived crispness but cannot recreate missing detail.
        was_upscaled = max(orig_w, orig_h) < 1000
        if was_upscaled:
            scale = 1000 / max(orig_w, orig_h)
            if scale > 1:
                image = image.resize((max(1, round(orig_w * scale)), max(1, round(orig_h * scale))), Image.Resampling.LANCZOS)
                image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=3))

        sample = image.copy()
        sample.thumbnail((100, 100), Image.Resampling.LANCZOS)
        px = sample.load()
        edges = [px[x, 0] for x in range(sample.width)] + [px[x, sample.height - 1] for x in range(sample.width)] + [px[0, y] for y in range(sample.height)] + [px[sample.width - 1, y] for y in range(sample.height)]
        has_white_background = sum(1 for r, g, b in edges if r >= 245 and g >= 245 and b >= 245) / max(1, len(edges)) >= 0.90
        canvas = Image.new("RGB", (1000, 1000), "white")
        if has_white_background:
            image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            canvas.paste(image, ((1000 - image.width) // 2, (1000 - image.height) // 2))
            may_be_stretched = False
            background_note = "White background detected; aspect ratio preserved."
        else:
            canvas.paste(image.resize((1000, 1000), Image.Resampling.LANCZOS), (0, 0))
            may_be_stretched = True
            background_note = "WARNING: Non-white background detected; image may be stretched to 1000x1000."

        # Compress the already-composed square canvas so background handling is retained.
        image = canvas

        # Enforce a strict maximum of 49 KiB, including difficult images.
        # If low quality is not enough, shrink the image content inside the fixed white canvas.
        content_scale = 1.0
        encoded = None
        quality = 92
        while True:
            content_w = max(1, round(image.width * content_scale))
            content_h = max(1, round(image.height * content_scale))
            content = image if content_scale == 1.0 else image.resize((content_w, content_h), Image.Resampling.LANCZOS)
            work_canvas = Image.new("RGB", (1000, 1000), "white")
            work_canvas.paste(content, ((1000 - content.width) // 2, (1000 - content.height) // 2))
            quality = 92
            while quality >= 10:
                buffer = io.BytesIO()
                work_canvas.save(buffer, format="WEBP", quality=quality, method=6)
                encoded = buffer.getvalue()
                if len(encoded) <= 49 * 1024:
                    break
                quality -= 5
            if len(encoded) <= 49 * 1024:
                break
            if content_scale <= 0.35:
                raise ValueError("Could not compress this image below 49 KB.")
            content_scale = round(content_scale - 0.1, 2)

        return {
            "name": output_name + ".webp",
            "bytes": encoded,
            "original_resolution": f"{orig_w}x{orig_h}",
            "final_canvas": "1000x1000",
            "size_kb": round(len(encoded) / 1024, 2),
            "quality": quality,
            "under_50_kb": len(encoded) <= 49 * 1024,
            "upscaled": was_upscaled,
            "resized": True,
            "content_scale_percent": round(content_scale * 100),
            "white_background_detected": has_white_background,
            "may_be_stretched": may_be_stretched,
            "background_note": background_note,
            "compressed": True,
        }


def _process_excel_server_side(uploaded_file):
    raw = uploaded_file.getvalue()
    workbook = __import__("openpyxl").load_workbook(io.BytesIO(raw), read_only=True, data_only=True) if uploaded_file.name.lower().endswith((".xlsx", ".xlsm")) else None
    if workbook:
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            raise ValueError("The spreadsheet is empty.")
        headers = [str(value or "").strip().lower() for value in header_row]
        rows = [dict(zip(headers, row)) for row in iterator]
    elif uploaded_file.name.lower().endswith(".csv"):
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("The CSV file is empty.")
        rows = [{str(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    else:
        raise ValueError("Please upload an .xlsx or .csv file. Save legacy .xls files as .xlsx first.")

    url_key = next((key for key in (rows[0].keys() if rows else []) if key == "image link"), None)
    name_key = next((key for key in (rows[0].keys() if rows else []) if key == "image name"), None)
    if not url_key or not name_key:
        raise ValueError('Required columns "Image link" and "Image name" were not found in the first worksheet.')

    output_rows = []
    failures = []
    used_names = set()
    active_rows = [(idx + 2, row) for idx, row in enumerate(rows) if str(row.get(url_key) or "").strip() or str(row.get(name_key) or "").strip()]
    progress = st.progress(0)
    status = st.empty()
    live_tiles = st.empty()
    counts = {"downloaded": 0, "resized": 0, "compressed": 0, "errors": 0}

    def _render_live_tiles(current, total):
        live_tiles.markdown(
            f"""
            <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 16px;">
              <div style="border:1px solid #d1d5db;border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#64748b;">Downloaded</div><div style="font-size:25px;font-weight:700;">{counts['downloaded']}</div></div>
              <div style="border:1px solid #d1d5db;border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#64748b;">Resized</div><div style="font-size:25px;font-weight:700;">{counts['resized']}</div></div>
              <div style="border:1px solid #d1d5db;border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#64748b;">Compressed ≤ 49 KB</div><div style="font-size:25px;font-weight:700;color:#059669;">{counts['compressed']}</div></div>
              <div style="border:1px solid #d1d5db;border-radius:12px;padding:12px;text-align:center;"><div style="font-size:12px;color:#64748b;">Errors</div><div style="font-size:25px;font-weight:700;color:#dc2626;">{counts['errors']}</div></div>
            </div>
            <div style="font-size:12px;color:#64748b;">Progress: {current} / {total} rows checked</div>
            """,
            unsafe_allow_html=True,
        )

    _render_live_tiles(0, len(active_rows))
    for index, (sheet_row, row) in enumerate(active_rows):
        url = str(row.get(url_key) or "").strip()
        raw_name = str(row.get(name_key) or "").strip()
        status.write(f"Downloading and optimizing image {index + 1} of {len(active_rows)}...")
        progress.progress(index / max(1, len(active_rows)))
        if not url or not raw_name:
            failures.append(f"Row {sheet_row}: Image link or Image name is blank.")
            counts["errors"] += 1
            _render_live_tiles(index + 1, len(active_rows))
            progress.progress((index + 1) / max(1, len(active_rows)))
            continue
        try:
            data = _download_image(url)
            counts["downloaded"] += 1
            _render_live_tiles(index + 1, len(active_rows))
            base_name = _safe_output_name(raw_name, f"image_{index + 1}")
            unique_name = base_name
            suffix = 2
            while (unique_name + ".webp").lower() in used_names:
                unique_name = f"{base_name}_{suffix}"
                suffix += 1
            used_names.add((unique_name + ".webp").lower())
            result = _optimize_image_bytes(data, unique_name)
            result["original_name"] = raw_name
            output_rows.append(result)
            counts["resized"] += 1
            if len(result["bytes"]) <= 49 * 1024:
                counts["compressed"] += 1
            _render_live_tiles(index + 1, len(active_rows))
        except Exception as exc:
            failures.append(f"Row {sheet_row} ({raw_name or 'unnamed'}): {str(exc)[:250]}")
            counts["errors"] += 1
            _render_live_tiles(index + 1, len(active_rows))
        progress.progress((index + 1) / max(1, len(active_rows)))

    status.write(f"Completed: {len(output_rows)} successful, {len(failures)} failed.")
    progress.empty()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in output_rows:
            archive.writestr(item["name"], item["bytes"])
        audit_buffer = io.StringIO()
        fields = ["Original Name", "Output WebP Name", "Original Resolution", "Final Canvas", "Format", "Final Size (KB)", "Quality Level (%)", "Under 50 KB", "Upscaled (< 600px)", "Content Scale (%)", "White Background Detected", "May Be Stretched", "Processing Comment"]
        writer = csv.DictWriter(audit_buffer, fieldnames=fields)
        writer.writeheader()
        for item in output_rows:
            writer.writerow({
                "Original Name": item["original_name"],
                "Output WebP Name": item["name"],
                "Original Resolution": item["original_resolution"],
                "Final Canvas": item["final_canvas"],
                "Format": "WEBP",
                "Final Size (KB)": item["size_kb"],
                "Quality Level (%)": item["quality"],
                "Under 50 KB": "Yes" if item["under_50_kb"] else "No",
                "Upscaled (< 600px)": "Yes" if item["upscaled"] else "No",
                "Content Scale (%)": item.get("content_scale_percent", 100),
                "White Background Detected": "Yes" if item.get("white_background_detected") else "No",
                "May Be Stretched": "Yes" if item.get("may_be_stretched") else "No",
                "Processing Comment": item.get("background_note", ""),
            })
        archive.writestr("Shopee_Image_Processing_Log.csv", audit_buffer.getvalue())
    return zip_buffer.getvalue(), output_rows, failures




MAX_VIDEO_BYTES = 1024 * 1024 * 1024
MAX_VIDEO_OUTPUT_BYTES = 15_000_000


def _download_video(url):
    parsed = _validate_public_url(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        # Vimeo page links are HTML pages, not direct video files. Use yt-dlp
        # to resolve a permitted public/unlisted playback source.
        try:
            import yt_dlp
        except ImportError as exc:
            raise ValueError("Vimeo link support is not installed yet. Please wait for the app deployment to finish.") from exc

        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = os.path.join(temp_dir, "vimeo_source.%(ext)s")
            options = {
                "format": "bestvideo*+bestaudio/best",
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                "noplaylist": True,
                "max_filesize": MAX_VIDEO_BYTES,
                "socket_timeout": 60,
                "retries": 2,
                "fragment_retries": 2,
                "quiet": True,
                "no_warnings": True,
            }
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.extract_info(url, download=True)
            except Exception as exc:
                message = str(exc).splitlines()[0][:220]
                raise ValueError(
                    "Could not download this Vimeo video. Check that the link is accessible and that its owner permits access/download. Details: "
                    + message
                ) from exc
            candidates = [
                os.path.join(temp_dir, name)
                for name in os.listdir(temp_dir)
                if os.path.isfile(os.path.join(temp_dir, name))
                and not name.endswith((".part", ".ytdl", ".json"))
            ]
            if not candidates:
                raise ValueError("Vimeo did not provide a downloadable video file for this link.")
            source_path = max(candidates, key=os.path.getsize)
            with open(source_path, "rb") as source_file:
                data = source_file.read()
            if not data:
                raise ValueError("Vimeo returned an empty video file.")
            if len(data) > MAX_VIDEO_BYTES:
                raise ValueError("Source video exceeds the 1 GB download limit.")
            return data

    current_url = url
    headers = {"User-Agent": "OurShopeeVideoAssistant/1.0"}
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_url(current_url)
        with requests.get(current_url, headers=headers, timeout=(10, 60), stream=True, allow_redirects=False) as response:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Video host returned a redirect without a destination.")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            if content_type and not (content_type.startswith("video/") or content_type in ("application/octet-stream", "binary/octet-stream")):
                raise ValueError("The URL did not return a video file. For Vimeo, provide the Vimeo page link; for other sites, use a direct video-file URL. Content-Type: " + content_type + ".")
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise ValueError("Source video exceeds the 1 GB download limit.")
                chunks.append(chunk)
            data = b"".join(chunks)
            if not data:
                raise ValueError("Downloaded video is empty.")
            return data
    raise ValueError("Video URL exceeded the redirect limit.")

def _process_video_server_side(uploaded_file):
    raw = uploaded_file.getvalue()
    if uploaded_file.name.lower().endswith((".xlsx", ".xlsm")):
        workbook = __import__("openpyxl").load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            raise ValueError("The spreadsheet is empty.")
        headers = [str(value or "").strip().lower() for value in header_row]
        rows = [dict(zip(headers, row)) for row in iterator]
    elif uploaded_file.name.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames:
            raise ValueError("The CSV file is empty.")
        rows = [{str(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    else:
        raise ValueError("Please upload an .xlsx or .csv file. Save legacy .xls files as .xlsx first.")

    first_keys = rows[0].keys() if rows else []
    url_key = next((key for key in first_keys if key == "video link"), None)
    name_key = next((key for key in first_keys if key == "video name"), None)
    if not url_key or not name_key:
        raise ValueError('Required columns "Video link" and "Video name" were not found in the first worksheet.')

    active_rows = [(idx + 2, row) for idx, row in enumerate(rows) if str(row.get(url_key) or "").strip() or str(row.get(name_key) or "").strip()]
    output_rows = []
    failures = []
    used_names = set()
    progress = st.progress(0)
    status = st.empty()
    for index, (sheet_row, row) in enumerate(active_rows):
        url = str(row.get(url_key) or "").strip()
        raw_name = str(row.get(name_key) or "").strip()
        status.write(f"Downloading and compressing video {index + 1} of {len(active_rows)}...")
        progress.progress(index / max(1, len(active_rows)))
        if not url or not raw_name:
            failures.append(f"Row {sheet_row}: Video link or Video name is blank.")
            progress.progress((index + 1) / max(1, len(active_rows)))
            continue
        try:
            video_data = _download_video(url)
            base_name = _safe_output_name(raw_name, f"video_{index + 1}")
            unique_name = base_name
            suffix = 2
            while (unique_name + ".mp4").lower() in used_names:
                unique_name = f"{base_name}_{suffix}"
                suffix += 1
            used_names.add((unique_name + ".mp4").lower())

            with tempfile.TemporaryDirectory() as temp_dir:
                input_path = os.path.join(temp_dir, "source_video")
                output_path = os.path.join(temp_dir, "compressed.mp4")
                with open(input_path, "wb") as source_file:
                    source_file.write(video_data)

                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-show_entries", "stream=codec_type,width,height", "-of", "json", input_path],
                    capture_output=True, text=True, timeout=60
                )
                if probe.returncode != 0:
                    raise ValueError("Could not read video metadata. The link may not be a supported video file.")
                metadata = json.loads(probe.stdout or "{}")
                video_stream = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video"), None)
                if not video_stream:
                    raise ValueError("The downloaded file does not contain a video stream.")
                duration = float(metadata.get("format", {}).get("duration") or 0)
                if duration <= 0:
                    raise ValueError("Could not determine video duration.")
                width, height = int(video_stream["width"]), int(video_stream["height"])
                if width % 2 or height % 2:
                    raise ValueError(f"Video resolution {width}x{height} has an odd dimension; this MP4 encoding profile cannot preserve it safely.")

                audio_exists = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
                audio_bitrate = 96000 if audio_exists else 0
                target_total_bitrate = int((MAX_VIDEO_OUTPUT_BYTES * 8 / duration) * 0.86)
                video_bitrate = max(100000, target_total_bitrate - audio_bitrate)
                last_size = None
                for attempt in range(8):
                    command = [
                        "ffmpeg", "-y", "-v", "error", "-i", input_path,
                        "-map", "0:v:0", "-map", "0:a:0?",
                        "-c:v", "libx264", "-preset", "medium",
                        "-b:v", str(video_bitrate), "-maxrate", str(video_bitrate),
                        "-bufsize", str(video_bitrate * 2), "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "96k", "-sn", "-dn",
                        "-movflags", "+faststart", "-f", "mp4", output_path
                    ]
                    encoded = subprocess.run(command, capture_output=True, text=True, timeout=1800)
                    if encoded.returncode != 0:
                        message = (encoded.stderr or "FFmpeg encoding failed.").strip().splitlines()[-1]
                        raise ValueError("Video conversion failed: " + message[:220])
                    last_size = os.path.getsize(output_path)
                    if last_size <= MAX_VIDEO_OUTPUT_BYTES:
                        break
                    video_bitrate = max(40000, int(video_bitrate * (MAX_VIDEO_OUTPUT_BYTES / last_size) * 0.88))
                    if video_bitrate <= 40000 and last_size > MAX_VIDEO_OUTPUT_BYTES:
                        break
                if not last_size or last_size > MAX_VIDEO_OUTPUT_BYTES:
                    raise ValueError("Could not compress this video to 15 MB or less without changing its resolution.")

                with open(output_path, "rb") as output_file:
                    encoded_data = output_file.read()

            output_rows.append({
                "name": unique_name + ".mp4",
                "bytes": encoded_data,
                "original_name": raw_name,
                "original_resolution": f"{width}x{height}",
                "duration_seconds": round(duration, 2),
                "size_mb": round(len(encoded_data) / (1024 * 1024), 2),
                "format": "MP4",
            })
        except Exception as exc:
            failures.append(f"Row {sheet_row} ({raw_name or 'unnamed'}): {str(exc)[:250]}")
        progress.progress((index + 1) / max(1, len(active_rows)))

    status.write(f"Completed: {len(output_rows)} successful, {len(failures)} failed.")
    progress.empty()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in output_rows:
            archive.writestr(item["name"], item["bytes"])
        audit_buffer = io.StringIO()
        fields = ["Original Name", "Output MP4 Name", "Original Resolution", "Duration (seconds)", "Format", "Final Size (MB)", "Under 15 MB"]
        writer = csv.DictWriter(audit_buffer, fieldnames=fields)
        writer.writeheader()
        for item in output_rows:
            writer.writerow({
                "Original Name": item["original_name"],
                "Output MP4 Name": item["name"],
                "Original Resolution": item["original_resolution"],
                "Duration (seconds)": item["duration_seconds"],
                "Format": item["format"],
                "Final Size (MB)": item["size_mb"],
                "Under 15 MB": "Yes" if len(item["bytes"]) <= MAX_VIDEO_OUTPUT_BYTES else "No",
            })
        archive.writestr("Shopee_Video_Processing_Log.csv", audit_buffer.getvalue())
    return zip_buffer.getvalue(), output_rows, failures


st.markdown("### Excel Import — Image or Video")
import_mode = st.selectbox("Choose what you want to process", ["Images", "Videos"], key="server_import_mode")
if import_mode == "Images":
    st.caption("Image mode: uses “Image link” and “Image name” columns. Images are processed to a 1000×1000 canvas, WebP, and 49 KB or less. Low-resolution images are enlarged, but upscaling cannot restore missing source detail.")
    server_excel = st.file_uploader("Upload Excel/CSV with “Image link” and “Image name” columns", type=["xlsx", "xlsm", "csv"], key="server_excel_upload")
    if server_excel is not None and st.button("Download and Optimize Images", type="primary", key="server_excel_process"):
        try:
            with st.spinner("Processing spreadsheet images..."):
                zip_data, successful_images, failed_rows = _process_excel_server_side(server_excel)
            st.success(f"Processed {len(successful_images)} image(s); {len(failed_rows)} row(s) failed.")
            st.download_button("Download Optimized Images + Audit Log (.ZIP)", data=zip_data, file_name="Shopee_Optimized_Images_From_Excel.zip", mime="application/zip")
            if failed_rows:
                with st.expander(f"View failed rows ({len(failed_rows)})"):
                    st.text("\n".join(failed_rows))
            if successful_images:
                st.dataframe([{"Output Name": item["name"], "Original Resolution": item["original_resolution"], "Final Canvas": item["final_canvas"], "Size (KB)": item["size_kb"], "Quality": item["quality"], "Upscaled": item["upscaled"], "White Background": item["white_background_detected"], "May Be Stretched": item["may_be_stretched"], "Comment": item["background_note"]} for item in successful_images], use_container_width=True)
        except Exception as exc:
            st.error(f"Could not process this spreadsheet: {exc}")
else:
    st.caption("Video mode: uses “Video link” and “Video name” columns. Output is MP4, kept at the original resolution, and compressed to 15 MB or less. Compression may reduce visual/audio quality. Direct, publicly accessible video links are required.")
    st.info("Example spreadsheet headers: Video link | Video name")
    video_excel = st.file_uploader("Upload Excel/CSV with “Video link” and “Video name” columns", type=["xlsx", "xlsm", "csv"], key="server_video_excel_upload")
    if video_excel is not None and st.button("Download and Compress Videos", type="primary", key="server_video_process"):
        try:
            with st.spinner("Downloading and compressing videos..."):
                zip_data, successful_videos, failed_rows = _process_video_server_side(video_excel)
            st.success(f"Processed {len(successful_videos)} video(s); {len(failed_rows)} row(s) failed.")
            st.download_button("Download MP4 Videos + Audit Log (.ZIP)", data=zip_data, file_name="Shopee_Compressed_Videos_From_Excel.zip", mime="application/zip")
            if failed_rows:
                with st.expander(f"View failed rows ({len(failed_rows)})"):
                    st.text("\n".join(failed_rows))
            if successful_videos:
                st.dataframe([{"Output Name": item["name"], "Original Resolution": item["original_resolution"], "Duration (seconds)": item["duration_seconds"], "Size (MB)": item["size_mb"], "Format": item["format"]} for item in successful_videos], use_container_width=True)
        except Exception as exc:
            st.error(f"Could not process this spreadsheet: {exc}")


# 2. Inject HTML Canvas Tool into Streamlit
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Our Shopee Image Assistant</title>

    <!-- Tailwind CSS for high contrast & clean styling -->
    <script src="https://cdn.tailwindcss.com"></script>

    <!-- JSZip for client-side batch download -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>

    <!-- SheetJS (xlsx) for Excel Audit Log export -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>

    <style>
        body {
            background-color: #f8fafc;
            color: #0f172a;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .drag-over {
            border-color: #059669 !important;
            background-color: #ecfdf5 !important;
        }
    </style>
</head>
<body class="p-4 md:p-8">

    <!-- App Container -->
    <div class="max-w-7xl mx-auto space-y-6">

        <!-- Header Card -->
        <div class="bg-white border border-slate-200 rounded-2xl p-6 text-center shadow-sm">
            <h1 class="text-3xl font-extrabold bg-gradient-to-r from-emerald-600 to-amber-600 bg-clip-text text-transparent">
                Our Shopee Image Assistant
            </h1>
            <p class="text-slate-600 text-sm md:text-base mt-2">
                Automated WebP conversion, 1000x1000 canvas processing, and high-quality upscaling for low-resolution images.
                Upscaling improves presentation but cannot fully restore missing source detail.
            </p>
            <div class="flex flex-wrap justify-center gap-2 mt-4">
                <span class="bg-emerald-50 text-emerald-700 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-200">
                    📐 1000 x 1000 Canvas
                </span>
                <span class="bg-amber-50 text-amber-700 text-xs font-semibold px-3 py-1 rounded-full border border-amber-200">
                    ⚡ Exact Name .WEBP
                </span>
                <span class="bg-emerald-50 text-emerald-700 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-200">
                    📦 &lt; 49 KB Strict Size
                </span>
                <span class="bg-amber-50 text-amber-700 text-xs font-semibold px-3 py-1 rounded-full border border-amber-200">
                    🔍 Low-Resolution Upscaling
                </span>
            </div>
        </div>

        <!-- Upload Zone -->
        <div id="dropzone" class="bg-white border-2 border-dashed border-slate-300 rounded-2xl p-8 text-center shadow-sm transition-all duration-200 cursor-pointer hover:border-emerald-500">
            <input type="file" id="fileInput" multiple accept="image/*,.zip" class="hidden">
            <div class="space-y-3">
                <div class="w-14 h-14 mx-auto bg-emerald-50 rounded-full flex items-center justify-center text-emerald-600 text-2xl">
                    📁
                </div>
                <div class="text-slate-800 font-bold text-lg">
                    Click to browse or drag & drop images or ZIP file here
                </div>
                <div class="text-slate-500 text-xs font-medium">
                    Supports PNG, JPG, JPEG, WEBP, BMP, and ZIP archives
                </div>
            </div>
        </div>

        <!-- Excel URL Import -->
        <div class="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <h2 class="text-lg font-bold text-slate-800">Import Images from Excel</h2>
            <p class="text-sm text-slate-600 mt-1 mb-4">Upload an .xlsx, .xls, or .csv file with columns named <strong>Image link</strong> and <strong>Image name</strong>. Images will be downloaded, optimized using the same settings, and saved using the names in the second column.</p>
            <div class="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
                <input type="file" id="excelInput" accept=".xlsx,.xls,.csv" class="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:font-semibold file:bg-emerald-50 file:text-emerald-700 hover:file:bg-emerald-100">
                <button id="processExcelBtn" disabled class="shrink-0 bg-emerald-600 disabled:bg-slate-300 hover:bg-emerald-700 text-white font-bold py-2 px-5 rounded-lg">Process Excel Images</button>
            </div>
            <p id="excelHelp" class="text-xs text-slate-500 mt-2">Use direct image URLs that are publicly accessible. Some websites block browser-based downloads; those rows will be reported as failed.</p>
        </div>

        <!-- Progress Indicator -->
        <div id="progressContainer" class="hidden bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
            <div class="flex justify-between items-center mb-2">
                <span id="progressText" class="text-sm font-semibold text-slate-800">Processing images...</span>
                <span id="progressPercent" class="text-sm font-bold text-emerald-600">0%</span>
            </div>
            <div class="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
                <div id="progressBar" class="bg-emerald-600 h-2.5 rounded-full transition-all duration-200" style="width: 0%"></div>
            </div>
        </div>

        <!-- Live Processing Tiles -->
        <div id="liveStats" class="hidden grid grid-cols-2 md:grid-cols-4 gap-3">
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm"><div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Downloaded</div><div id="liveDownloaded" class="text-2xl font-extrabold text-sky-600 mt-1">0</div></div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm"><div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Resized</div><div id="liveResized" class="text-2xl font-extrabold text-emerald-600 mt-1">0</div></div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm"><div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Compressed ≤ 49 KB</div><div id="liveCompressed" class="text-2xl font-extrabold text-emerald-600 mt-1">0</div></div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm"><div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Errors</div><div id="liveErrors" class="text-2xl font-extrabold text-rose-600 mt-1">0</div></div>
        </div>

        <!-- Metrics Dashboard -->
        <div id="dashboard" class="hidden grid grid-cols-2 md:grid-cols-5 gap-3">
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                <div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Total Loaded</div>
                <div id="statTotal" class="text-2xl font-extrabold text-slate-900 mt-1">0</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                <div class="text-xs font-bold uppercase text-slate-500 tracking-wider">1000x1000 Canvas</div>
                <div id="statCanvas" class="text-2xl font-extrabold text-emerald-600 mt-1">0</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                <div class="text-xs font-bold uppercase text-slate-500 tracking-wider">WebP Format</div>
                <div id="statWebp" class="text-2xl font-extrabold text-emerald-600 mt-1">0</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                <div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Under 50 KB</div>
                <div id="statUnder50" class="text-2xl font-extrabold text-emerald-600 mt-1">0</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm col-span-2 md:col-span-1">
                <div class="text-xs font-bold uppercase text-slate-500 tracking-wider">Upscaled (&lt;600px)</div>
                <div id="statUpscaled" class="text-2xl font-extrabold text-amber-600 mt-1">0</div>
            </div>
        </div>

        <!-- Actions / Downloads -->
        <div id="actionsContainer" class="hidden flex flex-col sm:flex-row gap-3">
            <button id="downloadZipBtn" class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 px-6 rounded-xl shadow-md transition-all flex items-center justify-center gap-2">
                <span>📦</span> Download All Optimized (.ZIP)
            </button>
            <button id="downloadExcelBtn" class="flex-1 bg-slate-800 hover:bg-slate-900 text-white font-bold py-3 px-6 rounded-xl shadow-md transition-all flex items-center justify-center gap-2">
                <span>📊</span> Download Batch Audit Log (.XLSX)
            </button>
        </div>

        <!-- Data Log Table -->
        <div id="tableContainer" class="hidden bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            <div class="p-4 bg-slate-50 border-b border-slate-200 font-bold text-slate-800">
                Audit Log & Image Preview
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse text-xs md:text-sm">
                    <thead>
                        <tr class="bg-slate-100 text-slate-700 font-bold border-b border-slate-200">
                            <th class="p-3">Preview</th>
                            <th class="p-3">Original Name</th>
                            <th class="p-3">Output WebP</th>
                            <th class="p-3">Original Size</th>
                            <th class="p-3">Final Canvas</th>
                            <th class="p-3">Size (KB)</th>
                            <th class="p-3">Quality</th>
                            <th class="p-3">&lt; 50 KB</th>
                            <th class="p-3">Upscaled</th>
                            <th class="p-3">Background / Stretch Note</th>
                        </tr>
                    </thead>
                    <tbody id="tableBody" class="divide-y divide-slate-200 text-slate-800">
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <!-- Processing Logic -->
    <script>
        const dropzone = document.getElementById('dropzone');
        const fileInput = document.getElementById('fileInput');
        const progressContainer = document.getElementById('progressContainer');
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');
        const dashboard = document.getElementById('dashboard');
        const actionsContainer = document.getElementById('actionsContainer');
        const tableContainer = document.getElementById('tableContainer');
        const tableBody = document.getElementById('tableBody');
        const liveStats = document.getElementById('liveStats');
        const liveDownloaded = document.getElementById('liveDownloaded');
        const liveResized = document.getElementById('liveResized');
        const liveCompressed = document.getElementById('liveCompressed');
        const liveErrors = document.getElementById('liveErrors');
        let liveCounts = { downloaded: 0, resized: 0, compressed: 0, errors: 0 };

        function resetLiveStats() {
            liveCounts = { downloaded: 0, resized: 0, compressed: 0, errors: 0 };
            updateLiveStats();
            liveStats.classList.remove('hidden');
        }

        function updateLiveStats() {
            liveDownloaded.innerText = liveCounts.downloaded;
            liveResized.innerText = liveCounts.resized;
            liveCompressed.innerText = liveCounts.compressed;
            liveErrors.innerText = liveCounts.errors;
        }

        const statTotal = document.getElementById('statTotal');
        const statCanvas = document.getElementById('statCanvas');
        const statWebp = document.getElementById('statWebp');
        const statUnder50 = document.getElementById('statUnder50');
        const statUpscaled = document.getElementById('statUpscaled');

        let processedFiles = [];
        let selectedExcelFile = null;
        const excelInput = document.getElementById('excelInput');
        const processExcelBtn = document.getElementById('processExcelBtn');
        const excelHelp = document.getElementById('excelHelp');

        excelInput.addEventListener('change', (e) => {
            selectedExcelFile = e.target.files && e.target.files[0] ? e.target.files[0] : null;
            processExcelBtn.disabled = !selectedExcelFile;
            if (selectedExcelFile) excelHelp.textContent = "Selected: " + selectedExcelFile.name;
        });

        processExcelBtn.addEventListener('click', async () => {
            if (selectedExcelFile) await processExcelImages(selectedExcelFile);
        });

        dropzone.addEventListener('click', () => fileInput.click());

        ['dragenter', 'dragover'].forEach(name => {
            dropzone.addEventListener(name, (e) => {
                e.preventDefault();
                dropzone.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(name => {
            dropzone.addEventListener(name, (e) => {
                e.preventDefault();
                dropzone.classList.remove('drag-over');
            });
        });

        dropzone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length) handleFiles(files);
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length) handleFiles(e.target.files);
        });

        async function handleFiles(files) {
            const fileList = [];

            for (let file of files) {
                if (file.name.toLowerCase().endsWith('.zip')) {
                    const zip = await JSZip.loadAsync(file);
                    for (let relativePath in zip.files) {
                        const zipEntry = zip.files[relativePath];
                        if (!zipEntry.dir && !relativePath.startsWith('__MACOSX')) {
                            const ext = relativePath.split('.').pop().toLowerCase();
                            if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(ext)) {
                                const blob = await zipEntry.async('blob');
                                const filename = relativePath.split('/').pop();
                                fileList.push(new File([blob], filename, { type: `image/${ext}` }));
                            }
                        }
                    }
                } else if (file.type.startsWith('image/')) {
                    fileList.push(file);
                }
            }

            if (!fileList.length) return;

            processedFiles = [];
            tableBody.innerHTML = '';
            resetLiveStats();
            dashboard.classList.add('hidden');
            actionsContainer.classList.add('hidden');
            tableContainer.classList.add('hidden');
            progressContainer.classList.remove('hidden');

            for (let i = 0; i < fileList.length; i++) {
                const file = fileList[i];
                const pct = Math.round(((i + 1) / fileList.length) * 100);
                progressText.innerText = `Processing ${i + 1} of ${fileList.length}: ${file.name}`;
                progressPercent.innerText = `${pct}%`;
                progressBar.style.width = `${pct}%`;

                try {
                    const result = await processImage(file);
                    liveCounts.downloaded += 1;
                    liveCounts.resized += 1;
                    if (Number(result.sizeKB) <= 49) liveCounts.compressed += 1;
                    processedFiles.push(result);
                    renderTableRow(result);
                } catch (err) {
                    liveCounts.errors += 1;
                }
                updateLiveStats();
            }

            progressText.innerText = '✅ Batch processing complete!';
            updateDashboard();

            dashboard.classList.remove('hidden');
            actionsContainer.classList.remove('hidden');
            tableContainer.classList.remove('hidden');
        }

        function safeOutputBaseName(value, fallback) {
            let name = String(value ?? '').trim();
            name = name.replace(/\.[^./\\]+$/, '');
            name = name.replace(/[\\/:*?"<>|\x00-\x1F]/g, '_').replace(/[. ]+$/g, '').trim();
            return name || fallback || 'image';
        }

        async function processExcelImages(excelFile) {
            let rows;
            try {
                const buffer = await excelFile.arrayBuffer();
                const workbook = excelFile.name.toLowerCase().endsWith('.csv')
                    ? XLSX.read(await excelFile.text(), { type: 'string' })
                    : XLSX.read(buffer, { type: 'array' });
                const sheet = workbook.Sheets[workbook.SheetNames[0]];
                rows = XLSX.utils.sheet_to_json(sheet, { defval: '' });
            } catch (err) {
                alert('Could not read the Excel/CSV file. Please check that it is a valid file.');
                return;
            }

            if (!rows.length) {
                alert('The selected spreadsheet has no data rows.');
                return;
            }

            const normalizeHeader = value => String(value).trim().toLowerCase().replace(/\s+/g, ' ');
            const headers = Object.keys(rows[0]);
            const urlHeader = headers.find(h => normalizeHeader(h) === 'image link');
            const nameHeader = headers.find(h => normalizeHeader(h) === 'image name');
            if (!urlHeader || !nameHeader) {
                alert('Required columns not found. The first worksheet must contain headers named "Image link" and "Image name".');
                return;
            }

            processedFiles = [];
            tableBody.innerHTML = '';
            dashboard.classList.add('hidden');
            actionsContainer.classList.add('hidden');
            tableContainer.classList.add('hidden');
            resetLiveStats();
            progressContainer.classList.remove('hidden');
            processExcelBtn.disabled = true;
            excelInput.disabled = true;
            const failures = [];
            const usedNames = new Set();
            const validRows = rows.filter(row => String(row[urlHeader] || '').trim() || String(row[nameHeader] || '').trim());

            for (let i = 0; i < validRows.length; i++) {
                const row = validRows[i];
                const rawUrl = String(row[urlHeader] || '').trim();
                const rawName = String(row[nameHeader] || '').trim();
                const pct = Math.round(((i + 1) / validRows.length) * 100);
                progressText.innerText = "Downloading and processing " + (i + 1) + " of " + validRows.length;
                progressPercent.innerText = pct + "%";
                progressBar.style.width = pct + "%";

                if (!rawUrl || !rawName) {
                    liveCounts.errors += 1;
                    updateLiveStats();
                    failures.push("Row " + (i + 2) + ": Image link or Image name is blank.");
                    continue;
                }

                try {
                    const parsedUrl = new URL(rawUrl);
                    if (!['http:', 'https:'].includes(parsedUrl.protocol)) throw new Error('Only HTTP/HTTPS image links are supported.');
                    const response = await fetch(parsedUrl.href);
                    if (!response.ok) throw new Error("Download failed (HTTP " + response.status + ").");
                    const blob = await response.blob();
                    if (!blob.size) throw new Error('Downloaded file is empty.');
                    liveCounts.downloaded += 1;
                    updateLiveStats();
                    if (blob.type && !blob.type.startsWith('image/')) throw new Error("URL did not return an image (" + blob.type + ").");

                    const baseName = safeOutputBaseName(rawName, "image_" + (i + 1));
                    let uniqueName = baseName;
                    let suffix = 2;
                    while (usedNames.has((uniqueName + '.webp').toLowerCase())) uniqueName = baseName + '_' + suffix++;
                    usedNames.add((uniqueName + '.webp').toLowerCase());
                    const ext = (blob.type.split('/')[1] || 'jpeg').replace('jpeg', 'jpg').replace('svg+xml', 'svg');
                    const imageFile = new File([blob], uniqueName + '.' + ext, { type: blob.type || 'image/jpeg' });
                    const result = await processImage(imageFile, uniqueName);
                    result.origName = rawName;
                    processedFiles.push(result);
                    liveCounts.resized += 1;
                    if (Number(result.sizeKB) <= 49) liveCounts.compressed += 1;
                    updateLiveStats();
                    renderTableRow(result);
                } catch (err) {
                    liveCounts.errors += 1;
                    updateLiveStats();
                    failures.push("Row " + (i + 2) + " (" + (rawName || 'unnamed') + "): " + (err.message || 'Could not download/process image. The host may block browser access (CORS).'));
                }
            }

            progressText.innerText = "Processing complete: " + processedFiles.length + " successful, " + failures.length + " failed.";
            updateDashboard();
            dashboard.classList.remove('hidden');
            actionsContainer.classList.remove('hidden');
            tableContainer.classList.remove('hidden');
            processExcelBtn.disabled = false;
            excelInput.disabled = false;
            if (failures.length) {
                const preview = failures.slice(0, 10).join('\n');
                alert("Finished with " + failures.length + " failed row(s).\n\n" + preview + (failures.length > 10 ? "\n...and " + (failures.length - 10) + " more. Check the browser console for details." : ''));
                console.warn('Excel image import failures:', failures);
                excelHelp.textContent = processedFiles.length + " image(s) processed; " + failures.length + " row(s) failed. See the alert and browser console for failed rows.";
            } else {
                excelHelp.textContent = "Successfully processed all " + processedFiles.length + " image(s) from " + excelFile.name + ".";
            }
        }

        function processImage(file, requestedBaseName = null) {
            return new Promise((resolve) => {
                const img = new Image();
                const url = URL.createObjectURL(file);

                img.onload = async () => {
                    const origW = img.width;
                    const origH = img.height;
                    const wasUpscaled = Math.max(origW, origH) < 1000;

                    let srcW = origW;
                    let srcH = origH;
                    let canvasSource = img;

                    if (wasUpscaled) {
                        // Enlarge low-resolution images to 1000 px on their longest side.
                        // Interpolation improves size/smoothness but cannot invent missing detail.
                        const scale = 1000 / Math.max(origW, origH);
                        if (scale > 1) {
                            srcW = Math.max(1, Math.round(origW * scale));
                            srcH = Math.max(1, Math.round(origH * scale));
                            const upCanvas = document.createElement('canvas');
                            upCanvas.width = srcW;
                            upCanvas.height = srcH;
                            const uCtx = upCanvas.getContext('2d');
                            uCtx.imageSmoothingEnabled = true;
                            uCtx.imageSmoothingQuality = 'high';
                            uCtx.drawImage(img, 0, 0, srcW, srcH);
                            canvasSource = upCanvas;
                        }
                    }

                    const canvas = document.createElement('canvas');
                    canvas.width = 1000;
                    canvas.height = 1000;
                    const ctx = canvas.getContext('2d');

                    ctx.fillStyle = '#FFFFFF';
                    ctx.fillRect(0, 0, 1000, 1000);

                    const sampleCanvas = document.createElement('canvas');
                    sampleCanvas.width = 100;
                    sampleCanvas.height = 100;
                    const sampleCtx = sampleCanvas.getContext('2d');
                    sampleCtx.drawImage(canvasSource, 0, 0, 100, 100);
                    const sampleData = sampleCtx.getImageData(0, 0, 100, 100).data;
                    let edgePixels = 0;
                    let whiteEdgePixels = 0;
                    for (let x = 0; x < 100; x++) {
                        for (const y of [0, 99]) {
                            const p = (y * 100 + x) * 4;
                            edgePixels++;
                            if (sampleData[p] >= 245 && sampleData[p + 1] >= 245 && sampleData[p + 2] >= 245) whiteEdgePixels++;
                        }
                    }
                    for (let y = 1; y < 99; y++) {
                        for (const x of [0, 99]) {
                            const p = (y * 100 + x) * 4;
                            edgePixels++;
                            if (sampleData[p] >= 245 && sampleData[p + 1] >= 245 && sampleData[p + 2] >= 245) whiteEdgePixels++;
                        }
                    }
                    const hasWhiteBackground = whiteEdgePixels / Math.max(1, edgePixels) >= 0.90;
                    let mayBeStretched = false;
                    let backgroundNote = '';
                    if (hasWhiteBackground) {
                        const scale = Math.min(1000 / srcW, 1000 / srcH);
                        const fitW = srcW * scale;
                        const fitH = srcH * scale;
                        ctx.drawImage(canvasSource, (1000 - fitW) / 2, (1000 - fitH) / 2, fitW, fitH);
                        backgroundNote = 'White background detected; aspect ratio preserved.';
                    } else {
                        ctx.drawImage(canvasSource, 0, 0, 1000, 1000);
                        mayBeStretched = true;
                        backgroundNote = 'WARNING: Non-white background detected; image may be stretched to 1000x1000.';
                    }

                    let quality = 0.92;
                    let blob = null;
                    let sizeKB = 0;
                    let contentScale = 1.0;
                    const sourceCanvas = document.createElement('canvas');
                    sourceCanvas.width = 1000;
                    sourceCanvas.height = 1000;
                    sourceCanvas.getContext('2d').drawImage(canvas, 0, 0);

                    while (true) {
                        const workingCanvas = document.createElement('canvas');
                        workingCanvas.width = 1000;
                        workingCanvas.height = 1000;
                        const wctx = workingCanvas.getContext('2d');
                        wctx.fillStyle = '#FFFFFF';
                        wctx.fillRect(0, 0, 1000, 1000);
                        const contentW = Math.max(1, Math.round(1000 * contentScale));
                        const contentH = Math.max(1, Math.round(1000 * contentScale));
                        wctx.drawImage(sourceCanvas, 0, 0, 1000, 1000, (1000-contentW)/2, (1000-contentH)/2, contentW, contentH);

                        quality = 0.92;
                        while (quality >= 0.10) {
                            blob = await new Promise(res => workingCanvas.toBlob(res, 'image/webp', quality));
                            if (!blob) throw new Error('WebP encoding failed.');
                            sizeKB = blob.size / 1024;
                            if (blob.size <= 49 * 1024) break;
                            quality -= 0.05;
                        }
                        if (blob && blob.size <= 49 * 1024) break;
                        if (contentScale <= 0.35) throw new Error('Could not compress this image below 49 KB.');
                        contentScale = Math.round((contentScale - 0.1) * 100) / 100;
                    }

                    const baseName = requestedBaseName || file.name.substring(0, file.name.lastIndexOf('.')) || file.name;
                    const outputName = `${baseName}.webp`;
                    const previewUrl = URL.createObjectURL(blob);

                    URL.revokeObjectURL(url);

                    resolve({
                        origName: file.name,
                        outputName: outputName,
                        origSize: `${origW}x${origH}`,
                        finalCanvas: '1000x1000',
                        sizeKB: sizeKB.toFixed(2),
                        quality: Math.round(quality * 100),
                        under50: blob.size <= 49 * 1024,
                        upscaled: wasUpscaled,
                        contentScale: Math.round(contentScale * 100),
                        whiteBackgroundDetected: hasWhiteBackground,
                        mayBeStretched: mayBeStretched,
                        backgroundNote: backgroundNote,
                        blob: blob,
                        previewUrl: previewUrl
                    });
                };

                img.src = url;
            });
        }

        function renderTableRow(item) {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-slate-50 transition-colors';
            tr.innerHTML = `
                <td class="p-3"><img src="${item.previewUrl}" class="w-10 h-10 object-cover rounded border border-slate-200 bg-white"></td>
                <td class="p-3 font-medium text-slate-900">${item.origName}</td>
                <td class="p-3 text-emerald-700 font-semibold">${item.outputName}</td>
                <td class="p-3 text-slate-600">${item.origSize}</td>
                <td class="p-3 text-slate-600">${item.finalCanvas}</td>
                <td class="p-3 font-bold ${item.sizeKB <= 49 ? 'text-emerald-600' : 'text-rose-600'}">${item.sizeKB} KB</td>
                <td class="p-3 text-slate-600">${item.quality}%</td>
                <td class="p-3"><span class="px-2 py-0.5 rounded-full text-xs font-bold ${item.under50 ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}">${item.under50 ? 'Yes' : 'No'}</span></td>
                <td class="p-3"><span class="px-2 py-0.5 rounded-full text-xs font-bold ${item.upscaled ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'}">${item.upscaled ? 'Yes' : 'No'}</span></td>
                <td class="p-3 ${item.mayBeStretched ? 'text-rose-700 font-semibold' : 'text-slate-600'}">${item.backgroundNote}</td>
            `;
            tableBody.appendChild(tr);
        }

        function updateDashboard() {
            statTotal.innerText = processedFiles.length;
            statCanvas.innerText = processedFiles.length;
            statWebp.innerText = processedFiles.length;
            statUnder50.innerText = processedFiles.filter(f => f.under50).length;
            statUpscaled.innerText = processedFiles.filter(f => f.upscaled).length;
        }

        document.getElementById('downloadZipBtn').addEventListener('click', async () => {
            const zip = new JSZip();
            processedFiles.forEach(file => {
                zip.file(file.outputName, file.blob);
            });
            const content = await zip.generateAsync({ type: 'blob' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(content);
            link.download = 'Shopee_Optimized_Images.zip';
            link.click();
        });

        document.getElementById('downloadExcelBtn').addEventListener('click', () => {
            const exportData = processedFiles.map(f => ({
                'Original Name': f.origName,
                'Output WebP Name': f.outputName,
                'Original Resolution': f.origSize,
                'Final Canvas': f.finalCanvas,
                'Format': 'WEBP',
                'Final Size (KB)': parseFloat(f.sizeKB),
                'Quality Level (%)': f.quality,
                'Under 50 KB': f.under50 ? 'Yes' : 'No',
                'Upscaled (< 600px)': f.upscaled ? 'Yes' : 'No',
                'White Background Detected': f.whiteBackgroundDetected ? 'Yes' : 'No',
                'May Be Stretched': f.mayBeStretched ? 'Yes' : 'No',
                'Processing Comment': f.backgroundNote
            }));

            const ws = XLSX.utils.json_to_sheet(exportData);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Image_Batch_Log");
            XLSX.writeFile(wb, "Shopee_Image_Processing_Log.xlsx");
        });
    </script>
</body>
</html>
"""

# Render full screen component
components.html(HTML_CONTENT, height=1200, scrolling=True)
