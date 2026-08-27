from __future__ import annotations

import re
from collections import defaultdict

from ..domain import BrandRules
from ..security import detect_prompt_injection
from .contracts import AgentContract, AgentTrace


class BrandCompilerAgent:
    contract = AgentContract(
        name="brand_compiler",
        version="1.0",
        allowed_tools=("document_text", "color_parser", "font_parser"),
        timeout_seconds=30,
        max_steps=4,
        max_cost_usd=0.05,
        input_schema="brand_guide_text:string",
        output_schema="BrandRules",
        escalation_conditions=(
            "prompt injection detected",
            "no brand colors found",
            "confidence below 0.55",
        ),
    )
    _tone_words = (
        "bold",
        "calm",
        "confident",
        "conversational",
        "energetic",
        "friendly",
        "inclusive",
        "minimal",
        "optimistic",
        "playful",
        "premium",
        "professional",
        "warm",
    )
    _known_fonts = (
        "Arial",
        "Futura",
        "Georgia",
        "Helvetica",
        "Inter",
        "Montserrat",
        "Open Sans",
        "Poppins",
        "Roboto",
        "Times New Roman",
    )

    def run(self, guide_text: str) -> tuple[BrandRules, AgentTrace]:
        normalized = guide_text.replace("\x00", " ")[:250_000]
        lines = [re.sub(r"\s+", " ", line).strip() for line in normalized.splitlines()]
        lines = [line for line in lines if line]
        evidence: dict[str, list[str]] = defaultdict(list)

        colors = list(
            dict.fromkeys(item.upper() for item in re.findall(r"#[0-9a-fA-F]{6}\b", normalized))
        )
        for line in lines:
            if any(color in line.upper() for color in colors):
                evidence["colors"].append(line[:240])

        fonts = [font for font in self._known_fonts if font.lower() in normalized.lower()]
        font_pattern = re.compile(
            r"(?:font|typeface|typography)\s*(?:family)?\s*[:\-]\s*([A-Za-z][A-Za-z0-9 ]{1,35})",
            re.IGNORECASE,
        )
        fonts.extend(match.strip() for match in font_pattern.findall(normalized))
        fonts = list(dict.fromkeys(fonts))[:6]
        for line in lines:
            if any(font.lower() in line.lower() for font in fonts):
                evidence["fonts"].append(line[:240])

        tone = [word for word in self._tone_words if re.search(rf"\b{word}\b", normalized, re.I)]
        tone = tone[:6] or ["clear", "confident"]
        prohibited = self._extract_prohibited(lines)
        disclaimers = self._extract_disclaimers(lines)
        clear_space = self._extract_clear_space(normalized)
        backgrounds = self._extract_backgrounds(lines)
        warnings = detect_prompt_injection(normalized)
        if not colors:
            warnings.append(
                "no explicit hex colors found; reviewer must provide an approved palette"
            )
            colors = ["#111827", "#FFFFFF"]
        if not fonts:
            warnings.append("no known font found; reviewer must confirm typography")
            fonts = ["Inter"]

        confidence_signals = [bool(colors), bool(fonts), bool(tone), clear_space > 0]
        confidence = min(0.98, 0.45 + 0.12 * sum(confidence_signals) - 0.08 * len(warnings))
        rules = BrandRules(
            colors=colors[:8],
            fonts=fonts,
            tone=tone,
            prohibited_terms=prohibited,
            required_disclaimers=disclaimers,
            logo_clear_space_px=clear_space,
            allowed_logo_backgrounds=backgrounds,
            evidence=dict(evidence),
            confidence=round(max(0.1, confidence), 2),
            warnings=warnings,
        )
        trace = AgentTrace(
            agent=self.contract.name,
            version=self.contract.version,
            decision_summary=(
                f"Compiled {len(colors)} colors, {len(fonts)} fonts, and {len(tone)} tone rules."
            ),
            tool_calls=[
                {"tool": "color_parser", "result_count": len(colors)},
                {"tool": "font_parser", "result_count": len(fonts)},
            ],
            warnings=warnings.copy(),
        )
        return rules, trace

    @staticmethod
    def _extract_prohibited(lines: list[str]) -> list[str]:
        results: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(
                marker in lowered for marker in ("do not use", "never use", "avoid", "prohibited")
            ):
                remainder = re.split(r"do not use|never use|avoid|prohibited", line, flags=re.I)[-1]
                results.extend(
                    item.strip(" :.-\"'")
                    for item in re.split(r"[,;|]", remainder)
                    if 1 < len(item.strip()) < 80
                )
        return list(dict.fromkeys(results))[:20]

    @staticmethod
    def _extract_disclaimers(lines: list[str]) -> list[str]:
        values = [
            line[:240]
            for line in lines
            if "disclaimer" in line.lower() or "required legal" in line.lower()
        ]
        return list(dict.fromkeys(values))[:10]

    @staticmethod
    def _extract_clear_space(text: str) -> int:
        patterns = (
            r"clear\s+space.{0,30}?(\d{1,3})\s*(?:px|pixels)",
            r"logo.{0,20}?(\d{1,3})\s*(?:px|pixels).{0,20}?space",
        )
        for pattern in patterns:
            if match := re.search(pattern, text, re.I | re.S):
                return min(256, int(match.group(1)))
        return 24

    @staticmethod
    def _extract_backgrounds(lines: list[str]) -> list[str]:
        candidates = []
        for line in lines:
            if "logo" in line.lower() and "background" in line.lower():
                candidates.append(line[:120])
        return candidates[:4] or ["white", "approved primary color"]
