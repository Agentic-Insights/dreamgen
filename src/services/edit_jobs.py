"""Durable local state for image-edit workflows."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class SQLiteEditJobStore:
    """Persist image-edit requests and their source/output lineage."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS image_edit_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    strength REAL NOT NULL,
                    backend TEXT NOT NULL,
                    source_path TEXT,
                    source_filename TEXT,
                    original_path TEXT,
                    edited_path TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(image_edit_jobs)").fetchall()
            }
            migrations = {
                "root_job_id": "TEXT",
                "parent_job_id": "TEXT",
                "version": "INTEGER NOT NULL DEFAULT 1",
                "decision_state": "TEXT NOT NULL DEFAULT 'pending'",
                "manifest_path": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE image_edit_jobs ADD COLUMN {name} {definition}"
                    )
        self._initialized = True

    def create_job(
        self,
        *,
        prompt: str,
        strength: float,
        backend: str,
        source_path: str | None = None,
        source_filename: str | None = None,
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
        root_job_id: str | None = None,
        parent_job_id: str | None = None,
        version: int = 1,
    ) -> dict[str, Any]:
        self.initialize()
        resolved_id = job_id or str(uuid.uuid4())
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO image_edit_jobs (
                    id, status, prompt, strength, backend, source_path,
                    source_filename, metadata_json, created_at, updated_at,
                    root_job_id, parent_job_id, version
                ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    prompt,
                    strength,
                    backend,
                    source_path,
                    source_filename,
                    json.dumps(metadata or {}, sort_keys=True, default=str),
                    now,
                    now,
                    root_job_id or resolved_id,
                    parent_job_id,
                    version,
                ),
            )
        return self.get_job(resolved_id) or {}

    def start_job(self, job_id: str) -> dict[str, Any]:
        self.initialize()
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE image_edit_jobs
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, job_id),
            )
        return self.get_job(job_id) or {}

    def complete_job(
        self,
        job_id: str,
        *,
        original_path: str,
        edited_path: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE image_edit_jobs
                SET status = 'succeeded', original_path = ?, edited_path = ?,
                    metadata_json = ?, updated_at = ?, completed_at = ?, error = NULL
                WHERE id = ?
                """,
                (
                    original_path,
                    edited_path,
                    json.dumps(metadata, sort_keys=True, default=str),
                    now,
                    now,
                    job_id,
                ),
            )
        return self.get_job(job_id) or {}

    def fail_job(self, job_id: str, error: str) -> dict[str, Any]:
        self.initialize()
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE image_edit_jobs
                SET status = 'failed', error = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (error, now, now, job_id),
            )
        return self.get_job(job_id) or {}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel queued work or record a best-effort cancellation request."""
        self.initialize()
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT status FROM image_edit_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row and row[0] == "queued":
                connection.execute(
                    "UPDATE image_edit_jobs SET status = 'cancelled', updated_at = ?, "
                    "completed_at = ? WHERE id = ?",
                    (now, now, job_id),
                )
            elif row and row[0] == "running":
                connection.execute(
                    "UPDATE image_edit_jobs SET status = 'cancelling', updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
        return self.get_job(job_id) or {}

    def finish_cancellation(self, job_id: str) -> dict[str, Any]:
        self.initialize()
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE image_edit_jobs SET status = 'cancelled', updated_at = ?, completed_at = ? "
                "WHERE id = ? AND status = 'cancelling'",
                (now, now, job_id),
            )
        return self.get_job(job_id) or {}

    def set_decision(
        self, job_id: str, decision: str, *, manifest_path: str | None = None
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected", "pending"}:
            raise ValueError(f"Invalid edit decision: {decision}")
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE image_edit_jobs SET decision_state = ?, manifest_path = COALESCE(?, manifest_path), "
                "updated_at = ? WHERE id = ? AND status = 'succeeded'",
                (decision, manifest_path, utc_now(), job_id),
            )
        return self.get_job(job_id) or {}

    def list_jobs(self, root_job_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        query = "SELECT id FROM image_edit_jobs"
        params: list[Any] = []
        if root_job_id:
            query += " WHERE root_job_id = ?"
            params.append(root_job_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [job for row in rows if (job := self.get_job(row[0])) is not None]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM image_edit_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "status": row["status"],
            "prompt": row["prompt"],
            "strength": row["strength"],
            "backend": row["backend"],
            "source_path": row["source_path"],
            "source_filename": row["source_filename"],
            "original_path": row["original_path"],
            "edited_path": row["edited_path"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "root_job_id": row["root_job_id"] or row["id"],
            "parent_job_id": row["parent_job_id"],
            "version": row["version"],
            "decision_state": row["decision_state"],
            "manifest_path": row["manifest_path"],
        }
