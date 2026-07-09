"""SQLite-backed durable generation job state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .image_generation import GenerationProgressEvent, GenerationServiceRequest

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass(frozen=True)
class GenerationJobCreate:
    """Durable job creation payload."""

    prompt: str | None = None
    meta_prompt: str | None = None
    seed: int | None = None
    publication_state: str = "draft"
    client_request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    recipe_id: str | None = None
    recipe_version: int | None = None
    config_overrides: dict[str, Any] = field(default_factory=dict)

    def to_service_request(self, job_id: str) -> GenerationServiceRequest:
        """Convert a persisted job payload to the service request boundary."""
        metadata = {**self.metadata, "job_id": job_id}
        if self.recipe_id:
            metadata["recipe"] = {
                **metadata.get("recipe", {}),
                "id": self.recipe_id,
                "version": self.recipe_version,
            }
        return GenerationServiceRequest(
            prompt=self.prompt,
            meta_prompt=self.meta_prompt,
            seed=self.seed,
            publication_state=self.publication_state,
            metadata=metadata,
        )


class SQLiteGenerationJobStore:
    """Persist generation jobs and progress events in a local SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialized = False

    def initialize(self) -> None:
        """Create the database schema if it does not already exist."""
        if self._initialized:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    client_request_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress INTEGER NOT NULL DEFAULT 0,
                    prompt TEXT,
                    backend TEXT,
                    model_name TEXT,
                    image_path TEXT,
                    relative_image_path TEXT,
                    generation_time REAL,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    progress INTEGER,
                    label TEXT,
                    detail TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(job_id) REFERENCES generation_jobs(id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_jobs_status_updated
                ON generation_jobs(status, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_events_job
                ON generation_job_events(job_id, id)
                """
            )
        self._initialized = True

    def create_job(self, payload: GenerationJobCreate, job_id: str | None = None) -> dict[str, Any]:
        """Create a queued generation job and return its snapshot."""
        self.initialize()
        resolved_job_id = job_id or str(uuid.uuid4())
        now = utc_now()
        request_payload = {
            "prompt": payload.prompt,
            "meta_prompt": payload.meta_prompt,
            "seed": payload.seed,
            "publication_state": payload.publication_state,
            "metadata": payload.metadata,
            "recipe_id": payload.recipe_id,
            "recipe_version": payload.recipe_version,
            "config_overrides": payload.config_overrides,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    id, status, request_json, client_request_id, created_at, updated_at
                )
                VALUES (?, 'queued', ?, ?, ?, ?)
                """,
                (
                    resolved_job_id,
                    json.dumps(request_payload, sort_keys=True),
                    payload.client_request_id,
                    now,
                    now,
                ),
            )
            self._append_event(
                connection,
                resolved_job_id,
                GenerationProgressEvent(
                    name="queued",
                    progress=0,
                    label="Queued",
                    detail="Generation job is waiting for the local worker.",
                ),
            )
        return self.get_job(resolved_job_id) or {}

    def start_job(self, job_id: str) -> dict[str, Any]:
        """Mark a queued job as running."""
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'running',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    attempts = attempts + 1,
                    progress = MAX(progress, 1),
                    error = NULL
                WHERE id = ? AND status NOT IN ('succeeded', 'failed', 'cancelled')
                """,
                (now, now, job_id),
            )
            self._append_event(
                connection,
                job_id,
                GenerationProgressEvent(
                    name="running",
                    progress=1,
                    label="Running",
                    detail="The local generation worker started this job.",
                ),
            )
        return self.get_job(job_id) or {}

    def record_event(self, job_id: str, event: GenerationProgressEvent) -> dict[str, Any]:
        """Persist a generation lifecycle event for a job."""
        self.initialize()
        with self._connect() as connection:
            self._append_event(connection, job_id, event)
            if event.progress is not None:
                connection.execute(
                    """
                    UPDATE generation_jobs
                    SET progress = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (event.progress, utc_now(), job_id),
                )
        return self.get_job(job_id) or {}

    def complete_job(
        self,
        job_id: str,
        *,
        prompt: str,
        image_path: Path,
        relative_image_path: str,
        backend: str,
        model_name: str,
        generation_time: float,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Mark a job as succeeded with generated artifact details."""
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'succeeded',
                    updated_at = ?,
                    completed_at = ?,
                    progress = 100,
                    prompt = ?,
                    backend = ?,
                    model_name = ?,
                    image_path = ?,
                    relative_image_path = ?,
                    generation_time = ?,
                    error = NULL,
                    metadata_json = ?
                WHERE id = ?
                """,
                (
                    now,
                    now,
                    prompt,
                    backend,
                    model_name,
                    str(image_path),
                    relative_image_path,
                    generation_time,
                    json.dumps(metadata, sort_keys=True),
                    job_id,
                ),
            )
            self._append_event(
                connection,
                job_id,
                GenerationProgressEvent(
                    name="succeeded",
                    progress=100,
                    label="Succeeded",
                    detail="Generation job completed successfully.",
                    payload={"image_path": relative_image_path},
                ),
            )
        return self.get_job(job_id) or {}

    def fail_job(self, job_id: str, error: str) -> dict[str, Any]:
        """Mark a job as failed and persist the error."""
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed',
                    updated_at = ?,
                    completed_at = ?,
                    error = ?
                WHERE id = ? AND status NOT IN ('succeeded', 'cancelled')
                """,
                (now, now, error, job_id),
            )
            self._append_event(
                connection,
                job_id,
                GenerationProgressEvent(
                    name="failed",
                    label="Failed",
                    detail=error,
                    payload={"error": error},
                ),
            )
        return self.get_job(job_id) or {}

    def fail_interrupted_jobs(self, error: str) -> list[dict[str, Any]]:
        """Mark queued or running jobs as failed after a process restart."""
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM generation_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [self.fail_job(row["id"], error) for row in rows]

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a queued job."""
        self.initialize()
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'cancelled',
                    updated_at = ?,
                    completed_at = ?,
                    error = 'cancelled'
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            self._append_event(
                connection,
                job_id,
                GenerationProgressEvent(
                    name="cancelled",
                    label="Cancelled",
                    detail="Generation job was cancelled before it started.",
                ),
            )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str, *, include_events: bool = False) -> dict[str, Any] | None:
        """Return a job snapshot by ID."""
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            job = self._row_to_job(row)
            if include_events:
                job["events"] = self.get_events(job_id)
            return job

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent jobs, optionally filtered by status."""
        self.initialize()
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM generation_jobs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return persisted lifecycle events for a job."""
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generation_job_events
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def request_for_job(self, job_id: str) -> GenerationJobCreate | None:
        """Return the original creation payload for a job."""
        job = self.get_job(job_id)
        if job is None:
            return None
        request = job["request"]
        return GenerationJobCreate(
            prompt=request.get("prompt"),
            meta_prompt=request.get("meta_prompt"),
            seed=request.get("seed"),
            publication_state=request.get("publication_state", "draft"),
            client_request_id=job.get("client_request_id"),
            metadata=request.get("metadata") or {},
            recipe_id=request.get("recipe_id"),
            recipe_version=request.get("recipe_version"),
            config_overrides=request.get("config_overrides") or {},
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _append_event(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        event: GenerationProgressEvent,
    ) -> None:
        connection.execute(
            """
            INSERT INTO generation_job_events (
                job_id, timestamp, name, progress, label, detail, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                utc_now(),
                event.name,
                event.progress,
                event.label,
                event.detail,
                json.dumps(event.payload, sort_keys=True, default=str),
            ),
        )

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        request = json.loads(row["request_json"] or "{}")
        metadata = json.loads(row["metadata_json"] or "{}")
        return {
            "id": row["id"],
            "status": row["status"],
            "request": request,
            "client_request_id": row["client_request_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "progress": row["progress"],
            "prompt": row["prompt"],
            "backend": row["backend"],
            "model_name": row["model_name"],
            "image_path": row["image_path"],
            "relative_image_path": row["relative_image_path"],
            "generation_time": row["generation_time"],
            "error": row["error"],
            "attempts": row["attempts"],
            "metadata": metadata,
        }

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "timestamp": row["timestamp"],
            "name": row["name"],
            "progress": row["progress"],
            "label": row["label"],
            "detail": row["detail"],
            "payload": json.loads(row["payload_json"] or "{}"),
        }


def job_payload_from_service_request(
    request: GenerationServiceRequest,
    *,
    client_request_id: str | None = None,
) -> GenerationJobCreate:
    """Build a durable job payload from the service request model."""
    data = asdict(request)
    return GenerationJobCreate(
        prompt=data.get("prompt"),
        meta_prompt=data.get("meta_prompt"),
        seed=data.get("seed"),
        publication_state=data.get("publication_state", "draft"),
        client_request_id=client_request_id,
        metadata=data.get("metadata") or {},
        recipe_id=data.get("recipe_id"),
        recipe_version=data.get("recipe_version"),
        config_overrides=data.get("config_overrides") or {},
    )
