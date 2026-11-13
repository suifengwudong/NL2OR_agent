"""The Problem IR as a value object: parse it, normalize it, read its data.

The wire shape is a plain dict; this module owns the executable parameter
vocabulary. Tool arguments, normalization, the executable parameter view and
parameter overrides all share this single implementation instead of one private
helper per caller.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .ir_normalize import normalize_problem_ir

# Which IR data keys the executable block semantics actually read. Overrides may
# only touch these, so a typo cannot silently leave a scenario unchanged.
READABLE_DATA_KEYS: frozenset[str] = frozenset(
    {
        "p",
        "distance",
        "demand",
        "value",
        "weight",
        "capacity",
        "facility_capacity",
        "fixed_cost",
        "service_cost",
        "coverage_matrix",
        "forced_open",
        "forced_closed",
        "service_distance_limit",
        "opening_budget",
        "availability",
        "facility_distance",
    }
)


def _as_object(value: Any, label: str) -> dict[str, Any]:
    """Coerce a tool argument (dict, JSON string, or None) to a dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() == "null":
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析 {label}：{exc}") from exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"{label} 必须是一个对象，收到 {type(parsed).__name__}")
    raise ValueError(f"{label} 必须是一个对象或它的 JSON 字符串，收到 {type(value).__name__}")


@dataclass(frozen=True)
class ProblemIR:
    """A Problem IR value, plus the operations that only make sense on one."""

    data: dict[str, Any]

    @classmethod
    def parse(cls, value: ProblemIR | str | dict[str, Any] | None) -> ProblemIR:
        """Accept an IR value, its dict form, its JSON string, or None."""
        if isinstance(value, cls):
            return value
        return cls(_as_object(value, "ir_json"))

    @property
    def normalized(self) -> ProblemIR:
        """The normalized IR, as produced by validation."""
        normalized, _, _ = normalize_problem_ir(self.data)
        return ProblemIR(normalized)

    def fingerprint(self) -> str:
        """Stable fingerprint of the raw dict, to pair artifacts with an IR."""
        return fingerprint(self.data)

    @property
    def parameters(self) -> dict[str, Any]:
        """The executable view: numeric data from parameters, blocks and objective.

        Data may sit in the top-level ``parameters`` or inside a block's own
        ``parameters``; string values are placeholders and ignored, top-level wins.
        """
        data = {
            key: value
            for key, value in (self.data.get("parameters") or {}).items()
            if not isinstance(value, str)
        }
        for entry in self.data.get("constraint_blocks") or []:
            for key, value in (entry.get("parameters") or {}).items():
                if not isinstance(value, str):
                    data.setdefault(key, value)
        for key, value in ((self.data.get("objective") or {}).get("parameters") or {}).items():
            if not isinstance(value, str):
                data.setdefault(key, value)
        return data

    def with_overrides(self, overrides: dict[str, Any] | None = None) -> ProblemIR:
        """Return a copy whose top-level parameters are replaced by *overrides*.

        Keys and value shapes are validated before the call (:meth:`parse_overrides`
        plus :func:`block_model.prepare_overrides`), so this stays a plain copy and
        callers can render the overrides they applied.
        """
        out = copy.deepcopy(self.data)
        for key, value in (overrides or {}).items():
            out.setdefault("parameters", {})[key] = value
        return ProblemIR(out)

    @classmethod
    def parse_overrides(
        cls, value: str | dict[str, Any] | None, allowed: frozenset[str] | None = None
    ) -> dict[str, Any]:
        """Coerce a scenario-override argument and reject keys nothing would read.

        Accepts a dict, its JSON string, or None. *allowed* narrows the vocabulary
        to the keys one model's blocks read; unknown keys raise either way, so a
        typo cannot silently leave a scenario identical to the baseline.
        """
        applied = _as_object(value, "overrides_json")
        keys = READABLE_DATA_KEYS if allowed is None else allowed
        unknown = sorted(key for key in applied if key not in keys)
        if unknown:
            if not keys:
                raise ValueError(f"不支持的参数 {unknown[0]!r}；该模型没有可覆盖的参数")
            allowed_list = "、".join(sorted(keys))
            raise ValueError(f"不支持的参数 {unknown[0]!r}；该模型可覆盖的键为 {allowed_list}")
        return applied


def _executable_view(ir: dict[str, Any]) -> dict[str, Any]:
    """Project an IR to the content that determines the solved model.

    Prose fields (``natural_language``, ``missing_data``), block bookkeeping
    (``status``, ``name``, ``category``) and string placeholders do not change
    the optimization model, so they must not invalidate a saved solve result.
    """

    def data(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [data(item) for item in value]
        return value

    def parameters(value: Any) -> dict[str, Any]:
        return {key: data(item) for key, item in (value or {}).items() if not isinstance(item, str)}

    objective = ir.get("objective") or {}
    blocks = sorted(
        (
            {
                "block_id": str(entry.get("block_id") or ""),
                "parameters": parameters(entry.get("parameters")),
            }
            for entry in ir.get("constraint_blocks") or []
        ),
        key=lambda entry: entry["block_id"],
    )
    entities = {
        key: {
            "size": entry.get("size"),
            "ids": [str(item) for item in entry.get("ids") or []],
        }
        for key, entry in (ir.get("entities") or {}).items()
    }
    return {
        "problem_families": sorted(
            str(family.get("id")) for family in ir.get("problem_families") or []
        ),
        "entities": entities,
        "parameters": parameters(ir.get("parameters")),
        "objective": {
            "block_id": str(objective.get("block_id") or ""),
            "sense": str(objective.get("sense") or ""),
            "expression": str(objective.get("expression") or ""),
            "parameters": parameters(objective.get("parameters")),
        },
        "constraint_blocks": blocks,
    }


def fingerprint(ir: dict[str, Any]) -> str:
    """Stable hash of the executable model content (prose and order independent)."""
    canonical = json.dumps(_executable_view(ir), sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


__all__ = ["ProblemIR", "READABLE_DATA_KEYS", "fingerprint"]
