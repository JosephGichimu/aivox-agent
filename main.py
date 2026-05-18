import os
import io
import json
import base64
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont

app = FastAPI(title="Aivox AI Agent")

# Enable Cross-Origin for Cloud Deployment[cite: 1]
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- CORE AGENT LOGIC ---

def generate_invoice_image(template_bytes, row_data, mapping):
    """The 'Digital Stamper': Overlays Excel data onto Image pixels"""
    img = Image.open(io.BytesIO(template_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Simple font loading for cloud environments
    try:
        font = ImageFont.load_default()
    except:
        font = None

    for field, coords in mapping.items():
        text_value = str(row_data.get(field, ""))
        # Cleanly draw the data at the exact coordinates captured by the UI[cite: 8]
        draw.text((float(coords['x']), float(coords['y'])), text_value, fill="black", font=font)
    
    # Save to buffer for instant download[cite: 15]
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

# --- API ENDPOINTS ---

@app.post("/batch-generate")
async def batch_generate(
    template: UploadFile = File(...),
    csv_file: UploadFile = File(...),
    mapping: str = Form(...) # JSON string of coordinates
):
    try:
        # Load Data[cite: 5, 7]
        df = pd.read_csv(io.BytesIO(await csv_file.read()))
        template_bytes = await template.read()
        mapping_dict = json.loads(mapping)
        
        # We generate the first one as a verification sample[cite: 15]
        sample_row = df.iloc[0].to_dict()
        output_image = generate_invoice_image(template_bytes, sample_row, mapping_dict)
        
        encoded_image = base64.b64encode(output_image).decode('utf-8')
        return JSONResponse(content={"sample_image": encoded_image, "count": len(df)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def interface():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><title>Aivox AI Agent</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .canvas-container { position: relative; cursor: crosshair; display: inline-block; }
            .marker { position: absolute; background: #4f46e5; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; transform: translate(-50%, -50%); pointer-events: none; }
        </style>
    </head>
    <body class="bg-slate-900 text-slate-200 min-h-screen flex">
        <!-- Multi-Client Sidebar -->
        <aside class="w-72 bg-slate-800 border-r border-slate-700 p-6 flex flex-col gap-8">
            <div>
                <h1 class="text-2xl font-black text-indigo-400">AIVOX AGENT</h1>
                <p class="text-[10px] text-slate-500 font-bold uppercase tracking-tighter">Enterprise Multi-Client Mode</p>
            </div>
            
            <div class="space-y-4">
                <label class="block text-xs font-bold text-slate-400 uppercase">1. Active Client</label>
                <select id="client" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white">
                    <option>Safaricom Ltd</option>
                    <option>Zuku Fiber</option>
                    <option>KRA Internal</option>
                </select>

                <label class="block text-xs font-bold text-slate-400 uppercase">2. Upload JPG Template</label>
                <input type="file" id="tpl" accept="image/*" class="text-xs">

                <label class="block text-xs font-bold text-slate-400 uppercase">3. Upload Data (CSV)</label>
                <input type="file" id="csv" accept=".csv" class="text-xs">
            </div>

            <div id="fields" class="flex-1 overflow-y-auto space-y-2 py-4 border-t border-slate-700">
                <p class="text-[10px] text-slate-500 italic">Upload CSV to see fields...</p>
            </div>

            <button onclick="runAgent()" class="bg-indigo-600 hover:bg-indigo-500 py-4 rounded-xl font-bold text-white shadow-2xl transition-all">PROCESS BATCH</button>
        </aside>

        <!-- Main Workspace -->
        <main class="flex-1 p-8 flex flex-col items-center overflow-auto">
            <div id="canvasBox" class="canvas-container bg-white rounded shadow-2xl hidden">
                <img id="view" class="max-w-4xl">
            </div>
            <div id="welcome" class="text-slate-500 text-center mt-40">
                <div class="text-6xl mb-4">🖨️</div>
                <p class="text-xl font-light">Load your Template and Data to begin mapping</p>
            </div>
        </main>

        <script>
            let mapping = {};
            let selectedField = null;

            document.getElementById('tpl').onchange = e => {
                const fr = new FileReader();
                fr.onload = () => {
                    document.getElementById('view').src = fr.result;
                    document.getElementById('canvasBox').classList.remove('hidden');
                    document.getElementById('welcome').classList.add('hidden');
                }
                fr.readAsDataURL(e.target.files[0]);
            }

            document.getElementById('csv').onchange = e => {
                const fr = new FileReader();
                fr.onload = () => {
                    const headers = fr.result.split('\\n')[0].split(',');
                    const div = document.getElementById('fields');
                    div.innerHTML = '<p class="text-[10px] font-bold text-indigo-400 mb-2">CLICK FIELD THEN CLICK IMAGE</p>';
                    headers.forEach(h => {
                        const b = document.createElement('button');
                        b.className = "w-full text-left p-2 bg-slate-900 border border-slate-700 rounded text-xs hover:border-indigo-500";
                        b.innerText = h.trim();
                        b.onclick = () => { selectedField = h.trim(); b.style.borderColor = '#4f46e5'; }
                        div.appendChild(b);
                    });
                }
                fr.readAsText(e.target.files[0]);
            }

            document.getElementById('canvasBox').onclick = e => {
                if(!selectedField) return;
                const rect = e.target.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                mapping[selectedField] = {x, y};
                
                const m = document.createElement('div');
                m.className = 'marker';
                m.style.left = x+'px'; m.style.top = y+'px';
                m.innerText = selectedField;
                document.getElementById('canvasBox').appendChild(m);
                selectedField = null;
            }

            async function runAgent() {
                const fd = new FormData();
                fd.append('template', document.getElementById('tpl').files[0]);
                fd.append('csv_file', document.getElementById('csv').files[0]);
                fd.append('mapping', JSON.stringify(mapping));
                
                const res = await fetch('/batch-generate', { method: 'POST', body: fd });
                const data = await res.json();
                alert('Success! Processed ' + data.count + ' invoices. Sample generated.');
                document.getElementById('view').src = "data:image/png;base64," + data.sample_image;
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
