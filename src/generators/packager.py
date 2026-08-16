"""
Packager: the final assembly step (requirement #5, #6).

Takes the outputs of XlsxGenerator, PdfGenerator, PreviewGenerator, and
InstructionsGenerator (already run by the caller — packaging does not
generate content itself, it only assembles what exists) plus the listing
text from listing_generator.py, lays them out under
output/<product-slug>/, writes metadata.json + README.txt, and produces
<product-slug>.zip.

Hard rule (requirement #13 / packaging safety): if any expected file is
missing or fails its own integrity check, packaging refuses to produce a
ZIP at all rather than shipping a broken/incomplete product.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass

from src.core.models import ProductSpec, DesignProfile
from src.generators.blueprints import ProductBlueprint

logger = logging.getLogger(__name__)


class PackagingError(Exception):
    """Raised when packaging cannot proceed (missing/invalid input file,
    empty ZIP, etc.). Callers should transition the product to FAILED,
    not silently continue."""


def slugify(text: str) -> str:
    """Safe, filesystem- and URL-friendly slug. Never returns an empty
    string — falls back to 'product' so a pathologically empty title
    can't produce an unusable directory name."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "product"


@dataclass
class PackageResult:
    success: bool
    package_dir: str = ""
    zip_path: str = ""
    error: str = ""


class Packager:
    # Files that MUST be present and non-empty for a package to be valid.
    REQUIRED_FILES = ("product.xlsx", "printable.pdf", "preview.png", "instructions.pdf", "metadata.json", "README.txt", "listing.txt")

    def package(
        self,
        product_spec: ProductSpec,
        design_profile: DesignProfile,
        blueprint: ProductBlueprint,
        source_files: dict[str, str],
        listing_text: str,
        quality_score: float | None,
        opportunity_score: float | None,
        base_output_dir: str,
    ) -> PackageResult:
        """
        source_files: maps a canonical key ("xlsx", "printable_pdf",
        "preview", "instructions_pdf") to the actual file path produced by
        the respective generator. Missing keys are treated as a packaging
        failure — packaging never invents a placeholder file.
        """
        slug = slugify(product_spec.title or blueprint.display_name)
        package_dir = os.path.join(base_output_dir, slug)

        try:
            os.makedirs(package_dir, exist_ok=True)

            self._copy_required(source_files, "xlsx", package_dir, "product.xlsx")
            self._copy_required(source_files, "printable_pdf", package_dir, "printable.pdf")
            self._copy_required(source_files, "preview", package_dir, "preview.png")
            self._copy_required(source_files, "instructions_pdf", package_dir, "instructions.pdf")

            self._write_listing(package_dir, listing_text)
            self._write_metadata(
                package_dir, product_spec, design_profile, blueprint,
                quality_score, opportunity_score,
            )
            self._write_readme(package_dir, product_spec, blueprint)

        except (OSError, PackagingError) as e:
            logger.error("Packaging failed while assembling files: %s", e)
            return PackageResult(success=False, error=str(e))

        try:
            self._verify_package_dir(package_dir)
        except PackagingError as e:
            logger.error("Packaging integrity check failed: %s", e)
            return PackageResult(success=False, error=str(e))

        try:
            zip_path = self._zip_package(package_dir, base_output_dir, slug)
            self._verify_zip(zip_path)
        except (OSError, PackagingError) as e:
            logger.error("ZIP creation/verification failed: %s", e)
            return PackageResult(success=False, error=str(e))

        return PackageResult(success=True, package_dir=package_dir, zip_path=zip_path)

    # ------------------------------------------------------------------

    def _copy_required(self, source_files: dict[str, str], key: str, package_dir: str, dest_name: str) -> None:
        src = source_files.get(key)
        if not src or not os.path.isfile(src):
            raise PackagingError(f"Required source file for '{key}' is missing or does not exist: {src!r}")
        if os.path.getsize(src) == 0:
            raise PackagingError(f"Required source file for '{key}' is empty: {src}")
        shutil.copyfile(src, os.path.join(package_dir, dest_name))

    def _write_listing(self, package_dir: str, listing_text: str) -> None:
        if not listing_text or not listing_text.strip():
            raise PackagingError("Listing text is empty")
        with open(os.path.join(package_dir, "listing.txt"), "w", encoding="utf-8") as f:
            f.write(listing_text)

    def _write_metadata(
        self,
        package_dir: str,
        spec: ProductSpec,
        design: DesignProfile,
        blueprint: ProductBlueprint,
        quality_score: float | None,
        opportunity_score: float | None,
    ) -> None:
        metadata = {
            "product_id": spec.product_id,
            "title": spec.title or blueprint.display_name,
            "target_customer": spec.target_customer or blueprint.default_target_customer,
            "category": blueprint.niche,
            "features": spec.core_features or blueprint.default_features,
            "files": list(self.REQUIRED_FILES),
            "design_profile": design.profile_id,
            "quality_score": quality_score,
            "opportunity_score": opportunity_score,
            "created_at": _now_iso(),
            "version": "1.0",
        }
        with open(os.path.join(package_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _write_readme(self, package_dir: str, spec: ProductSpec, blueprint: ProductBlueprint) -> None:
        lines = [
            f"{spec.title or blueprint.display_name}",
            "",
            "Contents:",
            "- product.xlsx        The editable spreadsheet (open in Excel, Google Sheets, etc.)",
            "- printable.pdf       A printable planner version of the same template",
            "- instructions.pdf    Quick-start usage guide",
            "- preview.png         Preview image",
            "- listing.txt         Suggested marketplace listing text (title/description/tags)",
            "",
            "This product is for personal budgeting organization only and does not",
            "constitute financial advice.",
        ]
        with open(os.path.join(package_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _verify_package_dir(self, package_dir: str) -> None:
        for filename in self.REQUIRED_FILES:
            path = os.path.join(package_dir, filename)
            if not os.path.isfile(path):
                raise PackagingError(f"Missing required packaged file: {filename}")
            if os.path.getsize(path) == 0:
                raise PackagingError(f"Packaged file is empty: {filename}")

    def _zip_package(self, package_dir: str, base_output_dir: str, slug: str) -> str:
        zip_path = os.path.join(base_output_dir, f"{slug}.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename in self.REQUIRED_FILES:
                zf.write(os.path.join(package_dir, filename), arcname=filename)
        return zip_path

    def _verify_zip(self, zip_path: str) -> None:
        if not os.path.isfile(zip_path) or os.path.getsize(zip_path) == 0:
            raise PackagingError(f"ZIP was not created or is empty: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                raise PackagingError(f"ZIP integrity check failed on entry: {bad_file}")
            names = set(zf.namelist())
            missing = set(self.REQUIRED_FILES) - names
            if missing:
                raise PackagingError(f"ZIP is missing expected entries: {missing}")


def _now_iso() -> str:
    from src.core.models import now_iso
    return now_iso()
