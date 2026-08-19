# ============================================
# Flipkart PDF Crop Module
# Ye module flipkart.py ke rearrange kiye hue PDF ko leta hai
# aur har label ko apne alag page par crop karta hai, chaaron
# taraf white space padding ke saath.
#
# flipkart.py ko is file mein edit nahi kiya gaya - hum bas uske
# already-tested card-detection helpers (_find_label_bands) reuse
# kar rahe hain, taaki crop bilkul wahi boundary use kare jo
# flipkart.py khud "card" maanta hai.
# ============================================

import io

import pymupdf  # PyMuPDF - PDF manipulation ke liye

from services.flipkart import _find_label_bands

DEFAULT_PADDING = 14.0  # points (~5mm) white space har side par


def crop_flipkart_pdf(
    contents: bytes,
    padding: float = DEFAULT_PADDING,
) -> io.BytesIO:
    """
    Har 2-up Flipkart sheet ko individual label pages mein split karta hai.

    Args:
        contents: rearranged PDF ke bytes (flipkart.process_flipkart_pdf ka output).
        padding: har label page ke chaaron taraf kitna white space chahiye (points mein).

    Returns:
        BytesIO stream jisme final PDF hai - ek label per page, padding ke saath.
    """
    doc = pymupdf.open(stream=contents, filetype="pdf")
    cropped = pymupdf.open()

    for page in doc:
        # flipkart.py wahi function use karta hai apne redraw ke liye - hum
        # bhi wahi bands lete hain taaki crop aur redraw hamesha match karein.
        bands = _find_label_bands(page)

        for band in bands:
            if band.width <= 1 or band.height <= 1:
                continue

            new_width = band.width + (padding * 2)
            new_height = band.height + (padding * 2)

            new_page = cropped.new_page(width=new_width, height=new_height)

            # Label ko naye page ke beech mein rakho, chaaron taraf padding
            # ke saath (naya page by default plain white hota hai).
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