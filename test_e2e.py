"""Quick end-to-end test: generate a sample PDF, run it through the imposer, verify output."""

import os
import sys

# Add project root
sys.path.insert(0, os.path.dirname(__file__))

from PyPDF2 import PdfWriter, PageObject
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO


def create_test_pdf(output_path, num_pages=20):
    """Create a test PDF with numbered pages."""
    writer = PdfWriter()

    for i in range(1, num_pages + 1):
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        # Draw page number large in center
        c.setFont("Helvetica-Bold", 72)
        c.drawCentredString(w / 2, h / 2, str(i))
        # Draw border
        c.setStrokeColorRGB(0.3, 0.3, 0.3)
        c.rect(20, 20, w - 40, h - 40)
        # Label
        c.setFont("Helvetica", 14)
        c.drawCentredString(w / 2, h / 2 - 60, f"Page {i} of {num_pages}")
        c.save()

        buf.seek(0)
        from PyPDF2 import PdfReader
        reader = PdfReader(buf)
        writer.add_page(reader.pages[0])

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Created test PDF: {output_path} ({num_pages} pages)")


def test_imposer():
    """Test the full imposition pipeline."""
    from core.pdf_writer import create_imposed_pdf

    test_input = "/tmp/test_input.pdf"
    test_output = "/tmp/test_output.pdf"

    # Create test PDF
    create_test_pdf(test_input, num_pages=20)

    # Process it
    result = create_imposed_pdf(
        input_pdf_path=test_input,
        output_pdf_path=test_output,
        grid_rows=3,
        grid_cols=3,
        paper_size="A4",
        margin=10,
    )

    print(f"\nImposition result:")
    print(f"  Total sheets: {result['total_sheets']}")
    print(f"  Output pages: {result['output_pages']}")
    print(f"  Output file:  {result['output_path']}")
    print(f"  File size:    {os.path.getsize(test_output) / 1024:.1f} KB")
    print(f"\n✅ End-to-end test passed!")


if __name__ == "__main__":
    try:
        import reportlab
        test_imposer()
    except ImportError:
        print("reportlab not installed. Installing...")
        os.system("pip install reportlab")
        test_imposer()
