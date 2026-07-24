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
    ) -> dict[str, Any]:
        self.initialize()
        resolved_id = job_id or str(uuid.uuid4())
        now = utc_now()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO image_edit_jobs (
                    id, status, prompt, strength, backend, source_path,
                    source_filename, metadata_json, created_at, updated_at
                ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
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
        }
