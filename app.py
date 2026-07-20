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
            "admin": {"username": "JUBARAJ", "password": "098765"}
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
    
    # User ke running background processes ko kill karna
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
                
    # Local application upload data wipe karna
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
            print(f"[AUTO-TERMINATE] Local folder deleted for expired user: {user_name}")
        except Exception as e:
            print(f"Error deleting user directory: {e}")
            
    # Firebase Cloud storage clean karna
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blobs = bucket.list_blobs(prefix=f"backups/{user_name}/")
            for blob in blobs:
                blob.delete()
            print(f"[AUTO-TERMINATE] Firebase backups cleared for: {user_name}")
        except Exception as e:
            print(f"Firebase clean error: {e}")
            
    # Database settings elements clean karna
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
        :root { --bg: #030508; --primary: #00ffff; --sec: #7000ff; --glass: rgba(255, 255, 255, 0.03); }
        body { background: var(--bg); color: white; font-family: 'Orbitron', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; padding: 15px; }
        
        .login-box-wrapper {
            position: relative;
            width: 100%;
            max-width: 420px;
            padding: 3px;
            border-radius: 25px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.05);
            box-shadow: 0 25px 45px rgba(0,0,0,0.5);
        }
        
        .login-box-wrapper::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(transparent, transparent, transparent, var(--primary));
            animation: animateBorder 4s linear infinite;
        }
        
        @keyframes animateBorder {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .login-card { 
            position: relative; 
            z-index: 10; 
            background: #090d16; 
            padding: 40px 35px; 
            border-radius: 23px; 
            width: 100%;
            text-align: center; 
            backdrop-filter: blur(20px); 
        }
        
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
    <title>Owner Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;800&family=Rajdhani:wght@600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root { 
            --bg-dark: #030508; 
            --panel-bg: #0c1223; 
            --card-bg: rgba(10, 15, 28, 0.95); 
            --neon-blue: #00ffff; 
            --neon-purple: #7000ff; 
            --text-light: #f1f5f9; 
            --border-light: rgba(0, 255, 255, 0.15);
        }
        body { 
            background: radial-gradient(circle at center, #070c1a 0%, var(--bg-dark) 100%); 
            color: var(--text-light); 
            font-family: 'Orbitron', sans-serif; 
            padding: 15px; 
        }
        .container { max-width: 1100px; margin: 0 auto; }
        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 20px; 
            padding: 12px 20px; 
            background: linear-gradient(135deg, rgba(12, 18, 35, 0.8), rgba(6, 9, 19, 0.9)); 
            border-radius: 15px; 
            border: 1px solid var(--border-light); 
            box-shadow: 0 0 15px rgba(0, 255, 255, 0.1);
        }
        .header h2 { 
            font-size: 16px; 
            letter-spacing: 3px;
            font-weight: 800;
            background: linear-gradient(to right, #ffffff, var(--neon-blue)); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
            text-transform: uppercase;
        }
        .grid { display: grid; grid-template-columns: 1fr; gap: 15px; margin-bottom: 15px; }
        @media(min-width: 768px) { .grid { grid-template-columns: 1fr 1fr; } }
        .card { 
            background: var(--card-bg); 
            padding: 15px 20px; 
            border-radius: 15px; 
            border: 1px solid rgba(0, 255, 255, 0.08); 
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            backdrop-filter: blur(10px);
            transition: border-color 0.3s ease;
        }
        .card:hover { border-color: rgba(0, 255, 255, 0.25); }
        h3 { 
            margin-bottom: 12px; 
            font-size: 12px; 
            display: flex; 
            align-items: center; 
            gap: 8px; 
            color: var(--neon-blue); 
            text-transform: uppercase; 
            letter-spacing: 1.5px;
            font-family: 'Rajdhani', sans-serif;
        }
        .input-group { display: flex; flex-direction: column; gap: 10px; }
        input, select, textarea { 
            width: 100%; 
            padding: 8px 12px; 
            border-radius: 8px; 
            border: 1px solid rgba(255,255,255,0.08); 
            background: #040710; 
            color: #fff; 
            outline: none; 
            font-size: 12px;
            font-family: sans-serif;
            transition: all 0.2s ease;
        }
        input:focus, select:focus, textarea:focus {
            border-color: var(--neon-blue);
            box-shadow: 0 0 8px rgba(0, 255, 255, 0.15);
        }
        .btn { 
            padding: 8px 15px; 
            border-radius: 8px; 
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
            box-shadow: 0 2px 10px rgba(0, 255, 255, 0.15);
        }
        .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 15px rgba(0, 255, 255, 0.35); }
        .btn-danger { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
        .btn-danger:hover { background: #dc2626; color: #fff; transform: translateY(-1px); }
        .btn-logout { background: rgba(239, 68, 68, 0.1); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25); padding: 6px 12px; font-size: 10px; }
        .btn-logout:hover { background: #ef4444; color: white; }
        .user-item { background: rgba(4, 7, 16, 0.7); border-radius: 10px; padding: 12px 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.02); }
        .user-item:hover { border-color: rgba(112, 0, 255, 0.3); }
        .user-info { display: flex; justify-content: space-between; align-items: center; }
        .username { font-weight: bold; font-size: 13px; color: var(--text-light); display: flex; align-items: center; gap: 6px; }
        .status-badge { padding: 2px 8px; border-radius: 12px; font-size: 9px; font-weight: bold; letter-spacing: 0.5px; text-transform: uppercase; }
        .status-active { background: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25); }
        .status-expired { background: rgba(239, 68, 68, 0.12); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25); }
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
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2><i class="fa-solid fa-crown" style="color:var(--neon-blue);"></i> OWNER PANEL</h2>
            <a href="/logout" class="btn btn-logout"><i class="fa-solid fa-power-off"></i> LOGOUT</a>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3><i class="fa-solid fa-user-plus"></i> NEW SUBSCRIPTION</h3>
                <form action="/admin/create_user" method="post" class="input-group">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <select name="plan_type" onchange="toggleExpiryInput(this.value)">
                        <option value="time_bound">Time Bound (Auto Deletion)</option>
                        <option value="permanent">Permanent (Lifetime)</option>
                    </select>
                    <div id="exp_input_wrapper">
                        <label style="font-size:10px; color: var(--neon-blue); display:block; margin-bottom:3px; font-family:'Rajdhani';">EXPIRY DATE & TIME:</label>
                        <input type="datetime-local" id="expiry_date_input" name="expiry" required>
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;">Create Account</button>
                </form>
            </div>

            <div class="card">
                <h3><i class="fa-solid fa-bullhorn"></i> BROADCAST STATION</h3>
                <form action="/admin/broadcast" method="post" class="input-group">
                    <select name="target_user">
                        <option value="ALL_USERS">--- GLOBAL BROADCAST ---</option>
                        {% for u_name in users.keys() %}
                        <option value="{{ u_name }}">Direct to: {{ u_name }}</option>
                        {% endfor %}
                    </select>
                    <textarea name="message" rows="3" placeholder="Enter Alert message details..." required></textarea>
                    <button type="submit" class="btn btn-primary" style="width:100%;"><i class="fa-solid fa-paper-plane"></i> Dispatch alert</button>
                </form>
            </div>
        </div>

        <div class="grid">
            <div class="card" style="grid-column: 1 / -1;">
                <h3><i class="fa-solid fa-key"></i> UPDATE ADMIN ROOT</h3>
                <form action="/admin/update_creds" method="post" style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 140px;">
                        <input type="text" name="admin_user" value="{{ admin_creds.username }}" placeholder="Admin User" required>
                    </div>
                    <div style="flex: 1; min-width: 140px;">
                        <input type="password" name="admin_pass" placeholder="New Password" required>
                    </div>
                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-save"></i> Save Admin</button>
                </form>
            </div>
        </div>

        <div class="card" style="margin-top: 5px;">
            <h3><i class="fa-solid fa-users-gear"></i> ACTIVE SUBSCRIBERS</h3>
            {% if users %}
                {% for u_name, u_info in users.items() %}
                <div class="user-item">
                    <div class="user-info">
                        <span class="username"><i class="fa-solid fa-user-circle"></i> {{ u_name }} <span style="font-size:10px; opacity:0.5; font-family:sans-serif;">(P: {{ u_info.password }})</span></span>
                        <div>
                            <span class="status-badge {% if u_info.status == 'active' %}status-active{% else %}status-expired{% endif %}">
                                {{ u_info.status|upper }}
                            </span>
                        </div>
                    </div>
                    <p style="font-size:11px; margin: 8px 0; opacity: 0.7; display: flex; align-items: center; gap: 10px; font-family:sans-serif;">
                        <span>Plan: <b style="color:var(--neon-blue)">{{ u_info.get('plan_type','time_bound')|upper }}</b></span>
                        {% if u_info.get('plan_type') != 'permanent' %}
                        <span>Expiry: <b style="color:var(--neon-purple)">{{ u_info.expiry.replace('T', ' ') if u_info.expiry else 'N/A' }}</b></span>
                        {% endif %}
                    </p>
                    <div style="display:flex; gap:8px; margin-top:10px; flex-wrap: wrap;">
                        <a href="/admin/login_as/{{ u_name }}" class="btn btn-primary" style="padding:4px 10px; font-size:10px;"><i class="fa-solid fa-sign-in-alt"></i> Login As</a>
                        <a href="/admin/delete_user/{{ u_name }}" class="btn btn-danger" style="padding:4px 10px; font-size:10px;" onclick="return confirm('Wipe data and delete user?')"><i class="fa-solid fa-trash-alt"></i> Delete</a>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p style="text-align: center; opacity: 0.5; padding: 15px; font-size:12px;">No subscriptions exist currently.</p>
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
            
    # Theme persistent state recovery
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
    admin_creds = db.get("admin", {"username": "JUBARAJ", "password": "098765"})
    return render_template_string(ADMIN_HTML, users=db["users"], admin_creds=admin_creds)

@app.route("/admin/update_creds", methods=["POST"])
def update_creds():
    if not session.get('is_admin'): return redirect(url_for("login"))
    new_user = request.form.get("admin_user", "").strip()
    new_pass = request.form.get("admin_pass", "").strip()
    
    if new_user and new_pass:
        db = load_db()
        db["admin"] = {"username": new_user, "password": new_pass}
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

# --- FILE MANAGER LOGICS PRESERVED ---
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
