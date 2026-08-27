from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from .domain import Campaign, DesignChannel, DesignRevision, LayerDocument, utc_now
from .exceptions import ConcurrencyError, ValidationError
from .ports import ObjectStore

CHANNEL_SIZES: dict[DesignChannel, tuple[int, int]] = {
    DesignChannel.INSTAGRAM: (1080, 1350),
    DesignChannel.EMAIL: (1200, 600),
    DesignChannel.WEB: (1440, 560),
    DesignChannel.PRESENTATION: (1920, 1080),
}
SUPPORTED_LAYER_TYPES = frozenset({"text", "image", "rect", "ellipse", "path", "group"})
MAX_LAYERS = 500
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_FABRIC_BYTES = 5 * 1024 * 1024
MAX_SVG_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True, slots=True)
class DesignSnapshot:
    revision: DesignRevision | None
    layer_document: LayerDocument
    fabric_json: dict[str, Any]
    svg: str
    preview_png: bytes | None = None


@dataclass(slots=True)
class DesignEditor:
    object_store: ObjectStore

    def load(self, campaign: Campaign, channel: str, bootstrap_svg: str) -> DesignSnapshot:
        design_channel = self.validate_channel(channel)
        revisions = campaign.designs.get(design_channel.value, [])
        if not revisions:
            width, height = CHANNEL_SIZES[design_channel]
            return DesignSnapshot(
                revision=None,
                layer_document=LayerDocument(design_channel, width, height, []),
                fabric_json={},
                svg=bootstrap_svg,
            )
        revision = revisions[-1]
        document_raw = json.loads(self.object_store.get(revision.layer_document_key))
        document = self.parse_layer_document(document_raw, design_channel)
        fabric = json.loads(self.object_store.get(revision.fabric_json_key))
        svg = self.object_store.get(revision.svg_key).decode("utf-8")
        preview = (
            self.object_store.get(revision.preview_png_key)
            if revision.preview_png_key is not None
            else None
        )
        return DesignSnapshot(revision, document, fabric, svg, preview)

    def save(
        self,
        campaign: Campaign,
        channel: str,
        *,
        layer_document: LayerDocument | dict[str, Any],
        fabric_json: dict[str, Any],
        svg: str,
        preview_png: bytes | None,
        expected_revision: int,
        created_by: str,
        editor: str = "fabric",
        editor_version: str = "unknown",
    ) -> DesignRevision:
        design_channel = self.validate_channel(channel)
        revisions = campaign.designs.get(design_channel.value, [])
        current_revision = revisions[-1].revision if revisions else 0
        if expected_revision != current_revision:
            raise ConcurrencyError(
                f"design {channel} expected revision {expected_revision}, "
                f"found {current_revision}"
            )
        if not _SAFE_IDENTIFIER.fullmatch(campaign.tenant_id) or not _SAFE_IDENTIFIER.fullmatch(
            campaign.id
        ):
            raise ValidationError("campaign identifiers cannot be used in design object keys")
        if not created_by.strip() or len(created_by) > 200:
            raise ValidationError("design creator is required and must be at most 200 characters")
        if not editor.strip() or len(editor) > 100 or len(editor_version) > 100:
            raise ValidationError("editor metadata exceeds its limits")

        document = self.parse_layer_document(layer_document, design_channel)
        document_bytes = json.dumps(
            {
                "schema_version": document.schema_version,
                "channel": document.channel.value,
                "width": document.width,
                "height": document.height,
                "layers": document.layers,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if len(document_bytes) > MAX_DOCUMENT_BYTES:
            raise ValidationError("layer document exceeds the 2 MiB limit")
        if not isinstance(fabric_json, dict):
            raise ValidationError("Fabric cache must be a JSON object")
        self._validate_json_value(fabric_json)
        fabric_bytes = json.dumps(fabric_json, separators=(",", ":"), sort_keys=True).encode()
        if len(fabric_bytes) > MAX_FABRIC_BYTES:
            raise ValidationError("Fabric cache exceeds the 5 MiB limit")
        svg_bytes = self._validate_svg(svg, document.width, document.height)
        if preview_png is not None:
            if len(preview_png) > MAX_PREVIEW_BYTES:
                raise ValidationError("preview exceeds the 10 MiB limit")
            if not preview_png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValidationError("preview must be a PNG image")

        revision_number = current_revision + 1
        base = (
            f"designs/{campaign.tenant_id}/{campaign.id}/{design_channel.value}/"
            f"v{revision_number}"
        )
        layer_document_key = f"{base}/layer-document.json"
        fabric_json_key = f"{base}/fabric.json"
        svg_key = f"{base}/design.svg"
        preview_png_key = f"{base}/preview.png" if preview_png is not None else None
        self.object_store.put(layer_document_key, document_bytes, "application/json")
        self.object_store.put(fabric_json_key, fabric_bytes, "application/json")
        self.object_store.put(svg_key, svg_bytes, "image/svg+xml")
        if preview_png is not None and preview_png_key is not None:
            self.object_store.put(preview_png_key, preview_png, "image/png")

        hashes = {
            "layer_document": hashlib.sha256(document_bytes).hexdigest(),
            "fabric_json": hashlib.sha256(fabric_bytes).hexdigest(),
            "svg": hashlib.sha256(svg_bytes).hexdigest(),
        }
        if preview_png is not None:
            hashes["preview_png"] = hashlib.sha256(preview_png).hexdigest()
        return DesignRevision(
            id=f"dsn_{uuid4().hex[:16]}",
            channel=design_channel,
            revision=revision_number,
            layer_document_key=layer_document_key,
            fabric_json_key=fabric_json_key,
            svg_key=svg_key,
            preview_png_key=preview_png_key,
            editor=editor.strip(),
            editor_version=editor_version.strip(),
            created_by=created_by.strip(),
            created_at=utc_now(),
            hashes=hashes,
        )

    @staticmethod
    def validate_channel(channel: str) -> DesignChannel:
        try:
            return DesignChannel(channel)
        except ValueError as error:
            raise ValidationError("unsupported design channel") from error

    @classmethod
    def parse_layer_document(
        cls, value: LayerDocument | dict[str, Any], channel: DesignChannel
    ) -> LayerDocument:
        if isinstance(value, LayerDocument):
            document = value
        elif isinstance(value, dict):
            try:
                document = LayerDocument(
                    channel=DesignChannel(value["channel"]),
                    width=int(value["width"]),
                    height=int(value["height"]),
                    layers=value["layers"],
                    schema_version=int(value.get("schema_version", 1)),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValidationError("invalid layer document") from error
        else:
            raise ValidationError("layer document must be an object")
        if document.channel != channel:
            raise ValidationError("layer document channel does not match the requested channel")
        if document.schema_version != 1:
            raise ValidationError("unsupported layer document schema version")
        if (document.width, document.height) != CHANNEL_SIZES[channel]:
            raise ValidationError("layer document dimensions do not match the channel")
        if not isinstance(document.layers, list) or len(document.layers) > MAX_LAYERS:
            raise ValidationError(f"layer document may contain at most {MAX_LAYERS} layers")
        seen: set[str] = set()
        for layer in document.layers:
            if not isinstance(layer, dict):
                raise ValidationError("each layer must be an object")
            layer_id = layer.get("id")
            layer_type = layer.get("type")
            if not isinstance(layer_id, str) or not _SAFE_IDENTIFIER.fullmatch(layer_id):
                raise ValidationError("each layer requires a safe, bounded id")
            if layer_id in seen:
                raise ValidationError("layer ids must be unique")
            seen.add(layer_id)
            if layer_type not in SUPPORTED_LAYER_TYPES:
                raise ValidationError(f"unsupported layer type: {layer_type}")
            cls._validate_json_value(layer)
        return document

    @classmethod
    def _validate_json_value(cls, value: Any, depth: int = 0) -> None:
        if depth > 12:
            raise ValidationError("design JSON nesting is too deep")
        if isinstance(value, str):
            if len(value) > 20_000:
                raise ValidationError("design strings may not exceed 20,000 characters")
        elif isinstance(value, dict):
            if len(value) > 500:
                raise ValidationError("design objects contain too many fields")
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 200:
                    raise ValidationError("design object keys are invalid")
                cls._validate_json_value(item, depth + 1)
        elif isinstance(value, list):
            if len(value) > 2_000:
                raise ValidationError("design arrays contain too many items")
            for item in value:
                cls._validate_json_value(item, depth + 1)
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ValidationError("design data must be JSON serializable")

    @staticmethod
    def _validate_svg(svg: str, width: int, height: int) -> bytes:
        if not isinstance(svg, str):
            raise ValidationError("design SVG must be text")
        content = svg.encode()
        if not content or len(content) > MAX_SVG_BYTES:
            raise ValidationError("design SVG is empty or exceeds the 5 MiB limit")
        lowered = svg.lower()
        if "<!doctype" in lowered or "<!entity" in lowered or "<script" in lowered:
            raise ValidationError("design SVG contains unsafe markup")
        try:
            root = ElementTree.fromstring(svg)  # noqa: S314 - DTD/entities rejected above
        except ElementTree.ParseError as error:
            raise ValidationError("design SVG is not valid XML") from error
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValidationError("design content must have an SVG root")
        for element in root.iter():
            for name, value in element.attrib.items():
                if name.lower().startswith("on") or value.strip().lower().startswith("javascript:"):
                    raise ValidationError("design SVG contains unsafe attributes")
        svg_width = root.attrib.get("width", "").removesuffix("px")
        svg_height = root.attrib.get("height", "").removesuffix("px")
        if svg_width and svg_height:
            try:
                if (round(float(svg_width)), round(float(svg_height))) != (width, height):
                    raise ValidationError("design SVG dimensions do not match the channel")
            except ValueError as error:
                raise ValidationError("design SVG dimensions are invalid") from error
        return content
