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
    ".mp3", ".mp4", ".ico", ".3vs",
    ".exe", ".XLSX", 
}

MAX_SIZE_MB = 10


# ---------------- JSON HELPERS ----------------
def load_json(file):
    if not os.path.exists(file):
        return {}

    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ---------------- FILE ORGANISER ----------------
def get_folder(ext, settings=None):
    ext = ext.lower()

    # --- Custom rules ---
    if settings and "rules" in settings:
        for folder, exts in settings["rules"].items():
            if ext in exts:
                return folder

    # --- Default fallback ---
    if ext in [".jpg", ".jpeg", ".png"]:
        return "Images"
    elif ext in [".pdf", ".docx", ".txt"]:
        return "Documents"
    elif ext in [".py", ".html", ".css", ".js"]:
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

        # ---------------- LOGIN ----------------
        if mode == "login":
            for u in users:
                if (
                    (u.get("username") == username_or_email or u.get("email") == username_or_email)
                    and u.get("password") == password
                ):
                    session["user_id"] = u["id"]
                    session["user"] = u["username"]
                    return redirect("/")

            return redirect("/auth?mode=login")

        # ---------------- SIGNUP ----------------
        if mode == "signup":

            for u in users:
                if u.get("username") == username_or_email or u.get("email") == email:
                    session["user_id"] = u["id"]
                    session["user"] = u["username"]
                    return redirect("/")

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

    return render_template("auth.html", mode=mode)


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/auth?mode=login")


# ---------------- HOME (FILE ORGANISER) ----------------
@app.route("/", methods=["GET", "POST"])
def home():

    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]

    settings_all = load_json(SETTINGS_FILE)
    user_id = session.get("user_id")

    settings = settings_all.get(user_id, {})
    toggles = settings.get("toggles", {})
    
    # Load user settings
    all_settings = load_json(SETTINGS_FILE)
    user_settings = all_settings.get(user_id, {})

    toggles = user_settings.get("toggles", {})
    rules = user_settings.get("rules", {})

    if request.method == "POST":

        # --- Confirm before organising ---
        if toggles.get("confirm"):
            if request.form.get("confirm_run") != "yes":
                return "Confirmation required"

        files = request.files.getlist("files")
        if not files or files[0].filename == "":
            return "No files uploaded"

        base = tempfile.mkdtemp()
        out_dir = os.path.join(base, "organised")
        os.makedirs(out_dir, exist_ok=True)

        count = 0
        failed = []

        for file in files:

            if not validate_file(file):
                failed.append(file.filename)
                continue

            filename = file.filename
            ext = os.path.splitext(filename)[1]

            # --- Use custom rules ---
            folder = get_folder(ext, user_settings)

            target = os.path.join(out_dir, folder)
            os.makedirs(target, exist_ok=True)

            path = os.path.join(target, filename)
            file.save(path)

            # --- Preserve timestamps ---
            if toggles.get("timestamps"):
                now = datetime.now().timestamp()
                os.utime(path, (now, now))

            count += 1

        zip_path = os.path.join(base, "output.zip")

        with ZipFile(zip_path, "w") as zipf:
            for root, _, fs in os.walk(out_dir):
                for f in fs:
                    full = os.path.join(root, f)
                    zipf.write(full, os.path.relpath(full, out_dir))

                    if toggles.get("confirm", True):
                        if request.form.get("confirm_run") != "yes":
                         return render_template(
                "index.html",
                confirm_needed=True
        )

        # --- Logging ---
        data = load_json(LOGS_FILE)
        logs = data.get("logs", [])

        logs.append({
            "user_id": user_id,
            "time": str(datetime.now()),
            "files": count,
            "failed": len(failed)
        })

        data["logs"] = logs
        save_json(LOGS_FILE, data)

        # --- Notifications (basic version) ---
        if toggles.get("notifications"):
            print(f"[NOTIFY] {count} files organised")

        # --- Auto-open folder (Windows only) ---
        if toggles.get("auto_open"):
            try:
                os.startfile(out_dir)
            except:
                pass

        return send_file(zip_path, as_attachment=True)

    return render_template("index.html", settings=user_settings)

# ---------------- LOGS PAGE ----------------
@app.route("/logs")
def logs_page():

    user_id = session.get("user_id")
    all_settings = load_json(SETTINGS_FILE)

    user_settings = all_settings.get(user_id, {
        "toggles": {
            "dark_mode": False
        }
    })

    if "user_id" not in session:
        return redirect("/auth?mode=login")

    data = load_json(LOGS_FILE)
    logs = data.get("logs", [])

    user_id = session["user_id"]
    user_logs = [l for l in logs if l.get("user_id") == user_id]

    summary = {
        "total": len(user_logs),
        "files": sum(l.get("files", 0) for l in user_logs),
        "failed": sum(l.get("failed", 0) for l in user_logs)
    }

    return render_template(
        "logs.html",
        logs=user_logs,
        summary=summary,
        settings=user_settings
    )

# ---------------- SETTINGS ----------------
@app.route("/settings", methods=["GET", "POST"])
def settings():

    if "user_id" not in session:
        return redirect("/auth?mode=login")

    user_id = session["user_id"]

    # -------- LOAD FILE SAFELY --------
    all_settings = load_json(SETTINGS_FILE)

    if not isinstance(all_settings, dict):
        all_settings = {}

    # -------- DEFAULT STRUCTURE --------
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

    # -------- ENSURE USER EXISTS --------
    if user_id not in all_settings:
        all_settings[user_id] = default_settings.copy()

    user_settings = all_settings[user_id]

    # -------- ENSURE KEYS EXIST (FOR OLD FILES) --------
    if not isinstance(user_settings, dict):
        user_settings = default_settings.copy()

    user_settings.setdefault("rules", {})
    user_settings.setdefault("toggles", {})

    # Ensure each toggle exists individually
    for key, value in default_settings["toggles"].items():
        user_settings["toggles"].setdefault(key, value)

    # -------- SAVE SETTINGS --------
    if request.method == "POST":

        # Toggles
        user_settings["toggles"] = {
            "auto_open": "auto_open" in request.form,
            "notifications": "notifications" in request.form,
            "confirm": "confirm" in request.form,
            "timestamps": "timestamps" in request.form,
            "dark_mode": "dark_mode" in request.form,
            "animations": "animations" in request.form,
        }

        # Rules
        rules_raw = request.form.get("rules", "")
        parsed_rules = {}

        if rules_raw.strip():
            for part in rules_raw.split(";"):
                if ":" in part:
                    folder, exts = part.split(":", 1)
                    parsed_rules[folder.strip()] = [
                        e.strip().lower()
                        for e in exts.split(",")
                        if e.strip()
                    ]

        user_settings["rules"] = parsed_rules

        # Save back
        all_settings[user_id] = user_settings
        save_json(SETTINGS_FILE, all_settings)

    return render_template("settings.html", settings=user_settings)



# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)