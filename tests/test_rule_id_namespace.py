"""The live electrical contract emits only canonical rule-ID namespaces."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_LITERAL = "CW-" + "POWER-"
ALLOWED_MIGRATION_FILES = {Path("src/circuit_weaver/benchmark_runner.py")}
HISTORICAL_FILES = {Path("TASKS.md"), Path("CHANGELOG.md")}
GENERATED_ROOTS = {".git", ".pytest_cache", ".test-tmp", "build", "__pycache__"}


def test_legacy_power_rule_literals_are_confined_to_explicit_migration_aliases() -> None:
    violations: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if relative in ALLOWED_MIGRATION_FILES | HISTORICAL_FILES or GENERATED_ROOTS & set(relative.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_LITERAL in text:
            violations.append(relative.as_posix())
    assert not violations, f"legacy CW-POWER rule literals remain outside migration aliases: {violations}"
