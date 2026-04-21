"""
PDF Writer module — pikepdf engine (C++ QPDF backend, ~5-10x faster than PyPDF2).
Takes the sheet layouts from imposer and renders them into a new PDF.
Each sheet becomes two pages in the output: front and back.
"""

import pikepdf

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
    """
    src_pdf = pikepdf.Pdf.open(input_pdf_path)
    total_pages = len(src_pdf.pages)

    page_indices = list(range(total_pages))
    sheets = build_sheet_layout(page_indices, grid_rows, grid_cols)

    paper_w, paper_h = PAPER_SIZES.get(paper_size, PAPER_SIZES["A4"])

    cell_w = (paper_w - margin * 2) / grid_cols
    cell_h = (paper_h - margin * 2) / grid_rows

    out_pdf = pikepdf.Pdf.new()

    for sheet in sheets:
        front_page = _render_grid_page(
            src_pdf, out_pdf, sheet["front"], grid_rows, grid_cols,
            paper_w, paper_h, cell_w, cell_h, margin
        )
        out_pdf.pages.append(front_page)

        back_page = _render_grid_page(
            src_pdf, out_pdf, sheet["back"], grid_rows, grid_cols,
            paper_w, paper_h, cell_w, cell_h, margin
        )
        out_pdf.pages.append(back_page)

    out_pdf.save(output_pdf_path)
    src_pdf.close()
    out_pdf.close()

    return {
        "output_path": output_pdf_path,
        "total_sheets": len(sheets),
        "output_pages": len(sheets) * 2,
    }


def _render_grid_page(src_pdf, out_pdf, grid, grid_rows, grid_cols,
                      paper_w, paper_h, cell_w, cell_h, margin):
    """
    Render a single grid page (front or back).
    Uses pikepdf Form XObjects for fast, clean placement.
    Draws a border and page number on each cell.
    """
    xobjects = pikepdf.Dictionary()
    content_parts = []
    xobj_idx = 0

    # Built-in Helvetica font for page numbers (no embedding needed)
    font_dict = pikepdf.Dictionary(
        Type=pikepdf.Name.Font,
        Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
    )

    for row_i in range(grid_rows):
        for col_i in range(grid_cols):
            page_idx = grid[row_i][col_i]
            if page_idx is None:
                continue

            src_page = src_pdf.pages[page_idx]

            mbox = src_page.mediabox
            src_w = float(mbox[2]) - float(mbox[0])
            src_h = float(mbox[3]) - float(mbox[1])

            scale_x = cell_w / src_w
            scale_y = cell_h / src_h
            scale = min(scale_x, scale_y)

            scaled_w = src_w * scale
            scaled_h = src_h * scale

            offset_x = (cell_w - scaled_w) / 2
            offset_y = (cell_h - scaled_h) / 2

            cell_x = margin + col_i * cell_w
            cell_y = paper_h - margin - (row_i + 1) * cell_h

            tx = cell_x + offset_x
            ty = cell_y + offset_y

            # --- Page content ---
            xobj = src_page.as_form_xobject()
            xobj_foreign = out_pdf.copy_foreign(xobj)
            name = f"Pg{xobj_idx}"
            xobjects[pikepdf.Name(f"/{name}")] = xobj_foreign
            xobj_idx += 1

            content_parts.append(
                f"q {scale:.6f} 0 0 {scale:.6f} {tx:.4f} {ty:.4f} cm /{name} Do Q"
            )

            # --- Border around scaled content ---
            content_parts.append(
                f"q 0.5 w 0.55 0.55 0.65 RG "
                f"{tx:.3f} {ty:.3f} {scaled_w:.3f} {scaled_h:.3f} re S Q"
            )

            # --- Page number label ---
            font_size = max(5.0, min(9.0, cell_h * 0.055))
            label = str(page_idx + 1)
            approx_label_w = len(label) * font_size * 0.52
            label_x = tx + scaled_w / 2 - approx_label_w / 2

            # Place below content if there's room in the cell gap, else inside at bottom
            label_y = ty - font_size - 1.5
            if label_y < cell_y + 1:
                label_y = ty + 2.5

            content_parts.append(
                f"BT /F1 {font_size:.2f} Tf 0.2 0.2 0.2 rg "
                f"{label_x:.3f} {label_y:.3f} Td ({label}) Tj ET"
            )

    # Build the page dictionary directly in the output PDF
    content_stream = out_pdf.make_stream("\n".join(content_parts).encode("ascii"))
    page_dict = out_pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=pikepdf.Array([0, 0, paper_w, paper_h]),
        Resources=pikepdf.Dictionary(
            XObject=xobjects,
            Font=pikepdf.Dictionary(F1=font_dict),
        ),
        Contents=content_stream,
    ))

    return pikepdf.Page(page_dict)
