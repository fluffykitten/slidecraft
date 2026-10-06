import os
import shutil
import asyncio
import logging
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import pymupdf

from backend.config import UPLOAD_DIR, OUTPUT_DIR, MAX_PAGES
from backend.models.schemas import (
    ConversionOptions,
    ExtractedPage,
    TaskStatusResponse
)
from backend.services.pdf_extractor import PDFExtractor
from backend.services.ai_analyzer import AIAnalyzer
from backend.services.pptx_builder import PPTXBuilder

logger = logging.getLogger(__name__)

class TaskState:
    def __init__(self, task_id: str, filename: str):
        self.task_id = task_id
        self.filename = filename
        self.status = "queued"
        self.progress = 0.0
        self.current_page = 0
        self.total_pages = 0
        self.message = "Task initialized"
        self.download_url: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at = datetime.datetime.now().isoformat()
        self.output_file: Optional[Path] = None
        self.temp_dir: Optional[Path] = None
        self.subscribers: List[asyncio.Queue] = []

    def to_response(self) -> TaskStatusResponse:
        return TaskStatusResponse(
            task_id=self.task_id,
            filename=self.filename,
            status=self.status,
            progress=round(self.progress, 1),
            current_page=self.current_page,
            total_pages=self.total_pages,
            message=self.message,
            download_url=self.download_url,
            error=self.error,
            created_at=self.created_at
        )

    async def update(
        self,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        current_page: Optional[int] = None,
        total_pages: Optional[int] = None,
        message: Optional[str] = None,
        download_url: Optional[str] = None,
        error: Optional[str] = None
    ):
        if status is not None:
            self.status = status
        if progress is not None:
            self.progress = progress
        if current_page is not None:
            self.current_page = current_page
        if total_pages is not None:
            self.total_pages = total_pages
        if message is not None:
            self.message = message
        if download_url is not None:
            self.download_url = download_url
        if error is not None:
            self.error = error

        # Broadcast update to all SSE subscribers
        data = self.to_response().model_dump_json()
        for q in list(self.subscribers):
            try:
                await q.put(data)
            except Exception:
                pass


class ConversionManager:
    """
    Coordinates PDF conversion tasks, tracking status, and managing outputs.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConversionManager, cls).__new__(cls)
            cls._instance.tasks: Dict[str, TaskState] = {}
        return cls._instance

    def create_task(self, filename: str) -> TaskState:
        task_id = str(uuid.uuid4())
        task = TaskState(task_id, filename)
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self.tasks.get(task_id)

    @staticmethod
    def parse_page_range(range_str: Optional[str], total_pages: int) -> List[int]:
        """
        Parses page range strings like '1-3, 5, 7-9' into sorted list of 1-based page numbers.
        """
        if not range_str or not range_str.strip():
            return list(range(1, total_pages + 1))

        pages: Set[int] = set()
        parts = [p.strip() for p in range_str.split(",") if p.strip()]

        for part in parts:
            if "-" in part:
                subparts = part.split("-")
                if len(subparts) == 2:
                    try:
                        start = int(subparts[0].strip())
                        end = int(subparts[1].strip())
                        for p in range(min(start, end), max(start, end) + 1):
                            if 1 <= p <= total_pages:
                                pages.add(p)
                    except ValueError:
                        continue
            else:
                try:
                    p = int(part)
                    if 1 <= p <= total_pages:
                        pages.add(p)
                except ValueError:
                    continue

        result = sorted(list(pages))
        return result if result else list(range(1, total_pages + 1))

    async def run_conversion(
        self,
        task: TaskState,
        pdf_path: Path,
        options: ConversionOptions
    ):
        """
        Executes the 4-stage conversion pipeline in the background.
        """
        temp_dir = UPLOAD_DIR / f"temp_{task.task_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        task.temp_dir = temp_dir

        try:
            await task.update(
                status="extracting",
                progress=5.0,
                message="Opening PDF document..."
            )

            # 1. Open document and determine pages
            doc = pymupdf.open(str(pdf_path))
            total_doc_pages = len(doc)
            target_pages = self.parse_page_range(options.page_range, total_doc_pages)
            pages_to_process = target_pages[:MAX_PAGES]
            num_pages = len(pages_to_process)

            await task.update(
                total_pages=num_pages,
                progress=10.0,
                message=f"Extracting {num_pages} pages from PDF..."
            )

            # Initialize AI Analyzer
            analyzer = AIAnalyzer(api_key=options.gemini_api_key, model_name=options.ai_model)

            extracted_pages: List[ExtractedPage] = []

            # 2. Extract & Analyze each page
            for idx, p_num in enumerate(pages_to_process):
                current_p_idx = idx + 1
                base_pct = 10.0 + (idx / num_pages) * 70.0

                # Extract
                await task.update(
                    status="extracting",
                    current_page=current_p_idx,
                    progress=base_pct,
                    message=f"Rendering high-res slide for page {p_num} ({current_p_idx}/{num_pages})..."
                )
                page_data = PDFExtractor.extract_page(doc, p_num, temp_dir)

                # Analyze & Decompose visual elements
                analyze_pct = base_pct + (0.5 / num_pages) * 70.0
                mode_label = "Editable" if options.conversion_mode == "editable" else "Visual"
                ai_mode_label = "Gemini Vision AI" if (options.ai_enabled and analyzer.client) else "Smart Visual"
                msg = f"{ai_mode_label} segmenting slide elements ({mode_label}) for page {p_num}..."

                await task.update(
                    status="analyzing",
                    current_page=current_p_idx,
                    progress=analyze_pct,
                    message=msg
                )
                custom_page_regions = None
                if options.custom_regions:
                    custom_page_regions = options.custom_regions.get(p_num) or options.custom_regions.get(str(p_num))

                analyzed_page = await asyncio.to_thread(
                    analyzer.analyze_page,
                    page_data,
                    ai_enabled=options.ai_enabled,
                    conversion_mode=options.conversion_mode,
                    custom_regions=custom_page_regions
                )
                extracted_pages.append(analyzed_page)

            doc.close()

            # 3. Build PPTX
            await task.update(
                status="building",
                progress=85.0,
                message="Building editable PowerPoint presentation..."
            )

            base_name = Path(task.filename).stem
            output_filename = f"{base_name}_{task.task_id[:8]}.pptx"
            output_path = OUTPUT_DIR / output_filename

            builder = PPTXBuilder(
                preferred_ratio=options.slide_ratio,
                heading_font=options.heading_font,
                body_font=options.body_font
            )
            builder.build_presentation(extracted_pages, output_path)

            task.output_file = output_path
            download_url = f"/api/tasks/{task.task_id}/download"

            # 4. Completed!
            await task.update(
                status="completed",
                progress=100.0,
                message="Conversion complete! Your editable PPTX is ready.",
                download_url=download_url
            )

        except Exception as e:
            logger.exception(f"Error during conversion task {task.task_id}: {e}")
            await task.update(
                status="failed",
                progress=100.0,
                message=f"Conversion error: {str(e)}",
                error=str(e)
            )
        finally:
            # Cleanup temp files (images embedded into PPTX are already saved inside the pptx zip)
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
