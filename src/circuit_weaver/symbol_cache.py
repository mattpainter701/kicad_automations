"""Smart symbol caching layer — 30-day TTL cache for resolved symbols.

Caches symbol resolution results (footprint, MPN, manufacturer, LCSC number, datasheet)
to `~/.cache/circuit-weaver/symbols/` with an `index.json` manifest. Avoids repeated
API queries for the same parts during development or CI/CD runs.

Usage:
    from circuit_weaver.symbol_cache import SymbolCache
    cache = SymbolCache()

    # Get cached data (None if miss or expired)
    data = cache.get("TPS62A01DRLR")

    # Store resolved component
    cache.put("TPS62A01DRLR", {
        "source": "digikey",
        "footprint": "Package_TO_SOT_SMD:SOT-23-5",
        "lcsc": "C123456",
        "manufacturer": "Texas Instruments",
        "description": "Boost converter 2A SOT-23-5",
        "digikey_pn": "296-TPS62A01DRLR-ND"
    })

    # Statistics
    stats = cache.stats()  # {total, fresh, stale, size_bytes, oldest_ts, newest_ts}

    # Maintenance
    cache.clear()                    # Remove all entries
    cache.clear(stale_only=True)     # Remove only entries older than 30 days
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".cache" / "circuit-weaver" / "symbols"
_INDEX_FILE = _CACHE_DIR / "index.json"
_CACHE_MAX_AGE = 30 * 24 * 3600  # 30 days in seconds


class SymbolCache:
    """30-day TTL cache for symbol resolution results.

    Stores one JSON file per MPN (sanitized filename) with full data including
    timestamp. Also maintains an `index.json` manifest for quick stat queries.

    Attributes:
        _dir: Cache directory (default ~/.cache/circuit-weaver/symbols/)
        _index_path: Path to index.json
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize cache, optionally with custom directory.

        Args:
            cache_dir: Optional custom cache directory. Defaults to
                `~/.cache/circuit-weaver/symbols/`.
        """
        self._dir = cache_dir or _CACHE_DIR
        self._index_path = self._dir / "index.json"

    def get(self, mpn: str) -> dict[str, Any] | None:
        """Return cached entry for MPN if present and not expired.

        Args:
            mpn: Manufacturer Part Number (e.g., "TPS62A01DRLR").

        Returns:
            Dict with cached data, or None if cache miss or entry expired.
        """
        entry_path = self._entry_path(mpn)
        if not entry_path.exists():
            return None

        try:
            raw = json.loads(entry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.debug("Cache read failed for %s: %s", mpn, exc)
            return None

        # Check if expired
        ts = raw.get("_cached_at", 0)
        if time.time() - ts > _CACHE_MAX_AGE:
            log.debug("Cache entry %s expired (%.1f days old)", mpn, (time.time() - ts) / 86400)
            return None

        # Remove internal timestamp before returning
        result = {k: v for k, v in raw.items() if k != "_cached_at"}
        return result

    def put(self, mpn: str, data: dict[str, Any]) -> None:
        """Write entry to cache and update index.json.

        Args:
            mpn: Manufacturer Part Number.
            data: Dict with keys like source, footprint, lcsc, manufacturer,
                description, digikey_pn (any keys are accepted).
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        # Write per-entry file with timestamp
        entry_path = self._entry_path(mpn)
        payload = dict(data)
        payload["_cached_at"] = time.time()
        try:
            entry_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("Cache write failed for %s: %s", mpn, exc)
            return

        # Update index with searchable metadata
        index = self._load_index()
        index[mpn] = {
            "source": data.get("source", "unknown"),
            "timestamp": payload["_cached_at"],
            "footprint": data.get("footprint", ""),
            "lcsc": data.get("lcsc", ""),
            "manufacturer": data.get("manufacturer", ""),
            "description": data.get("description", ""),
            "digikey_pn": data.get("digikey_pn", ""),
        }
        self._save_index(index)

    def stats(self) -> dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with keys: total, fresh, stale, size_bytes, oldest_ts, newest_ts,
            error (if any error occurred during stat collection).
        """
        try:
            if not self._dir.exists():
                return {"total": 0, "fresh": 0, "stale": 0, "size_bytes": 0, "oldest_ts": 0, "newest_ts": 0}

            now = time.time()
            total = 0
            fresh = 0
            stale = 0
            size_bytes = 0
            oldest_ts = now
            newest_ts = 0

            for entry_file in self._dir.glob("*.json"):
                if entry_file.name == "index.json":
                    continue

                try:
                    data = json.loads(entry_file.read_text(encoding="utf-8"))
                    ts = data.get("_cached_at", 0)
                    age = now - ts
                    size_bytes += entry_file.stat().st_size

                    if age <= _CACHE_MAX_AGE:
                        fresh += 1
                    else:
                        stale += 1

                    total += 1
                    oldest_ts = min(oldest_ts, ts)
                    newest_ts = max(newest_ts, ts)
                except (json.JSONDecodeError, OSError):
                    # Skip corrupted files
                    continue

            return {
                "total": total,
                "fresh": fresh,
                "stale": stale,
                "size_bytes": size_bytes,
                "oldest_ts": oldest_ts,
                "newest_ts": newest_ts,
            }
        except Exception as exc:
            log.error("Stats collection failed: %s", exc)
            return {"error": str(exc)}

    def clear(self, stale_only: bool = False) -> int:
        """Remove cache entries.

        Args:
            stale_only: If True, only remove entries older than 30 days.
                       If False, remove all entries.

        Returns:
            Number of entries deleted.
        """
        if not self._dir.exists():
            return 0

        now = time.time()
        deleted = 0

        for entry_file in self._dir.glob("*.json"):
            if entry_file.name == "index.json":
                continue

            if stale_only:
                try:
                    data = json.loads(entry_file.read_text(encoding="utf-8"))
                    ts = data.get("_cached_at", 0)
                    age = now - ts
                    if age < _CACHE_MAX_AGE:
                        continue  # Keep fresh entries
                except (json.JSONDecodeError, OSError):
                    pass  # Treat corrupted files as stale

            try:
                entry_file.unlink()
                deleted += 1
            except OSError as exc:
                log.debug("Failed to delete cache entry %s: %s", entry_file.name, exc)

        # Rewrite empty index
        if deleted > 0:
            self._save_index({})

        return deleted

    def _entry_path(self, mpn: str) -> Path:
        """Return the on-disk cache path for an MPN (sanitised filename).

        Args:
            mpn: Manufacturer Part Number.

        Returns:
            Path to the cache file for this MPN.
        """
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in mpn)
        return self._dir / f"{safe}.json"

    def _load_index(self) -> dict[str, Any]:
        """Load index.json, return empty dict on missing/corrupt."""
        if not self._index_path.exists():
            return {}

        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_index(self, index: dict[str, Any]) -> None:
        """Atomically write index.json using tmp → replace pattern."""
        self._dir.mkdir(parents=True, exist_ok=True)

        tmp_path = self._index_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._index_path)  # Atomic on POSIX; best-effort on Windows
        except OSError as exc:
            log.debug("Index write failed: %s", exc)
