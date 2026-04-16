"""
PDF Writer module.
Takes the sheet layouts from imposer and renders them into a new PDF.
Each sheet becomes two pages in the output: front and back.
"""

import copy

from PyPDF2 import PdfReader, PdfWriter, PageObject, Transformation

from .imposer import build_sheet_layout


# Standard paper sizes in points (72 points = 1 inch)
PAPER_SIZES = {
    "A4": (595.28, 841.89),     # 210mm × 297mm
    "Letter": (612, 792),        # 8.5" × 11"
    "A3": (841.89, 1190.55),    # 297mm × 420mm
    "Legal": (612, 1008),        # 8.5" × 14"
}


def create_imposed_pdf(input_pdf_path, output_pdf_path, grid_rows, grid_cols,
                       paper_size="A4", margin=10):
    """
    Main function: takes an input PDF, creates an imposed output PDF
    with front/back sheets arranged in grid with horizontal row reversal on back.

    Args:
        input_pdf_path: Path to source PDF
        output_pdf_path: Path for output PDF
        grid_rows: Number of rows in grid
        grid_cols: Number of columns in grid
        paper_size: Output paper size name
        margin: Margin in points around each cell
    """
    reader = PdfReader(input_pdf_path)
    source_pages = list(reader.pages)
    total_pages = len(source_pages)

    # Build the layout using page indices (0-based)
    page_indices = list(range(total_pages))
    sheets = build_sheet_layout(page_indices, grid_rows, grid_cols)

    # Output paper dimensions
    paper_w, paper_h = PAPER_SIZES.get(paper_size, PAPER_SIZES["A4"])

    # Cell dimensions
    cell_w = (paper_w - margin * 2) / grid_cols
    cell_h = (paper_h - margin * 2) / grid_rows

    writer = PdfWriter()

    for sheet in sheets:
        # Render front page
        front_page = _render_grid_page(
            source_pages, sheet["front"], grid_rows, grid_cols,
            paper_w, paper_h, cell_w, cell_h, margin
        )
        writer.add_page(front_page)

        # Render back page
        back_page = _render_grid_page(
            source_pages, sheet["back"], grid_rows, grid_cols,
            paper_w, paper_h, cell_w, cell_h, margin
        )
        writer.add_page(back_page)

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    return {
        "output_path": output_pdf_path,
        "total_sheets": len(sheets),
        "output_pages": len(sheets) * 2,
    }


def _render_grid_page(source_pages, grid, grid_rows, grid_cols,
                      paper_w, paper_h, cell_w, cell_h, margin):
    """
    Render a single grid page (front or back).
    Places source pages into the grid cells, scaled to fit.
    """
    # Create a blank page of the target paper size
    new_page = PageObject.create_blank_page(width=paper_w, height=paper_h)

    for row_i in range(grid_rows):
        for col_i in range(grid_cols):
            page_idx = grid[row_i][col_i]

            if page_idx is None:
                continue  # blank slot

            source_page = source_pages[page_idx]

            # Get source page dimensions
            src_box = source_page.mediabox
            src_w = float(src_box.width)
            src_h = float(src_box.height)

            # Calculate scale to fit cell while maintaining aspect ratio
            scale_x = cell_w / src_w
            scale_y = cell_h / src_h
            scale = min(scale_x, scale_y)

            # Calculate position (top-left origin → PDF uses bottom-left)
            # PDF coordinate system: (0,0) is bottom-left
            scaled_w = src_w * scale
            scaled_h = src_h * scale

            # Center within cell
            offset_x = (cell_w - scaled_w) / 2
            offset_y = (cell_h - scaled_h) / 2

            # Cell position
            cell_x = margin + col_i * cell_w
            # Rows go top-to-bottom, but PDF y goes bottom-to-top
            cell_y = paper_h - margin - (row_i + 1) * cell_h

            tx = cell_x + offset_x
            ty = cell_y + offset_y

            # Copy the source page so we don't mutate the original
            page_copy = copy.copy(source_page)
            # Apply scale + translate transformation
            # .scale(s).translate(tx, ty) → x' = s*x + tx, y' = s*y + ty
            page_copy.add_transformation(
                Transformation().scale(scale, scale).translate(tx, ty)
            )
            # Merge onto the output page
            new_page.merge_page(page_copy)

    return new_page
