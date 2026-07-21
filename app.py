from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io, threading, signal
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, storage

app = Flask(__name__, template_folder=".")
app.secret_key = "YUVI-HOSTING-PRO"

UPLOAD_FOLDER = "uploads"
DB_FILE = "database.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}
db_lock = threading.Lock()  # Concurrency lock to prevent file corruption

# --- FIREBASE INITIALIZATION ---
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

# --- DB STRUCTURE ---
def load_db():
    with db_lock:
        default = {
            "users": {}, 
            "start_times": {}, 
            "themes": {},
            "admin": {
                "username": "JUBARAJ", 
                "password": "098765",
                "api_key": "yuvi_secret_api_key_123"
            }
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
                if "api_key" not in data["admin"]: data["admin"]["api_key"] = "yuvi_secret_api_key_123"
                return data
            except Exception as e:
                print(f"DB Read Error, keeping current memory state: {e}")
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

# --- EXPIRY TRACKER & AUTO-TERMINATION ---
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
            print(f"[AUTO-TERMINATE] Local folder deleted for expired user: {user_name}")
        except Exception as e:
            print(f"Error deleting user directory: {e}")
            
    # Firebase Storage Deletion
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blobs = bucket.list_blobs(prefix=f"backups/{user_name}/")
            for blob in blobs:
                blob.delete()
            print(f"[AUTO-TERMINATE] Firebase backups cleared for: {user_name}")
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
                        print(f"[SYSTEM] User {username} expired. Cleaning up resources.")
                        users_to_clean.append(username)

            for username in users_to_clean:
                stop_and_clean_user(username)
                
        except Exception as e:
            print(f"Enforcement Loop Error: {e}")
        time.sleep(5)

threading.Thread(target=enforcement_loop, daemon=True).start()

# --- UI TEMPLATES ---
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | YUVI CODEX</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; }
        :root { --bg: #030508; --primary: #00ffff; --sec: #7000ff; }
        body { background: var(--bg); color: white; font-family: 'Orbitron', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; padding: 15px; }
        .login-box-wrapper { position: relative; width: 100%; max-width: 420px; padding: 3px; border-radius: 25px; overflow: hidden; background: rgba(255, 255, 255, 0.05); box-shadow: 0 25px 45px rgba(0,0,0,0.5); }
        .login-box-wrapper::before { content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; background: conic-gradient(transparent, transparent, transparent, var(--primary)); animation: animateBorder 4s linear infinite; }
        @keyframes animateBorder { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .login-card { position: relative; z-index: 10; background: #090d16; padding: 40px 35px; border-radius: 23px; width: 100%; text-align: center; backdrop-filter: blur(20px); }
        .lock-container { width: 85px; height: 85px; background: rgba(0, 255, 255, 0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 25px; border: 2px solid var(--primary); box-shadow: 0 0 20px var(--primary); }
        .lock-icon { font-size: 38px; color: var(--primary); }
        h2 { font-size: 22px; margin-bottom: 30px; letter-spacing: 4px; text-transform: uppercase; background: linear-gradient(to right, #fff, var(--primary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        input, select { width: 100%; padding: 14px; margin: 12px 0; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #fff; outline: none; font-size: 14px; }
        button { width: 100%; padding: 15px; border-radius: 12px; border: none; background: linear-gradient(45deg, var(--sec), var(--primary)); color: #fff; font-weight: bold; cursor: pointer; margin-top: 20px; text-transform: uppercase; letter-spacing: 2px; }
        .error-msg { color: #ff4757; font-size: 13px; margin-top: 10px; display: block; font-weight: bold; }
    </style>
</head>
<body>
    <div class="login-box-wrapper">
        <div class="login-card">
            <div class="lock-container"><i class="fa-solid fa-user-shield lock-icon"></i></div>
            <h2>System Login</h2>
            {% if error %}<span class="error-msg">{{ error }}</span>{% endif %}
            <form method="post" action="/login">
                <select name="login_type">
                    <option value="user">USER ACCESS</option>
                    <option value="admin">ADMIN ROOT</option>
                </select>
                <input type="text" name="username" placeholder="Enter Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Access System</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Owner Panel | Complete Control</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;800&family=Rajdhani:wght@600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root { 
            --bg-dark: #030508; 
            --panel-bg: #0c1223; 
            --card-bg: rgba(10, 15, 28, 0.95); 
            --neon-blue: #00ffff; 
            --neon-purple: #7000ff; 
            --neon-green: #00ff88;
            --text-light: #f1f5f9; 
            --border-light: rgba(0, 255, 255, 0.18);
        }
        body { 
            background: radial-gradient(circle at center, #070c1a 0%, var(--bg-dark) 100%); 
            color: var(--text-light); 
            font-family: 'Orbitron', sans-serif; 
            padding: 15px; 
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        
        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 25px; 
            padding: 18px 24px; 
            background: linear-gradient(135deg, rgba(12, 18, 35, 0.95), rgba(6, 9, 19, 0.98)); 
            border-radius: 16px; 
            border: 1px solid var(--border-light); 
            box-shadow: 0 0 25px rgba(0, 255, 255, 0.15);
        }
        .header h2 { 
            font-size: 20px; 
            letter-spacing: 3px;
            font-weight: 800;
            background: linear-gradient(to right, #ffffff, var(--neon-blue)); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .section-title {
            font-size: 14px;
            color: var(--neon-blue);
            margin: 30px 0 15px 0;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid rgba(0, 255, 255, 0.25);
            padding-bottom: 8px;
            letter-spacing: 2px;
            text-transform: uppercase;
            font-weight: 800;
        }
        
        .grid { display: grid; grid-template-columns: 1fr; gap: 18px; margin-bottom: 18px; }
        @media(min-width: 768px) { .grid { grid-template-columns: 1fr 1fr; } }
        @media(min-width: 1024px) { .grid-3 { grid-template-columns: 1fr 1fr 1fr; } }

        .stats-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        .stat-card {
            background: rgba(12, 18, 35, 0.85);
            border: 1px solid var(--border-light);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        }
        .stat-icon {
            font-size: 28px;
            color: var(--neon-blue);
            background: rgba(0, 255, 255, 0.1);
            width: 50px;
            height: 50px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .stat-data h4 { font-size: 11px; opacity: 0.7; text-transform: uppercase; font-family: 'Rajdhani', sans-serif; letter-spacing: 1px; }
        .stat-data p { font-size: 20px; font-weight: bold; color: #fff; margin-top: 2px; }

        .card { 
            background: var(--card-bg); 
            padding: 20px 24px; 
            border-radius: 16px; 
            border: 1px solid rgba(0, 255, 255, 0.12); 
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
            backdrop-filter: blur(12px);
            transition: all 0.3s ease;
        }
        .card:hover { border-color: rgba(0, 255, 255, 0.35); box-shadow: 0 10px 30px rgba(0,255,255,0.1); }
        h3 { 
            margin-bottom: 15px; 
            font-size: 14px; 
            display: flex; 
            align-items: center; 
            gap: 10px; 
            color: var(--neon-blue); 
            text-transform: uppercase; 
            letter-spacing: 1.5px;
            font-family: 'Rajdhani', sans-serif;
            font-weight: 700;
        }
        .input-group { display: flex; flex-direction: column; gap: 12px; }
        input, select, textarea { 
            width: 100%; 
            padding: 11px 14px; 
            border-radius: 10px; 
            border: 1px solid rgba(255,255,255,0.1); 
            background: #040710; 
            color: #fff; 
            outline: none; 
            font-size: 13px;
            font-family: sans-serif;
            transition: all 0.2s ease;
        }
        input:focus, select:focus, textarea:focus {
            border-color: var(--neon-blue);
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.2);
        }
        .btn { 
            padding: 11px 18px; 
            border-radius: 10px; 
            border: none; 
            font-weight: bold; 
            cursor: pointer; 
            text-align: center; 
            display: inline-flex; 
            align-items: center; 
            justify-content: center; 
            gap: 8px; 
            text-decoration: none;
            transition: all 0.2s ease;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 1px;
            font-family: 'Orbitron', sans-serif;
        }
        .btn-primary { 
            background: linear-gradient(45deg, var(--neon-purple), var(--neon-blue)); 
            color: #fff; 
            box-shadow: 0 2px 12px rgba(0, 255, 255, 0.2);
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 18px rgba(0, 255, 255, 0.4); }
        .btn-danger { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
        .btn-danger:hover { background: #dc2626; color: #fff; transform: translateY(-2px); }
        .btn-warning { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
        .btn-warning:hover { background: #d97706; color: #fff; }
        .btn-logout { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 8px 16px; font-size: 11px; }
        .btn-logout:hover { background: #ef4444; color: white; }
        
        .user-item { background: rgba(4, 7, 16, 0.85); border-radius: 12px; padding: 15px 18px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.05); transition: border-color 0.2s ease; }
        .user-item:hover { border-color: rgba(112, 0, 255, 0.4); }
        .user-info { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .username { font-weight: bold; font-size: 14px; color: var(--text-light); display: flex; align-items: center; gap: 8px; }
        .status-badge { padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: bold; letter-spacing: 0.5px; text-transform: uppercase; }
        .status-active { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
        .status-expired { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
        
        pre { background: #010204; color: #00ffff; padding: 14px; border-radius: 10px; font-size: 11px; overflow-x: auto; border: 1px solid rgba(0, 255, 255, 0.15); font-family: monospace; }
        
        .search-box {
            margin-bottom: 15px;
            display: flex;
            gap: 10px;
        }
    </style>
    <script>
        function toggleExpiryInput(value) {
            var expBox = document.getElementById('exp_input_wrapper');
            var expInput = document.getElementById('expiry_date_input');
            if(value === 'permanent') {
                expBox.style.display = 'none';
                expInput.removeAttribute('required');
            } else {
                expBox.style.display = 'block';
                expInput.setAttribute('required', 'required');
            }
        }

        function filterUsers() {
            var input = document.getElementById("userSearch");
            var filter = input.value.toLowerCase();
            var nodes = document.getElementsByClassName('user-item');
            for (var i = 0; i < nodes.length; i++) {
                if (nodes[i].innerText.toLowerCase().includes(filter)) {
                    nodes[i].style.display = "block";
                } else {
                    nodes[i].style.display = "none";
                }
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2><i class="fa-solid fa-crown" style="color:var(--neon-blue);"></i> OWNER SYSTEM CONTROL</h2>
            <a href="/logout" class="btn btn-logout"><i class="fa-solid fa-power-off"></i> LOGOUT</a>
        </div>

        <div class="stats-container">
            <div class="stat-card">
                <div class="stat-icon"><i class="fa-solid fa-users"></i></div>
                <div class="stat-data">
                    <h4>Total Registered Users</h4>
                    <p>{{ users.keys()|list|length }} Users</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon" style="color:var(--neon-green); background:rgba(0,255,136,0.1);"><i class="fa-solid fa-user-check"></i></div>
                <div class="stat-data">
                    <h4>System Active Status</h4>
                    <p style="color:var(--neon-green);">ONLINE 100%</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon" style="color:var(--neon-purple); background:rgba(112,0,255,0.1);"><i class="fa-solid fa-key"></i></div>
                <div class="stat-data">
                    <h4>Admin Root User</h4>
                    <p>{{ admin_creds.username }}</p>
                </div>
            </div>
        </div>

        <div class="section-title"><i class="fa-solid fa-user-gear"></i> SECTION 1: SUBSCRIPTION & USER MANAGEMENT</div>
        <div class="card">
            <h3><i class="fa-solid fa-user-plus"></i> ADD NEW USER ACCOUNT</h3>
            <form action="/admin/create_user" method="post" class="input-group">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
                    <input type="text" name="username" placeholder="Enter New Username" required>
                    <input type="password" name="password" placeholder="Enter User Password" required>
                </div>
                <select name="plan_type" onchange="toggleExpiryInput(this.value)">
                    <option value="time_bound">Time Bound (Auto Deletion & Termination)</option>
                    <option value="permanent">Permanent (Lifetime Plan)</option>
                </select>
                <div id="exp_input_wrapper">
                    <label style="font-size:11px; color: var(--neon-blue); display:block; margin-bottom:5px; font-family:'Rajdhani'; font-weight:700;">SET EXPIRY DATE & TIME:</label>
                    <input type="datetime-local" id="expiry_date_input" name="expiry" required>
                </div>
                <button type="submit" class="btn btn-primary" style="width:100%; margin-top:5px;"><i class="fa-solid fa-plus-circle"></i> Create Account Now</button>
            </form>
        </div>

        <div class="section-title"><i class="fa-solid fa-bullhorn"></i> SECTION 2: BROADCAST & SYSTEM ALERTS</div>
        <div class="card">
            <h3><i class="fa-solid fa-paper-plane"></i> DISPATCH BROADCAST STATION</h3>
            <form action="/admin/broadcast" method="post" class="input-group">
                <select name="target_user">
                    <option value="ALL_USERS">--- GLOBAL BROADCAST (SEND TO ALL USERS) ---</option>
                    {% for u_name in users.keys() %}
                    <option value="{{ u_name }}">Direct Message to: {{ u_name }}</option>
                    {% endfor %}
                </select>
                <textarea name="message" rows="3" placeholder="Write broadcast alert message details here..." required></textarea>
                <button type="submit" class="btn btn-primary" style="width:100%;"><i class="fa-solid fa-bolt"></i> Dispatch Alert To User Screen</button>
            </form>
        </div>

        <div class="section-title"><i class="fa-solid fa-shield-halved"></i> SECTION 3: SECURITY & BOT SETTINGS</div>
        <div class="grid">
            <div class="card">
                <h3><i class="fa-solid fa-lock"></i> UPDATE ADMIN ROOT CREDS</h3>
                <form action="/admin/update_creds" method="post" class="input-group">
                    <input type="text" name="admin_user" value="{{ admin_creds.username }}" placeholder="Admin Username" required>
                    <input type="password" name="admin_pass" placeholder="New Secret Password" required>
                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-save"></i> Save Credentials</button>
                </form>
            </div>

            <div class="card">
                <h3><i class="fa-solid fa-robot"></i> TELEGRAM BOT SECRET API KEY</h3>
                <form action="/admin/update_api_key" method="post" class="input-group">
                    <label style="font-size:11px; color: var(--neon-blue); font-family:'Rajdhani'; font-weight:700;">SECRET API KEY FOR BOT INTEGRATION:</label>
                    <input type="text" name="api_key" value="{{ admin_creds.api_key }}" required>
                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-key"></i> Update Secret API Key</button>
                </form>
            </div>
        </div>

        <div class="section-title"><i class="fa-solid fa-code"></i> SECTION 4: BOT INTEGRATION API ENDPOINT</div>
        <div class="card">
            <h3><i class="fa-solid fa-plug"></i> REMOTE BOT API DOCUMENTATION</h3>
            <p style="font-size: 12px; margin-bottom: 12px; opacity: 0.8; font-family: sans-serif;">Use this endpoint in your Python scripts or Telegram bots to register users remotely:</p>
            <pre>
# POST Endpoint to create user via Bot:
URL: http://your-domain.com/api/admin/create_user
METHOD: POST
HEADERS: {"Content-Type": "application/json"}
BODY:
{
    "api_key": "{{ admin_creds.api_key }}",
    "username": "user123",
    "password": "pass123",
    "plan_type": "time_bound",  # or "permanent"
    "expiry": "2026-12-31T23:59"
}
            </pre>
        </div>

        <div class="section-title"><i class="fa-solid fa-sliders"></i> SECTION 5: ADVANCED SYSTEM CONTROL & MAINTENANCE</div>
        <div class="card">
            <h3><i class="fa-solid fa-gears"></i> QUICK SYSTEM ACTIONS</h3>
            <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:10px;">
                <button class="btn btn-warning" onclick="alert('System Cache Cleared Successfully!')"><i class="fa-solid fa-broom"></i> Clear Temp Files</button>
                <button class="btn btn-danger" onclick="if(confirm('Are you sure you want to trigger database backup refresh?')) alert('Database Sync Complete!')"><i class="fa-solid fa-database"></i> Force DB Sync</button>
            </div>
        </div>

        <div class="section-title"><i class="fa-solid fa-users"></i> SECTION 6: SUBSCRIBER DIRECTORY & USER CONTROL</div>
        <div class="card">
            <h3><i class="fa-solid fa-database"></i> SUBSCRIBER MANAGEMENT</h3>
            <div class="search-box">
                <input type="text" id="userSearch" onkeyup="filterUsers()" placeholder="Search user by name..." style="margin:0;">
            </div>
            {% if users %}
                {% for u_name, u_info in users.items() %}
                <div class="user-item">
                    <div class="user-info">
                        <span class="username"><i class="fa-solid fa-user-circle" style="color:var(--neon-blue);"></i> {{ u_name }} <span style="font-size:11px; opacity:0.6; font-family:sans-serif;">(Pass: {{ u_info.password }})</span></span>
                        <div>
                            <span class="status-badge {% if u_info.status == 'active' %}status-active{% else %}status-expired{% endif %}">
                                {{ u_info.status|upper }}
                            </span>
                        </div>
                    </div>
                    <p style="font-size:11px; margin: 10px 0; opacity: 0.8; display: flex; align-items: center; gap: 15px; font-family:sans-serif;">
                        <span>Plan Type: <b style="color:var(--neon-blue)">{{ u_info.get('plan_type','time_bound')|upper }}</b></span>
                        {% if u_info.get('plan_type') != 'permanent' %}
                        <span>Expiry Date: <b style="color:var(--neon-purple)">{{ u_info.expiry.replace('T', ' ') if u_info.expiry else 'N/A' }}</b></span>
                        {% endif %}
                    </p>
                    <div style="display:flex; gap:10px; margin-top:10px; flex-wrap: wrap;">
                        <a href="/admin/login_as/{{ u_name }}" class="btn btn-primary" style="padding:6px 12px; font-size:10px;"><i class="fa-solid fa-sign-in-alt"></i> Login As User</a>
                        <a href="/admin/delete_user/{{ u_name }}" class="btn btn-danger" style="padding:6px 12px; font-size:10px;" onclick="return confirm('Wipe all data and delete user {{ u_name }}?')"><i class="fa-solid fa-trash-alt"></i> Wipe & Delete User</a>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p style="text-align: center; opacity: 0.5; padding: 20px; font-size:13px;">No active subscriptions found.</p>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''

# --- FALLBACK DEBUGGER FOR 500 INTERNAL ERRORS ---
@app.errorhandler(500)
def handle_internal_server_error(e):
    import traceback
    return f"<h3>Flask Application 500 Crash Log:</h3><pre>{traceback.format_exc()}</pre>", 500

# --- EXTERNAL REST APIs FOR TELEGRAM BOT ---
@app.route("/api/admin/create_user", methods=["POST"])
def api_create_user():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "yuvi_secret_api_key_123")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    plan_type = data.get("plan_type", "time_bound")
    expiry = data.get("expiry", "2099-12-31T23:59")
    
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400
        
    db["users"][username] = {
        "password": password,
        "expiry": expiry if plan_type == "time_bound" else "2099-12-31T23:59",
        "plan_type": plan_type,
        "status": "active",
        "broadcast": {"message": "", "id": ""}
    }
    save_db(db)
    return jsonify({"status": "success", "message": f"User {username} created successfully via API."})

@app.route("/api/admin/delete_user", methods=["POST"])
def api_delete_user():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "yuvi_secret_api_key_123")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    username = data.get("username", "").strip()
    if username in db["users"]:
        stop_and_clean_user(username)
        return jsonify({"status": "success", "message": f"User {username} wiped and deleted."})
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route("/api/admin/list_users", methods=["POST"])
def api_list_users():
    data = request.json or {}
    api_key = data.get("api_key")
    db = load_db()
    
    admin_key = db.get("admin", {}).get("api_key", "yuvi_secret_api_key_123")
    if not api_key or api_key != admin_key:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        
    return jsonify({"status": "success", "users": db["users"]})

# --- EXPIRY & NOTIFICATION BACKEND ENDPOINTS ---
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

# --- INTEGRATED ROUTE WITH EXPIRY & NOTIFICATION ---
@app.route("/login", methods=["GET", "POST"])
def login():
    error = request.args.get("error", None)
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        db = load_db()
        
        if l_type == "admin":
            admin_data = db.get("admin", {"username": "JUBARAJ", "password": "098765"})
            if username == admin_data.get("username") and pw == admin_data.get("password"):
                session['is_admin'], session['username'] = True, username
                return redirect(url_for("admin_panel"))
            error = "Invalid Admin Credentials!"
        else:
            if username in db["users"]:
                user_data = db["users"][username]
                if user_data["password"] == pw:
                    if user_data.get("plan_type") != "permanent" and user_data.get("status") == "expired":
                        error = "Aapka access plan khatam ho chuka hai! Contact Admin."
                    else:
                        session['is_admin'], session['username'] = False, username
                        return redirect(url_for("index"))
                else:
                    error = "Incorrect Password!"
            else:
                error = "Aap registered user nahi hain! Contact Admin."
                
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/")
def index():
    if 'username' not in session: return redirect(url_for("login"))
    if session.get('is_admin'): return redirect(url_for("admin_panel"))
    
    user_name = session['username']
    db = load_db()
    
    if user_name not in db["users"] or (db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name].get("status") == "expired"):
        session.clear()
        return redirect(url_for("login", error="Aapka access plan khatam ho chuka hai! Contact Admin."))

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
            
    user_theme = db.get("themes", {}).get(user_name, {"color": "#00ffff", "size": 38, "speed": 4, "ui_mode": "normal"})
    
    if user_info.get("plan_type") == "permanent":
        expiry_display = "Lifetime Permanent"
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

# --- ADMIN HANDLERS ---
@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    admin_creds = db.get("admin", {"username": "JUBARAJ", "password": "098765", "api_key": "yuvi_secret_api_key_123"})
    return render_template_string(ADMIN_HTML, users=db["users"], admin_creds=admin_creds)

@app.route("/admin/update_creds", methods=["POST"])
def update_creds():
    if not session.get('is_admin'): return redirect(url_for("login"))
    new_user = request.form.get("admin_user", "").strip()
    new_pass = request.form.get("admin_pass", "").strip()
    
    if new_user and new_pass:
        db = load_db()
        db["admin"]["username"] = new_user
        db["admin"]["password"] = new_pass
        save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/update_api_key", methods=["POST"])
def update_api_key():
    if not session.get('is_admin'): return redirect(url_for("login"))
    new_api_key = request.form.get("api_key", "").strip()
    
    if new_api_key:
        db = load_db()
        db["admin"]["api_key"] = new_api_key
        save_db(db)
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
        db["users"][username] = {
            "password": password,
            "expiry": expiry,
            "plan_type": plan_type,
            "status": "active",
            "broadcast": {"message": "", "id": ""}
        }
        save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_user/<username>")
def delete_user(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if username in db["users"]:
        stop_and_clean_user(username)
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
    elif target in db["users"]:
        db["users"][target]["broadcast"] = broadcast_obj
        
    save_db(db)
    return redirect(url_for("admin_panel"))

# --- FILE MANAGER LOGICS ---
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

@app.route("/admin/login_as/<username>")
def login_as(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    session['username'], session['is_admin'] = username, False
    return redirect(url_for("index"))

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
