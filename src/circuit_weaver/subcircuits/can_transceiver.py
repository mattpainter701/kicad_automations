"""Backward-compatible import for the JSON-backed CAN template."""

from ._compat import DeprecatedTemplateAdapter
from .base import LegacyDBProxy

CAN_TRANSCEIVER_IC_DATABASE = LegacyDBProxy("can_transceiver")


class CANTransceiverTemplate(DeprecatedTemplateAdapter):
    template_type = "can_transceiver"
    legacy_class_name = "CANTransceiverTemplate"


__all__ = ["CAN_TRANSCEIVER_IC_DATABASE", "CANTransceiverTemplate"]
