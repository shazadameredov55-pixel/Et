"""
ProfileSelector: resolves a DesignProfile for a ProductSpec using the
Target User -> Problem -> UX -> Layout -> Typography -> Visual System
logic (requirement: never random color assignment). Each design profile
in config/design_profiles.yaml declares `best_for` target-customer tags;
selection matches the spec's target_customer against those tags, falling
back to a stable default only when no tag matches.
"""

from __future__ import annotations

import yaml

from src.core.models import DesignProfile, ProductSpec


class ProfileSelector:
    def __init__(self, design_config_path: str = "config/design_profiles.yaml"):
        with open(design_config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._profiles: dict[str, dict] = data["profiles"]

    def select(self, product_spec: ProductSpec) -> DesignProfile:
        target = (product_spec.target_customer or "").lower().replace(" ", "_")

        best_match_id = None
        for profile_id, profile in self._profiles.items():
            best_for = [t.lower() for t in profile.get("best_for", [])]
            if any(tag in target or target in tag for tag in best_for):
                best_match_id = profile_id
                break

        # Stable, deterministic fallback (not random) when nothing matches:
        # the first profile in config file order.
        profile_id = best_match_id or next(iter(self._profiles.keys()))
        profile = self._profiles[profile_id]

        return DesignProfile(
            profile_id=profile_id,
            name=profile["name"],
            typography=profile["typography"],
            spacing=profile["spacing"],
            hierarchy=profile["hierarchy"],
            layout=profile["layout"],
            table_design=profile["table_design"],
            visual_density=profile["visual_density"],
            icon_usage=profile["icon_usage"],
        )
