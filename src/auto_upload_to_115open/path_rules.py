from __future__ import annotations

from pathlib import Path
from typing import Optional


def normalize_local_path(raw_path: str) -> str:
    return str(Path(raw_path).expanduser().resolve(strict=False))


def match_watch_dir(completed_path: str, watch_dirs: tuple[str, ...]) -> Optional[str]:
    completed = normalize_local_path(completed_path)
    for watch_dir in watch_dirs:
        normalized = normalize_local_path(watch_dir)
        if not normalized.endswith("/"):
            normalized += "/"

        if completed == normalized.rstrip("/") or completed.startswith(normalized):
            return normalized
    return None


def join_cloud_path(base: str, extra: str) -> str:
    base = base if base.startswith("/") else f"/{base}"
    base = base.rstrip("/") or "/"
    parts = [p for p in extra.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return base
    if base == "/":
        return "/" + "/".join(parts)
    return base + "/" + "/".join(parts)


def build_remote_target_path(completed_path: str, matched_watch_dir: str, target_root: str) -> str:
    completed = Path(normalize_local_path(completed_path))
    watch_root = Path(normalize_local_path(matched_watch_dir.rstrip("/")))

    if completed == watch_root:
        # qBittorrent generally passes the completed file/folder path. In the rare
        # case the watch root itself is passed, keep only its directory name.
        relative = completed.name
    else:
        relative = str(completed.relative_to(watch_root))

    return join_cloud_path(target_root, relative)
