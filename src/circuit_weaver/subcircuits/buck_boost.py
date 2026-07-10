"""Backward-compatible import for the JSON-backed buck-boost template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

BUCK_BOOST_IC_DATABASE = LegacyDBProxy("buck_boost")


class BuckBoostConverterTemplate(DeprecatedTemplateAdapter):
    template_type = "buck_boost"
    legacy_class_name = "BuckBoostConverterTemplate"


__all__ = ["BUCK_BOOST_IC_DATABASE", "BuckBoostConverterTemplate"]
