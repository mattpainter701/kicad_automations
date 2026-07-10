"""Truthful delivery-state manifest for generated manufacturing artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DeliveryArtifact:
    kind: str
    path: str
    status: str  # ready | omitted | blocked
    fabrication_ready: bool = False
    reason: str = ""


@dataclass
class DeliveryManifest:
    status: str  # ok | bom_only | blocked | error
    assembly_ready: bool
    fabrication_ready: bool
    assembly_item_count: int
    artifacts: list[DeliveryArtifact] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "assembly_ready": self.assembly_ready,
            "fabrication_ready": self.fabrication_ready,
            "assembly_item_count": self.assembly_item_count,
            "blocked_reasons": list(self.blocked_reasons),
            "warnings": list(self.warnings),
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
        }

    def write_json(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8", newline="")
        return path
