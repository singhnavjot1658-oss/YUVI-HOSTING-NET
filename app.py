from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io, threading, signal, psutil, secrets, string
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, storage

app = Flask(__name__, template_folder=".")
app.secret_key = secrets.token_hex(48)

UPLOAD_FOLDER = "uploads"
DB_FILE = "database.json"
AUDIT_LOG_FILE = "audit_logs.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}
db_lock = threading.Lock()

# --- FIREBASE INIT ---
if not firebase_admin._apps:
    firebase_creds_json = os.environ.get("FIREBASE_CREDS")
    if firebase_creds_json:
        try:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            project_id = creds_dict.get("project_id", "yuvi-hosting-net")
            bucket_name = f"{project_id}.appspot.com"
            firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
        except Exception as e:
            print(f"Firebase Init Error: {e}")

# ========== RANDOM API KEY GENERATOR ==========
def generate_random_api_key(length=64):
    """Generate a cryptographically secure random API key with mixed chars."""
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    # Make it look chaotic like "6ujvsjzixbsnakshxjdbsvsnhxdsv sjhxbdcdjsjebdyxhzbsskskdjdbbd"
    raw = ''.join(secrets.choice(charset) for _ in range(length))
    # Add some random spaces and special chars in between for that "lamsa" look
    parts = []
    pos = 0
    while pos < length:
        chunk_len = secrets.randbelow(8) + 3
        chunk = raw[pos:min(pos+chunk_len, length)]
        if secrets.randbelow(3) == 0 and pos + chunk_len < length:
            chunk += secrets.choice(" ._-")
        parts.append(chunk)
        pos += chunk_len
    return ''.join(parts)

def generate_readable_api_id():
    """Generate a short readable ID like 'xk7m9p' for display."""
    return secrets.token_hex(4)

# ========== AUDIT LOG SYSTEM ==========
def load_audit_logs():
    if os.path.exists(AUDIT_LOG_FILE):
        try:
            with open(AUDIT_LOG_FILE, "r") as f:
                return json.load(f)
        except:
            return {"logs": []}
    return {"logs": []}

def save_audit_logs(data):
    try:
        with open(AUDIT_LOG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except:
        pass

def add_audit_log(action, admin_user, details=""):
    """Add entry to audit log."""
    audit = load_audit_logs()
    audit["logs"].append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "admin": admin_user,
        "details": details,
        "id": secrets.token_hex(8)
    })
    # Keep last 500 logs
    if len(audit["logs"]) > 500:
        audit["logs"] = audit["logs"][-500:]
    save_audit_logs(audit)

# ========== DB STRUCTURE ==========
def load_db():
    with db_lock:
        default = {
            "users": {}, 
            "start_times": {}, 
            "themes": {},
            "global_settings": {
                "maintenance_mode": False,
                "default_theme_color": "#00ffff",
                "max_upload_size_mb": 100,
                "auto_backup": False,
                "session_timeout_minutes": 60
            },
            "api_keys": [],
            "admin": {
                "username": "JUBARAJ", 
                "password": "098765",
                "api_key": generate_random_api_key(64),
                "api_key_id": generate_readable_api_id(),
                "last_login": None,
                "session_id": None
            },
            "broadcast_history": [],
            "login_attempts": []
        }
        if not os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "w") as f: 
                    json.dump(default, f, indent=4)
            except Exception as e:
                print(f"Error creating default DB: {e}")
            return default
            
        with open(DB_FILE, "r") as f:
            try:
                data = json.load(f)
                if "users" not in data: data["users"] = {}
                if "start_times" not in data: data["start_times"] = {}
                if "themes" not in data: data["themes"] = {}
                if "admin" not in data: data["admin"] = default["admin"]
                if "api_keys" not in data: data["api_keys"] = []
                if "broadcast_history" not in data: data["broadcast_history"] = []
                if "login_attempts" not in data: data["login_attempts"] = []
                if "global_settings" not in data: 
                    data["global_settings"] = default["global_settings"]
                else:
                    for k, v in default["global_settings"].items():
                        if k not in data["global_settings"]:
                            data["global_settings"][k] = v
                # Ensure admin has api_key_id
                if "api_key_id" not in data["admin"]:
                    data["admin"]["api_key_id"] = generate_readable_api_id()
                return data
            except Exception as e:
                print(f"DB Read Error: {e}")
                return default

def save_db(data):
    with db_lock:
        try:
            temp_db = DB_FILE + ".tmp"
            with open(temp_db, "w") as f:
                json.dump(data, f, indent=4)
            os.replace(temp_db, DB_FILE)
            return True
        except Exception as e:
            print(f"Local DB Save Error: {e}")
            return False

# ========== EXPIRY TRACKER & AUTO-TERMINATION ==========
def stop_and_clean_user(user_name):
    db = load_db()
    
    # Process Killing
    for key, p in list(processes.items()):
        if key[0] == user_name:
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
            t_key = f"{user_name}_{key[1]}_{key[2]}"
            if t_key in db.get("start_times", {}): 
                del db["start_times"][t_key]
                
    # Local Files Deletion
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
        except Exception as e:
            print(f"Error deleting user directory: {e}")
            
    # Firebase Storage Deletion
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blobs = bucket.list_blobs(prefix=f"backups/{user_name}/")
            for blob in blobs:
                blob.delete()
        except Exception as e:
            print(f"Firebase clean error: {e}")
            
    # Database Cleanup
    if user_name in db.get("themes", {}):
        del db["themes"][user_name]
    if user_name in db["users"]:
        del db["users"][user_name]
        
    save_db(db)

def enforcement_loop():
    while True:
        try:
            db = load_db()
            now = time.time() 
            users_to_clean = []
            
            for username, info in list(db["users"].items()):
                if info.get("plan_type") == "permanent":
                    if info.get("status") != "active":
                        db["users"][username]["status"] = "active"
                        save_db(db)
                    continue
                    
                expiry_str = info.get("expiry")
                if expiry_str:
                    try:
                        if "T" in expiry_str:
                            expiry_dt = datetime.strptime(expiry_str[:19], "%Y-%m-%dT%H:%M:%S") if len(expiry_str) > 16 else datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M")
                        else:
                            expiry_dt = datetime.strptime(expiry_str[:19], "%Y-%m-%d %H:%M:%S") if len(expiry_str) > 16 else datetime.strptime(expiry_str, "%Y-%m-%d %H:%M")
                        
                        expiry_ts = expiry_dt.timestamp()
                    except Exception as parse_err:
                        print(f"Date Parse Error for {username}: {parse_err}")
                        continue

                    if now > expiry_ts:
                        print(f"[SYSTEM] User {username} expired. Cleaning up.")
                        users_to_clean.append(username)

            for username in users_to_clean:
                stop_and_clean_user(username)
                
        except Exception as e:
            print(f"Enforcement Loop Error: {e}")
        time.sleep(5)

threading.Thread(target=enforcement_loop, daemon=True).start()

# ========== LOGIN HTML ==========
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LOGIN | YUVI HOSTING SECURE</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700;900&family=Rajdhani:wght@300;400;600;700&family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root { --bg: #03050a; --primary: #00ffff; --sec: #7000ff; --danger: #ff1744; --success: #00e676; }
        body { 
            background: var(--bg); 
            color: white; 
            font-family: 'Orbitron', sans-serif; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
            min-height: 100vh; 
            margin: 0; 
            overflow: hidden; 
            padding: 15px;
            position: relative;
        }
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: 
                radial-gradient(ellipse at 20% 50%, rgba(112,0,255,0.08) 0%, transparent 60%),
                radial-gradient(ellipse at 80% 50%, rgba(0,255,255,0.06) 0%, transparent 60%),
                repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,255,0.015) 2px, rgba(0,255,255,0.015) 4px);
            pointer-events: none;
            z-index: 0;
        }
        .scanlines {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.15) 2px, rgba(0,0,0,0.15) 4px);
            pointer-events: none;
            z-index: 1;
        }
        .login-box-wrapper { 
            position: relative; 
            z-index: 10;
            width: 100%; 
            max-width: 460px; 
            padding: 2px; 
            border-radius: 20px; 
            overflow: hidden; 
            background: linear-gradient(45deg, var(--sec), var(--primary), var(--sec));
            background-size: 300% 300%;
            animation: gradientBorder 4s ease-in-out infinite;
            box-shadow: 0 0 60px rgba(0,255,255,0.1), 0 0 120px rgba(112,0,255,0.05);
        }
        @keyframes gradientBorder { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
        .login-card { 
            position: relative;
            z-index: 10; 
            background: rgba(6, 10, 22, 0.98); 
            padding: 45px 35px; 
            border-radius: 19px; 
            width: 100%; 
            text-align: center; 
            backdrop-filter: blur(20px);
            border: 1px solid rgba(0,255,255,0.05);
        }
        .lock-container { 
            width: 90px; 
            height: 90px; 
            background: rgba(0, 255, 255, 0.05); 
            border-radius: 50%; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            margin: 0 auto 20px; 
            border: 2px solid rgba(0,255,255,0.2); 
            box-shadow: 0 0 30px rgba(0,255,255,0.1), inset 0 0 30px rgba(0,255,255,0.05);
            position: relative;
        }
        .lock-container::after {
            content: '';
            position: absolute;
            top: -5px; left: -5px; right: -5px; bottom: -5px;
            border-radius: 50%;
            border: 1px solid rgba(112,0,255,0.2);
            animation: pulseRing 2s ease-in-out infinite;
        }
        @keyframes pulseRing { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.5; } }
        .lock-icon { font-size: 36px; color: var(--primary); }
        h2 { 
            font-size: 20px; 
            margin-bottom: 8px; 
            letter-spacing: 3px; 
            text-transform: uppercase; 
            background: linear-gradient(135deg, #fff, var(--primary)); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
        }
        .sub-title {
            font-family: 'Rajdhani', sans-serif;
            font-size: 12px;
            color: rgba(255,255,255,0.4);
            letter-spacing: 4px;
            margin-bottom: 28px;
            text-transform: uppercase;
        }
        input, select { 
            width: 100%; 
            padding: 15px 16px; 
            margin: 8px 0; 
            border-radius: 10px; 
            border: 1px solid rgba(255,255,255,0.06); 
            background: rgba(255,255,255,0.03); 
            color: #fff; 
            outline: none; 
            font-size: 13px;
            font-family: 'Rajdhani', sans-serif;
            transition: all 0.3s ease;
        }
        input:focus, select:focus { 
            border-color: var(--primary); 
            box-shadow: 0 0 15px rgba(0,255,255,0.1);
            background: rgba(0,255,255,0.03);
        }
        select option { background: #0a0e1a; }
        button { 
            width: 100%; 
            padding: 15px; 
            border-radius: 10px; 
            border: none; 
            background: linear-gradient(135deg, var(--sec), var(--primary)); 
            color: #fff; 
            font-family: 'Orbitron', sans-serif;
            font-weight: 700;
            cursor: pointer; 
            margin-top: 18px; 
            text-transform: uppercase; 
            letter-spacing: 2px;
            font-size: 12px;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0,255,255,0.2);
        }
        button::after {
            content: '';
            position: absolute;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255,255,255,0.05), transparent);
            transform: rotate(45deg);
            transition: all 0.5s ease;
        }
        button:hover::after { left: 100%; }
        .error-msg { 
            color: var(--danger); 
            font-size: 12px; 
            margin-top: 12px; 
            display: block; 
            font-weight: 600;
            font-family: 'Rajdhani', sans-serif;
            letter-spacing: 1px;
            background: rgba(255,23,68,0.08);
            padding: 8px 12px;
            border-radius: 6px;
            border: 1px solid rgba(255,23,68,0.15);
        }
        .status-dot {
            display: inline-block;
            width: 6px; height: 6px;
            border-radius: 50%;
            background: var(--success);
            margin-right: 6px;
            animation: blink 1.5s ease-in-out infinite;
        }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
        .footer-text {
            font-family: 'Rajdhani', sans-serif;
            font-size: 10px;
            color: rgba(255,255,255,0.15);
            margin-top: 20px;
            letter-spacing: 2px;
        }
    </style>
</head>
<body>
    <div class="scanlines"></div>
    <div class="login-box-wrapper">
        <div class="login-card">
            <div class="lock-container"><i class="fa-solid fa-user-shield lock-icon"></i></div>
            <h2>🔐 SECURE ACCESS</h2>
            <div class="sub-title"><span class="status-dot"></span> SYSTEM READY — AUTHENTICATION REQUIRED</div>
            {% if error %}<span class="error-msg"><i class="fa-solid fa-triangle-exclamation"></i> {{ error }}</span>{% endif %}
            <form method="post" action="/login">
                <select name="login_type">
                    <option value="user">👤 USER ACCESS</option>
                    <option value="admin">⚡ ADMIN ROOT ACCESS</option>
                </select>
                <input type="text" name="username" placeholder="USERNAME / IDENTIFIER" required>
                <input type="password" name="password" placeholder="PASSWORD / SECRET KEY" required>
                <button type="submit"><i class="fa-solid fa-lock-open"></i> AUTHENTICATE & ENTER</button>
            </form>
            <div class="footer-text">YUVI HOSTING v3.0 // SECURE NODE</div>
        </div>
    </div>
</body>
</html>
'''

# ========== PREMIUM HACKER-STYLE OWNER PANEL HTML ==========
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>👑 OWNER PANEL | YUVI HOSTING v3</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700;900&family=Rajdhani:wght@300;400;600;700&family=Fira+Code:wght@400;600&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root { 
            --bg-dark: #03050a; 
            --panel-bg: rgba(8, 12, 24, 0.95); 
            --card-bg: rgba(10, 16, 32, 0.9); 
            --neon-blue: #00ffff; 
            --neon-purple: #7000ff; 
            --neon-green: #00e676;
            --neon-red: #ff1744;
            --neon-yellow: #ffd740;
            --text-light: #e8eaf6; 
            --border-light: rgba(0, 255, 255, 0.08);
            --cyber-glow: 0 0 20px rgba(0,255,255,0.05);
        }
        html { scroll-behavior: smooth; }
        body { 
            background: var(--bg-dark); 
            color: var(--text-light); 
            font-family: 'Orbitron', sans-serif; 
            padding: 0;
            margin: 0;
            min-height: 100vh;
            position: relative;
            overflow-x: hidden;
        }
        /* Hacker BG Overlay */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: 
                radial-gradient(ellipse at 15% 30%, rgba(112,0,255,0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 85% 70%, rgba(0,255,255,0.04) 0%, transparent 50%),
                repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,255,255,0.008) 3px, rgba(0,255,255,0.008) 4px);
            pointer-events: none;
            z-index: 0;
        }
        .scanlines-overlay {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.1) 2px, rgba(0,0,0,0.1) 4px);
            pointer-events: none;
            z-index: 1;
        }
        
        /* TOP NAVIGATION BAR */
        .top-bar {
            position: fixed;
            top: 0; left: 0; right: 0;
            z-index: 100;
            background: rgba(3, 5, 10, 0.95);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(0,255,255,0.08);
            padding: 10px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            height: 56px;
        }
        .top-bar .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 2px;
            background: linear-gradient(135deg, #fff, var(--neon-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .top-bar .brand i { -webkit-text-fill-color: initial; color: var(--neon-blue); }
        .top-bar .status-ticker {
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px;
            color: var(--neon-green);
            letter-spacing: 1px;
        }
        .top-bar .status-ticker i { margin-right: 5px; }
        .top-bar .admin-badge {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .top-bar .admin-badge span {
            font-family: 'Rajdhani', sans-serif;
            font-size: 12px;
            color: rgba(255,255,255,0.5);
        }
        .btn-logout-top {
            padding: 6px 14px;
            border-radius: 6px;
            border: 1px solid rgba(255,23,68,0.3);
            background: rgba(255,23,68,0.08);
            color: #f87171;
            font-size: 10px;
            font-family: 'Orbitron', sans-serif;
            cursor: pointer;
            text-decoration: none;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
        }
        .btn-logout-top:hover {
            background: rgba(255,23,68,0.2);
            border-color: var(--neon-red);
        }
        
        /* SIDEBAR NAV */
        .sidebar {
            position: fixed;
            top: 56px; left: 0; bottom: 0;
            width: 220px;
            z-index: 99;
            background: rgba(3, 5, 10, 0.95);
            backdrop-filter: blur(20px);
            border-right: 1px solid rgba(0,255,255,0.06);
            padding: 15px 0;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(0,255,255,0.1) transparent;
        }
        .sidebar::-webkit-scrollbar { width: 3px; }
        .sidebar::-webkit-scrollbar-thumb { background: rgba(0,255,255,0.2); border-radius: 10px; }
        .sidebar .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 11px 18px;
            color: rgba(255,255,255,0.45);
            text-decoration: none;
            font-size: 11px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            font-weight: 500;
            border-left: 3px solid transparent;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        .sidebar .nav-item:hover, .sidebar .nav-item.active {
            color: var(--neon-blue);
            background: rgba(0,255,255,0.03);
            border-left-color: var(--neon-blue);
        }
        .sidebar .nav-item i { width: 18px; text-align: center; font-size: 13px; }
        .sidebar .nav-divider {
            height: 1px;
            background: rgba(0,255,255,0.04);
            margin: 8px 15px;
        }
        .sidebar .nav-section-label {
            padding: 12px 18px 5px;
            font-size: 9px;
            color: rgba(255,255,255,0.15);
            letter-spacing: 2px;
            text-transform: uppercase;
            font-family: 'Rajdhani', sans-serif;
        }
        
        /* MAIN CONTENT */
        .main-content {
            margin-left: 220px;
            margin-top: 56px;
            padding: 25px 30px 60px;
            position: relative;
            z-index: 2;
        }
        
        /* SECTION STYLING */
        .section-wrapper {
            margin-bottom: 35px;
            scroll-margin-top: 70px;
        }
        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 18px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(0,255,255,0.06);
        }
        .section-header .section-title {
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--text-light);
        }
        .section-header .section-title i { color: var(--neon-blue); font-size: 16px; }
        .section-header .section-badge {
            font-family: 'Rajdhani', sans-serif;
            font-size: 10px;
            color: rgba(255,255,255,0.25);
            letter-spacing: 1px;
            background: rgba(0,255,255,0.04);
            padding: 3px 10px;
            border-radius: 12px;
            border: 1px solid rgba(0,255,255,0.06);
        }
        
        /* GRID SYSTEM */
        .grid-2 { display: grid; grid-template-columns: 1fr; gap: 16px; }
        .grid-3 { display: grid; grid-template-columns: 1fr; gap: 16px; }
        .grid-4 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        @media(min-width: 768px) { 
            .grid-2 { grid-template-columns: 1fr 1fr; }
            .grid-3 { grid-template-columns: 1fr 1fr 1fr; }
            .grid-4 { grid-template-columns: 1fr 1fr; }
        }
        @media(min-width: 1024px) {
            .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
        }
        
        /* PREMIUM CARDS */
        .cyber-card {
            background: var(--card-bg);
            border: 1px solid var(--border-light);
            border-radius: 14px;
            padding: 20px;
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
            box-shadow: var(--cyber-glow);
        }
        .cyber-card:hover {
            border-color: rgba(0,255,255,0.15);
            box-shadow: 0 0 30px rgba(0,255,255,0.04);
            transform: translateY(-1px);
        }
        .cyber-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 3px;
            height: 100%;
            background: linear-gradient(to bottom, var(--neon-purple), var(--neon-blue));
            opacity: 0.5;
        }
        .cyber-card .card-label {
            font-family: 'Rajdhani', sans-serif;
            font-size: 10px;
            color: rgba(255,255,255,0.3);
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .cyber-card .card-label i { color: var(--neon-blue); }
        .cyber-card .card-title {
            font-size: 14px;
            font-weight: 700;
            color: #fff;
            margin-bottom: 12px;
        }
        
        /* METRIC BOXES */
        .metric-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .metric-box {
            background: rgba(0,0,0,0.3);
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.03);
            text-align: center;
        }
        .metric-box .metric-value {
            font-size: 22px;
            font-weight: 700;
            color: #fff;
            font-family: 'Share Tech Mono', monospace;
        }
        .metric-box .metric-value.green { color: var(--neon-green); }
        .metric-box .metric-value.blue { color: var(--neon-blue); }
        .metric-box .metric-value.purple { color: var(--neon-purple); }
        .metric-box .metric-value.red { color: var(--neon-red); }
        .metric-box .metric-value.yellow { color: var(--neon-yellow); }
        .metric-box .metric-label {
            font-size: 9px;
            color: rgba(255,255,255,0.3);
            font-family: 'Rajdhani', sans-serif;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 4px;
        }
        
        /* FORM ELEMENTS */
        .input-group { display: flex; flex-direction: column; gap: 10px; }
        .input-row { display: flex; gap: 10px; align-items: center; }
        input, select, textarea { 
            width: 100%; 
            padding: 11px 14px; 
            border-radius: 8px; 
            border: 1px solid rgba(255,255,255,0.06); 
            background: rgba(0,0,0,0.4); 
            color: #fff; 
            outline: none; 
            font-size: 12px;
            font-family: 'Rajdhani', sans-serif;
            transition: all 0.25s ease;
        }
        input:focus, select:focus, textarea:focus {
            border-color: var(--neon-blue);
            box-shadow: 0 0 12px rgba(0,255,255,0.08);
            background: rgba(0,255,255,0.02);
        }
        select option { background: #080c18; }
        textarea { resize: vertical; min-height: 70px; font-family: 'Share Tech Mono', monospace; }
        label {
            font-family: 'Rajdhani', sans-serif;
            font-size: 11px;
            color: rgba(255,255,255,0.5);
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        
        /* BUTTONS */
        .btn { 
            padding: 10px 18px; 
            border-radius: 8px; 
            border: none; 
            font-weight: 600; 
            cursor: pointer; 
            text-align: center; 
            display: inline-flex; 
            align-items: center; 
            justify-content: center; 
            gap: 8px; 
            text-decoration: none;
            transition: all 0.3s ease;
            text-transform: uppercase;
            font-size: 10px;
            letter-spacing: 1.5px;
            font-family: 'Orbitron', sans-serif;
            position: relative;
            overflow: hidden;
        }
        .btn::after {
            content: '';
            position: absolute;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255,255,255,0.03), transparent);
            transform: rotate(45deg);
            transition: all 0.5s ease;
        }
        .btn:hover::after { left: 100%; }
        .btn-primary { 
            background: linear-gradient(135deg, var(--neon-purple), var(--neon-blue)); 
            color: #fff; 
            box-shadow: 0 4px 15px rgba(0,255,255,0.1);
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 6px 25px rgba(0,255,255,0.2); }
        .btn-danger { background: rgba(255,23,68,0.12); color: var(--neon-red); border: 1px solid rgba(255,23,68,0.2); }
        .btn-danger:hover { background: var(--neon-red); color: #fff; transform: translateY(-2px); }
        .btn-warning { background: rgba(255,215,64,0.1); color: var(--neon-yellow); border: 1px solid rgba(255,215,64,0.2); }
        .btn-warning:hover { background: var(--neon-yellow); color: #000; transform: translateY(-2px); }
        .btn-success { background: rgba(0,230,118,0.1); color: var(--neon-green); border: 1px solid rgba(0,230,118,0.2); }
        .btn-success:hover { background: var(--neon-green); color: #000; transform: translateY(-2px); }
        .btn-ghost { background: transparent; color: rgba(255,255,255,0.4); border: 1px solid rgba(255,255,255,0.06); }
        .btn-ghost:hover { color: #fff; border-color: rgba(255,255,255,0.15); }
        .btn-sm { padding: 6px 12px; font-size: 9px; }
        .btn-xs { padding: 4px 8px; font-size: 8px; border-radius: 5px; }
        .btn-block { width: 100%; }
        
        /* USER ITEM */
        .user-item { 
            background: rgba(0,0,0,0.3); 
            border-radius: 10px; 
            padding: 14px 16px; 
            margin-bottom: 10px; 
            border: 1px solid rgba(255,255,255,0.02);
            transition: all 0.3s ease;
        }
        .user-item:hover { border-color: rgba(112,0,255,0.2); }
        .user-info { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
        .username { font-weight: 600; font-size: 12px; color: #fff; display: flex; align-items: center; gap: 8px; }
        .status-badge { 
            padding: 3px 10px; 
            border-radius: 10px; 
            font-size: 8px; 
            font-weight: 700; 
            letter-spacing: 0.5px; 
            text-transform: uppercase; 
            font-family: 'Rajdhani', sans-serif;
        }
        .status-active { background: rgba(0,230,118,0.1); color: var(--neon-green); border: 1px solid rgba(0,230,118,0.15); }
        .status-expired { background: rgba(255,23,68,0.1); color: var(--neon-red); border: 1px solid rgba(255,23,68,0.15); }
        
        /* BADGE / TAG */
        .tag {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 8px;
            font-weight: 600;
            font-family: 'Rajdhani', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .tag-blue { background: rgba(0,255,255,0.08); color: var(--neon-blue); border: 1px solid rgba(0,255,255,0.1); }
        .tag-purple { background: rgba(112,0,255,0.08); color: var(--neon-purple); border: 1px solid rgba(112,0,255,0.1); }
        .tag-green { background: rgba(0,230,118,0.08); color: var(--neon-green); border: 1px solid rgba(0,230,118,0.1); }
        
        /* API KEY DISPLAY */
        .api-key-box {
            background: rgba(0,0,0,0.5);
            border: 1px solid rgba(0,255,255,0.06);
            border-radius: 8px;
            padding: 12px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px;
            color: var(--neon-green);
            word-break: break-all;
            position: relative;
            line-height: 1.6;
        }
        .api-key-box .copy-btn {
            position: absolute;
            top: 8px; right: 8px;
            padding: 4px 8px;
            border-radius: 4px;
            border: none;
            background: rgba(0,255,255,0.1);
            color: var(--neon-blue);
            cursor: pointer;
            font-size: 10px;
            transition: all 0.3s ease;
        }
        .api-key-box .copy-btn:hover { background: rgba(0,255,255,0.2); }
        
        /* LOG ENTRY */
        .log-entry {
            padding: 8px 10px;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            font-family: 'Share Tech Mono', monospace;
            font-size: 10px;
            color: rgba(255,255,255,0.5);
            display: flex;
            gap: 10px;
        }
        .log-entry .log-time { color: rgba(0,255,255,0.4); white-space: nowrap; }
        .log-entry .log-action { color: var(--neon-blue); }
        .log-entry .log-admin { color: var(--neon-purple); }
        
        /* CODE BLOCK */
        pre.code-block {
            background: rgba(0,0,0,0.5);
            color: var(--neon-green);
            padding: 14px;
            border-radius: 8px;
            font-size: 10px;
            overflow-x: auto;
            border: 1px solid rgba(0,255,255,0.06);
            font-family: 'Share Tech Mono', monospace;
            line-height: 1.6;
        }
        
        /* PROGRESS BAR */
        .progress-bar {
            height: 4px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            overflow: hidden;
            margin-top: 5px;
        }
        .progress-bar .fill {
            height: 100%;
            border-radius: 4px;
            background: linear-gradient(90deg, var(--neon-purple), var(--neon-blue));
            transition: width 0.5s ease;
        }
        
        /* TOGGLE SWITCH */
        .toggle-switch {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
        }
        .toggle-switch input { display: none; }
        .toggle-track {
            width: 40px; height: 20px;
            background: rgba(255,255,255,0.08);
            border-radius: 20px;
            position: relative;
            transition: all 0.3s ease;
        }
        .toggle-track::after {
            content: '';
            position: absolute;
            top: 2px; left: 2px;
            width: 16px; height: 16px;
            background: #fff;
            border-radius: 50%;
            transition: all 0.3s ease;
        }
        .toggle-switch input:checked + .toggle-track {
            background: var(--neon-blue);
        }
        .toggle-switch input:checked + .toggle-track::after {
            left: 22px;
            background: #000;
        }
        
        /* NOTIFICATION TOAST */
        .toast-container {
            position: fixed;
            top: 70px; right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .toast {
            padding: 12px 18px;
            border-radius: 8px;
            font-family: 'Rajdhani', sans-serif;
            font-size: 12px;
            font-weight: 600;
            color: #fff;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            animation: slideIn 0.3s ease;
            border: 1px solid rgba(255,255,255,0.06);
        }
        .toast.success { background: rgba(0,230,118,0.2); border-color: rgba(0,230,118,0.2); }
        .toast.error { background: rgba(255,23,68,0.2); border-color: rgba(255,23,68,0.2); }
        .toast.info { background: rgba(0,255,255,0.12); border-color: rgba(0,255,255,0.12); }
        @keyframes slideIn { from { transform: translateX(100px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

        /* EMPTY STATE */
        .empty-state {
            text-align: center;
            padding: 30px 20px;
            color: rgba(255,255,255,0.15);
            font-family: 'Rajdhani', sans-serif;
            font-size: 13px;
        }
        .empty-state i { font-size: 32px; margin-bottom: 10px; opacity: 0.3; display: block; }
        
        /* RESPONSIVE */
        @media(max-width: 768px) {
            .sidebar { display: none; }
            .main-content { margin-left: 0; padding: 20px 15px; }
            .top-bar .status-ticker { display: none; }
        }
        
        /* Scrollbar */
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(0,255,255,0.15); border-radius: 10px; }
        
        /* Glitch text effect */
        .glitch-text {
            position: relative;
            display: inline-block;
        }
        .glitch-text::before, .glitch-text::after {
            content: attr(data-text);
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 100%;
            opacity: 0;
        }
        .glitch-text:hover::before {
            animation: glitch1 0.3s ease;
            color: var(--neon-red);
            opacity: 0.5;
        }
        .glitch-text:hover::after {
            animation: glitch2 0.3s ease;
            color: var(--neon-blue);
            opacity: 0.5;
        }
        @keyframes glitch1 { 0% { transform: translate(0); } 20% { transform: translate(-2px, 2px); } 40% { transform: translate(2px, -1px); } 60% { transform: translate(-1px, 1px); } 80% { transform: translate(1px, -2px); } 100% { transform: translate(0); } }
        @keyframes glitch2 { 0% { transform: translate(0); } 20% { transform: translate(2px, -2px); } 40% { transform: translate(-2px, 1px); } 60% { transform: translate(1px, -1px); } 80% { transform: translate(-1px, 2px); } 100% { transform: translate(0); } }
    </style>
</head>
<body>
    <div class="scanlines-overlay"></div>
    <div class="toast-container" id="toastContainer"></div>
    
    <!-- TOP BAR -->
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
    
    <!-- SIDEBAR -->
    <div class="sidebar">
        <div class="nav-section-label">MONITORING</div>
        <a href="#sec-overview" class="nav-item active"><i class="fa-solid fa-gauge-high"></i> System Overview</a>
        <a href="#sec-health" class="nav-item"><i class="fa-solid fa-heart-pulse"></i> Health & Uptime</a>
        
        <div class="nav-divider"></div>
        <div class="nav-section-label">MANAGEMENT</div>
        <a href="#sec-users" class="nav-item"><i class="fa-solid fa-users"></i> User Management</a>
        <a href="#sec-broadcast" class="nav-item"><i class="fa-solid fa-bullhorn"></i> Broadcast Center</a>
        <a href="#sec-backup" class="nav-item"><i class="fa-solid fa-cloud-arrow-up"></i> Backup & Restore</a>
        
        <div class="nav-divider"></div>
        <div class="nav-section-label">SECURITY</div>
        <a href="#sec-api" class="nav-item"><i class="fa-solid fa-key"></i> API & Integration</a>
        <a href="#sec-auth" class="nav-item"><i class="fa-solid fa-shield-halved"></i> Auth & Security</a>
        <a href="#sec-logs" class="nav-item"><i class="fa-solid fa-list"></i> Audit Logs</a>
        
        <div class="nav-divider"></div>
        <div class="nav-section-label">CONTROLS</div>
        <a href="#sec-maintenance" class="nav-item"><i class="fa-solid fa-screwdriver-wrench"></i> Maintenance</a>
        <a href="#sec-settings" class="nav-item"><i class="fa-solid fa-gear"></i> Global Settings</a>
        <a href="#sec-directory" class="nav-item"><i class="fa-solid fa-address-book"></i> User Directory</a>
    </div>
    
    <!-- MAIN CONTENT -->
    <div class="main-content">
        <!-- ===================== SECTION 1: SYSTEM OVERVIEW ===================== -->
        <div class="section-wrapper" id="sec-overview">
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
        </div>
        
        <!-- ===================== SECTION 2: HEALTH & UPTIME ===================== -->
        <div class="section-wrapper" id="sec-health">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-heart-pulse"></i> Health & Uptime Monitor</div>
                <span class="section-badge">REALTIME STATUS</span>
            </div>
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
        
        <!-- ===================== SECTION 3: USER MANAGEMENT ===================== -->
        <div class="section-wrapper" id="sec-users">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-users"></i> User Management</div>
                <span class="section-badge">CREATE / DELETE / MANAGE</span>
            </div>
            <div class="grid-2">
                <!-- CREATE USER -->
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-user-plus"></i> Create New User</div>
                    <form action="/admin/create_user" method="post" class="input-group">
                        <input type="text" name="username" placeholder="Username" required>
                        <input type="password" name="password" placeholder="Password" required>
                        <select name="plan_type" onchange="toggleExpiry(this.value)">
                            <option value="time_bound">⏱ Time Bound (Auto Deletion)</option>
                            <option value="permanent">♾ Permanent (Lifetime)</option>
                        </select>
                        <div id="exp_input_wrapper">
                            <label>EXPIRY DATE & TIME:</label>
                            <input type="datetime-local" id="expiry_date_input" name="expiry" required>
                        </div>
                        <button type="submit" class="btn btn-primary btn-block"><i class="fa-solid fa-plus-circle"></i> Create Account</button>
                    </form>
                </div>
                <!-- BULK & QUICK ACTIONS -->
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-bolt"></i> Quick Actions</div>
                    <div style="display:flex; flex-direction:column; gap:10px;">
                        <a href="/admin/export_users" class="btn btn-success btn-block"><i class="fa-solid fa-file-export"></i> Export All Users (JSON)</a>
                        <a href="/admin/kill_all_processes" class="btn btn-danger btn-block" onclick="return confirm('⚠ Kill ALL running user processes?')"><i class="fa-solid fa-skull"></i> Force Kill All Processes</a>
                        <a href="/admin/delete_all_expired" class="btn btn-warning btn-block" onclick="return confirm('⚠ Delete ALL expired users?')"><i class="fa-solid fa-broom"></i> Purge All Expired Users</a>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 4: BROADCAST CENTER ===================== -->
        <div class="section-wrapper" id="sec-broadcast">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-bullhorn"></i> Broadcast Center</div>
                <span class="section-badge">GLOBAL & TARGETED ALERTS</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-globe"></i> Send Broadcast</div>
                    <form action="/admin/broadcast" method="post" class="input-group">
                        <select name="target_user">
                            <option value="ALL_USERS">🌍 GLOBAL BROADCAST — ALL USERS</option>
                            {% for u_name in users.keys() %}
                            <option value="{{ u_name }}">📡 Direct: {{ u_name }}</option>
                            {% endfor %}
                        </select>
                        <textarea name="message" rows="3" placeholder="Enter alert message..." required></textarea>
                        <button type="submit" class="btn btn-primary btn-block"><i class="fa-solid fa-paper-plane"></i> Send Broadcast</button>
                    </form>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-clock-rotate-left"></i> Broadcast History</div>
                    {% if broadcast_history %}
                        {% for b in broadcast_history[-10:]|reverse %}
                        <div class="log-entry">
                            <span class="log-time">{{ b.time }}</span>
                            <span class="log-action">{{ b.target[:20] }}{% if b.target|length > 20 %}...{% endif %}</span>
                            <span style="color:rgba(255,255,255,0.3);">—</span>
                            <span style="color:var(--neon-green);">{{ b.msg[:30] }}{% if b.msg|length > 30 %}...{% endif %}</span>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="empty-state"><i class="fa-solid fa-inbox"></i> No broadcast history yet</div>
                    {% endif %}
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 5: BACKUP & RESTORE ===================== -->
        <div class="section-wrapper" id="sec-backup">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-cloud-arrow-up"></i> Backup & Restore</div>
                <span class="section-badge">DATA PROTECTION</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-download"></i> Manual Backup</div>
                    <div style="display:flex; flex-direction:column; gap:10px;">
                        <a href="/admin/backup_db" class="btn btn-primary btn-block"><i class="fa-solid fa-database"></i> Backup Database</a>
                        <a href="/admin/backup_all" class="btn btn-success btn-block"><i class="fa-solid fa-box"></i> Full System Backup (DB + Uploads)</a>
                        <form action="/admin/restore_backup" method="post" enctype="multipart/form-data" class="input-group" style="margin-top:5px;">
                            <label>Restore From Backup File:</label>
                            <input type="file" name="backup_file" accept=".zip,.json" required>
                            <button type="submit" class="btn btn-warning btn-block"><i class="fa-solid fa-rotate-left"></i> Restore Backup</button>
                        </form>
                    </div>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-fire"></i> Firebase Cloud Backups</div>
                    {% if firebase_active %}
                        <p style="font-family:'Rajdhani'; font-size:12px; color:var(--neon-green); margin-bottom:10px;">
                            <i class="fa-solid fa-check-circle"></i> Firebase Connected & Active
                        </p>
                        <a href="/admin/firebase_sync" class="btn btn-primary btn-block"><i class="fa-solid fa-arrows-rotate"></i> Sync to Firebase Now</a>
                    {% else %}
                        <p style="font-family:'Rajdhani'; font-size:12px; color:rgba(255,255,255,0.3); margin-bottom:10px;">
                            <i class="fa-solid fa-circle-exclamation"></i> Firebase Not Configured
                        </p>
                        <span style="font-size:10px; color:rgba(255,255,255,0.2);">Set FIREBASE_CREDS env variable to enable</span>
                    {% endif %}
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 6: API & INTEGRATION ===================== -->
        <div class="section-wrapper" id="sec-api">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-key"></i> API & Integration</div>
                <span class="section-badge">RANDOM SECURE KEYS</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-shield"></i> Current API Credentials</div>
                    <div style="margin-bottom:12px;">
                        <label style="font-size:9px; color:rgba(255,255,255,0.2);">API KEY ID:</label>
                        <div class="api-key-box" style="font-size:14px; color:var(--neon-blue); margin-top:3px;">
                            {{ admin_creds.api_key_id }}
                        </div>
                    </div>
                    <div>
                        <label style="font-size:9px; color:rgba(255,255,255,0.2);">SECRET API KEY (auto-generated random):</label>
                        <div class="api-key-box" style="margin-top:3px;">
                            {{ admin_creds.api_key }}
                            <button class="copy-btn" onclick="copyToClipboard('{{ admin_creds.api_key }}')"><i class="fa-regular fa-clipboard"></i> COPY</button>
                        </div>
                    </div>
                    <div style="margin-top:12px; display:flex; gap:8px;">
                        <a href="/admin/regenerate_api_key" class="btn btn-warning" style="flex:1;"><i class="fa-solid fa-rotate"></i> Regenerate API Key</a>
                        <a href="/admin/regenerate_api_key_id" class="btn btn-ghost" style="flex:1;"><i class="fa-solid fa-arrows-rotate"></i> New ID</a>
                    </div>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-book"></i> API Documentation</div>
                    <pre class="code-block">
# === BOT API ENDPOINTS ===

# Create User:
POST /api/admin/create_user
Headers: {"Content-Type": "application/json"}
Body: {
  "api_key": "{{ admin_creds.api_key }}",
  "username": "user123",
  "password": "pass123",
  "plan_type": "time_bound",
  "expiry": "2026-12-31T23:59"
}

# Delete User:
POST /api/admin/delete_user
Body: {"api_key": "...", "username": "user123"}

# List Users:
POST /api/admin/list_users
Body: {"api_key": "..."}

# Response: {"status": "success", ...}
</pre>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 7: AUTH & SECURITY ===================== -->
        <div class="section-wrapper" id="sec-auth">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-shield-halved"></i> Auth & Security</div>
                <span class="section-badge">ADMIN CREDENTIALS</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-lock"></i> Change Admin Credentials</div>
                    <form action="/admin/update_creds" method="post" class="input-group">
                        <label>New Admin Username:</label>
                        <input type="text" name="admin_user" value="{{ admin_creds.username }}" placeholder="Admin Username" required>
                        <label>New Admin Password:</label>
                        <input type="password" name="admin_pass" placeholder="Enter New Password" required>
                        <div style="display:flex; gap:8px;">
                            <button type="submit" class="btn btn-primary" style="flex:1;"><i class="fa-solid fa-save"></i> Save Credentials</button>
                            <a href="/admin/reset_session" class="btn btn-warning" style="flex:1;"><i class="fa-solid fa-rotate"></i> Reset Sessions</a>
                        </div>
                    </form>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-list-check"></i> Security Status</div>
                    <div style="display:flex; flex-direction:column; gap:8px;">
                        <div class="log-entry">
                            <span class="log-time"><i class="fa-solid fa-check-circle" style="color:var(--neon-green);"></i></span>
                            <span>Session Encryption: <span style="color:var(--neon-green);">ACTIVE (AES-256)</span></span>
                        </div>
                        <div class="log-entry">
                            <span class="log-time"><i class="fa-solid fa-check-circle" style="color:var(--neon-green);"></i></span>
                            <span>API Key: <span style="color:var(--neon-green);">128-CHAR RANDOM</span></span>
                        </div>
                        <div class="log-entry">
                            <span class="log-time"><i class="fa-solid fa-clock"></i></span>
                            <span>Last Admin Login: <span style="color:var(--neon-yellow);">{{ admin_creds.last_login or 'N/A' }}</span></span>
                        </div>
                        <div class="log-entry">
                            <span class="log-time"><i class="fa-solid fa-database"></i></span>
                            <span>Total Login Attempts Tracked: <span style="color:var(--neon-blue);">{{ login_attempts_count }}</span></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 8: AUDIT LOGS ===================== -->
        <div class="section-wrapper" id="sec-logs">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-list"></i> Audit Logs</div>
                <span class="section-badge">ACTIVITY HISTORY</span>
            </div>
            <div class="cyber-card">
                <div class="card-label"><i class="fa-solid fa-clock-rotate-left"></i> Recent Admin Actions</div>
                <div style="max-height: 300px; overflow-y: auto;">
                    {% if audit_logs %}
                        {% for log in audit_logs[:50] %}
                        <div class="log-entry">
                            <span class="log-time">{{ log.timestamp }}</span>
                            <span class="log-action">{{ log.action }}</span>
                            <span style="color:rgba(255,255,255,0.2);">by</span>
                            <span class="log-admin">{{ log.admin }}</span>
                            {% if log.details %}
                            <span style="color:rgba(255,255,255,0.15);">— {{ log.details[:30] }}{% if log.details|length > 30 %}...{% endif %}</span>
                            {% endif %}
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="empty-state"><i class="fa-solid fa-inbox"></i> No audit logs recorded yet</div>
                    {% endif %}
                </div>
                <div style="margin-top:10px; display:flex; gap:10px;">
                    <a href="/admin/clear_audit_logs" class="btn btn-danger btn-sm" onclick="return confirm('Clear all audit logs?')"><i class="fa-solid fa-trash"></i> Clear Logs</a>
                    <a href="/admin/export_logs" class="btn btn-ghost btn-sm"><i class="fa-solid fa-download"></i> Export Logs</a>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 9: MAINTENANCE ===================== -->
        <div class="section-wrapper" id="sec-maintenance">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-screwdriver-wrench"></i> Maintenance & Emergency</div>
                <span class="section-badge">SYSTEM CONTROLS</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-power-off"></i> System State</div>
                    <form action="/admin/toggle_maintenance" method="post">
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
                            <span style="font-family:'Rajdhani'; font-size:13px;">Maintenance Mode</span>
                            <label class="toggle-switch">
                                <input type="checkbox" onchange="this.form.submit()" {% if maintenance_mode %}checked{% endif %}>
                                <span class="toggle-track"></span>
                            </label>
                        </div>
                        <noscript><button type="submit" class="btn btn-primary btn-block">Toggle</button></noscript>
                    </form>
                    <p style="font-family:'Rajdhani'; font-size:11px; color:{% if maintenance_mode %}var(--neon-red){% else %}var(--neon-green){% endif %};">
                        <i class="fa-solid {% if maintenance_mode %}fa-lock{% else %}fa-lock-open{% endif %}"></i>
                        Maintenance is {% if maintenance_mode %}ACTIVE — Users cannot login{% else %}INACTIVE — System is live{% endif %}
                    </p>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-bolt"></i> Emergency Controls</div>
                    <div style="display:flex; flex-direction:column; gap:10px;">
                        <a href="/admin/kill_all_processes" class="btn btn-danger btn-block" onclick="return confirm('⚠ Kill ALL running processes immediately?')">
                            <i class="fa-solid fa-skull"></i> FORCE KILL ALL PROCESSES
                        </a>
                        <a href="/admin/restart_server" class="btn btn-warning btn-block" onclick="return confirm('⚠ Restart the entire server? This will disconnect all users.')">
                            <i class="fa-solid fa-rotate"></i> RESTART SERVER
                        </a>
                        <a href="/admin/delete_all_users" class="btn btn-danger btn-block" onclick="return confirm('☠ DESTROY ALL USERS AND DATA? This cannot be undone!')">
                            <i class="fa-solid fa-bomb"></i> ☠ NUKE ALL DATA
                        </a>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 10: GLOBAL SETTINGS ===================== -->
        <div class="section-wrapper" id="sec-settings">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-gear"></i> Global Settings</div>
                <span class="section-badge">SYSTEM PREFERENCES</span>
            </div>
            <div class="grid-2">
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-sliders"></i> System Configuration</div>
                    <form action="/admin/update_settings" method="post" class="input-group">
                        <label>Default Theme Color (for new users):</label>
                        <div class="input-row">
                            <input type="color" name="default_theme_color" value="{{ global_settings.default_theme_color }}" style="width:50px; padding:4px;">
                            <input type="text" name="default_theme_color_text" value="{{ global_settings.default_theme_color }}" placeholder="#00ffff" style="flex:1;">
                        </div>
                        <label>Max Upload Size (MB):</label>
                        <input type="number" name="max_upload_size_mb" value="{{ global_settings.max_upload_size_mb }}" min="1" max="1000">
                        <label>Session Timeout (minutes):</label>
                        <input type="number" name="session_timeout_minutes" value="{{ global_settings.session_timeout_minutes }}" min="5" max="1440">
                        <button type="submit" class="btn btn-primary btn-block"><i class="fa-solid fa-floppy-disk"></i> Save Settings</button>
                    </form>
                </div>
                <div class="cyber-card">
                    <div class="card-label"><i class="fa-solid fa-palette"></i> Quick Theme Preview</div>
                    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:15px;">
                        <div style="width:35px;height:35px;border-radius:8px;background:#00ffff;border:2px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="document.getElementById('themePreview').style.background='#00ffff'"></div>
                        <div style="width:35px;height:35px;border-radius:8px;background:#7000ff;border:2px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="document.getElementById('themePreview').style.background='#7000ff'"></div>
                        <div style="width:35px;height:35px;border-radius:8px;background:#ff1744;border:2px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="document.getElementById('themePreview').style.background='#ff1744'"></div>
                        <div style="width:35px;height:35px;border-radius:8px;background:#00e676;border:2px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="document.getElementById('themePreview').style.background='#00e676'"></div>
                        <div style="width:35px;height:35px;border-radius:8px;background:#ffd740;border:2px solid rgba(255,255,255,0.1);cursor:pointer;" onclick="document.getElementById('themePreview').style.background='#ffd740'"></div>
                    </div>
                    <div id="themePreview" style="width:100%;height:60px;border-radius:10px;background:{{ global_settings.default_theme_color }};border:1px solid rgba(255,255,255,0.05);transition:all 0.3s ease;"></div>
                </div>
            </div>
        </div>
        
        <!-- ===================== SECTION 11: USER DIRECTORY ===================== -->
        <div class="section-wrapper" id="sec-directory">
            <div class="section-header">
                <div class="section-title"><i class="fa-solid fa-address-book"></i> User Directory</div>
                <span class="section-badge">{{ users.keys()|length }} TOTAL</span>
            </div>
            <div class="cyber-card">
                <div class="card-label"><i class="fa-solid fa-users"></i> All Subscribers</div>
                <div style="margin-bottom:10px; display:flex; gap:8px;">
                    <input type="text" id="userSearch" placeholder="🔍 Search users..." onkeyup="filterUsers()" style="flex:1;">
                    <span style="font-family:'Rajdhani'; font-size:11px; color:rgba(255,255,255,0.2); align-self:center;">
                        {{ active_count }} active / {{ expired_count }} expired
                    </span>
                </div>
                {% if users %}
                    {% for u_name, u_info in users.items() %}
                    <div class="user-item searchable-user" data-name="{{ u_name }}">
                        <div class="user-info">
                            <span class="username">
                                <i class="fa-solid fa-user-circle"></i> {{ u_name }}
                                <span class="tag {% if u_info.get('plan_type') == 'permanent' %}tag-green{% else %}tag-blue{% endif %}">
                                    {{ u_info.get('plan_type', 'time_bound')|upper }}
                                </span>
                                <span style="font-family:'Rajdhani'; font-size:10px; color:rgba(255,255,255,0.2);">
                                    P: {{ u_info.password }}
                                </span>
                            </span>
                            <div>
                                <span class="status-badge {% if u_info.status == 'active' %}status-active{% else %}status-expired{% endif %}">
                                    {{ u_info.status|upper }}
                                </span>
                            </div>
                        </div>
                        <p style="font-size:10px; margin: 6px 0; opacity: 0.5; display: flex; align-items: center; gap: 15px; font-family:'Rajdhani';">
                            {% if u_info.get('plan_type') == 'permanent' %}
                            <span>📅 <b style="color:var(--neon-green);">LIFETIME PERMANENT</b></span>
                            {% else %}
                            <span>📅 Expires: <b style="color:var(--neon-purple);">{{ u_info.expiry.replace('T', ' ') if u_info.expiry else 'N/A' }}</b></span>
                            {% endif %}
                        </p>
                        <div style="display:flex; gap:8px; margin-top:6px; flex-wrap: wrap;">
                            <a href="/admin/login_as/{{ u_name }}" class="btn btn-primary btn-xs"><i class="fa-solid fa-sign-in-alt"></i> Login As</a>
                            {% if u_info.get('plan_type') != 'permanent' %}
                            <a href="/admin/make_permanent/{{ u_name }}" class="btn btn-success btn-xs" onclick="return confirm('Make {{ u_name }} permanent?')"><i class="fa-solid fa-infinity"></i> Make Permanent</a>
                            {% endif %}
                            <a href="/admin/delete_user/{{ u_name }}" class="btn btn-danger btn-xs" onclick="return confirm('Wipe ALL data for {{ u_name }}?')"><i class="fa-solid fa-trash-alt"></i> Delete</a>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="empty-state">
                        <i class="fa-solid fa-users-slash"></i>
                        No subscribers in the database
                    </div>
                {% endif %}
            </div>
        </div>
        
        <!-- FOOTER -->
        <div style="text-align:center; padding:30px 0 10px; font-family:'Rajdhani',sans-serif; font-size:11px; color:rgba(255,255,255,0.08); letter-spacing:2px;">
            YUVI HOSTING v3.0 // OWNER PANEL // POWERED BY FLASK & FIREBASE
        </div>
    </div>
    
    <script>
        // Toggle expiry input based on plan
        function toggleExpiry(val) {
            const wrapper = document.getElementById('exp_input_wrapper');
            const input = document.getElementById('expiry_date_input');
            if(val === 'permanent') {
                wrapper.style.display = 'none';
                input.removeAttribute('required');
            } else {
                wrapper.style.display = 'block';
                input.setAttribute('required', 'required');
            }
        }
        
        // Copy to clipboard
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                showToast('Copied to clipboard!', 'success');
            }).catch(() => {
                // Fallback
                const ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast('Copied to clipboard!', 'success');
            });
        }
        
        // Toast notification system
        function showToast(msg, type) {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.innerHTML = msg;
            container.appendChild(toast);
            setTimeout(() => { toast.remove(); }, 4000);
        }
        
        // User search filter
        function filterUsers() {
            const query = document.getElementById('userSearch').value.toLowerCase();
            document.querySelectorAll('.searchable-user').forEach(el => {
                const name = el.getAttribute('data-name').toLowerCase();
                el.style.display = name.includes(query) ? 'block' : 'none';
            });
        }
        
        // Sidebar active state tracking
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', function(e) {
                document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
                this.classList.add('active');
            });
        });

        // Highlight active section on scroll
        const sections = document.querySelectorAll('.section-wrapper');
        const navItems = document.querySelectorAll('.nav-item');
        window.addEventListener('scroll', () => {
            let current = '';
            sections.forEach(section => {
                const top = section.offsetTop - 120;
                if(window.scrollY >= top) current = section.id;
            });
            navItems.forEach(item => {
                item.classList.remove('active');
                if(item.getAttribute('href') === '#' + current) item.classList.add('active');
            });
        });
        
        // Auto-dismiss flash messages
        document.addEventListener('DOMContentLoaded', function() {
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        showToast('{{ message|e }}', '{{ category|e }}');
                    {% endfor %}
                {% endif %}
            {% endwith %}
        });
    </script>
</body>
</html>
'''

# ========== FALLBACK ERROR HANDLER ==========
@app.errorhandler(500)
def handle_internal_server_error(e):
    import traceback
    return f"<h3 style='color:#ff1744;font-family:sans-serif;'>⚠ Flask App Crashed</h3><pre style='background:#03050a;color:#00ff00;padding:20px;'>{traceback.format_exc()}</pre>", 500

# ========== EXTERNAL REST APIs FOR TELEGRAM BOT ==========
@app.route("/api/admin/create_user", methods=["POST"])
def api_create_user():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    plan_type = data.get("plan_type", "time_bound")
    expiry = data.get("expiry", "2099-12-31T23:59")
    
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400
        
    if username in db["users"]:
        return jsonify({"status": "error", "message": "User already exists"}), 409
        
    db["users"][username] = {
        "password": password,
        "expiry": expiry if plan_type == "time_bound" else "2099-12-31T23:59",
        "plan_type": plan_type,
        "status": "active",
        "broadcast": {"message": "", "id": ""}
    }
    save_db(db)
    add_audit_log("API: User Created", "BOT_API", f"User: {username}, Plan: {plan_type}")
    return jsonify({"status": "success", "message": f"User {username} created via API."})

@app.route("/api/admin/delete_user", methods=["POST"])
def api_delete_user():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    username = data.get("username", "").strip()
    if username in db["users"]:
        stop_and_clean_user(username)
        add_audit_log("API: User Deleted", "BOT_API", f"User: {username}")
        return jsonify({"status": "success", "message": f"User {username} wiped and deleted."})
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route("/api/admin/list_users", methods=["POST"])
def api_list_users():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    # Return sanitized user list (no passwords in API for security)
    safe_users = {}
    for u_name, u_info in db["users"].items():
        safe_users[u_name] = {
            "plan_type": u_info.get("plan_type", "time_bound"),
            "status": u_info.get("status", "active"),
            "expiry": u_info.get("expiry", "N/A")
        }
    return jsonify({"status": "success", "users": safe_users})

# ========== ALERT / EXPIRY CHECK API ==========
@app.route("/api/get_alert")
def get_alert():
    if 'username' not in session: return jsonify({"message": "", "id": "", "expired_kick": False})
    user_name = session['username']
    db = load_db()
    
    if not session.get('is_admin'):
        if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name].get("status") == "expired"):
            session.clear() 
            return jsonify({"expired_kick": True})
            
    broadcast_data = db["users"].get(user_name, {}).get("broadcast", "")
    if isinstance(broadcast_data, dict):
        msg = broadcast_data.get("message", "")
        msg_id = broadcast_data.get("id", "")
    else:
        msg = str(broadcast_data)
        msg_id = ""
        
    return jsonify({"message": msg, "id": msg_id, "expired_kick": False})

@app.route("/api/dismiss_alert", methods=["POST"])
def dismiss_alert():
    if 'username' not in session: return jsonify({"status": "error"})
    user_name = session['username']
    db = load_db()
    if user_name in db["users"]:
        db["users"][user_name]["broadcast"] = {"message": "", "id": ""}
        save_db(db)
    return jsonify({"status": "success"})

# ========== LOGIN ROUTE ==========
@app.route("/login", methods=["GET", "POST"])
def login():
    error = request.args.get("error", None)
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        db = load_db()
        
        # Track login attempts
        login_attempts = db.get("login_attempts", [])
        login_attempts.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "type": l_type,
            "ip": request.remote_addr or "unknown"
        })
        if len(login_attempts) > 200:
            login_attempts = login_attempts[-200:]
        db["login_attempts"] = login_attempts
        save_db(db)
        
        if l_type == "admin":
            admin_data = db.get("admin", {"username": "JUBARAJ", "password": "098765"})
            if username == admin_data.get("username") and pw == admin_data.get("password"):
                session['is_admin'], session['username'] = True, username
                admin_data["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_db(db)
                add_audit_log("Admin Login", username, f"Login via web panel")
                return redirect(url_for("admin_panel"))
            error = "⚠ Invalid Admin Credentials!"
        else:
            if db.get("global_settings", {}).get("maintenance_mode", False):
                return render_template_string(LOGIN_HTML, error="🔧 System Under Maintenance! Please try again later.")
                
            if username in db["users"]:
                user_data = db["users"][username]
                if user_data["password"] == pw:
                    if user_data.get("plan_type") != "permanent" and user_data.get("status") == "expired":
                        error = "⛔ Your access plan has expired! Contact Admin."
                    else:
                        session['is_admin'], session['username'] = False, username
                        return redirect(url_for("index"))
                else:
                    error = "🔐 Incorrect Password!"
            else:
                error = "❌ You are not a registered user! Contact Admin."
                
    return render_template_string(LOGIN_HTML, error=error)

# ========== USER INDEX ==========
@app.route("/")
def index():
    if 'username' not in session: return redirect(url_for("login"))
    if session.get('is_admin'): return redirect(url_for("admin_panel"))
    
    db = load_db()
    gs = db.get("global_settings", {})
    if gs.get("maintenance_mode", False):
        session.clear()
        return redirect(url_for("login", error="System is under maintenance! Please check back later."))

    user_name = session['username']
    
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name].get("status") == "expired"):
        session.clear()
        return redirect(url_for("login", error="⛔ Your access plan has expired! Contact Admin."))

    user_info = db["users"][user_name]
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    os.makedirs(user_dir, exist_ok=True)
    apps_list = []
    
    for name in os.listdir(user_dir):
        if os.path.isdir(os.path.join(user_dir, name)):
            is_any_running = False
            for key, p in list(processes.items()):
                if key[0] == user_name and key[1] == name and p.poll() is None:
                    is_any_running = True
                    break
            apps_list.append({"name": name, "running": is_any_running})
            
    user_theme = db.get("themes", {}).get(user_name, {"color": gs.get("default_theme_color", "#00ffff"), "size": 38, "speed": 4, "ui_mode": "normal"})
    
    if user_info.get("plan_type") == "permanent":
        expiry_display = "♾ Lifetime Permanent"
    else:
        expiry_display = user_info.get("expiry", "N/A").replace("T", " ") if user_info.get("expiry") else "N/A"

    return render_template("index.html", 
                           apps=apps_list, 
                           username=user_name,
                           plan_expiry=expiry_display,
                           user_color=user_theme.get("color", "#00ffff"),
                           user_size=user_theme.get("size", 38),
                           user_speed=user_theme.get("speed", 4),
                           user_ui_mode=user_theme.get("ui_mode", "normal"))

# ========== ADMIN ROUTES ==========
@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    admin_creds = db.get("admin", {"username": "JUBARAJ", "password": "098765", "api_key": "RANDOM", "api_key_id": "xxxx"})
    gs = db.get("global_settings", {})
    
    # Live System Diagnostics
    import platform
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    uptime_days = int(uptime_seconds // 86400)
    uptime_hours = int((uptime_seconds % 86400) // 3600)
    uptime_mins = int((uptime_seconds % 3600) // 60)
    
    # Storage info
    statvfs = shutil.disk_usage(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else None
    st_used_gb = round(statvfs.used / (1024**3), 1) if statvfs else 0
    st_total_gb = round(statvfs.total / (1024**3), 1) if statvfs else 100
    st_percent = round((statvfs.used / statvfs.total) * 100, 1) if statvfs else 0
    
    sys_info = {
        "cpu": psutil.cpu_percent(interval=0.5),
        "ram": psutil.virtual_memory().percent,
        "active_processes": len([p for p in processes.values() if p.poll() is None]),
        "uptime_days": uptime_days,
        "uptime_hours": uptime_hours,
        "uptime_mins": uptime_mins,
        "storage_used_gb": st_used_gb,
        "storage_total_gb": st_total_gb if st_total_gb > 0 else 100,
        "storage_percent": st_percent
    }
    
    # Active / expired counts
    active_count = sum(1 for u in db["users"].values() if u.get("status") == "active")
    expired_count = sum(1 for u in db["users"].values() if u.get("status") == "expired")
    
    # Audit logs
    audit_data = load_audit_logs()
    audit_logs = audit_data.get("logs", [])
    
    # Broadcast history
    broadcast_history = db.get("broadcast_history", [])
    
    # Login attempts count
    login_attempts_count = len(db.get("login_attempts", []))
    
    # Firebase active check
    firebase_active = bool(firebase_admin._apps)
    
    return render_template_string(ADMIN_HTML, 
                                 users=db["users"],
                                 admin_creds=admin_creds,
                                 sys_info=sys_info,
                                 maintenance_mode=gs.get("maintenance_mode", False),
                                 global_settings=gs,
                                 audit_logs=audit_logs,
                                 broadcast_history=broadcast_history,
                                 login_attempts_count=login_attempts_count,
                                 active_count=active_count,
                                 expired_count=expired_count,
                                 firebase_active=firebase_active)

@app.route("/admin/toggle_maintenance", methods=["POST"])
def toggle_maintenance():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if "global_settings" not in db: db["global_settings"] = {}
    db["global_settings"]["maintenance_mode"] = not db["global_settings"].get("maintenance_mode", False)
    save_db(db)
    new_state = "ENABLED" if db["global_settings"]["maintenance_mode"] else "DISABLED"
    add_audit_log("Maintenance Toggled", session['username'], f"Maintenance {new_state}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/update_settings", methods=["POST"])
def update_settings():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if "global_settings" not in db: db["global_settings"] = {}
    
    db["global_settings"]["default_theme_color"] = request.form.get("default_theme_color", "#00ffff")
    db["global_settings"]["max_upload_size_mb"] = int(request.form.get("max_upload_size_mb", 100))
    db["global_settings"]["session_timeout_minutes"] = int(request.form.get("session_timeout_minutes", 60))
    save_db(db)
    add_audit_log("Settings Updated", session['username'], "Global settings changed")
    
    from flask import flash
    return redirect(url_for("admin_panel"))

@app.route("/admin/kill_all_processes")
def kill_all_processes():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    count = 0
    for key, p in list(processes.items()):
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
        count += 1
    
    db["start_times"] = {}
    save_db(db)
    add_audit_log("Kill All Processes", session['username'], f"{count} processes terminated")
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_all_expired")
def delete_all_expired():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    expired_users = [u for u, info in db["users"].items() if info.get("status") == "expired"]
    for username in expired_users:
        stop_and_clean_user(username)
    add_audit_log("Purge Expired", session['username'], f"{len(expired_users)} expired users deleted")
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_all_users")
def delete_all_users():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    all_users = list(db["users"].keys())
    for username in all_users:
        stop_and_clean_user(username)
    # Also clear uploads
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER, ignore_errors=True)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    add_audit_log("NUKE ALL DATA", session['username'], f"All {len(all_users)} users and data destroyed")
    return redirect(url_for("admin_panel"))

@app.route("/admin/export_users")
def export_users():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    return jsonify({"exported_at": datetime.now().isoformat(), "users": db["users"]})

@app.route("/admin/update_creds", methods=["POST"])
def update_creds():
    if not session.get('is_admin'): return redirect(url_for("login"))
    new_user = request.form.get("admin_user", "").strip()
    new_pass = request.form.get("admin_pass", "").strip()
    
    if new_user and new_pass:
        db = load_db()
        old_user = db["admin"].get("username", "")
        db["admin"]["username"] = new_user
        db["admin"]["password"] = new_pass
        save_db(db)
        add_audit_log("Admin Credentials Changed", session['username'], f"User: {old_user} -> {new_user}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/reset_session")
def reset_session():
    if not session.get('is_admin'): return redirect(url_for("login"))
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin/regenerate_api_key")
def regenerate_api_key():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    db["admin"]["api_key"] = generate_random_api_key(64)
    save_db(db)
    add_audit_log("API Key Regenerated", session['username'], "New random API key generated")
    return redirect(url_for("admin_panel"))

@app.route("/admin/regenerate_api_key_id")
def regenerate_api_key_id():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    db["admin"]["api_key_id"] = generate_readable_api_id()
    save_db(db)
    add_audit_log("API Key ID Regenerated", session['username'], "New ID generated")
    return redirect(url_for("admin_panel"))

@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    plan_type = request.form.get("plan_type", "time_bound")
    
    if plan_type == "permanent":
        expiry = "2099-12-31T23:59"
    else:
        expiry = request.form.get("expiry", "2099-12-31T23:59")
    
    if username and password:
        db = load_db()
        if username in db["users"]:
            return redirect(url_for("admin_panel"))
        db["users"][username] = {
            "password": password,
            "expiry": expiry,
            "plan_type": plan_type,
            "status": "active",
            "broadcast": {"message": "", "id": ""}
        }
        save_db(db)
        add_audit_log("User Created", session['username'], f"User: {username}, Plan: {plan_type}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/make_permanent/<username>")
def make_permanent(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if username in db["users"]:
        db["users"][username]["plan_type"] = "permanent"
        db["users"][username]["expiry"] = "2099-12-31T23:59"
        db["users"][username]["status"] = "active"
        save_db(db)
        add_audit_log("User Made Permanent", session['username'], f"User: {username}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_user/<username>")
def delete_user(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if username in db["users"]:
        stop_and_clean_user(username)
        add_audit_log("User Deleted", session['username'], f"User: {username}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/broadcast", methods=["POST"])
def broadcast():
    if not session.get('is_admin'): return redirect(url_for("login"))
    target = request.form.get("target_user")
    msg = request.form.get("message", "").strip()
    db = load_db()
    
    msg_id = str(int(time.time()))
    broadcast_obj = {"message": msg, "id": msg_id}
    
    if target == "ALL_USERS":
        for u in db["users"]:
            db["users"][u]["broadcast"] = broadcast_obj
        target_display = "ALL USERS (Global)"
    elif target in db["users"]:
        db["users"][target]["broadcast"] = broadcast_obj
        target_display = f"User: {target}"
    else:
        return redirect(url_for("admin_panel"))
    
    # Save to broadcast history
    if "broadcast_history" not in db:
        db["broadcast_history"] = []
    db["broadcast_history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target": target_display,
        "msg": msg[:50],
        "id": msg_id
    })
    if len(db["broadcast_history"]) > 100:
        db["broadcast_history"] = db["broadcast_history"][-100:]
    
    save_db(db)
    add_audit_log("Broadcast Sent", session['username'], f"Target: {target_display}")
    return redirect(url_for("admin_panel"))

@app.route("/admin/login_as/<username>")
def login_as(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    session['username'], session['is_admin'] = username, False
    add_audit_log("Login As User", session['username'], f"Impersonated: {username}")
    return redirect(url_for("index"))

# ========== AUDIT LOG MANAGEMENT ==========
@app.route("/admin/clear_audit_logs")
def clear_audit_logs():
    if not session.get('is_admin'): return redirect(url_for("login"))
    save_audit_logs({"logs": []})
    add_audit_log("Audit Logs Cleared", session['username'], "All audit history deleted")
    return redirect(url_for("admin_panel"))

@app.route("/admin/export_logs")
def export_logs():
    if not session.get('is_admin'): return redirect(url_for("login"))
    audit = load_audit_logs()
    return jsonify(audit)

# ========== BACKUP & RESTORE ==========
@app.route("/admin/backup_db")
def backup_db():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    memory_file = io.BytesIO()
    memory_file.write(json.dumps(db, indent=4).encode())
    memory_file.seek(0)
    add_audit_log("Database Backup", session['username'], "DB exported as JSON")
    return send_file(memory_file, download_name=f"yuvi_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", as_attachment=True)

@app.route("/admin/backup_all")
def backup_all():
    if not session.get('is_admin'): return redirect(url_for("login"))
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add database
        if os.path.exists(DB_FILE):
            zf.write(DB_FILE, "database.json")
        # Add uploads
        if os.path.exists(UPLOAD_FOLDER):
            for root, dirs, files in os.walk(UPLOAD_FOLDER):
                for file in files:
                    file_path = os.path.join(root, file)
                    zf.write(file_path, os.path.join("uploads", os.path.relpath(file_path, UPLOAD_FOLDER)))
    memory_file.seek(0)
    add_audit_log("Full Backup", session['username'], "Complete system backup downloaded")
    return send_file(memory_file, download_name=f"yuvi_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", as_attachment=True)

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
            # Upload database backup
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
    # Fork a process to restart after a small delay
    def delayed_restart():
        time.sleep(2)
        os._exit(0)  # Will be restarted by supervisor/docker
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