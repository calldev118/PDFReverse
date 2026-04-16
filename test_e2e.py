"""Quick end-to-end test: generate a sample PDF, run it through the imposer, verify output."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import pikepdf


def create_test_pdf(output_path, num_pages=20):
    """Create a test PDF with numbered pages using reportlab."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    for i in range(1, num_pages + 1):
        c.setFont("Helvetica-Bold", 72)
        c.drawCentredString(w / 2, h / 2, str(i))
        c.setStrokeColorRGB(0.3, 0.3, 0.3)
        c.rect(20, 20, w - 40, h - 40)
        c.setFont("Helvetica", 14)
        c.drawCentredString(w / 2, h / 2 - 60, f"Page {i} of {num_pages}")
        c.showPage()

    c.save()

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())

    print(f"Created test PDF: {output_path} ({num_pages} pages)")


def test_imposer():
    """Test the full imposition pipeline."""
    from core.pdf_writer import create_imposed_pdf

    test_input = "/tmp/test_input.pdf"
    test_output = "/tmp/test_output.pdf"

    create_test_pdf(test_input, num_pages=20)

    start = time.perf_counter()
    result = create_imposed_pdf(
        input_pdf_path=test_input,
        output_pdf_path=test_output,
        grid_rows=3,
        grid_cols=3,
        paper_size="A4",
        margin=10,
    )
    elapsed = time.perf_counter() - start

    # Verify output
    out_pdf = pikepdf.Pdf.open(test_output)
    assert len(out_pdf.pages) == result["output_pages"], "Page count mismatch!"
    out_pdf.close()

    print(f"\nImposition result:")
    print(f"  Total sheets: {result['total_sheets']}")
    print(f"  Output pages: {result['output_pages']}")
    print(f"  File size:    {os.path.getsize(test_output) / 1024:.1f} KB")
    print(f"  Time:         {elapsed * 1000:.0f} ms")
    print(f"\n  End-to-end test passed!")


if __name__ == "__main__":
    test_imposer()
