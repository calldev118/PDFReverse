"""
Flask backend for PDF Print Layout Tool.
Handles file upload, PDF processing, download, and admin panel.
"""

import os
import uuid
import time
import hashlib
import secrets
import threading
from functools import wraps

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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB limit
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "tmp", "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "tmp", "output")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Track files for cleanup: {file_id: {"timestamp": ..., "original_name": ...}}
_file_registry = {}
CLEANUP_AFTER_SEC = 600  # 10 minutes

# Initialize database
init_db()


def _cleanup_old_files():
    """Remove files older than CLEANUP_AFTER_SEC."""
    now = time.time()
    to_remove = []
    for file_id, info in _file_registry.items():
        if now - info["timestamp"] > CLEANUP_AFTER_SEC:
            to_remove.append(file_id)

    for file_id in to_remove:
        for directory in [UPLOAD_DIR, OUTPUT_DIR]:
            for f in os.listdir(directory):
                if f.startswith(file_id):
                    path = os.path.join(directory, f)
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        _file_registry.pop(file_id, None)


def _schedule_cleanup():
    """Run cleanup every 60 seconds."""
    _cleanup_old_files()
    t = threading.Timer(60, _schedule_cleanup)
    t.daemon = True
    t.start()


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


@app.route("/api/process", methods=["POST"])
def process_pdf():
    """Upload and process a PDF."""
    # Check if service is enabled
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
    input_filename = f"{file_id}_input.pdf"
    output_filename = f"{file_id}_output.pdf"

    input_path = os.path.join(UPLOAD_DIR, input_filename)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    pdf_file.save(input_path)

    original_name = os.path.splitext(pdf_file.filename)[0]
    _file_registry[file_id] = {
        "timestamp": time.time(),
        "original_name": original_name,
    }

    try:
        result = create_imposed_pdf(
            input_pdf_path=input_path,
            output_pdf_path=output_path,
            grid_rows=rows,
            grid_cols=cols,
            paper_size=paper_size,
            margin=margin,
        )
    except Exception as e:
        try:
            os.remove(input_path)
        except OSError:
            pass
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500

    # Log to analytics
    import pikepdf
    try:
        src = pikepdf.Pdf.open(input_path)
        pages_in = len(src.pages)
        src.close()
    except Exception:
        pages_in = 0

    log_conversion(
        filename=pdf_file.filename,
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

    output_filename = f"{file_id}_output.pdf"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    if not os.path.exists(output_path):
        return jsonify({"error": "File not found or expired"}), 404

    info = _file_registry.get(file_id)
    if info and info.get("original_name"):
        download_name = f"{info['original_name']}_imposed.pdf"
    else:
        download_name = "imposed_output.pdf"

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
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if authenticate_admin(username, password):
            session["admin_logged_in"] = True
            session["admin_user"] = username
            session.permanent = True
            return redirect(url_for("admin_dashboard"))
        else:
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
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# Start auto-cleanup timer on import
_schedule_cleanup()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
