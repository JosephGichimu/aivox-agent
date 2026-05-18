import os
import io
import json
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import zipfile

# Core PDF Processing Engines
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="Aivox Enterprise Document Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSION_CACHE = {"bytes": None, "name": "aivox_invoice_bundle.zip"}

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
    mapping: str = Form(...)
):
    try:
        df = helper_read_dataframe(await data_file.read(), data_file.filename)
        tpl_bytes = await template.read()
        mapping_dict = json.loads(mapping)
        
        if not mapping_dict:
            raise Exception("Mapping rules are empty. Please configure field coordinates.")

        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for index, row in df.iterrows():
                row_data = row.to_dict()
                
                # Determine custom file naming tracking from row indexes safely
                filename = f"Invoice_Record_{index + 1}.pdf"
                
                reader = PdfReader(io.BytesIO(tpl_bytes))
                writer = PdfWriter()
                
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                can.setFont("Helvetica", 10)
                
                # Dynamic coordinate translation logic onto PDF vector layers
                for field, target in mapping_dict.items():
                    val = str(row_data.get(field, ""))
                    if val and val != "nan" and 'x' in target and 'y' in target:
                        x_pos = float(target['x'])
                        y_pos = float(target['y'])
                        can.drawString(x_pos, y_pos, val)
                can.save()
                
                packet.seek(0)
                overlay_pdf = PdfReader(packet)
                
                # Flatten the compiled values over page 1 of the template
                page = reader.pages[0]
                if len(overlay_pdf.pages) > 0:
                    page.merge_page(overlay_pdf.pages[0])
                
                writer.add_page(page)
                out_buf = io.BytesIO()
                writer.write(out_buf)
                zip_file.writestr(filename, out_buf.getvalue())
        
        zip_data = zip_buffer.getvalue()
        if len(zip_data) == 0:
            raise Exception("Generated empty output archive package.")
            
        SESSION_CACHE["bytes"] = zip_data
        return JSONResponse(content={"status": "success", "count": len(df)})
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download-latest-bundle")
async def download_latest_bundle():
    if not SESSION_CACHE["bytes"]:
        raise HTTPException(status_code=404, detail="No processed archives found.")
    return StreamingResponse(
        io.BytesIO(SESSION_CACHE["bytes"]), 
        media_type="application/zip", 
        headers={"Content-Disposition": "attachment; filename=aivox_invoice_bundle.zip"}
    )

@app.get("/", response_class=HTMLResponse)
async def interface():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><title>Aivox Premium Production Workspace</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-200 min-h-screen flex">
        
        <aside class="w-80 bg-slate-800 border-r border-slate-700 p-6 flex flex-col gap-5 shadow-xl">
            <div>
                <h1 class="text-2xl font-black text-indigo-400">AIVOX AGENT</h1>
                <p class="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Document Overlay Framework</p>
            </div>
            
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">1. Base Document Template (.pdf)</label>
                    <input type="file" id="tpl" accept=".pdf" class="w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-slate-200 cursor-pointer">
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase mb-1">2. Core Invoice Spreadsheet (.xlsx)</label>
                    <input type="file" id="csv" accept=".csv, .xlsx, .xls" class="w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-slate-200 cursor-pointer">
                </div>
            </div>

            <div class="flex-1 flex flex-col min-h-0">
                <label class="block text-xs font-bold text-slate-400 uppercase mb-2">Source Fields Found</label>
                <div id="fields" class="flex-1 overflow-y-auto space-y-2 pr-1 bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
                    <p class="text-xs text-slate-500 italic text-center mt-4">Upload spreadsheet data to map headings...</p>
                </div>
            </div>

            <button id="execBtn" onclick="runUniversalAgent()" class="bg-indigo-600 hover:bg-indigo-500 py-4 rounded-xl font-bold text-white shadow-lg transition-all tracking-wide text-sm">EXECUTE BATCH PROCESSING</button>
        </aside>

        <main class="flex-1 p-8 flex flex-col items-center justify-center overflow-auto bg-slate-950">
            <div id="pdfBox" class="w-full max-w-3xl bg-slate-900 border border-slate-800 p-6 rounded-2xl hidden shadow-2xl">
                <h3 class="text-sm font-bold mb-1 text-slate-300">PDF Absolute Point Configuration Grid</h3>
                <p class="text-xs text-slate-500 mb-6">Enter typography structural layout grid dimensions (0,0 is the page bottom-left corner):</p>
                <div id="pdfForm" class="space-y-4"></div>
            </div>

            <div id="errorPanel" class="w-full max-w-xl bg-slate-900 border-2 border-rose-500/40 p-6 rounded-xl hidden">
                <p class="text-rose-400 font-bold mb-2">⚠️ Execution Refused</p>
                <pre id="errorText" class="bg-black/50 text-rose-300 p-4 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap"></pre>
            </div>

            <div id="successPanel" class="w-full max-w-md bg-slate-900 border-2 border-emerald-500/30 p-8 rounded-2xl hidden text-center space-y-4 shadow-2xl">
                <div class="text-5xl">🎉</div>
                <h2 class="text-xl font-bold text-emerald-400">Batch Rendering Success!</h2>
                <p id="successMeta" class="text-xs text-slate-400"></p>
                <a href="/download-latest-bundle" class="block w-full text-center bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3.5 px-4 rounded-xl shadow-lg transition-all">
                    📥 Download Zip File Packages
                </a>
            </div>

            <div id="welcome" class="text-slate-500 text-center max-w-sm">
                <div class="text-5xl mb-4">⚙️</div>
                <p class="text-lg font-medium text-slate-400">Production Dashboard Standby</p>
                <p class="text-xs text-slate-500 mt-1">Upload your workspace documents in the left sidebar to commence transformation.</p>
            </div>
        </main>

        <script>
            let mapping = {};

            document.getElementById('csv').onchange = async e => {
                const file = e.target.files[0];
                if(!file) return;
                const div = document.getElementById('fields');
                div.innerHTML = '<p class="text-xs text-indigo-400 animate-pulse text-center mt-4">Parsing headings...</p>';
                
                const fd = new FormData();
                fd.append('data_file', file);
                
                try {
                    const res = await fetch('/get-headers', { method: 'POST', body: fd });
                    const data = await res.json();
                    
                    div.innerHTML = '';
                    document.getElementById('pdfForm').innerHTML = '';
                    document.getElementById('pdfBox').classList.remove('hidden');
                    document.getElementById('welcome').classList.add('hidden');
                    
                    data.headers.forEach(h => {
                        const rowId = h.replace(/[^a-zA-Z0-9]/g, "_");
                        
                        // Sidebar element indicator
                        const b = document.createElement('div');
                        b.className = "w-full text-left px-3 py-2 bg-slate-900/60 border border-slate-700/40 rounded-lg text-xs text-slate-400 flex justify-between items-center";
                        b.innerHTML = `<span>${h}</span><span id="dot-${rowId}" class="text-[9px] text-slate-600">● Unset</span>`;
                        div.appendChild(b);

                        // Grid position input rows
                        const d = document.createElement('div');
                        d.className = "flex gap-4 items-center bg-slate-950 p-3 rounded-xl border border-slate-800/80";
                        d.innerHTML = `
                            <span class="text-xs font-semibold w-1/3 text-indigo-300 truncate">${h}</span>
                            <input type="number" placeholder="X axis point" onchange="updateTrack('${h}', 'x', this.value)" class="w-1/3 bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-lg outline-none focus:border-indigo-500">
                            <input type="number" placeholder="Y axis point" onchange="updateTrack('${h}', 'y', this.value)" class="w-1/3 bg-slate-900 border border-slate-700 text-xs text-white p-2 rounded-lg outline-none focus:border-indigo-500">
                        `;
                        document.getElementById('pdfForm').appendChild(d);
                    });
                } catch(err) {
                    div.innerHTML = `<p class="text-xs text-rose-400 text-center mt-4">Failed parsing source data sheet columns.</p>`;
                }
            }

            function updateTrack(field, axis, val) {
                if(!mapping[field]) mapping[field] = {};
                mapping[field][axis] = val;
                
                if(mapping[field].x && mapping[field].y) {
                    const rowId = field.replace(/[^a-zA-Z0-9]/g, "_");
                    const dot = document.getElementById(`dot-${rowId}`);
                    if(dot) {
                        dot.className = "text-[9px] text-emerald-400 font-bold";
                        dot.innerText = "✓ Ready";
                    }
                }
            }

            async function runUniversalAgent() {
                const tplFile = document.getElementById('tpl').files[0];
                const dataFile = document.getElementById('csv').files[0];
                if(!tplFile || !dataFile) return alert("Please check your layout data inputs. Both PDF template and XLSX spreadsheet are mandatory.");

                const btn = document.getElementById('execBtn');
                btn.innerText = "COMPILING BUNDLE PACKAGE..."; btn.disabled = true;
                
                document.getElementById('successPanel').classList.add('hidden');
                document.getElementById('errorPanel').classList.add('hidden');

                const fd = new FormData();
                fd.append('template', tplFile);
                fd.append('data_file', dataFile);
                fd.append('mapping', JSON.stringify(mapping));
                
                try {
                    const res = await fetch('/batch-process', { method: 'POST', body: fd });
                    const resData = await res.json();
                    
                    if (!res.ok || resData.error) throw new Error(resData.error || "Batch execution faulted.");
                    
                    document.getElementById('pdfBox').classList.add('hidden');
                    document.getElementById('successMeta').innerText = `Successfully processed and generated ${resData.count} targeted corporate invoice bundles.`;
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
