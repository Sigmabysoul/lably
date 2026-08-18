# LabelCode API - FastAPI server for Flipkart label processing
from typing import Optional
import io
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from services.amazon import process_amazon_pdf
from services.flipkart import process_flipkart_pdf

app = FastAPI(title="LabelCode API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/process-amazon")
async def process_amazon(
    file: UploadFile = File(...),
    sku_code: Optional[str] = Form(None),
):
    """Process an Amazon shipping label PDF and return the modified PDF."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    try:
        contents = await file.read()
        output = process_amazon_pdf(
            contents,
            file.filename,
            sku_code=sku_code or None,
        )
        if isinstance(output, (bytes, bytearray)):
            output = io.BytesIO(output)
        else:
            output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="amazon-{file.filename}"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing Error: {str(e)}")


@app.post("/api/process-flipkart")
async def process_flipkart(
    file: UploadFile = File(...),
    box_id: Optional[str] = Form(None),
    consignment_id: Optional[str] = Form(None),
    from_address: Optional[str] = Form(None),   # ← NEW: sender address
):
    """
    Process a Flipkart shipping label PDF.

    - Crops 2-per-page layouts into individual label pages automatically.
    - Auto-detects Box ID and Consignment ID from the PDF.
    - Inserts the From address into the blank section of each label.
    - Returns the processed PDF as a download.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    try:
        contents = await file.read()
        output = process_flipkart_pdf(
            contents,
            box_id=box_id or None,
            consignment_id=consignment_id or None,
            from_address=from_address or None,
        )

        if isinstance(output, (bytes, bytearray)):
            output = io.BytesIO(output)
        else:
            output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="flipkart-{file.filename}"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing Error: {str(e)}")