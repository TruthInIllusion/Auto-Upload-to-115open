from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


TERMINAL_STATES = {"completed", "failed", "skipped"}
ACTIVE_STATES = {"queued", "scheduled", "retry_scheduled", "running"}


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class UploadTask:
    task_id: str
    source_path: str
    matched_watch_dir: str
    remote_target_path: str
    delay_seconds: int
    max_retries: int
    attempts_done: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "UploadTask":
        return cls(
            task_id=str(raw["task_id"]),
            source_path=str(raw["source_path"]),
            matched_watch_dir=str(raw["matched_watch_dir"]),
            remote_target_path=str(raw["remote_target_path"]),
            delay_seconds=int(raw["delay_seconds"]),
            max_retries=int(raw.get("max_retries", 3)),
            attempts_done=int(raw.get("attempts_done", 0)),
            created_at=str(raw.get("created_at") or utc_now_iso()),
            updated_at=str(raw.get("updated_at") or utc_now_iso()),
        )


@dataclass
class TaskState:
    task_id: str
    source_path: str
    status: str
    attempts: int = 0
    max_retries: int = 3
    remote_target_path: str = ""
    scheduler: str = ""
    last_error: str = ""
    last_unit: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskState":
        return cls(
            task_id=str(raw["task_id"]),
            source_path=str(raw.get("source_path", "")),
            status=str(raw.get("status", "queued")),
            attempts=int(raw.get("attempts", 0)),
            max_retries=int(raw.get("max_retries", 3)),
            remote_target_path=str(raw.get("remote_target_path", "")),
            scheduler=str(raw.get("scheduler", "")),
            last_error=str(raw.get("last_error", "")),
            last_unit=str(raw.get("last_unit", "")),
            updated_at=str(raw.get("updated_at") or utc_now_iso()),
            created_at=str(raw.get("created_at") or utc_now_iso()),
        )
