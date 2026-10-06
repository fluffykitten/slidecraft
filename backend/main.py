import os
import json
import base64
import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from backend.config import UPLOAD_DIR, OUTPUT_DIR, MAX_FILE_SIZE_MB, GEMINI_API_KEY
from backend.models.schemas import ConversionOptions, PDFPreviewResponse, TaskStatusResponse
from backend.services.pdf_extractor import PDFExtractor
from backend.services.converter import ConversionManager
from backend.services.ai_analyzer import AIAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF to PPTX Converter API",
    description="High-fidelity PDF to editable PowerPoint presentation converter with Gemini 2.5 layout intelligence",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

conversion_mgr = ConversionManager()

# Helper models
class GeminiTestRequest(BaseModel):
    api_key: str

@app.get("/api/health")
async def health_check():
    """
    Health check endpoint for connection tests and deployment monitoring.
    """
    return {"status": "ok", "app": "SlideCraft", "version": "1.0.0"}

@app.get("/api/config")
async def get_config():
    """
    Returns server configuration and capabilities.
    """
    system_key = os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
    has_system_gemini_key = bool(system_key and len(system_key) > 5)
    return {
        "has_gemini_key": has_system_gemini_key,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "default_ratio": "16:9",
        "supported_ratios": ["16:9", "4:3", "auto"],
        "default_model": "gemini-3.5-flash-lite"
    }

@app.get("/api/models")
async def get_available_models():
    """
    Returns the list of supported Gemini AI models for layout reconstruction.
    """
    return {
        "default_model": "gemini-3.5-flash-lite",
        "models": [
            {
                "id": "gemini-3.5-flash-lite",
                "name": "Gemini 3.5 Flash-Lite",
                "badge": "Recommended",
                "description": "Ultra fast visual element decomposition with high quota",
                "recommended": True
            },
            {
                "id": "gemini-3.1-flash-lite",
                "name": "Gemini 3.1 Flash-Lite",
                "badge": "Fast",
                "description": "Lightweight document structure analyzer",
                "recommended": False
            },
            {
                "id": "gemini-3.6-flash",
                "name": "Gemini 3.6 Flash",
                "badge": "High Precision",
                "description": "Deep slide layout hierarchy analysis",
                "recommended": False
            },
            {
                "id": "gemini-3.5-flash",
                "name": "Gemini 3.5 Flash",
                "badge": "Stable",
                "description": "High stability element grouping",
                "recommended": False
            },
            {
                "id": "gemini-3.8-flash",
                "name": "Gemini 3.8 Flash",
                "badge": "Latest",
                "description": "Latest generation multimodal reasoning",
                "recommended": False
            }
        ]
    }

@app.post("/api/test-gemini")
async def test_gemini_key(req: GeminiTestRequest):
    """
    Validates a user-supplied Gemini API key with a quick test prompt.
    """
    key = req.api_key.strip()
    if not key:
        return {"valid": False, "message": "API key cannot be empty"}
    try:
        from google import genai
        client = genai.Client(api_key=key)
        # Test with gemini-3.6-flash or gemini-3.5-flash
        res = client.models.generate_content(
            model="gemini-3.6-flash",
            contents="Ping"
        )
        return {"valid": True, "message": "Gemini API key is valid and working!"}
    except Exception as e:
        # Try fallback
        try:
            from google import genai
            client = genai.Client(api_key=key)
            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents="Ping"
            )
            return {"valid": True, "message": "Gemini API key is valid (verified with gemini-3.5-flash)!"}
        except Exception as e2:
            return {"valid": False, "message": f"Gemini API verification failed: {str(e)}"}

@app.post("/api/preview")
async def preview_pdf(file: UploadFile = File(...)):
    """
    Generates page thumbnails and page count for interactive page selection.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    temp_preview_path = UPLOAD_DIR / f"preview_{file.filename}"
    try:
        content = await file.read()
        with open(temp_preview_path, "wb") as f_out:
            f_out.write(content)

        previews = PDFExtractor.get_document_previews(str(temp_preview_path), max_pages=60)
        return {
            "filename": file.filename,
            "total_pages": len(previews),
            "pages": [p.model_dump() for p in previews]
        }
    except Exception as e:
        logger.exception("Error generating preview")
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")
    finally:
        if temp_preview_path.exists():
            try:
                os.remove(temp_preview_path)
            except Exception:
                pass

@app.post("/api/detect-slide-regions")
async def detect_slide_regions(
    file: UploadFile = File(...),
    page_num: int = Form(1),
    detect_ai: bool = Form(True),
    ai_model: str = Form("gemini-3.5-flash-lite"),
    conversion_mode: str = Form("visual"),
    gemini_api_key: Optional[str] = Form(None)
):
    """
    Renders a single slide at high resolution, executes AI element detection if requested,
    and returns the slide image base64 and detected/suggested bounding boxes.
    Used by the Interactive Slide Inspector.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    temp_pdf = UPLOAD_DIR / f"inspect_{file.filename}"
    temp_img = UPLOAD_DIR / f"inspect_page_{page_num}.png"
    try:
        content = await file.read()
        with open(temp_pdf, "wb") as f_out:
            f_out.write(content)

        import pymupdf
        with pymupdf.open(temp_pdf) as doc:
            if page_num < 1 or page_num > len(doc):
                raise HTTPException(status_code=400, detail=f"Page number {page_num} out of range (1-{len(doc)})")
            page = doc[page_num - 1]
            pix = page.get_pixmap(dpi=150)
            pix.save(str(temp_img))
            width_pt = float(page.rect.width)
            height_pt = float(page.rect.height)

        with open(temp_img, "rb") as f_img:
            img_b64 = "data:image/png;base64," + base64.b64encode(f_img.read()).decode("utf-8")

        elements = []
        bg_color = "#ffffff"
        used_model = "manual"

        if detect_ai:
            system_key = os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
            analyzer = AIAnalyzer(api_key=gemini_api_key or system_key, model_name=ai_model)
            try:
                detection = analyzer.detect_slide_elements(str(temp_img), width_pt, height_pt, conversion_mode=conversion_mode)
                elements = detection.get("elements", [])
                bg_color = detection.get("background_color", "#ffffff")
                used_model = detection.get("model", ai_model)
            except Exception as det_err:
                logger.warning(f"Detection failed: {det_err}")

        return {
            "page_num": page_num,
            "width": width_pt,
            "height": height_pt,
            "image_base64": img_b64,
            "background_color": bg_color,
            "elements": elements,
            "model": used_model
        }
    except Exception as e:
        logger.exception("Error in detect_slide_regions")
        raise HTTPException(status_code=500, detail=f"Failed to detect slide regions: {str(e)}")
    finally:
        if temp_pdf.exists():
            try: os.remove(temp_pdf)
            except Exception: pass
        if temp_img.exists():
            try: os.remove(temp_img)
            except Exception: pass

@app.post("/api/convert")
async def start_conversion(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    page_range: Optional[str] = Form(None),
    slide_ratio: str = Form("16:9"),
    ai_enabled: bool = Form(True),
    ai_model: str = Form("gemini-3.5-flash-lite"),
    gemini_api_key: Optional[str] = Form(None),
    conversion_mode: str = Form("visual"),
    heading_font: str = Form("auto"),
    body_font: str = Form("auto"),
    custom_regions: Optional[str] = Form(None)
):
    """
    Accepts one or more PDF files, initiates background conversion, and returns task IDs.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    created_tasks = []
    system_key = os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
    custom_regions_dict = None
    if custom_regions:
        try:
            custom_regions_dict = json.loads(custom_regions)
        except Exception as e:
            logger.warning(f"Failed to parse custom_regions: {e}")

    options = ConversionOptions(
        page_range=page_range,
        slide_ratio=slide_ratio,
        ai_enabled=ai_enabled,
        ai_model=ai_model,
        gemini_api_key=gemini_api_key or system_key,
        conversion_mode=conversion_mode,
        heading_font=heading_font,
        body_font=body_font,
        custom_regions=custom_regions_dict
    )

    for upload_file in files:
        if not upload_file.filename.lower().endswith(".pdf"):
            continue

        task = conversion_mgr.create_task(upload_file.filename)
        saved_pdf_path = UPLOAD_DIR / f"{task.task_id}_{upload_file.filename}"

        content = await upload_file.read()
        with open(saved_pdf_path, "wb") as f_out:
            f_out.write(content)

        # Launch conversion task
        background_tasks.add_task(
            conversion_mgr.run_conversion,
            task,
            saved_pdf_path,
            options
        )

        created_tasks.append(task.to_response())

    if not created_tasks:
        raise HTTPException(status_code=400, detail="No valid PDF files provided.")

    return {"tasks": created_tasks}

@app.get("/api/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Fetches latest status for a conversion task.
    """
    task = conversion_mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_response()

@app.get("/api/tasks/{task_id}/stream")
async def stream_task_progress(task_id: str):
    """
    Server-Sent Events (SSE) endpoint providing real-time progress updates.
    """
    task = conversion_mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    queue = asyncio.Queue()
    task.subscribers.append(queue)

    async def event_generator():
        # First send immediate current state
        yield {
            "event": "progress",
            "data": task.to_response().model_dump_json()
        }

        try:
            while True:
                data = await queue.get()
                yield {
                    "event": "progress",
                    "data": data
                }
                # If completed or failed, close the stream after slight delay
                if task.status in ["completed", "failed"]:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if queue in task.subscribers:
                task.subscribers.remove(queue)

    return EventSourceResponse(event_generator())

@app.get("/api/tasks/{task_id}/download")
async def download_pptx(task_id: str):
    """
    Downloads the converted PPTX file.
    """
    task = conversion_mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "completed" or not task.output_file or not task.output_file.exists():
        raise HTTPException(status_code=400, detail="Presentation is not ready or failed to generate")

    original_stem = Path(task.filename).stem
    download_filename = f"{original_stem}.pptx"

    return FileResponse(
        path=str(task.output_file),
        filename=download_filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

# Static files for frontend
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
