from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Optional

from auto_upload_to_115open.config import load_settings
from auto_upload_to_115open.models import ACTIVE_STATES, TERMINAL_STATES, TaskState, UploadTask
from auto_upload_to_115open.path_rules import (
    build_remote_target_path,
    match_watch_dir,
    normalize_local_path,
)
from auto_upload_to_115open.scheduler import SchedulingError, schedule_worker
from auto_upload_to_115open.task_store import TaskStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Queue upload task by completed path and schedule delayed worker",
    )
    parser.add_argument("--completed-path", required=True, help="qBittorrent completed content path")
    return parser


def _should_skip_existing(state: TaskState) -> bool:
    if state.status in ACTIVE_STATES:
        return True
    if state.status == "completed":
        return True
    if state.status == "failed" and state.attempts >= state.max_retries:
        return True
    if state.status in TERMINAL_STATES and state.status != "failed":
        return True
    return False


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()
    store = TaskStore(settings.cd2_queue_dir, settings.cd2_state_dir)
    store.ensure_dirs()

    completed_path = normalize_local_path(args.completed_path)
    matched_watch_dir = match_watch_dir(completed_path, settings.cd2_watch_dirs)
    if matched_watch_dir is None:
        print(f"skip: completed path not in CD2_WATCH_DIRS -> {completed_path}")
        return 0
    if not Path(completed_path).exists():
        print(f"error: completed path does not exist: {completed_path}", file=sys.stderr)
        return 1

    remote_target_path = build_remote_target_path(
        completed_path=completed_path,
        matched_watch_dir=matched_watch_dir,
        target_root=settings.cd2_target_root,
    )

    task_id = store.task_id_from_path(completed_path)

    with store.task_lock(task_id):
        state = store.load_state(task_id)
        if state and _should_skip_existing(state):
            print(
                f"skip: task already tracked task_id={task_id} status={state.status} attempts={state.attempts}"
            )
            return 0

        attempts_done = state.attempts if state else 0
        task = UploadTask(
            task_id=task_id,
            source_path=completed_path,
            matched_watch_dir=matched_watch_dir,
            remote_target_path=remote_target_path,
            delay_seconds=settings.delay_seconds,
            max_retries=settings.cd2_max_retries,
            attempts_done=attempts_done,
        )
        task_file = store.save_task(task)

        try:
            sched = schedule_worker(
                settings=settings,
                task_file=task_file,
                task_id=task_id,
                delay_seconds=settings.delay_seconds,
                reason="initial",
            )
        except SchedulingError as exc:
            failed_state = TaskState(
                task_id=task_id,
                source_path=completed_path,
                status="failed",
                attempts=attempts_done,
                max_retries=settings.cd2_max_retries,
                remote_target_path=remote_target_path,
                scheduler="",
                last_error=str(exc),
            )
            store.save_state(failed_state)
            print(f"error: {exc}", file=sys.stderr)
            return 1

        new_state = TaskState(
            task_id=task_id,
            source_path=completed_path,
            status="scheduled",
            attempts=attempts_done,
            max_retries=settings.cd2_max_retries,
            remote_target_path=remote_target_path,
            scheduler=sched.scheduler,
            last_unit=sched.unit_name,
        )
        store.save_state(new_state)

    print(
        "queued: "
        f"task_id={task_id} source={completed_path} remote={remote_target_path} "
        f"delay={settings.cd2_delay_minutes}m scheduler={new_state.scheduler} unit={new_state.last_unit}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
