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

# --- SAFE FIREBASE STORAGE INITIALIZATION ---
if not firebase_admin._apps:
    firebase_creds_json = os.environ.get("FIREBASE_CREDS")
    if firebase_creds_json:
        try:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            project_id = creds_dict.get("project_id", "yuvi-hosting-net")
            bucket_name = f"{project_id}.appspot.com"
            firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
            print(f"Firebase Storage successfully initialized: {bucket_name}")
        except Exception as e:
            print(f"Firebase Storage Initialization Error: {e}")

# --- LOCAL DB FUNCTIONS (UPDATED FOR SUBSCRIPTION) ---
def load_db():
    if not os.path.exists(DB_FILE):
        # Users data ab ek dictionary hoga format: {"username": {"password": "...", "expiry": "YYYY-MM-DD HH:MM"}}
        default = {"user_pw": "codex123", "users": {}, "start_times": {}, "themes": {}}
        with open(DB_FILE, "w") as f: 
            json.dump(default, f, indent=4)
        return default
    with open(DB_FILE, "r") as f:
        try:
            data = json.load(f)
            if "users" not in data: data["users"] = {}
            if "user_pw" not in data: data["user_pw"] = "codex123"
            if "start_times" not in data: data["start_times"] = {}
            if "themes" not in data: data["themes"] = {}
            return data
        except:
            return {"user_pw": "codex123", "users": {}, "start_times": {}, "themes": {}}

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

# Owner / Admin Access Details
ADMIN_USER = "JUBARAJ"
ADMIN_PASS = "098765"

# --- LOGIN PAGE HTML ---
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
        .login-card { position: relative; z-index: 10; background: var(--glass); padding: 40px 30px; border-radius: 25px; width: 340px; text-align: center; border: 1px solid rgba(0, 255, 255, 0.15); backdrop-filter: blur(20px); box-shadow: 0 25px 45px rgba(0,0,0,0.5); transition: 0.4s; }
        .lock-container { width: 80px; height: 80px; background: rgba(0, 255, 255, 0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; border: 2px solid var(--primary); }
        .lock-icon { font-size: 35px; color: var(--primary); }
        h2 { font-size: 20px; margin-bottom: 25px; letter-spacing: 4px; text-transform: uppercase; background: linear-gradient(to right, #fff, var(--primary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        input, select { width: 100%; padding: 14px; margin: 10px 0; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); color: #fff; outline: none; box-sizing: border-box; }
        button { width: 100%; padding: 15px; border-radius: 12px; border: none; background: linear-gradient(45deg, var(--sec), var(--primary)); color: #fff; font-weight: bold; cursor: pointer; margin-top: 15px; text-transform: uppercase; }
        .error-msg { color: #ff4757; font-size: 13px; margin-top: 10px; font-weight: bold; }
        .get-pw { margin-top: 25px; font-size: 12px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 15px; }
        .get-pw a { color: var(--primary); text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <div id="particles-js"></div>
    <div class="login-card">
        <div class="lock-container"><i class="fa-solid fa-user-shield lock-icon"></i></div>
        <h2>System Login</h2>
        {% if error %}<div class="error-msg"><i class="fa-solid fa-triangle-exclamation"></i> {{ error }}</div>{% endif %}
        <form method="post" action="/login">
            <select name="login_type">
                <option value="user">USER ACCESS</option>
                <option value="admin">ADMIN ROOT</option>
            </select>
            <input type="text" name="username" placeholder="Enter Nickname" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Access System</button>
        </form>
        <div class="get-pw"><a href="https://t.me/ItsYuvi_LEGACY" target="_blank"><i class="fa-brands fa-telegram"></i> BUY SUBSCRIPTION / FORGOT?</a></div>
    </div>
</body>
</html>
'''

# --- UPDATED ADMIN PANEL HTML (WITH USER ADD & EXPIRY MANAGE) ---
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JUBARAJ Panel | Premium Management</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #030508; --card: rgba(22, 27, 34, 0.8); --accent: #00ffff; --text: #e6edf3; --glass: rgba(255, 255, 255, 0.05); }
        * { box-sizing: border-box; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 15px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 10px; background: var(--glass); border-radius: 15px; border: 1px solid rgba(0, 255, 255, 0.2); }
        .header h2 { font-size: 18px; color: var(--accent); margin: 0; }
        .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
        .stat-card { background: var(--card); padding: 15px; border-radius: 15px; border: 1px solid rgba(255,255,255,0.05); text-align: center; }
        .stat-card div { font-size: 18px; font-weight: bold; }
        .card { background: var(--card); padding: 15px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; }
        h3 { margin-top: 0; font-size: 16px; color: var(--accent); display: flex; align-items: center; gap: 8px; }
        .input-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        input, select { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #333; background: rgba(0,0,0,0.3); color: white; outline: none; }
        .btn { padding: 12px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-align: center; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .btn-danger { background: #ff4757; color: white; }
        .btn-logout { background: #ff4757; color: white; padding: 8px 15px; }
        .user-item { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
        .user-info { display: flex; justify-content: space-between; align-items: center; }
        .username { font-weight: bold; color: var(--accent); font-size: 16px; }
        .expiry-text { font-size: 12px; color: #ffa502; }
        .action-row { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; gap: 10px; }
    </style>
</head>
<body>
    <div class="header"><h2><i class="fa-solid fa-shield-halved"></i> JUBARAJ PAID HOSTING ROOT</h2><a href="/logout" class="btn btn-logout"><i class="fa-solid fa-power-off"></i></a></div>
    
    <div class="stats-grid">
        <div class="stat-card"><i class="fa-solid fa-users" style="color:#00ffff"></i><p>Total Paid Users</p><div>{{ users|length }}</div></div>
        <div class="stat-card"><i class="fa-solid fa-rocket" style="color:#7000ff"></i><p>Running Bots</p><div>{{ start_times|length }}</div></div>
    </div>

    <div class="card">
        <h3><i class="fa-solid fa-user-plus"></i> Create Premium User</h3>
        <form action="/admin/create_user" method="post" class="input-group">
            <input type="text" name="new_username" placeholder="Enter Unique Username" required>
            <input type="text" name="new_password" placeholder="Enter Password (Leave blank for default: {{ global_pw }})">
            <label style="font-size:12px; margin-bottom:-5px; opacity:0.8;">Subscription Expiry Date & Time:</label>
            <input type="datetime-local" name="expiry_date" required>
            <button type="submit" class="btn btn-primary"><i class="fa-solid fa-user-check"></i> Authorize & Save User</button>
        </form>
    </div>

    <div class="card">
        <h3><i class="fa-solid fa-users-gear"></i> Premium Users Directory</h3>
        {% for u_name, u_data in users.items() %}
        <div class="user-item">
            <div class="user-info">
                <span class="username"><i class="fa-solid fa-circle-user"></i> {{ u_name }}</span>
                <span class="expiry-text"><i class="fa-solid fa-clock"></i> Exp: {{ u_data.expiry }}</span>
            </div>
            
            <div class="action-row">
                <form action="/admin/change_pw" method="post" style="display:flex; gap:5px; flex: 2;">
                    <input type="hidden" name="username" value="{{ u_name }}">
                    <input type="text" name="new_pw" value="{{ u_data.password }}" style="padding:8px; font-size:12px;">
                    <button type="submit" class="btn btn-primary" style="padding:8px 12px;" title="Save Password"><i class="fa-solid fa-save"></i></button>
                </form>
                
                <a href="/admin/login_as/{{ u_name }}" class="btn" style="background:#fff; color:#000; padding:8px 12px; font-size:12px;" title="Login As User"><i class="fa-solid fa-sign-in"></i></a>
                
                <form action="/admin/delete_user" method="post" onsubmit="return confirm('Kya aap sach me is user aur iska sara hosting data delete karna chahte hain?');">
                    <input type="hidden" name="username" value="{{ u_name }}">
                    <button type="submit" class="btn btn-danger" style="padding:8px 12px;" title="Delete User Completely"><i class="fa-solid fa-user-slash"></i> Delete</button>
                </form>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

# --- LOGIN OVERWRITE WITH EXPIRY VALIDATION ---
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        db = load_db()
        
        if l_type == "admin":
            if username == ADMIN_USER and pw == ADMIN_PASS:
                session['is_admin'], session['username'] = True, ADMIN_USER
                return redirect(url_for("admin_panel"))
            else:
                error = "Wrong Admin Credentials!"
        else:
            # Check if user exists in our Paid Database
            if username in db["users"]:
                user_record = db["users"][username]
                # Validate Password
                if pw == user_record.get("password"):
                    # Check Expiry
                    expiry_str = user_record.get("expiry")
                    try:
                        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M")
                        if datetime.now() > expiry_dt:
                            error = "Aapka Plan Expire ho gaya hai! Renew ke liye Admin se sampark karein."
                        else:
                            session['is_admin'], session['username'] = False, username
                            return redirect(url_for("index"))
                    except Exception as e:
                        error = "System Configuration Error inside Expiry Date."
                else:
                    error = "Galat Password! Kripya sahi details dalein."
            else:
                error = "Aap registered user nahi hain! Please purchase a subscription."
                
    return render_template_string(LOGIN_HTML, error=error)

# --- ADMIN ACTIONS FOR PAID SYSTEM ---

@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    
    u_name = request.form.get("new_username", "").strip()
    u_pw = request.form.get("new_password", "").strip()
    expiry_input = request.form.get("expiry_date") # Format received: YYYY-MM-DDTHH:MM
    
    db = load_db()
    
    if u_name:
        if not u_pw: u_pw = db["user_pw"] # Default password fall back
        
        # Format HTML5 datetime-local string to standard readable string
        formatted_expiry = "2026-12-31 23:59"
        if expiry_input:
            formatted_expiry = expiry_input.replace("T", " ")
            
        db["users"][u_name] = {
            "password": u_pw,
            "expiry": formatted_expiry
        }
        save_db(db)
        
        # Instantly create user folder
        os.makedirs(os.path.join(UPLOAD_FOLDER, u_name), exist_ok=True)
        
    return redirect(url_for("admin_panel"))

@app.route("/admin/change_pw", methods=["POST"])
def change_pw():
    if not session.get('is_admin'): return redirect(url_for("login"))
    u_name, new_pw = request.form.get("username"), request.form.get("new_pw")
    db = load_db()
    if u_name in db["users"]:
        db["users"][u_name]["password"] = new_pw
        save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/delete_user", methods=["POST"])
def delete_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    u_name = request.form.get("username")
    
    db = load_db()
    
    # 1. Pehle user ke chalte hue saare active scripts/bots ko terminate karein
    for key, p in list(processes.items()):
        if key[0] == u_name:
            try: p.terminate()
            except: pass
            del processes[key]
            
            t_key = f"{u_name}_{key[1]}_{key[2]}"
            if t_key in db["start_times"]: del db["start_times"][t_key]

    # 2. Local JSON db se data delete karein
    if u_name in db["users"]: del db["users"][u_name]
    if u_name in db.get("themes", {}): del db["themes"][u_name]
    save_db(db)
    
    # 3. User ke uploads/projects folder ko system se delete karein
    user_dir = os.path.join(UPLOAD_FOLDER, u_name)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
        
    return redirect(url_for("admin_panel"))

# --- BASE/INDEX SAFE CHECK ---
@app.route("/")
def index():
    if 'username' not in session: return redirect(url_for("login"))
    
    user_name = session['username']
    
    # Ek fallback security check: Agar user already logged in tha, par admin ne delete/expire kar diya
    if not session.get('is_admin'):
        db = load_db()
        if user_name not in db["users"]:
            session.clear()
            return redirect(url_for("login"))
        
        # Live expiry double check during dashboard reloading
        expiry_dt = datetime.strptime(db["users"][user_name]["expiry"], "%Y-%m-%d %H:%M")
        if datetime.now() > expiry_dt:
            session.clear()
            return redirect(url_for("login"))

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
            
    db = load_db()
    user_theme = db.get("themes", {}).get(user_name, {"color": "#00ffff", "size": 38, "speed": 4})
    
    return render_template("index.html", 
                           apps=apps_list, 
                           username=user_name,
                           user_color=user_theme.get("color", "#00ffff"),
                           user_size=user_theme.get("size", 38),
                           user_speed=user_theme.get("speed", 4))

# --- DUMMY/EXISTING EXTRA METHODS PRESERVATION ---
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

@app.route("/admin/global_pw", methods=["POST"])
def global_pw():
    db = load_db()
    db["user_pw"] = request.form.get("global_pw")
    save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/login_as/<username>")
def login_as(username):
    session['username'], session['is_admin'] = username, False
    return redirect(url_for("index"))

def bg_smart_scan_and_run(user_name, name, app_dir, extract_dir):
    log_path = os.path.join(app_dir, "logs.txt")
    req_file_path = os.path.join(extract_dir, "requirements.txt")
    with open(log_path, "a") as log_file:
        if not os.path.exists(req_file_path):
            try:
                subprocess.run(["pipreqs", extract_dir, "--force"], stdout=log_file, stderr=log_file, text=True, check=True)
            except: pass
        if os.path.exists(req_file_path) and os.path.getsize(req_file_path) > 0:
            try:
                subprocess.run(["pip", "install", "-r", "requirements.txt", "--disable-pip-version-check"], cwd=extract_dir, stdout=log_file, stderr=log_file, text=True, check=True)
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
            except Exception as e: print(f"Firebase Storage Backup Error: {e}")
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
        except Exception as e: print(f"Firebase Storage Delete Error: {e}")
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3522, debug=True)
