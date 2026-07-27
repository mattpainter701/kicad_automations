"""JSON Schema generation for the DesignIR format."""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from .design_ir import DesignBlock, DesignInterface, PowerDomain


def _get_type_schema(python_type: Any) -> dict[str, Any]:
    """Convert Python type hint to JSON Schema type.

    Args:
        python_type: A Python type object or string annotation

    Returns:
        A dict with 'type' key and optionally 'items' or 'properties'
    """
    # Handle string annotations
    if isinstance(python_type, str):
        # Basic string matching
        if "bool" in python_type:
            return {"type": "boolean"}
        if "int" in python_type:
            return {"type": "integer"}
        if "float" in python_type:
            return {"type": "number"}
        if "str" in python_type:
            return {"type": "string"}
        if "list" in python_type or "List" in python_type:
            return {"type": "array", "items": {}}
        if "dict" in python_type or "Dict" in python_type:
            return {"type": "object"}
        return {"type": "object"}

    origin = get_origin(python_type)
    if origin in (Union, types.UnionType):
        non_null = [item for item in get_args(python_type) if item is not type(None)]
        if len(non_null) == 1 and len(non_null) != len(get_args(python_type)):
            return _get_type_schema(non_null[0])

    # Handle None/NoneType
    if python_type is type(None):
        return {"type": "null"}

    # Handle bool (must come before int since bool is subclass of int)
    if python_type is bool:
        return {"type": "boolean"}

    # Handle int
    if python_type is int:
        return {"type": "integer"}

    # Handle float
    if python_type is float:
        return {"type": "number"}

    # Handle str
    if python_type is str:
        return {"type": "string"}

    # Handle list
    if hasattr(python_type, "__origin__"):
        origin = python_type.__origin__
        if origin is list:
            args = getattr(python_type, "__args__", ())
            item_schema = _get_type_schema(args[0]) if args else {}
            return {"type": "array", "items": item_schema}
        if origin is dict:
            return {"type": "object"}

    # Fallback
    return {"type": "object"}


def _dataclass_to_schema(cls: type) -> dict[str, Any]:
    """Convert a dataclass to JSON Schema.

    Args:
        cls: A dataclass type

    Returns:
        JSON Schema dict with properties
    """
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    # Get type hints for the dataclass
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = {}

    # Process each field
    for field in dataclasses.fields(cls):
        field_name = field.name
        field_type = hints.get(field_name, field.type)

        schema["properties"][field_name] = _get_type_schema(field_type)

        # Check if field is required (no default value)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            schema["required"].append(field_name)

    return schema


def get_design_ir_schema() -> dict[str, Any]:
    """Return JSON Schema for the DesignIR format.

    Returns:
        A complete JSON Schema dict describing the DesignIR structure
    """
    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Circuit Weaver Design IR",
        "description": "Internal Design Representation for circuit-weaver",
        "type": "object",
        "properties": {},
        "required": ["project", "blocks"],
    }

    power_domain_schema = _dataclass_to_schema(PowerDomain)
    power_domain_properties = power_domain_schema["properties"]
    power_domain_properties["direction"]["enum"] = ["source", "load", "bidirectional"]
    for name in ("i_peak_ma", "i_steady_ma", "tolerance", "sequence_order"):
        power_domain_properties[name]["minimum"] = 0

    # Manually define the top-level properties (DesignIR fields)
    design_ir_fields = {
        "project": {"type": "string", "description": "Project name"},
        "blocks": {
            "type": "array",
            "description": "List of design blocks",
            "items": _dataclass_to_schema(DesignBlock),
        },
        "interfaces": {
            "type": "array",
            "description": "List of design interfaces",
            "items": _dataclass_to_schema(DesignInterface),
        },
        "power_domains": {
            "type": "array",
            "description": "Declared power rails and optional operating envelopes",
            "items": power_domain_schema,
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary metadata dict",
            "additionalProperties": True,
        },
    }

    schema["properties"] = design_ir_fields

    return schema
