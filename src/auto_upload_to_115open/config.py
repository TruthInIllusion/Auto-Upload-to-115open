from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_WATCH_DIR = "/mnt/seedbox/complete/"
DEFAULT_TARGET_ROOT = "/115open"
DEFAULT_QUEUE_DIR = "/var/lib/auto_uploader/queue"
DEFAULT_STATE_DIR = "/var/lib/auto_uploader/state"
DEFAULT_DELAY_MINUTES = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2.0


def _parse_bool(raw: Optional[str], default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: Optional[str], default: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _parse_float(raw: Optional[str], default: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _split_watch_dirs(raw: str) -> list[str]:
    tokens = raw.replace(",", ":").split(":")
    watch_dirs: list[str] = []
    for token in tokens:
        item = token.strip()
        if not item:
            continue
        watch_dirs.append(item)
    return watch_dirs or [DEFAULT_WATCH_DIR]


def _normalize_watch_dir(path: str) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    text = str(resolved)
    if not text.endswith("/"):
        text += "/"
    return text


def _normalize_cloud_path(path: str) -> str:
    path = path.strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


@dataclass(frozen=True)
class Settings:
    cd2_addr: str
    cd2_use_tls: bool
    cd2_token: str
    cd2_target_root: str
    cd2_delay_minutes: int
    cd2_watch_dirs: tuple[str, ...]
    cd2_max_retries: int
    cd2_retry_backoff: float
    cd2_queue_dir: Path
    cd2_state_dir: Path
    worker_script: Path

    @property
    def delay_seconds(self) -> int:
        return max(1, self.cd2_delay_minutes) * 60



def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]

    watch_dirs_raw = os.getenv("CD2_WATCH_DIRS", DEFAULT_WATCH_DIR)
    watch_dirs = tuple(_normalize_watch_dir(item) for item in _split_watch_dirs(watch_dirs_raw))

    worker_script = Path(
        os.getenv("CD2_WORKER_SCRIPT", str((repo_root / "scripts" / "auto_upload_worker.sh").resolve()))
    )

    cd2_addr = os.getenv("CD2_ADDR", "127.0.0.1:19798")
    cd2_use_tls = _parse_bool(os.getenv("CD2_USE_TLS"), default=False)
    cd2_token = os.getenv("CD2_TOKEN", "").strip()
    cd2_target_root = _normalize_cloud_path(os.getenv("CD2_TARGET_ROOT", DEFAULT_TARGET_ROOT))
    cd2_delay_minutes = _parse_int(os.getenv("CD2_DELAY_MINUTES"), DEFAULT_DELAY_MINUTES)
    cd2_max_retries = _parse_int(os.getenv("CD2_MAX_RETRIES"), DEFAULT_MAX_RETRIES)
    cd2_retry_backoff = _parse_float(os.getenv("CD2_RETRY_BACKOFF"), DEFAULT_RETRY_BACKOFF)
    cd2_queue_dir = Path(os.getenv("CD2_QUEUE_DIR", DEFAULT_QUEUE_DIR)).expanduser().resolve(strict=False)
    cd2_state_dir = Path(os.getenv("CD2_STATE_DIR", DEFAULT_STATE_DIR)).expanduser().resolve(strict=False)

    if cd2_max_retries < 1:
        raise ValueError("CD2_MAX_RETRIES must be >= 1")
    if cd2_delay_minutes < 1:
        raise ValueError("CD2_DELAY_MINUTES must be >= 1")

    return Settings(
        cd2_addr=cd2_addr,
        cd2_use_tls=cd2_use_tls,
        cd2_token=cd2_token,
        cd2_target_root=cd2_target_root,
        cd2_delay_minutes=cd2_delay_minutes,
        cd2_watch_dirs=watch_dirs,
        cd2_max_retries=cd2_max_retries,
        cd2_retry_backoff=cd2_retry_backoff,
        cd2_queue_dir=cd2_queue_dir,
        cd2_state_dir=cd2_state_dir,
        worker_script=worker_script,
    )
