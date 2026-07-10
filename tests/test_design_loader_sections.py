"""Ownership metadata must survive DesignIR compilation into components."""

from circuit_weaver.component_db import ComponentDef
from circuit_weaver.design_ir import DesignBlock, DesignIR
from circuit_weaver.design_loader import _apply_block_attributes


def test_block_section_and_id_propagate_to_every_resolved_component() -> None:
    block = DesignBlock(
        id="power:U1:input",
        section="power_input",
        kind="component",
        ref="U1",
    )
    primary = ComponentDef(mpn="REG", ref_prefix="U", source_ref="U1")
    generated = ComponentDef(mpn="TVS", ref_prefix="D", source_ref="U1")

    _apply_block_attributes(DesignIR(blocks=[block]), [primary, generated])

    assert {primary.functional_section, generated.functional_section} == {"power_input"}
    assert {primary.block_id, generated.block_id} == {"power:U1:input"}
