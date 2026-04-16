"""
PDF Reader module.
Extracts page info from an uploaded PDF file using pikepdf.
"""

import pikepdf


def extract_pages(pdf_path):
    """
    Read a PDF file and return page metadata.
    """
    pdf = pikepdf.Pdf.open(pdf_path)

    return {
        "total": len(pdf.pages),
        "page_sizes": [_get_page_size(p) for p in pdf.pages],
    }


def _get_page_size(page):
    """Get the width and height of a page in points."""
    mbox = page.mediabox
    width = float(mbox[2]) - float(mbox[0])
    height = float(mbox[3]) - float(mbox[1])
    return {"width": width, "height": height}
