# app.py
import os
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# image thumbnail
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Load env
load_dotenv()

BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"
MESSAGES_DIR = BASE_DIR / "messages"
UPLOADS_DIR = BASE_DIR / "static" / "uploads"

for d in (CONTENT_DIR, MESSAGES_DIR, UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")
ALLOWED_EXT = set(os.getenv("ALLOWED_EXT", "png,jpg,jpeg,webp").split(","))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "5")) * 1024 * 1024  # MB to bytes

app = Flask(__name__, static_folder="static")
CORS(app, origins=os.getenv("CORS_ORIGINS", "http://localhost:3000"))

def load_json_file(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)

def save_json_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_allowed_filename(filename: str):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXT

def make_thumbnail(src_path: Path, thumb_path: Path, size=(800,800)):
    if not PIL_AVAILABLE:
        return False
    try:
        with Image.open(src_path) as img:
            img.thumbnail(size)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(thumb_path)
        return True
    except Exception:
        return False

# ---------------- Routes ------------------

@app.route("/api/pages/<slug>", methods=["GET"])
def get_page(slug):
    lang = request.args.get("lang", "ar")
    path = CONTENT_DIR / lang / f"{slug}.json"
    data = load_json_file(path)
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)

@app.route("/api/pages", methods=["GET"])
def list_pages():
    lang = request.args.get("lang", "ar")
    dirpath = CONTENT_DIR / lang
    pages = []
    if dirpath.exists():
        for p in dirpath.glob("*.json"):
            d = load_json_file(p)
            if d:
                pages.append({"slug": p.stem, "title": d.get("title")})
    return jsonify(pages)

@app.route("/api/projects", methods=["GET"])
def list_projects():
    lang = request.args.get("lang", "ar")
    dirpath = CONTENT_DIR / lang / "projects"
    projects = []
    if dirpath.exists():
        for p in dirpath.glob("*.json"):
            d = load_json_file(p)
            if d:
                projects.append({
                    "slug": p.stem,
                    "title": d.get("title"),
                    "summary": d.get("summary"),
                    "images": d.get("images", [])
                })
    return jsonify(projects)

@app.route("/api/projects/<slug>", methods=["GET"])
def get_project(slug):
    lang = request.args.get("lang", "ar")
    path = CONTENT_DIR / lang / "projects" / f"{slug}.json"
    data = load_json_file(path)
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)

@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()
    if not name or not email or not message:
        return jsonify({"error": "name, email, message required"}), 400

    entry = {
        "name": name,
        "email": email,
        "message": message,
        "received_at": datetime.utcnow().isoformat() + "Z"
    }
    # Save backup copy
    filename = MESSAGES_DIR / f"message_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
    save_json_file(filename, entry)

    # Try to send email if configured (simple smtplib) - optional
    # If not configured, we already saved the message.
    smtp_host = os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_port = int(os.getenv("SMTP_PORT", "587") or 587)
    admin_email = os.getenv("ADMIN_EMAIL")
    if smtp_host and smtp_user and smtp_pass and admin_email:
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["Subject"] = f"Contact from {name}"
            msg["From"] = smtp_user
            msg["To"] = admin_email
            msg.set_content(f"From: {name} <{email}>\n\n{message}")
            with smtplib.SMTP(smtp_host, smtp_port) as s:
                s.starttls()
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)
            return jsonify({"status": "sent"}), 200
        except Exception as e:
            return jsonify({"status":"saved","note":str(e)}), 200
    return jsonify({"status":"saved"}), 200

@app.route("/api/uploads", methods=["POST"])
def uploads():
    if "file" not in request.files:
        return jsonify({"error":"file required"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error":"filename empty"}), 400
    filename = secure_filename(f.filename)
    if not is_allowed_filename(filename):
        return jsonify({"error":"file type not allowed"}), 400
    # limit size
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > MAX_UPLOAD_SIZE:
        return jsonify({"error":"file too large"}), 400

    # unique name
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    name = f"{timestamp}_{filename}"
    save_path = UPLOADS_DIR / name
    f.save(save_path)

    # make thumbnail (optional)
    thumb_name = f"thumb_{name}"
    thumb_path = UPLOADS_DIR / thumb_name
    thumb_created = False
    if PIL_AVAILABLE:
        try:
            thumb_created = make_thumbnail(save_path, thumb_path, size=(1200,1200))
        except Exception:
            thumb_created = False

    url = f"/uploads/{name}"
    thumb_url = f"/uploads/{thumb_name}" if thumb_created else None
    return jsonify({"url": url, "thumbnail": thumb_url}), 200

@app.route("/api/pages", methods=["POST"])
def create_page():
    token = request.headers.get("X-ADMIN-TOKEN")
    if token != ADMIN_TOKEN:
        return jsonify({"error":"unauthorized"}), 401
    data = request.get_json() or {}
    lang = data.get("lang", "ar")
    slug = data.get("slug")
    if not slug:
        return jsonify({"error":"slug required"}), 400
    path = CONTENT_DIR / lang / f"{slug}.json"
    if path.exists():
        return jsonify({"error":"already exists"}), 400
    save_json_file(path, data)
    return jsonify({"status":"created","slug":slug}), 201

@app.route("/uploads/<path:filename>")
def uploads_serve(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)

# health
@app.route("/api/health")
def health():
    return jsonify({"status":"ok","time": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
