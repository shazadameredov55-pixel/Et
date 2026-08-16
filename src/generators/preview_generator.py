"""
Preview image generator. Implements src.core.interfaces.ProductGenerator.

Produces a PNG "cover/dashboard" preview that reflects the ACTUAL sheets,
features, and design profile of the product — not a generic stock image
and not a feature the product doesn't have (requirement #4: no fake
screenshots). This is a rendered mockup built with Pillow, not a
screenshot of the real Excel file (rendering an actual xlsx screenshot
would require a spreadsheet engine we don't have on a GitHub Actions
runner), but every piece of text on it is pulled directly from the
ProductSpec/blueprint, so it can never claim a feature the workbook
doesn't have.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from src.core.interfaces import ProductGenerator, GenerationResult, GeneratedFile
from src.core.models import ProductSpec, DesignProfile
from src.generators.blueprints import get_blueprint, ProductBlueprint

logger = logging.getLogger(__name__)

_WIDTH, _HEIGHT = 1600, 1000  # matches common digital-product marketplace preview ratio


class PreviewIntegrityError(Exception):
    """Raised when a generated preview image fails a basic integrity check."""


class PreviewGenerator(ProductGenerator):
    output_type = "png"

    def generate(self, product_spec: ProductSpec, design_profile: DesignProfile, output_dir: str) -> GenerationResult:
        try:
            blueprint = get_blueprint(product_spec.niche)
        except KeyError as e:
            logger.error("Preview generation failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            os.makedirs(output_dir, exist_ok=True)
            file_path = os.path.join(output_dir, "preview.png")

            image = self._render(product_spec, blueprint, design_profile)
            image.save(file_path, format="PNG")

        except Exception as e:  # noqa: BLE001
            logger.exception("Preview generation raised an unexpected error")
            return GenerationResult(success=False, files=[], error=str(e))

        try:
            self._verify_integrity(file_path)
        except PreviewIntegrityError as e:
            logger.error("Preview integrity check failed: %s", e)
            return GenerationResult(success=False, files=[], error=str(e))

        return GenerationResult(
            success=True,
            files=[
                GeneratedFile(
                    file_path=file_path,
                    file_type="png",
                    description=f"{blueprint.display_name} preview image",
                )
            ],
        )

    # ------------------------------------------------------------------

    def _render(self, spec: ProductSpec, blueprint: ProductBlueprint, design: DesignProfile) -> Image.Image:
        header_fill = _hex(design.table_design.get("header_fill", "1F2937"))
        accent = _hex(design.table_design.get("header_font_color", "FFFFFF"))
        bg = (248, 250, 252)

        img = Image.new("RGB", (_WIDTH, _HEIGHT), bg)
        draw = ImageDraw.Draw(img)

        font_title = _load_font(size=54, bold=True)
        font_subtitle = _load_font(size=26, bold=False)
        font_section = _load_font(size=28, bold=True)
        font_body = _load_font(size=22, bold=False)
        font_small = _load_font(size=18, bold=False)

        # Top banner using the design profile's header color, like the
        # workbook's own header styling — a visual echo of the real file.
        draw.rectangle([(0, 0), (_WIDTH, 220)], fill=header_fill)
        title = spec.title or blueprint.display_name
        draw.text((60, 60), title, font=font_title, fill=accent)
        target = (spec.target_customer or blueprint.default_target_customer).replace("_", " ").title()
        draw.text((60, 140), f"For {target}", font=font_subtitle, fill=accent)

        # Sheet list — pulled directly from the blueprint, so the preview
        # can never advertise a sheet the workbook doesn't actually have.
        y = 260
        draw.text((60, y), "What's Inside", font=font_section, fill=(31, 41, 55))
        y += 50
        for sheet in blueprint.sheets:
            draw.ellipse([(64, y + 10), (76, y + 22)], fill=header_fill)
            draw.text((90, y), sheet.title, font=font_body, fill=(55, 65, 81))
            y += 40

        # Feature list from the actual ProductSpec (falls back to the
        # blueprint defaults only if the strategist hasn't set any yet).
        features = spec.core_features or blueprint.default_features
        x2 = _WIDTH // 2 + 40
        y2 = 260
        draw.text((x2, y2), "Key Features", font=font_section, fill=(31, 41, 55))
        y2 += 50
        for feature in features[:8]:
            draw.ellipse([(x2 + 4, y2 + 10), (x2 + 16, y2 + 22)], fill=(16, 185, 129))
            draw.text((x2 + 30, y2), feature, font=font_body, fill=(55, 65, 81))
            y2 += 40

        # Footer with format badges — only formats actually produced.
        footer_y = _HEIGHT - 90
        draw.rectangle([(0, footer_y), (_WIDTH, _HEIGHT)], fill=(31, 41, 55))
        formats_text = "  •  ".join(f.upper() for f in spec.file_formats)
        draw.text((60, footer_y + 28), f"Includes: {formats_text}", font=font_small, fill=(229, 231, 235))

        return img

    def _verify_integrity(self, file_path: str) -> None:
        try:
            with Image.open(file_path) as img:
                img.verify()
        except Exception as e:
            raise PreviewIntegrityError(f"Preview image could not be verified: {e}") from e

        with Image.open(file_path) as img:
            if img.size != (_WIDTH, _HEIGHT):
                raise PreviewIntegrityError(
                    f"Unexpected preview dimensions: {img.size}, expected {(_WIDTH, _HEIGHT)}"
                )
            if img.format != "PNG":
                raise PreviewIntegrityError(f"Unexpected preview format: {img.format}")


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _load_font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
    """Load a real TrueType font if one is available on the system, else
    fall back to Pillow's built-in bitmap font (still valid, just less
    polished) rather than raising — a missing font file must never break
    generation."""
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold
        else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    logger.warning("No TrueType font found on system; falling back to Pillow's default bitmap font")
    return ImageFont.load_default()
