from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .archive_index import ArchiveEntry


class ArchiveDatabase:
    """SQLite cache for the archive browser.

    group JSON remains the source of truth; this database is rebuildable and
    only used for fast filtering/reporting.
    """

    SCHEMA_VERSION = 1

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.path = output_root / ".birdroost" / "index.sqlite"
        self._connection: sqlite3.Connection | None = None

    def _conn(self) -> sqlite3.Connection | None:
        if not self.path.parent.exists():
            return None
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    status TEXT,
                    source_relative_path TEXT,
                    observation_location TEXT,
                    observation_time TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS copies (
                    relative_path TEXT PRIMARY KEY,
                    group_id TEXT,
                    species_cn TEXT,
                    species_latin TEXT,
                    target_indices TEXT
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    started_at TEXT,
                    finished_at TEXT,
                    summary_json TEXT
                );
                CREATE TABLE IF NOT EXISTS entries (
                    relative_path TEXT PRIMARY KEY,
                    folder TEXT,
                    species_cn TEXT,
                    species_latin TEXT,
                    group_id TEXT,
                    batch_id TEXT,
                    observation_location TEXT,
                    observation_time TEXT,
                    status TEXT,
                    special TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    mtime REAL
                );
                CREATE INDEX IF NOT EXISTS idx_entries_batch ON entries(batch_id);
                CREATE INDEX IF NOT EXISTS idx_entries_location ON entries(observation_location);
                CREATE INDEX IF NOT EXISTS idx_groups_batch_status ON groups(batch_id, status);
                """
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
            self._connection.commit()
        return self._connection

    def sync(
        self,
        entries: Iterable[ArchiveEntry],
        groups: dict[str, dict],
        batches: Iterable[dict],
    ) -> None:
        connection = self._conn()
        if connection is None:
            return
        entries = list(entries)
        paths = {entry.relative_path for entry in entries}
        with connection:
            connection.execute("DELETE FROM copies")
            connection.execute("DELETE FROM groups")
            connection.execute("DELETE FROM batches")
            for group in groups.values():
                observation = group.get("observation") or {}
                connection.execute(
                    "INSERT INTO groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(group.get("group_id", "")),
                        str(group.get("batch_id", "")),
                        str(group.get("status", "")),
                        str(group.get("source_relative_path", "")),
                        str(observation.get("location", "")),
                        str(observation.get("time", "")),
                        str(group.get("error_code", "")),
                        str(group.get("error_message", "")),
                        str(group.get("created_at", "")),
                    ),
                )
                for copy in group.get("copies", []):
                    connection.execute(
                        "INSERT OR REPLACE INTO copies VALUES (?, ?, ?, ?, ?)",
                        (
                            str(copy.get("relative_path", "")),
                            str(group.get("group_id", "")),
                            str(copy.get("species_cn", "")),
                            str(copy.get("species_latin", "")),
                            json.dumps(copy.get("target_indices", []), ensure_ascii=False),
                        ),
                    )
            for batch in batches:
                connection.execute(
                    "INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?)",
                    (
                        str(batch.get("batch_id", "")),
                        str(batch.get("started_at", "")),
                        str(batch.get("finished_at", "")),
                        json.dumps(batch.get("summary", {}), ensure_ascii=False),
                    ),
                )
            existing = {
                row[0] for row in connection.execute("SELECT relative_path FROM entries")
            }
            for entry in entries:
                observation = entry.group.get("observation") or {}
                connection.execute(
                    "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.relative_path,
                        entry.folder,
                        entry.species_cn,
                        entry.species_latin,
                        entry.group_id,
                        entry.batch_id,
                        entry.observation_location,
                        entry.observation_time,
                        entry.status,
                        entry.special,
                        entry.error_code,
                        entry.error_message,
                        entry.absolute_path.stat().st_mtime if entry.absolute_path.exists() else 0,
                    ),
                )
            stale = existing - paths
            for relative_path in stale:
                connection.execute("DELETE FROM entries WHERE relative_path = ?", (relative_path,))

    def locations(self, batch_id: str | None = None) -> list[str]:
        connection = self._conn()
        if connection is None:
            return []
        query = "SELECT DISTINCT observation_location FROM entries WHERE observation_location <> ''"
        params: tuple[Any, ...] = ()
        if batch_id:
            query += " AND batch_id = ?"
            params = (batch_id,)
        query += " ORDER BY observation_location"
        return [row[0] for row in connection.execute(query, params)]

    def issues(self, batch_id: str) -> list[dict[str, Any]]:
        connection = self._conn()
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT * FROM groups WHERE batch_id = ? AND status IN ('failed', 'review_pending') "
            "ORDER BY status, source_relative_path",
            (batch_id,),
        )
        issues = []
        for row in rows:
            value = dict(row)
            value["copies"] = "；".join(
                copy[0] for copy in connection.execute(
                    "SELECT relative_path FROM copies WHERE group_id = ?",
                    (value["group_id"],),
                )
            )
            issues.append(value)
        return issues

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def count(self) -> int:
        connection = self._conn()
        if connection is None:
            return 0
        return int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
