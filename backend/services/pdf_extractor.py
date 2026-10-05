import io
import os
import re
import base64
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
import pymupdf

from backend.models.schemas import (
    ExtractedImage,
    ExtractedPage,
    PagePreviewItem,
)

class PDFExtractor:
    """
    Renders high-resolution slide images and extracts visual image assets from PDF pages.
    Text OCR is bypassed in favor of direct visual element segmentation.
    """

    @classmethod
    def generate_page_preview(cls, page: pymupdf.Page, dpi: int = 120) -> str:
        """
        Renders a PDF page to a PNG thumbnail and returns as base64 data URL.
        """
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    @classmethod
    def get_document_previews(cls, pdf_path: str, max_pages: int = 60) -> List[PagePreviewItem]:
        """
        Generates thumbnails for all pages in a document.
        """
        previews = []
        with pymupdf.open(pdf_path) as doc:
            total = min(len(doc), max_pages)
            for i in range(total):
                page = doc[i]
                b64 = cls.generate_page_preview(page, dpi=90)
                previews.append(PagePreviewItem(
                    page_num=i + 1,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    thumbnail_base64=b64
                ))
        return previews

    @classmethod
    def extract_page(
        cls,
        doc: pymupdf.Document,
        page_num: int,
        temp_dir: Path
    ) -> ExtractedPage:
        """
        Prepares a page for visual element decomposition by rendering a high-res slide image
        and extracting any embedded raster image objects.
        """
        page_idx = page_num - 1
        page = doc[page_idx]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)

        # 1. Render high-resolution page image (180 DPI for crisp slide graphics & text)
        render_pix = page.get_pixmap(dpi=180)
        render_file = temp_dir / f"p{page_num}_render.png"
        render_pix.save(str(render_file))
        full_render_path = str(render_file)

        # 2. Extract any standalone embedded images
        extracted_images: List[ExtractedImage] = []
        image_list = page.get_images(full=True)
        img_id_counter = 0
        seen_rects = set()

        for img_info in image_list:
            xref = img_info[0]
            rects = page.get_image_rects(xref)
            if not rects:
                continue

            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image.get("image")
                image_ext = base_image.get("ext", "png")

                if not image_bytes:
                    continue

                for r in rects:
                    # Ignore tiny 1x1 tracking pixels
                    if r.width < 10 or r.height < 10:
                        continue

                    # Ignore full-page background images so we don't duplicate the full slide
                    if r.width >= page_width * 0.9 and r.height >= page_height * 0.9:
                        continue

                    rect_key = (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                    if rect_key in seen_rects:
                        continue
                    seen_rects.add(rect_key)

                    img_filename = f"p{page_num}_native_{img_id_counter}.{image_ext}"
                    img_path = temp_dir / img_filename
                    with open(img_path, "wb") as f_out:
                        f_out.write(image_bytes)

                    extracted_images.append(ExtractedImage(
                        id=img_id_counter,
                        bbox=(float(r.x0), float(r.y0), float(r.x1), float(r.y1)),
                        width=int(base_image.get("width", r.width)),
                        height=int(base_image.get("height", r.height)),
                        format=image_ext,
                        temp_path=str(img_path),
                        name=f"Embedded Graphic {img_id_counter + 1}",
                        element_type="illustration"
                    ))
                    img_id_counter += 1
            except Exception as e:
                print(f"[PDFExtractor] Warning: failed to extract native image xref {xref}: {e}")

        # Fallback background image representing the full slide
        fallback_bg_img = ExtractedImage(
            id=9999,
            bbox=(0.0, 0.0, page_width, page_height),
            width=render_pix.width,
            height=render_pix.height,
            format="png",
            temp_path=full_render_path,
            name="Slide Image",
            element_type="slide"
        )

        # Generate thumbnail for preview
        thumb_b64 = cls.generate_page_preview(page, dpi=90)

        return ExtractedPage(
            page_num=page_num,
            width=page_width,
            height=page_height,
            text_blocks=[],
            images=extracted_images,
            shapes=[],
            tables=[],
            background_color=None,
            thumbnail_base64=thumb_b64,
            is_scanned_or_rasterized=True,
            full_render_path=full_render_path,
            fallback_background_image=fallback_bg_img,
            vision_decomposed=False
        )
