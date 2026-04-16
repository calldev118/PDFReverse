"""
PDF Reader module.
Extracts individual pages from an uploaded PDF file.
"""

from PyPDF2 import PdfReader


def extract_pages(pdf_path):
    """
    Read a PDF file and return a list of page objects.
    Each element is a PyPDF2 PageObject that can be placed onto a new PDF.
    """
    reader = PdfReader(pdf_path)
    pages = list(reader.pages)

    return {
        "pages": pages,
        "total": len(pages),
        "page_sizes": [_get_page_size(p) for p in pages],
    }


def _get_page_size(page):
    """Get the width and height of a page in points."""
    box = page.mediabox
    width = float(box.width)
    height = float(box.height)
    return {"width": width, "height": height}
