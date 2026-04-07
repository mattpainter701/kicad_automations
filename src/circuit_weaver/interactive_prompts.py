"""Platform-aware interactive prompt handler.

Detects execution context (Claude Code, Codex, OpenCode, or plain CLI)
and uses the appropriate UI for collecting structured input from users.

Supports:
- Claude Code: AskUserQuestion tool (native interactive UI)
- Codex/OpenCode: Conversational prompting (natural text + user response parsing)
- CLI: Terminal UI with questionary/inquirer (checkbox, multi-select, arrow keys)
"""

from __future__ import annotations

import os
from typing import Any, Literal

# Try to import questionary for terminal UI
try:
    import questionary

    HAS_QUESTIONARY = True
except ImportError:
    HAS_QUESTIONARY = False


def detect_platform() -> Literal["claude_code", "codex", "opencode", "cli"]:
    """Detect execution platform based on environment and available tools."""
    # Claude Code sets specific environment variables
    if os.environ.get("CLAUDE_CODE"):
        return "claude_code"

    # Codex detection (specific env vars or tool availability)
    if os.environ.get("CODEX_SESSION"):
        return "codex"

    # OpenCode detection
    if os.environ.get("OPENCODE_SESSION"):
        return "opencode"

    # Default to CLI
    return "cli"


def ask_multiple_choice(
    question: str,
    options: list[dict[str, str]],
    allow_multiple: bool = False,
    description: str = "",
) -> str | list[str]:
    """
    Ask user to select from a list of options.

    Auto-detects platform and uses appropriate UI.

    Args:
        question: The question to ask
        options: List of {"label": "...", "value": "..."} dicts
        allow_multiple: Allow multi-select (checkbox mode)
        description: Optional description/context

    Returns:
        Single value (str) or list of values if allow_multiple=True

    Example:
        >>> options = [
        ...     {"label": "Option A", "value": "a"},
        ...     {"label": "Option B", "value": "b"},
        ...     {"label": "Option C", "value": "c"},
        ... ]
        >>> choice = ask_multiple_choice("Pick one:", options)
        >>> print(choice)  # "a", "b", or "c"
    """
    platform = detect_platform()

    if platform == "claude_code":
        return _ask_claude_code(question, options, allow_multiple, description)
    elif platform in ("codex", "opencode"):
        return _ask_conversational(question, options, allow_multiple, description)
    else:
        return _ask_cli(question, options, allow_multiple, description)


def _ask_claude_code(
    question: str,
    options: list[dict[str, str]],
    allow_multiple: bool,
    description: str,
) -> str | list[str]:
    """Use Claude Code's native AskUserQuestion tool."""
    try:
        # In Claude Code context, AskUserQuestion is available as a tool
        # The skill framework will render these as interactive buttons/checkboxes

        option_list = [
            {
                "label": opt["label"],
                "description": opt.get("description", ""),
            }
            for opt in options
        ]

        # Return structured data that Claude Code will render interactively
        # In practice, this gets intercepted by the skill framework
        return {
            "type": "interactive_choice",
            "question": question,
            "description": description,
            "options": option_list,
            "multiSelect": allow_multiple,
            "values": [opt["value"] for opt in options],
        }
    except Exception:
        # Fallback if tool not available
        return _ask_conversational(question, options, allow_multiple, description)


def _ask_conversational(
    question: str,
    options: list[dict[str, str]],
    allow_multiple: bool,
    description: str,
) -> str | list[str]:
    """Use conversational prompting (for Codex, OpenCode, or text-based fallback)."""
    print(f"\n{question}")
    if description:
        print(f"  {description}\n")

    # Display options
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt['label']}")
        if opt.get("description"):
            print(f"      {opt['description']}")

    print()

    if allow_multiple:
        # For multi-select, accept comma-separated numbers: "1,3,5"
        response = input("Enter option numbers (comma-separated): ").strip()
        try:
            indices = [int(x.strip()) - 1 for x in response.split(",")]
            selected = [options[i]["value"] for i in indices if 0 <= i < len(options)]
            return selected if selected else [options[0]["value"]]
        except (ValueError, IndexError):
            print("Invalid input. Selecting first option.")
            return [options[0]["value"]]
    else:
        # Single select
        response = input("Enter option number: ").strip()
        try:
            idx = int(response) - 1
            if 0 <= idx < len(options):
                return options[idx]["value"]
        except ValueError:
            pass
        print("Invalid input. Selecting first option.")
        return options[0]["value"]


def _ask_cli(
    question: str,
    options: list[dict[str, str]],
    allow_multiple: bool,
    description: str,
) -> str | list[str]:
    """Use terminal UI with questionary (if available) or conversational fallback."""
    if HAS_QUESTIONARY:
        return _ask_cli_questionary(question, options, allow_multiple, description)
    else:
        return _ask_conversational(question, options, allow_multiple, description)


def _ask_cli_questionary(
    question: str,
    options: list[dict[str, str]],
    allow_multiple: bool,
    description: str,
) -> str | list[str]:
    """Use questionary for interactive terminal UI (arrow keys, checkboxes)."""
    choices = [questionary.Choice(opt["label"], value=opt["value"]) for opt in options]

    try:
        if allow_multiple:
            # Checkbox mode: arrow keys, spacebar to toggle, enter to confirm
            result = questionary.checkbox(question, choices=choices).ask()
            return result if result else [options[0]["value"]]
        else:
            # Select mode: arrow keys, enter to select
            result = questionary.select(question, choices=choices).ask()
            return result if result else options[0]["value"]
    except (EOFError, KeyboardInterrupt):
        # Fallback on interrupt or EOF
        return [options[0]["value"]] if allow_multiple else options[0]["value"]


def ask_text(
    question: str,
    default: str = "",
    description: str = "",
) -> str:
    """
    Ask user for free-form text input.

    Works across all platforms (simple input).

    Args:
        question: The question to ask
        default: Default value if user presses Enter
        description: Optional context

    Returns:
        User's input or default
    """
    prompt = question
    if default:
        prompt += f" [{default}]"
    prompt += ": "

    if description:
        print(f"  {description}")

    response = input(prompt).strip()
    return response if response else default


def ask_form_section(
    section_title: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Ask a grouped section of questions (like a form).

    Returns dict of {field_name: value}.

    Args:
        section_title: Title for the section
        fields: List of field dicts with 'name', 'question', 'type', 'options', 'default'

    Returns:
        Dict mapping field names to user responses
    """
    print(f"\n{'=' * 60}")
    print(f"  {section_title}")
    print(f"{'=' * 60}\n")

    results = {}
    for field in fields:
        name = field["name"]
        question = field["question"]
        field_type = field.get("type", "text")

        if field_type == "choice":
            options = field.get("options", [])
            allow_multiple = field.get("multiSelect", False)
            results[name] = ask_multiple_choice(
                question,
                options,
                allow_multiple=allow_multiple,
            )
        elif field_type == "text":
            default = field.get("default", "")
            results[name] = ask_text(question, default=default)
        else:
            results[name] = ask_text(question)

    return results


# Export public API
__all__ = [
    "detect_platform",
    "ask_multiple_choice",
    "ask_text",
    "ask_form_section",
]
