"""
Listing text generator. NOT a ProductGenerator (it doesn't produce a
"file" in the same sense as xlsx/pdf/png) — it's a plain text builder
consumed by packager.py to write listing.txt.

Requirement #6: no automatic upload to any marketplace. This only
produces the TEXT the user will copy/paste when they manually list the
product. Requirement: SEO-aware but no keyword stuffing, no misleading
claims, no financial-advice framing.
"""

from __future__ import annotations

from src.core.models import ProductSpec
from src.generators.blueprints import ProductBlueprint


def build_listing_text(product_spec: ProductSpec, blueprint: ProductBlueprint) -> str:
    base_title = product_spec.title or blueprint.display_name
    # Etsy titles perform far better front-loaded with the primary keyword
    # phrase followed by descriptive modifiers (what search + browse both
    # reward) than a bare product name — cap at Etsy's 140-character title
    # limit, and fall back to the bare title if no suffix is defined for
    # this niche yet.
    if blueprint.seo_title_suffix:
        title = f"{base_title} | {blueprint.seo_title_suffix}"[:140].rstrip(" |")
    else:
        title = base_title
    target = (product_spec.target_customer or blueprint.default_target_customer).replace("_", " ")
    features = product_spec.core_features or blueprint.default_features
    optional_features = product_spec.optional_features
    # Prefer real per-niche SEO tags (blueprint.seo_keywords) over the bare
    # niche/title-word fallback — Etsy allows up to 13 tags and search
    # visibility depends heavily on actually using all of them with real
    # buyer search phrases, not just the product's own name split into
    # words.
    keywords = product_spec.keywords or blueprint.seo_keywords or _derive_keywords(product_spec, blueprint)
    price = product_spec.price_suggestion

    description_lines = [
        f"{base_title} is a {blueprint.display_name.lower()} built for {target}.",
    ]
    if product_spec.problem:
        description_lines.append(f"It's designed to help with: {product_spec.problem}")
    if product_spec.differentiation:
        description_lines.append(product_spec.differentiation)
    description = " ".join(description_lines)

    lines: list[str] = []
    lines.append("Title:")
    lines.append(title)
    lines.append("")
    lines.append("Description:")
    lines.append(description)
    lines.append("")
    lines.append("Features:")
    for f in features:
        lines.append(f"- {f}")
    if optional_features:
        lines.append("")
        lines.append("Also included:")
        for f in optional_features:
            lines.append(f"- {f}")
    lines.append("")
    lines.append("Tags:")
    lines.append(", ".join(keywords[:13]))  # marketplaces like Etsy cap around 13 tags
    lines.append("")
    lines.append("Keywords:")
    lines.append(", ".join(keywords))
    lines.append("")
    lines.append("Suggested Price:")
    lines.append(f"${price:.2f}" if price is not None else "Not set — review comparable listings before pricing.")
    lines.append("")
    lines.append("Target Customer:")
    lines.append(target)
    lines.append("")
    lines.append("What's Included:")
    for fmt in product_spec.file_formats:
        lines.append(f"- {fmt.upper()} file")
    lines.append("- Preview image")
    lines.append("- Instructions guide")
    lines.append("")
    lines.append("Usage Instructions:")
    lines.append(
        "Download and open the file in Excel, Google Sheets, or a compatible spreadsheet "
        "application. Enter your own data in place of the example rows. Totals and "
        "percentages update automatically."
    )
    lines.append("")
    lines.append(
        "Note: this template is for personal budgeting organization only and does not "
        "constitute financial, tax, or investment advice."
    )
    return "\n".join(lines)


def _derive_keywords(product_spec: ProductSpec, blueprint: ProductBlueprint) -> list[str]:
    """Fallback keyword list built from the niche/title only when the
    strategist hasn't supplied explicit keywords yet — never fabricated
    claims, just plain descriptive terms."""
    base = blueprint.niche.replace("_", " ").split()
    title_words = [w.lower() for w in (product_spec.title or "").split() if len(w) > 2]
    seen: list[str] = []
    for w in base + title_words:
        if w not in seen:
            seen.append(w)
    return seen
