"""
Standalone Instructions PDF generator. Implements ProductGenerator.

The printable.pdf produced by pdf_generator.py already includes an
instructions page as part of the worksheet planner. This generator
produces a SEPARATE, self-contained instructions.pdf — useful for buyers
who only want the digital Excel file and a quick-start guide, without
the full printable planner. Reuses the exact same style/instructions
content builders as pdf_generator.py so the two documents never drift
out of sync with each other.
"""

from __future__ import annotations

import logging
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Spacer

from src.core.interfaces import ProductGenerator, GenerationResult, GeneratedFile
from src.core.models import ProductSpec, DesignProfile
from src.generators.blueprints import get_blueprint
from src.generators.pdf_generator import (
    resolve_fonts, _build_styles, _build_cover_page, _build_instructions_page, PdfIntegrityError,
)

logger = logging.getLogger(__name__)


class InstructionsGenerator(ProductGenerator):
    output_type = "pdf"

    def generate(self, product_spec: ProductSpec, design_profile: DesignProfile, output_dir: str) -> GenerationResult:
        try:
            blueprint = get_blueprint(product_spec.niche)
        except KeyError as e:
            logger.error("Instructions PDF generation failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, "instructions.pdf")

            fonts = resolve_fonts(design_profile)
            styles = _build_styles(fonts)

            story = []
            story.extend(_build_cover_page(product_spec, blueprint, styles))
            story.append(Spacer(1, 0.4 * inch))
            story.extend(_build_instructions_page(product_spec, blueprint, styles))

            doc = SimpleDocTemplate(
                file_path,
                pagesize=letter,
                topMargin=0.75 * inch,
                bottomMargin=0.75 * inch,
                leftMargin=0.75 * inch,
                rightMargin=0.75 * inch,
                title=f"{product_spec.title or blueprint.display_name} — Instructions",
            )
            doc.build(story)

        except Exception as e:  # noqa: BLE001
            logger.exception("Instructions PDF generation raised an unexpected error")
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            self._verify_integrity(file_path)
        except PdfIntegrityError as e:
            logger.error("Instructions PDF integrity check failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        return GenerationResult(
            success=True,
            files=[
                GeneratedFile(
                    file_path=file_path,
                    file_type="pdf",
                    description=f"{blueprint.display_name} quick-start instructions",
                )
            ],
        )

    def _verify_integrity(self, file_path: str) -> None:
        from pypdf import PdfReader

        try:
            reader = PdfReader(file_path)
        except Exception as e:
            raise PdfIntegrityError(f"Instructions PDF could not be reopened: {e}") from e

        if len(reader.pages) < 1:
            raise PdfIntegrityError("Instructions PDF has zero pages")
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if not text:
                raise PdfIntegrityError(f"Instructions PDF page {i + 1} is blank")
