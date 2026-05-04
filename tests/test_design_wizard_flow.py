from circuit_weaver.dispatcher import _normalize_wizard_experience, _wizard_requirement_prompt_plan


def test_normalize_wizard_experience_aliases():
    assert _normalize_wizard_experience("") == "Intermediate"
    assert _normalize_wizard_experience("pro") == "Professional"
    assert _normalize_wizard_experience("professional ee") == "Professional"
    assert _normalize_wizard_experience("ADVANCED") == "Advanced"
    assert _normalize_wizard_experience("1") == "Beginner"


def test_professional_prompt_plan_starts_with_design_brief():
    first_key, first_prompt, first_default = _wizard_requirement_prompt_plan("Professional")[0]
    assert first_key == "purpose"
    assert "Design brief" in first_prompt
    assert "interfaces" in first_prompt.lower()
    assert first_default == "Custom circuit"


def test_advanced_prompt_plan_uses_compact_brief():
    first_key, first_prompt, _ = _wizard_requirement_prompt_plan("Advanced")[0]
    assert first_key == "purpose"
    assert "Compact design brief" in first_prompt


def test_beginner_prompt_plan_uses_plain_language_prompt():
    first_key, first_prompt, _ = _wizard_requirement_prompt_plan("Beginner")[0]
    assert first_key == "purpose"
    assert "plain language" in first_prompt.lower()
