"""Backward-compatible import for the JSON-backed EEPROM template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

EEPROM_IC_DATABASE = LegacyDBProxy("eeprom")


class EEPROMTemplate(DeprecatedTemplateAdapter):
    template_type = "eeprom"
    legacy_class_name = "EEPROMTemplate"


__all__ = ["EEPROM_IC_DATABASE", "EEPROMTemplate"]
