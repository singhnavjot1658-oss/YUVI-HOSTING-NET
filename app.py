from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, zipfile, subprocess, shutil, json, time, io, threading, signal, secrets, string
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, storage

app = Flask(__name__, template_folder=".")
app.secret_key = "YUVI-HOSTING-PRO-ULTRA"

UPLOAD_FOLDER = "uploads"
DB_FILE = "database.json"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

processes = {}
db_lock = threading.Lock()

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

def generate_random_api_key(length=32):
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

# --- HELPER: Parse expiry to UTC timestamp (backward compatible) ---
def parse_expiry_to_ts(expiry_val):
    """Convert stored expiry (string or number) to Unix UTC timestamp.
    Returns None if unparseable."""
    if expiry_val is None:
        return None
    # If it's already a number (timestamp format)
    if isinstance(expiry_val, (int, float)):
        return float(expiry_val)
    # String format: try parsing
    try:
        s = str(expiry_val)
        if len(s) > 16:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M")
        # Convert naive datetime to UTC timestamp
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None

def is_user_expired(user_info):
    """Check if a user is expired based on current UTC time."""
    if user_info.get("plan_type") == "permanent":
        return False
    if user_info.get("status") == "expired":
        return True
    expiry_ts = parse_expiry_to_ts(user_info.get("expiry"))
    if expiry_ts is None:
        return False
    return time.time() > expiry_ts

# --- DB STRUCTURE WITH API KEY & DYNAMIC ADMIN CREDS ---
def load_db():
    with db_lock:
        default_admin_settings = {
            "api_key": generate_random_api_key(),
            "admin_user": "JUBARAJ",
            "admin_pass": "098765"
        }
        if not os.path.exists(DB_FILE):
            default = {
                "users": {}, 
                "start_times": {}, 
                "themes": {}, 
                "admin_settings": default_admin_settings
            }
            with open(DB_FILE, "w") as f: 
                json.dump(default, f, indent=4)
            return default
        with open(DB_FILE, "r") as f:
            try:
                data = json.load(f)
                if "users" not in data: data["users"] = {}
                if "start_times" not in data: data["start_times"] = {}
                if "themes" not in data: data["themes"] = {}
                if "admin_settings" not in data: 
                    data["admin_settings"] = default_admin_settings
                else:
                    if "admin_user" not in data["admin_settings"]:
                        data["admin_settings"]["admin_user"] = "JUBARAJ"
                    if "admin_pass" not in data["admin_settings"]:
                        data["admin_settings"]["admin_pass"] = "098765"
                return data
            except:
                return {
                    "users": {}, 
                    "start_times": {}, 
                    "themes": {}, 
                    "admin_settings": default_admin_settings
                }

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

# --- KILL ALL PROCESSES FOR A USER (ROBUST) ---
def kill_user_processes(user_name):
    """Kill all processes belonging to user_name. Logs errors, always removes from dict."""
    killed_any = False
    for key, p in list(processes.items()):
        if key[0] == user_name:
            try:
                # Try process group kill first (most thorough)
                if hasattr(os, 'killpg'):
                    try:
                        pgid = os.getpgid(p.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError) as e:
                        print(f"killpg failed for {key}: {e}")
                        # Fallback: kill individual process
                        p.kill()
                else:
                    p.kill()
                
                # Wait briefly for termination
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force terminate if still alive
                    p.terminate()
                    try:
                        p.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                
                killed_any = True
            except Exception as e:
                print(f"Error killing process {key}: {e}")
                # Last resort on Windows
                if os.name == 'nt':
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5
                        )
                    except Exception as e2:
                        print(f"taskkill also failed: {e2}")
            
            # ALWAYS remove from dict regardless of kill success
            del processes[key]
    
    return killed_any

# --- STOP & CLEAN USER (only called from middleware, idempotent) ---
def stop_and_clean_user(user_name, db_data=None):
    """
    Stop user processes, clean files, remove from themes/start_times.
    If db_data is provided, modifies it in-place. Otherwise loads fresh.
    Returns True if any cleanup was done.
    """
    if db_data is None:
        db = load_db()
        owns_db = True
    else:
        db = db_data
        owns_db = False
    
    # 1. Kill processes
    killed = kill_user_processes(user_name)
    
    # 2. Remove from start_times
    st_keys_to_del = [k for k in db["start_times"] if k.startswith(user_name + "_")]
    for k in st_keys_to_del:
        del db["start_times"][k]
    
    # 3. Clean user directory
    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir)
        except Exception as e:
            print(f"Error deleting user directory {user_dir}: {e}")
    
    # 4. Clean Firebase backup
    if firebase_admin._apps:
        try:
            bucket = storage.bucket()
            blobs = bucket.list_blobs(prefix=f"backups/{user_name}/")
            for blob in blobs:
                blob.delete()
        except Exception as e:
            print(f"Firebase data clean error: {e}")
    
    # 5. Remove from themes
    if user_name in db.get("themes", {}):
        del db["themes"][user_name]
    
    # 6. Set status to expired
    if user_name in db["users"]:
        db["users"][user_name]["status"] = "expired"
    
    # 7. Save if we own the db
    if owns_db:
        save_db(db)
    
    return killed or len(st_keys_to_del) > 0

# --- EXPIRY TRACKER & AUTO-STOPPER (FIXED) ---
def enforcement_loop():
    while True:
        try:
            db = load_db()
            now_utc = time.time()
            changed = False
            
            for username, info in list(db["users"].items()):
                if info.get("plan_type") == "permanent":
                    if info.get("status") != "active":
                        db["users"][username]["status"] = "active"
                        changed = True
                    continue
                
                # Check if expired using consistent UTC timestamp comparison
                if is_user_expired(info):
                    if info.get("status") != "expired":
                        db["users"][username]["status"] = "expired"
                        changed = True
                    
                    # Kill processes (inline, using same db context)
                    killed = kill_user_processes(username)
                    
                    # Clean start_times entries
                    st_keys = [k for k in db["start_times"] if k.startswith(username + "_")]
                    for k in st_keys:
                        del db["start_times"][k]
                        changed = True
                    
                    # Clean themes
                    if username in db.get("themes", {}):
                        del db["themes"][username]
                        changed = True
                    
                    if killed:
                        print(f"[Enforcer] Killed processes for expired user: {username}")
            
            if changed:
                # Save everything in ONE atomic write — no race condition
                save_db(db)
                
        except Exception as e:
            print(f"Enforcement Loop Error: {e}")
        
        time.sleep(3)

enforcement_thread = threading.Thread(target=enforcement_loop, daemon=True)
enforcement_thread.start()

# --- REAL-TIME AUTO TERMINATE MIDDLEWARE (FIXED) ---
@app.before_request
def check_user_plan_status():
    if request.endpoint in ['login', 'static']:
        return None

    if 'username' in session and not session.get('is_admin'):
        username = session['username']
        db = load_db()
        user_info = db.get("users", {}).get(username)

        if not user_info:
            session.clear()
            return redirect(url_for('login', error="User account does not exist."))
        
        # Use the same is_user_expired check as enforcement loop
        if is_user_expired(user_info):
            # Clean up AND save db (pass in our db copy)
            stop_and_clean_user(username, db_data=db)
            save_db(db)
            session.clear()
            
            if request.is_json:
                return jsonify({"expired_kick": True, "error": "Plan Expired"}), 403
            return redirect(url_for('login', error="Your Plan Expired! Access Terminated."))
    
    return None

# --- LOGIN HTML ---
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | YUVI CODEX</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; }
        :root { 
            --bg: #03070d; 
            --primary: #00f0ff; 
            --sec: #0072ff; 
            --accent-glow: rgba(0, 240, 255, 0.4);
        }
        
        body { 
            background: var(--bg); 
            color: white; 
            font-family: sans-serif; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
            height: 100vh; 
            margin: 0; 
            padding: 15px; 
            position: relative;
            overflow: hidden;
        }

        .glow-blob {
            position: absolute;
            border-radius: 50%;
            background: #00f0ff;
            box-shadow: 0 0 30px #00f0ff, 0 0 60px #0072ff;
            animation: floatAnim 6s ease-in-out infinite alternate;
            z-index: 1;
            opacity: 0.5;
        }
        .blob-1 { width: 50px; height: 50px; top: 10%; right: 15%; animation-duration: 5s; }
        .blob-2 { width: 70px; height: 70px; top: 18%; right: -25px; animation-duration: 7s; }
        .blob-3 { width: 40px; height: 40px; bottom: 35%; left: -15px; animation-duration: 6s; }
        .blob-4 { width: 60px; height: 60px; bottom: 5%; right: 25%; animation-duration: 8s; }
        .blob-5 { width: 35px; height: 35px; bottom: 15%; left: 10%; animation-duration: 4.5s; }

        @keyframes floatAnim {
            0% { transform: translateY(0px) scale(1); }
            100% { transform: translateY(-20px) scale(1.15); }
        }

        .card-wrapper {
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 380px;
            border-radius: 20px;
            padding: 2px;
            overflow: hidden;
            background: rgba(0, 0, 0, 0.6);
        }

        .card-wrapper::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(
                transparent, 
                #00f0ff, 
                transparent 40%,
                #0072ff 50%,
                transparent 90%
            );
            animation: rotateBorder 3.5s linear infinite;
        }

        @keyframes rotateBorder {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .login-card { 
            position: relative;
            z-index: 3;
            background: #080e18; 
            padding: 30px; 
            border-radius: 18px; 
            width: 100%; 
            text-align: center; 
            box-shadow: 0 0 25px rgba(0, 240, 255, 0.25); 
        }

        .lock-container { 
            width: 65px; 
            height: 65px; 
            background: rgba(0, 240, 255, 0.1); 
            border-radius: 50%; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            margin: 0 auto 15px; 
            border: 1px solid var(--primary); 
            box-shadow: 0 0 15px var(--accent-glow);
        }
        .lock-icon { font-size: 28px; color: var(--primary); }
        h2 { font-size: 18px; margin-bottom: 20px; letter-spacing: 2px; text-transform: uppercase; color: var(--primary); }
        input, select { width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: 1px solid rgba(0,240,255,0.2); background: rgba(255,255,255,0.05); color: #fff; font-size: 13px; outline: none; }
        button { width: 100%; padding: 11px; border-radius: 8px; border: none; background: linear-gradient(45deg, var(--sec), var(--primary)); color: #000; font-weight: bold; cursor: pointer; margin-top: 15px; text-transform: uppercase; font-size: 13px; box-shadow: 0 0 15px var(--accent-glow); }
        .error-msg { color: #ff4757; font-size: 12px; margin-top: 10px; display: block; font-weight: bold; }
    </style>
</head>
<body>
    <div class="glow-blob blob-1"></div>
    <div class="glow-blob blob-2"></div>
    <div class="glow-blob blob-3"></div>
    <div class="glow-blob blob-4"></div>
    <div class="glow-blob blob-5"></div>

    <div class="card-wrapper">
        <div class="login-card">
            <div class="lock-container"><i class="fa-solid fa-user-shield lock-icon"></i></div>
            <h2>System Login</h2>
            {% if error %}<span class="error-msg"><i class="fa-solid fa-triangle-exclamation"></i> {{ error }}</span>{% endif %}
            <form method="post" action="/login">
                <select name="login_type">
                    <option value="user">USER ACCESS</option>
                    <option value="admin">ADMIN ROOT</option>
                </select>
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Access System</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

# --- ADMIN HTML ---
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JUBARAJ Panel | Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        :root { --bg: #03070d; --card: #080e18; --accent: #00f0ff; --sec: #0072ff; --text: #c9d1d9; --border: rgba(0, 240, 255, 0.2); }
        body { background: var(--bg); color: var(--text); padding-bottom: 75px; }
        
        .header { display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; background: #080e18; border-bottom: 1px solid var(--border); position: sticky; top:0; z-index: 100;}
        .header h2 { font-size: 15px; color: var(--accent); letter-spacing: 1px; }
        
        .container { padding: 12px; max-width: 800px; margin: 0 auto; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .card { background: var(--card); padding: 14px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 12px; }
        h3 { font-size: 13px; color: var(--accent); margin-bottom: 10px; display: flex; align-items: center; gap: 6px; text-transform: uppercase;}
        
        .input-group { display: flex; flex-direction: column; gap: 8px; }
        input, select, textarea { width: 100%; padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(0, 240, 255, 0.2); background: #010409; color: white; font-size: 12px; outline: none; }
        
        .btn-sm { padding: 6px 12px; border-radius: 6px; border: none; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 5px; text-decoration: none; font-size: 11px; }
        .btn-primary { background: linear-gradient(45deg, var(--sec), var(--accent)); color: #000; font-weight: bold; box-shadow: 0 0 10px rgba(0,240,255,0.3); }
        .btn-danger { background: #da3633; color: white; }
        .btn-outline { background: transparent; border: 1px solid var(--accent); color: var(--accent); }
        
        .user-item { background: #010409; border-radius: 8px; padding: 10px; margin-bottom: 8px; border: 1px solid var(--border); }
        .user-info { display: flex; justify-content: space-between; align-items: center; }
        .username { font-weight: bold; color: #fff; font-size: 12px; }
        .status-badge { padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: bold; }
        .status-active { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
        .status-expired { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
        
        .navbar { position: fixed; bottom: 0; left: 0; right: 0; background: #080e18; display: flex; justify-content: space-around; padding: 8px 0; border-top: 1px solid var(--border); z-index: 1000; }
        .nav-item { color: #8b949e; text-decoration: none; font-size: 10px; display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; flex: 1; text-align: center;}
        .nav-item i { font-size: 16px; }
        .nav-item.active { color: var(--accent); }

        .api-box { background: #000; padding: 10px; border-radius: 6px; border: 1px dashed var(--accent); font-family: monospace; font-size: 11px; word-break: break-all; margin: 8px 0; color: #39d353; display: flex; justify-content: space-between; align-items: center;}
        
        .stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 10px; }
        .stat-card { background: #010409; border: 1px solid var(--border); padding: 10px; border-radius: 8px; text-align: center; }
        .stat-num { font-size: 18px; font-weight: bold; color: var(--accent); }
        .stat-label { font-size: 10px; color: #8b949e; }
    </style>
</head>
<body>
    <div class="header">
        <h2><i class="fa-solid fa-shield-halved"></i> ADMIN CONTROL</h2>
        <a href="/logout" class="btn-sm btn-danger"><i class="fa-solid fa-power-off"></i></a>
    </div>

    <div class="container">
        <div id="tab-users" class="tab-content active">
            <div class="card">
                <h3><i class="fa-solid fa-user-plus"></i> Add New User</h3>
                <form action="/admin/create_user" method="post" class="input-group" onsubmit="appendTabHash(this); setTimezoneOffset();">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <select name="plan_type" onchange="toggleExpiryInput(this.value)">
                        <option value="time_bound">Time Bound Plan</option>
                        <option value="permanent">Lifetime Permanent</option>
                    </select>
                    <div id="exp_input_wrapper">
                        <input type="datetime-local" id="expiry_date_input" name="expiry">
                    </div>
                        <input type="hidden" name="tz_offset" id="tz_offset" value="0">
                    <button type="submit" class="btn-sm btn-primary"><i class="fa-solid fa-plus"></i> Create Account</button>
                </form>
            </div>

            <div class="card">
                <h3><i class="fa-solid fa-users"></i> Subscriptions ({{ users.keys()|length }})</h3>
                {% for u_name, u_info in users.items() %}
                <div class="user-item">
                    <div class="user-info">
                        <span class="username"><i class="fa-solid fa-user"></i> {{ u_name }}</span>
                        <span class="status-badge {% if u_info.status == 'active' %}status-active{% else %}status-expired{% endif %}">
                            {{ u_info.status|upper }}
                        </span>
                    </div>
                    <div style="font-size:10px; opacity:0.7; margin:4px 0;">
                        Pass: {{ u_info.password }} | {{ u_info.get('plan_type','time_bound')|upper }}
                        {% if u_info.get('plan_type') != 'permanent' %}
                        | Exp: {{ u_info.expiry.replace('T', ' ') if u_info.expiry else 'N/A' }}
                        {% endif %}
                    </div>
                    <div style="display:flex; gap:6px; margin-top:6px;">
                        <a href="/admin/login_as/{{ u_name }}" class="btn-sm btn-outline" style="padding: 3px 8px;">Login As</a>
                        <a href="/admin/delete_user/{{ u_name }}#tab-users" class="btn-sm btn-danger" style="padding: 3px 8px;" onclick="return confirm('Delete user data?')">Delete</a>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div id="tab-broadcast" class="tab-content">
            <div class="card">
                <h3><i class="fa-solid fa-bullhorn"></i> Push Alert System</h3>
                <form action="/admin/broadcast" method="post" class="input-group" onsubmit="appendTabHash(this)">
                    <select name="target_user">
                        <option value="ALL_USERS">--- ALL USERS ---</option>
                        {% for u_name in users.keys() %}
                        <option value="{{ u_name }}">Target: {{ u_name }}</option>
                        {% endfor %}
                    </select>
                    <textarea name="message" rows="4" placeholder="Write announcement message..." required></textarea>
                    <button type="submit" class="btn-sm btn-primary"><i class="fa-solid fa-paper-plane"></i> Push Broadcast</button>
                </form>
            </div>
        </div>

        <div id="tab-api" class="tab-content">
            <div class="card">
                <h3><i class="fa-solid fa-key"></i> Telegram Bot API Settings</h3>
                <p style="font-size: 11px; opacity: 0.8; margin-bottom: 6px;">Use this API Key to manage panel directly from Telegram Bot:</p>

                <div class="api-box">
                    <span id="apiKeyText">{{ api_key }}</span>
                    <button type="button" onclick="copyApiKey()" class="btn-sm btn-primary" style="padding: 3px 8px;">
                        <i class="fa-solid fa-copy"></i> Copy
                    </button>
                </div>
                
                <form action="/admin/regen_key" method="post" style="margin-top: 8px;" onsubmit="appendTabHash(this)">
                    <button type="submit" class="btn-sm btn-outline"><i class="fa-solid fa-arrows-rotate"></i> Reset API Key</button>
                </form>

                <h3 style="margin-top: 15px;"><i class="fa-solid fa-code"></i> API Endpoint Details</h3>
                <div style="font-size:10px; font-family: monospace; line-height: 1.6; opacity: 0.8;">
                    <b>Get Users:</b> <code>GET /api/admin/users?api_key={{ api_key }}</code><br>
                    <b>Create User:</b> <code>POST /api/admin/create_user</code><br>
                    <b>Delete User:</b> <code>POST /api/admin/delete_user</code><br>
                    <b>Broadcast:</b> <code>POST /api/admin/broadcast</code>
                </div>
            </div>
        </div>

        <div id="tab-settings" class="tab-content">
            <div class="card">
                <h3><i class="fa-solid fa-gears"></i> Change Admin Credentials</h3>
                <form action="/admin/update_credentials" method="post" class="input-group" onsubmit="appendTabHash(this)">
                    <label style="font-size: 11px; color: #8b949e;">New Admin Username:</label>
                    <input type="text" name="admin_username" value="{{ admin_user }}" required>
                    
                    <label style="font-size: 11px; color: #8b949e;">New Admin Password:</label>
                    <input type="password" name="admin_password" value="{{ admin_pass }}" required>
                    
                    <button type="submit" class="btn-sm btn-primary"><i class="fa-solid fa-floppy-disk"></i> Save Admin Credentials</button>
                </form>
            </div>
        </div>

        <div id="tab-stats" class="tab-content">
            <div class="card">
                <h3><i class="fa-solid fa-chart-line"></i> Server Overview</h3>
                <div class="stat-grid">
                    <div class="stat-card">
                        <div class="stat-num">{{ users.keys()|length }}</div>
                        <div class="stat-label">Total Users</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-num">{{ active_proc_count }}</div>
                        <div class="stat-label">Active Processes</div>
                    </div>
                </div>
                <p style="font-size: 11px; color: #8b949e; text-align: center; margin-top: 5px;">System status is operational.</p>
            </div>
        </div>
    </div>

    <div class="navbar">
        <div class="nav-item active" data-tab="tab-users" onclick="switchTab('tab-users', this)">
            <i class="fa-solid fa-users-gear"></i>
            <span>Users</span>
        </div>
        <div class="nav-item" data-tab="tab-broadcast" onclick="switchTab('tab-broadcast', this)">
            <i class="fa-solid fa-paper-plane"></i>
            <span>Broadcast</span>
        </div>
        <div class="nav-item" data-tab="tab-api" onclick="switchTab('tab-api', this)">
            <i class="fa-solid fa-robot"></i>
            <span>Bot API</span>
        </div>
        <div class="nav-item" data-tab="tab-settings" onclick="switchTab('tab-settings', this)">
            <i class="fa-solid fa-sliders"></i>
            <span>Settings</span>
        </div>
        <div class="nav-item" data-tab="tab-stats" onclick="switchTab('tab-stats', this)">
            <i class="fa-solid fa-chart-pie"></i>
            <span>Stats</span>
        </div>
    </div>

    <script>
        function switchTab(tabId, el) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            
            const target = document.getElementById(tabId);
            if(target) target.classList.add('active');
            if(el) el.classList.add('active');
            
            window.location.hash = tabId;
        }

        function appendTabHash(form) {
            const activeTab = document.querySelector('.tab-content.active');
            if (activeTab) {
                form.action = form.action.split('#')[0] + '#' + activeTab.id;
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            const hash = window.location.hash.replace('#', '');
            if (hash && document.getElementById(hash)) {
                const navBtn = document.querySelector(`.nav-item[data-tab="${hash}"]`);
                switchTab(hash, navBtn);
            }
        });

        function toggleExpiryInput(value) {
            var expBox = document.getElementById('exp_input_wrapper');
            if(value === 'permanent') {
                expBox.style.display = 'none';
            } else {
                expBox.style.display = 'block';
            }
        }

        function setTimezoneOffset() {
            document.getElementById('tz_offset').value = new Date().getTimezoneOffset();
        }

        function copyApiKey() {
            var keyText = document.getElementById('apiKeyText').innerText;
            navigator.clipboard.writeText(keyText).then(function() {
                alert("API Key copied to clipboard!");
            }).catch(function() {
                alert("Failed to copy API key.");
            });
        }
    </script>
</body>
</html>
'''

# --- API ENDPOINTS FOR TELEGRAM BOT ---
@app.route("/api/admin/users", methods=["GET"])
def api_get_users():
    key = request.args.get("api_key")
    db = load_db()
    if key != db.get("admin_settings", {}).get("api_key"):
        return jsonify({"status": "error", "message": "Invalid API Key"}), 403
    return jsonify({"status": "success", "users": db.get("users", {})})

@app.route("/api/admin/create_user", methods=["POST"])
def api_create_user():
    data = request.json or request.form
    key = data.get("api_key")
    db = load_db()
    if key != db.get("admin_settings", {}).get("api_key"):
        return jsonify({"status": "error", "message": "Invalid API Key"}), 403
        
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    plan_type = data.get("plan_type", "time_bound")
    expiry = data.get("expiry", "2099-12-31T23:59") if plan_type != "permanent" else "2099-12-31T23:59"
    
    # Convert local time to UTC for API calls too
    if plan_type != "permanent" and expiry:
        tz_offset_str = str(data.get("tz_offset", "0"))
        try:
            tz_offset = int(tz_offset_str)
            s = str(expiry)
            if len(s) > 16:
                dt_local = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            else:
                dt_local = datetime.strptime(s, "%Y-%m-%dT%H:%M")
            dt_utc = dt_local + timedelta(minutes=tz_offset)
            expiry = dt_utc.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            print(f"API Timezone conversion error: {e}")
    
    if username and password:
        db["users"][username] = {
            "password": password,
            "expiry": expiry,
            "plan_type": plan_type,
            "status": "active",
            "broadcast": {"message": "", "id": ""}
        }
        save_db(db)
        return jsonify({"status": "success", "message": f"User {username} created successfully."})
    return jsonify({"status": "error", "message": "Missing parameters"}), 400

@app.route("/api/admin/delete_user", methods=["POST"])
def api_delete_user():
    data = request.json or request.form
    key = data.get("api_key")
    username = data.get("username", "").strip()
    db = load_db()
    if key != db.get("admin_settings", {}).get("api_key"):
        return jsonify({"status": "error", "message": "Invalid API Key"}), 403
        
    if username in db["users"]:
        # Pass db context to avoid race condition
        stop_and_clean_user(username, db_data=db)
        del db["users"][username]
        save_db(db)
        return jsonify({"status": "success", "message": f"User {username} deleted."})
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route("/api/admin/broadcast", methods=["POST"])
def api_broadcast():
    data = request.json or request.form
    key = data.get("api_key")
    target = data.get("target_user", "ALL_USERS")
    msg = data.get("message", "").strip()
    db = load_db()
    if key != db.get("admin_settings", {}).get("api_key"):
        return jsonify({"status": "error", "message": "Invalid API Key"}), 403
        
    msg_id = str(int(time.time()))
    broadcast_obj = {"message": msg, "id": msg_id}
    
    if target == "ALL_USERS":
        for u in db["users"]: db["users"][u]["broadcast"] = broadcast_obj
    elif target in db["users"]:
        db["users"][target]["broadcast"] = broadcast_obj
        
    save_db(db)
    return jsonify({"status": "success", "message": "Broadcast sent."})

# --- USER NOTIFICATIONS & BACKEND ROUTES ---
@app.route("/api/get_alert")
def get_alert():
    if 'username' not in session: return jsonify({"message": "", "id": "", "expired_kick": True})
    user_name = session['username']
    db = load_db()
    
    if not session.get('is_admin') and user_name in db["users"]:
        u_info = db["users"][user_name]
        # Use consistent expiry check
        if is_user_expired(u_info):
            session.clear()
            stop_and_clean_user(user_name, db_data=db)
            save_db(db)
            return jsonify({"expired_kick": True})
            
    broadcast_data = db["users"].get(user_name, {}).get("broadcast", "")
    msg = broadcast_data.get("message", "") if isinstance(broadcast_data, dict) else broadcast_data
    msg_id = broadcast_data.get("id", "") if isinstance(broadcast_data, dict) else ""
        
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

@app.route("/login", methods=["GET", "POST"])
def login():
    error = request.args.get("error", None)
    if request.method == "POST":
        l_type = request.form.get("login_type")
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        db = load_db()
        
        admin_settings = db.get("admin_settings", {})
        current_admin_user = admin_settings.get("admin_user", "JUBARAJ")
        current_admin_pass = admin_settings.get("admin_pass", "098765")
        
        if l_type == "admin":
            if username == current_admin_user and pw == current_admin_pass:
                session['is_admin'], session['username'] = True, current_admin_user
                return redirect(url_for("admin_panel"))
            error = "Invalid Admin Credentials!"
        else:
            if username in db["users"]:
                user_data = db["users"][username]
                if user_data["password"] == pw:
                    # Use consistent expiry check
                    if is_user_expired(user_data):
                        error = "Access plan expired! Contact Admin."
                    else:
                        session['is_admin'], session['username'] = False, username
                        return redirect(url_for("index"))
                else:
                    error = "Incorrect Password!"
            else:
                error = "User not registered!"
                
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/")
def index():
    if 'username' not in session: return redirect(url_for("login"))
    user_name = session['username']
    db = load_db()
    user_info = db["users"].get(user_name, {})

    user_dir = os.path.join(UPLOAD_FOLDER, user_name)
    os.makedirs(user_dir, exist_ok=True)
    apps_list = []
    for name in os.listdir(user_dir):
        if os.path.isdir(os.path.join(user_dir, name)):
            is_any_running = any(key[0] == user_name and key[1] == name and p.poll() is None for key, p in list(processes.items()))
            apps_list.append({"name": name, "running": is_any_running})
            
    user_theme = db.get("themes", {}).get(user_name, {"color": "#00ffff", "size": 38, "speed": 4, "ui_mode": "normal"})
    expiry_display = "Lifetime Permanent" if user_info.get("plan_type") == "permanent" else (user_info.get("expiry", "N/A").replace("T", " ") if user_info.get("expiry") else "N/A")

    return render_template("index.html", 
                           apps=apps_list, 
                           username=user_name,
                           plan_expiry=expiry_display,
                           user_color=user_theme.get("color", "#00ffff"),
                           user_size=user_theme.get("size", 38),
                           user_speed=user_theme.get("speed", 4),
                           user_ui_mode=user_theme.get("ui_mode", "normal"))

@app.route("/admin")
def admin_panel():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    admin_settings = db.get("admin_settings", {})
    api_key = admin_settings.get("api_key", "")
    admin_user = admin_settings.get("admin_user", "JUBARAJ")
    admin_pass = admin_settings.get("admin_pass", "098765")
    
    active_proc_count = sum(1 for p in processes.values() if p.poll() is None)
    
    return render_template_string(ADMIN_HTML, 
                                 users=db["users"], 
                                 api_key=api_key, 
                                 admin_user=admin_user, 
                                 admin_pass=admin_pass,
                                 active_proc_count=active_proc_count)

@app.route("/admin/update_credentials", methods=["POST"])
def update_credentials():
    if not session.get('is_admin'): return redirect(url_for("login"))
    new_user = request.form.get("admin_username", "").strip()
    new_pass = request.form.get("admin_password", "").strip()
    
    if new_user and new_pass:
        db = load_db()
        db["admin_settings"]["admin_user"] = new_user
        db["admin_settings"]["admin_pass"] = new_pass
        save_db(db)
        session['username'] = new_user
    return redirect(url_for("admin_panel") + "#tab-settings")

@app.route("/admin/regen_key", methods=["POST"])
def regen_key():
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    db["admin_settings"]["api_key"] = generate_random_api_key()
    save_db(db)
    return redirect(url_for("admin_panel") + "#tab-api")

@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if not session.get('is_admin'): return redirect(url_for("login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    plan_type = request.form.get("plan_type", "time_bound")
    expiry = request.form.get("expiry", "2099-12-31T23:59") if plan_type != "permanent" else "2099-12-31T23:59"
    
    # Convert local time to UTC using browser's timezone offset
    if plan_type != "permanent" and expiry:
        tz_offset_str = request.form.get("tz_offset", "0")
        try:
            tz_offset = int(tz_offset_str)
            s = str(expiry)
            if len(s) > 16:
                dt_local = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            else:
                dt_local = datetime.strptime(s, "%Y-%m-%dT%H:%M")
            dt_utc = dt_local + timedelta(minutes=tz_offset)
            expiry = dt_utc.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            print(f"Timezone conversion error: {e}")
    
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
    return redirect(url_for("admin_panel") + "#tab-users")

@app.route("/admin/delete_user/<username>")
def delete_user(username):
    if not session.get('is_admin'): return redirect(url_for("login"))
    db = load_db()
    if username in db["users"]:
        # Pass db context to avoid race
        stop_and_clean_user(username, db_data=db)
        del db["users"][username]
        save_db(db)
    return redirect(url_for("admin_panel") + "#tab-users")

@app.route("/admin/broadcast", methods=["POST"])
def broadcast():
    if not session.get('is_admin'): return redirect(url_for("login"))
    target = request.form.get("target_user")
    msg = request.form.get("message", "").strip()
    db = load_db()
    
    msg_id = str(int(time.time()))
    broadcast_obj = {"message": msg, "id": msg_id}
    
    if target == "ALL_USERS":
        for u in db["users"]: db["users"][u]["broadcast"] = broadcast_obj
    elif target in db["users"]:
        db["users"][target]["broadcast"] = broadcast_obj
        
    save_db(db)
    return redirect(url_for("admin_panel") + "#tab-broadcast")

# --- FILE & PROCESS CONTROL ENDPOINTS ---
@app.route("/list_files/<name>")
def list_files(name):
    if 'username' not in session: return jsonify({"files": []})
    user_name = session['username']
        
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
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted", data['filename'])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f: return jsonify({"content": f.read()})
    return jsonify({"content": ""})

@app.route("/save_file", methods=["POST"])
def save_content():
    if 'username' not in session: return jsonify({"status": "error"})
    user_name = session['username']
    data = request.json
    path = os.path.join(UPLOAD_FOLDER, user_name, data['project'], "extracted", data['filename'])
    with open(path, "w", encoding="utf-8") as f: f.write(data['content'])
    return jsonify({"status": "success"})

@app.route("/delete_file", methods=["POST"])
def delete_file_api():
    if 'username' not in session: return jsonify({"status": "error"})
    user_name = session['username']
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
    
    color = data.get("color", current_theme.get("color", "#00ffff"))
    size = int(data.get("size", current_theme.get("size", 38)))
    speed = int(data.get("speed", current_theme.get("speed", 4)))
    ui_mode = data.get("ui_mode", current_theme.get("ui_mode", "normal"))
    
    db["themes"][user_name] = {
        "color": color, 
        "size": size, 
        "speed": speed,
        "ui_mode": ui_mode
    }
    save_db(db)
    return jsonify({"status": "success", "ui_mode": ui_mode})

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
                kwargs = {}
                if hasattr(os, 'setsid'): kwargs['preexec_fn'] = os.setsid
                processes[process_key] = subprocess.Popen(cmd, cwd=extract_dir, stdout=log_file_handle, stderr=log_file_handle, text=True, **kwargs)
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
            try:
                if hasattr(os, 'killpg'): 
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    except:
                        p.kill()
                else: 
                    p.kill()
                try: p.wait(timeout=2)
                except: p.terminate()
            except:
                try: p.terminate()
                except: pass
            if os.name == 'nt':
                try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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