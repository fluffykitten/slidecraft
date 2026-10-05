import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from PIL import Image
from google import genai
from google.genai import types

from backend.models.schemas import (
    ExtractedPage,
    ExtractedImage,
    TextBlock,
    TextBlockLine,
    TextBlockSpan,
    ExtractedTable,
)

from backend.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Element types considered text-primary (will get OCR in editable mode)
TEXT_PRIMARY_TYPES = {"text", "header", "footer", "badge", "section", "card", "title", "body"}
# Element types that stay as pictures regardless of mode
GRAPHIC_TYPES = {"diagram", "illustration", "chart", "photo", "logo", "icon"}


class AIAnalyzer:
    """
    Intelligent Slide Layout & Visual Decomposition Engine:

    Extracts:
    1. Slide background color
    2. Fine-grained text blocks with exact bounding boxes, semantic roles,
       and badge/pill container backgrounds.
    3. Standalone graphic elements (illustrations, diagrams, photos, icons)
       as high-resolution picture shapes.
    4. Structured tables with rows and columns.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-3.5-flash-lite"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
        self.model_name = model_name or "gemini-3.5-flash-lite"
        self.client = None
        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")
                self.client = None

    def analyze_page(
        self,
        page: ExtractedPage,
        ai_enabled: bool = True,
        conversion_mode: str = "visual",
        custom_regions: Optional[List[Dict[str, Any]]] = None
    ) -> ExtractedPage:
        """
        Decomposes the slide into distinct visual elements, text blocks, and tables.
        If custom_regions is provided by user, processes those regions directly.
        """
        if custom_regions:
            try:
                logger.info(f"[AIAnalyzer] Using {len(custom_regions)} user custom regions for Page {page.page_num}")
                return self._process_elements(page, custom_regions, conversion_mode)
            except Exception as e:
                logger.warning(f"Failed to process custom regions for page {page.page_num}: {e}")

        if ai_enabled and self.client and page.full_render_path:
            try:
                return self._decompose_slide_elements(page, conversion_mode)
            except Exception as e:
                logger.warning(f"Gemini slide element decomposition failed for page {page.page_num}: {e}. Falling back to rule-based.")
                return self._decompose_rule_based(page)
        else:
            return self._decompose_rule_based(page)

    @staticmethod
    def _normalize_box_2d(raw_box: Any) -> Optional[List[int]]:
        """
        Normalizes bounding box coordinates from Gemini into a flat [ymin, xmin, ymax, xmax] list of ints.
        Handles flat lists, nested lists (e.g. [[ymin, xmin, ymax, xmax]]), and floats.
        """
        if not raw_box or not isinstance(raw_box, (list, tuple)):
            return None
        curr = raw_box
        while isinstance(curr, (list, tuple)) and len(curr) == 1 and isinstance(curr[0], (list, tuple)):
            curr = curr[0]
        if isinstance(curr, (list, tuple)) and len(curr) == 4:
            try:
                coords = [int(round(float(v))) for v in curr]
                ymin, xmin, ymax, xmax = coords
                if ymax > ymin and xmax > xmin:
                    return coords
            except (ValueError, TypeError):
                return None
        return None

    # ------------------------------------------------------------------ #
    # Standalone region detection for interactive editor
    # ------------------------------------------------------------------ #
    def detect_slide_elements(
        self,
        image_path: str,
        width: float,
        height: float
    ) -> Dict[str, Any]:
        """
        Analyzes a single slide image and returns fine-grained visual regions
        with normalized 0-1000 bounding boxes and 'text'/'graphic'/'table' classification.
        Used by the frontend Interactive Region Inspector.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Slide image not found: {image_path}")

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        prompt = f"""You are an expert presentation layout reconstruction engine.
Analyze this slide image (original dimensions: {width:.1f}x{height:.1f} points).

Extract:
1. "background_color": Dominant background hex (e.g. "#ffffff" or "#1e293b").
2. "text_elements": List of distinct text blocks/labels. For each:
   - "text": Exact text
   - "role": "title" | "subtitle" | "heading" | "body" | "bullet" | "badge" | "footer"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around this specific text block (include 2-3% padding for ascenders/descenders)
   - "font_size_pt": Estimated font size in points
   - "bold": true/false
   - "color_hex": Text color hex (e.g. "#1e293b" or "#ffffff")
   - "background_hex": Background color hex if this is a badge/pill/card with solid fill (e.g. "#334155" for dark badge), or null if transparent
3. "graphic_elements": List of visual graphics (illustrations, diagrams, photos, icons, charts). For each:
   - "name": Descriptive name
   - "type": "illustration" | "icon" | "diagram" | "chart"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around ONLY the graphic image (excluding separate text)
4. "tables": List of data tables. ONLY extract genuine statistical/tabular data grids consisting purely of alphanumeric cells (such as financial statements, comparison matrices, or numerical schedules).
   CRITICAL NEGATIVE RULE: NEVER classify multi-column slide layouts, card grids, feature lists, or sections containing illustrations/icons as tables! Those MUST be decomposed into separate text_elements and graphic_elements.

Return strictly a valid JSON object.
"""
        data, used_model = self._call_gemini_json(
            [types.Part.from_bytes(data=img_bytes, mime_type="image/png"), prompt],
            label="detect_slide_elements"
        )

        elements = []
        graphic_boxes = []

        # 1. Graphic elements
        for g in data.get("graphic_elements", []):
            box = self._normalize_box_2d(g.get("box_2d"))
            if not box:
                continue
            graphic_boxes.append(box)
            elements.append({
                "name": g.get("name", "Graphic Shape"),
                "type": "graphic",
                "box_2d": box,
                "text_primary": False
            })

        # 2. Tables with validation filter against false-positive layout grids
        valid_table_boxes = []
        for tbl in data.get("tables", []):
            box = self._normalize_box_2d(tbl.get("box_2d"))
            if not box:
                continue
            ymin, xmin, ymax, xmax = box
            box_area_pct = ((ymax - ymin) * (xmax - xmin)) / 10000.0
            # If the candidate table has graphics inside it or covers >60% of slide, reject as layout grid
            has_nested_graphic = any(
                ymin <= (gy0 + gy1) / 2.0 <= ymax and xmin <= (gx0 + gx1) / 2.0 <= xmax
                for gy0, gx0, gy1, gx1 in graphic_boxes
            )
            if has_nested_graphic or box_area_pct > 60.0:
                logger.info(f"[AIAnalyzer] Rejecting table {box} (area={box_area_pct:.1f}%, has_graphic={has_nested_graphic}) - treating as layout grid")
                continue

            valid_table_boxes.append(box)
            elements.append({
                "name": "Data Table",
                "type": "table",
                "box_2d": box,
                "text_primary": True,
                "rows": tbl.get("rows", [])
            })

        # 3. Text elements (exclude if inside a genuine table)
        for t in data.get("text_elements", []):
            box = self._normalize_box_2d(t.get("box_2d"))
            if not box:
                continue
            if self._is_inside_table(box, valid_table_boxes):
                continue
            role = t.get("role", "text")
            is_badge = role == "badge" or bool(t.get("background_hex"))
            name = f"Badge: {t.get('text', '')[:20]}" if is_badge else f"{role.capitalize()}: {t.get('text', '')[:25]}"
            elements.append({
                "name": name,
                "type": "text",
                "box_2d": box,
                "text_primary": True
            })

        return {
            "background_color": data.get("background_color", "#ffffff"),
            "elements": elements,
            "model": used_model
        }

    # ------------------------------------------------------------------ #
    # Gemini API call helper with multi-model fallback & JSON parsing
    # ------------------------------------------------------------------ #
    def _call_gemini_json(self, contents, label: str = "request") -> Tuple[Dict[str, Any], str]:
        """Calls Gemini with automatic model fallback and JSON parsing. Returns (parsed_dict, used_model)."""
        models_to_try = [self.model_name]
        for candidate in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        last_err = None
        for m in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
                if response and response.text:
                    cleaned = self._clean_json(response.text.strip())
                    parsed = json.loads(cleaned)
                    return parsed, m
            except Exception as e:
                last_err = e
                logger.warning(f"[AIAnalyzer] {label}: model {m} failed or returned invalid JSON: {e}")

        raise last_err or RuntimeError(f"No Gemini models responded with valid JSON for {label}")

    # ------------------------------------------------------------------ #
    # Pass 1: Slide decomposition into visual elements, text, and tables
    # ------------------------------------------------------------------ #
    def _decompose_slide_elements(self, page: ExtractedPage, conversion_mode: str = "visual") -> ExtractedPage:
        """
        Decomposes the slide into distinct layout elements:
        - Standalone graphics (illustrations, diagrams, photos) cropped as pictures
        - Clean text blocks with semantic roles, typography, and badge fills
        - Native PowerPoint tables
        """
        if not page.full_render_path or not os.path.exists(page.full_render_path):
            return self._decompose_rule_based(page)

        with open(page.full_render_path, "rb") as f:
            img_bytes = f.read()

        prompt = f"""You are an expert presentation layout reconstruction engine.
Analyze this slide image (original dimensions: {page.width:.1f}x{page.height:.1f} points).

Extract:
1. "background_color": Dominant background hex (e.g. "#ffffff" or "#1e293b").
2. "text_elements": List of distinct text blocks/labels. For each:
   - "text": Exact text
   - "role": "title" | "subtitle" | "heading" | "body" | "bullet" | "badge" | "footer"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around this specific text block (include 2-3% padding for ascenders/descenders)
   - "font_size_pt": Estimated font size in points
   - "bold": true/false
   - "italic": true/false
   - "color_hex": Text color hex (e.g. "#1e293b" or "#ffffff")
   - "background_hex": Background color hex if this is a badge/pill/card with solid fill (e.g. "#334155" for dark badge), or null if transparent
3. "graphic_elements": List of visual graphics (illustrations, diagrams, photos, icons, charts). For each:
   - "name": Descriptive name
   - "type": "illustration" | "icon" | "diagram" | "chart"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around ONLY the graphic image (excluding separate text)
4. "tables": List of data tables. ONLY extract genuine statistical/tabular data grids consisting purely of alphanumeric cells (such as financial statements, comparison matrices, or numerical schedules).
   CRITICAL NEGATIVE RULE: NEVER classify multi-column slide layouts, card grids, feature lists, or sections containing illustrations/icons as tables! Those MUST be decomposed into separate text_elements and graphic_elements.

Return strictly a valid JSON object.
"""

        logger.info(f"[AIAnalyzer] Decomposing Page {page.page_num}...")
        try:
            data, used_model = self._call_gemini_json(
                [types.Part.from_bytes(data=img_bytes, mime_type="image/png"), prompt],
                label=f"Decompose-Page{page.page_num}"
            )
        except Exception as e:
            logger.warning(f"[AIAnalyzer] Gemini decomposition failed on page {page.page_num}: {e}. Falling back to rule-based.")
            return self._decompose_rule_based(page)

        pil_img = Image.open(page.full_render_path).convert("RGB")
        img_w, img_h = pil_img.size
        temp_dir = Path(page.full_render_path).parent

        bg_hex = data.get("background_color", "#ffffff")
        page.background_color = self._parse_hex_color(bg_hex) or self._detect_dominant_border_color(pil_img)

        # 1. Extract Graphics (pictures) first to enable nested-element validation for tables
        cropped_images: List[ExtractedImage] = []
        graphic_boxes = []
        for g_idx, g in enumerate(data.get("graphic_elements", [])):
            box = self._normalize_box_2d(g.get("box_2d"))
            if not box:
                continue
            graphic_boxes.append(box)
            ymin, xmin, ymax, xmax = box

            cx0 = max(0, int((xmin / 1000.0) * img_w) - 3)
            cy0 = max(0, int((ymin / 1000.0) * img_h) - 3)
            cx1 = min(img_w, int((xmax / 1000.0) * img_w) + 3)
            cy1 = min(img_h, int((ymax / 1000.0) * img_h) + 3)

            if (cx1 - cx0) < 10 or (cy1 - cy0) < 10:
                continue

            try:
                crop = pil_img.crop((cx0, cy0, cx1, cy1))
                crop_path = temp_dir / f"p{page.page_num}_graphic_{g_idx}.png"
                crop.save(str(crop_path), "PNG")
            except Exception as crop_err:
                logger.warning(f"Failed to crop graphic {g_idx}: {crop_err}")
                continue

            pdf_x0 = (xmin / 1000.0) * page.width
            pdf_y0 = (ymin / 1000.0) * page.height
            pdf_x1 = (xmax / 1000.0) * page.width
            pdf_y1 = (ymax / 1000.0) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            cropped_images.append(ExtractedImage(
                id=g_idx,
                bbox=elem_bbox,
                width=cx1 - cx0,
                height=cy1 - cy0,
                format="png",
                temp_path=str(crop_path),
                name=g.get("name", f"Graphic {g_idx + 1}"),
                element_type=g.get("type", "illustration")
            ))

        # 2. Extract Tables (with validation filter against false-positive layout grids)
        tables_list: List[ExtractedTable] = []
        table_boxes = []
        for tbl_idx, tbl in enumerate(data.get("tables", [])):
            box = self._normalize_box_2d(tbl.get("box_2d"))
            rows = tbl.get("rows", [])
            if not box or not rows:
                continue
            ymin, xmin, ymax, xmax = box
            box_area_pct = ((ymax - ymin) * (xmax - xmin)) / 10000.0
            has_nested_graphic = any(
                ymin <= (gy0 + gy1) / 2.0 <= ymax and xmin <= (gx0 + gx1) / 2.0 <= xmax
                for gy0, gx0, gy1, gx1 in graphic_boxes
            )
            if has_nested_graphic or box_area_pct > 60.0:
                logger.info(f"[AIAnalyzer] Rejecting table {box} (area={box_area_pct:.1f}%, has_graphic={has_nested_graphic}) - treating as layout grid")
                continue

            pdf_x0 = (xmin / 1000.0) * page.width
            pdf_y0 = (ymin / 1000.0) * page.height
            pdf_x1 = (xmax / 1000.0) * page.width
            pdf_y1 = (ymax / 1000.0) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            tables_list.append(ExtractedTable(
                id=tbl_idx,
                bbox=elem_bbox,
                rows=rows,
                header_row=True
            ))
            table_boxes.append(box)

        # 3. Extract Text Blocks
        text_blocks: List[TextBlock] = []
        text_block_id = 0
        for t in data.get("text_elements", []):
            box = self._normalize_box_2d(t.get("box_2d"))
            if not box:
                continue
            if self._is_inside_table(box, table_boxes):
                continue

            ymin, xmin, ymax, xmax = box

            pdf_x0 = (xmin / 1000.0) * page.width
            pdf_y0 = (ymin / 1000.0) * page.height
            pdf_x1 = (xmax / 1000.0) * page.width
            pdf_y1 = (ymax / 1000.0) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            raw_text_val = t.get("text", "").strip()
            if not raw_text_val:
                continue

            role = t.get("role", "body")
            color_hex = t.get("color_hex", "#1e293b")
            color_rgb = self._parse_hex_color(color_hex) or (30, 41, 59)
            bg_hex = t.get("background_hex")
            bg_rgb = self._parse_hex_color(bg_hex) if bg_hex else None
            font_size = float(t.get("font_size_pt", 14.0))
            is_bold = bool(t.get("bold", False)) or (role in {"title", "heading", "badge"})
            is_italic = bool(t.get("italic", False))

            if conversion_mode == "visual":
                cx0 = max(0, int((xmin / 1000.0) * img_w) - 3)
                cy0 = max(0, int((ymin / 1000.0) * img_h) - 3)
                cx1 = min(img_w, int((xmax / 1000.0) * img_w) + 3)
                cy1 = min(img_h, int((ymax / 1000.0) * img_h) + 3)
                if (cx1 - cx0) >= 10 and (cy1 - cy0) >= 10:
                    crop = pil_img.crop((cx0, cy0, cx1, cy1))
                    crop_path = temp_dir / f"p{page.page_num}_textimg_{text_block_id}.png"
                    crop.save(str(crop_path), "PNG")
                    cropped_images.append(ExtractedImage(
                        id=len(cropped_images),
                        bbox=elem_bbox,
                        width=cx1 - cx0,
                        height=cy1 - cy0,
                        format="png",
                        temp_path=str(crop_path),
                        name=f"Text: {raw_text_val[:20]}",
                        element_type="text_image"
                    ))
                    text_block_id += 1
                continue

            # In editable mode, build native editable TextBlock
            tb_lines: List[TextBlockLine] = []
            for line_str in raw_text_val.split("\n"):
                if not line_str.strip():
                    continue
                span = TextBlockSpan(
                    text=line_str.strip(),
                    font="Segoe UI",
                    size=font_size,
                    color_rgb=color_rgb,
                    color_hex=color_hex,
                    bold=is_bold,
                    italic=is_italic,
                    bbox=elem_bbox
                )
                tb_lines.append(TextBlockLine(
                    spans=[span],
                    bbox=elem_bbox,
                    text=line_str.strip(),
                    alignment="center" if role in {"title", "badge"} else "left"
                ))

            if tb_lines:
                text_blocks.append(TextBlock(
                    id=text_block_id,
                    lines=tb_lines,
                    bbox=elem_bbox,
                    text=raw_text_val,
                    role=role,
                    background_color=bg_rgb
                ))
                text_block_id += 1

        page.tables = tables_list
        page.images = cropped_images
        page.text_blocks = text_blocks
        page.vision_decomposed = True

        logger.info(
            f"[AIAnalyzer] Page {page.page_num}: {len(text_blocks)} text blocks, "
            f"{len(cropped_images)} pictures, {len(tables_list)} tables"
        )
        return page

    @staticmethod
    def _is_inside_table(elem_box: List[int], table_boxes: List[List[int]]) -> bool:
        """Checks if a text box center is completely inside a detected table."""
        if not table_boxes:
            return False
        ymin, xmin, ymax, xmax = elem_box
        cy = (ymin + ymax) / 2.0
        cx = (xmin + xmax) / 2.0
        for tb in table_boxes:
            t_ymin, t_xmin, t_ymax, t_xmax = tb
            if t_ymin <= cy <= t_ymax and t_xmin <= cx <= t_xmax:
                return True
        return False

    def _process_elements(
        self,
        page: ExtractedPage,
        elements: List[Dict[str, Any]],
        conversion_mode: str = "visual",
        bg_hex: Optional[str] = None
    ) -> ExtractedPage:
        """
        Processes custom user regions or explicit region lists:
        - 'graphic' -> cropped picture shape
        - 'table' -> table shape
        - 'text' -> editable text block with OCR and font fitting
        """
        if not page.full_render_path or not os.path.exists(page.full_render_path):
            return self._decompose_rule_based(page)

        pil_img = Image.open(page.full_render_path).convert("RGB")
        img_w, img_h = pil_img.size

        # Background color
        page.background_color = self._parse_hex_color(bg_hex) if bg_hex else None
        if not page.background_color:
            page.background_color = self._detect_dominant_border_color(pil_img)

        temp_dir = Path(page.full_render_path).parent
        cropped_images: List[ExtractedImage] = []
        text_blocks: List[TextBlock] = []
        tables_list: List[ExtractedTable] = []
        text_block_id = 0

        for idx, el in enumerate(elements):
            box = self._normalize_box_2d(el.get("box_2d"))
            if not box:
                continue

            ymin, xmin, ymax, xmax = box

            cx0 = max(0, int((xmin / 1000.0) * img_w) - 3)
            cy0 = max(0, int((ymin / 1000.0) * img_h) - 3)
            cx1 = min(img_w, int((xmax / 1000.0) * img_w) + 3)
            cy1 = min(img_h, int((ymax / 1000.0) * img_h) + 3)

            if (cx1 - cx0) < 10 or (cy1 - cy0) < 10:
                continue

            pdf_x0 = (xmin / 1000.0) * page.width
            pdf_y0 = (ymin / 1000.0) * page.height
            pdf_x1 = (xmax / 1000.0) * page.width
            pdf_y1 = (ymax / 1000.0) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            elem_name = el.get("name") or f"Element {idx + 1}"
            elem_type = str(el.get("type", "card")).lower()
            is_text_primary = bool(
                el.get("text_primary") or
                elem_type in TEXT_PRIMARY_TYPES or
                elem_type == "text"
            )

            # Check if this element is a table
            if elem_type == "table" or "rows" in el:
                rows = el.get("rows", [])
                if rows:
                    tables_list.append(ExtractedTable(
                        id=len(tables_list),
                        bbox=elem_bbox,
                        rows=rows,
                        header_row=True
                    ))
                    continue

            try:
                crop = pil_img.crop((cx0, cy0, cx1, cy1))
                crop_path = temp_dir / f"p{page.page_num}_custom_{idx}.png"
                crop.save(str(crop_path), "PNG")
            except Exception as crop_err:
                logger.warning(f"[AIAnalyzer] Failed to crop custom element {idx}: {crop_err}")
                continue

            # If element is a table without pre-computed rows, run table OCR
            if elem_type == "table" and self.client:
                try:
                    tbl = self._ocr_table(crop_path, elem_bbox, len(tables_list), page)
                    if tbl and tbl.rows:
                        tables_list.append(tbl)
                        logger.info(f"[AIAnalyzer]   → OCR'd table with {len(tbl.rows)} rows")
                        continue
                except Exception as tbl_err:
                    logger.warning(f"[AIAnalyzer] Table OCR failed for custom region: {tbl_err}")

            # If element is marked as text (or editable mode with text-primary):
            # User specifically chose text, so convert to editable TextBlock via OCR!
            if (elem_type in {"text", "badge"} or is_text_primary) and self.client:
                try:
                    ocr_block = self._ocr_element(
                        crop_path, elem_bbox, elem_name, elem_type, text_block_id, page
                    )
                    if ocr_block:
                        text_blocks.append(ocr_block)
                        text_block_id += 1
                        logger.info(f"[AIAnalyzer]   → OCR'd custom '{elem_name}' → {len(ocr_block.lines)} lines")
                        continue
                except Exception as ocr_err:
                    logger.warning(f"[AIAnalyzer] OCR failed for custom '{elem_name}': {ocr_err}. Keeping as picture.")

            # Default: add as picture shape
            cropped_images.append(ExtractedImage(
                id=idx,
                bbox=elem_bbox,
                width=cx1 - cx0,
                height=cy1 - cy0,
                format="png",
                temp_path=str(crop_path),
                name=elem_name,
                element_type=elem_type
            ))

        page.images = cropped_images
        page.text_blocks = text_blocks
        page.tables = tables_list
        page.vision_decomposed = True

        logger.info(
            f"[AIAnalyzer] Page {page.page_num} custom processed: "
            f"{len(cropped_images)} pictures, {len(text_blocks)} text boxes, {len(tables_list)} tables"
        )
        return page

    # ------------------------------------------------------------------ #
    # Pass 2: Per-element focused OCR & Table Extraction
    # ------------------------------------------------------------------ #
    def _ocr_table(
        self,
        crop_path: Path,
        elem_bbox: Tuple[float, float, float, float],
        block_id: int,
        page: ExtractedPage
    ) -> Optional[ExtractedTable]:
        """
        Runs Gemini Vision on a cropped table element to extract
        structured 2D rows of text, column alignments, and styling.
        """
        with open(str(crop_path), "rb") as f:
            crop_bytes = f.read()

        prompt = """You are an expert table OCR and layout engine for presentation slides.
Analyze this cropped image of a table.

Extract:
1. "rows": 2D array of strings for all cells (clean whitespace, preserve newlines within cells if multi-line).
2. "has_header_row": true/false
3. "header_background_hex": Header fill color hex (e.g. "#1e293b", "#f1f5f9"), or null if transparent/white.
4. "header_text_color_hex": Header font color hex (e.g. "#ffffff", "#0f172a"), or null.
5. "column_alignments": Array of "left" | "center" | "right" for each column (use "right" for numerical/currency/percentage columns).
6. "alternate_row_background_hex": Zebra striping fill color if present, or null.

Return strictly a JSON object:
{
  "rows": [
    ["Col 1 Header", "Col 2 Header", "Col 3 Header"],
    ["Row 1 Cell 1", "Row 1 Cell 2", "123.45"]
  ],
  "has_header_row": true,
  "header_background_hex": "#f1f5f9",
  "header_text_color_hex": "#1e293b",
  "column_alignments": ["left", "left", "right"],
  "alternate_row_background_hex": null
}
If this image is not a table, return: {"rows": []}
"""
        data, used_model = self._call_gemini_json(
            [types.Part.from_bytes(data=crop_bytes, mime_type="image/png"), prompt],
            label=f"OCR-Table-{block_id}"
        )
        rows = data.get("rows", [])
        if rows and isinstance(rows, list) and len(rows) > 0:
            header_bg = self._parse_hex_color(data.get("header_background_hex"))
            header_text = self._parse_hex_color(data.get("header_text_color_hex"))
            alt_bg = self._parse_hex_color(data.get("alternate_row_background_hex"))
            col_aligns = data.get("column_alignments")
            if not isinstance(col_aligns, list):
                col_aligns = None

            return ExtractedTable(
                id=block_id,
                bbox=elem_bbox,
                rows=rows,
                header_row=bool(data.get("has_header_row", True)),
                header_bg_rgb=header_bg,
                header_text_rgb=header_text,
                col_alignments=col_aligns,
                alternate_bg_rgb=alt_bg
            )
        return None

    def _ocr_element(
        self,
        crop_path: Path,
        elem_bbox: Tuple[float, float, float, float],
        elem_name: str,
        elem_type: str,
        block_id: int,
        page: ExtractedPage
    ) -> Optional[TextBlock]:
        """
        Runs Gemini Vision on a cropped element image to extract
        clean semantic paragraphs, typography styling, and container aesthetics.
        """
        with open(str(crop_path), "rb") as f:
            crop_bytes = f.read()

        box_w = max(10.0, elem_bbox[2] - elem_bbox[0])
        box_h = max(10.0, elem_bbox[3] - elem_bbox[1])
        slide_w = page.width if page and page.width > 0 else 960.0
        slide_h = page.height if page and page.height > 0 else 540.0

        prompt = f"""You are an expert presentation OCR and typography extraction engine.
Analyze this cropped image of a single slide element/card.

Physical context:
- Parent slide dimensions: {slide_w:.0f} x {slide_h:.0f} pt
- This cropped box occupies: {box_w:.1f} pt width by {box_h:.1f} pt height on the slide
- Reference font scales: Titles (28-36 pt), Subheadings (18-24 pt), Body/Cards (11-15 pt), Badges/Captions (9-11 pt).

Extract:
1. "container":
   - "background_hex": Solid card/badge fill color (e.g. "#ffffff", "#f8fafc", "#1e293b"), or null if transparent.
   - "border_hex": Card outline border color if visible (e.g. "#cbd5e1"), or null.
   - "is_rounded": true if rounded corners or pill shape, false otherwise.
2. "paragraphs": List of distinct semantic paragraphs (headings, body blocks, bullet items).
   CRITICAL: Do NOT break continuous sentences into multiple lines. Group naturally wrapped text into a single paragraph string so it reflows cleanly.
   For each paragraph:
   - "type": "title" | "heading" | "body" | "bullet" | "badge"
   - "text": Clean text content of the paragraph (if bullet, exclude leading bullet symbols like • or -).
   - "font_family": Standard PowerPoint font ("Calibri", "Arial", "Segoe UI", "Century Gothic")
   - "font_size_pt": Estimated font size in points, calibrated to the {box_w:.0f}x{box_h:.0f} pt box size.
   - "bold": true/false
   - "italic": true/false
   - "color_hex": Text color hex (e.g. "#000000" or "#334155")
   - "alignment": "left" | "center" | "right"
   - "is_bullet": true if this is a bulleted/numbered list item, false otherwise

Return strictly valid JSON:
{{
  "container": {{
    "background_hex": null,
    "border_hex": null,
    "is_rounded": false
  }},
  "paragraphs": [
    {{
      "type": "heading",
      "text": "Heading text",
      "font_family": "Segoe UI",
      "font_size_pt": 18,
      "bold": true,
      "italic": false,
      "color_hex": "#000000",
      "alignment": "left",
      "is_bullet": false
    }}
  ]
}}
If there is no readable text, return: {{"container": {{"background_hex": null, "border_hex": null, "is_rounded": false}}, "paragraphs": []}}
"""

        data, used_model = self._call_gemini_json(
            [types.Part.from_bytes(data=crop_bytes, mime_type="image/png"), prompt],
            label=f"OCR-{elem_name}"
        )

        paragraphs_data = data.get("paragraphs")
        # Backwards compatibility if model returned "lines"
        if not paragraphs_data and data.get("lines"):
            paragraphs_data = data.get("lines")

        if not paragraphs_data or not isinstance(paragraphs_data, list):
            return None

        tb_lines: List[TextBlockLine] = []

        for p_data in paragraphs_data:
            text = str(p_data.get("text") or "").strip()
            if not text:
                continue

            # Strip leading bullet glyphs if is_bullet was flagged or raw bullet character present
            is_bullet = bool(p_data.get("is_bullet", False))
            if text.startswith(("• ", "- ", "* ", "– ")):
                is_bullet = True
                text = text[2:].strip()

            p_type = str(p_data.get("type", elem_type or "body")).lower().strip()
            font_name = str(p_data.get("font_family") or "Segoe UI").strip()
            font_size = float(p_data.get("font_size_pt", 14.0))
            is_bold = bool(p_data.get("bold", False)) or (p_type in {"title", "heading", "badge"})
            is_italic = bool(p_data.get("italic", False))
            color_hex = str(p_data.get("color_hex", "#1e293b"))
            color_rgb = self._parse_hex_color(color_hex) or (30, 41, 59)
            alignment = str(p_data.get("alignment", "left")).lower().strip()
            if alignment not in {"left", "center", "right", "justify"}:
                alignment = "left"

            span = TextBlockSpan(
                text=text,
                font=font_name,
                size=font_size,
                color_rgb=color_rgb,
                color_hex=color_hex if color_hex.startswith("#") else "#1e293b",
                bold=is_bold,
                italic=is_italic,
                bbox=elem_bbox
            )
            tb_lines.append(TextBlockLine(
                spans=[span],
                bbox=elem_bbox,
                text=text,
                alignment=alignment,
                role=p_type,
                is_bullet=is_bullet
            ))

        if not tb_lines:
            return None

        full_text = "\n".join(line.text for line in tb_lines)
        container = data.get("container", {}) if isinstance(data.get("container"), dict) else {}
        bg_hex = container.get("background_hex") or data.get("element_background_hex")
        border_hex = container.get("border_hex")
        is_rounded = bool(container.get("is_rounded", False))

        elem_bg_rgb = self._parse_hex_color(bg_hex) if bg_hex else None
        border_rgb = self._parse_hex_color(border_hex) if border_hex else None

        # Determine dominant block role
        primary_role = tb_lines[0].role if tb_lines else "body"
        if elem_type in {"header", "title", "subtitle", "badge"}:
            primary_role = elem_type

        return TextBlock(
            id=block_id,
            lines=tb_lines,
            bbox=elem_bbox,
            text=full_text,
            role=primary_role,
            background_color=elem_bg_rgb,
            border_color=border_rgb,
            is_rounded=is_rounded
        )

    # ------------------------------------------------------------------ #
    # Rule-based fallback
    # ------------------------------------------------------------------ #
    def _decompose_rule_based(self, page: ExtractedPage) -> ExtractedPage:
        """
        Algorithmic fallback when AI is disabled or unavailable.
        """
        if page.full_render_path and os.path.exists(page.full_render_path):
            try:
                pil_img = Image.open(page.full_render_path).convert("RGB")
                page.background_color = self._detect_dominant_border_color(pil_img)
            except Exception as e:
                logger.warning(f"Border color detection error: {e}")
                page.background_color = (255, 255, 255)
        else:
            page.background_color = (255, 255, 255)

        if not page.images and page.fallback_background_image:
            page.images.append(page.fallback_background_image)

        return page

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_json(raw: str) -> str:
        """Strip markdown fences and find the outermost JSON object."""
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            return raw[start:end + 1]
        return raw

    @staticmethod
    def _parse_hex_color(hex_str: Optional[str]) -> Optional[Tuple[int, int, int]]:
        if not hex_str or not isinstance(hex_str, str):
            return None
        clean = hex_str.strip().lstrip("#")
        if len(clean) == 6:
            try:
                return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
            except ValueError:
                return None
        return None

    @staticmethod
    def _detect_dominant_border_color(img: Image.Image) -> Tuple[int, int, int]:
        w, h = img.size
        samples = []
        step_x = max(1, w // 40)
        step_y = max(1, h // 40)
        for x in range(0, w, step_x):
            samples.append(img.getpixel((x, min(5, h - 1))))
            samples.append(img.getpixel((x, max(0, h - 6))))
        for y in range(0, h, step_y):
            samples.append(img.getpixel((min(5, w - 1), y)))
            samples.append(img.getpixel((max(0, w - 6), y)))
        if samples:
            most_common, _ = Counter(samples).most_common(1)[0]
            return most_common
        return (255, 255, 255)
