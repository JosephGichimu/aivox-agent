import os
import io
import json
import base64
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw
import zipfile

# PDF processing additions
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="Aivox Universal Agent Production Fix")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSION_CACHE = {"bytes": None, "name": "aivox_batch_output.zip"}

def helper_read_dataframe(file_bytes, filename: str) -> pd.DataFrame:
    file_buffer = io.BytesIO(file_bytes)
    if filename.lower().endswith(('.xlsx', '.xls')):
        return pd.read_excel(file_buffer, engine="openpyxl")
    return pd.read_csv(file_buffer)

@app.post("/get-headers")
async def get_headers(data_file: UploadFile = File(...)):
    try:
        file_bytes = await data_file.read()
        df = helper_read_dataframe(file_bytes, data_file.filename)
        headers = [str(col).strip() for col in df.columns]
        return JSONResponse(content={"headers": headers})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.post("/batch-process")
async def batch_process(
    template: UploadFile = File(...),
    data_file: UploadFile = File(...),
    mapping: str = Form(...),
    layout_type: str = Form(...)
):
    try:
        df = helper_read_dataframe(await data_file.read(), data_file.filename)
        tpl_bytes = await template.read()
        mapping_dict = json.loads(mapping)
        
        if not mapping_dict:
            raise Exception("Mapping configuration is empty. Map fields before processing.")

        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for index, row in df.iterrows():
                row_data = row.to_dict()
                filename = f"Invoice_{index + 1}.pdf" if layout_type == "pdf" else f"Document_{index + 1}.png"
                
                if layout_type == "pdf":
                    reader = PdfReader(io.BytesIO(tpl_bytes))
                    writer = PdfWriter()
                    
                    packet = io.BytesIO()
                    can = canvas.Canvas(packet, pagesize=letter)
                    
                    for field, target in mapping_dict.items():
                        val = str(row_data.get(field, ""))
                        if val and val != "nan" and 'x' in target and 'y' in target:
                            # PDF coordinates use standard points
                            can.drawString(float(target['x']), float(target['y']), val)
                    can.save()
                    
                    packet.seek(0)
                    new_pdf = PdfReader(packet)
                    
                    page = reader.pages[0]
                    if len(new_pdf.pages) > 0:
                        page.merge_page(new_pdf.pages[0])
                    
                    writer.add_page(page)
                    out_buf = io.BytesIO()
                    writer.write(out_buf)
                    zip_file.writestr(filename, out_buf.getvalue())
                    
                elif layout_type == "image":
                    img = Image.open(io.BytesIO(tpl_bytes)).convert("RGB")
                    draw = ImageDraw.Draw(img)
                    
                    for field, coords in mapping_dict.items():
                        val = str(row_data.get(field, ""))
                        if val and val != "nan" and 'x' in coords and 'y' in coords:
                            # Draws on the real full-scale image dimensions
                            draw.text((float(coords['x']), float(coords['y'])), val, fill="black")
                    
                    out_buf = io.BytesIO()
                    img.save(out_buf, format='PNG')
                    zip_file.writestr(filename, out_buf.getvalue())
        
        zip_data = zip_buffer.getvalue()
        if len(zip_data) == 0:
            raise Exception("Generated archive package is empty.")
            
        SESSION_CACHE["bytes"] = zip_data
        return JSONResponse(content={"status": "success", "count": len(df)})
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download-latest-bundle")
async def download_latest_bundle():
    if not SESSION_CACHE["bytes"]:
        raise HTTPException(status_code=404, detail="No archive found.")
    return StreamingResponse(
        io.BytesIO(SESSION_CACHE["bytes"]), 
        media_type="application/zip", 
        headers={"Content-Disposition": f"attachment; filename={SESSION_CACHE['name']}"}
    )

@app.get("/", response_class=HTMLResponse)
async def interface():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><title>Aivox Universal Workspace</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .canvas-container { position: relative; display: inline-block; cursor: crosshair; }
            .marker { position: absolute; background: #4f46e5; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; transform: translate(-50%, -50%); pointer-events: none; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 100; justify-content: center; align-items: center; }
        </style>
    </head>
    <body class="bg-slate-900 text-slate-200 min-h-screen flex">
        
        <aside class="w-80 bg-slate-800 border-r border-slate-700 p-6 flex flex-col gap-5">
            <div>
                <h1 class="text-2xl font-black text-indigo-400">AIVOX AGENT</h1>
                <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Universal Mode</p>
            </div>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Active Client Profile</label>
                    <select id="client" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white outline-none">
                        <option>ELPINE</option>
                    </select>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Template Format Type</label>
                    <select id="layoutType" onchange="switchLayoutMode()" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white outline-none">
                        <option value="image">Image (PNG, JPG, JPEG)</option>
                        <option value="xlsx">Spreadsheet (XLSX, XLS)</option>
                        <option value="pdf">Document (PDF)</option>
                    </select>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Upload Layout Template</label>
                    <input type="file" id="tpl" class="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-slate-200 cursor-pointer">
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Upload Data Sheet</label>
                    <input type="file" id="csv" accept=".csv, .xlsx, .xls" class="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-slate-200 cursor-pointer">
                </div>
            </div>

            <div class="flex-1 flex flex-col min-h-0">
                <label class="block text-xs font-bold text-slate-400 uppercase mb-2">Source Fields</label>
                <div id="fields" class="flex-1 overflow-y-auto space-y-2 pr-1 bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
                    <p class="text-xs text-slate-500 italic text-center mt-4">Load data file to map fields...</p>
                </div>
            </div>

            <button id="execBtn" onclick="runUniversalAgent()" class="bg-indigo-600 hover:bg-indigo-500 py-4 rounded-xl font-bold text-white shadow-lg transition-all">EXECUTE BATCH PROCESSING</button>
        </aside>

        <main class="flex-1 p-8 flex flex-col items-center justify-center overflow-auto bg-slate-950">
            <div id="canvasBox" class="canvas-container bg-white rounded shadow-2xl hidden">
                <img id="view" class="max-w-4xl block select-none">
            </div>

            <div id="excelBox" class="w-full max-w-4xl bg-slate-900 border border-slate-800 p-6 rounded-xl hidden">
                <h3 class="text-sm font-bold mb-4 text-slate-400">Excel Structural Grid Mapping</h3>
                <div id="excelForm" class="space-y-3"></div>
            </div>

            <div id="pdfBox" class="w-full max-w-4xl bg-slate-900 border border-slate-800 p-6 rounded-xl hidden">
                <h3 class="text-sm font-bold mb-4 text-slate-400">PDF Coordinate Overlay Configuration</h3>
                <div id="pdfForm" class="space-y-3"></div>
            </div>

            <div id="errorPanel" class="w-full max-w-xl bg-slate-900 border-2 border-rose-500/40 p-6 rounded-xl hidden">
                <p class="text-rose-400 font-bold mb-2">⚠️ Engine Execution Aborted</p>
                <pre id="errorText" class="bg-black/50 text-rose-300 p-4 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap></pre>
            </div>

            <div id="successPanel" class="w-full max-w-md bg-slate-900 border-2 border-emerald-500/30 p-8 rounded-2xl hidden text-center space-y-4">
                <div class="text-5xl">📦</div>
                <h2 class="text-xl font-bold text-emerald-400">Batch Processing Complete!</h2>
                <p id="successMeta" class="text-xs text-slate-400"></p>
                <a href="/download-latest-bundle" target="_blank" class="block w-full text-center bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3.5 px-4 rounded-xl shadow-lg transition-all">
                    📥 Download Output ZIP Bundle
                </a>
            </div>

            <div id="welcome" class="text-slate-500 text-center max-w-sm">
                <div class="text-5xl mb-4">⚙️</div>
                <p class="text-lg font-medium text-slate-400">Workspace Standard View</p>
            </div>
        </main>

        <script>
            let mapping = {};
            let selectedField = null;
            let nativeWidth = 0;
            let nativeHeight = 0;

            function switchLayoutMode() {
                const type = document.getElementById('layoutType').value;
                document.getElementById('canvasBox').classList.add('hidden');
                document.getElementById('excelBox').classList.add('hidden');
                document.getElementById('pdfBox').classList.add('hidden');
                document.getElementById('successPanel').classList.add('hidden');
                document.getElementById('errorPanel').classList.add('hidden');
                document.getElementById('welcome').classList.remove('hidden');
                mapping = {};
                document.querySelectorAll('.marker').forEach(m => m.remove());
                
                if(type === 'xlsx') {
                    document.getElementById('excelBox').classList.remove('hidden');
                    document.getElementById('welcome').classList.add('hidden');
                } else if(type === 'pdf') {
                    document.getElementById('pdfBox').classList.remove('hidden');
                    document.getElementById('welcome').classList.add('hidden');
                }
            }

            document.getElementById('tpl').onchange = e => {
                if(!e.target.files[0]) return;
                const type = document.getElementById('layoutType').value;
                if (type === 'image') {
                    const fr = new FileReader();
                    fr.onload = () => {
                        const img = new Image();
                        img.onload = function() {
                            nativeWidth = this.width;
                            nativeHeight = this.height;
                            
                            const viewImg = document.getElementById('view');
                            viewImg.src = fr.result;
                            document.getElementById('canvasBox').classList.remove('hidden');
                            document.getElementById('welcome').classList.add('hidden');
                        };
                        img.src = fr.result;
                    }
                    fr.readAsDataURL(e.target.files[0]);
                }
            }

            document.getElementById('csv').onchange = async e => {
                const file = e.target.files[0];
                if(!file) return;
                const div = document.getElementById('fields');
                div.innerHTML = '<p class="text-xs text-indigo-400 animate-pulse text-center mt-4">Parsing headers...</p>';
                
                const fd = new FormData();
                fd.append('data_file', file);
                
                try {
                    const res = await fetch('/get-headers', { method: 'POST', body: fd });
                    const data = await res.json();
                    
                    div.innerHTML = '';
                    document.getElementById('excelForm').innerHTML = '';
                    document.getElementById('pdfForm').innerHTML = '';
                    
                    data.headers.forEach(h => {
                        const b = document.createElement('button');
                        b.id = "btn-" + h.replace(/[^a-zA-Z0-9]/g, "_");
                        b.className = "w-full text-left px-3 py-2 bg-slate-900 border border-slate-700/60 rounded-lg text-xs text-slate-300 hover:border-indigo-500 flex justify-between items-center";
                        b.innerHTML = `<span>${h}</span><span class="status-dot text-[9px] text-slate-500">● Unmapped</span>`;
                        
                        b.onclick = () => { 
                            selectedField = h; 
                            document.querySelectorAll('#fields button').forEach(el => el.classList.remove('ring-1', 'ring-indigo-500'));
                            b.classList.add('ring-1', 'ring-indigo-500');
                            
                            const type = document.getElementById('layoutType').value;
                            if (type === 'xlsx') { addStructuralInputRow(h, 'excelForm', 'cell'); }
                            if (type === 'pdf') { addPdfCoordinateInputRow(h); }
                        }
                        div.appendChild(b);
                    });
                } catch(err) {
                    div.innerHTML = `<p class="text-xs text-rose-400 text-center mt-4">Error parsing input metadata.</p>`;
                }
            }

            // PIXEL-PERFECT SCALING CLICK LOGIC
            document.getElementById('canvasBox').onclick = e => {
                if(!selectedField) return alert("Select a source field from the left panel first.");
                
                const imgElement = document.getElementById('view');
                const rect = imgElement.getBoundingClientRect();
                
                // Get exactly where the click landed inside the display box
                const displayX = e.clientX - rect.left;
                const displayY = e.clientY - rect.top;
                
                // Scale coordinates relative to the full-size source image dimensions
                const scaleX = nativeWidth / rect.width;
                const scaleY = nativeHeight / rect.height;
                
                const actualX = displayX * scaleX;
                const actualY = displayY * scaleY;
                
                mapping[selectedField] = { x: actualX, y: actualY };
                updateFieldStatus(selectedField);
                
                // Render visual marker pinned safely on the layout screen
                const m = document.createElement('div');
                m.className = 'marker';
                m.style.left = displayX + 'px';
                m.style.top = displayY + 'px';
                m.innerText = selectedField;
                document.getElementById('canvasBox').appendChild(m);
                
                selectedField = null;
            }

            function addPdfCoordinateInputRow(field) {
                const form = document.getElementById('pdfForm');
                const safeId = 'inp-pdf-' + field.replace(/[^a-zA-Z0-9]/g, "_");
                if(document.getElementById(safeId)) return;
                
                const d = document.createElement('div');
                d.id = safeId;
                d.className = "flex gap-4 items-center bg-slate-950 p-3 rounded-lg border border-slate-800";
                d.innerHTML = `
                    <span class="text-xs font-medium w-1/4 text-slate-300">${field}</span>
                    <input type="number" placeholder="X" onchange="registerCoord('${field}', 'x', this.value)" class="w-1/3 bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-md outline-none">
                    <input type="number" placeholder="Y" onchange="registerCoord('${field}', 'y', this.value)" class="w-1/3 bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-md outline-none">
                `;
                form.appendChild(d);
            }

            function addStructuralInputRow(field, formId, attributeKey) {
                const form = document.getElementById(formId);
                const safeId = 'inp-' + formId + '-' + field.replace(/[^a-zA-Z0-9]/g, "_");
                if(document.getElementById(safeId)) return;
                
                const d = document.createElement('div');
                d.id = safeId;
                d.className = "flex items-center gap-4 bg-slate-950 p-2 rounded-lg border border-slate-800";
                d.innerHTML = `<span class="text-xs font-medium w-1/3 text-slate-300">${field}</span>
                               <input type="text" placeholder="B4" onchange="registerCoord('${field}', '${attributeKey}', this.value)" class="bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-md outline-none w-2/3">`;
                form.appendChild(d);
            }

            function registerCoord(field, key, value) {
                if(!mapping[field]) mapping[field] = {};
                mapping[field][key] = value;
                updateFieldStatus(field);
            }

            function updateFieldStatus(field) {
                const safeId = "btn-" + field.replace(/[^a-zA-Z0-9]/g, "_");
                const targetBtn = document.getElementById(safeId);
                if(targetBtn) {
                    targetBtn.querySelector('.status-dot').className = "status-dot text-[9px] text-emerald-400 font-bold";
                    targetBtn.querySelector('.status-dot').innerText = "✓ Mapped";
                    targetBtn.classList.remove('ring-1', 'ring-indigo-500');
                }
            }

            async function runUniversalAgent() {
                const tplFile = document.getElementById('tpl').files[0];
                const dataFile = document.getElementById('csv').files[0];
                const lType = document.getElementById('layoutType').value;
                if(!tplFile || !dataFile) return alert("Upload template and data targets.");

                const btn = document.getElementById('execBtn');
                btn.innerText = "PROCESSING..."; btn.disabled = true;
                
                document.getElementById('successPanel').classList.add('hidden');
                document.getElementById('errorPanel').classList.add('hidden');

                const fd = new FormData();
                fd.append('template', tplFile);
                fd.append('data_file', dataFile);
                fd.append('mapping', JSON.stringify(mapping));
                fd.append('layout_type', lType);
                
                try {
                    const res = await fetch('/batch-process', { method: 'POST', body: fd });
                    const resData = await res.json();
                    
                    if (!res.ok || resData.error) throw new Error(resData.error || "Execution Interrupted");
                    
                    document.getElementById('canvasBox').classList.add('hidden');
                    document.getElementById('excelBox').classList.add('hidden');
                    document.getElementById('pdfBox').classList.add('hidden');
                    document.getElementById('welcome').classList.add('hidden');
                    
                    document.getElementById('successMeta').innerText = `Processed ${resData.count} data rows successfully.`;
                    document.getElementById('successPanel').classList.remove('hidden');
                } catch(e) {
                    document.getElementById('errorText').innerText = e.message;
                    document.getElementById('errorPanel').classList.remove('hidden');
                } finally {
                    btn.innerText = "EXECUTE BATCH PROCESSING";
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
