"""Compatibility adapters for templates migrated to the JSON registry."""

from __future__ import annotations

import warnings
from typing import Any

from .base import SubcircuitResult, SubcircuitTemplate, get_default_registry


class DeprecatedTemplateAdapter(SubcircuitTemplate):
    """Preserve an old template class while delegating to its current engine."""

    legacy_class_name = "SubcircuitTemplate"

    def __init__(self) -> None:
        warnings.warn(
            f"{self.legacy_class_name} is deprecated; use "
            f"get_default_registry().get('{self.template_type}')",
            DeprecationWarning,
            stacklevel=2,
        )
        delegate = get_default_registry().get(self.template_type)
        if delegate is None:
            raise RuntimeError(f"No registered replacement for template '{self.template_type}'")
        self._delegate = delegate
        self.description = delegate.description
        self.param_schema = delegate.get_param_schema()

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return self._delegate.validate_params(params)

    def generate(self, params: dict[str, Any]) -> SubcircuitResult:
        return self._delegate.generate(params)
