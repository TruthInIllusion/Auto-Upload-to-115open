from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Optional
import uuid

from auto_upload_to_115open.models import TaskState, UploadTask, utc_now_iso


class TaskStore:
    def __init__(self, queue_dir: Path, state_dir: Path) -> None:
        self.queue_dir = queue_dir
        self.state_dir = state_dir
        self.lock_dir = self.state_dir / "locks"
        self.device_id_file = self.state_dir / "device_id"

    def ensure_dirs(self) -> None:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def task_id_from_path(source_path: str) -> str:
        return hashlib.sha256(source_path.encode("utf-8")).hexdigest()

    def task_file(self, task_id: str) -> Path:
        return self.queue_dir / f"{task_id}.json"

    def state_file(self, task_id: str) -> Path:
        return self.state_dir / f"{task_id}.json"

    @contextmanager
    def task_lock(self, task_id: str):
        lock_path = self.lock_dir / f"{task_id}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as fp:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)

    def load_task(self, task_file: Path) -> UploadTask:
        raw = self._load_json(task_file)
        return UploadTask.from_dict(raw)

    def save_task(self, task: UploadTask) -> Path:
        task.updated_at = utc_now_iso()
        path = self.task_file(task.task_id)
        self._atomic_write_json(path, task.to_dict())
        return path

    def remove_task(self, task_id: str) -> None:
        path = self.task_file(task_id)
        if path.exists():
            path.unlink()

    def load_state(self, task_id: str) -> Optional[TaskState]:
        path = self.state_file(task_id)
        if not path.exists():
            return None
        raw = self._load_json(path)
        return TaskState.from_dict(raw)

    def save_state(self, state: TaskState) -> None:
        state.updated_at = utc_now_iso()
        path = self.state_file(state.task_id)
        self._atomic_write_json(path, state.to_dict())

    def get_or_create_device_id(self) -> str:
        self.ensure_dirs()
        with self.task_lock("device_id"):
            if self.device_id_file.exists():
                value = self.device_id_file.read_text(encoding="utf-8").strip()
                if value:
                    return value

            value = uuid.uuid4().hex
            self.device_id_file.write_text(value + "\n", encoding="utf-8")
            return value

    @staticmethod
    def _load_json(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=True, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            temp_path = Path(tmp.name)

        temp_path.replace(path)
