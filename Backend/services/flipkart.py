# ============================================
# Flipkart PDF Label Processing Module
# This module processes Flipkart PDF labels
# and adds barcodes and information to them
# ============================================

import io
import re
from typing import List, Optional

import pymupdf  # PyMuPDF - PDF manipulation
import barcode
from barcode.writer import ImageWriter
from PIL import Image

# Regex patterns - used to find specific text in the PDF
BOX_ID_PATTERN = re.compile(r"fk_mp_\d+_\d+")  # Pattern for finding the Box ID
CONSIGNMENT_ID_PATTERN = re.compile(r"fk_mp_\d+(?!_\d)")  # Consignment ID pattern
COUNT_PATTERN = re.compile(r"\[\s*\d+\s+of\s+\d+\s*\]")  # Item count pattern, such as [1 of 5]

# Colors - defined in RGB format
NAVY = (0.08, 0.10, 0.35)  # Navy - for text and borders
GREY = (0.55, 0.55, 0.55)   # Gray - for divider lines

MIN_CONSIGNMENT_WIDTH = 90.0  # Minimum width for the Consignment ID


# ============================================
# Barcode generation functions
# Functions used to generate barcodes
# ============================================

def generate_barcode_bytes(
    data: str,
    module_height: float = 15.0,
    font_size: int = 9,
    write_text: bool = True,
    module_width: float = 0.34,
) -> bytes:
    # Generate a barcode.
    # Input: data to encode in the barcode
    # Output: barcode image as bytes
    
    code128 = barcode.get_barcode_class("code128")  # Code128 barcode format
    writer = ImageWriter()  # Write in image format
    
    # Barcode options - dimensions and styling
    options = {
        "module_width": module_width,      # Barcode width
        "module_height": module_height,    # Barcode height
        "quiet_zone": 1.5,                 # White space around the barcode
        "font_size": font_size,            # Text font size
        "text_distance": 3.0,              # Distance from text to barcode
        "write_text": write_text,          # Whether to display text
        "dpi": 300,                        # Print quality (300 DPI)
    }
    
    # Write the barcode to a BytesIO buffer
    buffer = io.BytesIO()
    code128(data, writer=writer).write(buffer, options=options)
    buffer.seek(0)  # Seek to the start of the buffer
    return buffer.getvalue()  # Return the barcode bytes


def _sized_barcode_bytes(
    data: str,
    target_rect: "pymupdf.Rect",  # Rectangle defining the target barcode size
    *,
    module_height: float,
    min_module_width: float = 0.5,
    max_module_width: float = 1.8,
    write_text: bool = False,
    font_size: int = 0,
) -> bytes:
    # Fit the barcode into the target rectangle.
    # Resize it so it fits well within the box.
    # First generate a standard barcode as a baseline.
    baseline_width = 0.34
    baseline = generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=baseline_width,
    )
    
    # Return the baseline when the target rectangle is invalid
    if target_rect.width <= 0 or target_rect.height <= 0:
        return baseline

    # Check the baseline barcode dimensions
    with Image.open(io.BytesIO(baseline)) as img:
        baseline_aspect = img.width / img.height  # Aspect ratio (width/height)

    if baseline_aspect <= 0:
        return baseline

    # Calculate the target rectangle aspect ratio
    target_aspect = target_rect.width / target_rect.height
    # Adjust the module width to match the target
    module_width = baseline_width * (target_aspect / baseline_aspect)
    # Keep the width within the minimum and maximum bounds
    module_width = max(min_module_width, min(max_module_width, module_width))

    # Return the baseline when the width does not change
    if abs(module_width - baseline_width) < 1e-3:
        return baseline

    # Generate a newly sized barcode
    return generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=module_width,
    )


def _find_card_bounds_for_anchor(page: "pymupdf.Page", anchor: "pymupdf.Rect") -> Optional["pymupdf.Rect"]:
    # Find the rectangular card boundary around an anchor.
    # The 'Handle with care' text is treated as the anchor.
    
    probe_top = anchor.y0 - 30      # Look 30 units above the anchor
    probe_bottom = anchor.y0 + 350  # Look 350 units below the anchor
    try:
        # Get all drawings (rectangles) from the page
        drawings = page.get_drawings()
    except Exception:
        return None  # Return None when an error occurs

    # Collect valid card boundaries
    candidates = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        
        r = pymupdf.Rect(rect)
        
        # Size check - reject rectangles that are too small or too large
        if r.width < 100 or r.width > page.rect.width * 0.98:
            continue
        if r.height < 100:
            continue
        
        # Position check - keep only rectangles near the anchor
        if r.y0 > probe_bottom or r.y1 < probe_top:
            continue
        
        candidates.append(r)

    if not candidates:
        return None

    # Choose the rectangle with the largest area as the card boundary
    return max(candidates, key=lambda r: r.width * r.height)


def _find_card_x_bounds(page: "pymupdf.Page", anchors: List["pymupdf.Rect"]) -> "tuple[float, float]":
    # Find the left and right card boundaries.
    # Return: (left_x, right_x) tuple
    
    default = (0.0, page.rect.width)  # Default: full page width
    if not anchors:
        return default

    # Find the card boundary from the first anchor
    card_rect = _find_card_bounds_for_anchor(page, anchors[0])
    if card_rect:
        return card_rect.x0, card_rect.x1  # Return the card's left and right edges

    return default


def _find_label_bands(page: "pymupdf.Page") -> List["pymupdf.Rect"]:
    # Find the rectangles for all labels on the page.
    # Each label starts with 'Handle with care'.
    
    # Find the positions of 'Handle with care' text
    anchors = page.search_for("Handle with care")
    anchors.sort(key=lambda r: r.y0)  # Sort from top to bottom
    
    if not anchors:
        return [page.rect]  # Return the full page when no label is found

    # Find the card boundaries (left and right x coordinates)
    left, right = _find_card_x_bounds(page, anchors)

    # Track page height and band heights
    page_h = page.rect.height
    heights: List[float] = []  # Store the height of each band
    bands: List[pymupdf.Rect] = []  # List of final bands
    
    for i, anchor in enumerate(anchors):
        # Find the card boundary around the anchor
        card_rect = _find_card_bounds_for_anchor(page, anchor)
        
        if card_rect is not None:
            bands.append(card_rect)  # Use the card boundary when found
        else:
            # Estimate manually when no card is found
            top = max(0, anchor.y0 - 25)  # 25 units above the anchor
            
            if i + 1 < len(anchors):
                # Extend the band to the next anchor when one exists
                bottom = anchors[i + 1].y0 - 25
                heights.append(bottom - top)  # Store the height
            else:
                # Last label - use the typical height
                typical = sum(heights) / len(heights) if heights else 320.0
                bottom = min(page_h, top + typical)
            
            bands.append(pymupdf.Rect(left, top, right, bottom))
    
    return bands  # Return all bands


def _extract_box_id(page: "pymupdf.Page", band: "pymupdf.Rect") -> Optional[str]:
    # Extract the Box ID from the band (fk_mp_XXXX_XXXX format)
    
    text = page.get_text("text", clip=band)  # Get text inside the band
    match = BOX_ID_PATTERN.search(text)      # Find the Box ID with the regex
    return match.group(0) if match else None  # Return the match or None


def _extract_box_name(page: "pymupdf.Page", band: "pymupdf.Rect", anchor: "pymupdf.Rect") -> str:
    # Extract the Box Name - the text following 'Box Name'
    
    words = page.get_text("words", clip=band)  # Get all words inside the band
    parts: List[str] = []
    
    for x0, y0, _x1, _y1, text, *_rest in words:
        # Position check - keep only words near the anchor
        if y0 < anchor.y0 - 2 or y0 > anchor.y1 + 14:
            continue
        
        # Keep text to the right of the anchor (Box Name follows the anchor)
        if x0 <= anchor.x1 + 2:
            continue
        
        # Skip the Box ID and count; only keep the Box Name
        if BOX_ID_PATTERN.fullmatch(text) or COUNT_PATTERN.fullmatch(text):
            continue
        
        parts.append(text)
    
    return " ".join(parts)  # Join all parts with spaces and return them


def _find_count_text(page: "pymupdf.Page", band: "pymupdf.Rect") -> str:
    # Find count text in the band (such as '[1 of 5]')
    
    text = page.get_text("text", clip=band)  # Get the band text
    match = COUNT_PATTERN.search(text)       # Find the count pattern with the regex
    return match.group(0) if match else ""   # Return the match or an empty string


def _pad(rect: "pymupdf.Rect", amount: float) -> "pymupdf.Rect":
    # Shrink the rectangle by adding padding on all sides.
    # This creates inner space for the content.
    return pymupdf.Rect(rect.x0 + amount, rect.y0 + amount, rect.x1 - amount, rect.y1 - amount)


def _process_label_band(
    page: "pymupdf.Page",
    band: "pymupdf.Rect",        # Label band to process
    box_id_override: Optional[str],  # Manual Box ID override
    consignment_id: str,         # Consignment ID to write
) -> None:
    # Process a label band.
    # Add barcodes and information for the Box ID and Consignment ID.
    
    # Search for the required labels
    cid_hits = page.search_for("Consignment ID", clip=band)  # Find the Consignment ID label
    box_id_hits = page.search_for("Box ID", clip=band)       # Find the Box ID label
    box_name_hits = page.search_for("Box Name", clip=band)   # Find the Box Name label
    from_hits = page.search_for("From:", clip=band)          # Find the From: label
    
    # Skip this band when any label is missing
    if not cid_hits or not box_id_hits or not box_name_hits or not from_hits:
        return

    # Store the label positions (rectangles)
    cid_caption = cid_hits[0]
    box_id_caption = box_id_hits[0]
    box_name_caption = box_name_hits[0]
    from_caption = from_hits[0]

    # Get the Box ID - use the override when provided, otherwise extract it
    current_box_id = box_id_override or _extract_box_id(page, band)
    if not current_box_id:
        return  # Skip the band when no Box ID is found
    
    # Extract the remaining information
    box_name_text = _extract_box_name(page, band, box_name_caption)
    count_text = _find_count_text(page, band)

    # Determine the Box boundaries
    box_top = min(cid_caption.y0, box_id_caption.y0) - 8
    box_bottom = from_caption.y0 - 6
    
    # Reject the box when its height is too small
    if box_bottom - box_top < 20:
        return
    
    # Create the Box rectangle
    box_rect = pymupdf.Rect(band.x0 + 8, box_top, band.x1 - 8, box_bottom)

    # Find the address dimensions so the Consignment area is placed correctly
    from_block = pymupdf.Rect(band.x0, from_caption.y0 - 2, band.x1, band.y1)
    addr_words = page.get_text("words", clip=from_block)
    addr_right_edge = max((w[2] for w in addr_words), default=band.x0 + 220)

    # Determine the left boundary of the Consignment area
    if band.x1 - (addr_right_edge + 16) < MIN_CONSIGNMENT_WIDTH:
        # Allocate 32% of the width when space is limited
        consignment_left = band.x1 - (band.width * 0.32)
    else:
        # Leave space after the address
        consignment_left = addr_right_edge + 16

    # Position of the divider line
    divider_x = consignment_left - 6
    cons_top = box_bottom + 6
    # Keep 3pt inside the border so it is not clipped
    cons_bottom = band.y1 - 3
    consignment_rect = pymupdf.Rect(consignment_left, cons_top, band.x1 - 3, cons_bottom)

    # Cover the old content with white redaction areas
    page.add_redact_annot(box_rect, fill=(1, 1, 1))
    page.add_redact_annot(consignment_rect, fill=(1, 1, 1))
    page.apply_redactions()  # Apply the redactions

    # ============================================
    # Create the Box ID box
    # ============================================
    page.draw_rect(box_rect, color=NAVY, width=1.2)  # Draw the navy rectangle

    inner = _pad(box_rect, 6)  # Create inner space with padding
    
    # Write the 'Box ID' label
    label_fontsize = 9.5
    page.insert_text((inner.x0, inner.y0 + label_fontsize), "Box ID", fontsize=label_fontsize, fontname="hebo", color=NAVY)
    
    # Write the Box ID text, adjusting the font size for long IDs
    box_id_fontsize = 9.5 if len(current_box_id) <= 24 else 8.5
    label_w = pymupdf.get_text_length("Box ID", fontname="hebo", fontsize=label_fontsize)
    page.insert_text(
        (inner.x0 + label_w + 8, inner.y0 + label_fontsize),
        current_box_id,
        fontsize=box_id_fontsize,
        fontname="helv",
    )
    # Write the count on the right when present
    if count_text:
        count_w = pymupdf.get_text_length(count_text, fontname="helv", fontsize=9.0)
        page.insert_text(
            (inner.x1 - count_w, inner.y0 + label_fontsize),  # Right aligned
            count_text,
            fontsize=9.0,
            fontname="helv",
        )

    # Write the 'Box Name' label at the bottom
    box_name_fontsize = 9.0
    bn_label_w = pymupdf.get_text_length("Box Name", fontname="hebo", fontsize=box_name_fontsize)
    page.insert_text((inner.x0, inner.y1 - 2), "Box Name", fontsize=box_name_fontsize, fontname="hebo", color=NAVY)
    
    # Write the Box Name text
    if box_name_text:
        page.insert_text(
            (inner.x0 + bn_label_w + 8, inner.y1 - 2),
            box_name_text,
            fontsize=box_name_fontsize,
            fontname="helv",
        )

    # Generate and insert the Box ID barcode
    barcode_top = inner.y0 + label_fontsize + 6
    barcode_bottom = inner.y1 - box_name_fontsize - 6
    
    # Center the barcode when space is limited
    if barcode_bottom - barcode_top < 8:
        mid = (inner.y0 + inner.y1) / 2
        barcode_top, barcode_bottom = mid - 4, mid + 4
    
    barcode_rect = pymupdf.Rect(inner.x0, barcode_top, inner.x1, barcode_bottom)
    box_barcode_bytes = _sized_barcode_bytes(
        current_box_id,
        barcode_rect,
        module_height=26.0,
    )
    page.insert_image(barcode_rect, stream=box_barcode_bytes, keep_proportion=True)  # Insert the image

    # ============================================
    # Draw divider lines
    # ============================================
    # Horizontal line between the Box and Consignment sections
    page.draw_line(
        (band.x0 + 8, box_bottom + 4), (band.x1 - 8, box_bottom + 4), color=GREY, width=0.8
    )
    # Vertical divider between the Box and Consignment sections
    page.draw_line(
        (divider_x, box_bottom + 8), (divider_x, band.y1 - 3), color=GREY, width=0.8
    )

    # ============================================
    # Consignment ID Section
    # ============================================
    cons_fontsize = 9.0
    
    # Write the 'Consignment ID' label
    page.insert_text(
        (consignment_rect.x0, consignment_rect.y0 + cons_fontsize + 2),
        "Consignment ID",
        fontsize=cons_fontsize,
        fontname="hebo",
        color=NAVY,
    )
    
    # Write the Consignment ID number
    cons_label_w = pymupdf.get_text_length("Consignment ID", fontname="hebo", fontsize=cons_fontsize)
    page.insert_text(
        (consignment_rect.x0 + cons_label_w + 6, consignment_rect.y0 + cons_fontsize + 2),
        consignment_id,
        fontsize=cons_fontsize,
        fontname="helv",
    )

    # Generate and insert the Consignment ID barcode.
    # Use the maximum width and height.
    cb_top = consignment_rect.y0 + cons_fontsize + 10
    cb_bottom = consignment_rect.y1 - 20
    consignment_barcode_rect = pymupdf.Rect(
        consignment_rect.x0, cb_top, band.x1 - 5, cb_bottom
    )

    consignment_barcode_bytes = _sized_barcode_bytes(
        consignment_id,
        consignment_barcode_rect,
        module_height=28.0,
        min_module_width=0.25,
        max_module_width=0.9,
        write_text=False,  # Write only the barcode, not the text
    )
    page.insert_image(
        consignment_barcode_rect, stream=consignment_barcode_bytes, keep_proportion=True
    )


def _detect_consignment_id(doc: "pymupdf.Document") -> Optional[str]:
    # Find the Consignment ID in the PDF document.
    # It uses the fk_mp_XXXX format.
    
    for page in doc:
        match = CONSIGNMENT_ID_PATTERN.search(page.get_text())
        if match:
            return match.group(0)  # Return the first match
    
    return None  # Return None when no match is found


def process_flipkart_pdf(
    contents: bytes,                           # PDF file bytes
    box_id: Optional[str] = None,             # Optional: manually provided Box ID
    consignment_id: Optional[str] = None,     # Optional: manually provided Consignment ID
    from_address: Optional[str] = None,       # Optional: address information (currently unused)
) -> io.BytesIO:
    # ============================================
    # Main function - process a Flipkart PDF.
    # Input: PDF bytes
    # Output: Modified PDF bytes in io.BytesIO format
    # ============================================
    
    # Open the PDF
    doc = pymupdf.open(stream=contents, filetype="pdf")

    # Detect the Consignment ID automatically when it was not provided
    if not consignment_id:
        consignment_id = _detect_consignment_id(doc)
    
    # Raise an error when the Consignment ID is still missing
    if not consignment_id:
        doc.close()
        raise ValueError(
            "Could not detect a Consignment ID in this PDF. Pass "
            "consignment_id explicitly if this file doesn't contain one "
            "in the expected fk_mp_<digits> format."
        )

    # Process every page
    for page in doc:
        # Find label bands on the page
        bands = _find_label_bands(page)
        
        for band in bands:
            # Use the Box ID when there is only one band and one was provided
            band_box_id = box_id if (box_id and len(bands) == 1) else None
            
            # Process the label band and add the barcode and information
            _process_label_band(
                page,
                band,
                band_box_id,
                consignment_id,
            )

    # Save the modified PDF
    out_buffer = io.BytesIO()
    doc.save(out_buffer, garbage=4, deflate=True)  # Compress it as well
    doc.close()
    out_buffer.seek(0)
    return out_buffer  # Return the modified PDF