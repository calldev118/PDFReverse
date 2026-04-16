"""
Flask backend for PDF Print Layout Tool.
Handles file upload, PDF processing, and download.
"""

import os
import uuid
import time
import threading

from flask import Flask, request, jsonify, send_file, render_template

from core.pdf_writer import create_imposed_pdf

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB limit

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "tmp", "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "tmp", "output")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Track files for cleanup: {file_id: creation_timestamp}
_file_registry = {}
CLEANUP_AFTER_SEC = 600  # 10 minutes


def _cleanup_old_files():
    """Remove files older than CLEANUP_AFTER_SEC."""
    now = time.time()
    to_remove = []
    for file_id, ts in _file_registry.items():
        if now - ts > CLEANUP_AFTER_SEC:
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/process", methods=["POST"])
def process_pdf():
    """
    Upload and process a PDF.
    Expects: multipart form with 'pdf' file, 'rows' (int), 'cols' (int),
             optional 'paper_size' (str), optional 'margin' (float).
    Returns: JSON with download URL.
    """
    _cleanup_old_files()

    # Validate file
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400

    pdf_file = request.files["pdf"]
    if pdf_file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    # Validate grid params
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
    margin = max(0, min(margin, 100))  # Clamp 0-100

    # Save uploaded file
    file_id = uuid.uuid4().hex[:12]
    input_filename = f"{file_id}_input.pdf"
    output_filename = f"{file_id}_output.pdf"

    input_path = os.path.join(UPLOAD_DIR, input_filename)
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    pdf_file.save(input_path)
    _file_registry[file_id] = time.time()

    # Process
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
        # Clean up on failure
        try:
            os.remove(input_path)
        except OSError:
            pass
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "download_url": f"/api/download/{file_id}",
        "total_sheets": result["total_sheets"],
        "output_pages": result["output_pages"],
    })


@app.route("/api/download/<file_id>")
def download_pdf(file_id):
    """Download a processed PDF."""
    # Sanitize file_id to prevent path traversal
    if not file_id.isalnum() or len(file_id) != 12:
        return jsonify({"error": "Invalid file ID"}), 400

    output_filename = f"{file_id}_output.pdf"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    if not os.path.exists(output_path):
        return jsonify({"error": "File not found or expired"}), 404

    return send_file(
        output_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="imposed_output.pdf",
    )


if __name__ == "__main__":
    _schedule_cleanup()
    app.run(debug=True, port=5000)
