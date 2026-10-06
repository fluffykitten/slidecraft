from typing import List, Tuple, Optional, Dict, Any
from pydantic import BaseModel, Field

class TextBlockSpan(BaseModel):
    text: str
    font: str = "Arial"
    size: float = 12.0
    color_rgb: Tuple[int, int, int] = (0, 0, 0)
    color_hex: str = "#000000"
    bold: bool = False
    italic: bool = False
    bbox: Tuple[float, float, float, float]

class TextBlockLine(BaseModel):
    spans: List[TextBlockSpan] = []
    bbox: Tuple[float, float, float, float]
    text: str = ""
    alignment: str = "left"  # left, center, right, justify
    role: str = "body"  # title, subtitle, heading, body, bullet, badge, caption, footer
    is_bullet: bool = False

class TextBlock(BaseModel):
    id: int
    lines: List[TextBlockLine] = []
    bbox: Tuple[float, float, float, float]
    text: str = ""
    role: str = "body"  # title, subtitle, heading, body, bullet, caption, footer
    merged: bool = False
    background_color: Optional[Tuple[int, int, int]] = None
    border_color: Optional[Tuple[int, int, int]] = None
    is_rounded: bool = False

class ExtractedImage(BaseModel):
    id: int
    bbox: Tuple[float, float, float, float]
    width: int
    height: int
    format: str = "png"
    temp_path: Optional[str] = None
    name: Optional[str] = None
    element_type: Optional[str] = "image"


class ExtractedShape(BaseModel):
    type: str = "rect"  # rect, rounded_rect, line
    bbox: Tuple[float, float, float, float]
    fill_color: Optional[Tuple[int, int, int]] = None
    stroke_color: Optional[Tuple[int, int, int]] = None
    stroke_width_pt: float = 1.5
    is_rounded: bool = False
    name: Optional[str] = None

class ExtractedTable(BaseModel):
    id: int
    bbox: Tuple[float, float, float, float]
    rows: List[List[str]] = []
    header_row: bool = True
    header_bg_rgb: Optional[Tuple[int, int, int]] = None
    header_text_rgb: Optional[Tuple[int, int, int]] = None
    col_alignments: Optional[List[str]] = None
    alternate_bg_rgb: Optional[Tuple[int, int, int]] = None
    border_rgb: Optional[Tuple[int, int, int]] = (148, 163, 184)
    border_width_pt: float = 1.0

class ExtractedPage(BaseModel):
    page_num: int  # 1-indexed
    width: float
    height: float
    text_blocks: List[TextBlock] = []
    images: List[ExtractedImage] = []
    shapes: List[ExtractedShape] = []
    tables: List[ExtractedTable] = []
    background_color: Optional[Tuple[int, int, int]] = None
    thumbnail_base64: Optional[str] = None
    is_scanned_or_rasterized: bool = False
    full_render_path: Optional[str] = None
    fallback_background_image: Optional[ExtractedImage] = None
    vision_decomposed: bool = False

class PagePreviewItem(BaseModel):
    page_num: int
    width: float
    height: float
    thumbnail_base64: str

class PDFPreviewResponse(BaseModel):
    filename: str
    total_pages: int
    pages: List[PagePreviewItem]

class ConversionOptions(BaseModel):
    page_range: Optional[str] = None
    slide_ratio: str = "16:9"  # "16:9", "4:3", "auto"
    ai_enabled: bool = True
    ai_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: Optional[str] = None
    conversion_mode: str = "visual"  # "visual" (pictures only) or "editable" (text OCR on text-primary elements)
    heading_font: str = "auto"  # "auto", "Century Gothic", "Segoe UI", "Calibri", "Arial", "Georgia", etc.
    body_font: str = "auto"     # "auto", "Century Gothic", "Segoe UI", "Calibri", "Arial", "Georgia", etc.
    custom_regions: Optional[Dict[str, Any]] = None  # page_num (str) -> list of custom elements {box_2d, type, name}

class TaskStatusResponse(BaseModel):
    task_id: str
    filename: str
    status: str  # queued, extracting, analyzing, building, completed, failed
    progress: float  # 0.0 - 100.0
    current_page: int = 0
    total_pages: int = 0
    message: str = ""
    download_url: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
