from typing import Tuple, Dict, Any
from pptx.util import Inches, Pt

class CoordinateMapper:
    """
    Handles translation and scaling of PDF coordinates (points)
    to PowerPoint slide dimensions (Inches / Pt).
    """

    @staticmethod
    def calculate_slide_dimensions(
        pdf_width: float,
        pdf_height: float,
        preferred_ratio: str = "16:9"
    ) -> Tuple[float, float]:
        """
        Determines target PowerPoint slide width and height in inches.
        Returns: (width_inches, height_inches)
        """
        pdf_aspect = pdf_width / max(pdf_height, 1.0)

        if preferred_ratio == "16:9":
            return (13.333, 7.5)
        elif preferred_ratio == "4:3":
            return (10.0, 7.5)
        elif preferred_ratio == "auto":
            # If portrait document (e.g. A4 / Letter)
            if pdf_aspect < 0.9:
                # Target standard 8.5 x 11 portrait or scaled
                target_width = 8.5
                target_height = target_width / pdf_aspect
                return (target_width, target_height)
            elif pdf_aspect >= 1.55:
                # Close to 16:9
                return (13.333, 7.5)
            else:
                # Close to 4:3
                return (10.0, 7.5)
        else:
            return (13.333, 7.5)

    def __init__(self, pdf_width: float, pdf_height: float, slide_width_in: float, slide_height_in: float):
        self.pdf_width = max(pdf_width, 1.0)
        self.pdf_height = max(pdf_height, 1.0)
        self.slide_width_in = slide_width_in
        self.slide_height_in = slide_height_in

        # Slide dimensions in points (72 points = 1 inch)
        self.slide_width_pt = slide_width_in * 72.0
        self.slide_height_pt = slide_height_in * 72.0

        # Scaling multipliers from PDF points to Slide points
        self.scale_x = self.slide_width_pt / self.pdf_width
        self.scale_y = self.slide_height_pt / self.pdf_height

    def map_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        width_buffer_pct: float = 0.05
    ) -> Tuple[Any, Any, Any, Any]:
        """
        Maps a PDF bounding box (x0, y0, x1, y1) to pptx (left, top, width, height) in Inches.
        Includes a small width buffer (default 5%) to prevent PowerPoint font metrics
        from causing unexpected word wraps.
        """
        x0, y0, x1, y1 = bbox

        # Scaled values in points
        left_pt = max(0.0, x0 * self.scale_x)
        top_pt = max(0.0, y0 * self.scale_y)
        raw_width_pt = max(4.0, (x1 - x0) * self.scale_x)
        raw_height_pt = max(4.0, (y1 - y0) * self.scale_y)

        # Apply subtle width buffer to accommodate slight text rendering differences
        width_pt = raw_width_pt * (1.0 + width_buffer_pct)

        # Clamp within slide bounds
        left_pt = min(left_pt, self.slide_width_pt - 10.0)
        top_pt = min(top_pt, self.slide_height_pt - 10.0)
        width_pt = min(width_pt, self.slide_width_pt - left_pt)
        height_pt = min(raw_height_pt, self.slide_height_pt - top_pt)

        # Return as Inches for python-pptx
        return (
            Inches(left_pt / 72.0),
            Inches(top_pt / 72.0),
            Inches(width_pt / 72.0),
            Inches(height_pt / 72.0)
        )

    def map_font_size(self, original_size_pt: float) -> float:
        """
        Scales font size proportionally to vertical slide scaling.
        Clamped between 6.0 and 80.0 pt.
        """
        scaled = original_size_pt * self.scale_y
        return max(6.0, min(80.0, round(scaled, 1)))
