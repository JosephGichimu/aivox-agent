import os
import io
import json
import base64
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
import zipfile

app = FastAPI(title="Aivox Universal Agent Elite")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
        
        # We create an in-memory zip file to store all generated files
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            # Process every single row inside the data sheet (15 rows)
            for index, row in df.iterrows():
                row_data = row.to_dict()
                filename = f"Invoice_{index + 1}.pdf" if layout_type == "pdf" else f"Document_{index + 1}.png"
                
                if layout_type == "pdf":
                    reader = PdfReader(io.BytesIO(tpl_bytes))
                    writer = PdfWriter()
                    writer.append(reader)
                    
                    field_data = {}
                    for field, target in mapping_dict.items():
                        val = str(row_data.get(field, ""))
                        if val and val != "nan" and target.get('pdfField'):
                            field_data[target.get('pdfField')] = val
                    
                    try:
                        writer.update_page_form_field_values(writer.pages[0], field_data)
                    except:
                        pass
                    
                    out_buf = io.BytesIO()
                    writer.write(out_buf)
                    zip_file.writestr(filename, out_buf.getvalue())
                    
                elif layout_type == "image":
                    img = Image.open(io.BytesIO(tpl_bytes)).convert("RGB")
                    draw = ImageDraw.Draw(img)
                    for field, coords in mapping_dict.items():
                        val = str(row_data.get(field, ""))
                        if val and val != "nan":
                            draw.text((float(coords['x']), float(coords['y'])), val, fill="black")
                    
                    out_buf = io.BytesIO()
                    img.save(out_buf, format='PNG')
                    zip_file.writestr(filename, out_buf.getvalue())
        
        zip_buffer.seek(0)
        # Returns raw binary stream to the front-end to trigger immediate download window
        return StreamingResponse(
            zip_buffer, 
            media_type="application/zip", 
            headers={"Content-Disposition": "attachment; filename=aivox_batch_output.zip"}
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def interface():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><title>Aivox Universal Agent</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .canvas-container { position: relative; cursor: crosshair; display: inline-block; }
            .marker { position: absolute; background: #4f46e5; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; transform: translate(-50%, -50%); pointer-events: none; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 100; justify-content: center; align-items: center; }
        </style>
    </head>
    <body class="bg-slate-900 text-slate-200 min-h-screen flex">
        
        <aside class="w-80 bg-slate-800 border-r border-slate-700 p-6 flex flex-col gap-5">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-black text-indigo-400">AIVOX AGENT</h1>
                    <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Universal Mode</p>
                </div>
                <button onclick="toggleModal(true)" class="px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600 text-indigo-400 hover:text-white rounded-lg font-bold text-xs transition-all">
                    ＋ Client
                </button>
            </div>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Active Client Profile</label>
                    <select id="client" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white outline-none">
                        <option>ELPINE</option>
                        <option>Safaricom Ltd</option>
                    </select>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Template Format Type</label>
                    <select id="layoutType" onchange="switchLayoutMode()" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white outline-none focus:border-indigo-500">
                        <option value="image">Image (PNG, JPG, JPEG)</option>
                        <option value="xlsx">Spreadsheet (XLSX, XLS)</option>
                        <option value="pdf">Document (PDF)</option>
                    </select>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Upload Layout Template File</label>
                    <input type="file" id="tpl" class="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-slate-200 cursor-pointer">
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Upload Data Sheet (CSV / XLSX)</label>
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
                <img id="view" class="max-w-4xl block">
            </div>

            <div id="excelBox" class="w-full max-w-4xl bg-slate-900 border border-slate-800 p-6 rounded-xl hidden">
                <h3 class="text-sm font-bold mb-4 text-slate-400">Excel Structural Grid Mapping</h3>
                <p class="text-xs text-slate-500 mb-4">Input structural cell codes (e.g., C5, F12) matching your raw row fields:</p>
                <div id="excelForm" class="space-y-3"></div>
            </div>

            <div id="pdfBox" class="w-full max-w-4xl bg-slate-900 border border-slate-800 p-6 rounded-xl hidden">
                <h3 class="text-sm font-bold mb-4 text-slate-400">PDF Form Fill Value Schema</h3>
                <p class="text-xs text-slate-500 mb-4">Type the exact string names of the interactive PDF form fields:</p>
                <div id="pdfForm" class="space-y-3"></div>
            </div>

            <div id="welcome" class="text-slate-500 text-center max-w-sm">
                <div class="text-5xl mb-4">⚙️</div>
                <p class="text-lg font-medium text-slate-400">Workspace Standard View</p>
                <p class="text-xs text-slate-500 mt-1">Select your client configuration framework to initialize mapping fields.</p>
            </div>
        </main>

        <div id="clientModal" class="modal">
            <div class="bg-slate-800 border border-slate-700 p-6 rounded-2xl w-96 shadow-2xl">
                <h3 class="text-lg font-bold text-white mb-4">Register New Client Workspace</h3>
                <input type="text" id="newClientName" placeholder="e.g. Airtel Kenya" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-sm text-white mb-4 outline-none">
                <div class="flex justify-end gap-3">
                    <button onclick="toggleModal(false)" class="px-4 py-2 text-xs bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                    <button onclick="addNewClient()" class="px-4 py-2 text-xs bg-indigo-600 hover:bg-indigo-500 rounded-lg text-white">Create</button>
                </div>
            </div>
        </div>

        <script>
            let mapping = {};
            let selectedField = null;

            function toggleModal(show) {
                document.getElementById('clientModal').style.display = show ? 'flex' : 'none';
            }

            function addNewClient() {
                const name = document.getElementById('newClientName').value.trim();
                if(!name) return;
                const select = document.getElementById('client');
                const opt = document.createElement('option');
                opt.value = name; opt.innerText = name;
                select.appendChild(opt); select.value = name;
                document.getElementById('newClientName').value = '';
                toggleModal(false);
            }

            function switchLayoutMode() {
                const type = document.getElementById('layoutType').value;
                document.getElementById('canvasBox').classList.add('hidden');
                document.getElementById('excelBox').classList.add('hidden');
                document.getElementById('pdfBox').classList.add('hidden');
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
                
                const fieldsDiv = document.getElementById('fields');
                fieldsDiv.innerHTML = '<p class="text-xs text-slate-500 italic text-center mt-4">Load data file to map fields...</p>';
                document.getElementById('csv').value = '';
            }

            document.getElementById('tpl').onchange = e => {
                if(!e.target.files[0]) return;
                const type = document.getElementById('layoutType').value;
                if (type === 'image') {
                    const fr = new FileReader();
                    fr.onload = () => {
                        document.getElementById('view').src = fr.result;
                        document.getElementById('canvasBox').classList.remove('hidden');
                        document.getElementById('welcome').classList.add('hidden');
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
                    
                    if(!res.ok) { throw new Error(data.error || "Failed file parsing"); }
                    
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
                            if (type === 'pdf') { addStructuralInputRow(h, 'pdfForm', 'pdfField'); }
                        }
                        div.appendChild(b);
                    });
                } catch(err) {
                    div.innerHTML = `<p class="text-xs text-rose-400 text-center mt-4">Error parsing input metadata.</p>';
                }
            }

            document.getElementById('canvasBox').onclick = e => {
                if(!selectedField) return;
                const rect = document.getElementById('view').getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                mapping[selectedField] = {x, y};
                updateFieldStatus(selectedField);
                
                const m = document.createElement('div');
                m.className = 'marker';
                m.style.left = x + 'px'; m.style.top = y + 'px';
                m.innerText = selectedField;
                document.getElementById('canvasBox').appendChild(m);
                selectedField = null;
            }

            function addStructuralInputRow(field, formId, attributeKey) {
                const form = document.getElementById(formId);
                const safeId = 'inp-' + formId + '-' + field.replace(/[^a-zA-Z0-9]/g, "_");
                if(document.getElementById(safeId)) return;
                
                const d = document.createElement('div');
                d.id = safeId;
                d.className = "flex items-center gap-4 bg-slate-950 p-2 rounded-lg border border-slate-800";
                
                placeholderText = attributeKey === 'cell' ? 'e.g. B4' : 'e.g. invoice_total_field';
                
                d.innerHTML = `<span class="text-xs font-medium w-1/3 text-slate-300">${field}</span>
                               <input type="text" placeholder="${placeholderText}" onchange="registerStructuralValue('${field}', '${attributeKey}', this.value)" class="bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-md outline-none focus:border-indigo-500 w-2/3">`;
                form.appendChild(d);
            }

            function registerStructuralValue(field, key, value) {
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
                btn.innerText = "PROCESSING BATCH PACKETS...";
                btn.disabled = true;

                const fd = new FormData();
                fd.append('template', tplFile);
                fd.append('data_file', dataFile);
                fd.append('mapping', JSON.stringify(mapping));
                fd.append('layout_type', lType);
                
                try {
                    const res = await fetch('/batch-process', { method: 'POST', body: fd });
                    if(!res.ok) throw new Error("Processing failed");
                    
                    // Directly capture the binary file payload from response stream
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    
                    // Auto-trigger browser local download window
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = "aivox_batch_output.zip";
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    
                    alert("Success! Archive packet containing all outputs generated and downloaded successfully.");
                } catch(e) {
                    alert('Batch automation stream error.');
                } finally {
                    btn.innerText = "EXECUTE BATCH PROCESSING";
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
