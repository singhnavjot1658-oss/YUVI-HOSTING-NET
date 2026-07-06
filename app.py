from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io, sys
import firebase_admin
from firebase_admin import credentials, db
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='.')

# Secret key ko strong aur fallback secure banaya hai
app.secret_key = os.environ.get("SECRET_KEY", "YUVRAJ_HOSTING_PRO_SECURE_RANDOM_99X")

# --- RENDER PERSISTENT DISK CONFIGURATION ---
if os.path.exists("/data"):
    BASE_DIR = "/data"
    print("Running on Render with Persistent Disk mounted.")
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    print("Running on Local Environment.")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_FILE = os.path.join(BASE_DIR, "database.json")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Helper function: Path Traversal Attack se bachne ke liye validation
def is_safe_path(base_dir, path):
    matchpath = os.path.realpath(path)
    base_dir_real = os.path.realpath(base_dir)
    return base_dir_real == matchpath or matchpath.startswith(base_dir_real + os.sep)

# --- FIREBASE INITIALIZATION ---
FIREBASE_DB_URL = "https://yuvi-hosting-default-rtdb.firebaseio.com/"

try:
    if os.path.exists("firebase-key.json"):
        cred = credentials.Certificate("firebase-key.json")
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DB_URL
        })
        print("Firebase connected successfully!")
    else:
        print("firebase-key.json not found! Running in local DB fallback mode.")
except Exception as e:
    print(f"Firebase connection failed: {e}. Falling back to local DB.")

# Global process controller dictionary
processes = {}

def load_db():
    default = {"user_pw": "yuvi123", "users": {}, "start_times": {}}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                if "users" not in data: data["users"] = {}
                if "user_pw" not in data: data["user_pw"] = "yuvi123"
                if "start_times" not in data: data["start_times"] = {}
                default = data
        except:
            pass

    try:
        ref = db.reference("hosting_db")
        firebase_data = ref.get()
        if firebase_data:
            if "users" not in firebase_data: firebase_data["users"] = {}
            if "user_pw" not in firebase_data: firebase_data["user_pw"] = "yuvi123"
            if "start_times" not in firebase_data: firebase_data["start_times"] = {}
            return firebase_data
    except Exception as e:
        print(f"Could not load from Firebase: {e}")
        
    return default

def save_db(data):
    temp_db = DB_FILE + ".tmp"
    with open(temp_db, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(temp_db, DB_FILE)
    
    try:
        ref = db.reference("hosting_db")
        ref.set(data)
    except Exception as e:
        print(f"Could not save to Firebase: {e}")

# --- OWNER / ADMIN CREDENTIALS ---
ADMIN_USER = os.environ.get("ADMIN_USER", "JUBARAJ")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "098765")

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
            <input type="text" name="username" placeholder="Enter Nickname" required>
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

# --- ADMIN PANEL HTML ---
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
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 15px; min-height: 100vh; overflow-x: hidden; position: relative; }
        .header { display: flex; flex-direction: row; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 10px; background: var(--glass); border-radius: 15px; backdrop-filter: blur(10px); border: 1px solid rgba(0, 255, 255, 0.2); }
        .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
        .stat-card { background: var(--card); padding: 15px; border-radius: 15px; border: 1px solid rgba(255,255,255,0.05); text-align: center; }
        .stat-card i { font-size: 20px; color: var(--accent); margin-bottom: 5px; }
        .stat-card p { font-size: 12px; margin: 5px 0; opacity: 0.7; }
        .stat-card div { font-size: 18px; font-weight: bold; }
        .card { background: var(--card); padding: 15px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; }
        h3 { margin-top: 0; font-size: 16px; color: var(--accent); display: flex; align-items: center; gap: 8px; }
        .input-group { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        input { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #333; background: rgba(0,0,0,0.3); color: white; outline: none; }
        .btn { padding: 12px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 14px; }
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .user-item { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
        .user-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .username { font-weight: bold; color: var(--accent); font-size: 16px; }
        .project-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0; }
        .project-tag { background: rgba(0,255,255,0.1); color: var(--accent); padding: 4px 10px; border-radius: 6px; font-size: 11px; }
        .action-row { display: flex; gap: 10px; margin-top: 10px; }
        .action-row form { flex: 2; }
        .action-row .btn-login { flex: 1; background: #fff; color: #000; font-size: 12px; font-weight: bold; text-decoration: none; border-radius: 10px; display: flex; align-items: center; justify-content: center; }
    </style>
</head>
<body>
    <div class="header">
        <div style="color: var(--accent); font-size: 13px; letter-spacing: 2px;">Y U V I  H O S T I N G (ADMIN)</div>
        <a href="/logout" style="color:#ff4d4d; font-size:18px;"><i class="fa-solid fa-power-off"></i></a>
    </div>
    <div class="stats-grid">
        <div class="stat-card"><i class="fa-solid fa-users"></i><p>Users</p><div>{{ users|length }}</div></div>
        <div class="stat-card"><i class="fa-solid fa-rocket"></i><p>Active</p><div>{{ start_times|length }}</div></div>
    </div>
    <div class="card">
        <h3><i class="fa-solid fa-gears"></i> Default User Password</h3>
        <form action="/admin/global_pw" method="post" class="input-group">
            <input type="text" name="global_pw" value="{{ global_pw }}">
            <button type="submit" class="btn btn-primary">Update Default</button>
        </form>
    </div>
    <div class="card">
        <h3><i class="fa-solid fa-user-gear"></i> User Management</h3>
        {% for u_name, u_pw in users.items() %}
        <div class="user-item">
            <div class="user-info"><span class="username"><i class="fa-solid fa-circle-user"></i> {{ u_name }}</span></div>
            <div class="project-tags">
                {% set count = namespace(value=0) %}
                {% for p_key in start_times.keys() %}
                    {% if p_key.startswith(u_name + '_') %}
                        <span class="project-tag">● {{ p_key.split('_')[1] }}</span>
                        {% set count.value = count.value + 1 %}
                    {% endif %}
                {% endfor %}
                {% if count.value == 0 %}<span style="color:#666; font-size:11px;">No active bots</span>{% endif %}
            </div>
            <div class="action-row">
                <form action="/admin/change_pw" method="post" style="display:flex; gap:5px;">
                    <input type="hidden" name="username" value="{{ u_name }}">
                    <input type="text" name="new_pw" value="{{ u_pw }}" style="padding:8px; font-size:12px;">
                    <button type="submit" class="btn btn-primary" style="padding:8px 12px;"><i class="fa-solid fa-save"></i></button>
                </form>
                <a href="/admin/login_as/{{ u_name }}" class="btn btn-login"><i class="fa-solid fa-sign-in"></i> LOGIN</a>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

# --- API & SECURED ROUTES ---

@app.route("/list_files/<name>")
def list_files(name):
    if 'username' not in session: return jsonify({"files": []})
    user_name = session['username']
    
    extract_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, name, "extracted"))
    if not is_safe_path(os.path.join(UPLOAD_FOLDER, user_name), extract_dir):
        return jsonify({"files": []})
        
    files = []
    if os.path.exists(extract_dir):
        for root, _, filenames in os.walk(extract_dir):
            for f in filenames:
                rel = os.path.relpath(os.path.join(root, f), extract_dir)
                files.append(rel)
    return jsonify({"files": files})

@app.route("/read_file", methods=["POST"])
def read_content():
    if 'username' not in session: return jsonify({"content": "Unauthorized"})
    user_name = session['username']
    data = request.json
    
    extract_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted"))
    path = os.path.abspath(os.path.join(extract_dir, data['filename']))
    
    if not is_safe_path(extract_dir, path):
        return jsonify({"content": "Security Error: Path Prohibited"})
        
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    if 'username' not in session: return jsonify({"status": "failed"})
    user_name = session['username']
    data = request.json
    
    extract_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted"))
    path = os.path.abspath(os.path.join(extract_dir, data['filename']))
    
    if not is_safe_path(extract_dir, path):
        return jsonify({"status": "failed", "message": "Prohibited Path"})
        
    with open(path, "w", encoding="utf-8") as f:
        f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    if 'username' not in session: return jsonify({"status": "failed"})
    user_name = session['username']
    data = request.json
    
    extract_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted"))
    path = os.path.abspath(os.path.join(extract_dir, data['filename']))
    
    if not is_safe_path(extract_dir, path):
        return jsonify({"status": "failed"})
        
    if os.path.exists(path): 
        os.remove(path)
    return jsonify({"status": "deleted"})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = secure_filename(request.form.get("username", "").strip())
        pw = request.form.get("password", "").strip()
        db_data = load_db()
        
        if l_type == "admin":
            if username == ADMIN_USER and pw == ADMIN_PASS:
                session['is_admin'], session['username'] = True, ADMIN_USER
                return redirect(url_for("admin_panel"))
            else:
                return redirect(url_for("login"))
        else:
            if username == ADMIN_USER or not username:
                return redirect(url_for("login"))
                
            if username not in db_data["users"]:
                db_data["users"][username] = db_data["user_pw"] 
                save_db(db_data)
                
            if pw == db_data["users"].get(username):
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
    
    db_data = load_db()
    
    for name in os.listdir(user_dir):
        if os.path.isdir(os.path.join(user_dir, name)):
            p = processes.get((user_name, name))
            is_running = (p and p.poll() is None) or f"{user_name}_{name}" in db_data.get("start_times", {})
            apps_list.append({"name": name, "running": is_running})
            
    try:
        return render_template("index.html", apps=apps_list, username=user_name)
    except:
        return "<h3>Index HTML missing from templates folder. Please create templates/index.html</h3>"

@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db_data = load_db()
    return render_template_string(ADMIN_HTML, users=db_data["users"], start_times=db_data["start_times"], global_pw=db_data["user_pw"])

@app.route("/admin/global_pw", methods=["POST"])
def global_pw():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db_data = load_db()
    db_data["user_pw"] = request.form.get("global_pw")
    save_db(db_data)
    return redirect(url_for("admin_panel"))

@app.route("/admin/change_pw", methods=["POST"])
def change_pw():
    if not session.get('is_admin'): return redirect(url_for("login"))
    u_name, new_pw = request.form.get("username"), request.form.get("new_pw")
    db_data = load_db()
    if u_name in db_data["users"]:
        db_data["users"][u_name] = new_pw
        save_db(db_data)
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
    
    # Check if process is already running in local process context
    p = processes.get((user_name, name))
    if p and p.poll() is None:
        return redirect(url_for("index"))

    main_file = next((f for f in ["main.py", "bot.py", "app.py", "index.js", "server.js"] if os.path.exists(os.path.join(extract_dir, f))), None)
    if main_file:
        log_path = os.path.join(app_dir, "logs.txt")
        
        # Open file carefully using context manager to avoid file lockups
        with open(log_path, "a", encoding="utf-8") as log_file:
            if main_file.endswith('.py'):
                req_path = os.path.join(extract_dir, "requirements.txt")
                if os.path.exists(req_path):
                    log_file.write("\n[SYSTEM] Installing pip packages from requirements.txt...\n")
                    log_file.flush()
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], stdout=log_file, stderr=log_file)
                else:
                    log_file.write("\n[SYSTEM] requirements.txt missing! Scanning imports in file...\n")
                    log_file.flush()
                    try:
                        package_mapping = {
                            "telebot": "pyTelegramBotAPI", "PIL": "Pillow", "bs4": "beautifulsoup4",
                            "telegram": "python-telegram-bot", "discord": "discord.py", "pyrogram": "pyrogram",
                            "tgcrypto": "tgcrypto", "aiohttp": "aiohttp", "pymongo": "pymongo"
                        }
                        with open(os.path.join(extract_dir, main_file), "r", encoding="utf-8", errors="ignore") as f:
                            lines = f.readlines()
                        
                        modules_to_install = set()
                        for line in lines:
                            line = line.strip()
                            if line.startswith("import ") or line.startswith("from "):
                                parts = line.split()
                                if len(parts) > 1:
                                    mod = parts[1].split('.')[0].strip() if parts[0] == "from" else parts[1].split(',')[0].split('.')[0].strip()
                                    if mod not in ["os", "sys", "time", "json", "random", "math", "re", "requests", "subprocess", "io", "shutil", "asyncio", "hashlib", "urllib"]:
                                        modules_to_install.add(mod)

                        for mod in modules_to_install:
                            install_name = package_mapping.get(mod, mod)
                            log_file.write(f"[SYSTEM] Auto-detect: Found '{mod}'. Installing via pip as '{install_name}'...\n")
                            log_file.flush()
                            subprocess.run([sys.executable, "-m", "pip", "install", install_name], stdout=log_file, stderr=log_file)
                    except Exception as ex:
                        log_file.write(f"[SYSTEM] Auto-import-installer exception: {ex}\n")
                        log_file.flush()
                cmd = [sys.executable, main_file]
            else:
                pkg_path = os.path.join(extract_dir, "package.json")
                if os.path.exists(pkg_path):
                    log_file.write("\n[SYSTEM] Installing npm packages...\n")
                    log_file.flush()
                    subprocess.run(["npm", "install"], cwd=extract_dir, stdout=log_file, stderr=log_file)
                cmd = ["node", main_file]

        # Popen output must stream to a permanent file description handle safely
        out_handle = open(log_path, "a", encoding="utf-8")
        processes[(user_name, name)] = subprocess.Popen(cmd, cwd=extract_dir, stdout=out_handle, stderr=out_handle, text=True)
        
        db_data = load_db()
        if "start_times" not in db_data: db_data["start_times"] = {}
        db_data["start_times"][f"{user_name}_{name}"] = int(time.time() * 1000)
        save_db(db_data)
            
    return redirect(url_for("index"))

@app.route("/get_log/<name>")
def get_log(name):
    user_name = session.get('username')
    if not user_name: return jsonify({"status": "OFFLINE", "log": ""})
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    log_path = os.path.join(app_dir, "logs.txt")
    log_content = ""
    
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f: 
            log_content = f.read()[-3000:]
            
    p = processes.get((user_name, name))
    db_data = load_db()
    
    # If standard memory dict lost reference but db says it should be running, track via state fallbacks safely
    is_running = (p and p.poll() is None) or f"{user_name}_{name}" in db_data.get("start_times", {})
    
    # Safety Check: If process has terminated physically, fix DB synchronization state
    if p and p.poll() is not None and f"{user_name}_{name}" in db_data.get("start_times", {}):
        is_running = False
        del db_data["start_times"][f"{user_name}_{name}"]
        save_db(db_data)

    return jsonify({
        "log": log_content if log_content else "> System ready. Press START to activate server context.", 
        "status": "RUNNING" if is_running else "OFFLINE", 
        "start_time": db_data.get("start_times", {}).get(f"{user_name}_{name}", 0)
    })

@app.route("/stop/<name>")
def stop(name):
    user_name = session.get('username')
    p = processes.get((user_name, name))
    if p: 
        try: p.terminate()
        except: pass
        if (user_name, name) in processes:
            del processes[(user_name, name)]
            
    db_data = load_db()
    if "start_times" in db_data and f"{user_name}_{name}" in db_data["start_times"]:
        del db_data["start_times"][f"{user_name}_{name}"]
        save_db(db_data)
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    file = request.files.get("file")
    if file and file.filename.endswith(".zip"):
        app_name = secure_filename(file.filename.rsplit('.', 1)[0])
        user_dir = os.path.join(UPLOAD_FOLDER, user_name, app_name)
        
        # Clean clean slate extraction mechanism to prevent overlapping file corruption
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
            
        os.makedirs(user_dir, exist_ok=True)
        zip_path = os.path.join(user_dir, secure_filename(file.filename))
        file.save(zip_path)
        extract_dir = os.path.join(user_dir, "extracted")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        os.remove(zip_path)
    return redirect(url_for("index"))

@app.route("/download/<name>")
def download(name):
    user_name = session.get('username')
    app_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, name, "extracted"))
    
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
    app_dir = os.path.abspath(os.path.join(UPLOAD_FOLDER, user_name, name))
    if os.path.exists(app_dir): 
        shutil.rmtree(app_dir)
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): 
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    # Dynamic port extraction specifically built for Render Environment Engine
    port = int(os.environ.get("PORT", 3522))
    app.run(host="0.0.0.0", port=port)
