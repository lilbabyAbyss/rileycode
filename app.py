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
    ".py", ".html", ".css", ".js"
    ".mp3", ".mp4", ".ico", ".3vs",
    ".exe"
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
def get_folder(ext, rules):
    ext = ext.lower()

    for folder, exts in rules.items():
        if ext in exts:
            return folder

    if ext in [".jpg", ".jpeg", ".png", ".ico"]:
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

    if request.method == "POST":
        files = request.files.getlist("files")
        if not files or files[0].filename == "":
            return "No files uploaded"

        user_id = session.get("user_id", "guest")

        base = tempfile.mkdtemp()
        out_dir = os.path.join(base, "organised")
        os.makedirs(out_dir, exist_ok=True)

        count = 0
        failed = []

        settings_all = load_json(SETTINGS_FILE)
        rules = settings_all.get(user_id, {}).get("rules", {})

        for file in files:
            if not validate_file(file):
                failed.append(file.filename)
                continue

            filename = file.filename
            ext = os.path.splitext(filename)[1].lower()

            folder = get_folder(ext, rules)
            target = os.path.join(out_dir, folder)
            os.makedirs(target, exist_ok=True)

            file.save(os.path.join(target, filename))
            count += 1

        zip_path = os.path.join(base, "output.zip")

        with ZipFile(zip_path, "w") as zipf:
            for root, _, fs in os.walk(out_dir):
                for f in fs:
                    full = os.path.join(root, f)
                    zipf.write(full, os.path.relpath(full, out_dir))

        # ---------------- LOGS ----------------
        data = load_json(LOGS_FILE)
        logs = data.get("logs", [])

        logs.append({
            "user_id": user_id,
            "username": session.get("user"),
            "time": str(datetime.now()),
            "files": count,
            "failed": len(failed)
        })

        data["logs"] = logs
        save_json(LOGS_FILE, data)

        return send_file(zip_path, as_attachment=True)

    return render_template("index.html")


# ---------------- LOGS PAGE ----------------
@app.route("/logs")
def logs_page():

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

    return render_template("logs.html", logs=user_logs, summary=summary)


# ---------------- SETTINGS ----------------
@app.route("/settings", methods=["GET", "POST"])
def settings():

    if "user_id" not in session:
        return redirect("/auth?mode=login")

    all_settings = load_json(SETTINGS_FILE)
    user_id = session["user_id"]

    if request.method == "POST":
        rules = request.form.get("rules")
        parsed = {}

        if rules:
            for part in rules.split(";"):
                if ":" in part:
                    folder, exts = part.split(":")
                    parsed[folder.strip()] = [e.strip().lower() for e in exts.split(",")]

        all_settings[user_id] = {"rules": parsed}
        save_json(SETTINGS_FILE, all_settings)

    return render_template("settings.html", settings=all_settings.get(user_id, {}))


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)