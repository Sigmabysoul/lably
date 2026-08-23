# ============================================
# Flipkart PDF Crop Module
# This module takes the rearranged PDF from flipkart.py
# and crops each label onto its own page with white-space padding
# on all sides.
#
# flipkart.py is not edited here - we only reuse its already-tested
# card-detection helper (_find_label_bands), so the crop uses exactly
# the same boundary that flipkart.py considers a "card".
# ============================================

import io

import pymupdf  # PyMuPDF - PDF manipulation

from Backend.services.flipkart import _find_label_bands

DEFAULT_PADDING = 14.0  # points (~5mm) of white space on each side


def crop_flipkart_pdf(
    contents: bytes,
    padding: float = DEFAULT_PADDING,
) -> io.BytesIO:
    """
    Split each 2-up Flipkart sheet into individual label pages.

    Args:
        contents: Bytes from the rearranged PDF (the output of flipkart.process_flipkart_pdf).
        padding: Amount of white space around each label page, in points.

    Returns:
        A BytesIO stream containing the final PDF, with one padded label per page.
    """
    if not 0 <= padding <= 144:
        raise ValueError("Padding must be between 0 and 144 points.")

    doc = pymupdf.open(stream=contents, filetype="pdf")
    cropped = pymupdf.open()

    for page in doc:
        # `_find_label_bands` intentionally falls back to the full page when it
        # cannot find an anchor. That fallback is useful during rearranging,
        # but would turn a trailing blank sheet into an output page here.
        if not page.search_for("Handle with care"):
            continue

        # flipkart.py uses the same function for redrawing; use the same
        # bands here so the crop and redraw always match.
        bands = _find_label_bands(page)

        for band in bands:
            if band.width <= 1 or band.height <= 1:
                continue

            new_width = band.width + (padding * 2)
            new_height = band.height + (padding * 2)

            new_page = cropped.new_page(width=new_width, height=new_height)

            # Place the label in the center of the new page with padding
            # on all sides (new pages are plain white by default).
            target_rect = pymupdf.Rect(
                padding,
                padding,
                padding + band.width,
                padding + band.height,
            )
            new_page.show_pdf_page(target_rect, doc, page.number, clip=band)

    doc.close()

    if cropped.page_count == 0:
        cropped.close()
        raise ValueError(
            "Could not find any labels to crop in this PDF (looked for "
            "'Handle with care' on each page)."
        )

    out_buffer = io.BytesIO()
    cropped.save(out_buffer, garbage=4, deflate=True)
    cropped.close()
    out_buffer.seek(0)
    return out_buffer
