"""
Flask backend for Slipgrid — PDF Imposition & Duplex Layout Tool.
Handles file upload, PDF processing, download, and admin panel.
"""

import os
import uuid
import time
import secrets
import logging
import threading
from datetime import timedelta
from functools import wraps
from collections import defaultdict, deque

# Load .env BEFORE importing modules that read environment at import time.
from dotenv_lite import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import pikepdf
from werkzeug.utils import secure_filename
from flask import (
    Flask, request, jsonify, send_file, render_template,
    session, redirect, url_for,
)

from core.pdf_writer import create_imposed_pdf
from core.database import (
    init_db, log_conversion, get_total_conversions, get_today_conversions,
    get_daily_stats, get_recent_conversions, is_service_enabled, set_service_enabled,
    delete_conversion, delete_all_conversions,
    authenticate_admin, get_all_admins, create_admin, delete_admin,
    SUPER_ADMIN,
)

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("slipgrid")

# ─── App & config ────────────────────────────────────────────────
app = Flask(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB
MAX_PDF_PAGES = 500                   # abuse guard on input page count

app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# Secret key MUST come from the environment in production: a random per-process
# fallback breaks sessions across gunicorn workers and restarts.
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY not set — using an ephemeral key. Sessions will reset on "
        "restart and will not be shared across workers. Set SECRET_KEY in .env."
    )
app.secret_key = _secret

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "tmp", "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "tmp", "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Track files for cleanup: {file_id: {"timestamp": ..., "original_name": ...}}
_file_registry = {}
CLEANUP_AFTER_SEC = 600  # 10 minutes

init_db()


# ─── Rate limiting & login lockout (in-memory) ───────────────────
# Note: state is per-process. Behind multiple gunicorn workers limits apply
# per worker; for this single-server deployment that is an acceptable, simple
# abuse guard. Move to Redis if you scale horizontally.

class RateLimiter:
    """Sliding-window limiter: at most `max_events` per `window_sec` per key."""

    def __init__(self, max_events, window_sec):
        self.max = max_events
        self.window = window_sec
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.max:
                return False
            dq.append(now)
            return True


class LoginGuard:
    """Locks out a key after `max_fails` failures within `lock_sec`."""

    def __init__(self, max_fails, lock_sec):
        self.max_fails = max_fails
        self.lock_sec = lock_sec
        self._fails = defaultdict(list)
        self._lock = threading.Lock()

    def is_locked(self, key):
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails[key] if now - t < self.lock_sec]
            self._fails[key] = fails
            return len(fails) >= self.max_fails

    def record_fail(self, key):
        with self._lock:
            self._fails[key].append(time.time())

    def reset(self, key):
        with self._lock:
            self._fails.pop(key, None)


process_limiter = RateLimiter(max_events=20, window_sec=60)
login_guard = LoginGuard(max_fails=5, lock_sec=900)  # 5 failures → 15 min lock


def _client_ip():
    """Best-effort client IP, honouring a single upstream proxy."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ─── File cleanup ────────────────────────────────────────────────
def _cleanup_old_files():
    """Remove files older than CLEANUP_AFTER_SEC."""
    now = time.time()
    to_remove = [fid for fid, info in _file_registry.items()
                 if now - info["timestamp"] > CLEANUP_AFTER_SEC]
    for file_id in to_remove:
        for directory in (UPLOAD_DIR, OUTPUT_DIR):
            for f in os.listdir(directory):
                if f.startswith(file_id):
                    try:
                        os.remove(os.path.join(directory, f))
                    except OSError:
                        pass
        _file_registry.pop(file_id, None)


def _schedule_cleanup():
    """Run cleanup every 60 seconds."""
    _cleanup_old_files()
    t = threading.Timer(60, _schedule_cleanup)
    t.daemon = True
    t.start()


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _validate_pdf(path):
    """Validate a real, openable PDF within limits. Returns page count.

    Raises ValueError with a user-safe message on any problem.
    """
    with open(path, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise ValueError("That file is not a valid PDF.")
    try:
        with pikepdf.open(path) as pdf:
            n = len(pdf.pages)
    except Exception:
        raise ValueError("The PDF could not be read — it may be corrupted or encrypted.")
    if n == 0:
        raise ValueError("The PDF has no pages.")
    if n > MAX_PDF_PAGES:
        raise ValueError(f"The PDF has too many pages (limit is {MAX_PDF_PAGES}).")
    return n


def admin_required(f):
    """Decorator to protect admin routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ─── Public Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ads.txt")
def ads_txt():
    return (
        "google.com, pub-4924359931236069, DIRECT, f08c47fec0942fa0\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@app.route("/api/process", methods=["POST"])
def process_pdf():
    """Upload and process a PDF."""
    if not process_limiter.allow(_client_ip()):
        return jsonify({"error": "Too many requests. Please wait a moment and try again."}), 429

    if not is_service_enabled():
        return jsonify({"error": "Service is temporarily disabled. Please try again later."}), 503

    _cleanup_old_files()

    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400

    pdf_file = request.files["pdf"]
    if pdf_file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    try:
        rows = int(request.form.get("rows", 3))
        cols = int(request.form.get("cols", 3))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid grid dimensions"}), 400

    if not (1 <= rows <= 10 and 1 <= cols <= 10):
        return jsonify({"error": "Grid must be between 1×1 and 10×10"}), 400

    paper_size = request.form.get("paper_size", "A4")
    valid_sizes = ["A4", "Letter", "A3", "Legal"]
    if paper_size not in valid_sizes:
        return jsonify({"error": f"Paper size must be one of: {valid_sizes}"}), 400

    try:
        margin = float(request.form.get("margin", 10))
    except (ValueError, TypeError):
        margin = 10
    margin = max(0, min(margin, 100))

    file_id = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_DIR, f"{file_id}_input.pdf")
    output_path = os.path.join(OUTPUT_DIR, f"{file_id}_output.pdf")

    pdf_file.save(input_path)

    # Validate it is a genuine, sane PDF before doing any work.
    try:
        pages_in = _validate_pdf(input_path)
    except ValueError as e:
        _safe_remove(input_path)
        return jsonify({"error": str(e)}), 400

    # Sanitise the original name; it is only used to build the download filename.
    safe_stem = (secure_filename(os.path.splitext(pdf_file.filename)[0]) or "document")[:60]
    _file_registry[file_id] = {"timestamp": time.time(), "original_name": safe_stem}
    # Persist the name to disk so any gunicorn worker can serve the friendly
    # download filename (in-memory registry is per-worker).
    try:
        with open(os.path.join(OUTPUT_DIR, f"{file_id}.name"), "w", encoding="utf-8") as fh:
            fh.write(safe_stem)
    except OSError:
        pass

    try:
        result = create_imposed_pdf(
            input_pdf_path=input_path,
            output_pdf_path=output_path,
            grid_rows=rows,
            grid_cols=cols,
            paper_size=paper_size,
            margin=margin,
        )
    except Exception:
        logger.exception("PDF processing failed for file_id=%s", file_id)
        _safe_remove(input_path)
        _file_registry.pop(file_id, None)
        return jsonify({"error": "We couldn't process that PDF. Please try a different file."}), 500

    # Input is no longer needed once the output exists.
    _safe_remove(input_path)

    log_conversion(
        filename=safe_stem,
        pages_in=pages_in,
        pages_out=result["output_pages"],
        sheets=result["total_sheets"],
        grid=f"{rows}x{cols}",
        paper_size=paper_size,
    )

    return jsonify({
        "success": True,
        "download_url": f"/api/download/{file_id}",
        "total_sheets": result["total_sheets"],
        "output_pages": result["output_pages"],
    })


@app.route("/api/download/<file_id>")
def download_pdf(file_id):
    """Download a processed PDF."""
    if not file_id.isalnum() or len(file_id) != 12:
        return jsonify({"error": "Invalid file ID"}), 400

    output_path = os.path.join(OUTPUT_DIR, f"{file_id}_output.pdf")
    if not os.path.exists(output_path):
        return jsonify({"error": "File not found or expired"}), 404

    stem = ""
    info = _file_registry.get(file_id)
    if info and info.get("original_name"):
        stem = info["original_name"]
    else:
        # Fall back to the on-disk sidecar (download may hit a different worker).
        name_path = os.path.join(OUTPUT_DIR, f"{file_id}.name")
        if os.path.exists(name_path):
            try:
                with open(name_path, "r", encoding="utf-8") as fh:
                    stem = fh.read().strip()
            except OSError:
                stem = ""
    stem = secure_filename(stem)
    download_name = f"{stem}_imposed.pdf" if stem else "imposed_output.pdf"

    return send_file(
        output_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


# ─── Admin Routes ────────────────────────────────────────────────

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    """Admin login page."""
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))

    error = None
    if request.method == "POST":
        ip = _client_ip()
        if login_guard.is_locked(ip):
            error = "Too many failed attempts. Try again later."
            return render_template("admin_login.html", error=error), 429

        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if authenticate_admin(username, password):
            login_guard.reset(ip)
            session.clear()
            session["admin_logged_in"] = True
            session["admin_user"] = username
            session.permanent = True
            return redirect(url_for("admin_dashboard"))
        else:
            login_guard.record_fail(ip)
            logger.warning("Failed admin login for '%s' from %s", username, ip)
            error = "Invalid username or password"

    return render_template("admin_login.html", error=error)


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Admin dashboard with analytics and service control."""
    current_user = session.get("admin_user", "")
    is_super = current_user == SUPER_ADMIN
    return render_template(
        "admin_dashboard.html",
        service_enabled=is_service_enabled(),
        total_conversions=get_total_conversions(),
        today_conversions=get_today_conversions(),
        daily_stats=get_daily_stats(30),
        recent=get_recent_conversions(50),
        admins=get_all_admins() if is_super else [],
        is_super=is_super,
        current_user=current_user,
    )


@app.route("/admin/toggle-service", methods=["POST"])
@admin_required
def toggle_service():
    """Enable or disable the processing service."""
    action = request.form.get("action")
    if action == "start":
        set_service_enabled(True)
    elif action == "stop":
        set_service_enabled(False)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete-conversion/<int:conv_id>", methods=["POST"])
@admin_required
def delete_conversion_route(conv_id):
    """Delete a single conversion record."""
    delete_conversion(conv_id)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reset-analytics", methods=["POST"])
@admin_required
def reset_analytics():
    """Delete all conversion records."""
    delete_all_conversions()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/create-admin", methods=["POST"])
@admin_required
def create_admin_route():
    """Create a new admin (super admin only)."""
    if session.get("admin_user") != SUPER_ADMIN:
        return redirect(url_for("admin_dashboard"))
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    create_admin(username, password)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete-admin/<int:admin_id>", methods=["POST"])
@admin_required
def delete_admin_route(admin_id):
    """Delete an admin (super admin only)."""
    if session.get("admin_user") != SUPER_ADMIN:
        return redirect(url_for("admin_dashboard"))
    delete_admin(admin_id)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    """Logout admin."""
    session.clear()
    return redirect(url_for("admin_login"))


# ─── Security headers & error handling ───────────────────────────

@app.after_request
def _security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com "
        "https://*.googlesyndication.com https://*.googleadservices.com "
        "https://*.google.com https://*.doubleclick.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "frame-src https://*.googlesyndication.com https://*.doubleclick.net https://*.google.com; "
        "connect-src 'self' https:; "
        "object-src 'none'; base-uri 'self'"
    )
    return resp


def _error_response(code, message):
    """JSON for API paths, branded HTML page otherwise."""
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), code
    return render_template("error.html", code=code, message=message), code


@app.errorhandler(404)
def _not_found(e):
    return _error_response(404, "Page not found.")


@app.errorhandler(413)
def _too_large(e):
    return _error_response(413, "That file is too large. The maximum upload size is 50 MB.")


@app.errorhandler(429)
def _too_many(e):
    return _error_response(429, "Too many requests. Please slow down and try again shortly.")


@app.errorhandler(500)
def _server_error(e):
    logger.exception("Unhandled server error")
    return _error_response(500, "Something went wrong on our side. Please try again.")


# Start auto-cleanup timer on import
_schedule_cleanup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    # debug stays off — never expose tracebacks to users.
    app.run(host="0.0.0.0", port=port)
