"""
PDF product generator. Implements src.core.interfaces.ProductGenerator.

Produces a printable companion PDF for the same ProductSpec/DesignProfile
the XLSX generator used: a cover page, an instructions page, and one
printable worksheet page per data-entry sheet in the blueprint (header row
+ blank ruled rows for pen-and-paper use). This is deliberately NOT a
dump of the Excel content — it is a distinct, print-optimized artifact,
which is also why it varies structurally by niche exactly like the XLSX
does (same blueprint, different medium).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from src.core.interfaces import ProductGenerator, GenerationResult, GeneratedFile
from src.core.models import ProductSpec, DesignProfile
from src.generators.blueprints import get_blueprint, ProductBlueprint, SheetSpec

logger = logging.getLogger(__name__)


class PdfIntegrityError(Exception):
    """Raised when a generated PDF fails a basic integrity check (cannot
    be reopened, has zero pages, or contains a blank page)."""


# reportlab's Base-14 fonts are the only fonts guaranteed available
# without embedding a font file. Design-profile font names (Calibri,
# Segoe UI, Georgia, ...) are mapped to the nearest of these rather than
# assumed to exist, so PDFs never silently fall back to a default font
# openpyxl-style tools would tolerate but reportlab will not resolve.
_FONT_MAP: dict[str, tuple[str, str]] = {
    # design profile heading_font -> (regular, bold) reportlab font names
    "Calibri": ("Helvetica", "Helvetica-Bold"),
    "Segoe UI": ("Helvetica", "Helvetica-Bold"),
    "Arial": ("Helvetica", "Helvetica-Bold"),
    "Verdana": ("Helvetica", "Helvetica-Bold"),
    "Georgia": ("Times-Roman", "Times-Bold"),
    "Times New Roman": ("Times-Roman", "Times-Bold"),
}
_DEFAULT_FONTS = ("Helvetica", "Helvetica-Bold")


def resolve_fonts(design_profile: DesignProfile) -> tuple[str, str]:
    """Public helper so other generators (instructions_generator.py) can
    resolve the same font mapping without duplicating the table."""
    return _FONT_MAP.get(design_profile.typography.get("heading_font", ""), _DEFAULT_FONTS)


class PdfGenerator(ProductGenerator):
    output_type = "pdf"

    def generate(self, product_spec: ProductSpec, design_profile: DesignProfile, output_dir: str) -> GenerationResult:
        try:
            blueprint = get_blueprint(product_spec.niche)
        except KeyError as e:
            logger.error("PDF generation failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, "printable.pdf")

            fonts = resolve_fonts(design_profile)
            styles = _build_styles(fonts)

            story: list[Any] = []
            story.extend(_build_cover_page(product_spec, blueprint, styles))
            story.append(PageBreak())
            story.extend(_build_instructions_page(product_spec, blueprint, styles))

            printable_sheets = [
                s for s in blueprint.sheets
                if s.sheet_key not in ("instructions", "dashboard") and s.columns
            ]
            for sheet_spec in printable_sheets:
                story.append(PageBreak())
                story.extend(_build_worksheet_page(sheet_spec, styles, design_profile))

            doc = SimpleDocTemplate(
                file_path,
                pagesize=letter,
                topMargin=0.75 * inch,
                bottomMargin=0.75 * inch,
                leftMargin=0.75 * inch,
                rightMargin=0.75 * inch,
                title=product_spec.title or blueprint.display_name,
            )
            doc.build(story)

        except Exception as e:  # noqa: BLE001
            logger.exception("PDF generation raised an unexpected error")
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            expected_pages = 2 + len(printable_sheets)  # cover + instructions + 1 per worksheet
            self._verify_integrity(file_path, expected_pages)
        except PdfIntegrityError as e:
            logger.error("PDF integrity check failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        return GenerationResult(
            success=True,
            files=[
                GeneratedFile(
                    file_path=file_path,
                    file_type="pdf",
                    description=f"{blueprint.display_name} printable companion PDF",
                )
            ],
        )

    def _verify_integrity(self, file_path: str, expected_pages: int) -> None:
        from pypdf import PdfReader

        try:
            reader = PdfReader(file_path)
        except Exception as e:
            raise PdfIntegrityError(f"PDF could not be reopened: {e}") from e

        actual_pages = len(reader.pages)
        if actual_pages != expected_pages:
            raise PdfIntegrityError(
                f"Expected {expected_pages} pages, got {actual_pages}"
            )

        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if not text:
                raise PdfIntegrityError(f"Page {i + 1} appears to be blank")


def _build_styles(fonts: tuple[str, str]) -> dict[str, ParagraphStyle]:
    regular, bold = fonts
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PdfTitle", parent=base["Title"], fontName=bold, fontSize=22,
            alignment=TA_CENTER, spaceAfter=14,
        ),
        "subtitle": ParagraphStyle(
            "PdfSubtitle", parent=base["Normal"], fontName=regular, fontSize=12,
            alignment=TA_CENTER, textColor=colors.HexColor("#4B5563"), spaceAfter=6,
        ),
        "heading": ParagraphStyle(
            "PdfHeading", parent=base["Heading2"], fontName=bold, fontSize=15,
            spaceAfter=10, spaceBefore=4,
        ),
        "body": ParagraphStyle(
            "PdfBody", parent=base["Normal"], fontName=regular, fontSize=10.5,
            leading=15, alignment=TA_LEFT, spaceAfter=8,
        ),
        "table_header_font": bold,
        "table_body_font": regular,
    }


def _build_cover_page(spec: ProductSpec, blueprint: ProductBlueprint, styles: dict) -> list[Any]:
    title = spec.title or blueprint.display_name
    target = spec.target_customer or blueprint.default_target_customer
    elements: list[Any] = [
        Spacer(1, 1.5 * inch),
        Paragraph(title, styles["title"]),
        Paragraph(f"Printable Companion Planner — for {target.replace('_', ' ')}", styles["subtitle"]),
        Spacer(1, 0.6 * inch),
    ]
    if spec.differentiation:
        elements.append(Paragraph(spec.differentiation, styles["body"]))
    return elements


def _build_instructions_page(spec: ProductSpec, blueprint: ProductBlueprint, styles: dict) -> list[Any]:
    elements: list[Any] = [
        Paragraph("How to Use This Planner", styles["heading"]),
        Paragraph(
            "Print the following pages and fill them in by hand, or use them alongside "
            "the companion spreadsheet for a mixed digital/paper workflow.",
            styles["body"],
        ),
    ]
    # Use the actual product's features when the strategist has set them;
    # only fall back to the blueprint defaults if none were assigned yet.
    # Always sourcing blueprint.default_features here would let the PDF
    # describe features a specific product doesn't actually have.
    features = spec.core_features or blueprint.default_features
    if features:
        elements.append(Paragraph("What's included:", styles["heading"]))
        for feature in features:
            elements.append(Paragraph(f"&bull; {feature}", styles["body"]))
    elements.append(
        Paragraph(
            "This planner is provided for personal budgeting organization only "
            "and does not constitute financial advice.",
            styles["body"],
        )
    )
    return elements


def _build_worksheet_page(sheet_spec: SheetSpec, styles: dict, design_profile: DesignProfile) -> list[Any]:
    header_fill = design_profile.table_design.get("header_fill", "1F2937")
    header_font_color = design_profile.table_design.get("header_font_color", "FFFFFF")

    elements: list[Any] = [Paragraph(sheet_spec.title, styles["heading"])]

    headers = [c.header for c in sheet_spec.columns]
    blank_rows = 18  # generous, print-friendly row count per page
    table_data = [headers] + [["" for _ in headers] for _ in range(blank_rows)]

    col_count = len(headers)
    usable_width = 7.0 * inch  # letter width minus 0.75in margins each side
    col_width = usable_width / col_count

    table = Table(table_data, colWidths=[col_width] * col_count, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{header_fill}")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(f"#{header_font_color}")),
                ("FONTNAME", (0, 0), (-1, 0), styles["table_header_font"]),
                ("FONTNAME", (0, 1), (-1, -1), styles["table_body_font"]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(table)
    return elements
