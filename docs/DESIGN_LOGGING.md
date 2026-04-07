# Design Workflow Logging

Circuit Weaver now tracks all design wizard and CLI operations in a persistent **design.log** file. This enables:

1. **Proactive Troubleshooting** — See exactly which commands failed, when, and why
2. **Design Resumption** — Load an existing project and see where you left off
3. **Workflow Auditing** — Full timeline of requirements capture, validations, generations
4. **Error Recovery** — Diagnose issues without re-running the entire workflow

## Log File Location

Each design project has its own log file:

```
my_project/
├── design.yaml          # Your design spec
├── design.log           # Workflow log (JSON Lines format)
└── output/
    └── ...generated files...
```

## Log Format

The `design.log` file is **JSON Lines** — one JSON object per line, easy to parse and stream:

```json
{"timestamp": "2026-04-06T10:23:45.123456", "type": "wizard_step", "step": 1, "description": "Requirements captured - basic info", "user_input": {"project_name": "VTec Toy Phone", "purpose": "Compact WiFi-enabled toy phone"}}
{"timestamp": "2026-04-06T10:23:52.234567", "type": "wizard_step", "step": 2, "description": "Power supply requirements captured", "user_input": {"input_power": "3.7V LiPo", "output_rails": "3.3V, 500mA; 5V, 100mA"}}
{"timestamp": "2026-04-06T10:24:30.345678", "type": "cli_call", "command": "validate", "args": ["design.yaml"], "return_code": 0, "duration_sec": 2.34, "generated_files": ["design_report.md"], "success": true}
{"timestamp": "2026-04-06T10:24:35.456789", "type": "validation", "spec_file": "design.yaml", "passed": true, "error_count": 0, "warning_count": 2, "errors": [], "warnings": ["C1: capacitance should be >= 10uF", "Missing datasheet for U7"]}
```

## Viewing Workflow Status

### Show Summary

Check the current status of a design project:

```bash
circuit-weaver log-status <project_dir>
```

Output example:

```
========================================================================
Design Workflow Summary
========================================================================
Status:      IN_PROGRESS
Last step:   2
Log entries: 4
Files:       1 generated

Validation:  PASSED

Warnings (2 total):
  - C1: capacitance should be >= 10uF
  - Missing datasheet for U7

Log: /home/user/my_project/design.log
========================================================================
```

### View Recent Log Entries

See detailed recent activity with human-readable formatting:

```bash
# View last 10 entries (default)
circuit-weaver log-view <project_dir>

# View last 20 entries
circuit-weaver log-view <project_dir> --lines 20

# Filter by entry type (wizard_step, cli_call, validation, research)
circuit-weaver log-view <project_dir> --type cli_call

# Show only validation results
circuit-weaver log-view <project_dir> --type validation
```

Output example:

```
>>> Recent Log Entries (4 shown):

  [1] 2026-04-07T14:52:58 [WIZARD] Step 1: Requirements captured - basic info
  [2] 2026-04-07T14:52:58 [WIZARD] Step 2: Power supply requirements captured
  [3] 2026-04-07T14:52:59 [WIZARD] Step 3: Components and interfaces specified
  [4] 2026-04-07T15:01:23 [VALIDATION] PASS

Log file: /home/user/my_project/design.log
```

## Logged Events

### Wizard Steps

```json
{
  "type": "wizard_step",
  "step": 1,
  "description": "Requirements captured - basic info",
  "user_input": {"project_name": "...", "purpose": "..."},
  "timestamp": "2026-04-06T10:23:45.123456"
}
```

Records each step of the design wizard, including user input captured at that step.

### CLI Calls

```json
{
  "type": "cli_call",
  "command": "validate",
  "args": ["design.yaml"],
  "return_code": 0,
  "duration_sec": 2.34,
  "generated_files": ["design_report.md"],
  "success": true,
  "timestamp": "2026-04-06T10:24:30.345678"
}
```

Logs every CLI subcommand execution: `validate`, `generate`, `scaffold`, `cost-bom`, etc.
Captures return code, execution time, files created, and any error output.

### Validation Results

```json
{
  "type": "validation",
  "spec_file": "design.yaml",
  "passed": true,
  "error_count": 0,
  "warning_count": 2,
  "errors": [],
  "warnings": ["C1: capacitance...", "Missing datasheet..."],
  "timestamp": "2026-04-06T10:24:35.456789"
}
```

Records validation pass/fail, error counts, and summary of issues.

### Research Queries

```json
{
  "type": "research",
  "phase": "project_context",
  "status": "ok",
  "result_count": 5,
  "query_length": 287,
  "timestamp": "2026-04-06T10:25:00.567890"
}
```

Logs Perplexity research agent calls (when using `/circuit-weaver` skill in Claude Code).
Tracks query phases, status, and number of results returned.

## Resuming a Design

If you stopped in the middle of designing a circuit, you can check where you left off:

```bash
# See the current state
circuit-weaver log-status my_project/

# This tells you:
# - Which wizard step you completed last
# - Whether design.yaml was generated
# - Whether validation passed
# - Which errors need fixing
# - Which CLI commands failed (if any)

# Then resume by editing the spec and running the next step:
circuit-weaver validate my_project/design.yaml
circuit-weaver generate my_project/design.yaml -o my_project/output/
```

## Troubleshooting with Logs

### "Command failed but I don't know why"

Check the detailed log:

```bash
# View raw JSON log
cat my_project/design.log | jq '.[] | select(.success == false)'

# Shows: return code, stderr, duration, which files were affected
```

### "I'm stuck — don't remember what I decided for requirements"

Look at the first few log entries:

```bash
cat my_project/design.log | jq '.[] | select(.type == "wizard_step")'

# Shows: project name, purpose, power input, interfaces, MCU choice, etc.
```

### "Validation has warnings — do I need to fix them?"

Check the log:

```bash
cat my_project/design.log | jq '.[] | select(.type == "validation")'

# Shows: warning count, specific warnings (first 5)
# Warnings = non-critical; you can proceed
# Errors = critical; must fix before generation
```

## Log Size & Cleanup

The log file is lightweight — typically < 10 KB for a complete design workflow.

If you want to archive an old design, keep `design.log` with `design.yaml` as a record of what decisions were made.

To start fresh on a new design, create a new directory — the logger automatically creates a fresh `design.log` in each project directory.

## Integration with Claude Code Skills

When using `/circuit-weaver` skill in Claude Code:

1. The skill creates/updates `design.log` automatically
2. Each research query, CLI call, and validation is logged
3. If the skill crashes or times out, `design.log` shows exactly where
4. You can check `log-status` to understand why the design failed

Example workflow:

```bash
# In Claude Code, start the skill
/circuit-weaver

# ... (skill runs through steps 1-5)
# ... (something fails on step 6)

# In terminal, check what went wrong:
circuit-weaver log-status <project_dir>

# Output shows: last successful step was 5 (validation PASSED)
# No entries for step 6 (generation) yet
# This tells you the issue happened during generation command
```

## Python API

If you're integrating Circuit Weaver into your own tools:

```python
from src.circuit_weaver.design_logger import DesignLogger

# Create a logger for your project
logger = DesignLogger("my_project/")

# Log a wizard step
logger.log_step(1, "Requirements captured", {
    "project_name": "My Board",
    "purpose": "WiFi sensor"
})

# Log a CLI call
logger.log_cli_call(
    command="validate",
    args=["design.yaml"],
    return_code=0,
    duration_sec=2.34,
    generated_files=["report.md"]
)

# Get a summary
summary = logger.get_summary()
print(summary)

# Print human-readable status
logger.print_summary()
```
