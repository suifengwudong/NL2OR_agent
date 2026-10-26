"""The Problem IR as a value object: parse it, normalize it, read its data.

The wire shape is a plain dict; the alias vocabulary lives in
``schema/problem_ir.py``. This class carries the behaviour, so tool arguments,
normalization, the executable parameter view and parameter overrides all share a
single implementation instead of one private helper per caller.
"""

from __future__ import annotations

import copy
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


__all__ = ["ProblemIR", "READABLE_DATA_KEYS"]
