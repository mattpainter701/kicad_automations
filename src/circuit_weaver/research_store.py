"""Persistent store for Circuit Weaver research workflow output.

Sprint 37 Task 160 addresses a user-reported bug: the research workflow
produced no artifacts in the project directory, so users couldn't see
which parts were researched, what citations backed each choice, or
reproduce the selection later.

Every research run now writes three files under ``{project_dir}/research/``:

1. ``{topic_slug}.json`` — structured record: timestamp, query, backend
   (sonar-pro | standard | ...), summary, findings, citations, optional
   raw response body.
2. ``{topic_slug}.md`` — human-readable rendering of the JSON.
3. ``summary.md`` — auto-maintained index listing every research run for
   the project with date, topic, backend, and finding count.

The JSON is the source of truth; the markdown files are regenerated from
it. A ``design.log`` entry is appended via ``DesignLogger.log_research``
so the structured log still tracks each run and references the JSON file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_RESEARCH_SUBDIR = "research"

# Limit slug to 60 chars so generated filenames stay within typical
# filesystem limits on Windows even when prefixed with the project path.
_MAX_SLUG_LEN = 60


@dataclass
class ResearchCitation:
    """A single cited source backing a finding."""

    title: str = ""
    url: str = ""
    snippet: str = ""


@dataclass
class ResearchFinding:
    """A single candidate / recommendation from the research run."""

    title: str = ""
    mpn: str = ""
    summary: str = ""
    cost_usd: float | None = None
    notes: str = ""


@dataclass
class ResearchResult:
    """Full record of a single persisted research invocation."""

    topic: str
    query: str
    backend: str = "unknown"
    summary: str = ""
    findings: list[ResearchFinding] = field(default_factory=list)
    citations: list[ResearchCitation] = field(default_factory=list)
    raw_response: str = ""
    timestamp: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""

    def ensure_timestamp(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def slugify(topic: str) -> str:
    """Turn a free-form topic string into a filesystem-safe slug.

    ``"MCU Selection (Zigbee)"`` → ``"mcu-selection-zigbee"``.
    """
    if not topic:
        return "untitled"
    slug = topic.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        return "untitled"
    return slug[:_MAX_SLUG_LEN]


def _research_dir(project_dir: str | Path) -> Path:
    path = Path(project_dir) / _RESEARCH_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _from_dict(data: dict[str, Any]) -> ResearchResult:
    """Rehydrate a ResearchResult from a JSON-loaded dict, tolerating
    missing optional fields (for external callers that send partial data).
    """
    citations = [ResearchCitation(**c) for c in data.get("citations", []) if isinstance(c, dict)]
    findings = [ResearchFinding(**f) for f in data.get("findings", []) if isinstance(f, dict)]
    return ResearchResult(
        topic=str(data.get("topic", "")),
        query=str(data.get("query", "")),
        backend=str(data.get("backend", "unknown")),
        summary=str(data.get("summary", "")),
        findings=findings,
        citations=citations,
        raw_response=str(data.get("raw_response", "")),
        timestamp=str(data.get("timestamp", "")),
        tokens_in=int(data.get("tokens_in", 0) or 0),
        tokens_out=int(data.get("tokens_out", 0) or 0),
        model=str(data.get("model", "")),
    )


def _render_markdown(result: ResearchResult) -> str:
    lines: list[str] = []
    lines.append(f"# {result.topic or 'Untitled research'}")
    lines.append("")
    meta_rows = [
        ("Backend", result.backend or "unknown"),
        ("Timestamp", result.timestamp or "?"),
    ]
    if result.model:
        meta_rows.append(("Model", result.model))
    if result.tokens_in or result.tokens_out:
        meta_rows.append(("Tokens", f"{result.tokens_in} in / {result.tokens_out} out"))
    lines.append("| Field | Value |")
    lines.append("|-|-|")
    for k, v in meta_rows:
        lines.append(f"| {k} | {v} |")
    lines.append("")
    if result.query:
        lines.append("## Query")
        lines.append("")
        lines.append("```")
        lines.append(result.query.strip())
        lines.append("```")
        lines.append("")
    if result.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(result.summary.strip())
        lines.append("")
    if result.findings:
        lines.append("## Findings")
        lines.append("")
        for i, f in enumerate(result.findings, 1):
            head = f.title or f.mpn or f"Option {i}"
            cost = f" — ${f.cost_usd:.2f}" if f.cost_usd is not None else ""
            lines.append(f"{i}. **{head}**{cost}")
            if f.mpn and f.mpn != f.title:
                lines.append(f"   - MPN: `{f.mpn}`")
            if f.summary:
                lines.append(f"   - {f.summary}")
            if f.notes:
                lines.append(f"   - Notes: {f.notes}")
        lines.append("")
    if result.citations:
        lines.append("## Citations")
        lines.append("")
        for c in result.citations:
            title = c.title or c.url
            url = c.url
            if url:
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")
            if c.snippet:
                lines.append(f"  > {c.snippet}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _rebuild_summary(research_dir: Path) -> None:
    """Regenerate ``summary.md`` from every JSON file in ``research_dir``."""
    entries: list[tuple[str, str, str, int, int]] = []  # (timestamp, topic, backend, findings, citations)
    for json_path in sorted(research_dir.glob("*.json")):
        if json_path.name == "summary.json":
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(
            (
                str(data.get("timestamp", "?")),
                str(data.get("topic", json_path.stem)),
                str(data.get("backend", "unknown")),
                len(data.get("findings", []) or []),
                len(data.get("citations", []) or []),
            )
        )

    entries.sort(key=lambda row: row[0], reverse=True)

    lines = [
        "# Research log",
        "",
        "Auto-generated index of every research run recorded for this project.",
        "Source of truth is the per-topic `*.json` file next to this summary.",
        "",
        "| Timestamp | Topic | Backend | Findings | Citations |",
        "|-|-|-|-|-|",
    ]
    if not entries:
        lines.append("| (no research runs yet) | | | | |")
    else:
        for ts, topic, backend, findings, cits in entries:
            lines.append(f"| {ts} | {topic} | {backend} | {findings} | {cits} |")
    lines.append("")
    (research_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def save_research_result(
    project_dir: str | Path,
    result: ResearchResult,
) -> Path:
    """Persist a :class:`ResearchResult` to ``{project_dir}/research/``.

    Writes three files:
    - ``{slug}.json`` — canonical structured record (atomic via tmp-rename)
    - ``{slug}.md`` — human-readable rendering
    - ``summary.md`` — regenerated index

    Returns the path of the canonical JSON file.
    """
    result.ensure_timestamp()
    research_dir = _research_dir(project_dir)
    slug = slugify(result.topic)

    json_path = research_dir / f"{slug}.json"
    md_path = research_dir / f"{slug}.md"

    payload = asdict(result)
    tmp_path = json_path.with_suffix(json_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(json_path)

    md_path.write_text(_render_markdown(result), encoding="utf-8")
    _rebuild_summary(research_dir)

    # Mirror into design.log so the structured log reflects the run.
    try:
        from .logging_bridge import get_design_logger

        dl = get_design_logger()
        if dl is not None:
            dl.log_research(
                query_phase=result.topic or slug,
                query=result.query,
                status="ok",
                result_count=len(result.findings),
                backend=result.backend,
                artifact_path=str(json_path),
            )
    except Exception:  # pragma: no cover — logging must not raise
        pass

    _logger.info(
        "Saved research topic '%s' (backend=%s, findings=%d, citations=%d) → %s",
        result.topic or slug,
        result.backend,
        len(result.findings),
        len(result.citations),
        json_path,
    )
    return json_path


def save_research_from_dict(
    project_dir: str | Path,
    data: dict[str, Any],
) -> Path:
    """Convenience wrapper: accepts a plain dict (as produced by agents or
    piped through the CLI) and saves it as a :class:`ResearchResult`.
    """
    return save_research_result(project_dir, _from_dict(data))


def load_research_result(path: str | Path) -> ResearchResult:
    """Load a previously-saved research JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _from_dict(data)


def list_research_topics(project_dir: str | Path) -> list[dict[str, Any]]:
    """Return metadata for every saved research run in ``project_dir``.

    Each entry: ``{topic, backend, timestamp, findings, citations, path}``.
    """
    research_dir = Path(project_dir) / _RESEARCH_SUBDIR
    if not research_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for json_path in sorted(research_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "topic": data.get("topic", json_path.stem),
                "backend": data.get("backend", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "findings": len(data.get("findings", []) or []),
                "citations": len(data.get("citations", []) or []),
                "path": str(json_path),
            }
        )
    return out
