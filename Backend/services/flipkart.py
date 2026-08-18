# ============================================
# Flipkart PDF Label Processing Module
# Ye module Flipkart ke PDF labels ko process karta hai
# aur unme barcode aur information add karta hai
# ============================================

import io
import re
from typing import List, Optional

import pymupdf  # PyMuPDF - PDF manipulation ke liye
import barcode
from barcode.writer import ImageWriter
from PIL import Image

# Regex patterns - ye patterns specific text ko PDF mein dhundne ke liye use hote hain
BOX_ID_PATTERN = re.compile(r"fk_mp_\d+_\d+")  # Box ID ko dhundne ke liye pattern
CONSIGNMENT_ID_PATTERN = re.compile(r"fk_mp_\d+(?!_\d)")  # Consignment ID pattern
COUNT_PATTERN = re.compile(r"\[\s*\d+\s+of\s+\d+\s*\]")  # Item count pattern jaise [1 of 5]

# Colors - RGB format mein define kiye gaye
NAVY = (0.08, 0.10, 0.35)  # Neela rang - text aur borders ke liye
GREY = (0.55, 0.55, 0.55)   # Dhusara rang - divider lines ke liye

MIN_CONSIGNMENT_WIDTH = 90.0  # Consignment ID ke liye minimum width


# ============================================
# Barcode generation functions
# Barcode generate karne ke liye ye functions use hote hain
# ============================================

def generate_barcode_bytes(
    data: str,
    module_height: float = 15.0,
    font_size: int = 9,
    write_text: bool = True,
    module_width: float = 0.34,
) -> bytes:
    # Barcode generate karne ke liye ye function hai
    # Input: data (jinhe barcode mein encode karna hai)
    # Output: bytes mein barcode image
    
    code128 = barcode.get_barcode_class("code128")  # Code128 format ka barcode
    writer = ImageWriter()  # Image format mein likne ke liye
    
    # Barcode ke options - dimensions aur styling
    options = {
        "module_width": module_width,      # Barcode ki width
        "module_height": module_height,    # Barcode ki height
        "quiet_zone": 1.5,                 # Barcode ke aas-paas white space
        "font_size": font_size,            # Text ka font size
        "text_distance": 3.0,              # Text se barcode tak distance
        "write_text": write_text,          # Text display karega ya nahi
        "dpi": 300,                        # Print quality (300 DPI)
    }
    
    # BytesIO buffer mein barcode likho
    buffer = io.BytesIO()
    code128(data, writer=writer).write(buffer, options=options)
    buffer.seek(0)  # Buffer ke shuruat par jaao
    return buffer.getvalue()  # Barcode ke bytes return karo


def _sized_barcode_bytes(
    data: str,
    target_rect: "pymupdf.Rect",  # Ye rectangle batata hai ki barcode kitin bada hona chahiye
    *,
    module_height: float,
    min_module_width: float = 0.5,
    max_module_width: float = 1.8,
    write_text: bool = False,
    font_size: int = 0,
) -> bytes:
    # Ye function barcode ko target rectangle mein fit karta hai
    # Barcode ko resize karta hai taaki wo box mein acha se aaye
    # Pehle ek standard barcode banao (baseline)
    baseline_width = 0.34
    baseline = generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=baseline_width,
    )
    
    # Agar target rectangle invalid hai to baseline return karo
    if target_rect.width <= 0 or target_rect.height <= 0:
        return baseline

    # Baseline barcode ki dimensions check karo
    with Image.open(io.BytesIO(baseline)) as img:
        baseline_aspect = img.width / img.height  # Aspect ratio (width/height)

    if baseline_aspect <= 0:
        return baseline

    # Target rectangle ka aspect ratio calculate karo
    target_aspect = target_rect.width / target_rect.height
    # Module width ko target se match karane ke liye adjust karo
    module_width = baseline_width * (target_aspect / baseline_aspect)
    # Width ko min aur max boundaries mein rakho
    module_width = max(min_module_width, min(max_module_width, module_width))

    # Agar width mein koi change nahi hai to baseline return karo
    if abs(module_width - baseline_width) < 1e-3:
        return baseline

    # Naya sized barcode generate karo
    return generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=module_width,
    )


def _find_card_bounds_for_anchor(page: "pymupdf.Page", anchor: "pymupdf.Rect") -> Optional["pymupdf.Rect"]:
    # Ye function anchor ke aas-paas card ka rectangular boundary dhundta hai
    # Jab 'Handle with care' text mil jaaye tab use anchor mante hain
    
    probe_top = anchor.y0 - 30      # Anchor se 30 units upar dekho
    probe_bottom = anchor.y0 + 350  # Anchor se 350 units neeche dekho
    try:
        # Page se sab drawings (rectangles) nikalo
        drawings = page.get_drawings()
    except Exception:
        return None  # Agar error aaye to None return karo

    # Valid card boundaries ko collect karo
    candidates = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        
        r = pymupdf.Rect(rect)
        
        # Size check - bohat chhota ya bohat bada rectangle reject karo
        if r.width < 100 or r.width > page.rect.width * 0.98:
            continue
        if r.height < 100:
            continue
        
        # Position check - anchor ke kareeb wala hi chahiye
        if r.y0 > probe_bottom or r.y1 < probe_top:
            continue
        
        candidates.append(r)

    if not candidates:
        return None

    # Sabse bada area wala rectangle choose karo (wo card boundary hoga)
    return max(candidates, key=lambda r: r.width * r.height)


def _find_card_x_bounds(page: "pymupdf.Page", anchors: List["pymupdf.Rect"]) -> "tuple[float, float]":
    # Card ke left aur right boundaries dhundna
    # Return: (left_x, right_x) tuple
    
    default = (0.0, page.rect.width)  # Default: pura page width
    if not anchors:
        return default

    # Pehle anchor se card boundary dhundho
    card_rect = _find_card_bounds_for_anchor(page, anchors[0])
    if card_rect:
        return card_rect.x0, card_rect.x1  # Card ka left aur right edge return karo

    return default


def _find_label_bands(page: "pymupdf.Page") -> List["pymupdf.Rect"]:
    # Page mein sab labels ke rectangles dhundna
    # Har label 'Handle with care' text se start hota hai
    
    # 'Handle with care' text ke positions dhundho
    anchors = page.search_for("Handle with care")
    anchors.sort(key=lambda r: r.y0)  # Top se neeche ke order mein sort karo
    
    if not anchors:
        return [page.rect]  # Agar koi label nahi mila to pura page return karo

    # Card ke boundaries (left aur right x coordinates) dhundho
    left, right = _find_card_x_bounds(page, anchors)

    # Page height aur band heights track karo
    page_h = page.rect.height
    heights: List[float] = []  # Har band ki height store karenge
    bands: List[pymupdf.Rect] = []  # Final bands ka list
    
    for i, anchor in enumerate(anchors):
        # Anchor ke aas-paas card boundary dhundho
        card_rect = _find_card_bounds_for_anchor(page, anchor)
        
        if card_rect is not None:
            bands.append(card_rect)  # Agar card mila to use karo
        else:
            # Agar card nahi mila to manual estimate karo
            top = max(0, anchor.y0 - 25)  # Anchor se 25 units upar
            
            if i + 1 < len(anchors):
                # Agar agle anchor hai to uske aas tak band extend karo
                bottom = anchors[i + 1].y0 - 25
                heights.append(bottom - top)  # Height store karo
            else:
                # Last label - typical height use karo
                typical = sum(heights) / len(heights) if heights else 320.0
                bottom = min(page_h, top + typical)
            
            bands.append(pymupdf.Rect(left, top, right, bottom))
    
    return bands  # Sab bands return karo


def _extract_box_id(page: "pymupdf.Page", band: "pymupdf.Rect") -> Optional[str]:
    # Band se Box ID extract karo (fk_mp_XXXX_XXXX format)
    
    text = page.get_text("text", clip=band)  # Band ke andar ka text nikalo
    match = BOX_ID_PATTERN.search(text)      # Regex se Box ID dhundho
    return match.group(0) if match else None  # Agar mila to return karo, nahi to None


def _extract_box_name(page: "pymupdf.Page", band: "pymupdf.Rect", anchor: "pymupdf.Rect") -> str:
    # Box Name extract karo - ye 'Box Name' ke baad wala text hota hai
    
    words = page.get_text("words", clip=band)  # Band ke andar sab words nikalo
    parts: List[str] = []
    
    for x0, y0, _x1, _y1, text, *_rest in words:
        # Position check - anchor ke kareeb ke words hi le sakte ho
        if y0 < anchor.y0 - 2 or y0 > anchor.y1 + 14:
            continue
        
        # Anchor ke right side se hi text chahiye (Box Name anchor ke aage hota hai)
        if x0 <= anchor.x1 + 2:
            continue
        
        # Box ID aur Count ko skip karo - sirf Box Name chahiye
        if BOX_ID_PATTERN.fullmatch(text) or COUNT_PATTERN.fullmatch(text):
            continue
        
        parts.append(text)
    
    return " ".join(parts)  # Sab parts ko space se join karke return karo


def _find_count_text(page: "pymupdf.Page", band: "pymupdf.Rect") -> str:
    # Band se count text dhundho (jaise '[1 of 5]')
    
    text = page.get_text("text", clip=band)  # Band ka text nikalo
    match = COUNT_PATTERN.search(text)       # Regex se count pattern dhundho
    return match.group(0) if match else ""   # Agar mila to return karo, nahi to empty string


def _pad(rect: "pymupdf.Rect", amount: float) -> "pymupdf.Rect":
    # Rectangle ko chhota karo (sabhi sides se padding add karo)
    # Ye content ke liye inner space banane ke liye use hota hai
    return pymupdf.Rect(rect.x0 + amount, rect.y0 + amount, rect.x1 - amount, rect.y1 - amount)


def _process_label_band(
    page: "pymupdf.Page",
    band: "pymupdf.Rect",        # Process karne wala label band
    box_id_override: Optional[str],  # Agar manually box_id dena hai
    consignment_id: str,         # Consignment ID likhi hogi
) -> None:
    # Ye function ek label band ko process karta hai
    # Box ID aur Consignment ID ke barcode aur information add karta hai
    
    # Required labels ko search karo
    cid_hits = page.search_for("Consignment ID", clip=band)  # Consignment ID label dhundho
    box_id_hits = page.search_for("Box ID", clip=band)       # Box ID label dhundho
    box_name_hits = page.search_for("Box Name", clip=band)   # Box Name label dhundho
    from_hits = page.search_for("From:", clip=band)          # From: label dhundho
    
    # Agar koi label nahi mila to ye band skip karo
    if not cid_hits or not box_id_hits or not box_name_hits or not from_hits:
        return

    # Labels ke positions (rectangles) store karo
    cid_caption = cid_hits[0]
    box_id_caption = box_id_hits[0]
    box_name_caption = box_name_hits[0]
    from_caption = from_hits[0]

    # Box ID nikalo - override diya hai to wo use karo, nahi to extract karo
    current_box_id = box_id_override or _extract_box_id(page, band)
    if not current_box_id:
        return  # Agar box_id nahi mila to band skip karo
    
    # Aur information extract karo
    box_name_text = _extract_box_name(page, band, box_name_caption)
    count_text = _find_count_text(page, band)

    # Box ke boundaries determine karo
    box_top = min(cid_caption.y0, box_id_caption.y0) - 8
    box_bottom = from_caption.y0 - 6
    
    # Agar box ka height bohat kam hai to valid nahi hai
    if box_bottom - box_top < 20:
        return
    
    # Box ke liye rectangle banao
    box_rect = pymupdf.Rect(band.x0 + 8, box_top, band.x1 - 8, box_bottom)

    # Address ke dimensions dhundho taaki consignment area properly place ho
    from_block = pymupdf.Rect(band.x0, from_caption.y0 - 2, band.x1, band.y1)
    addr_words = page.get_text("words", clip=from_block)
    addr_right_edge = max((w[2] for w in addr_words), default=band.x0 + 220)

    # Consignment area ke left boundary decide karo
    if band.x1 - (addr_right_edge + 16) < MIN_CONSIGNMENT_WIDTH:
        # Agar space kam hai to 32% width allocate karo
        consignment_left = band.x1 - (band.width * 0.32)
    else:
        # Address ke aage space rakho
        consignment_left = addr_right_edge + 16

    # Divider line ki position
    divider_x = consignment_left - 6
    cons_top = box_bottom + 6
    # Border se 3pt andar tak - taaki border cut na ho
    cons_bottom = band.y1 - 3
    consignment_rect = pymupdf.Rect(consignment_left, cons_top, band.x1 - 3, cons_bottom)

    # Purane content ko white color se cover karo (redact karo)
    page.add_redact_annot(box_rect, fill=(1, 1, 1))
    page.add_redact_annot(consignment_rect, fill=(1, 1, 1))
    page.apply_redactions()  # Apply karo

    # ============================================
    # Box ID Box banao
    # ============================================
    page.draw_rect(box_rect, color=NAVY, width=1.2)  # Neela rectangle draw karo

    inner = _pad(box_rect, 6)  # Inner space banao (padding ke saath)
    
    # 'Box ID' label likho
    label_fontsize = 9.5
    page.insert_text((inner.x0, inner.y0 + label_fontsize), "Box ID", fontsize=label_fontsize, fontname="hebo", color=NAVY)
    
    # Box ID text likho (font size adjust karo agar ID lambi ho)
    box_id_fontsize = 9.5 if len(current_box_id) <= 24 else 8.5
    label_w = pymupdf.get_text_length("Box ID", fontname="hebo", fontsize=label_fontsize)
    page.insert_text(
        (inner.x0 + label_w + 8, inner.y0 + label_fontsize),
        current_box_id,
        fontsize=box_id_fontsize,
        fontname="helv",
    )
    # Agar count hai to right side mein likho
    if count_text:
        count_w = pymupdf.get_text_length(count_text, fontname="helv", fontsize=9.0)
        page.insert_text(
            (inner.x1 - count_w, inner.y0 + label_fontsize),  # Right aligned
            count_text,
            fontsize=9.0,
            fontname="helv",
        )

    # 'Box Name' label likho - bottom mein
    box_name_fontsize = 9.0
    bn_label_w = pymupdf.get_text_length("Box Name", fontname="hebo", fontsize=box_name_fontsize)
    page.insert_text((inner.x0, inner.y1 - 2), "Box Name", fontsize=box_name_fontsize, fontname="hebo", color=NAVY)
    
    # Box Name text likho
    if box_name_text:
        page.insert_text(
            (inner.x0 + bn_label_w + 8, inner.y1 - 2),
            box_name_text,
            fontsize=box_name_fontsize,
            fontname="helv",
        )

    # Box ID ka barcode banao aur insert karo
    barcode_top = inner.y0 + label_fontsize + 6
    barcode_bottom = inner.y1 - box_name_fontsize - 6
    
    # Agar space kam hai to center mein barcode rakhho
    if barcode_bottom - barcode_top < 8:
        mid = (inner.y0 + inner.y1) / 2
        barcode_top, barcode_bottom = mid - 4, mid + 4
    
    barcode_rect = pymupdf.Rect(inner.x0, barcode_top, inner.x1, barcode_bottom)
    box_barcode_bytes = _sized_barcode_bytes(
        current_box_id,
        barcode_rect,
        module_height=26.0,
    )
    page.insert_image(barcode_rect, stream=box_barcode_bytes, keep_proportion=True)  # Image insert karo

    # ============================================
    # Divider Lines draw karo
    # ============================================
    # Box aur Consignment section ke beech horizontal line
    page.draw_line(
        (band.x0 + 8, box_bottom + 4), (band.x1 - 8, box_bottom + 4), color=GREY, width=0.8
    )
    # Box aur Consignment ke beech vertical divider line
    page.draw_line(
        (divider_x, box_bottom + 8), (divider_x, band.y1 - 3), color=GREY, width=0.8
    )

    # ============================================
    # Consignment ID Section
    # ============================================
    cons_fontsize = 9.0
    
    # 'Consignment ID' label likho
    page.insert_text(
        (consignment_rect.x0, consignment_rect.y0 + cons_fontsize + 2),
        "Consignment ID",
        fontsize=cons_fontsize,
        fontname="hebo",
        color=NAVY,
    )
    
    # Consignment ID number likho
    cons_label_w = pymupdf.get_text_length("Consignment ID", fontname="hebo", fontsize=cons_fontsize)
    page.insert_text(
        (consignment_rect.x0 + cons_label_w + 6, consignment_rect.y0 + cons_fontsize + 2),
        consignment_id,
        fontsize=cons_fontsize,
        fontname="helv",
    )

    # Consignment ID ka barcode banao aur insert karo
    # Maximum width aur height use karo
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
        write_text=False,  # Text nahi likho, sirf barcode
    )
    page.insert_image(
        consignment_barcode_rect, stream=consignment_barcode_bytes, keep_proportion=True
    )


def _detect_consignment_id(doc: "pymupdf.Document") -> Optional[str]:
    # PDF document mein Consignment ID dhundho
    # Ye fk_mp_XXXX format mein hota hai
    
    for page in doc:
        match = CONSIGNMENT_ID_PATTERN.search(page.get_text())
        if match:
            return match.group(0)  # Pehla match return karo
    
    return None  # Agar nahi mila to None return karo


def process_flipkart_pdf(
    contents: bytes,                           # PDF file ke bytes
    box_id: Optional[str] = None,             # Optional: manually box ID dena
    consignment_id: Optional[str] = None,     # Optional: manually consignment ID dena
    from_address: Optional[str] = None,       # Optional: address info (abhi use nahi ho raha)
) -> io.BytesIO:
    # ============================================
    # Main function - Flipkart PDF ko process karne ke liye
    # Input: PDF bytes
    # Output: Modified PDF ke bytes (io.BytesIO format mein)
    # ============================================
    
    # PDF ko open karo
    doc = pymupdf.open(stream=contents, filetype="pdf")

    # Consignment ID automatically detect karo agar nahi diya hai
    if not consignment_id:
        consignment_id = _detect_consignment_id(doc)
    
    # Agar abhi bhi consignment ID nahi mila to error throw karo
    if not consignment_id:
        doc.close()
        raise ValueError(
            "Could not detect a Consignment ID in this PDF. Pass "
            "consignment_id explicitly if this file doesn't contain one "
            "in the expected fk_mp_<digits> format."
        )

    # Har page ko process karo
    for page in doc:
        # Page mein se label bands dhundho
        bands = _find_label_bands(page)
        
        for band in bands:
            # Agar sirf ek band hai aur box_id diya hai to use karo
            band_box_id = box_id if (box_id and len(bands) == 1) else None
            
            # Label band ko process karo - barcode aur info add karo
            _process_label_band(
                page,
                band,
                band_box_id,
                consignment_id,
            )

    # Modified PDF ko save karo
    out_buffer = io.BytesIO()
    doc.save(out_buffer, garbage=4, deflate=True)  # Compress bhi karo
    doc.close()
    out_buffer.seek(0)
    return out_buffer  # Modified PDF return karo