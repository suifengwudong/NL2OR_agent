"""Structured final-answer format helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

REQUIRED_FIELD_ORDER = (
    "conclusion",
    "key_evidence",
    "constraints_assumptions",
    "actionable_steps",
)

_JSON_FENCE_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class StructuredFinalAnswer(BaseModel):
    """Strict schema for final_answer payload."""

    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1, max_length=400)
    key_evidence: list[str] = Field(min_length=1, max_length=6)
    constraints_assumptions: list[str] = Field(min_length=1, max_length=6)
    actionable_steps: list[str] = Field(min_length=1, max_length=8)

    @field_validator("key_evidence", "constraints_assumptions", "actionable_steps")
    @classmethod
    def _validate_items(cls, values: list[str]) -> list[str]:
        for value in values:
            text = value.strip()
            if not text:
                raise ValueError("List items must be non-empty.")
            if len(text) > 200:
                raise ValueError("Each list item must be at most 200 characters.")
        return [value.strip() for value in values]

    @field_validator("conclusion")
    @classmethod
    def _validate_conclusion(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("conclusion must be non-empty.")
        return text


def extract_json_payload(raw: str) -> dict[str, Any]:
    """Extract JSON payload from plain JSON text or a fenced json block."""

    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        return _load_json_dict(text)

    matches = list(_JSON_FENCE_PATTERN.finditer(raw))
    if matches:
        return _load_json_dict(matches[-1].group(1))

    raise ValueError("Missing JSON payload. Expected plain JSON or ```json fenced block.")


def validate_payload_dict(payload: dict[str, Any]) -> StructuredFinalAnswer:
    """Validate key order, required fields and value constraints."""

    actual_keys = list(payload.keys())
    expected_keys = list(REQUIRED_FIELD_ORDER)
    if actual_keys != expected_keys:
        raise ValueError(
            "Invalid field order or fields. Expected keys in order: " + ", ".join(expected_keys)
        )

    try:
        return StructuredFinalAnswer.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Schema validation failed: {exc}") from exc


def format_for_display(raw: str) -> str:
    """Return normalized human-readable + JSON output."""

    payload = validate_payload_dict(extract_json_payload(raw))
    human_readable = _render_human_readable(payload)
    json_block = json.dumps(payload.model_dump(), ensure_ascii=False, indent=2)
    return f"{human_readable}\n\n```json\n{json_block}\n```"


_NOISE_PREFIXES = ("Thought:", "Code:", "```", "import", "╭", "╰", "━━")


def format_agent_output(raw: str) -> str:
    """Render agent output for display.

    Prefers the structured final-answer format; falls back to cleaned raw text
    for natural-language replies (e.g. IR confirmation, model-lookup summary).
    """
    text = str(raw).strip()
    try:
        return format_for_display(text)
    except ValueError:
        pass

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    clean = [line for line in lines if not line.startswith(_NOISE_PREFIXES) and "```" not in line]
    return "\n".join(clean[-20:]) or text[-500:]


def _render_human_readable(payload: StructuredFinalAnswer) -> str:
    sections = [
        "结论",
        payload.conclusion,
        "",
        "关键依据",
        _render_bullets(payload.key_evidence),
        "",
        "约束/假设",
        _render_bullets(payload.constraints_assumptions),
        "",
        "可执行步骤",
        _render_numbered(payload.actionable_steps),
    ]
    return "\n".join(sections)


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _render_numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _load_json_dict(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object.")
    return payload
