"""Backward-compatible import for the JSON-backed LDO template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

LDO_IC_DATABASE = LegacyDBProxy("ldo")


class LDOTemplate(DeprecatedTemplateAdapter):
    template_type = "ldo"
    legacy_class_name = "LDOTemplate"


__all__ = ["LDO_IC_DATABASE", "LDOTemplate"]
