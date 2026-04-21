from flask import Flask, render_template, request, send_file, redirect, session
import os, json, tempfile, uuid
from zipfile import ZipFile
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------------- FILES ----------------
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


# ---------------- JSON HELPERS ----------------
def load_json(file):
    if not os.path.exists(file):
        return {}
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# ---------------- GLOBAL SETTINGS INJECTION ----------------
def inject_settings():
    if "user_id" in session:
        all_settings = load_json(SETTINGS_FILE)

        default = {
            "rules": {},
            "toggles": {
                "auto_open": False,
                "notifications": True,
                "confirm": True,
                "timestamps": True,
                "dark_mode": False,
                "animations": True
            }
        }

        user_settings = all_settings.get(session["user_id"], default)

        # Ensure structure is always valid
        user_settings.setdefault("rules", {})
        user_settings.setdefault("toggles", default["toggles"])

        return {"settings": user_settings}

    # Not logged in → safe default
    return {
        "settings": {
            "rules": {},
            "toggles": {
                "dark_mode": False,
                "animations": True
            }
        }
    }

# ---------------- SETTINGS CORE ----------------
def get_settings(user_id):
    all_settings = load_json(SETTINGS_FILE)

    default_settings = {
        "rules": {},
        "toggles": {
            "auto_open": False,
            "notifications": True,
            "confirm": True,
            "timestamps": True,
            "dark_mode": False,
            "animations": True
        }
    }

    user_settings = all_settings.get(user_id, default_settings)

    user_settings.setdefault("rules", {})
    user_settings.setdefault("toggles", default_settings["toggles"])

    return user_settings

# ---------------- FILE ORGANISER ----------------
def get_folder(ext, settings):
    ext = ext.lower().strip()

    rules = settings.get("rules", {})

    for folder, exts in rules.items():
        cleaned = [e.lower().strip() for e in exts]

        if ext in cleaned:
            return folder

    # --- DEFAULT FALLBACK ---
    if ext in [".jpg", ".jpeg", ".png"]:
        return "Images"
    elif ext in [".pdf", ".docx", ".txt"]:
        return "Documents"
    elif ext in [".py", ".html", ".css", ".js"]:
        return "CodeFiles"
    else:
        return "OtherFiles"


def validate_file(file):
    ext = os.path.splitext(file.filename)[1].lower().strip()

    if ext not in ALLOWED_EXTENSIONS:
        return False

    file.seek(0, os.SEEK_END)
    size = file.tell() / (1024 * 1024)
    file.seek(0)

    return size <= MAX_SIZE_MB


# ---------------- AUTH ----------------
@app.route("/auth", methods=["GET", "POST"])
def auth():
    mode = request.args.get("mode", "login")

    data = load_json(USERS_FILE)
    users = data.get("users", [])

    if request.method == "POST":
        username_or_email = request.form["username"]
        password = request.form["password"]
        email = request.form.get("email")

        # LOGIN
        if mode == "login":
            for u in users:
                if (u["username"] == username_or_email or u.get("email") == username_or_email) and u["password"] == password:
                    session["user_id"] = u["id"]
                    session["user"] = u["username"]
                    return redirect("/")
            return redirect("/auth?mode=login")

        # SIGNUP
        if mode == "signup":
            for u in users:
                if u["username"] == username_or_email or u.get("email") == email:
                    return redirect("/auth?mode=login")

            new_user = {
                "id": str(uuid.uuid4()),
                "username": username_or_email,
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
    settings = get_settings(user_id)
    toggles = settings["toggles"]

    if request.method == "POST":

        if toggles["confirm"] and request.form.get("confirm_run") != "yes":
            return "Confirmation required"

        files = request.files.getlist("files")
        if not files or files[0].filename == "":
            return "No files"

        base = tempfile.mkdtemp()
        out_dir = os.path.join(base, "out")
        os.makedirs(out_dir, exist_ok=True)

        count = 0
        failed = []

        for file in files:
            if not validate_file(file):
                failed.append(file.filename)
                continue

            ext = os.path.splitext(file.filename)[1].lower().strip()
            folder = get_folder(ext, settings)

            target = os.path.join(out_dir, folder)
            os.makedirs(target, exist_ok=True)

            path = os.path.join(target, file.filename)
            file.save(path)

            if toggles["timestamps"]:
                now = datetime.now().timestamp()
                os.utime(path, (now, now))

            count += 1

        zip_path = os.path.join(base, "result.zip")

        with ZipFile(zip_path, "w") as zipf:
            for root, _, files in os.walk(out_dir):
                for f in files:
                    full = os.path.join(root, f)
                    zipf.write(full, os.path.relpath(full, out_dir))

        # LOGS
        logs = load_json(LOGS_FILE)
        log_list = logs.get("logs", [])

        log_list.append({
            "user_id": user_id,
            "time": str(datetime.now()),
            "files": count,
            "failed": len(failed)
        })

        logs["logs"] = log_list
        save_json(LOGS_FILE, logs)

        if toggles["auto_open"]:
            try:
                os.startfile(out_dir)
            except:
                pass

        return send_file(zip_path, as_attachment=True)

    return render_template("index.html", settings=settings)


# ---------------- LOGS ----------------
@app.route("/logs")
def logs_page():
    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]
    settings = get_settings(user_id)

    logs = load_json(LOGS_FILE).get("logs", [])
    user_logs = [l for l in logs if l.get("user_id") == user_id]

    summary = {
        "total": len(user_logs),
        "files": sum(l["files"] for l in user_logs),
        "failed": sum(l["failed"] for l in user_logs)
    }

    return render_template("logs.html", logs=user_logs, summary=summary, settings=settings)


# ---------------- SETTINGS ----------------
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]
    all_settings = load_json(SETTINGS_FILE)

    all_settings = load_json(SETTINGS_FILE)
    settings = all_settings.get(user_id, get_settings(user_id))

    if request.method == "POST":

        settings["toggles"] = {
            "auto_open": "auto_open" in request.form,
            "notifications": "notifications" in request.form,
            "confirm": "confirm" in request.form,
            "timestamps": "timestamps" in request.form,
            "dark_mode": "dark_mode" in request.form,
            "animations": "animations" in request.form,
        }

        rules_raw = request.form.get("rules", "")
        rules = {}

        if rules_raw.strip():
            for part in rules_raw.split(";"):
                if ":" in part:
                    folder, exts = part.split(":")
                    rules[folder.strip()] = [
                    e.strip().lower()
                    for e in exts.split(",")
]

        settings["rules"] = rules

        all_settings[user_id] = settings
        save_json(SETTINGS_FILE, all_settings)

    return render_template("settings.html", settings=settings)


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)