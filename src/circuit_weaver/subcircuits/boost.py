"""Backward-compatible import for the JSON-backed boost template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

BOOST_IC_DATABASE = LegacyDBProxy("boost")


class BoostConverterTemplate(DeprecatedTemplateAdapter):
    template_type = "boost"
    legacy_class_name = "BoostConverterTemplate"


__all__ = ["BOOST_IC_DATABASE", "BoostConverterTemplate"]
