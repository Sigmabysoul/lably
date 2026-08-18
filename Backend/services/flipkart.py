# Flipkart PDF label processing ke liye zaruri libraries import kar rahe hain
import io
import re
from typing import List, Optional

import fitz  # PDF ko edit karne ke liye PyMuPDF library
import barcode  # Barcode images generate karne ke liye
from barcode.writer import ImageWriter  # Barcode ko image format me likhnay ke liye
from PIL import Image  # Image processing aur manipulation ke liye

# Flipkart labels me used patterns ke liye regex define kar rahe hain
BOX_ID_PATTERN = re.compile(r"fk_mp_\d+_\d+")  # Box ID pattern: fk_mp_123_456
CONSIGNMENT_ID_PATTERN = re.compile(r"fk_mp_\d+(?!_\d)")  # Consignment ID pattern: fk_mp_123
COUNT_PATTERN = re.compile(r"\[\s*\d+\s+of\s+\d+\s*\]")  # Box count pattern: [1 of 5]

# Label par text ke liye colors define kar rahe hain (RGB tuple)
NAVY = (0.08, 0.10, 0.35)  # Navy blue color label heading ke liye
GREY = (0.55, 0.55, 0.55)  # Grey color dividing lines ke liye

# Address bahut lamba ho tab bhi Consignment ID ke liye minimum jagah rakho (points me)
MIN_CONSIGNMENT_WIDTH = 90.0


def generate_barcode_bytes(
    data: str,
    module_height: float = 22.0,
    font_size: int = 9,
    write_text: bool = True,
    module_width: float = 0.34,
) -> bytes:
    """Diye gaye data ke liye Code128 barcode image bytes generate karta hai.
    
    Module height se barcode ka height decide hota hai,
    aur module width se barcode ki thickness decide hoti hai.
    """
    # Code128 barcode image banate hain
    code128 = barcode.get_barcode_class("code128")
    writer = ImageWriter()
    options = {
        "module_width": module_width,
        "module_height": module_height,
        "quiet_zone": 1.5,
        "font_size": font_size,
        "text_distance": 3.0,
        "write_text": write_text,
        "dpi": 300,
    }
    buffer = io.BytesIO()
    code128(data, writer=writer).write(buffer, options=options)
    buffer.seek(0)
    return buffer.getvalue()


def _sized_barcode_bytes(
    data: str,
    target_rect: "fitz.Rect",
    *,
    module_height: float,
    min_module_width: float = 0.50,
    max_module_width: float = 1.8,
    write_text: bool = False,
    font_size: int = 0,
) -> bytes:
    """Target area ke ratio ke hisaab se barcode ki width adjust karta hai."""
    baseline_width = 0.34
    baseline = generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=baseline_width,
    )

    # Agar area invalid hai to normal barcode hi use karo.
    if target_rect.width <= 0 or target_rect.height <= 0:
        return baseline

    with Image.open(io.BytesIO(baseline)) as img:
        baseline_aspect = img.width / img.height

    if baseline_aspect <= 0:
        return baseline

    # Target ke width/height aur barcode ke ratio se best module width nikaalo.
    target_aspect = target_rect.width / target_rect.height
    module_width = baseline_width * (target_aspect / baseline_aspect)
    module_width = max(min_module_width, min(max_module_width, module_width))

    if abs(module_width - baseline_width) < 1e-3:
        return baseline

    return generate_barcode_bytes(
        data,
        module_height=module_height,
        write_text=write_text,
        font_size=font_size,
        module_width=module_width,
    )


def _find_card_x_bounds(page: "fitz.Page", anchors: List["fitz.Rect"]) -> "tuple[float, float]":
    """Original Flipkart label ka left aur right border find karta hai."""
    default = (0.0, page.rect.width)
    if not anchors:
        return default

    probe_top = anchors[0].y0
    probe_bottom = anchors[0].y0 + 400

    try:
        drawings = page.get_drawings()
    except Exception:
        return default

    candidates = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        rect = fitz.Rect(rect)

        # Bahut chhoti lines aur almost full-page drawings ko ignore karo.
        if rect.width < 100 or rect.width > page.rect.width * 0.95:
            continue
        if rect.height < 100:
            continue
        if rect.y0 > probe_bottom or rect.y1 < probe_top:
            continue
        candidates.append(rect)

    if not candidates:
        return default

    # Sabse wide matching drawing ko label border maan lo.
    best = max(candidates, key=lambda r: r.width)
    return best.x0, best.x1


def _find_card_bottom(page: "fitz.Page", band: "fitz.Rect") -> float:
    """Is label ka actual bottom border dhoondta hai taaki divider bahar na nikle."""
    try:
        drawings = page.get_drawings()
    except Exception:
        return band.y1

    candidates = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        rect = fitz.Rect(rect)

        # Label ka outer rectangle usually band ke andar hota hai aur kaafi wide hota hai.
        if abs(rect.x0 - band.x0) > 1.5 or abs(rect.x1 - band.x1) > 1.5:
            continue
        if rect.height < 100:
            continue
        if rect.y0 < band.y0 - 2 or rect.y0 > band.y1 + 2:
            continue
        candidates.append(rect)

    if not candidates:
        # Safe fallback: band ke bottom se thoda pehle ruk jao.
        return max(band.y0 + 20, band.y1 - 8)

    # Sabse relevant outer card ka bottom use karo.
    return max(r.y1 for r in candidates)


def _find_label_bands(page: "fitz.Page") -> List["fitz.Rect"]:
    anchors = page.search_for("Handle with care")
    anchors.sort(key=lambda r: r.y0)
    if not anchors:
        return [page.rect]

    left, right = _find_card_x_bounds(page, anchors)

    page_h = page.rect.height
    heights: List[float] = []
    bands: List["fitz.Rect"] = []

    for i, anchor in enumerate(anchors):
        top = max(0, anchor.y0 - 25)
        if i + 1 < len(anchors):
            bottom = anchors[i + 1].y0 - 25
            heights.append(bottom - top)
        else:
            # Last label ke liye pehle labels ki average height use karo.
            typical = sum(heights) / len(heights) if heights else 320.0
            bottom = min(page_h, top + typical)
        bands.append(fitz.Rect(left, top, right, bottom))

    return bands


def _extract_box_id(page: "fitz.Page", band: "fitz.Rect") -> Optional[str]:
    """PDF page ke specific band se Box ID extract karta hai."""
    text = page.get_text("text", clip=band)  # Band ke andar se text nikaalte hain
    match = BOX_ID_PATTERN.search(text)  # Box ID pattern se match dhundho
    return match.group(0) if match else None  # Match mila to return karo, nahi to None


def _extract_box_name(page: "fitz.Page", band: "fitz.Rect", anchor: "fitz.Rect") -> str:
    """Box Name text ko anchor ke bagal se extract karta hai."""
    words = page.get_text("words", clip=band)  # Band ke sare words nikaalte hain
    parts: List[str] = []

    for x0, y0, _x1, _y1, text, *_rest in words:
        # Anchor ke vertical range me hi text dhundho
        if y0 < anchor.y0 - 2 or y0 > anchor.y1 + 14:
            continue
        # Anchor ke right side se text lo, uske baad wale
        if x0 <= anchor.x1 + 2:
            continue
        # Box ID aur count text ko skip karo
        if BOX_ID_PATTERN.fullmatch(text) or COUNT_PATTERN.fullmatch(text):
            continue
        parts.append(text)

    return " ".join(parts)  # Sab parts ko space se join karke return karo


def _find_count_text(page: "fitz.Page", band: "fitz.Rect") -> str:
    """Box count text dhundo ([1 of 5] jaisa)."""
    text = page.get_text("text", clip=band)  # Band se complete text nikalo
    match = COUNT_PATTERN.search(text)  # Count pattern se match dhundo
    return match.group(0) if match else ""  # Match mila to return karo, nahi to empty string


def _pad(rect: "fitz.Rect", amount: float) -> "fitz.Rect":
    """Rectangle ke sab sides se equal amount by cutting karta hai (padding/margin)."""
    return fitz.Rect(rect.x0 + amount, rect.y0 + amount, rect.x1 - amount, rect.y1 - amount)


def _process_label_band(
    page: "fitz.Page",
    band: "fitz.Rect",
    box_id_override: Optional[str],
    consignment_id: str,
    consignment_barcode_bytes: bytes,
) -> None:
    cid_hits = page.search_for("Consignment ID", clip=band)
    box_id_hits = page.search_for("Box ID", clip=band)
    box_name_hits = page.search_for("Box Name", clip=band)
    from_hits = page.search_for("From:", clip=band)

    if not cid_hits or not box_id_hits or not box_name_hits or not from_hits:
        # Layout match na ho to label ko skip karo, taaki galat jagah erase na ho.
        return

    cid_caption = cid_hits[0]
    box_id_caption = box_id_hits[0]
    box_name_caption = box_name_hits[0]
    from_caption = from_hits[0]

    current_box_id = box_id_override or _extract_box_id(page, band)
    if not current_box_id:
        return

    box_name_text = _extract_box_name(page, band, box_name_caption)
    count_text = _find_count_text(page, band)

    # Box ID wale section ki jagah nikaal rahe hain.
    # Yahan sirf redaction hoga; koi naya outer box draw nahi karna hai.
    box_top = min(cid_caption.y0, box_id_caption.y0) - 8
    box_bottom = from_caption.y0 - 8
    if box_bottom - box_top < 20:
        return

    box_rect = fitz.Rect(band.x0 + 8, box_top, band.x1 - 8, box_bottom)

    # Label ka asli bottom dhoondo. Isse vertical line label ke bahar nahi jayegi.
    card_bottom = _find_card_bottom(page, band)

    # Address section full width lega
    # From: section se neeche tak address ke liye jagah nikaalo.
    addr_top = from_caption.y0 - 2
    addr_bottom = card_bottom - 4
    
    # Consignment section ko address ke neeche rakhenge (nahi right side me)
    # Pehle half address ko, doosra half Consignment ke liye
    mid_point = (addr_top + addr_bottom) / 2
    
    # Consignment section neeche rakhenge
    cons_top = mid_point + 5
    cons_bottom = card_bottom - 4
    if cons_bottom - cons_top < 28:
        cons_bottom = cons_top + 28

    consignment_rect = fitz.Rect(
        band.x0 + 8,
        cons_top,
        band.x1 - 8,
        cons_bottom,
    )

    # Purane Box ID aur Address aur Consignment wale generated parts ko white karke clean area banao.
    page.add_redact_annot(box_rect, fill=(1, 1, 1))
    # Address section ko puraa clean karo (full width)
    addr_and_cons_rect = fitz.Rect(band.x0 + 8, from_caption.y0 - 2, band.x1 - 8, card_bottom - 4)
    page.add_redact_annot(addr_and_cons_rect, fill=(1, 1, 1))
    page.add_redact_annot(consignment_rect, fill=(1, 1, 1))
    page.apply_redactions()

    # Box ID text ko original style me wapas draw karo, lekin outer border bilkul mat draw karo.
    inner = _pad(box_rect, 6)
    label_fontsize = 11
    page.insert_text(
        (inner.x0, inner.y0 + label_fontsize),
        "Box ID",
        fontsize=label_fontsize,
        fontname="hebo",
        color=NAVY,
    )

    # Box ID ki length ke hisaab se font size adjust karo taaki text fit ho jaye
    box_id_fontsize = 11 if len(current_box_id) <= 24 else 9
    label_w = fitz.get_text_length("Box ID", fontname="hebo", fontsize=label_fontsize)  # Label width calculate karo
    page.insert_text(
        (inner.x0 + label_w + 10, inner.y0 + label_fontsize),
        current_box_id,
        fontsize=box_id_fontsize,
        fontname="helv",
    )

    if count_text:
        count_w = fitz.get_text_length(count_text, fontname="helv", fontsize=10)
        page.insert_text(
            (inner.x1 - count_w, inner.y0 + label_fontsize),
            count_text,
            fontsize=10,
            fontname="helv",
        )

    box_name_fontsize = 10
    bn_label_w = fitz.get_text_length("Box Name", fontname="hebo", fontsize=box_name_fontsize)
    page.insert_text(
        (inner.x0, inner.y1 - 3),
        "Box Name",
        fontsize=box_name_fontsize,
        fontname="hebo",
        color=NAVY,
    )

    if box_name_text:
        page.insert_text(
            (inner.x0 + bn_label_w + 10, inner.y1 - 3),
            box_name_text,
            fontsize=box_name_fontsize,
            fontname="helv",
        )

    # Box ID barcode ka size aur placement ko untouched rakha gaya hai.
    barcode_top = inner.y0 + label_fontsize + 6
    barcode_bottom = inner.y1 - box_name_fontsize - 6
    if barcode_bottom - barcode_top < 8:
        # Bahut kam jagah ho to safe fallback use karo.
        mid = (inner.y0 + inner.y1) / 2
        barcode_top, barcode_bottom = mid - 4, mid + 4

    barcode_rect = fitz.Rect(inner.x0, barcode_top, inner.x1, barcode_bottom)
    box_barcode_bytes = _sized_barcode_bytes(
        current_box_id,
        barcode_rect,
        module_height=26.0,
    )
    page.insert_image(barcode_rect, stream=box_barcode_bytes, keep_proportion=True)

    # Horizontal divider Box ID section ke baad
    page.draw_line(
        (band.x0 + 8, box_bottom + 5),
        (band.x1 - 8, box_bottom + 5),
        color=GREY,
        width=0.8,
    )

    # Horizontal divider Address section ke baad (neeche)
    page.draw_line(
        (band.x0 + 8, mid_point),
        (band.x1 - 8, mid_point),
        color=GREY,
        width=0.8,
    )

    # Consignment section ko clean rakhne ke liye barcode full width me rakhenge.
    # Barcode ko available full width denge.
    barcode_side_gap = 6.0
    barcode_rect = fitz.Rect(
        consignment_rect.x0 + barcode_side_gap,
        consignment_rect.y0 + 5,
        consignment_rect.x1 - barcode_side_gap,
        consignment_rect.y0 + 28,
    )

    # Barcode ko target width ke hisaab se dobara generate kar rahe hain,
    # taaki image patli na lage aur available jagah properly use ho.
    clean_consignment_barcode = _sized_barcode_bytes(
        consignment_id,
        barcode_rect,
        module_height=14.0,
        min_module_width=0.22,
        max_module_width=1.0,
        write_text=False,
        font_size=0,
    )

    page.insert_image(
        barcode_rect,
        stream=clean_consignment_barcode,
        keep_proportion=True,
    )

    # Consignment ID ko barcode ke neeche rakhenge
    # Font size taaki text fit ho jaye
    cons_fontsize = 9.0
    label_text = "Consignment ID"
    # Available width se check karo fit hota hai ya nahi
    available_text_width = consignment_rect.width - 12
    cons_fontsize = 9.0
    while cons_fontsize > 7.0:
        test_label_width = fitz.get_text_length(
            label_text,
            fontname="hebo",
            fontsize=cons_fontsize,
        )
        test_id_width = fitz.get_text_length(
            consignment_id,
            fontname="helv",
            fontsize=cons_fontsize,
        )
        if test_label_width + 6.0 + test_id_width <= available_text_width:
            break
        cons_fontsize -= 0.25

    text_y = barcode_rect.y1 + cons_fontsize + 4

    # Label ko bold aur ID ko normal rakhne ke liye dono alag draw kar rahe hain.
    label_width = fitz.get_text_length(
        label_text,
        fontname="hebo",
        fontsize=cons_fontsize,
    )
    id_width = fitz.get_text_length(
        consignment_id,
        fontname="helv",
        fontsize=cons_fontsize,
    )
    gap = 6.0
    combined_width = label_width + gap + id_width
    # Left side se start karo (nahi center me)
    text_x = consignment_rect.x0 + 6.0

    page.insert_text(
        (text_x, text_y),
        label_text,
        fontsize=cons_fontsize,
        fontname="hebo",
        color=NAVY,
    )
    page.insert_text(
        (text_x + label_width + gap, text_y),
        consignment_id,
        fontsize=cons_fontsize,
        fontname="helv",
    )


def _detect_consignment_id(doc: "fitz.Document") -> Optional[str]:
    """Poore PDF me se Consignment ID automatically detect karta hai.
    
    Same Consignment ID sab labels par hoti hai,
    to sirf pehla match return karte hain.
    """
    for page in doc:  # Har page ke liye
        match = CONSIGNMENT_ID_PATTERN.search(page.get_text())  # Consignment ID dhundo
        if match:
            return match.group(0)  # Pehla match mil gaya to return karo
    return None  # Pura PDF scan kar liye aur nahi mila


def process_flipkart_pdf(
    contents: bytes,
    box_id: Optional[str] = None,
    consignment_id: Optional[str] = None,
    from_address: Optional[str] = None,
) -> io.BytesIO:
    """Flipkart PDF ko process karta hai: Box ID aur Consignment ID update karta hai.

    The `from_address` argument is accepted for API compatibility with the
    FastAPI route and any frontend payloads that include a sender address.

    Args:
        contents: PDF file ke bytes
        box_id: Manual Box ID (optional - auto-detect hota hai)
        consignment_id: Consignment ID (optional - auto-detect hota hai)
        from_address: Sender address for label generation (optional)

    Returns:
        Modified PDF as BytesIO stream
    """
    # The legacy implementation here doesn't currently render a sender address,
    # but the parameter must be accepted to avoid 500 errors from the API route.
    _ = from_address
    if not contents:
        raise ValueError("PDF contents are empty.")
    try:
        doc = fitz.open(stream=contents, filetype="pdf")  # PDF ko memory me open karo
    except Exception as exc:  # pragma: no cover - defensive validation guard
        raise ValueError("Invalid PDF contents provided.") from exc

    # Agar Consignment ID diya nahi gaya to PDF se dhundo
    if not consignment_id:
        consignment_id = _detect_consignment_id(doc)

    # Agar ab bhi nahi mila to error do
    if not consignment_id:
        doc.close()
        raise ValueError(
            "Could not detect a Consignment ID in this PDF. Pass "
            "consignment_id explicitly if this file doesn't contain one "
            "in the expected fk_mp_<digits> format."
        )

    # Consignment barcode har label par same hota hai
    # Actual size aur width label ke andar target rect ke hisaab se set hogi
    consignment_barcode_bytes = generate_barcode_bytes(
        consignment_id,
        module_height=14.0,
        font_size=0,
        write_text=False,
        module_width=0.34,
    )

    # Har page ko process karo
    for page in doc:
        bands = _find_label_bands(page)  # Page se sab label bands dhundo
        for band in bands:  # Har band ke liye
            # Sirf ek label ho to manually diya gaya Box ID use karo
            band_box_id = box_id if (box_id and len(bands) == 1) else None

            # Label band ko update karo: Box ID aur Consignment ID likhao
            _process_label_band(
                page,
                band,
                band_box_id,
                consignment_id,
                consignment_barcode_bytes,
            )

    # Modified PDF ko output buffer me save karo
    out_buffer = io.BytesIO()
    doc.save(out_buffer, garbage=4, deflate=True)  # File size reduce karne ke liye compress karo
    doc.close()  # PDF document ko close karo
    out_buffer.seek(0)  # Buffer ko start se read karne ke liye position set karo
    return out_buffer  # Modified PDF return karo