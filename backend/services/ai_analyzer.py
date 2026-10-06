import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, deque
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

from backend.models.schemas import (
    ExtractedPage,
    ExtractedImage,
    TextBlock,
    TextBlockLine,
    TextBlockSpan,
    ExtractedTable,
    ExtractedShape,
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

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-3.1-flash-lite"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
        self.model_name = model_name or "gemini-3.1-flash-lite"
        self.client = None
        self.deprioritized_models = set()
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
                logger.warning(f"Gemini slide element decomposition failed for page {page.page_num}: {e}. Falling back to heuristic/rule-based.")

        # Heuristic visual decomposition fallback for visual mode
        if conversion_mode == "visual" and page.full_render_path:
            try:
                detection = self._detect_slide_elements_heuristic(
                    page.full_render_path, page.width, page.height, conversion_mode=conversion_mode
                )
                heuristic_elements = detection.get("elements", [])
                if heuristic_elements and len(heuristic_elements) >= 1:
                    logger.info(f"[AIAnalyzer] Using {len(heuristic_elements)} heuristic vision layers for Page {page.page_num}")
                    return self._process_elements(page, heuristic_elements, conversion_mode=conversion_mode)
            except Exception as h_err:
                logger.warning(f"Heuristic visual decomposition failed on page {page.page_num}: {h_err}")

        return self._decompose_rule_based(page)

    @staticmethod
    def _normalize_box_2d(raw_box: Any) -> Optional[List[int]]:
        """
        Normalizes bounding box coordinates from Gemini into a flat [ymin, xmin, ymax, xmax] list of ints.
        Handles flat lists, nested lists (e.g. [[ymin, xmin, ymax, xmax]], or [[ymin, ...], extra_data...]),
        dict formats, and floats.
        """
        if not raw_box:
            return None

        if isinstance(raw_box, dict):
            try:
                ymin = int(round(float(raw_box.get("ymin", raw_box.get("y0", 0)))))
                xmin = int(round(float(raw_box.get("xmin", raw_box.get("x0", 0)))))
                ymax = int(round(float(raw_box.get("ymax", raw_box.get("y1", 0)))))
                xmax = int(round(float(raw_box.get("xmax", raw_box.get("x1", 0)))))
                if ymax > ymin and xmax > xmin:
                    return [ymin, xmin, ymax, xmax]
            except (ValueError, TypeError):
                return None

        if not isinstance(raw_box, (list, tuple)):
            return None

        curr = raw_box
        if len(curr) >= 1 and isinstance(curr[0], (list, tuple)) and len(curr[0]) >= 4:
            curr = curr[0]
        else:
            while isinstance(curr, (list, tuple)) and len(curr) == 1 and isinstance(curr[0], (list, tuple)):
                curr = curr[0]

        if isinstance(curr, (list, tuple)) and len(curr) >= 4:
            try:
                coords = [int(round(float(curr[i]))) for i in range(4)]
                ymin, xmin, ymax, xmax = coords
                if ymax > ymin and xmax > xmin:
                    return coords
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def _snap_bbox_to_whitespace(
        img: Image.Image,
        cx0: int,
        cy0: int,
        cx1: int,
        cy1: int,
        bg_rgb: Optional[Tuple[int, int, int]] = (255, 255, 255),
        max_expand_x: int = 45,
        max_expand_y: int = 30
    ) -> Tuple[int, int, int, int]:
        """
        Computer vision whitespace boundary snapping:
        If an element bounding box cuts through ink (pixels differing from slide background),
        iteratively expands outward until it lands on clean whitespace or hits the safety threshold.
        Guarantees letters, chemical symbols, bullet points, and doodles are never sliced in half.
        """
        w, h = img.size
        bg = bg_rgb or (255, 255, 255)

        def is_ink_col(x: int, y_start: int, y_end: int) -> bool:
            if x < 0 or x >= w:
                return False
            ink_count = 0
            step = max(1, (y_end - y_start) // 60)
            for y in range(y_start, y_end, step):
                px = img.getpixel((x, y))
                diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
                if diff > 40:
                    ink_count += 1
                    if ink_count >= 2:
                        return True
            return False

        def is_ink_row(y: int, x_start: int, x_end: int) -> bool:
            if y < 0 or y >= h:
                return False
            ink_count = 0
            step = max(1, (x_end - x_start) // 60)
            for x in range(x_start, x_end, step):
                px = img.getpixel((x, y))
                diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
                if diff > 40:
                    ink_count += 1
                    if ink_count >= 2:
                        return True
            return False

        # Expand left (cx0)
        for _ in range(max_expand_x):
            if not is_ink_col(cx0, cy0, cy1):
                break
            if cx0 <= 0:
                break
            cx0 -= 1

        # Expand right (cx1)
        for _ in range(max_expand_x):
            if not is_ink_col(cx1, cy0, cy1):
                break
            if cx1 >= w - 1:
                break
            cx1 += 1

        # Expand top (cy0)
        for _ in range(max_expand_y):
            if not is_ink_row(cy0, cx0, cx1):
                break
            if cy0 <= 0:
                break
            cy0 -= 1

        # Expand bottom (cy1)
        for _ in range(max_expand_y):
            if not is_ink_row(cy1, cx0, cx1):
                break
            if cy1 >= h - 1:
                break
            cy1 += 1

        return max(0, cx0), max(0, cy0), min(w, cx1), min(h, cy1)

    @staticmethod
    def _make_transparent_background(
        crop_img: Image.Image,
        bg_rgb: Optional[Tuple[int, int, int]] = (255, 255, 255),
        tolerance: int = 25
    ) -> Image.Image:
        """
        Alpha masking for standalone illustrations and doodles:
        Converts exterior background connected to the borders into transparent alpha (0),
        allowing generous crop padding without opaque white boxes obscuring neighboring elements.
        """
        if crop_img.mode != "RGBA":
            crop_img = crop_img.convert("RGBA")

        bg = bg_rgb or (255, 255, 255)
        bg_lum = bg[0] * 0.299 + bg[1] * 0.587 + bg[2] * 0.114
        # Only apply on light/clean backgrounds
        if bg_lum < 180:
            return crop_img

        w, h = crop_img.size
        transparent = (bg[0], bg[1], bg[2], 0)
        sample_points = [
            (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
            (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)
        ]
        for pt in sample_points:
            px = crop_img.getpixel(pt)
            diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
            if diff <= tolerance * 3 and px[3] > 0:
                ImageDraw.floodfill(crop_img, pt, transparent, thresh=tolerance)

        return crop_img

    # ------------------------------------------------------------------ #
    # Standalone region detection for interactive editor
    # ------------------------------------------------------------------ #
    def _detect_slide_elements_heuristic(
        self,
        image_path: str,
        width: float,
        height: float,
        conversion_mode: str = "visual"
    ) -> Dict[str, Any]:
        """
        High-speed computer vision visual component detector (offline fallback).
        Uses connected-component clustering with whitespace gap analysis to detect
        animatable picture layers without requiring external AI APIs.
        """
        try:
            img = Image.open(image_path).convert("RGB")
            bg = self._detect_dominant_border_color(img)
            gw, gh = 128, 72  # 16:9 ratio, ultra-fast and accurate
            small = img.resize((gw, gh), Image.Resampling.BILINEAR)

            grid = []
            for y in range(gh):
                row = []
                for x in range(gw):
                    p = small.getpixel((x, y))
                    diff = abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2])
                    row.append(1 if diff > 35 else 0)
                grid.append(row)

            # Single-pass 3x3 dilation to bridge word spacing
            dilated = [[0] * gw for _ in range(gh)]
            for y in range(gh):
                for x in range(gw):
                    if grid[y][x] == 1:
                        for dy in (-1, 0, 1):
                            for dx in (-1, 0, 1):
                                ny, nx = y + dy, x + dx
                                if 0 <= ny < gh and 0 <= nx < gw:
                                    dilated[ny][nx] = 1

            visited = [[False] * gw for _ in range(gh)]
            raw_boxes = []

            for y in range(gh):
                for x in range(gw):
                    if dilated[y][x] == 1 and not visited[y][x]:
                        queue = deque([(y, x)])
                        visited[y][x] = True
                        min_y, max_y = y, y
                        min_x, max_x = x, x
                        count = 0
                        while queue:
                            cy, cx = queue.popleft()
                            count += 1
                            if cy < min_y: min_y = cy
                            if cy > max_y: max_y = cy
                            if cx < min_x: min_x = cx
                            if cx > max_x: max_x = cx
                            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                                ny, nx = cy + dy, cx + dx
                                if 0 <= ny < gh and 0 <= nx < gw and not visited[ny][nx] and dilated[ny][nx] == 1:
                                    visited[ny][nx] = True
                                    queue.append((ny, nx))

                        if count >= 6:
                            ymin = max(0, int((min_y / gh) * 1000) - 10)
                            xmin = max(0, int((min_x / gw) * 1000) - 10)
                            ymax = min(1000, int((max_y / gh) * 1000) + 10)
                            xmax = min(1000, int((max_x / gw) * 1000) + 10)
                            raw_boxes.append([ymin, xmin, ymax, xmax])

            def merge_boxes(b_list, threshold=35):
                changed = True
                while changed:
                    changed = False
                    new_list = []
                    skip = set()
                    for i in range(len(b_list)):
                        if i in skip:
                            continue
                        b1 = b_list[i]
                        for j in range(i + 1, len(b_list)):
                            if j in skip:
                                continue
                            b2 = b_list[j]
                            if not (b1[2] + threshold < b2[0] or b1[0] - threshold > b2[2] or
                                    b1[3] + threshold < b2[1] or b1[1] - threshold > b2[3]):
                                b1 = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                                skip.add(j)
                                changed = True
                        new_list.append(b1)
                    b_list = new_list
                return b_list

            merged = merge_boxes(raw_boxes, threshold=35)
            merged.sort(key=lambda b: (b[0], b[1]))

            elements = []
            for idx, box in enumerate(merged):
                ymin, xmin, ymax, xmax = box
                if ymax <= 200:
                    name = "Title" if idx == 0 else f"Header {idx + 1}"
                else:
                    name = f"Layer {idx + 1}"
                elements.append({
                    "name": name,
                    "type": "graphic" if conversion_mode == "visual" else "card",
                    "box_2d": box,
                    "text_primary": False if conversion_mode == "visual" else True
                })

            bg_hex = f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}"
            return {
                "background_color": bg_hex,
                "elements": elements,
                "model": "heuristic-vision"
            }
        except Exception as e:
            logger.warning(f"Heuristic detection failed: {e}")
            return {
                "background_color": "#ffffff",
                "elements": [],
                "model": "fallback"
            }

    def detect_slide_elements(
        self,
        image_path: str,
        width: float,
        height: float,
        conversion_mode: str = "visual"
    ) -> Dict[str, Any]:
        """
        Analyzes a single slide image and returns visual regions:
        - In 'visual' mode: clusters slide into 3-7 clean, animatable picture layers for PowerPoint animations.
        - In 'editable' mode: returns fine-grained text, graphic, and table elements.
        Used by the frontend Slide Region Inspector.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Slide image not found: {image_path}")

        if not self.client:
            return self._detect_slide_elements_heuristic(image_path, width, height, conversion_mode=conversion_mode)

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        if conversion_mode == "visual":
            prompt = f"""You are an expert presentation visual decomposition engine for PowerPoint animation layers.
Analyze this slide image (original dimensions: {width:.1f}x{height:.1f} points).
Identify distinct, independent visual blocks that a presenter/teacher would want to animate sequentially (e.g. Title, Main Diagram / Equipment, Problem Question, Step 1, Step 2, Worked Example, Mascot / Kitten).

Extract:
1. "background_color": Dominant background hex (e.g. "#ffffff" or "#1e293b").
2. "layers": List of distinct animatable visual components (aim for 3 to 7 clean, cohesive layers). For each:
   - "name": Concise descriptive layer name for PowerPoint animation (e.g. "Title", "Balance Scale Diagram", "Problem Question", "Step 1 Calculation", "Step 2 Calculation", "Cat Mascot")
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 tightly surrounding the entire visual unit with generous margins so nothing is clipped.
Return strictly a valid JSON object:
{{
  "background_color": "#ffffff",
  "layers": [
    {{"name": "Title", "box_2d": [ymin, xmin, ymax, xmax]}}
  ]
}}
"""
            data, used_model = self._call_gemini_json(
                [types.Part.from_bytes(data=img_bytes, mime_type="image/png"), prompt],
                label="detect_visual_layers"
            )
            elements = []
            layers_data = data.get("layers", [])
            if not layers_data and data.get("elements"):
                layers_data = data.get("elements")
            elif not layers_data and data.get("graphic_elements"):
                layers_data = data.get("graphic_elements") + data.get("text_elements", [])

            for idx, lyr in enumerate(layers_data):
                box = self._normalize_box_2d(lyr.get("box_2d"))
                if not box:
                    continue
                name = lyr.get("name") or f"Layer {idx + 1}"
                elements.append({
                    "name": name,
                    "type": "graphic",
                    "box_2d": box,
                    "text_primary": False
                })

            return {
                "background_color": data.get("background_color", "#ffffff"),
                "elements": elements,
                "model": used_model
            }

        prompt = f"""You are an expert presentation layout reconstruction engine.
Analyze this slide image (original dimensions: {width:.1f}x{height:.1f} points).

Extract:
1. "background_color": Dominant background hex (e.g. "#ffffff" or "#1e293b").
2. "text_elements": List of distinct text blocks/labels. For each:
   - "text": Exact text
   - "role": "title" | "subtitle" | "heading" | "body" | "bullet" | "badge" | "footer"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around this specific text block (include 2-3% padding for ascenders/descenders)
   - "font_family": Dominant font style/family (e.g. "Comic Neue" for comic/casual/handwritten lettering, "Segoe UI", "Century Gothic", "Calibri", "Arial", "Georgia")
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

        # 2. Tables
        valid_table_boxes = []
        for tbl in data.get("tables", []):
            box = self._normalize_box_2d(tbl.get("box_2d"))
            if not box:
                continue
            ymin, xmin, ymax, xmax = box
            box_area_pct = ((ymax - ymin) * (xmax - xmin)) / 10000.0
            has_nested_graphic = any(
                ymin <= (gy0 + gy1) / 2.0 <= ymax and xmin <= (gx0 + gx1) / 2.0 <= xmax
                for gy0, gx0, gy1, gx1 in graphic_boxes
            )
            if has_nested_graphic or box_area_pct > 65.0:
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
        """
        Calls Gemini with adaptive circuit-breaker model fallback and JSON parsing.
        If a model fails due to high demand (503) or rate limits (429), it is deprioritized
        for remaining pages, and the working fallback model is promoted to prevent timeout delays.
        """
        candidates = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]

        models_to_try = []
        # Attempt current primary model first if not deprioritized
        if self.model_name not in self.deprioritized_models:
            models_to_try.append(self.model_name)

        # Add candidate models that have not failed
        for candidate in candidates:
            if candidate not in models_to_try and candidate not in self.deprioritized_models:
                models_to_try.append(candidate)

        # Finally append deprioritized models as last resorts
        for candidate in candidates:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        last_err = None
        http_options = types.HttpOptions(
            timeout=25000,
            retry_options=types.HttpRetryOptions(attempts=1)
        )

        for m in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        http_options=http_options
                    )
                )
                if response and response.text:
                    cleaned = self._clean_json(response.text.strip())
                    parsed = json.loads(cleaned)

                    # Sticky promotion: If the original primary model failed and fallback succeeded, promote fallback
                    if m != self.model_name and self.model_name in self.deprioritized_models:
                        logger.info(f"[AIAnalyzer] Circuit breaker: promoting {m} as active primary model for subsequent slides (replaced {self.model_name}).")
                        self.model_name = m

                    return parsed, m
            except Exception as e:
                last_err = e
                err_str = str(e)
                # If model is unavailable (503) or rate-limited (429), deprioritize it immediately
                if any(code in err_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand"]):
                    if m not in self.deprioritized_models:
                        logger.warning(f"[AIAnalyzer] {label}: model {m} is overloaded/unavailable. Deprioritizing for subsequent slides.")
                        self.deprioritized_models.add(m)
                else:
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
        - Tables (cropped as high-fidelity picture in visual mode, or native PPTX table in editable mode)
        """
        if not page.full_render_path or not os.path.exists(page.full_render_path):
            return self._decompose_rule_based(page)

        with open(page.full_render_path, "rb") as f:
            img_bytes = f.read()

        prompt = f"""You are an expert presentation layout reconstruction engine.
Analyze this slide image (original dimensions: {page.width:.1f}x{page.height:.1f} points).

Extract:
1. "background_color": Dominant background hex (e.g. "#ffffff" or "#1e293b").
2. "text_elements": List of distinct text blocks/labels (excluding text inside genuine tables). For each:
   - "text": Exact text
   - "role": "title" | "subtitle" | "heading" | "body" | "bullet" | "badge" | "footer"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 with generous boundaries around this specific text block (include 3-4% padding on left/right/top/bottom so letters, words, and subscripts are NEVER clipped!). If a text block is inside a callout box, rule frame, or border card, extend the box to encompass the outer border stroke so the frame is preserved.
   - "font_size_pt": Estimated font size in points
   - "bold": true/false
   - "italic": true/false
   - "color_hex": Text color hex (e.g. "#1e293b" or "#ffffff")
   - "background_hex": Background color hex if this is a badge/pill/card with solid fill (e.g. "#334155" for dark badge), or null if transparent
3. "graphic_elements": Standalone visual graphics (illustrations, diagrams, photos, icons, charts). Excluding pure text and text containers. For each:
   - "name": Descriptive name
   - "type": "illustration" | "icon" | "diagram" | "chart"
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around ONLY the graphic image (excluding separate text)
   CRITICAL NEGATIVE RULES FOR GRAPHICS:
   - Standalone graphics must be actual illustrations, characters, icons, or drawings. Do NOT extract rectangular card containers, border boxes, bounding frames, or background panels as graphic elements.
   - Do NOT duplicate elements: if a visual diagram has multiple connected components (e.g. a central beaker with arrows pointing to it), extract it as ONE unified diagram, NOT both the whole diagram and duplicate nested sub-parts.
   - CRITICAL: NEVER include explanatory text paragraphs, definitions, or side notes inside a graphic_element bounding box! If a curved arrow or line points to a text block, terminate the graphic box at the tip of the arrow. The text must remain a separate text_element.
   - CRITICAL: If a drawing has text inside it (such as a balance scale with weights labeled 'Magnesium' or molecules labeled 'H2O'), the graphic box MUST encompass the entire object and its labels completely with generous margins so nothing is cut off.
   - CRITICAL: For bulleted text items (•, -, 1.), ALWAYS include the bullet glyph and leading margin in 'text_elements' box_2d.
4. "tables": Tabular data grids (such as multi-row multi-column comparison tables, statistical tables). For each:
   - "name": Descriptive name
   - "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000 around the entire table grid including outer borders (excluding surrounding standalone illustrations outside the table)
   - "rows": 2D array of string values for all cells
   - "has_header_row": true/false
   - "header_bg_hex": Header fill hex or null
   - "border_hex": Table grid lines color hex or null
   CRITICAL NEGATIVE RULE: Do NOT classify flowchart steps, card layouts, or process arrow sequences as tables! Those must be decomposed into graphic_elements and text_elements.

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
        raw_graphics = []
        for g_idx, g in enumerate(data.get("graphic_elements", [])):
            box = self._normalize_box_2d(g.get("box_2d"))
            if not box:
                continue
            g_name = (g.get("name") or "").lower()
            # Filter out container boxes / border frames mistakenly extracted as graphics
            if any(k in g_name for k in ["border frame", "card box", "card frame", "container frame", "background frame", "outer box", "outer frame"]):
                logger.info(f"[AIAnalyzer] Suppressing container frame graphic: '{g.get('name')}'")
                continue
            raw_graphics.append((box, g, g_idx))

        # Deduplicate overlapping graphics (suppress nested duplicate graphics e.g. Beaker inside Beaker with Arrows)
        suppressed_graphic_indices = set()
        for i in range(len(raw_graphics)):
            if i in suppressed_graphic_indices:
                continue
            box_i, g_i, _ = raw_graphics[i]
            area_i = (box_i[2] - box_i[0]) * (box_i[3] - box_i[1])
            for j in range(i + 1, len(raw_graphics)):
                if j in suppressed_graphic_indices:
                    continue
                box_j, g_j, _ = raw_graphics[j]
                area_j = (box_j[2] - box_j[0]) * (box_j[3] - box_j[1])

                iy0 = max(box_i[0], box_j[0])
                ix0 = max(box_i[1], box_j[1])
                iy1 = min(box_i[2], box_j[2])
                ix1 = min(box_i[3], box_j[3])

                if iy1 > iy0 and ix1 > ix0:
                    inter_area = (iy1 - iy0) * (ix1 - ix0)
                    containment_i = inter_area / area_i if area_i > 0 else 0
                    containment_j = inter_area / area_j if area_j > 0 else 0

                    if containment_j > 0.70:
                        logger.info(f"[AIAnalyzer] Suppressing duplicate nested graphic '{g_j.get('name')}' (inside '{g_i.get('name')}')")
                        suppressed_graphic_indices.add(j)
                    elif containment_i > 0.70:
                        logger.info(f"[AIAnalyzer] Suppressing duplicate nested graphic '{g_i.get('name')}' (inside '{g_j.get('name')}')")
                        suppressed_graphic_indices.add(i)
                        break

        accepted_graphics = [raw_graphics[i] for i in range(len(raw_graphics)) if i not in suppressed_graphic_indices]
        cropped_images: List[ExtractedImage] = []
        graphic_boxes = []

        for box, g, g_idx in accepted_graphics:
            graphic_boxes.append(box)
            ymin, xmin, ymax, xmax = box

            pad_x = max(16, int(img_w * 0.012))
            pad_y = max(12, int(img_h * 0.010))
            cx0 = max(0, int((xmin / 1000.0) * img_w) - pad_x)
            cy0 = max(0, int((ymin / 1000.0) * img_h) - pad_y)
            cx1 = min(img_w, int((xmax / 1000.0) * img_w) + pad_x)
            cy1 = min(img_h, int((ymax / 1000.0) * img_h) + pad_y)

            # Snap boundaries outward to whitespace so line art & enclosed text are never sliced
            cx0, cy0, cx1, cy1 = self._snap_bbox_to_whitespace(
                pil_img, cx0, cy0, cx1, cy1, page.background_color,
                max_expand_x=int(img_w * 0.04), max_expand_y=int(img_h * 0.025)
            )

            if (cx1 - cx0) < 10 or (cy1 - cy0) < 10:
                continue

            try:
                crop = pil_img.crop((cx0, cy0, cx1, cy1))
                # Make exterior background transparent so large crops never block neighboring elements
                crop = self._make_transparent_background(crop, page.background_color)
                crop_path = temp_dir / f"p{page.page_num}_graphic_{g_idx}.png"
                crop.save(str(crop_path), "PNG")
            except Exception as crop_err:
                logger.warning(f"Failed to crop graphic {g_idx}: {crop_err}")
                continue

            pdf_x0 = (cx0 / img_w) * page.width
            pdf_y0 = (cy0 / img_h) * page.height
            pdf_x1 = (cx1 / img_w) * page.width
            pdf_y1 = (cy1 / img_h) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            cropped_images.append(ExtractedImage(
                id=len(cropped_images),
                bbox=elem_bbox,
                width=cx1 - cx0,
                height=cy1 - cy0,
                format="png",
                temp_path=str(crop_path),
                name=g.get("name", f"Graphic {g_idx + 1}"),
                element_type=g.get("type", "illustration")
            ))

        # 2. Extract Tables with validation against layout grids
        tables_list: List[ExtractedTable] = []
        table_boxes = []
        for tbl_idx, tbl in enumerate(data.get("tables", [])):
            box = self._normalize_box_2d(tbl.get("box_2d"))
            rows = tbl.get("rows", [])
            if not box or not rows or not isinstance(rows, list) or len(rows) < 1:
                continue
            ymin, xmin, ymax, xmax = box
            box_area_pct = ((ymax - ymin) * (xmax - xmin)) / 10000.0

            has_nested_graphic = any(
                ymin <= (gy0 + gy1) / 2.0 <= ymax and xmin <= (gx0 + gx1) / 2.0 <= xmax
                for gy0, gx0, gy1, gx1 in graphic_boxes
            )
            if has_nested_graphic or box_area_pct > 65.0:
                logger.info(f"[AIAnalyzer] Rejecting table {box} (area={box_area_pct:.1f}%, has_graphic={has_nested_graphic}) - treating as layout grid")
                continue

            pad_x = max(6, int(img_w * 0.005))
            pad_y = max(6, int(img_h * 0.005))
            cx0 = max(0, int((xmin / 1000.0) * img_w) - pad_x)
            cy0 = max(0, int((ymin / 1000.0) * img_h) - pad_y)
            cx1 = min(img_w, int((xmax / 1000.0) * img_w) + pad_x)
            cy1 = min(img_h, int((ymax / 1000.0) * img_h) + pad_y)

            pdf_x0 = (cx0 / img_w) * page.width
            pdf_y0 = (cy0 / img_h) * page.height
            pdf_x1 = (cx1 / img_w) * page.width
            pdf_y1 = (cy1 / img_h) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            if conversion_mode == "visual":
                # In Visual mode: crop the ENTIRE table as a high-fidelity image!
                # NEVER create a native PowerPoint table with editable text in visual mode!
                if (cx1 - cx0) >= 10 and (cy1 - cy0) >= 10:
                    try:
                        crop = pil_img.crop((cx0, cy0, cx1, cy1))
                        crop_path = temp_dir / f"p{page.page_num}_tblimg_{tbl_idx}.png"
                        crop.save(str(crop_path), "PNG")
                        cropped_images.append(ExtractedImage(
                            id=len(cropped_images),
                            bbox=elem_bbox,
                            width=cx1 - cx0,
                            height=cy1 - cy0,
                            format="png",
                            temp_path=str(crop_path),
                            name=tbl.get("name", f"Table {tbl_idx + 1}"),
                            element_type="table"
                        ))
                    except Exception as tbl_crop_err:
                        logger.warning(f"Failed to crop table image: {tbl_crop_err}")
            else:
                # In Editable mode: create native PowerPoint table
                header_bg = self._parse_hex_color(tbl.get("header_bg_hex"))
                border_rgb = self._parse_hex_color(tbl.get("border_hex")) or (148, 163, 184)
                tables_list.append(ExtractedTable(
                    id=tbl_idx,
                    bbox=elem_bbox,
                    rows=rows,
                    header_row=bool(tbl.get("has_header_row", True)),
                    header_bg_rgb=header_bg,
                    border_rgb=border_rgb
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

            raw_text_val = t.get("text", "").strip()
            if not raw_text_val:
                continue

            # In visual mode, only skip minor diagram labels (<= 15 chars) whose center is completely inside a graphic.
            # Never skip substantive text paragraphs, definitions, or bullet points!
            if conversion_mode == "visual" and len(raw_text_val) <= 15 and self._is_inside_table(box, graphic_boxes):
                logger.info(f"[AIAnalyzer] Skipping minor graphic label '{raw_text_val}' in visual mode - already rendered inside graphic.")
                continue

            ymin, xmin, ymax, xmax = box

            # Generous safety padding so letters, chemical symbols, bullets, and subscripts are NEVER clipped
            pad_x = max(24, int(img_w * 0.016))
            pad_y = max(10, int(img_h * 0.008))
            cx0 = max(0, int((xmin / 1000.0) * img_w) - pad_x)
            cy0 = max(0, int((ymin / 1000.0) * img_h) - pad_y)
            cx1 = min(img_w, int((xmax / 1000.0) * img_w) + pad_x)
            cy1 = min(img_h, int((ymax / 1000.0) * img_h) + pad_y)

            # Snap text boundary outward to whitespace so bullet characters and edge letters are completely included
            cx0, cy0, cx1, cy1 = self._snap_bbox_to_whitespace(
                pil_img, cx0, cy0, cx1, cy1, page.background_color,
                max_expand_x=int(img_w * 0.035), max_expand_y=int(img_h * 0.02)
            )

            # Map slide bbox to exact cropped image pixels
            pdf_x0 = (cx0 / img_w) * page.width
            pdf_y0 = (cy0 / img_h) * page.height
            pdf_x1 = (cx1 / img_w) * page.width
            pdf_y1 = (cy1 / img_h) * page.height
            elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            role = t.get("role", "body")
            color_hex = t.get("color_hex", "#1e293b")
            color_rgb = self._parse_hex_color(color_hex) or (30, 41, 59)
            bg_hex = t.get("background_hex")
            bg_rgb = self._parse_hex_color(bg_hex) if bg_hex else None
            font_size = float(t.get("font_size_pt", 14.0))
            is_bold = bool(t.get("bold", False)) or (role in {"title", "heading", "badge"})
            is_italic = bool(t.get("italic", False))

            if conversion_mode == "visual":
                if (cx1 - cx0) >= 10 and (cy1 - cy0) >= 10:
                    crop = pil_img.crop((cx0, cy0, cx1, cy1))
                    crop = self._make_transparent_background(crop, page.background_color)
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
                detected_font = str(t.get("font_family") or "Segoe UI").strip()
                span = TextBlockSpan(
                    text=line_str.strip(),
                    font=detected_font,
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

        page.shapes = []
        page.tables = [] if conversion_mode == "visual" else tables_list
        page.images = cropped_images
        page.text_blocks = [] if conversion_mode == "visual" else text_blocks
        page.vision_decomposed = True

        logger.info(
            f"[AIAnalyzer] Page {page.page_num}: mode={conversion_mode}, "
            f"{len(cropped_images)} pictures, {len(tables_list)} tables, {len(text_blocks)} text blocks"
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

            if conversion_mode == "visual":
                pad_x = max(16, int(img_w * 0.012))
                pad_y = max(12, int(img_h * 0.010))
                cx0 = max(0, int((xmin / 1000.0) * img_w) - pad_x)
                cy0 = max(0, int((ymin / 1000.0) * img_h) - pad_y)
                cx1 = min(img_w, int((xmax / 1000.0) * img_w) + pad_x)
                cy1 = min(img_h, int((ymax / 1000.0) * img_h) + pad_y)

                # Snap boundaries outward to whitespace
                cx0, cy0, cx1, cy1 = self._snap_bbox_to_whitespace(
                    pil_img, cx0, cy0, cx1, cy1, page.background_color,
                    max_expand_x=int(img_w * 0.04), max_expand_y=int(img_h * 0.025)
                )

                if (cx1 - cx0) < 10 or (cy1 - cy0) < 10:
                    continue

                pdf_x0 = (cx0 / img_w) * page.width
                pdf_y0 = (cy0 / img_h) * page.height
                pdf_x1 = (cx1 / img_w) * page.width
                pdf_y1 = (cy1 / img_h) * page.height
                elem_bbox = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

                try:
                    crop = pil_img.crop((cx0, cy0, cx1, cy1))
                    crop = self._make_transparent_background(crop, page.background_color)
                    crop_path = temp_dir / f"p{page.page_num}_custom_{idx}.png"
                    crop.save(str(crop_path), "PNG")
                except Exception as crop_err:
                    logger.warning(f"[AIAnalyzer] Failed to crop custom visual element {idx}: {crop_err}")
                    continue

                elem_name = el.get("name") or f"Picture Layer {idx + 1}"
                cropped_images.append(ExtractedImage(
                    id=len(cropped_images),
                    bbox=elem_bbox,
                    width=cx1 - cx0,
                    height=cy1 - cy0,
                    format="png",
                    temp_path=str(crop_path),
                    name=elem_name,
                    element_type="visual_region"
                ))
                continue

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

            try:
                crop = pil_img.crop((cx0, cy0, cx1, cy1))
                crop_path = temp_dir / f"p{page.page_num}_custom_{idx}.png"
                crop.save(str(crop_path), "PNG")
            except Exception as crop_err:
                logger.warning(f"[AIAnalyzer] Failed to crop custom element {idx}: {crop_err}")
                continue

            # In editable mode: check if this element is a table
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
                id=len(cropped_images),
                bbox=elem_bbox,
                width=cx1 - cx0,
                height=cy1 - cy0,
                format="png",
                temp_path=str(crop_path),
                name=elem_name,
                element_type=elem_type
            ))

        page.shapes = []
        page.images = cropped_images
        page.text_blocks = [] if conversion_mode == "visual" else text_blocks
        page.tables = [] if conversion_mode == "visual" else tables_list
        page.vision_decomposed = True

        logger.info(
            f"[AIAnalyzer] Page {page.page_num} custom processed (mode={conversion_mode}): "
            f"{len(cropped_images)} pictures, {len(page.text_blocks)} text boxes, {len(page.tables)} tables"
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
   - "font_family": Standard PowerPoint font ("Comic Neue", "Calibri", "Arial", "Segoe UI", "Century Gothic", "Georgia")
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
            raw = raw[start:end + 1]
        # Strip illegal trailing commas before closing brackets or braces (e.g. [1, 2,] or {"a": 1,})
        prev = ""
        while prev != raw:
            prev = raw
            raw = re.sub(r",\s*([\]}])", r"\g<1>", raw)
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
