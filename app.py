from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io
import firebase_admin
from firebase_admin import credentials, db

app = Flask(__name__)
app.secret_key = "YUVI-HOSTING-PRO"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}

# --- ADMIN CREDENTIALS UPDATED ---
ADMIN_USER = "JUBARAJ"
ADMIN_PASS = "098765"

# --- FIREBASE INITIALIZATION (NO FILE REQUIRED) ---
fb_creds_json = os.environ.get("FIREBASE_CREDS")

if fb_creds_json:
    # Render ke environment variable se direct connect hoga
    try:
        cred_dict = json.loads(fb_creds_json)
        cred = credentials.Certificate(cred_dict)
    except Exception as e:
        print(f"Firebase JSON Parse Error: {e}")
        cred = None
else:
    # Agar Render par variable nahi mila, toh local file dhoondhega
    if os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
    else:
        cred = None

if cred:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://yuvi-hosting-net-default-rtdb.firebaseio.com/'
    })
else:
    print("WARNING: Firebase credentials NOT found!")

# --- DATABASE HELPER FUNCTIONS ---
def get_db_ref():
    return db.reference('/')

def load_db():
    ref = get_db_ref()
    data = ref.get()
    
    if data is None:
        default_data = {"user_pw": "codex123", "users": {}, "start_times": {}}
        ref.set(default_data)
        return default_data
        
    if "users" not in data or data["users"] is None: 
        data["users"] = {}
    if "user_pw" not in data or data["user_pw"] is None: 
        data["user_pw"] = "codex123"
    if "start_times" not in data or data["start_times"] is None: 
        data["start_times"] = {}
    return data

# --- 1. LOGIN PAGE HTML ---
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | YUVI CODEX</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #030508; --primary: #00ffff; --sec: #7000ff; --glass: rgba(255, 255, 255, 0.03); }
        body { background: var(--bg); color: white; font-family: 'Orbitron', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; }
        #particles-js { position: fixed; width: 100%; height: 100%; z-index: 1; }
        .login-card { position: relative; z-index: 10; background: var(--glass); padding: 40px 30px; border-radius: 25px; width: 340px; text-align: center; border: 1px solid rgba(0, 255, 255, 0.15); backdrop-filter: blur(20px); box-shadow: 0 25px 45px rgba(0,0,0,0.5), inset 0 0 15px rgba(0, 255, 255, 0.05); transition: 0.4s; }
        .login-card:hover { border-color: var(--primary); box-shadow: 0 0 30px rgba(0, 255, 255, 0.15); }
        .lock-container { width: 80px; height: 80px; background: rgba(0, 255, 255, 0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; border: 2px solid var(--primary); box-shadow: 0 0 20px var(--primary); animation: pulse 2s infinite; }
        @keyframes pulse { 0% { transform: scale(1); box-shadow: 0 0 10px var(--primary); } 50% { transform: scale(1.05); box-shadow: 0 0 25px var(--primary); } 100% { transform: scale(1); box-shadow: 0 0 10px var(--primary); } }
        .lock-icon { font-size: 35px; color: var(--primary); }
        h2 { font-size: 20px; margin-bottom: 25px; letter-spacing: 4px; text-transform: uppercase; background: linear-gradient(to right, #fff, var(--primary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        input, select { width: 100%; padding: 14px; margin: 10px 0; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #fff; outline: none; font-size: 14px; transition: 0.3s; }
        input:focus { background: rgba(255,255,255,0.1); border-color: var(--primary); box-shadow: 0 0 10px rgba(0, 255, 255, 0.2); }
        button { width: 100%; padding: 15px; border-radius: 12px; border: none; background: linear-gradient(45deg, var(--sec), var(--primary)); color: #fff; font-weight: bold; font-size: 15px; cursor: pointer; margin-top: 15px; text-transform: uppercase; letter-spacing: 2px; transition: 0.4s; }
        button:hover { letter-spacing: 4px; box-shadow: 0 0 20px var(--primary); opacity: 0.9; }
        .get-pw { margin-top: 25px; font-size: 12px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 15px; }
        .get-pw a { color: var(--primary); text-decoration: none; font-weight: bold; display: inline-flex; align-items: center; gap: 8px; transition: 0.3s; }
    </style>
</head>
<body>
    <div id="particles-js"></div>
    <div class="login-card">
        <div class="lock-container"><i class="fa-solid fa-user-shield lock-icon"></i></div>
        <h2>System Login</h2>
        <form method="post" action="/login">
            <select name="login_type">
                <option value="user">USER ACCESS</option>
                <option value="admin">ADMIN ROOT</option>
            </select>
            <input type="text" name="username" placeholder="Enter Username/Nickname" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Access System</button>
        </form>
        <div class="get-pw"><a href="https://t.me/YuviApis" target="_blank"><i class="fa-brands fa-telegram"></i> FORGOT PASSWORD?</a></div>
    </div>
    <script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
    <script>
        particlesJS('particles-js', { "particles": { "number": { "value": 100, "density": { "enable": true, "value_area": 800 } }, "color": { "value": "#00ffff" }, "shape": { "type": "circle" }, "opacity": { "value": 0.5, "random": true }, "size": { "value": 3, "random": true }, "line_linked": { "enable": true, "distance": 150, "color": "#00ffff", "opacity": 0.2, "width": 1 }, "move": { "enable": true, "speed": 2, "direction": "none", "random": false, "straight": false, "out_mode": "out", "bounce": false } } });
    </script>
</body>
</html>
'''

# --- 2. MAIN INDEX PAGE HTML ---
INDEX_HTML = '''
<!DOCTYPE html>
<html lang="bn">
<head>
    <title>YUVI CODEX - Ultra Hosting Panel</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        :root {
            --bg-color: #000000;
            --primary: #00ffff;
            --accent: #00ffff;
            --box-bg: rgba(22, 27, 34, 0.7);
            --text-glow: rgba(0, 255, 204, 0.4);
            --font-head: 'Orbitron', sans-serif;
            --font-body: 'Rajdhani', sans-serif;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { background-color: var(--bg-color); color: #e6edf3; font-family: var(--font-body); min-height: 100vh; padding-bottom: 120px; overflow-x: hidden; }
        #particles-js { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: -1; }
        .menu-toggle { position: fixed; top: 70px; right: 15px; width: 45px; height: 45px; background: rgba(0, 255, 255, 0.1); border: 1px solid #00ffff; border-radius: 50%; display: flex; justify-content: center; align-items: center; color: #00ffff; font-size: 18px; cursor: pointer; z-index: 1000; backdrop-filter: blur(10px); box-shadow: 0 0 15px rgba(0, 255, 255, 0.3); transition: 0.4s ease; }
        .cyber-panel { position: fixed; top: 125px; right: -300px; width: 260px; background: rgba(10, 15, 20, 0.95); padding: 25px; border-radius: 20px; backdrop-filter: blur(20px); border: 1px solid rgba(0, 255, 255, 0.2); z-index: 999; transition: 0.5s cubic-bezier(0.68, -0.55, 0.27, 1.55); display: flex; flex-direction: column; gap: 20px; }
        .cyber-panel.active { right: 15px; }
        .color-dots-container { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 10px; }
        .color-dot { width: 30px; height: 30px; border-radius: 50%; cursor: pointer; border: 2px solid rgba(255,255,255,0.1); transition: 0.3s; }
        .color-dot.active { border-color: #fff; box-shadow: 0 0 15px currentColor; transform: scale(1.1); }
        .setting-label { font-size: 10px; color: #00ffff; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; display: block; }
        input[type="range"] { width: 100%; cursor: pointer; accent-color: #00ffff; }
        .user-bar { background: rgba(0, 0, 0, 0.8); padding: 10px 15px; display: flex; justify-content: space-between; align-items: center; backdrop-filter: blur(15px); position: sticky; top: 0; z-index: 1000; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .container { width: 94%; max-width: 600px; margin: 0 auto; position: relative; z-index: 1; }
        .upload-card { background: var(--box-bg); padding: 25px; border-radius: 20px; border: 2px dashed rgba(0, 255, 255, 0.3); backdrop-filter: blur(12px); margin-bottom: 20px; transition: 0.3s; }
        #file-details { margin-top: 15px; padding: 12px; background: rgba(0, 255, 255, 0.05); border: 1px solid rgba(0, 255, 255, 0.2); border-radius: 12px; display: none; animation: fadeIn 0.4s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        .upload-btn { background: var(--accent); color: #000; font-weight: 800; font-family: var(--font-head); border:none; border-radius:10px; padding: 14px; width: 100%; margin-top: 15px; cursor: pointer; text-transform: uppercase; box-shadow: 0 0 15px var(--text-glow); }
        .box { background: var(--box-bg); padding: 18px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 20px; }
        .status-badge { padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: bold; font-family: var(--font-head); display: inline-block; text-transform: uppercase; }
        .status-running { background: rgba(0, 255, 65, 0.15); color: #00ff41; border: 1px solid #00ff41; }
        .status-offline { background: rgba(255, 71, 87, 0.15); color: #ff4757; border: 1px solid #ff4757; }
        .runtime-container { margin: 10px 0 15px 0; padding: 10px; background: rgba(0, 255, 255, 0.05); border-radius: 12px; border: 1px solid rgba(0, 255, 255, 0.1); display: flex; align-items: center; justify-content: space-between; }
        .runtime-clock { font-family: var(--font-head); font-size: 12px; color: var(--accent); text-shadow: 0 0 5px var(--accent); }
        .button-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
        .btn-m { padding: 12px; border-radius: 10px; text-decoration: none; text-align: center; font-size: 13px; font-weight: 600; display: flex; align-items: center; justify-content: center; gap: 5px; border: none; font-family: var(--font-body); cursor: pointer; }
        .run { background: #00d2ff; color: #000; }
        .stop { background: #ff4757; color: #fff; }
        .restart { background: #f39c12; color: #000; }
        .delete { background: #30363d; color: #ff4d4d; border: 1px solid #ff4d4d; }
        .download { background: rgba(0, 255, 255, 0.1); color: var(--accent); border: 1px solid var(--accent); }
        .edit { background: #58a6ff; color: #000; }
        pre { background: #0d1117; color: #00ff41; padding: 12px; height: 130px; overflow-y: auto; border-radius: 12px; border: 1px solid #30363d; font-size: 11px; margin-top: 15px; }
        #fmModal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); z-index:2000; padding:10px; box-sizing: border-box; }
        .fm-container { background: #161b22; height: 100%; border-radius: 15px; display: flex; flex-direction: column; padding: 15px; border: 1px solid var(--accent); }
        #fileList { flex: 1; overflow-y: auto; background: #000; border-radius: 8px; padding: 10px; margin-bottom: 10px; border: 1px solid #222; }
        #editor { flex: 2; border-radius: 8px; font-size: 14px; }
        .file-item { padding: 10px; border-bottom: 1px solid #222; display: flex; justify-content: space-between; align-items: center; }
        .save-btn { background: #238636; color: white; padding: 10px; border-radius: 8px; border: none; margin-top: 10px; font-weight: bold; cursor: pointer; }
        .branding { text-align: center; padding: 20px 0; }
        .jubayer-text { font-size: 1.6rem; font-weight: 900; font-family: var(--font-head); letter-spacing: 6px; background: linear-gradient(to bottom, #fff, var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .social-bar { background: transparent; padding: 15px; position: fixed; bottom: 20px; width: 100%; display: flex; justify-content: center; gap: 25px; border: none; z-index: 1001; }
        .social-icon { color: white; font-size: 26px; transition: 0.3s; text-shadow: 0 0 10px rgba(0, 255, 255, 0.5); }
    </style>
</head>
<body>
<div id="particles-js"></div>
<div class="menu-toggle" onclick="toggleMenu()"><i class="fa-solid fa-sliders" id="menuIcon"></i></div>
<div class="cyber-panel" id="sidePanel">
    <div style="color: #fff; font-size: 12px; text-align: center; border-bottom: 1px solid #333; padding-bottom: 10px; letter-spacing: 2px;">GHOST CONFIG</div>
    <div>
        <span class="setting-label"><i class="fa-solid fa-palette"></i> Select System Hue</span>
        <div class="color-dots-container">
            <div class="color-dot active" style="background: #00ffff; color: #00ffff;" onclick="changeHue('#00ffff', this)"></div>
            <div class="color-dot" style="background: #ff004c; color: #ff004c;" onclick="changeHue('#ff004c', this)"></div>
            <div class="color-dot" style="background: #00ff00; color: #00ff00;" onclick="changeHue('#00ff00', this)"></div>
            <div class="color-dot" style="background: #ff00ff; color: #ff00ff;" onclick="changeHue('#ff00ff', this)"></div>
            <div class="color-dot" style="background: #ffff00; color: #ffff00;" onclick="changeHue('#ffff00', this)"></div>
        </div>
    </div>
    <div>
        <span class="setting-label"><i class="fa-solid fa-expand"></i> Node Size</span>
        <input type="range" id="pSize" min="10" max="80" value="38" oninput="updateSize(this.value)">
    </div>
    <div>
        <span class="setting-label"><i class="fa-solid fa-gauge-high"></i> Velocity</span>
        <input type="range" id="pSpeed" min="1" max="15" value="4" oninput="updateSpeed(this.value)">
    </div>
</div>
<div class="user-bar">
    <div style="font-family: var(--font-head); color: var(--accent); font-size: 13px;">Y U V I C O D E X</div>
    <div style="font-size: 13px; color: #fff;">Hello, <span style="color: var(--accent);">{{ username }}</span></div>
    <a href="/logout" style="color:#ff4d4d; font-size:18px;"><i class="fa-solid fa-power-off"></i></a>
</div>
<div class="container">
    <div class="upload-card">
        <form id="uploadForm" method="POST" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" id="fileInput" accept=".zip" required style="display:none;">
            <label for="fileInput" style="cursor:pointer; display:block; text-align: center;">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 40px; color: var(--accent);"></i>
                <div style="margin-top:10px; font-weight: 600; letter-spacing: 1px;">UPLOAD ZIP PROJECT</div>
            </label>
            <div id="file-details">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <i class="fa-solid fa-file-code" style="color: var(--accent); font-size: 20px;"></i>
                    <div style="overflow: hidden;">
                        <div id="file-name" style="font-size: 13px; font-weight: bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">No file selected</div>
                        <div id="file-size" style="font-size: 11px; color: #8b949e;">0 KB</div>
                    </div>
                </div>
            </div>
            <button type="submit" class="upload-btn">DEPLOY SERVER</button>
        </form>
    </div>

    {% for app in apps %}
    <div class="box">
        <div style="display:flex; justify-content:space-between; align-items: center; margin-bottom:15px; font-family: var(--font-head);">
            <span style="color: var(--accent);">{{ app.name }}</span>
            <span id="status-{{ app.name }}" class="status-badge {% if app.running %}status-running{% else %}status-offline{% endif %}">
                ● {% if app.running %}RUNNING{% else %}OFFLINE{% endif %}
            </span>
        </div>
        <div class="runtime-container">
            <span style="font-size: 11px; color: #8b949e;">UPTIME:</span>
            <span class="runtime-clock" id="timer-{{ app.name }}">00d 00h 00m 00s</span>
        </div>
        <div class="button-grid">
            <a href="/run/{{ app.name }}" class="btn-m run"><i class="fa-solid fa-play"></i> START</a>
            <a href="/stop/{{ app.name }}" class="btn-m stop"><i class="fa-solid fa-stop"></i> STOP</a>
            <button onclick="openFM('{{ app.name }}')" class="btn-m edit"><i class="fa-solid fa-code"></i> EDIT CODE</button>
            <a href="/restart/{{ app.name }}" class="btn-m restart"><i class="fa-solid fa-rotate"></i> RESTART</a>
            <a href="/download/{{ app.name }}" class="btn-m download"><i class="fa-solid fa-download"></i> DOWNLOAD ZIP</a>
            <button onclick="confirmDelete('{{ app.name }}', '/delete/{{ app.name }}')" class="btn-m delete"><i class="fa-solid fa-trash"></i> DELETE</button>
        </div>
        <pre id="log-{{ app.name }}">Logs will appear here...</pre>
    </div>
    {% endfor %}

    <div class="branding">
        <h1 class="jubayer-text">Y U V I C O D E X</h1>
        <p style="font-size: 11px; color: #8b949e; letter-spacing: 3px;">LOVE YOU ALL. SUPPOT KARO</p>
    </div>
</div>
<div id="fmModal">
    <div class="fm-container">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <h4 id="fmTitle" style="margin:0; color:var(--accent); font-family:var(--font-head); font-size:14px;">EDIT PROJECT</h4>
            <button onclick="closeFM()" style="background:#ff4d4d; border:none; color:white; padding:5px 12px; border-radius:5px; cursor:pointer;">CLOSE</button>
        </div>
        <div id="fileList">Loading files...</div>
        <div id="editor"></div>
        <button id="saveBtn" class="save-btn" style="display:none;" onclick="saveFile()">SAVE CHANGES</button>
    </div>
</div>
<div class="social-bar">
    <a href="https://t.me/ItsYuvi_LEGACY" target="_blank" class="social-icon"><i class="fa-brands fa-telegram"></i></a>
    <a href="https://www.youtube.com/@AlphaRush_TV" target="_blank" class="social-icon"><i class="fa-brands fa-youtube"></i></a>
    <a href="https://instagram.com/asm_niyar07" target="_blank" class="social-icon"><i class="fa-brands fa-instagram"></i></a>
    <a href="https://tiktok.com/" target="_blank" class="social-icon"><i class="fa-brands fa-tiktok"></i></a>
</div>
<script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.4.12/ace.js"></script>
<script>
    let startTimes = {}; 
    let pConfig = { color: "#00ffff", size: 38, speed: 4 };
    let editor = ace.edit("editor");
    editor.setTheme("ace/theme/monokai");
    let activeProj = "";
    let activeFile = "";

    function openFM(name) { activeProj = name; document.getElementById('fmTitle').innerText = "FILES: " + name; document.getElementById('fmModal').style.display = 'block'; refreshFiles(); }
    function closeFM() { document.getElementById('fmModal').style.display = 'none'; }
    function refreshFiles() {
        fetch('/list_files/' + activeProj).then(res => res.json()).then(data => {
            let html = "";
            data.files.forEach(f => {
                html += `<div class="file-item"><span onclick="loadFile('${f}')" style="cursor:pointer; color:var(--accent); font-size:13px;">📄 ${f}</span><i class="fa-solid fa-trash-can" onclick="deleteFile('${f}')" style="color:#ff4d4d; cursor:pointer;"></i></div>`;
            });
            document.getElementById('fileList').innerHTML = html || "Empty Project";
        });
    }
    function loadFile(f) {
        activeFile = f;
        fetch('/read_file', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({project: activeProj, filename: f}) }).then(res => res.json()).then(data => {
            editor.setValue(data.content, -1); document.getElementById('saveBtn').style.display = 'block';
            if(f.endsWith('.js')) editor.session.setMode("ace/mode/javascript");
            else if(f.endsWith('.py')) editor.session.setMode("ace/mode/python");
            else editor.session.setMode("ace/mode/text");
        });
    }
    function saveFile() {
        fetch('/save_file', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({project: activeProj, filename: activeFile, content: editor.getValue()}) }).then(res => res.json()).then(() => {
            Swal.fire({ icon: 'success', title: 'Saved!', background: '#0a0a0a', color: '#fff', timer: 1000, showConfirmButton: false });
        });
    }
    function deleteFile(f) {
        Swal.fire({ title: 'মুছে ফেলবেন?', text: `${f} স্থায়ীভাবে ডিলিট হবে!`, icon: 'warning', showCancelButton: true, confirmButtonColor: '#ff4d4d', background: '#0a0a0a', color: '#fff' }).then(res => {
            if(res.isConfirmed) { fetch('/delete_file', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({project: activeProj, filename: f}) }).then(() => refreshFiles()); }
        });
    }
    document.getElementById('fileInput').addEventListener('change', function(e) {
        const file = e.target.files[0]; const detailBox = document.getElementById('file-details');
        if (file) { document.getElementById('file-name').innerText = file.name; let size = file.size / 1024; document.getElementById('file-size').innerText = size > 1024 ? (size / 1024).toFixed(2) + " MB" : size.toFixed(2) + " KB"; detailBox.style.display = 'block'; } else { detailBox.style.display = 'none'; }
    });
    function loadParticles() {
        particlesJS('particles-js', { "particles": { "number": { "value": 60, "density": { "enable": true, "value_area": 800 } }, "color": { "value": pConfig.color }, "shape": { "type": "circle" }, "opacity": { "value": 0.8 }, "size": { "value": pConfig.size, "random": true }, "line_linked": { "enable": true, "distance": 150, "color": pConfig.color, "opacity": 0.3, "width": 2 }, "move": { "enable": true, "speed": pConfig.speed, "out_mode": "out" } }, "interactivity": { "events": { "onhover": { "enable": true, "mode": "grab" }, "onclick": { "enable": true, "mode": "push" } } }, "retina_detect": true });
        document.documentElement.style.setProperty('--accent', pConfig.color);
    }
    function toggleMenu() { const panel = document.getElementById('sidePanel'); panel.classList.toggle('active'); document.getElementById('menuIcon').className = panel.classList.contains('active') ? "fa-solid fa-xmark" : "fa-solid fa-sliders"; }
    function changeHue(newColor, element) { pConfig.color = newColor; document.querySelectorAll('.color-dot').forEach(dot => dot.classList.remove('active')); element.classList.add('active'); loadParticles(); }
    function updateSize(val) { pConfig.size = parseInt(val); loadParticles(); }
    function updateSpeed(val) { pConfig.speed = parseInt(val); loadParticles(); }
    function updateSystem() {
        {% for app in apps %}
            fetch('/get_log/{{ app.name }}').then(res => res.json()).then(data => {
                const badge = document.getElementById('status-{{ app.name }}'); const logBox = document.getElementById('log-{{ app.name }}');
                if (data.log) logBox.innerText = data.log;
                if (data.status === "RUNNING") { badge.innerText = "● RUNNING"; badge.className = "status-badge status-running"; if (data.start_time > 0) startTimes['{{ app.name }}'] = data.start_time; } 
                else { badge.innerText = "● OFFLINE"; badge.className = "status-badge status-offline"; delete startTimes['{{ app.name }}']; }
            });
        {% endfor %}
    }
    function runTimers() {
        Object.keys(startTimes).forEach(name => {
            const diff = Date.now() - startTimes[name];
            if (diff > 0) { const d = Math.floor(diff / 86400000); const h = Math.floor((diff % 86400000) / 3600000); const m = Math.floor((diff % 3600000) / 60000); const s = Math.floor((diff % 60000) / 1000); document.getElementById(`timer-${name}`).innerText = `${String(d).padStart(2,'0')}d ${String(h).padStart(2,'0')}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`; }
        });
    }
    setInterval(updateSystem, 3000); setInterval(runTimers, 1000); loadParticles();
    function confirmDelete(name, url) { Swal.fire({ title: 'মুছে ফেলবেন?', text: `${name} মুছে ফেলা হবে!`, icon: 'warning', showCancelButton: true, confirmButtonColor: '#ff4d4d', background: '#0a0a0a', color: '#fff' }).then(res => { if(res.isConfirmed) window.location.href = url; }); }
</script>
</body>
</html>
'''

# --- 3. ADMIN PANEL HTML ---
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Root | Ultra Hosting</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #030508; --card: rgba(22, 27, 34, 0.8); --accent: #00ffff; --text: #e6edf3; --glass: rgba(255, 255, 255, 0.05); }
        * { box-sizing: border-box; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 15px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 10px; background: var(--glass); border-radius: 15px; backdrop-filter: blur(10px); border: 1px solid rgba(0, 255, 255, 0.2); }
        .header h2 { font-size: 18px; color: var(--accent); margin: 0; }
        .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
        .stat-card { background: var(--card); padding: 15px; border-radius: 15px; border: 1px solid rgba(255,255,255,0.05); text-align: center; }
        .stat-card i { font-size: 20px; color: var(--accent); }
        .stat-card div { font-size: 18px; font-weight: bold; margin-top: 5px; }
        .card { background: var(--card); padding: 15px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; }
        h3 { margin-top: 0; font-size: 16px; color: var(--accent); }
        .input-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        input { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #333; background: rgba(0,0,0,0.3); color: white; outline: none; }
        .btn { padding: 12px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .btn-logout { background: #ff4757; color: white; padding: 8px 15px; text-decoration: none; border-radius: 10px; font-size: 13px; }
        .user-item { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
        .username { font-weight: bold; color: var(--accent); font-size: 16px; }
        .project-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0; }
        .project-tag { background: rgba(0,255,255,0.1); color: var(--accent); padding: 4px 10px; border-radius: 6px; font-size: 11px; }
        .action-row { display: flex; gap: 10px; margin-top: 10px; }
        .btn-login { background: #fff; color: #000; font-size: 12px; text-decoration: none; padding: 8px 12px; border-radius: 10px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="header"><h2><i class="fa-solid fa-shield-halved"></i> ROOT PANEL</h2><a href="/logout" class="btn-logout"><i class="fa-solid fa-power-off"></i></a></div>
    <div class="stats-grid"><div class="stat-card"><i class="fa-solid fa-users"></i><p style="margin:2px 0; font-size:12px; opacity:0.7;">Users</p><div>{{ users|length }}</div></div><div class="stat-card"><i class="fa-solid fa-rocket"></i><p style="margin:2px 0; font-size:12px; opacity:0.7;">Active</p><div>{{ start_times|length }}</div></div></div>
    <div class="card"><h3><i class="fa-solid fa-gears"></i> Default User Password</h3><form action="/admin/global_pw" method="post" class="input-group"><input type="text" name="global_pw" value="{{ global_pw }}"><button type="submit" class="btn btn-primary">Update Default PW</button></form></div>
    <div class="card"><h3><i class="fa-solid fa-user-gear"></i> User Database</h3>
        {% for u_name, u_pw in users.items() %}
        <div class="user-item">
            <div class="username"><i class="fa-solid fa-circle-user"></i> {{ u_name }}</div>
            <div class="project-tags">
                {% set count = namespace(value=0) %}
                {% for p_key in start_times.keys() %}{% if p_key.startswith(u_name + '_') %}<span class="project-tag">● {{ p_key.split('_')[1] }}</span>{% set count.value = count.value + 1 %}{% endif %}{% endfor %}
                {% if count.value == 0 %}<span style="color:#666; font-size:11px;">No active bots</span>{% endif %}
            </div>
            <div class="action-row">
                <form action="/admin/change_pw" method="post" style="display:flex; gap:5px; flex:2;"><input type="hidden" name="username" value="{{ u_name }}"><input type="text" name="new_pw" value="{{ u_pw }}" style="padding:8px; font-size:12px;"><button type="submit" class="btn btn-primary" style="padding:8px 12px;"><i class="fa-solid fa-save"></i></button></form>
                <a href="/admin/login_as/{{ u_name }}" class="btn-login"><i class="fa-solid fa-sign-in"></i> Login</a>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

# --- API & BACKEND ROUTING ---

@app.route("/list_files/<name>")
def list_files(name):
    if 'username' not in session: return jsonify({"files": []})
    extract_dir = os.path.join(UPLOAD_FOLDER, session['username'], name, "extracted")
    files = []
    if os.path.exists(extract_dir):
        for root, _, filenames in os.walk(extract_dir):
            for f in filenames: files.append(os.path.relpath(os.path.join(root, f), extract_dir))
    return jsonify({"files": files})

@app.route("/read_file", methods=["POST"])
def read_content():
    if 'username' not in session: return jsonify({"content": ""})
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f: return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    if 'username' not in session: return jsonify({"status": "error"})
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    with open(path, "w", encoding="utf-8") as f: f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    if 'username' not in session: return jsonify({"status": "error"})
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    if os.path.exists(path): os.remove(path)
    return jsonify({"status": "deleted"})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        
        db_data = load_db()
        ref = get_db_ref()
        
        if l_type == "admin":
            if username == ADMIN_USER and pw == ADMIN_PASS:
                session['is_admin'], session['username'] = True, ADMIN_USER
                return redirect(url_for("admin_panel"))
        else:
            if username:
                user_existing_pw = ref.child("users").child(username).get()
                
                if user_existing_pw is None:
                    current_global_pw = db_data.get("user_pw", "codex123")
                    ref.child("users").child(username).set(current_global_pw)
                    user_existing_pw = current_global_pw
                
                if pw == user_existing_pw:
                    session['is_admin'], session['username'] = False, username
                    return redirect(url_for("index"))
                    
    return render_template_string(LOGIN_HTML)

@app.route("/")
def index():
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    os.makedirs(user_dir, exist_ok=True)
    apps_list = []
    for name in os.listdir(user_dir):
        if os.path.isdir(os.path.join(user_dir, name)):
            p = processes.get((user_name, name))
            apps_list.append({"name": name, "running": (p and p.poll() is None)})
    return render_template_string(INDEX_HTML, apps=apps_list, username=user_name)

@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db_data = load_db()
    return render_template_string(ADMIN_HTML, users=db_data["users"], start_times=db_data["start_times"], global_pw=db_data["user_pw"])

@app.route("/admin/global_pw", methods=["POST"])
def global_pw():
    if not session.get('is_admin'): return redirect(url_for("login"))
    ref = get_db_ref()
    ref.child("user_pw").set(request.form.get("global_pw"))
    return redirect(url_for("admin_panel"))

@app.route("/admin/change_pw", methods=["POST"])
def change_pw():
    if not session.get('is_admin'): return redirect(url_for("login"))
    ref = get_db_ref()
    ref.child("users").child(request.form.get("username")).set(request.form.get("new_pw"))
    return redirect(url_for("admin_panel"))

@app.route("/admin/login_as/<username>")
def login_as(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    session['username'], session['is_admin'] = username, False
    return redirect(url_for("index"))

@app.route("/run/<name>")
def run(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    extract_dir = os.path.join(app_dir, "extracted")
    
    if (user_name, name) not in processes or processes[(user_name, name)].poll() is not None:
        main_file = None
        
        if os.path.exists(extract_dir):
            all_files = os.listdir(extract_dir)
            standard_files = ["main.py", "bot.py", "app.py", "index.js", "server.js"]
            main_file = next((f for f in standard_files if f in all_files), None)
            
            if not main_file:
                main_file = next((f for f in all_files if f.endswith('.py') or f.endswith('.js')), None)
                
        if main_file:
            log_path = os.path.join(app_dir, "logs.txt")
            log_file = open(log_path, "a")
            cmd = ["python", main_file] if main_file.endswith('.py') else ["node", main_file]
            processes[(user_name, name)] = subprocess.Popen(cmd, cwd=extract_dir, stdout=log_file, stderr=log_file, text=True)
            ref = get_db_ref()
            ref.child("start_times").child(f"{user_name}_{name}").set(int(time.time() * 1000))
            
    return redirect(url_for("index"))

@app.route("/get_log/<name>")
def get_log(name):
    if 'username' not in session: return jsonify({"status": "OFFLINE", "log": ""})
    user_name = session.get('username')
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    log_path = os.path.join(app_dir, "logs.txt")
    log_content = ""
    if os.path.exists(log_path):
        with open(log_path, "r") as f: log_content = f.read()[-2000:]
    p = processes.get((user_name, name))
    db_data = load_db()
    is_running = (p and p.poll() is None)
    return jsonify({"log": log_content, "status": "RUNNING" if is_running else "OFFLINE", "start_time": db_data["start_times"].get(f"{user_name}_{name}", 0)})

@app.route("/stop/<name>")
def stop(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    p = processes.get((user_name, name))
    if p: 
        p.terminate()
        try: del processes[(user_name, name)]
        except KeyError: pass
    ref = get_db_ref()
    ref.child("start_times").child(f"{user_name}_{name}").delete()
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    file = request.files.get("file")
    if file and file.filename.endswith(".zip"):
        app_name = file.filename.rsplit('.', 1)[0]
        user_dir = os.path.join(UPLOAD_FOLDER, user_name, app_name)
        os.makedirs(user_dir, exist_ok=True)
        zip_path = os.path.join(user_dir, file.filename)
        file.save(zip_path)
        extract_dir = os.path.join(user_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extract_dir)
        os.remove(zip_path)
    return redirect(url_for("index"))

@app.route("/download/<name>")
def download(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name, "extracted")
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(app_dir):
            for file in files:
                file_path = os.path.join(root, file)
                zf.write(file_path, os.path.relpath(file_path, app_dir))
    memory_file.seek(0)
    return send_file(memory_file, download_name=f"{name}.zip", as_attachment=True)

@app.route("/restart/<name>")
def restart(name):
    if 'username' not in session: return redirect(url_for("login"))
    stop(name)
    time.sleep(1)
    return run(name)

@app.route("/delete/<name>")
def delete(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    stop(name)
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    if os.path.exists(app_dir): shutil.rmtree(app_dir)
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): 
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3522, debug=True)
