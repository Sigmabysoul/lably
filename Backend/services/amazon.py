import io
import re
from typing import Optional, Tuple
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def extract_sku_and_qty_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts SKU (prioritizing bracketed text right before HSN) and Quantity from invoice page text."""
    if not text:
        return None, None

    found_sku = None
    found_qty = None

    # 1. Primary rule: Extract bracketed text directly before HSN (e.g. "( 6_EBCC-NAF-AAPRO-NC023 ) HSN:")
    bracket_hsn_match = re.search(
        r'\(\s*([A-Za-z0-9_\-\.\/]+?)\s*\)\s*(?:\n|\s)*HSN',
        text,
        re.IGNORECASE
    )
    if bracket_hsn_match:
        found_sku = bracket_hsn_match.group(1).strip()

    # 2. Fallback: Any bracketed text containing hyphens or underscores
    if not found_sku:
        bracket_matches = re.findall(
            r'\(\s*([A-Za-z0-9]*[_\-][A-Za-z0-9_\-\.]+)\s*\)',
            text
        )
        for candidate in bracket_matches:
            candidate_clean = candidate.strip()
            if not candidate_clean.lower().startswith("page") and len(candidate_clean) > 3:
                found_sku = candidate_clean
                break

    # 3. Fallback: Text directly before HSN without brackets
    if not found_sku:
        hsn_match = re.search(
            r'([A-Za-z0-9_\-\.]{3,50})\s*(?:\n|\s)*HSN',
            text,
            re.IGNORECASE
        )
        if hsn_match:
            found_sku = hsn_match.group(1).strip()

    # 4. Fallback: Amazon ASIN format (B0...)
    if not found_sku:
        asin_match = re.search(
            r'\b(B0[A-Z0-9]{8})\b',
            text
        )
        if asin_match:
            found_sku = asin_match.group(1).strip()

    # Extract Quantity (check explicit "Qty" keyword or invoice table format: "₹369.49 1 ₹369.49")
    qty_match = re.search(
        r'(?:Qty|Quantity)\s*[:\-]?\s*(\d+)',
        text,
        re.IGNORECASE
    )
    if qty_match:
        found_qty = qty_match.group(1).strip()
    else:
        table_qty_match = re.search(
            r'(?:₹[\d\.,]+\s+)(\d{1,3})(?:\s+₹[\d\.,]+)',
            text
        )
        if table_qty_match:
            found_qty = table_qty_match.group(1).strip()

    return found_sku, found_qty


def process_amazon_pdf(
    contents: bytes,
    filename: str,
    sku_code: Optional[str] = None,
    pair_index: Optional[int] = None,
) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(contents))
    writer = PdfWriter()

    total_pages = len(reader.pages)

    if pair_index is not None and (pair_index < 0 or pair_index * 2 >= total_pages):
        raise ValueError("The requested label pair does not exist in this PDF.")

    pair_starts = [pair_index * 2] if pair_index is not None else range(0, total_pages, 2)
    for i in pair_starts:
        shipping_page = reader.pages[i]

        # Extract text exclusively from the 2nd page of the current pair (the invoice label)
        invoice_text = ""
        if i + 1 < total_pages:
            invoice_page = reader.pages[i + 1]
            invoice_text = invoice_page.extract_text() or ""

        # Fallback to shipping page text if invoice text is empty
        if not invoice_text.strip():
            invoice_text = shipping_page.extract_text() or ""

        # Parse unique SKU and Quantity for THIS specific invoice page
        parsed_sku, parsed_qty = extract_sku_and_qty_from_text(invoice_text)

        final_sku = sku_code or parsed_sku or "UNKNOWN-SKU"
        final_qty = parsed_qty if parsed_qty else "1"

        # Create overlay canvas for the 1st page of the current pair (the shipping label)
        w = float(shipping_page.mediabox.width)
        h = float(shipping_page.mediabox.height)

        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=(w, h))
        y_pos = 160
        display_text = f"SKU: {final_sku}  |  QTY: {final_qty}"

        font_size = 25
        if len(display_text) > 35:
            font_size = 20
        if len(display_text) > 50:
            font_size = 15

        can.saveState()
        can.setFillColorRGB(0, 0, 0)
        can.setFont("Helvetica-Bold", font_size)

        text_width = can.stringWidth(display_text, "Helvetica-Bold", font_size)
        x_pos = (w - text_width) / 2

        can.drawString(x_pos, y_pos, display_text)
        can.restoreState()
        can.save()

        packet.seek(0)
        overlay = PdfReader(packet)

        # Attach the page to the writer before replacing its contents. This is
        # the supported pypdf mutation order and avoids shared-reader side effects.
        output_shipping_page = writer.add_page(shipping_page)
        output_shipping_page.merge_page(overlay.pages[0])

        # Write the original invoice page after its modified shipping page.
        if i + 1 < total_pages:
            writer.add_page(reader.pages[i + 1])

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out
