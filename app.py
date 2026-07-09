from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io, threading
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, storage

app = Flask(__name__, template_folder=".")
app.secret_key = "YUVI-HOSTING-PRO"

UPLOAD_FOLDER = "uploads"
DB_FILE = "database.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}

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

# --- DB STRUCTURE UPGRADE FOR PAID SYSTEM ---
def load_db():
    if not os.path.exists(DB_FILE):
        default = {"users": {}, "start_times": {}, "themes": {}}
        with open(DB_FILE, "w") as f: 
            json.dump(default, f, indent=4)
        return default
    with open(DB_FILE, "r") as f:
        try:
            data = json.load(f)
            if "users" not in data: data["users"] = {}
            if "start_times" not in data: data["start_times"] = {}
            if "themes" not in data: data["themes"] = {}
            return data
        except:
            return {"users": {}, "start_times": {}, "themes": {}}

def save_db(data):
    try:
        temp_db = DB_FILE + ".tmp"
        with open(temp_db, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_db, DB_FILE)
        return True
    except Exception as e:
        print(f"Local DB Save Error: {e}")
        return False

ADMIN_USER = "JUBARAJ"
ADMIN_PASS = "098765"

# --- EXPIRY TRACKER & AUTO-STOPPER BACKGROUND THREAD ---
def stop_and_clean_user(user_name):
    """User ke chal rahe apps ko stop karta hai aur uska sara hosted data reset/delete karta hai."""
    db = load_db()
    
    # 1. Active background processes ko terminate karein
    for key, p in list(processes.items()):
        if key[0] == user_name:
            try: 
                p.terminate()
            except: 
                pass
            del processes[key]
            t_key = f"{user_name}_{key[1]}_{key[2]}"
            if t_key in db["start_times"]: 
                del db["start_times"][t_key]
                
    # 2. Local uploads data directory completely clear/reset karein
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir)
            print(f"[DATA RESET] Local folder deleted for expired user: {user_name}")
        except Exception as e:
            print(f"Error deleting user directory: {e}")
            
    # 3. Firebase Storage se user ke backups delete karein
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blobs = bucket.list_blobs(prefix=f"backups/{user_name}/")
            for blob in blobs:
                blob.delete()
            print(f"[FIREBASE RESET] Firebase backups cleared for expired user: {user_name}")
        except Exception as e:
            print(f"Firebase data clean error: {e}")
            
    # 4. User settings aur themes database se clear karein
    if user_name in db.get("themes", {}):
        del db["themes"][user_name]
        
    save_db(db)

def enforcement_loop():
    while True:
        try:
            db = load_db()
            # standard UNIX timestamp current system ka
            now = time.time() 
            changed = False
            for username, info in list(db["users"].items()):
                # Permanent plan check bypass
                if info.get("plan_type") == "permanent":
                    if info.get("status") != "active":
                        db["users"][username]["status"] = "active"
                        changed = True
                    continue
                    
                expiry_str = info.get("expiry")
                if expiry_str:
                    try:
                        # Dono datetime formats (%Y-%m-%dT%H:%M aur %Y-%m-%dT%H:%M:%S) ko handle karne ke liye safe dynamic parsing
                        if len(expiry_str) > 16:
                            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M:%S")
                        else:
                            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M")
                        
                        # Local time/System time ke accurate context me timestamp conversion
                        expiry_ts = expiry_dt.timestamp()
                    except Exception as parse_err:
                        print(f"Date Parse Error for {username}: {parse_err}")
                        continue

                    if now > expiry_ts and info.get("status") != "expired":
                        db["users"][username]["status"] = "expired"
                        changed = True
                        # Sabhi apps stop karein aur hosted data completely delete karein
                        stop_and_clean_user(username)
                        print(f"[PAID SYSTEM] Access expired and data wiped for user: {username}.")
            if changed:
                save_db(db)
        except Exception as e:
            print(f"Enforcement Loop Error: {e}")
        time.sleep(10) # Scanner frequency optimized to 10 seconds

threading.Thread(target=enforcement_loop, daemon=True).start()

# --- UI LOGINS ---
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | YUVI CODEX</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; }
        :root { --bg: #030508; --primary: #00ffff; --sec: #7000ff; --glass: rgba(255, 255, 255, 0.03); }
        body { background: var(--bg); color: white; font-family: 'Orbitron', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; padding: 15px; }
        
        /* Animated Border Outer Box Container */
        .login-box-wrapper {
            position: relative;
            width: 100%;
            max-width: 420px;
            padding: 3px; /* border thickness control */
            border-radius: 25px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.05);
            box-shadow: 0 25px 45px rgba(0,0,0,0.5);
        }
        
        /* Rotating Blue Glow Line Effect */
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
            background: #090d16; /* solid dark premium tint background to hide inner rotation */
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
    <title>JUBARAJ Panel | Ultra Hosting</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root { --bg: #030508; --card: rgba(22, 27, 34, 0.8); --accent: #00ffff; --text: #e6edf3; --glass: rgba(255, 255, 255, 0.05); }
        body { background: var(--bg); color: var(--text); font-family: sans-serif; padding: 15px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 10px; background: var(--glass); border-radius: 15px; border: 1px solid rgba(0, 255, 255, 0.2); width: 100%; }
        .header h2 { font-size: 18px; color: var(--accent); }
        .grid { display: grid; grid-template-columns: 1fr; gap: 20px; width: 100%; }
        @media(min-width: 768px) { .grid { grid-template-columns: 1fr 1fr; } }
        .card { background: var(--card); padding: 15px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; width: 100%; }
        h3 { margin-top: 0; font-size: 16px; color: var(--accent); }
        .input-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; width: 100%; }
        input, select, textarea { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #333; background: rgba(0,0,0,0.3); color: white; outline: none; }
        .btn { padding: 12px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none;}
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .btn-danger { background: #ff4757; color: white; }
        .user-item { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
        .user-info { display: flex; justify-content: space-between; align-items: center; }
        .username { font-weight: bold; color: var(--accent); }
        .status-badge { padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: bold; }
        .status-active { background: rgba(46, 213, 115, 0.2); color: #2ed573; }
        .status-expired { background: rgba(255, 71, 87, 0.2); color: #ff4757; }
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
    <div class="header"><h2><i class="fa-solid fa-shield-halved"></i> JUBARAJ PAID PANEL</h2><a href="/logout" class="btn btn-danger"><i class="fa-solid fa-power-off"></i></a></div>
    
    <div class="grid">
        <div class="card">
            <h3><i class="fa-solid fa-user-plus"></i> Create New Paid User</h3>
            <form action="/admin/create_user" method="post" class="input-group">
                <input type="text" name="username" placeholder="Username / Nickname" required>
                <input type="password" name="password" placeholder="Set Access Password" required>
                <select name="plan_type" onchange="toggleExpiryInput(this.value)">
                    <option value="time_bound">Time Bound Plan (Standard)</option>
                    <option value="permanent">Permanent Plan (Lifetime Access)</option>
                </select>
                <div id="exp_input_wrapper">
                    <label style="font-size:12px; color: var(--accent); display:block; margin-bottom:5px;">Access Valid Till (Date & Time):</label>
                    <input type="datetime-local" id="expiry_date_input" name="expiry" required>
                </div>
                <button type="submit" class="btn btn-primary">Grant & Generate Access</button>
            </form>
        </div>

        <div class="card">
            <h3><i class="fa-solid fa-bullhorn"></i> Push Notification / Broadcast</h3>
            <form action="/admin/broadcast" method="post" class="input-group">
                <select name="target_user">
                    <option value="ALL_USERS">--- BROADCAST TO ALL USERS ---</option>
                    {% for u_name in users.keys() %}
                    <option value="{{ u_name }}">Only Alert: {{ u_name }}</option>
                    {% endfor %}
                </select>
                <textarea name="message" rows="3" placeholder="Type system alert / text notice here..." required></textarea>
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-paper-plane"></i> Send Notification</button>
            </form>
        </div>
    </div>

    <div class="card">
        <h3><i class="fa-solid fa-users-gear"></i> Managed Paid Subscriptions</h3>
        {% for u_name, u_info in users.items() %}
        <div class="user-item">
            <div class="user-info">
                <span class="username"><i class="fa-solid fa-user"></i> {{ u_name }} (Pass: {{ u_info.password }})</span>
                <div>
                    <span class="status-badge {% if u_info.status == 'active' %}status-active{% else %}status-expired{% endif %}">
                        {{ u_info.status|upper }}
                    </span>
                </div>
            </div>
            <p style="font-size:12px; margin: 8px 0; opacity: 0.8;">
                <i class="fa-solid fa-clock"></i> Type: <b>{{ u_info.get('plan_type','time_bound')|upper }}</b> 
                {% if u_info.get('plan_type') != 'permanent' %}
                | Expiry: <b>{{ u_info.expiry.replace('T', ' ') }}</b>
                {% endif %}
            </p>
            <div style="display:flex; gap:10px; margin-top:10px;">
                <a href="/admin/login_as/{{ u_name }}" class="btn btn-primary" style="padding:5px 10px; font-size:12px;">Login As</a>
                <a href="/admin/delete_user/{{ u_name }}" class="btn btn-danger" style="padding:5px 10px; font-size:12px;" onclick="return confirm('Pura data delete ho jayega, continue?')">Terminate & Delete User</a>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

# --- EXPIRY & NOTIFICATION BACKEND ENDPOINTS ---
@app.route("/api/get_alert")
def get_alert():
    if 'username' not in session: return jsonify({"message": "", "id": ""})
    user_name = session['username']
    db = load_db()
    
    # Real-time check inside current dynamic requests:
    if not session.get('is_admin') and user_name in db["users"]:
        u_info = db["users"][user_name]
        if u_info.get("plan_type") != "permanent" and u_info.get("status") == "expired":
            return jsonify({"expired_kick": True})
            
    broadcast_data = db["users"].get(user_name, {}).get("broadcast", "")
    if isinstance(broadcast_data, dict):
        msg = broadcast_data.get("message", "")
        msg_id = broadcast_data.get("id", "")
    else:
        msg = broadcast_data
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
    error = request.args.get("error", None) # Read automatic kicked status parameter
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        db = load_db()
        
        if l_type == "admin":
            if username == ADMIN_USER and pw == ADMIN_PASS:
                session['is_admin'], session['username'] = True, ADMIN_USER
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
    user_name = session['username']
    
    db = load_db()
    user_info = db["users"].get(user_name, {})
    
    if not session.get('is_admin') and user_name in db["users"]:
        if user_info.get("plan_type") != "permanent" and user_info.get("status") == "expired":
            session.clear()
            return redirect(url_for("login", error="Aapka access plan khatam ho chuka hai! Contact Admin."))

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
            
    user_theme = db.get("themes", {}).get(user_name, {"color": "#00ffff", "size": 38, "speed": 4})
    
    if user_info.get("plan_type") == "permanent":
        expiry_display = "Lifetime Permanent"
    else:
        expiry_display = user_info.get("expiry", "N/A").replace("T", " ")

    return render_template("index.html", 
                           apps=apps_list, 
                           username=user_name,
                           plan_expiry=expiry_display,
                           user_color=user_theme.get("color", "#00ffff"),
                           user_size=user_theme.get("size", 38),
                           user_speed=user_theme.get("speed", 4))

# --- ADMIN HANDLERS ---
@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    return render_template_string(ADMIN_HTML, users=db["users"])

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
        del db["users"][username]
        save_db(db)
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
    extract_dir = os.path.join(UPLOAD_FOLDER, session['username'], name, "extracted")
    files = []
    if os.path.exists(extract_dir):
        for root, _, filenames in os.walk(extract_dir):
            for f in filenames: files.append(os.path.relpath(os.path.join(root, f), extract_dir))
    return jsonify({"files": files})

@app.route("/read_file", methods=["POST"])
def read_content():
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f: return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    with open(path, "w", encoding="utf-8") as f: f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    if os.path.exists(path): os.remove(path)
    return jsonify({"status": "deleted"})

@app.route("/save_theme", methods=["POST"])
def save_theme():
    if 'username' not in session: return jsonify({"status": "unauthorized"}), 401
    user_name = session['username']
    data = request.json
    db = load_db()
    if "themes" not in db: db["themes"] = {}
    db["themes"][user_name] = {"color": data.get("color", "#00ffff"), "size": int(data.get("size", 38)), "speed": int(data.get("speed", 4))}
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
            except: pass
        if os.path.exists(req_file_path) and os.path.getsize(req_file_path) > 0:
            try: subprocess.run(["pip", "install", "-r", "requirements.txt", "--disable-pip-version-check"], cwd=extract_dir, stdout=log_file, stderr=log_file, text=True, check=True)
            except: pass
    for f in os.listdir(extract_dir):
        file_path = os.path.join(extract_dir, f)
        if os.path.isfile(file_path) and (f.endswith('.py') or f.endswith('.js')):
            process_key = (user_name, name, f)
            if process_key not in processes or processes[process_key].poll() is not None:
                log_file_handle = open(log_path, "a")
                cmd = ["python", f] if f.endswith('.py') else ["node", f]
                processes[process_key] = subprocess.Popen(cmd, cwd=extract_dir, stdout=log_file_handle, stderr=log_file_handle, text=True)
                db = load_db()
                db["start_times"][f"{user_name}_{name}_{f}"] = int(time.time() * 1000)
                save_db(db)

@app.route("/run/<name>")
def run(name):
    user_name = session['username']
    db = load_db()
    if user_name in db["users"] and db["users"][user_name].get("plan_type") != "permanent" and db["users"][user_name]["status"] == "expired":
        return redirect(url_for("index"))
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    extract_dir = os.path.join(app_dir, "extracted")
    if os.path.exists(extract_dir):
        threading.Thread(target=bg_smart_scan_and_run, args=(user_name, name, app_dir, extract_dir)).start()
    return redirect(url_for("index"))

@app.route("/get_log/<name>")
def get_log(name):
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
    user_name = session.get('username')
    db = load_db()
    for key, p in list(processes.items()):
        if key[0] == user_name and key[1] == name:
            try: p.terminate()
            except: pass
            del processes[key]
            t_key = f"{user_name}_{name}_{key[2]}"
            if t_key in db["start_times"]: del db["start_times"][t_key]
    save_db(db)
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
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
            except: pass
        extract_dir = os.path.join(user_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extract_dir)
        os.remove(zip_path)
    return redirect(url_for("index"))

@app.route("/download/<name>")
def download(name):
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
    user_name = session.get('username')
    stop(name)
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    if os.path.exists(app_dir): shutil.rmtree(app_dir)
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blob = bucket.blob(f"backups/{user_name}/{name}.zip")
            if blob.exists(): blob.delete()
        except: pass
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3522, debug=True)
