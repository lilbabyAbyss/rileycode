# right now, it does everything but return a file specficially when preview is off, also doesn't give a confrim message

from flask import Flask, render_template, request, send_file, redirect, after_this_request, session
import os, json, tempfile, uuid
from zipfile import ZipFile
from datetime import datetime
import shutil

app = Flask(__name__)
app.secret_key = "supersecretkey"

USERS_FILE = "users.json"
LOGS_FILE = "logs.json"
SETTINGS_FILE = "settings.json"

ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png",
    ".pdf", ".docx", ".txt",
    ".py", ".html", ".css", ".js",
    ".mp3", ".mp4", ".ico", ".exe"
}

MAX_SIZE_MB = 10
TEMP_ROOT = "temp_uploads"
os.makedirs(TEMP_ROOT, exist_ok=True)


# ---------------- JSON ----------------

def load_json(file):
    if not os.path.exists(file):
        return {}

    try:
        fileObject = open(file, "r", encoding="utf-8")
        data = json.load(fileObject)
        fileObject.close()
        return data
    except:
        return {}


def save_json(file, data):
    fileObject = open(file, "w", encoding="utf-8")
    json.dump(data, fileObject, indent=4)
    fileObject.close()


# ---------------- SETTINGS ----------------

def get_settings(user_id):
    default = {
        "rules": {},
        "toggles": {
            "auto_open": False,
            "notifications": True,
            "confirm": True,
            "dark_mode": False,
            "preview": True
        }
    }

    all_settings = load_json(SETTINGS_FILE)

    if not user_id or user_id not in all_settings:
        return default

    user = all_settings[user_id]

    if "rules" not in user:
        user["rules"] = {}

    # Merge toggles safely (prevents disappearing keys)
    saved = user.get("toggles", {})
    merged = default["toggles"].copy()

    for key in merged:
        if key in saved:
            merged[key] = saved[key]

    user["toggles"] = merged

    return user


# ---------------- AUTH ----------------

def find_user_by_login(users, username_or_email, password):
    for i in range(0, len(users)):
        u = users[i]

        if (u["username"] == username_or_email or u.get("email") == username_or_email) and u["password"] == password:
            return u

    return None


def user_exists(users, username, email):
    for i in range(0, len(users)):
        u = users[i]

        if u["username"] == username or u.get("email") == email:
            return True

    return False


# ---------------- FILE RULES ----------------

def get_folder(ext, settings):
    ext = ext.lower().strip()
    rules = settings.get("rules", {})

    for folder in rules:
        exts = rules[folder]

        for i in range(0, len(exts)):
            clean = exts[i].lower().strip()

            if ext == clean:
                return folder

    if ext == ".jpg" or ext == ".jpeg" or ext == ".png":
        return "Images"
    elif ext == ".pdf" or ext == ".docx" or ext == ".txt":
        return "Documents"
    elif ext == ".py" or ext == ".html" or ext == ".css" or ext == ".js":
        return "CodeFiles"
    else:
        return "OtherFiles"


def validate_file(file):
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return False

    file.seek(0, os.SEEK_END)
    size = file.tell() / (1024 * 1024)
    file.seek(0)

    if size <= MAX_SIZE_MB:
        return True
    else:
        return False


# ---------------- AUTH ROUTE ----------------

@app.route("/auth", methods=["GET", "POST"])
def auth():
    mode = request.args.get("mode", "login")

    data = load_json(USERS_FILE)
    users = data.get("users", [])

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        email = request.form.get("email")

        if mode == "login":
            user = find_user_by_login(users, username, password)

            if user != None:
                session["user_id"] = user["id"]
                session["user"] = user["username"]
                return redirect("/")

            return redirect("/auth?mode=login")

        if mode == "signup":
            if user_exists(users, username, email):
                return redirect("/auth?mode=login")

            new_user = {
                "id": str(uuid.uuid4()),
                "username": username,
                "email": email,
                "password": password
            }

            users.append(new_user)
            data["users"] = users
            save_json(USERS_FILE, data)

            session["user_id"] = new_user["id"]
            session["user"] = new_user["username"]

            return redirect("/")

    return render_template("auth.html", mode=mode, settings=get_settings(session.get("user_id")))


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/auth?mode=login")


# ---------------- HOME ----------------

@app.route("/", methods=["GET", "POST"])
def home():
    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]

    all_settings = load_json(SETTINGS_FILE)  # ✅ ADD THIS

    settings = all_settings.get(user_id, {
        "rules": {},
        "toggles": {
            "confirm": True,
            "dark_mode": False,
            "preview": True
        }
    })

    if request.method == "GET":
        return render_template("index.html", settings=settings)

    files = request.files.getlist("files")

    files = [f for f in files if f.filename]

    if len(files) == 0:
        return "No files uploaded", 400

    if not files or files[0].filename == "":
        return "No files uploaded"

    job_id = str(uuid.uuid4())

    input_dir = os.path.join(TEMP_ROOT, job_id)
    os.makedirs(input_dir, exist_ok=True)

    filenames = []

    for file in files:
        file.save(os.path.join(input_dir, file.filename))
        filenames.append(file.filename)

    job_data = {
    "user_id": user_id,
    "path": input_dir,
    "files": filenames
}

    job_file = os.path.join(TEMP_ROOT, f"{job_id}.json")

    with open(job_file, "w") as f:
        json.dump(job_data, f)

        structure = {}

    for f in files:
        ext = os.path.splitext(f.filename)[1]
        folder = get_folder(ext, settings)
        structure.setdefault(folder, []).append(f.filename)

    # ---------------- DECISION LOGIC ----------------
    confirm_enabled = settings["toggles"].get("confirm", True)
    preview_enabled = settings["toggles"].get("preview", True)

    print("CONFIRM:", confirm_enabled, "| PREVIEW:", preview_enabled)

    # ---------------- CASE 1: Confirm ON ----------------
    if confirm_enabled:
        return render_template(
            "index.html",
            settings=settings,
            preview_mode=preview_enabled,   # 👈 FIX: respect preview toggle
            preview_structure=structure,
            job_id=job_id
        )

    # ---------------- CASE 2: Confirm OFF ----------------
    if preview_enabled:
        return render_template(
        "index.html",
        settings=settings,
        preview_mode=False,
        preview_structure=structure,
        job_id=job_id,
        confirm_only=True
    )

    # ---------------- CASE 3: Instant ----------------
    return confirm(job_id)


# ---------------- LOGS ----------------

@app.route("/logs")
def logs_page():
    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]
    settings = get_settings(user_id)

    logs = load_json(LOGS_FILE).get("logs", [])

    user_logs = []
    for i in range(0, len(logs)):
        if logs[i].get("user_id") == user_id:
            user_logs.append(logs[i])

    total = len(user_logs)

    files = 0
    failed = 0

    for log in user_logs:
        files += len(log.get("files", []))
        failed += log.get("failed", 0)

    summary = {
        "total": total,
        "files": files,
        "failed": failed
    }

    return render_template("logs.html", logs=user_logs, summary=summary, settings=settings)


@app.route("/confirm/<job_id>", methods=["GET", "POST"])
def confirm(job_id):

    job_file = os.path.join(TEMP_ROOT, f"{job_id}.json")

    if not os.path.exists(job_file):
        return "Job expired", 404

    # ---------------- LOAD JOB ----------------
    with open(job_file, "r") as f:
        job = json.load(f)

    input_path = job.get("path")

    if not input_path or not os.path.exists(input_path):
        return "Missing uploaded files", 404

    # ---------------- OUTPUT FOLDERS ----------------
    out_base = tempfile.mkdtemp()
    out_dir = os.path.join(out_base, "out")
    os.makedirs(out_dir, exist_ok=True)

    settings = get_settings(job["user_id"])

    success_files = []
    failed_files = []

    # ---------------- PROCESS FILES ----------------
    for filename in job["files"]:
        full = os.path.join(input_path, filename)

        if not os.path.exists(full):
            failed_files.append({
                "name": filename,
                "reason": "File missing",
                "status": "failed"
            })
            continue

        try:
            folder = get_folder(os.path.splitext(filename)[1], settings)
            target = os.path.join(out_dir, folder)
            os.makedirs(target, exist_ok=True)

            shutil.move(full, os.path.join(target, filename))

            success_files.append({
                "name": filename,
                "reason": "Organised successfully",
                "status": "success"
            })

        except Exception as e:
            failed_files.append({
                "name": filename,
                "reason": str(e),
                "status": "failed"
            })

    # ---------------- ZIP ----------------
    zip_path = os.path.join(out_base, "result.zip")

    with ZipFile(zip_path, "w") as z:
        for root, _, files in os.walk(out_dir):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, out_dir))

    # ---------------- LOGGING ----------------
    logs = load_json(LOGS_FILE)

    if "logs" not in logs:
        logs["logs"] = []

    log_entry = {
        "user_id": job["user_id"],
        "time": str(datetime.now()),
        "success": len(success_files),
        "failed": len(failed_files),
        "files": success_files + failed_files
    }

    logs["logs"].append(log_entry)
    logs["logs"] = logs["logs"][-100:]  # limit size
    save_json(LOGS_FILE, logs)

    # ---------------- CLEANUP AFTER RESPONSE ----------------
    @after_this_request
    def cleanup(response):
        shutil.rmtree(input_path, ignore_errors=True)
        os.remove(job_file)
        shutil.rmtree(out_base, ignore_errors=True)
        return response
    print("ZIP EXISTS:", os.path.exists(zip_path))
    print("ZIP PATH:", zip_path)

    return send_file(zip_path, as_attachment=True)

# ---------------- SETTINGS ----------------

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]
    all_settings = load_json(SETTINGS_FILE)

    # ensure user exists
    if user_id not in all_settings:
        all_settings[user_id] = {
            "rules": {},
            "toggles": {
                "auto_open": False,
                "notifications": True,
                "confirm": True,
                "dark_mode": False,
                "preview": True
            }
        }

    if request.method == "POST":

        settings = all_settings[user_id]

        settings["toggles"] = {
            "auto_open": "auto_open" in request.form,
            "notifications": "notifications" in request.form,
            "confirm": "confirm" in request.form,
            "dark_mode": "dark_mode" in request.form,
            "preview": "preview" in request.form
        }

        # rules
        rules = {}
        rules_raw = request.form.get("rules", "").strip()

        if rules_raw:
            parts = rules_raw.split(";")

            for part in parts:
                if ":" not in part:
                    continue

                folder, exts_raw = part.split(":", 1)

                exts = [e.strip().lower() for e in exts_raw.split(",") if e.strip()]

                if exts:
                    rules[folder.strip()] = exts

        settings["rules"] = rules

        all_settings[user_id] = settings
        save_json(SETTINGS_FILE, all_settings)

    return render_template(
        "settings.html",
        settings=all_settings[user_id]
    )
# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)