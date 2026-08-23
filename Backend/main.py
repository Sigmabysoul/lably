# LabelCode API - FastAPI server for Flipkart label processing
import io
import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from services.amazon import process_amazon_pdf
from services.flipkart import process_flipkart_pdf
from services.crop import crop_flipkart_pdf

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app = FastAPI(title="LabelCode API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


async def read_pdf(file: UploadFile) -> bytes:
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the upload limit.")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")
    return contents


def attachment_header(prefix: str, filename: str) -> str:
    safe_name = Path(filename).name.replace('"', "")
    return f"attachment; filename*=UTF-8''{quote(f'{prefix}-{safe_name}')}"


@app.post("/api/process-amazon")
async def process_amazon(
    file: UploadFile = File(...),
    sku_code: Optional[str] = Form(None),
    pair_index: Optional[int] = Form(None),
):
    """Process an Amazon shipping label PDF and return the modified PDF."""
    try:
        filename = file.filename or "upload.pdf"
        contents = await read_pdf(file)
        output = await run_in_threadpool(
            process_amazon_pdf,
            contents,
            filename,
            sku_code or None,
            pair_index,
        )
        if isinstance(output, (bytes, bytearray)):
            output = io.BytesIO(output)
        else:
            output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": attachment_header("amazon", filename)
            },
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to process this PDF.") from error


@app.post("/api/process-flipkart")
async def process_flipkart(
    file: UploadFile = File(...),
    box_id: Optional[str] = Form(None),
    consignment_id: Optional[str] = Form(None),
    from_address: Optional[str] = Form(None),   # ← NEW: sender address
    crop_padding: Optional[float] = Form(None),  # white space (pt) around each cropped label
    label_overrides: Optional[str] = Form(None),
):
    """
    Process a Flipkart shipping label PDF.

    - Auto-detects Box ID and Consignment ID from the PDF.
    - Inserts the From address into the blank section of each label.
    - Once flipkart.py is done rearranging the sheet, hands the result to
      crop.py, which splits the 2-per-page layout into individual label
      pages with white padding on every side.
    - Returns the final, cropped PDF as a download.
    """
    try:
        filename = file.filename or "upload.pdf"
        contents = await read_pdf(file)
        try:
            overrides = json.loads(label_overrides) if label_overrides else None
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="Invalid label overrides.") from error
        if overrides is not None and not isinstance(overrides, dict):
            raise HTTPException(status_code=400, detail="Invalid label overrides.")
        if overrides and not all(
            isinstance(key, str)
            and isinstance(value, dict)
            and all(
                field in {"box_id", "consignment_id"}
                and isinstance(field_value, str)
                and len(field_value) <= 200
                for field, field_value in value.items()
            )
            for key, value in overrides.items()
        ):
            raise HTTPException(status_code=400, detail="Invalid label overrides.")
        rearranged = await run_in_threadpool(
            process_flipkart_pdf,
            contents,
            box_id or None,
            consignment_id or None,
            from_address or None,
            overrides,
        )

        if isinstance(rearranged, (bytes, bytearray)):
            rearranged_bytes = bytes(rearranged)
        else:
            rearranged.seek(0)
            rearranged_bytes = rearranged.read()

        # flipkart.py's rearranging pass is done - now crop.py splits the
        # sheet into one page per label, with white padding all around.
        output = await run_in_threadpool(
            crop_flipkart_pdf,
            rearranged_bytes,
            crop_padding if crop_padding is not None else 14.0,
        )

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": attachment_header("flipkart", filename)
            },
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to process this PDF.") from error
