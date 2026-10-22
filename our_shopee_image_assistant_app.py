import streamlit as st
import streamlit.components.v1 as components

# 1. Page Configuration
st.set_page_config(
    page_title="Our Shopee Image Assistant",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
                Automated WebP conversion, aspect-ratio safe 1000x1000 canvas padding, & &lt;600px detail upscaling.
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
                    🔍 &lt; 600px Auto-Upscaler
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
            progressContainer.classList.remove('hidden');

            for (let i = 0; i < fileList.length; i++) {
                const file = fileList[i];
                const pct = Math.round(((i + 1) / fileList.length) * 100);
                progressText.innerText = `Processing ${i + 1} of ${fileList.length}: ${file.name}`;
                progressPercent.innerText = `${pct}%`;
                progressBar.style.width = `${pct}%`;

                const result = await processImage(file);
                processedFiles.push(result);
                renderTableRow(result);
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
                    renderTableRow(result);
                } catch (err) {
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
                    const wasUpscaled = origW < 600 || origH < 600;

                    let srcW = origW;
                    let srcH = origH;
                    let canvasSource = img;

                    if (wasUpscaled) {
                        const scale = Math.max(600 / origW, 600 / origH);
                        srcW = Math.round(origW * scale);
                        srcH = Math.round(origH * scale);

                        const upCanvas = document.createElement('canvas');
                        upCanvas.width = srcW;
                        upCanvas.height = srcH;
                        const uCtx = upCanvas.getContext('2d');
                        uCtx.drawImage(img, 0, 0, srcW, srcH);

                        canvasSource = upCanvas;
                    }

                    const canvas = document.createElement('canvas');
                    canvas.width = 1000;
                    canvas.height = 1000;
                    const ctx = canvas.getContext('2d');

                    ctx.fillStyle = '#FFFFFF';
                    ctx.fillRect(0, 0, 1000, 1000);

                    const scale = Math.min(1000 / srcW, 1000 / srcH);
                    const fitW = srcW * scale;
                    const fitH = srcH * scale;
                    const pasteX = (1000 - fitW) / 2;
                    const pasteY = (1000 - fitH) / 2;

                    ctx.drawImage(canvasSource, pasteX, pasteY, fitW, fitH);

                    let quality = 0.92;
                    let blob = null;
                    let sizeKB = 0;

                    while (quality >= 0.60) {
                        blob = await new Promise(res => canvas.toBlob(res, 'image/webp', quality));
                        sizeKB = blob.size / 1024;
                        if (sizeKB <= 49.0) break;
                        quality -= 0.04;
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
                        under50: sizeKB <= 50.0,
                        upscaled: wasUpscaled,
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
                'Upscaled (< 600px)': f.upscaled ? 'Yes' : 'No'
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
