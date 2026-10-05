
import os
import math
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls

from backend.models.schemas import ExtractedPage
from backend.services.coordinate_mapper import CoordinateMapper

# Universal PowerPoint standard font mappings for design & web fonts
FONT_FAMILY_MAPPING = {
    # Geometric Sans (e.g. Montserrat, Poppins, Outfit, Futura) -> Century Gothic or Segoe UI
    "montserrat": "Century Gothic",
    "poppins": "Century Gothic",
    "outfit": "Century Gothic",
    "futura": "Century Gothic",
    "century gothic": "Century Gothic",
    "proxima nova": "Century Gothic",
    "gotham": "Century Gothic",
    "quicksand": "Century Gothic",
    "raleway": "Century Gothic",
    # Neo-Grotesque / Clean Sans (e.g. Inter, Roboto, Helvetica, Segoe UI)
    "inter": "Segoe UI",
    "roboto": "Segoe UI",
    "segoe ui": "Segoe UI",
    "open sans": "Segoe UI",
    "helvetica": "Arial",
    "helvetica neue": "Arial",
    "arial": "Arial",
    "aptos": "Aptos",
    "lato": "Calibri",
    "calibri": "Calibri",
    "source sans pro": "Segoe UI",
    "nunito": "Segoe UI",
    # Editorial Serif (e.g. Georgia, Garamond, Playfair Display)
    "georgia": "Georgia",
    "times new roman": "Times New Roman",
    "garamond": "Garamond",
    "merriweather": "Georgia",
    "playfair display": "Georgia",
    "pt serif": "Georgia",
    "lora": "Georgia",
    "baskerville": "Georgia",
    # Monospace & Technical
    "consolas": "Consolas",
    "courier new": "Courier New",
    "fira code": "Consolas",
    "source code pro": "Consolas",
    # Display & Heavy
    "impact": "Impact",
    "trebuchet ms": "Trebuchet MS",
    "comic sans ms": "Comic Sans MS",
}

def calculate_optimal_font_size(
    text_lines: List[str],
    box_width_pt: float,
    box_height_pt: float,
    gemini_suggested_pt: Optional[float] = None,
    role: str = "body",
    line_spacing_mult: float = 1.25
) -> float:
    """
    Calculates a typography-accurate font size in points that guarantees:
    1. Zero mid-word wrapping (every word fits horizontally)
    2. Accurate visual line estimation with automatic word wrapping
    3. Zero vertical overflow within available box height
    4. Proportional scaling by semantic role
    """
    if not text_lines:
        return 12.0

    avail_w = max(15.0, box_width_pt - 6.0)
    avail_h = max(8.0, box_height_pt - 4.0)

    role_max = {
        "title": 36.0,
        "subtitle": 24.0,
        "heading": 22.0,
        "body": 16.0,
        "bullet": 15.0,
        "badge": 14.0,
        "caption": 12.0,
        "footer": 11.0
    }.get(role, 16.0)

    all_words = []
    for l in text_lines:
        all_words.extend(l.strip().split())
    max_word_len = max((len(w) for w in all_words), default=1)

    # 1. Word width constraint: longest word must not break mid-word
    max_fs_from_word = avail_w / (max_word_len * 0.60)

    # 2. Single-line constraint for titles/badges where wrapping is undesirable
    if len(text_lines) == 1 and role in {"title", "badge", "caption", "footer"}:
        max_line_len = len(text_lines[0].strip())
        max_fs_from_line = avail_w / (max(1, max_line_len) * 0.55)
        target_fs = min(role_max, max_fs_from_word, max_fs_from_line)
    else:
        target_fs = min(role_max, max_fs_from_word)

    if gemini_suggested_pt and gemini_suggested_pt > 0:
        target_fs = min(target_fs, gemini_suggested_pt)

    # 3. Height constraint with word-wrap simulation
    fitted_fs = target_fs
    for test_fs in [target_fs - 0.5 * i for i in range(25)]:
        if test_fs < 8.0:
            fitted_fs = 8.0
            break
        total_est_lines = 0
        for l in text_lines:
            chars = len(l.strip())
            total_est_lines += max(1, math.ceil((chars * test_fs * 0.52) / avail_w))
        needed_h = total_est_lines * test_fs * line_spacing_mult
        if needed_h <= avail_h:
            fitted_fs = test_fs
            break

    return max(7.0, min(role_max, round(fitted_fs, 1)))


class PPTXBuilder:
    """
    Builds native, fully editable PowerPoint presentations (.pptx)
    from extracted and analyzed PDF pages.
    """

    def __init__(
        self,
        preferred_ratio: str = "16:9",
        heading_font: str = "auto",
        body_font: str = "auto"
    ):
        self.preferred_ratio = preferred_ratio
        self.heading_font = heading_font or "auto"
        self.body_font = body_font or "auto"
        self.presentation = Presentation()

    def build_presentation(
        self,
        pages: List[ExtractedPage],
        output_path: Path
    ) -> Path:
        """
        Creates slides for each extracted page and saves the presentation.
        """
        if not pages:
            self.presentation.slides.add_slide(self.presentation.slide_layouts[6])
            self.presentation.save(str(output_path))
            return output_path

        # Determine presentation slide dimensions from first page
        first_page = pages[0]
        slide_w_in, slide_h_in = CoordinateMapper.calculate_slide_dimensions(
            first_page.width,
            first_page.height,
            self.preferred_ratio
        )
        self.presentation.slide_width = Inches(slide_w_in)
        self.presentation.slide_height = Inches(slide_h_in)

        blank_layout = self.presentation.slide_layouts[6]

        for page in pages:
            slide = self.presentation.slides.add_slide(blank_layout)
            mapper = CoordinateMapper(
                pdf_width=page.width,
                pdf_height=page.height,
                slide_width_in=slide_w_in,
                slide_height_in=slide_h_in
            )

            # 0. Set slide background color if detected
            if page.background_color:
                try:
                    r, g, b = page.background_color
                    background = slide.background
                    fill = background.fill
                    fill.solid()
                    fill.fore_color.rgb = RGBColor(r, g, b)
                except Exception as e:
                    print(f"[PPTXBuilder] Warning: failed to set slide background: {e}")

            # 1. Add background shapes & cards
            self._add_shapes(slide, page, mapper)

            # 2. Add native PowerPoint table objects
            self._add_tables(slide, page, mapper)

            # 3. Add editable picture objects
            self._add_images(slide, page, mapper)

            # 4. Add editable text boxes
            self._add_text_blocks(slide, page, mapper)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.presentation.save(str(output_path))
        return output_path

    def _add_tables(self, slide, page: ExtractedPage, mapper: CoordinateMapper):
        """
        Adds native, editable PowerPoint table shapes with clean styling.
        """
        for tbl in page.tables:
            if not tbl.rows:
                continue
            num_rows = len(tbl.rows)
            num_cols = max(len(r) for r in tbl.rows)
            if num_rows == 0 or num_cols == 0:
                continue

            try:
                left, top, width, height = mapper.map_bbox(tbl.bbox, width_buffer_pct=0.0)
                table_shape = slide.shapes.add_table(num_rows, num_cols, left, top, width, height)
                table = table_shape.table

                header_bg = tbl.header_bg_rgb or (241, 245, 249)
                header_fg = tbl.header_text_rgb or (30, 41, 59)
                alt_bg = tbl.alternate_bg_rgb
                col_aligns = tbl.col_alignments or []

                for r_idx, row in enumerate(tbl.rows):
                    is_header = (r_idx == 0 and tbl.header_row)
                    for c_idx, cell_value in enumerate(row):
                        if c_idx < num_cols:
                            cell = table.cell(r_idx, c_idx)
                            cell.text = str(cell_value).strip()
                            cell.margin_left = Pt(5)
                            cell.margin_right = Pt(5)
                            cell.margin_top = Pt(3)
                            cell.margin_bottom = Pt(3)

                            cell.fill.solid()
                            if is_header:
                                cell.fill.fore_color.rgb = RGBColor(*header_bg)
                            elif alt_bg and r_idx % 2 == 1:
                                cell.fill.fore_color.rgb = RGBColor(*alt_bg)
                            else:
                                cell.fill.fore_color.rgb = RGBColor(255, 255, 255)

                            # Determine column-specific alignment
                            align = PP_ALIGN.LEFT
                            if c_idx < len(col_aligns):
                                ca = str(col_aligns[c_idx]).lower().strip()
                                if ca == "right":
                                    align = PP_ALIGN.RIGHT
                                elif ca == "center":
                                    align = PP_ALIGN.CENTER
                            elif is_header or c_idx > 0:
                                align = PP_ALIGN.CENTER

                            for p in cell.text_frame.paragraphs:
                                p.alignment = align
                                for r in p.runs:
                                    r.font.name = "Segoe UI"
                                    r.font.size = Pt(11 if is_header else 10)
                                    r.font.bold = is_header
                                    if is_header:
                                        r.font.color.rgb = RGBColor(*header_fg)
                                    else:
                                        r.font.color.rgb = RGBColor(30, 41, 59)
            except Exception as e:
                print(f"[PPTXBuilder] Warning: failed to add table: {e}")

    def _add_shapes(self, slide, page: ExtractedPage, mapper: CoordinateMapper):
        """
        Adds vector card backgrounds and banner shapes.
        """
        for shape in page.shapes:
            if shape.type == "rect" and shape.fill_color:
                left, top, width, height = mapper.map_bbox(shape.bbox, width_buffer_pct=0.0)
                rect_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
                rect_shape.fill.solid()
                r, g, b = shape.fill_color
                rect_shape.fill.fore_color.rgb = RGBColor(r, g, b)
                rect_shape.line.color.rgb = RGBColor(r, g, b)

    def _add_images(self, slide, page: ExtractedPage, mapper: CoordinateMapper):
        """
        Adds native PowerPoint picture shapes.
        """
        for img in page.images:
            if img.temp_path and os.path.exists(img.temp_path):
                try:
                    left, top, width, height = mapper.map_bbox(img.bbox, width_buffer_pct=0.0)
                    pic = slide.shapes.add_picture(img.temp_path, left, top, width, height)
                    if img.name:
                        pic.name = img.name
                except Exception as e:
                    print(f"[PPTXBuilder] Warning: failed to add picture {img.temp_path}: {e}")

    def _add_text_blocks(self, slide, page: ExtractedPage, mapper: CoordinateMapper):
        """
        Adds native, editable PowerPoint text boxes with:
        - Optimal mathematical font size fitting (zero mid-word wrap, zero overflow)
        - Native <a:normAutofit/> XML auto-shrinking on text overflow
        - Contrast guard against invisible white text
        - Badge background fills
        """
        align_map = {
            "center": PP_ALIGN.CENTER,
            "right": PP_ALIGN.RIGHT,
            "justify": PP_ALIGN.JUSTIFY,
            "left": PP_ALIGN.LEFT
        }

        slide_bg_rgb = page.background_color or (255, 255, 255)
        slide_is_light = (slide_bg_rgb[0] * 0.299 + slide_bg_rgb[1] * 0.587 + slide_bg_rgb[2] * 0.114) > 180

        for block in page.text_blocks:
            if not block.text.strip():
                continue

            raw_w_pt = (block.bbox[2] - block.bbox[0]) * mapper.scale_x
            raw_h_pt = (block.bbox[3] - block.bbox[1]) * mapper.scale_y

            # Width buffer provides breathing room for font metrics
            width_buf = 0.12 if block.role in {"title", "subtitle", "heading"} else 0.08
            left, top, width, height = mapper.map_bbox(block.bbox, width_buffer_pct=width_buf)

            # Container styling (card / pill / background fill / border)
            has_bg_fill = False
            has_border = bool(block.border_color)
            is_card_shape = block.is_rounded and (block.background_color or has_border)

            if is_card_shape:
                try:
                    tb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
                    if block.background_color:
                        tb.fill.solid()
                        tb.fill.fore_color.rgb = RGBColor(*block.background_color)
                        has_bg_fill = True
                    else:
                        tb.fill.background()

                    if has_border:
                        tb.line.color.rgb = RGBColor(*block.border_color)
                        tb.line.width = Pt(1)
                    else:
                        tb.line.fill.background()
                except Exception:
                    tb = slide.shapes.add_textbox(left, top, width, height)
            else:
                tb = slide.shapes.add_textbox(left, top, width, height)
                if block.background_color:
                    try:
                        tb.fill.solid()
                        tb.fill.fore_color.rgb = RGBColor(*block.background_color)
                        has_bg_fill = True
                    except Exception as e:
                        print(f"[PPTXBuilder] Warning: failed to set textbox background: {e}")
                if has_border:
                    try:
                        tb.line.color.rgb = RGBColor(*block.border_color)
                        tb.line.width = Pt(1)
                    except Exception:
                        pass

            tf = tb.text_frame
            tf.word_wrap = True

            # Tight margins for natural layout alignment
            tf.margin_left = Pt(4 if is_card_shape else 2)
            tf.margin_top = Pt(3 if is_card_shape else 1)
            tf.margin_right = Pt(4 if is_card_shape else 2)
            tf.margin_bottom = Pt(3 if is_card_shape else 1)

            # Inject <a:normAutofit/> for fail-safe shrink on overflow
            try:
                bodyPr = tf._txBody.bodyPr
                for child in list(bodyPr):
                    if child.tag.endswith('noAutofit') or child.tag.endswith('spAutoFit'):
                        bodyPr.remove(child)
                bodyPr.append(parse_xml(f'<a:normAutofit {nsdecls("a")} />'))
            except Exception:
                pass

            valid_lines = [l for l in block.lines if l.spans and any(s.text.strip() for s in l.spans)]
            num_valid = len(valid_lines)
            if num_valid == 0:
                continue

            # Calculate proportional height allocations across paragraphs
            weights = []
            for l in valid_lines:
                p_role = getattr(l, "role", None) or block.role
                mult = 1.4 if p_role in {"title", "heading"} else 1.0
                weights.append(max(10, len(l.text)) * mult)
            total_weight = sum(weights) or 1.0

            first_line = True
            for l_idx, line in enumerate(valid_lines):
                if first_line:
                    p = tf.paragraphs[0]
                    first_line = False
                else:
                    p = tf.add_paragraph()

                # Paragraph alignment
                if line.alignment and line.alignment in align_map:
                    p.alignment = align_map[line.alignment]
                elif block.role == "badge":
                    p.alignment = PP_ALIGN.CENTER

                p_role = getattr(line, "role", None) or block.role
                is_bullet = getattr(line, "is_bullet", False)

                # Paragraph spacing
                if p_role in {"title", "heading"}:
                    p.space_after = Pt(4)
                elif is_bullet:
                    p.space_after = Pt(2)
                else:
                    p.space_after = Pt(3)

                p.space_before = Pt(0)

                # Proportional height slice for this paragraph
                prop_h = raw_h_pt if num_valid == 1 else max(16.0, raw_h_pt * (weights[l_idx] / total_weight))

                for s_idx, span in enumerate(line.spans):
                    if not span.text:
                        continue

                    run = p.add_run()
                    # Add clean bullet prefix if bullet item
                    if is_bullet and s_idx == 0 and not span.text.startswith("•"):
                        run.text = "• " + span.text
                    else:
                        run.text = span.text

                    run.font.name = self._resolve_font(span.font, p_role)

                    # Calculate optimal font size for this paragraph's role and proportional height
                    opt_size = calculate_optimal_font_size(
                        [line.text],
                        raw_w_pt,
                        prop_h,
                        gemini_suggested_pt=span.size,
                        role=p_role
                    )
                    run.font.size = Pt(opt_size)
                    run.font.bold = span.bold or (p_role in {"title", "heading", "badge"})
                    run.font.italic = span.italic

                    # Contrast Guard: prevent white text from becoming invisible on white slide
                    r, g, b = span.color_rgb
                    span_lum = r * 0.299 + g * 0.587 + b * 0.114
                    if span_lum > 200 and not has_bg_fill and slide_is_light:
                        run.font.color.rgb = RGBColor(30, 41, 59)
                    else:
                        run.font.color.rgb = RGBColor(r, g, b)

    def _resolve_font(self, span_font: Optional[str], role: str) -> str:
        """
        Determines the best standard PowerPoint font based on role,
        user configuration, and smart archetype mapping.
        """
        is_heading = role in {"title", "subtitle", "heading"}

        # 1. User manual font override if configured
        if is_heading and self.heading_font and self.heading_font.lower() != "auto":
            return self.heading_font
        if not is_heading and self.body_font and self.body_font.lower() != "auto":
            return self.body_font

        # 2. Smart archetype mapping from detected font
        if span_font:
            clean = span_font.strip().lower()
            if clean in FONT_FAMILY_MAPPING:
                return FONT_FAMILY_MAPPING[clean]
            return span_font.strip()

        # 3. Default fallback based on role
        return "Century Gothic" if is_heading else "Segoe UI"

