from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .domain import Campaign, ExportManifest
from .exceptions import ValidationError
from .ports import ObjectStore

CHANNEL_SIZES = {
    "instagram": (1080, 1350),
    "email": (1200, 600),
    "web": (1440, 560),
    "presentation": (1920, 1080),
}


@dataclass(slots=True)
class CampaignExporter:
    object_store: ObjectStore

    def export(self, campaign: Campaign) -> ExportManifest:
        variant = campaign.selected_variant()
        if variant is None:
            raise ValidationError("a selected variant is required before export")
        base = f"exports/{campaign.tenant_id}/{campaign.id}/v{campaign.version + 1}"
        formats: dict[str, str] = {}
        for channel in variant.copy_by_channel:
            revisions = campaign.designs.get(channel, [])
            svg = (
                self.object_store.get(revisions[-1].svg_key)
                if revisions
                else self.render_channel(campaign, channel).encode()
            )
            key = f"{base}/{channel}.svg"
            self.object_store.put(key, svg, "image/svg+xml")
            formats[channel] = key

        design_sources = {
            channel: {
                "design_revision_id": revisions[-1].id,
                "revision": revisions[-1].revision,
                "canonical_layer_source": revisions[-1].layer_document_key,
                "svg_source": revisions[-1].svg_key,
            }
            for channel, revisions in campaign.designs.items()
            if revisions
        }
        manifest_payload: dict[str, Any] = {
            "campaign_id": campaign.id,
            "tenant_id": campaign.tenant_id,
            "variant_id": variant.id,
            "format_objects": formats,
            "editable_source": "svg",
            "design_sources": design_sources,
            "express_handoff": {
                "enabled_when_configured": True,
                "sdk": "Adobe Express Embed SDK v4",
                "note": "The browser opens an approved SVG in Express; no publishing occurs.",
            },
            "reproducibility": {
                "workflow_version": campaign.workflow_version,
                "agent_graph_version": campaign.agent_graph_version,
                "prompt_versions": campaign.prompt_versions,
                "models": campaign.model_manifest,
                "brand_rules_version": campaign.brand_rules.version
                if campaign.brand_rules
                else None,
                "input_asset_hashes": [asset.sha256 for asset in campaign.assets],
                "human_approval_ids": [item.id for item in campaign.approvals],
                "total_cost_usd": campaign.total_cost_usd,
            },
        }
        manifest_bytes = json.dumps(manifest_payload, indent=2, sort_keys=True).encode()
        manifest_key = f"{base}/manifest.json"
        self.object_store.put(manifest_key, manifest_bytes, "application/json")
        return ExportManifest(
            id=f"exp_{uuid4().hex[:16]}",
            campaign_id=campaign.id,
            object_key=manifest_key,
            variant_id=variant.id,
            formats=formats,
            provenance={
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "workflow_version": campaign.workflow_version,
                "agent_graph_version": campaign.agent_graph_version,
                "design_revision_ids": {
                    channel: source["design_revision_id"]
                    for channel, source in design_sources.items()
                },
                "canonical_layer_sources": {
                    channel: source["canonical_layer_source"]
                    for channel, source in design_sources.items()
                },
            },
        )

    def render_channel(self, campaign: Campaign, channel: str) -> str:
        variant = campaign.selected_variant()
        if variant is None:
            raise ValidationError("a selected variant is required before rendering a design")
        if channel not in CHANNEL_SIZES or channel not in variant.copy_by_channel:
            raise ValidationError("unsupported design channel")
        copy = variant.copy_by_channel[channel]
        width, height = CHANNEL_SIZES[channel]
        return _render_svg(
            width=width,
            height=height,
            palette=variant.palette,
            headline=copy.get("headline", variant.concept),
            body=copy.get("body", copy.get("caption", "")),
            cta=copy.get("cta", ""),
            concept=variant.concept,
        )

    def store_generated_image(
        self, campaign: Campaign, variant_id: str, image_payload: dict[str, object]
    ) -> str | None:
        encoded = image_payload.get("image_base64")
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValidationError("generated image payload was not valid base64") from error
        if len(content) > 20 * 1024 * 1024:
            raise ValidationError("generated image exceeded the 20 MiB asset limit")
        media_type = str(image_payload.get("media_type", "image/png"))
        extensions = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/svg+xml": "svg",
        }
        if media_type not in extensions:
            raise ValidationError("generated image media type is not allowlisted")
        key = (
            f"generated/{campaign.tenant_id}/{campaign.id}/v{campaign.version + 1}/"
            f"{variant_id}.{extensions[media_type]}"
        )
        return self.object_store.put(key, content, media_type)


def _render_svg(
    *,
    width: int,
    height: int,
    palette: list[str],
    headline: str,
    body: str,
    cta: str,
    concept: str,
) -> str:
    primary = _safe_color(palette[0] if palette else "", "#111827")
    secondary = _safe_color(palette[1] if len(palette) > 1 else "", "#F8FAFC")
    safe_headline = html.escape(headline[:90])
    safe_body = html.escape(body[:180])
    safe_cta = html.escape(cta[:40])
    safe_concept = html.escape(concept[:60])
    headline_size = max(40, round(width * 0.055))
    body_size = max(22, round(width * 0.022))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="brandGradient" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{primary}"/>
      <stop offset="100%" stop-color="{secondary}"/>
    </linearGradient>
  </defs>
  <rect id="gradient-overlay" data-name="Gradient overlay" width="{width}" height="{height}" fill="url(#brandGradient)" opacity="0.30"/>
  <rect id="content-panel" data-name="Content panel" x="{width * 0.06:.0f}" y="{height * 0.08:.0f}" width="{width * 0.88:.0f}" height="{height * 0.84:.0f}" rx="32" fill="#000" opacity="0.18"/>
  <text id="concept-label" data-name="Concept label" x="{width * 0.1:.0f}" y="{height * 0.2:.0f}" fill="#fff" font-family="Inter,Arial,sans-serif" font-size="24" letter-spacing="4">{safe_concept.upper()}</text>
  <text id="headline" data-name="Headline" x="{width * 0.1:.0f}" y="{height * 0.42:.0f}" fill="#fff" font-family="Inter,Arial,sans-serif" font-size="{headline_size}" font-weight="700">{safe_headline}</text>
  <text id="body-copy" data-name="Body copy" x="{width * 0.1:.0f}" y="{height * 0.57:.0f}" fill="#fff" font-family="Inter,Arial,sans-serif" font-size="{body_size}">{safe_body}</text>
  <rect id="cta-background" data-name="CTA background" x="{width * 0.1:.0f}" y="{height * 0.72:.0f}" width="{max(210, width * 0.22):.0f}" height="64" rx="32" fill="#fff"/>
  <text id="cta-label" data-name="CTA label" x="{width * 0.13:.0f}" y="{height * 0.72 + 42:.0f}" fill="{primary}" font-family="Inter,Arial,sans-serif" font-size="22" font-weight="700">{safe_cta}</text>
</svg>
"""


def _safe_color(value: str, fallback: str) -> str:
    return value.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else fallback
