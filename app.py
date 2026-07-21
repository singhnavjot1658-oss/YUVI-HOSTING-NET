import os
import sys
import time
import json
import shutil
import signal
import zipfile
import threading
import subprocess
import io
import string
import random
from datetime import datetime
import psutil
from flask import (
    Flask, render_template, request, redirect, 
    url_for, session, jsonify, send_file, render_template_string
)
import firebase_admin
from firebase_admin import credentials, storage

# ========== APP & CONFIGURATION ==========
app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_FILE = os.path.join(BASE_DIR, "database.json")
AUDIT_LOG_FILE = os.path.join(BASE_DIR, "audit_logs.json")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global runtime process registry
processes = {}

# ========== INITIALIZE FIREBASE ==========
FIREBASE_CREDS = os.environ.get("FIREBASE_CREDS")
if FIREBASE_CREDS:
    try:
        cred_dict = json.loads(FIREBASE_CREDS)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'storageBucket': cred_dict.get('project_id', '') + '.appspot.com'
        })
        print("Firebase Admin Initialized Successfully!")
    except Exception as e:
        print(f"Firebase Init Warning: {e}")
else:
    print("FIREBASE_CREDS env variable not found. Cloud backup disabled.")

# ========== DATABASE HELPERS ==========
def load_db():
    if not os.path.exists(DB_FILE):
        default_db = {
            "users": {},
            "admin": {
                "username": "JUBARAJ",
                "password": "098765",
                "api_key": generate_random_api_key(64),
                "api_key_id": generate_readable_api_id(),
                "last_login": None
            },
            "global_settings": {
                "maintenance_mode": False,
                "default_theme_color": "#00ffff",
                "max_upload_size_mb": 100,
                "session_timeout_minutes": 60
            },
            "themes": {},
            "start_times": {},
            "broadcast_history": [],
            "login_attempts": []
        }
        save_db(default_db)
        return default_db
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "admin": {}, "global_settings": {}, "themes": {}, "start_times": {}}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_audit_logs():
    if not os.path.exists(AUDIT_LOG_FILE):
        return {"logs": []}
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"logs": []}

def save_audit_logs(data):
    with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def add_audit_log(action, admin_user, details=""):
    logs_data = load_audit_logs()
    logs_data["logs"].insert(0, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "admin": admin_user,
        "details": details
    })
    # Keep last 500 logs
    logs_data["logs"] = logs_data["logs"][:500]
    save_audit_logs(logs_data)

def generate_random_api_key(length=64):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_readable_api_id():
    prefix = "YUV"
    num = ''.join(random.choice(string.digits) for _ in range(6))
    return f"{prefix}-{num}"

def stop_and_clean_user(username):
    db = load_db()
    # Stop processes
    for key, p in list(processes.items()):
        if key[0] == username:
            try:
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    p.kill()
            except Exception:
                try: p.terminate()
                except Exception: pass
            
            if os.name == 'nt':
                try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception: pass
            del processes[key]

    # Clean storage
    user_dir = os.path.join(UPLOAD_FOLDER, username)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir, ignore_errors=True)

    # Clean DB
    if username in db["users"]:
        del db["users"][username]
    if "themes" in db and username in db["themes"]:
        del db["themes"][username]
        
    save_db(db)

# ========== TEMPLATES ==========
LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YUVI HOSTING // LOGIN</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Space+Grotesk:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --neon-blue: #00ffff;
            --neon-purple: #7000ff;
            --neon-red: #ff1744;
            --neon-green: #00e676;
            --bg-dark: #03050a;
            --card-bg: rgba(10, 15, 30, 0.85);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; }
        body {
            background-color: var(--bg-dark);
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(0, 255, 255, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(112, 0, 255, 0.08) 0%, transparent 40%);
        }
        .login-card {
            background: var(--card-bg);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 0 30px rgba(0, 0, 0, 0.8), 0 0 15px rgba(0, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            position: relative;
        }
        .login-card::before {
            content: '';
            position: absolute;
            top: -1px; left: -1px; right: -1px; bottom: -1px;
            background: linear-gradient(45deg, var(--neon-blue), transparent, var(--neon-purple));
            border-radius: 16px;
            z-index: -1;
            opacity: 0.3;
        }
        .brand-header {
            text-align: center;
            margin-bottom: 30px;
        }
        .brand-header i {
            font-size: 40px;
            color: var(--neon-blue);
            text-shadow: 0 0 10px var(--neon-blue);
            margin-bottom: 10px;
        }
        .brand-header h2 {
            font-family: 'Rajdhani', sans-serif;
            font-size: 28px;
            letter-spacing: 2px;
            color: #fff;
        }
        .tab-switcher {
            display: flex;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 4px;
            margin-bottom: 25px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .tab-btn {
            flex: 1;
            padding: 10px;
            border: none;
            background: transparent;
            color: #aaa;
            font-weight: 600;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.3s ease;
            font-size: 13px;
        }
        .tab-btn.active {
            background: var(--neon-blue);
            color: #000;
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.5);
        }
        .input-group {
            margin-bottom: 20px;
        }
        .input-group label {
            display: block;
            font-size: 11px;
            color: var(--neon-blue);
            margin-bottom: 6px;
            letter-spacing: 1px;
            font-family: 'Rajdhani', sans-serif;
        }
        .input-group input {
            width: 100%;
            padding: 12px 15px;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            color: #fff;
            font-size: 14px;
            outline: none;
            transition: all 0.3s ease;
        }
        .input-group input:focus {
            border-color: var(--neon-blue);
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.2);
        }
        .btn-submit {
            width: 100%;
            padding: 14px;
            background: linear-gradient(90deg, var(--neon-blue), var(--neon-purple));
            border: none;
            border-radius: 8px;
            color: #fff;
            font-weight: 700;
            font-size: 15px;
            cursor: pointer;
            letter-spacing: 1px;
            transition: all 0.3s ease;
            box-shadow: 0 0 15px rgba(0, 255, 255, 0.3);
            margin-top: 10px;
        }
        .btn-submit:hover {
            opacity: 0.9;
            transform: translateY(-1px);
        }
        .error-badge {
            background: rgba(255, 23, 68, 0.15);
            border: 1px solid var(--neon-red);
            color: var(--neon-red);
            padding: 10px;
            border-radius: 8px;
            font-size: 12px;
            margin-bottom: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="brand-header">
            <i class="fa-solid fa-crown"></i>
            <h2>YUVI HOSTING v3</h2>
        </div>
        
        {% if error %}
        <div class="error-badge">
            <i class="fa-solid fa-triangle-exclamation"></i> {{ error }}
        </div>
        {% endif %}
        
        <div class="tab-switcher">
            <button class="tab-btn active" id="btn-user" onclick="switchLogin('user')"><i class="fa-solid fa-user"></i> USER</button>
            <button class="tab-btn" id="btn-admin" onclick="switchLogin('admin')"><i class="fa-solid fa-user-shield"></i> OWNER</button>
        </div>
        
        <form action="/login" method="post" id="loginForm">
            <input type="hidden" name="login_type" id="login_type" value="user">
            
            <div class="input-group">
                <label><i class="fa-solid fa-id-badge"></i> USERNAME</label>
                <input type="text" name="username" placeholder="Enter username..." required autocomplete="off">
            </div>
            
            <div class="input-group">
                <label><i class="fa-solid fa-key"></i> PASSWORD</label>
                <input type="password" name="password" placeholder="Enter password..." required autocomplete="off">
            </div>
            
            <button type="submit" class="btn-submit" id="submitBtn">LOGIN TO PANEL</button>
        </form>
    </div>
    
    <script>
        function switchLogin(type) {
            document.getElementById('login_type').value = type;
            if(type === 'admin') {
                document.getElementById('btn-admin').classList.add('active');
                document.getElementById('btn-user').classList.remove('active');
                document.getElementById('submitBtn').style.background = 'linear-gradient(90deg, #ff1744, #7000ff)';
                document.getElementById('submitBtn').innerText = 'LOGIN AS OWNER';
            } else {
                document.getElementById('btn-user').classList.add('active');
                document.getElementById('btn-admin').classList.remove('active');
                document.getElementById('submitBtn').style.background = 'linear-gradient(90deg, #00ffff, #7000ff)';
                document.getElementById('submitBtn').innerText = 'LOGIN TO PANEL';
            }
        }
    </script>
</body>
</html>
'''

ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YUVI HOSTING // OWNER PANEL v3</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Space+Grotesk:wght@400;600&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --neon-blue: #00ffff;
            --neon-purple: #7000ff;
            --neon-red: #ff1744;
            --neon-green: #00e676;
            --neon-yellow: #ffd740;
            --bg-dark: #03050a;
            --panel-bg: rgba(10, 15, 25, 0.95);
            --card-bg: rgba(15, 22, 38, 0.85);
            --card-border: rgba(0, 255, 255, 0.15);
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; }
        
        body {
            background-color: var(--bg-dark);
            color: #e0e6ed;
            min-height: 100vh;
            padding-bottom: 80px; /* Space for Bottom Nav Bar */
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(0, 255, 255, 0.05) 0%, transparent 30%),
                radial-gradient(circle at 90% 80%, rgba(112, 0, 255, 0.05) 0%, transparent 30%);
        }

        /* TOP BAR */
        .top-bar {
            height: 60px;
            background: rgba(8, 12, 20, 0.95);
            border-bottom: 1px solid var(--card-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            position: sticky;
            top: 0;
            z-index: 1000;
            backdrop-filter: blur(10px);
        }
        .brand {
            font-family: 'Rajdhani', sans-serif;
            font-size: 20px;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
            letter-spacing: 1px;
        }
        .brand i { color: var(--neon-yellow); text-shadow: 0 0 10px var(--neon-yellow); }
        
        .status-ticker {
            font-family: 'Fira Code', monospace;
            font-size: 11px;
            color: var(--neon-green);
            background: rgba(0, 230, 118, 0.08);
            padding: 5px 12px;
            border-radius: 20px;
            border: 1px solid rgba(0, 230, 118, 0.2);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .admin-badge {
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 13px;
        }
        .btn-logout-top {
            color: var(--neon-red);
            text-decoration: none;
            padding: 6px 12px;
            border: 1px solid rgba(255, 23, 68, 0.3);
            border-radius: 6px;
            transition: all 0.3s ease;
            font-size: 12px;
            font-weight: 600;
        }
        .btn-logout-top:hover {
            background: var(--neon-red);
            color: #fff;
            box-shadow: 0 0 10px var(--neon-red);
        }

        /* MAIN CONTENT AREA */
        .main-content {
            max-width: 1300px;
            margin: 20px auto;
            padding: 0 20px;
        }

        /* SECTION SWITCHING (TAB SYSTEM) */
        .section-wrapper {
            display: none;
            animation: fadeIn 0.3s ease-in-out;
        }
        .section-wrapper.active-section {
            display: block;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .section-title {
            font-family: 'Rajdhani', sans-serif;
            font-size: 22px;
            font-weight: 700;
            color: var(--neon-blue);
            display: flex;
            align-items: center;
            gap: 10px;
            letter-spacing: 1px;
        }
        .section-badge {
            font-size: 10px;
            background: rgba(0, 255, 255, 0.1);
            color: var(--neon-blue);
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid rgba(0, 255, 255, 0.2);
            font-family: 'Fira Code', monospace;
        }

        /* CYBER CARDS & GRIDS */
        .grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 15px; }
        .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; }

        @media (max-width: 768px) {
            .grid-2 { grid-template-columns: 1fr; }
            .top-bar { padding: 0 10px; }
            .status-ticker { display: none; }
        }

        .cyber-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            position: relative;
            backdrop-filter: blur(5px);
            transition: all 0.3s ease;
        }
        .cyber-card:hover {
            border-color: rgba(0, 255, 255, 0.4);
            box-shadow: 0 0 15px rgba(0, 255, 255, 0.05);
        }
        .card-label {
            font-family: 'Rajdhani', sans-serif;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.5);
            letter-spacing: 1px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .metric-box { text-align: left; }
        .metric-value {
            font-family: 'Rajdhani', sans-serif;
            font-size: 28px;
            font-weight: 700;
            color: #fff;
        }
        .metric-value.green { color: var(--neon-green); text-shadow: 0 0 10px rgba(0, 230, 118, 0.3); }
        .metric-value.yellow { color: var(--neon-yellow); text-shadow: 0 0 10px rgba(255, 215, 64, 0.3); }
        .metric-value.red { color: var(--neon-red); text-shadow: 0 0 10px rgba(255, 23, 68, 0.3); }
        .metric-value.blue { color: var(--neon-blue); text-shadow: 0 0 10px rgba(0, 255, 255, 0.3); }
        .metric-value.purple { color: var(--neon-purple); text-shadow: 0 0 10px rgba(112, 0, 255, 0.3); }

        .metric-label { font-size: 11px; color: #888; margin-top: 2px; }

        .progress-bar {
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 3px;
            margin-top: 10px;
            overflow: hidden;
        }
        .progress-bar .fill {
            height: 100%;
            background: linear-gradient(90deg, var(--neon-blue), var(--neon-purple));
            border-radius: 3px;
        }

        /* INPUTS & BUTTONS */
        .input-group { display: flex; flex-direction: column; gap: 12px; }
        .input-group label { font-size: 11px; color: var(--neon-blue); font-family: 'Rajdhani', sans-serif; }
        .input-group input, .input-group select, .input-group textarea {
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.15);
            padding: 10px 12px;
            border-radius: 6px;
            color: #fff;
            font-size: 13px;
            outline: none;
            transition: all 0.3s ease;
        }
        .input-group input:focus, .input-group select:focus, .input-group textarea:focus {
            border-color: var(--neon-blue);
            box-shadow: 0 0 8px rgba(0, 255, 255, 0.2);
        }

        .btn {
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 12px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.3s ease;
            text-decoration: none;
        }
        .btn-primary { background: linear-gradient(90deg, var(--neon-blue), var(--neon-purple)); color: #fff; }
        .btn-success { background: var(--neon-green); color: #000; }
        .btn-danger { background: var(--neon-red); color: #fff; }
        .btn-warning { background: var(--neon-yellow); color: #000; }
        .btn-ghost { background: rgba(255, 255, 255, 0.05); color: #fff; border: 1px solid rgba(255, 255, 255, 0.1); }
        .btn-block { width: 100%; }
        .btn-xs { padding: 4px 8px; font-size: 10px; border-radius: 4px; }
        .btn-sm { padding: 6px 12px; font-size: 11px; }

        .btn:hover { opacity: 0.85; transform: translateY(-1px); }

        /* API KEYS & CODE BLOCKS */
        .api-key-box {
            background: rgba(0, 0, 0, 0.6);
            border: 1px dashed var(--neon-blue);
            padding: 10px;
            border-radius: 6px;
            font-family: 'Fira Code', monospace;
            font-size: 12px;
            color: var(--neon-green);
            word-break: break-all;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .copy-btn {
            background: rgba(0, 255, 255, 0.1);
            border: 1px solid var(--neon-blue);
            color: var(--neon-blue);
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
        }

        .code-block {
            background: #000;
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 12px;
            border-radius: 6px;
            font-family: 'Fira Code', monospace;
            font-size: 11px;
            color: #aaa;
            white-space: pre-wrap;
            max-height: 200px;
            overflow-y: auto;
        }

        /* LOG ENTRIES */
        .log-entry {
            font-family: 'Fira Code', monospace;
            font-size: 11px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .log-time { color: rgba(255, 255, 255, 0.3); }
        .log-action { color: var(--neon-blue); }
        .log-admin { color: var(--neon-yellow); }

        /* USER DIRECTORY ITEM */
        .user-item {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 10px;
        }
        .user-info { display: flex; align-items: center; justify-content: space-between; }
        .user-info .username { font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 8px; }
        .tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 700; }
        .tag-green { background: rgba(0, 230, 118, 0.15); color: var(--neon-green); border: 1px solid rgba(0, 230, 118, 0.3); }
        .tag-blue { background: rgba(0, 255, 255, 0.15); color: var(--neon-blue); border: 1px solid rgba(0, 255, 255, 0.3); }

        .status-badge { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }
        .status-active { background: rgba(0, 230, 118, 0.2); color: var(--neon-green); }
        .status-expired { background: rgba(255, 23, 68, 0.2); color: var(--neon-red); }

        /* TOGGLE SWITCH */
        .toggle-switch { position: relative; display: inline-block; width: 40px; height: 20px; }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .toggle-track { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: rgba(255, 255, 255, 0.1); transition: .4s; border-radius: 20px; }
        .toggle-track:before { position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background-color: #fff; transition: .4s; border-radius: 50%; }
        input:checked + .toggle-track { background-color: var(--neon-green); }
        input:checked + .toggle-track:before { transform: translateX(20px); }

        /* BOTTOM NAVIGATION BAR (FIXED) */
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 65px;
            background: rgba(6, 10, 18, 0.96);
            border-top: 1px solid var(--neon-blue);
            display: flex;
            justify-content: space-around;
            align-items: center;
            z-index: 9999;
            backdrop-filter: blur(15px);
            box-shadow: 0 -5px 25px rgba(0, 0, 0, 0.8);
        }
        .nav-btn {
            background: transparent;
            border: none;
            color: rgba(255, 255, 255, 0.4);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            flex: 1;
            height: 100%;
            gap: 4px;
        }
        .nav-btn i { font-size: 18px; transition: all 0.3s ease; }
        .nav-btn.active, .nav-btn:hover {
            color: var(--neon-blue);
            text-shadow: 0 0 8px var(--neon-blue);
        }
        .nav-btn.active i {
            transform: translateY(-2px);
            color: var(--neon-blue);
        }

        /* TOAST NOTIFICATIONS */
        #toastContainer { position: fixed; top: 70px; right: 20px; z-index: 10000; }
        .toast {
            background: rgba(10, 15, 25, 0.95);
            border: 1px solid var(--neon-blue);
            color: #fff;
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 10px;
            font-size: 12px;
            box-shadow: 0 0 15px rgba(0, 0, 0, 0.5);
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
    </style>
</head>
<body>
    <div id="toastContainer"></div>

    <div class="top-bar">
        <div class="brand">
            <i class="fa-solid fa-crown"></i> YUVI HOSTING // OWNER PANEL v3
        </div>
        <div class="status-ticker">
            <i class="fa-solid fa-circle" style="color: var(--neon-green); font-size: 6px;"></i>
            SYSTEM ACTIVE // {{ sys_info.active_processes }} BOTS // {{ users.keys()|length }} USERS
        </div>
        <div class="admin-badge">
            <span><i class="fa-regular fa-user"></i> {{ admin_creds.username }}</span>
            <a href="/logout" class="btn-logout-top"><i class="fa-solid fa-power-off"></i> EXIT</a>
        </div>
    </div>
    
    <div class="main-content">
        <div class="section-wrapper active-section" id="sec-overview">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-gauge-high"></i> System Overview</div>
                <span class="section-badge">LIVE DASHBOARD</span>
            </div>
            <div class="grid-4">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-microchip"></i> CPU Usage</div>
                    <div class="metric-box" style="margin-top:5px;">
                        <div class="metric-value {% if sys_info.cpu > 80 %}red{% elif sys_info.cpu > 50 %}yellow{% else %}green{% endif %}">{{ sys_info.cpu }}%</div>
                        <div class="metric-label">Processor Load</div>
                        <div class="progress-bar"><div class="fill" style="width:{{ sys_info.cpu }}%;"></div></div>
                    </div>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-memory"></i> RAM Usage</div>
                    <div class="metric-box" style="margin-top:5px;">
                        <div class="metric-value {% if sys_info.ram > 80 %}red{% elif sys_info.ram > 50 %}yellow{% else %}green{% endif %}">{{ sys_info.ram }}%</div>
                        <div class="metric-label">Memory Load</div>
                        <div class="progress-bar"><div class="fill" style="width:{{ sys_info.ram }}%;"></div></div>
                    </div>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-robot"></i> Active Bots</div>
                    <div class="metric-box" style="margin-top:5px;">
                        <div class="metric-value blue">{{ sys_info.active_processes }}</div>
                        <div class="metric-label">Running Processes</div>
                    </div>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-users"></i> Total Users</div>
                    <div class="metric-box" style="margin-top:5px;">
                        <div class="metric-value purple">{{ users.keys()|length }}</div>
                        <div class="metric-label">Registered Accounts</div>
                    </div>
                </div>
            </div>

            <div style="margin-top: 20px;">
                <div class="grid-2">
                    <div class="cyber-card">
                        <div class="card-label"><i class="fa-solid fa-clock"></i> System Uptime</div>
                        <div class="metric-box" style="margin-top:5px;">
                            <div class="metric-value blue">{{ sys_info.uptime_days }}d {{ sys_info.uptime_hours }}h {{ sys_info.uptime_mins }}m</div>
                            <div class="metric-label">Server Running Since Last Restart</div>
                        </div>
                    </div>
                    <div class="cyber-card">
                        <div class="card-label"><i class="fa-solid fa-database"></i> Storage Status</div>
                        <div class="metric-box" style="margin-top:5px;">
                            <div class="metric-value green">{{ sys_info.storage_used_gb }} GB / {{ sys_info.storage_total_gb }} GB</div>
                            <div class="metric-label">Upload Storage Usage</div>
                            <div class="progress-bar"><div class="fill" style="width:{{ sys_info.storage_percent }}%;"></div></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="section-wrapper" id="sec-users">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-users"></i> User Management</div>
                <span class="section-badge">{{ users.keys()|length }} ACCOUNTS</span>
            </div>
            
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-user-plus"></i> Create New Account</div>
                    <form action="/admin/create_user" method="post" class="input-group">
                        <div>
                            <label>USERNAME</label>
                            <input type="text" name="username" placeholder="Enter username..." required autocomplete="off">
                        </div>
                        <div>
                            <label>PASSWORD</label>
                            <input type="password" name="password" placeholder="Enter password..." required autocomplete="off">
                        </div>
                        <div>
                            <label>PLAN TYPE</label>
                            <select name="plan_type" id="plan_select" onchange="toggleValidityInput()">
                                <option value="30_days">30 Days Plan</option>
                                <option value="custom">Custom Days</option>
                                <option value="permanent">Permanent Plan</option>
                            </select>
                        </div>
                        <div id="custom_days_group" style="display: none;">
                            <label>VALIDITY (DAYS)</label>
                            <input type="number" name="custom_days" placeholder="e.g. 15" min="1" value="30">
                        </div>
                        <button type="submit" class="btn btn-primary" style="margin-top: 10px;">
                            <i class="fa-solid fa-plus"></i> CREATE USER
                        </button>
                    </form>
                </div>

                <div class="cyber-card" style="max-height: 500px; overflow-y: auto;">
                    <div class="card-label"><i class="fa-solid fa-address-book"></i> Active Users Directory</div>
                    
                    {% for username, udata in users.items() %}
                    <div class="user-item">
                        <div class="user-info">
                            <div class="username">
                                <i class="fa-solid fa-circle-user"></i> {{ username }}
                                {% if udata.get("plan_type") == "permanent" %}
                                    <span class="tag tag-blue">PERMANENT</span>
                                {% else %}
                                    <span class="tag tag-green">{{ udata.get("days_left", 0) }} DAYS LEFT</span>
                                {% endif %}
                            </div>
                            <div>
                                {% if udata.get("status") == "active" or udata.get("plan_type") == "permanent" %}
                                    <span class="status-badge status-active">ACTIVE</span>
                                {% else %}
                                    <span class="status-badge status-expired">EXPIRED</span>
                                {% endif %}
                            </div>
                        </div>
                        
                        <div style="font-size: 11px; color: #888; margin: 8px 0;">
                            Expiry: {{ udata.get("expiry_date", "N/A") }} | Apps: {{ udata.get("app_count", 0) }}
                        </div>
                        
                        <div style="display: flex; gap: 8px; margin-top: 10px;">
                            <form action="/admin/renew_user" method="post" style="display: inline-flex; gap: 4px;">
                                <input type="hidden" name="username" value="{{ username }}">
                                <input type="number" name="add_days" value="30" style="width: 60px; padding: 4px; font-size: 11px;" min="1">
                                <button type="submit" class="btn btn-xs btn-warning"><i class="fa-solid fa-clock-rotate-left"></i> Add Days</button>
                            </form>
                            
                            <a href="/admin/toggle_user_status/{{ username }}" class="btn btn-xs btn-ghost">
                                <i class="fa-solid fa-power-off"></i> Toggle
                            </a>
                            
                            <a href="/admin/delete_user/{{ username }}" class="btn btn-xs btn-danger" onclick="return confirm('Delete user {{ username }} and all files?')">
                                <i class="fa-solid fa-trash"></i> Delete
                            </a>
                        </div>
                    </div>
                    {% else %}
                    <div style="text-align: center; padding: 20px; color: #666; font-size: 12px;">No users created yet.</div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="section-wrapper" id="sec-broadcast">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-bullhorn"></i> Broadcast Announcements</div>
                <span class="section-badge">SYSTEM NOTIFIER</span>
            </div>
            
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-paper-plane"></i> Send Global Announcement</div>
                    <form action="/admin/send_broadcast" method="post" class="input-group">
                        <div>
                            <label>NOTIFICATION MESSAGE</label>
                            <textarea name="broadcast_message" rows="4" placeholder="Enter message for all user dashboards..." required></textarea>
                        </div>
                        <div>
                            <label>ALERT TYPE</label>
                            <select name="alert_type">
                                <option value="info">Info (Blue)</option>
                                <option value="warning">Warning (Yellow)</option>
                                <option value="critical">Critical Alert (Red)</option>
                                <option value="success">Success Notice (Green)</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fa-solid fa-satellite-dish"></i> TRANSMIT BROADCAST
                        </button>
                    </form>
                </div>

                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-history"></i> Broadcast History</div>
                    <div style="max-height: 250px; overflow-y: auto;">
                        {% for item in broadcast_history %}
                        <div class="log-entry">
                            <span class="log-time">[{{ item.timestamp }}]</span>
                            <span class="log-action">({{ item.type|upper }})</span>:
                            <span>{{ item.message }}</span>
                        </div>
                        {% else %}
                        <div style="color: #666; font-size: 12px; padding: 10px;">No broadcast history found.</div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>

        <div class="section-wrapper" id="sec-backup">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-cloud-arrow-up"></i> Backup & Database Restore</div>
                <span class="section-badge">CLOUD & STORAGE</span>
            </div>
            
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-download"></i> Manual Database Backup</div>
                    <p style="font-size: 12px; color: #aaa; margin-bottom: 15px;">Download full database dump in JSON format or manually sync to Firebase storage.</p>
                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                        <a href="/admin/download_db_backup" class="btn btn-primary">
                            <i class="fa-solid fa-file-arrow-down"></i> Export JSON Database
                        </a>
                        <a href="/admin/firebase_sync" class="btn btn-success">
                            <i class="fa-solid fa-cloud-check"></i> Sync to Firebase Cloud
                        </a>
                    </div>
                </div>

                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-upload"></i> Restore Backup</div>
                    <form action="/admin/restore_backup" method="post" enctype="multipart/form-data" class="input-group">
                        <div>
                            <label>SELECT BACKUP FILE (.JSON or .ZIP)</label>
                            <input type="file" name="backup_file" accept=".json,.zip" required>
                        </div>
                        <button type="submit" class="btn btn-warning" onclick="return confirm('Warning: Restoring backup will overwrite current database!')">
                            <i class="fa-solid fa-rotate-left"></i> RESTORE DATABASE
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <div class="section-wrapper" id="sec-api">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-key"></i> External API & Telegram Controls</div>
                <span class="section-badge">API ACCESS</span>
            </div>
            
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-shield-halved"></i> Owner API Key</div>
                    <p style="font-size: 12px; color: #aaa; margin-bottom: 10px;">Use this key for external API integration and Telegram bot administration.</p>
                    
                    <div class="api-key-box" style="margin-bottom: 15px;">
                        <span id="apiKeyText">{{ admin_creds.api_key }}</span>
                        <button class="copy-btn" onclick="copyToClipboard('apiKeyText')"><i class="fa-regular fa-copy"></i> Copy</button>
                    </div>

                    <div style="font-size: 11px; color: #888; margin-bottom: 15px;">
                        Key ID: <strong style="color: var(--neon-blue);">{{ admin_creds.api_key_id }}</strong>
                    </div>

                    <form action="/admin/regenerate_api_key" method="post">
                        <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Regenerate API key? Existing integrations will stop working.')">
                            <i class="fa-solid fa-arrows-rotate"></i> REGENERATE API KEY
                        </button>
                    </form>
                </div>

                <div class="cyber-card">
                    <div class="card-label"><i class="fa-brands fa-telegram"></i> Telegram Bot API Integration</div>
                    <p style="font-size: 12px; color: #aaa; margin-bottom: 10px;">Webhook Endpoint for Telegram Bot commands:</p>
                    <div class="code-block">POST /api/v1/telegram_webhook
Header: X-API-KEY: {{ admin_creds.api_key }}
Payload: { "command": "/status" }</div>
                </div>
            </div>
        </div>

        <div class="section-wrapper" id="sec-security">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-shield-cat"></i> Audit Logs & Security</div>
                <span class="section-badge">REALTIME LOGS</span>
            </div>
            
            <div class="cyber-card">
                <div class="card-label"><i class="fa-solid fa-list-check"></i> Recent Security Audit Trail</div>
                <div style="max-height: 400px; overflow-y: auto; background: #000; border-radius: 6px; padding: 10px; border: 1px solid rgba(255,255,255,0.05);">
                    {% for log in audit_logs %}
                    <div class="log-entry">
                        <span class="log-time">[{{ log.timestamp }}]</span>
                        <span class="log-admin">[{{ log.admin }}]</span>
                        <span class="log-action">{{ log.action }}:</span>
                        <span style="color: #ccc;">{{ log.details }}</span>
                    </div>
                    {% else %}
                    <div style="color: #666; font-size: 12px;">No audit records available.</div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="section-wrapper" id="sec-controls">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-gears"></i> Server Emergency Controls</div>
                <span class="section-badge">ADMIN ACTIONS</span>
            </div>
            
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-lock"></i> Global Maintenance Mode</div>
                    <p style="font-size: 12px; color: #aaa; margin-bottom: 15px;">When active, regular users cannot log in or manage their applications.</p>
                    
                    <form action="/admin/toggle_maintenance" method="post" style="display: flex; align-items: center; justify-content: space-between;">
                        <span style="font-weight: 600; font-size: 13px;">Maintenance State:</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="maintenance_mode" onchange="this.form.submit()" {% if global_settings.maintenance_mode %}checked{% endif %}>
                            <span class="toggle-track"></span>
                        </label>
                    </form>
                </div>

                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-triangle-exclamation"></i> Emergency Server Restart</div>
                    <p style="font-size: 12px; color: #aaa; margin-bottom: 15px;">Restart the Flask server process. Background supervisor will automatically relaunch the app.</p>
                    <a href="/admin/restart_server" class="btn btn-danger" onclick="return confirm('Are you sure you want to restart the server process?')">
                        <i class="fa-solid fa-power-off"></i> RESTART FLASK SERVER
                    </a>
                </div>
            </div>
        </div>
    </div>

    <div class="bottom-nav">
        <button class="nav-btn active" id="btn-overview" onclick="switchTab('sec-overview', this)">
            <i class="fa-solid fa-gauge-high"></i>
            <span>Overview</span>
        </button>
        <button class="nav-btn" id="btn-users" onclick="switchTab('sec-users', this)">
            <i class="fa-solid fa-users"></i>
            <span>Users</span>
        </button>
        <button class="nav-btn" id="btn-broadcast" onclick="switchTab('sec-broadcast', this)">
            <i class="fa-solid fa-bullhorn"></i>
            <span>Broadcast</span>
        </button>
        <button class="nav-btn" id="btn-backup" onclick="switchTab('sec-backup', this)">
            <i class="fa-solid fa-cloud-arrow-up"></i>
            <span>Backup</span>
        </button>
        <button class="nav-btn" id="btn-api" onclick="switchTab('sec-api', this)">
            <i class="fa-solid fa-key"></i>
            <span>API Keys</span>
        </button>
        <button class="nav-btn" id="btn-security" onclick="switchTab('sec-security', this)">
            <i class="fa-solid fa-shield-cat"></i>
            <span>Audit Logs</span>
        </button>
        <button class="nav-btn" id="btn-controls" onclick="switchTab('sec-controls', this)">
            <i class="fa-solid fa-gears"></i>
            <span>Controls</span>
        </button>
    </div>

    <script>
        // Tab Switcher
        function switchTab(sectionId, btnElement) {
            // Hide all sections
            document.querySelectorAll('.section-wrapper').forEach(sec => {
                sec.classList.remove('active-section');
            });

            // Show target section
            const target = document.getElementById(sectionId);
            if (target) {
                target.classList.add('active-section');
            }

            // Update active nav button
            document.querySelectorAll('.nav-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            btnElement.classList.add('active');

            // Save active tab in localStorage
            localStorage.setItem('active_owner_tab', sectionId);

            // Smooth scroll to top
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // Restore last active tab on refresh
        document.addEventListener('DOMContentLoaded', () => {
            const savedTab = localStorage.getItem('active_owner_tab');
            if (savedTab) {
                const targetBtn = document.querySelector(`.nav-btn[onclick*="${savedTab}"]`);
                if (targetBtn) {
                    switchTab(savedTab, targetBtn);
                    return;
                }
            }
            // Default to overview
            switchTab('sec-overview', document.getElementById('btn-overview'));
        });

        // Toggle validity input on plan select change
        function toggleValidityInput() {
            const planSelect = document.getElementById('plan_select');
            const customGroup = document.getElementById('custom_days_group');
            if (planSelect.value === 'custom') {
                customGroup.style.display = 'block';
            } else {
                customGroup.style.display = 'none';
            }
        }

        // Copy API key helper
        function copyToClipboard(elementId) {
            const text = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(text).then(() => {
                showToast('API Key copied to clipboard!');
            }).catch(err => {
                showToast('Failed to copy text', 'red');
            });
        }

        // Toast Notification System
        function showToast(message, color = 'var(--neon-blue)') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.style.borderColor = color;
            toast.innerHTML = `<i class="fa-solid fa-circle-info"></i> ${message}`;
            container.appendChild(toast);

            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s ease';
                setTimeout(() => toast.remove(), 500);
            }, 3000);
        }
    </script>
</body>
</html>
'''

# ========== USER PANEL TEMPLATE ==========
USER_PANEL_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YUVI HOSTING // DASHBOARD</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Space+Grotesk:wght@400;600&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --neon-blue: {{ user_theme.get('color', '#00ffff') }};
            --neon-purple: #7000ff;
            --neon-red: #ff1744;
            --neon-green: #00e676;
            --bg-dark: #03050a;
            --card-bg: rgba(10, 15, 25, 0.9);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; }
        body { background-color: var(--bg-dark); color: #fff; min-height: 100vh; padding: 20px; }
        .top-nav { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); padding: 20px; border-radius: 12px; }
        .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; font-weight: 600; font-size: 12px; display: inline-flex; align-items: center; gap: 6px; }
        .btn-primary { background: var(--neon-blue); color: #000; }
        .btn-danger { background: var(--neon-red); color: #fff; }
        .btn-success { background: var(--neon-green); color: #000; }
    </style>
</head>
<body>
    <div class="top-nav">
        <h2><i class="fa-solid fa-server"></i> YUVI HOSTING DASHBOARD</h2>
        <div>
            <span>Welcome, <strong>{{ username }}</strong></span>
            <a href="/logout" class="btn btn-danger" style="margin-left: 15px;"><i class="fa-solid fa-power-off"></i> Logout</a>
        </div>
    </div>

    {% if broadcast_alerts %}
    <div style="margin-bottom: 20px;">
        {% for alert in broadcast_alerts %}
        <div style="background: rgba(0,255,255,0.1); border: 1px solid var(--neon-blue); padding: 12px; border-radius: 8px; margin-bottom: 10px; font-size: 13px;">
            <i class="fa-solid fa-bullhorn"></i> <strong>NOTICE:</strong> {{ alert.message }}
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="grid">
        <div class="card">
            <h3><i class="fa-solid fa-upload"></i> Deploy New Bot / Script</h3>
            <p style="font-size: 12px; color: #aaa; margin: 10px 0;">Upload a .ZIP file containing your Python (.py) or Node.js (.js) project files.</p>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".zip" required style="margin-bottom: 10px; width: 100%;">
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-cloud-arrow-up"></i> Upload & Deploy</button>
            </form>
        </div>

        <div class="card">
            <h3><i class="fa-solid fa-list-check"></i> Your Deployed Apps</h3>
            <div style="margin-top: 15px;">
                {% for app_name in apps %}
                <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.4); padding: 10px; border-radius: 6px; margin-bottom: 8px;">
                    <span style="font-weight: 600; font-family: 'Fira Code', monospace;">{{ app_name }}</span>
                    <div style="display: flex; gap: 5px;">
                        <a href="/run/{{ app_name }}" class="btn btn-success"><i class="fa-solid fa-play"></i> Run</a>
                        <a href="/stop/{{ app_name }}" class="btn btn-danger"><i class="fa-solid fa-stop"></i> Stop</a>
                        <a href="/delete/{{ app_name }}" class="btn btn-danger" onclick="return confirm('Delete app {{ app_name }}?')"><i class="fa-solid fa-trash"></i></a>
                    </div>
                </div>
                {% else %}
                <div style="color: #666; font-size: 12px;">No applications uploaded yet.</div>
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
'''

# ========== ROUTE HANDLERS ==========

@app.route("/")
def index():
    if 'username' not in session:
        return redirect(url_for("login"))
    if session.get('is_admin'):
        return redirect(url_for("admin_panel"))
    
    username = session['username']
    db = load_db()
    
    # Check expiry
    user_data = db["users"].get(username, {})
    if user_data.get("plan_type") != "permanent" and user_data.get("status") == "expired":
        return "ACCOUNT EXPIRED. Contact administrator."

    user_dir = os.path.join(UPLOAD_FOLDER, username)
    apps = []
    if os.path.exists(user_dir):
        apps = [d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))]

    user_theme = db.get("themes", {}).get(username, {})
    broadcast_alerts = db.get("broadcast_history", [])[-3:] # Last 3 broadcasts

    return render_template_string(
        USER_PANEL_HTML, 
        username=username, 
        apps=apps, 
        user_theme=user_theme,
        broadcast_alerts=broadcast_alerts
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        db = load_db()
        
        if login_type == "admin":
            admin_data = db.get("admin", {})
            if username == admin_data.get("username") and password == admin_data.get("password"):
                session['username'] = username
                session['is_admin'] = True
                add_audit_log("Admin Login Success", username, f"Logged in from IP {request.remote_addr}")
                return redirect(url_for("admin_panel"))
            else:
                add_audit_log("Admin Login Failed", username, f"Failed attempt from IP {request.remote_addr}")
                return render_template_string(LOGIN_HTML, error="Invalid Owner Credentials")
        else:
            users = db.get("users", {})
            if username in users and users[username].get("password") == password:
                # Check Maintenance
                if db.get("global_settings", {}).get("maintenance_mode"):
                    return render_template_string(LOGIN_HTML, error="System is under maintenance. Please try later.")
                
                session['username'] = username
                session['is_admin'] = False
                return redirect(url_for("index"))
            else:
                return render_template_string(LOGIN_HTML, error="Invalid Username or Password")
                
    return render_template_string(LOGIN_HTML)

@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'):
        return redirect(url_for("login"))
    
    db = load_db()
    
    # System info gathering
    uptime = time.time() - psutil.boot_time()
    uptime_days = int(uptime // (24 * 3600))
    uptime_hours = int((uptime % (24 * 3600)) // 3600)
    uptime_mins = int((uptime % 3600) // 60)
    
    active_procs_count = sum(1 for p in processes.values() if p.poll() is None)
    
    # Disk Usage
    total_disk, used_disk, free_disk = shutil.disk_usage(UPLOAD_FOLDER)
    
    sys_info = {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "active_processes": active_procs_count,
        "uptime_days": uptime_days,
        "uptime_hours": uptime_hours,
        "uptime_mins": uptime_mins,
        "storage_used_gb": round(used_disk / (1024**3), 2),
        "storage_total_gb": round(total_disk / (1024**3), 2),
        "storage_percent": round((used_disk / total_disk) * 100, 1)
    }

    audit_logs = load_audit_logs().get("logs", [])[:50]
    
    return render_template_string(
        ADMIN_HTML,
        users=db.get("users", {}),
        admin_creds=db.get("admin", {}),
        global_settings=db.get("global_settings", {}),
        sys_info=sys_info,
        broadcast_history=db.get("broadcast_history", []),
        audit_logs=audit_logs
    )

@app.route("/admin/create_user", methods=["POST"])
def admin_create_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    plan_type = request.form.get("plan_type", "30_days")
    custom_days = int(request.form.get("custom_days", 30))

    if not username or not password:
        return redirect(url_for("admin_panel"))

    db = load_db()
    if username in db["users"]:
        return redirect(url_for("admin_panel"))

    days = 30
    if plan_type == "custom":
        days = custom_days
    elif plan_type == "permanent":
        days = 99999

    db["users"][username] = {
        "password": password,
        "plan_type": plan_type,
        "days_left": days,
        "expiry_date": (datetime.now()).strftime("%Y-%m-%d"),
        "status": "active",
        "app_count": 0
    }
    save_db(db)
    add_audit_log("Create User", session['username'], f"Created user {username} with plan {plan_type}")
    return redirect(url_for("admin_panel"))
@app.route("/admin/renew_user", methods=["POST"])
def admin_renew_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    username = request.form.get("username")
    add_days = int(request.form.get("add_days", 30))
    
    db = load_db()
    if username in db["users"]:
        db["users"][username]["days_left"] = db["users"][username].get("days_left", 0) + add_days
        db["users"][username]["status"] = "active"
        save_db(db)
        add_audit_log("Renew User", session['username'], f"Added {add_days} days to {username}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/toggle_user_status/<username>")
def admin_toggle_user_status(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if username in db["users"]:
        curr = db["users"][username].get("status", "active")
        db["users"][username]["status"] = "expired" if curr == "active" else "active"
        save_db(db)
        add_audit_log("Toggle User Status", session['username'], f"Toggled status of {username} to {db['users'][username]['status']}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_user/<username>")
def admin_delete_user(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    stop_and_clean_user(username)
    add_audit_log("Delete User", session['username'], f"Deleted user and all data for {username}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/send_broadcast", methods=["POST"])
def admin_send_broadcast():
    if not session.get('is_admin'): return redirect(url_for("login"))
    msg = request.form.get("broadcast_message", "").strip()
    alert_type = request.form.get("alert_type", "info")
    
    if msg:
        db = load_db()
        if "broadcast_history" not in db: db["broadcast_history"] = []
        db["broadcast_history"].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": msg,
            "type": alert_type
        })
        save_db(db)
        add_audit_log("Send Broadcast", session['username'], f"Sent [{alert_type}] message: {msg}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/download_db_backup")
def admin_download_db_backup():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(db, indent=4).encode('utf-8'))
    mem_file.seek(0)
    add_audit_log("Export DB Backup", session['username'], "Downloaded JSON database dump")
    return send_file(mem_file, download_name=f"database_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", as_attachment=True)

@app.route("/admin/regenerate_api_key", methods=["POST"])
def admin_regenerate_api_key():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    new_key = generate_random_api_key(64)
    new_id = generate_readable_api_id()
    db["admin"]["api_key"] = new_key
    db["admin"]["api_key_id"] = new_id
    save_db(db)
    add_audit_log("Regenerate API Key", session['username'], "Generated new owner API key")
    return redirect(url_for("admin_panel"))

@app.route("/admin/toggle_maintenance", methods=["POST"])
def admin_toggle_maintenance():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    current = db["global_settings"].get("maintenance_mode", False)
    db["global_settings"]["maintenance_mode"] = not current
    save_db(db)
    add_audit_log("Toggle Maintenance", session['username'], f"Maintenance mode set to {not current}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/restore_backup", methods=["POST"])
def restore_backup():
    if not session.get('is_admin'): return redirect(url_for("login"))
    file = request.files.get("backup_file")
    if not file: return redirect(url_for("admin_panel"))
    
    try:
        if file.filename.endswith('.json'):
            content = file.read().decode()
            data = json.loads(content)
            if "users" in data:
                save_db(data)
                add_audit_log("Backup Restored", session['username'], "Database restored from JSON backup")
        elif file.filename.endswith('.zip'):
            zip_path = os.path.join(UPLOAD_FOLDER, "_restore_temp.zip")
            file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                if "database.json" in zf.namelist():
                    db_data = json.loads(zf.read("database.json"))
                    if "users" in db_data:
                        save_db(db_data)
                zf.extractall(UPLOAD_FOLDER)
            os.remove(zip_path)
            add_audit_log("Full Restore", session['username'], "Full system restored from ZIP backup")
    except Exception as e:
        print(f"Restore Error: {e}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/firebase_sync")
def firebase_sync():
    if not session.get('is_admin'): return redirect(url_for("login"))
    if firebase_admin._apps:
        try:
            db = load_db()
            bucket = storage.bucket()
            blob = bucket.blob(f"backups/_admin/database_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            blob.upload_from_string(json.dumps(db, indent=4))
            add_audit_log("Firebase Sync", session['username'], "Database synced to Firebase cloud")
        except Exception as e:
            print(f"Firebase sync error: {e}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/restart_server")
def restart_server():
    if not session.get('is_admin'): return redirect(url_for("login"))
    add_audit_log("Server Restart", session['username'], "Server restart initiated")
    def delayed_restart():
        time.sleep(2)
        os._exit(0)
    threading.Thread(target=delayed_restart, daemon=True).start()
    return "Server is restarting... <a href='/login'>Back to Login</a>"

# ========== FILE MANAGER ==========
@app.route("/list_files/<name>")
def list_files(name):
    if 'username' not in session: return jsonify({"files": []})
    user_name = session['username']
    db = load_db()
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired"):
        return jsonify({"files": [], "error": "expired"})
        
    extract_dir = os.path.join(UPLOAD_FOLDER, user_name, name, "extracted")
    files = []
    if os.path.exists(extract_dir):
        for root, _, filenames in os.walk(extract_dir):
            for f in filenames: files.append(os.path.relpath(os.path.join(root, f), extract_dir))
    return jsonify({"files": files})

@app.route("/read_file", methods=["POST"])
def read_content():
    if 'username' not in session: return jsonify({"content": ""})
    user_name = session['username']
    db = load_db()
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired"):
        return jsonify({"content": "PLAN EXPIRED"})
        
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted", data['filename'])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f: return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    if 'username' not in session: return jsonify({"status": "error"})
    user_name = session['username']
    db = load_db()
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired"):
        return jsonify({"status": "expired"})
        
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted", data['filename'])
    with open(path, "w", encoding="utf-8") as f: f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    if 'username' not in session: return jsonify({"status": "error"})
    user_name = session['username']
    db = load_db()
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired"):
        return jsonify({"status": "expired"})
        
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted", data['filename'])
    if os.path.exists(path): os.remove(path)
    return jsonify({"status": "deleted"})

@app.route("/save_theme", methods=["POST"])
def save_theme():
    if 'username' not in session: return jsonify({"status": "unauthorized"}), 401
    user_name = session['username']
    data = request.json or {}
    db = load_db()
    if "themes" not in db: db["themes"] = {}
    
    current_theme = db["themes"].get(user_name, {})
    current_theme.update({
        "color": data.get("color", current_theme.get("color", "#00ffff")),
        "size": int(data.get("size", current_theme.get("size", 38))),
        "speed": int(data.get("speed", current_theme.get("speed", 4))),
        "ui_mode": data.get("ui_mode", current_theme.get("ui_mode", "normal"))
    })
    
    db["themes"][user_name] = current_theme
    save_db(db)
    return jsonify({"status": "success"})

# ========== APP LIFECYCLE ==========
def bg_smart_scan_and_run(user_name, name, app_dir, extract_dir):
    log_path = os.path.join(app_dir, "logs.txt")
    req_file_path = os.path.join(extract_dir, "requirements.txt")
    with open(log_path, "a") as log_file:
        if not os.path.exists(req_file_path):
            try: subprocess.run(["pipreqs", extract_dir, "--force"], stdout=log_file, stderr=log_file, text=True, check=True)
            except Exception: pass
        if os.path.exists(req_file_path) and os.path.getsize(req_file_path) > 0:
            try: subprocess.run(["pip", "install", "-r", "requirements.txt", "--disable-pip-version-check"], cwd=extract_dir, stdout=log_file, stderr=log_file, text=True, check=True)
            except Exception: pass
    
    for f in os.listdir(extract_dir):
        file_path = os.path.join(extract_dir, f)
        if os.path.isfile(file_path) and (f.endswith('.py') or f.endswith('.js')):
            process_key = (user_name, name, f)
            if process_key not in processes or processes[process_key].poll() is not None:
                log_file_handle = open(log_path, "a")
                cmd = ["python", f] if f.endswith('.py') else ["node", f]
                
                kwargs = {}
                if hasattr(os, 'setsid'):
                    kwargs['preexec_fn'] = os.setsid
                    
                processes[process_key] = subprocess.Popen(cmd, cwd=extract_dir, stdout=log_file_handle, stderr=log_file_handle, text=True, **kwargs)
                db = load_db()
                db["start_times"][f"{user_name}_{name}_{f}"] = int(time.time() * 1000)
                save_db(db)

@app.route("/run/<name>")
def run(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    db = load_db()
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired"):
        return redirect(url_for("index"))
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    extract_dir = os.path.join(app_dir, "extracted")
    if os.path.exists(extract_dir):
        threading.Thread(target=bg_smart_scan_and_run, args=(user_name, name, app_dir, extract_dir)).start()
    return redirect(url_for("index"))

@app.route("/get_log/<name>")
def get_log(name):
    if 'username' not in session: return jsonify({"log": "", "status": "OFFLINE", "start_time": 0})
    user_name = session.get('username')
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    log_path = os.path.join(app_dir, "logs.txt")
    log_content = ""
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f: log_content = f.read()[-2000:]
    is_running = False
    db = load_db()
    oldest_time = 0
    for key, p in list(processes.items()):
        if key[0] == user_name and key[1] == name and p.poll() is None:
            is_running = True
            t_key = f"{user_name}_{name}_{key[2]}"
            if oldest_time == 0 or db["start_times"].get(t_key, 0) < oldest_time: oldest_time = db["start_times"].get(t_key, 0)
    return jsonify({"log": log_content, "status": "RUNNING" if is_running else "OFFLINE", "start_time": oldest_time})

@app.route("/stop/<name>")
def stop(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    db = load_db()
    for key, p in list(processes.items()):
        if key[0] == user_name and key[1] == name:
            try:
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    p.kill()
            except Exception:
                try: p.terminate()
                except Exception: pass
            
            if os.name == 'nt':
                try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception: pass
                
            del processes[key]
            t_key = f"{user_name}_{name}_{key[2]}"
            if t_key in db.get("start_times", {}): del db["start_times"][t_key]
    save_db(db)
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
        if firebase_admin._apps:
            try:
                bucket = storage.bucket()
                blob = bucket.blob(f"backups/{user_name}/{file.filename}")
                blob.upload_from_filename(zip_path)
            except Exception: pass
        extract_dir = os.path.join(user_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extract_dir)
        os.remove(zip_path)
        
        # Increment app count
        db = load_db()
        if user_name in db["users"]:
            db["users"][user_name]["app_count"] = db["users"][user_name].get("app_count", 0) + 1
            save_db(db)

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
    stop(name)
    time.sleep(1)
    return run(name)

@app.route("/delete/<name>")
def delete(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    stop(name)
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    if os.path.exists(app_dir): 
        try: shutil.rmtree(app_dir, ignore_errors=True)
        except Exception: pass
    
    db = load_db()
    if user_name in db["users"] and db["users"][user_name].get("app_count", 0) > 0:
        db["users"][user_name]["app_count"] -= 1
        save_db(db)

    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blob = bucket.blob(f"backups/{user_name}/{name}.zip")
            if blob.exists(): blob.delete()
        except Exception: pass
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): 
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3522, debug=True, use_reloader=False)
