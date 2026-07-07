from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io

app = Flask(__name__)
app.secret_key = "YUVI-HOSTING-PRO"

# CRITICAL FIX: Render पर परमिशन एरर और क्रैश रोकने के लिए /tmp पाथ का उपयोग
UPLOAD_FOLDER = "/tmp/uploads"
DB_FILE = "/tmp/database.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}

def load_db():
    if not os.path.exists(DB_FILE):
        default = {"user_pw": "yuvi123", "users": {}, "start_times": {}}
        try:
            with open(DB_FILE, "w") as f: json.dump(default, f)
        except Exception as e:
            print(f"Error creating DB: {e}")
        return default
    with open(DB_FILE, "r") as f:
        try:
            data = json.load(f)
            if "users" not in data: data["users"] = {}
            if "user_pw" not in data: data["user_pw"] = "codex123"
            if "start_times" not in data: data["start_times"] = {}
            return data
        except:
            return {"user_pw": "yuvi123", "users": {}, "start_times": {}}

def save_db(data):
    try:
        temp_db = DB_FILE + ".tmp"
        with open(temp_db, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_db, DB_FILE)
    except Exception as e:
        print(f"Error saving DB: {e}")

ADMIN_PASS = "098765"

# --- LOGIN PAGE HTML ---
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | YUVI CODEX</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script language="javascript">
document.write(unescape('%3Cscript%20src%3D%22https%3A%2F%2Fpl28664877.effectivegatecpm.com%2F9b%2F09%2F14%2F9b0914dde54e0f75462c782bc760cb71.js%22%3E%3C%2Fscript%3E'));
</script>
    <style>
        :root { --bg: #030508; --primary: #00ffff; --sec: #7000ff; --glass: rgba(255, 255, 255, 0.03); }
        body { background: var(--bg); color: white; font-family: 'Orbitron', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; }
        #particles-js { position: fixed; width: 100%; height: 100%; z-index: 1; }
        .login-card { position: relative; z-index: 10; background: var(--glass); padding: 40px 30px; border-radius: 25px; width: 340px; text-align: center; border: 1px solid rgba(0, 255, 255, 0.15); backdrop-filter: blur(20px); box-shadow: 0 25px 45px rgba(0,0,0,0.5), inset 0 0 15px rgba(0, 255, 255, 0.05); transition: 0.4s; }
        .login-card:hover { border-color: var(--primary); box-shadow: 0 0 30px rgba(0, 255, 255, 0.15); }
        .lock-container { width: 80px; height: 80px; background: rgba(0, 255, 255, 0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 py auto 20px; border: 2px solid var(--primary); box-shadow: 0 0 20px var(--primary); animation: pulse 2s infinite; }
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
        <div class="get-pw"><a href="https://t.me/mr_ghost34" target="_blank"><i class="fa-brands fa-telegram"></i> FORGOT PASSWORD?</a></div>
    </div>
    <script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
    <script>
        particlesJS('particles-js', { "particles": { "number": { "value": 100, "density": { "enable": true, "value_area": 800 } }, "color": { "value": "#00ffff" }, "shape": { "type": "circle" }, "opacity": { "value": 0.5, "random": true }, "size": { "value": 3, "random": true }, "line_linked": { "enable": true, "distance": 150, "color": "#00ffff", "opacity": 0.2, "width": 1 }, "move": { "enable": true, "speed": 2, "direction": "none", "random": false, "straight": false, "out_mode": "out", "bounce": false } } });
    </script>
</body>
</html>
'''

# --- INDEX/MAIN PAGE HTML (COMBINED TO PREVENT ERRORS) ---
INDEX_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard | YUVI CODEX</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #030508; --card: rgba(22, 27, 34, 0.8); --accent: #00ffff; --text: #e6edf3; --glass: rgba(255, 255, 255, 0.05); }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: var(--glass); border-radius: 15px; border: 1px solid rgba(0, 255, 255, 0.2); margin-bottom: 20px; }
        .header h2 { color: var(--accent); margin: 0; }
        .card { background: var(--card); padding: 20px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; }
        .btn { padding: 10px 20px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; }
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .btn-danger { background: #ff4757; color: #fff; }
        .btn-success { background: #2ed573; color: #fff; }
        .app-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: rgba(255,255,255,0.03); margin-bottom: 10px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }
        .status-badge { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }
        .status-running { background: rgba(46, 213, 115, 0.2); color: #2ed573; }
        .status-offline { background: rgba(255, 71, 87, 0.2); color: #ff4757; }
        input[type="file"] { background: var(--glass); padding: 10px; border-radius: 10px; border: 1px dashed var(--accent); color: white; }
    </style>
</head>
<body>
    <div class="header">
        <h2><i class="fa-solid fa-cube"></i> Welcome, {{ username }}</h2>
        <a href="/logout" class="btn btn-danger"><i class="fa-solid fa-power-off"></i> Logout</a>
    </div>

    <div class="card">
        <h3><i class="fa-solid fa-cloud-arrow-up"></i> Deploy New Project (.zip)</h3>
        <form action="/upload" method="post" enctype="multipart/form-data" style="display: flex; gap: 15px; align-items: center;">
            <input type="file" name="file" accept=".zip" required>
            <button type="submit" class="btn btn-primary"><i class="fa-solid fa-rocket"></i> Upload & Deploy</button>
        </form>
    </div>

    <div class="card">
        <h3><i class="fa-solid fa-server"></i> Active Applications</h3>
        {% if not apps %}
            <p style="opacity: 0.6;">No projects deployed yet. Upload a zip file above!</p>
        {% endif %}
        {% for app in apps %}
        <div class="app-item">
            <div>
                <strong style="font-size: 16px; color: var(--accent);">{{ app.name }}</strong>
                <span class="status-badge {% if app.running %}status-running{% else %}status-offline{% endif %}">
                    {% if app.running %}RUNNING{% else %}OFFLINE{% endif %}
                </span>
            </div>
            <div style="display: flex; gap: 10px;">
                {% if not app.running %}
                    <a href="/run/{{ app.name }}" class="btn btn-success"><i class="fa-solid fa-play"></i> Run</a>
                {% else %}
                    <a href="/stop/{{ app.name }}" class="btn btn-danger"><i class="fa-solid fa-stop"></i> Stop</a>
                {% endif %}
                <a href="/delete/{{ app.name }}" class="btn btn-danger" style="background: transparent; border: 1px solid #ff4757; color: #ff4757;"><i class="fa-solid fa-trash"></i> Delete</a>
            </div>
        </div>
        {% endfor %}
    </div>
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
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: var(--glass); border-radius: 15px; border: 1px solid rgba(0, 255, 255, 0.2); margin-bottom: 20px; }
        .header h2 { color: var(--accent); margin: 0; }
        .card { background: var(--card); padding: 20px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px; }
        .btn { padding: 10px 20px; border-radius: 10px; border: none; font-weight: bold; cursor: pointer; text-decoration: none; }
        .btn-primary { background: linear-gradient(45deg, #00ffff, #7000ff); color: #000; }
        .btn-logout { background: #ff4757; color: white; }
        input { padding: 10px; border-radius: 8px; border: 1px solid #333; background: #000; color: white; }
    </style>
</head>
<body>
    <div class="header"><h2><i class="fa-solid fa-shield-halved"></i> ADMIN ROOT</h2><a href="/logout" class="btn btn-logout">Logout</a></div>
    <div class="card"><h3>Update Password</h3><form action="/admin/global_pw" method="post"><input type="text" name="global_pw" value="{{ global_pw }}"><button type="submit" class="btn btn-primary">Update</button></form></div>
</body>
</html>
'''

# --- API & ROUTES ---

@app.route("/list_files/<name>")
def list_files(name):
    if 'username' not in session: return jsonify({"files": []})
    extract_dir = os.path.join(UPLOAD_FOLDER, session['username'], name, "extracted")
    files = []
    if os.path.exists(extract_dir):
        for root, _, filenames in os.walk(extract_dir):
            for f in filenames:
                files.append(os.path.relpath(os.path.join(root, f), extract_dir))
    return jsonify({"files": files})

@app.route("/read_file", methods=["POST"])
def read_content():
    if 'username' not in session: return jsonify({"content": ""})
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    if 'username' not in session: return jsonify({"status": "unauthorized"})
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, session['username'], data['project'], "extracted", data['filename'])
    with open(path, "w", encoding="utf-8") as f:
        f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    if 'username' not in session: return jsonify({"status": "unauthorized"})
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
        db = load_db()
        if l_type == "admin":
            if username == "admin" and pw == ADMIN_PASS:
                session['is_admin'], session['username'] = True, "admin"
                return redirect(url_for("admin_panel"))
        else:
            if username and username not in db["users"]:
                db["users"][username] = db["user_pw"]
                save_db(db)
            if username and pw == db["users"].get(username):
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
    # FIXED: Template render string का उपयोग ताकि बाहरी HTML फाइल की निर्भरता ही खत्म हो जाए
    return render_template_string(INDEX_HTML, apps=apps_list, username=user_name)

@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    return render_template_string(ADMIN_HTML, users=db["users"], start_times=db["start_times"], global_pw=db["user_pw"])

@app.route("/admin/global_pw", methods=["POST"])
def global_pw():
    db = load_db()
    db["user_pw"] = request.form.get("global_pw")
    save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/change_pw", methods=["POST"])
def change_pw():
    u_name, new_pw = request.form.get("username"), request.form.get("new_pw")
    db = load_db()
    if u_name in db["users"]:
        db["users"][u_name] = new_pw
        save_db(db)
    return redirect(url_for("admin_panel"))

@app.route("/admin/login_as/<username>")
def login_as(username):
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
            primary_files = ["main.py", "bot.py", "app.py", "index.js", "server.js"]
            for pf in primary_files:
                if pf in all_files:
                    main_file = pf
                    break
            if not main_file:
                for f in all_files:
                    if f.endswith('.py') or f.endswith('.js'):
                        main_file = f
                        break

        if main_file:
            log_path = os.path.join(app_dir, "logs.txt")
            log_file = open(log_path, "w", encoding="utf-8")
            cmd = ["python", main_file] if main_file.endswith('.py') else ["node", main_file]
            processes[(user_name, name)] = subprocess.Popen(cmd, cwd=extract_dir, stdout=log_file, stderr=log_file, text=True)
            db = load_db()
            db["start_times"][f"{user_name}_{name}"] = int(time.time() * 1000)
            save_db(db)
            
    return redirect(url_for("index"))

@app.route("/get_log/<name>")
def get_log(name):
    if 'username' not in session: return jsonify({"status": "offline", "log": ""})
    user_name = session.get('username')
    app_dir = os.path.join(UPLOAD_FOLDER, user_name, name)
    log_path = os.path.join(app_dir, "logs.txt")
    log_content = ""
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f: 
                log_content = f.read()[-3000:]
        except:
            log_content = "Reading logs..."
            
    p = processes.get((user_name, name))
    db = load_db()
    is_running = (p and p.poll() is None)
    return jsonify({
        "log": log_content, 
        "status": "RUNNING" if is_running else "OFFLINE", 
        "start_time": db["start_times"].get(f"{user_name}_{name}", 0)
    })

@app.route("/stop/<name>")
def stop(name):
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session.get('username')
    p = processes.get((user_name, name))
    if p:
        try:
            p.terminate()
            p.wait(timeout=2)
        except:
            try: p.kill()
            except: pass
        if (user_name, name) in processes: del processes[(user_name, name)]
    db = load_db()
    if f"{user_name}_{name}" in db["start_times"]:
        del db["start_times"][f"{user_name}_{name}"]
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
        extract_dir = os.path.join(user_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
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
    if os.path.exists(app_dir): shutil.rmtree(app_dir)
    return redirect(url_for("index"))

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3522, debug=True)
