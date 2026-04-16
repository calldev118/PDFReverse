"""
Core imposition algorithm.
Takes a list of pages, grid dimensions, and produces
front/back sheet arrangements with horizontal row reversal on back sides.
"""

import math


def calculate_sheets(total_pages, grid_rows, grid_cols):
    """Calculate how many physical sheets are needed."""
    slots_per_side = grid_rows * grid_cols
    pages_per_sheet = slots_per_side * 2  # front + back
    return math.ceil(total_pages / pages_per_sheet)


def build_sheet_layout(pages, grid_rows, grid_cols):
    """
    Given a flat list of pages (or page numbers), arrange them into sheets.
    Each sheet has a front grid and a back grid (with row-reversed back).

    Returns a list of dicts:
    [
        {
            "front": [[p1, p3, p5], [p7, p9, p11], [p13, p15, p17]],
            "back":  [[p6, p4, p2], [p12, p10, p8], [p18, p16, p14]]
        },
        ...
    ]
    """
    slots_per_side = grid_rows * grid_cols
    pages_per_sheet = slots_per_side * 2

    total_pages = len(pages)
    total_sheets = calculate_sheets(total_pages, grid_rows, grid_cols)

    sheets = []

    for sheet_idx in range(total_sheets):
        start = sheet_idx * pages_per_sheet

        # Collect front (odd-position: 0, 2, 4...) and back (even-position: 1, 3, 5...)
        front_pages = []
        back_pages = []

        for i in range(pages_per_sheet):
            page_index = start + i
            page = pages[page_index] if page_index < total_pages else None  # None = blank

            if i % 2 == 0:
                front_pages.append(page)
            else:
                back_pages.append(page)

        # Pad to fill grid if needed
        while len(front_pages) < slots_per_side:
            front_pages.append(None)
        while len(back_pages) < slots_per_side:
            back_pages.append(None)

        # Arrange into grid rows
        front_grid = _chunk(front_pages, grid_cols)
        back_grid = _chunk(back_pages, grid_cols)

        # Reverse each row in back grid (horizontal flip for duplex)
        back_grid_reversed = [row[::-1] for row in back_grid]

        sheets.append({
            "front": front_grid,
            "back": back_grid_reversed,
        })

    return sheets


def _chunk(lst, size):
    """Split a list into chunks of given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def simulate(total_pages, grid_rows, grid_cols):
    """
    Run a simulation with page numbers 1..total_pages.
    Prints the front and back grids for each sheet.
    """
    pages = list(range(1, total_pages + 1))
    sheets = build_sheet_layout(pages, grid_rows, grid_cols)

    print(f"=== PDF Imposition Simulation ===")
    print(f"Total pages: {total_pages}")
    print(f"Grid: {grid_rows}×{grid_cols} ({grid_rows * grid_cols} slots per side)")
    print(f"Pages per sheet: {grid_rows * grid_cols * 2}")
    print(f"Sheets needed: {len(sheets)}")
    print()

    for idx, sheet in enumerate(sheets):
        print(f"--- Sheet {idx + 1} ---")
        print(f"  FRONT:")
        for row in sheet["front"]:
            display = [str(p) if p is not None else "___" for p in row]
            print(f"    {' | '.join(f'{d:>4}' for d in display)}")

        print(f"  BACK (after horizontal reverse):")
        for row in sheet["back"]:
            display = [str(p) if p is not None else "___" for p in row]
            print(f"    {' | '.join(f'{d:>4}' for d in display)}")
        print()

    # Verify alignment (after physical horizontal flip, front[r][c] aligns with back[r][cols-1-c])
    print("=== Duplex Alignment Check (after physical flip) ===")
    all_ok = True
    for idx, sheet in enumerate(sheets):
        print(f"Sheet {idx + 1}:")
        for row_i in range(grid_rows):
            for col_i in range(grid_cols):
                front_p = sheet["front"][row_i][col_i]
                # After physical flip, column mirrors: col_i -> cols-1-col_i
                flip_col = grid_cols - 1 - col_i
                back_p = sheet["back"][row_i][flip_col]
                f_str = str(front_p) if front_p else "blank"
                b_str = str(back_p) if back_p else "blank"
                status = ""
                if front_p is not None and back_p is not None:
                    if back_p == front_p + 1:
                        status = "✓"
                    else:
                        status = "✗ MISMATCH"
                        all_ok = False
                elif front_p is None and back_p is None:
                    status = "✓ (both blank)"
                else:
                    status = "~ (partial)"
                print(f"  [{row_i},{col_i}] front={f_str:>5} ↔ physical_back={b_str:>5}  {status}")

    if all_ok:
        print("\n✅ All page pairs aligned correctly!")
    else:
        print("\n❌ Some pages misaligned!")
    print()

    return sheets


if __name__ == "__main__":
    # Test with 20 pages, 3x3 grid
    print("=" * 50)
    print("TEST 1: 20 pages, 3x3 grid")
    print("=" * 50)
    simulate(20, 3, 3)

    print("\n" + "=" * 50)
    print("TEST 2: 8 pages, 2x2 grid")
    print("=" * 50)
    simulate(8, 2, 2)

    print("\n" + "=" * 50)
    print("TEST 3: 5 pages, 2x2 grid (incomplete sheet)")
    print("=" * 50)
    simulate(5, 2, 2)

    print("\n" + "=" * 50)
    print("TEST 4: 36 pages, 3x3 grid (exact 2 sheets)")
    print("=" * 50)
    simulate(36, 3, 3)
