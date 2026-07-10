"""Backward-compatible import for the JSON-backed buck template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

BUCK_IC_DATABASE = LegacyDBProxy("buck")


class BuckConverterTemplate(DeprecatedTemplateAdapter):
    template_type = "buck"
    legacy_class_name = "BuckConverterTemplate"


__all__ = ["BUCK_IC_DATABASE", "BuckConverterTemplate"]
