"""Backward-compatible import for the JSON-backed protection template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

TVS_DATABASE = LegacyDBProxy("protection")


class ProtectionTemplate(DeprecatedTemplateAdapter):
    template_type = "protection"
    legacy_class_name = "ProtectionTemplate"


__all__ = ["ProtectionTemplate", "TVS_DATABASE"]
