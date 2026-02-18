from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Optional

from auto_upload_to_115open.config import load_settings
from auto_upload_to_115open.models import TaskState
from auto_upload_to_115open.scheduler import SchedulingError, schedule_worker
from auto_upload_to_115open.task_store import TaskStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one queued upload task")
    parser.add_argument("--task-file", required=True, help="Task json file path")
    return parser


def _compute_retry_delay(base_delay_seconds: int, backoff: float, attempts: int) -> int:
    exponent = max(0, attempts - 1)
    return max(60, int(base_delay_seconds * (backoff**exponent)))


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()
    store = TaskStore(settings.cd2_queue_dir, settings.cd2_state_dir)
    store.ensure_dirs()

    task_file = Path(args.task_file).expanduser().resolve(strict=False)
    if not task_file.exists():
        print(f"error: task file not found: {task_file}", file=sys.stderr)
        return 1

    task = store.load_task(task_file)

    with store.task_lock(task.task_id):
        state = store.load_state(task.task_id)
        if state and state.status == "completed":
            print(f"skip: already completed task_id={task.task_id}")
            store.remove_task(task.task_id)
            return 0

        attempts = (state.attempts if state else task.attempts_done) + 1
        running_state = TaskState(
            task_id=task.task_id,
            source_path=task.source_path,
            status="running",
            attempts=attempts,
            max_retries=task.max_retries,
            remote_target_path=task.remote_target_path,
            scheduler=(state.scheduler if state else ""),
            last_unit=(state.last_unit if state else ""),
        )
        store.save_state(running_state)

    try:
        if not settings.cd2_token:
            raise RuntimeError("CD2_TOKEN is empty")

        from auto_upload_to_115open.grpc_client import CloudDriveRemoteUploader

        device_id = store.get_or_create_device_id()
        uploader = CloudDriveRemoteUploader(settings=settings, device_id=device_id)
        try:
            file_count = uploader.upload_path(task.source_path, task.remote_target_path)
        finally:
            uploader.close()

        with store.task_lock(task.task_id):
            completed_state = TaskState(
                task_id=task.task_id,
                source_path=task.source_path,
                status="completed",
                attempts=attempts,
                max_retries=task.max_retries,
                remote_target_path=task.remote_target_path,
                scheduler=(running_state.scheduler or ""),
                last_unit=running_state.last_unit,
            )
            store.save_state(completed_state)
            store.remove_task(task.task_id)

        print(
            f"completed: task_id={task.task_id} uploaded_files={file_count} "
            f"source={task.source_path} remote={task.remote_target_path}"
        )
        return 0

    except Exception as exc:
        error_text = str(exc)

        with store.task_lock(task.task_id):
            current = store.load_state(task.task_id)
            attempts_done = current.attempts if current else attempts

            if attempts_done < task.max_retries:
                retry_delay = _compute_retry_delay(
                    base_delay_seconds=task.delay_seconds,
                    backoff=settings.cd2_retry_backoff,
                    attempts=attempts_done,
                )
                try:
                    sched = schedule_worker(
                        settings=settings,
                        task_file=task_file,
                        task_id=task.task_id,
                        delay_seconds=retry_delay,
                        reason=f"retry{attempts_done}",
                    )
                    retry_state = TaskState(
                        task_id=task.task_id,
                        source_path=task.source_path,
                        status="retry_scheduled",
                        attempts=attempts_done,
                        max_retries=task.max_retries,
                        remote_target_path=task.remote_target_path,
                        scheduler=sched.scheduler,
                        last_unit=sched.unit_name,
                        last_error=error_text,
                    )
                    store.save_state(retry_state)
                    print(
                        "retry-scheduled: "
                        f"task_id={task.task_id} attempts={attempts_done}/{task.max_retries} "
                        f"delay={retry_delay}s scheduler={sched.scheduler} unit={sched.unit_name} "
                        f"error={error_text}",
                        file=sys.stderr,
                    )
                    return 10
                except SchedulingError as sched_exc:
                    error_text = (
                        f"{error_text}; retry scheduling failed: {sched_exc}"
                    )

            failed_state = TaskState(
                task_id=task.task_id,
                source_path=task.source_path,
                status="failed",
                attempts=attempts_done,
                max_retries=task.max_retries,
                remote_target_path=task.remote_target_path,
                scheduler=(current.scheduler if current else ""),
                last_unit=(current.last_unit if current else ""),
                last_error=error_text,
            )
            store.save_state(failed_state)

        print(
            f"failed: task_id={task.task_id} attempts={attempts_done}/{task.max_retries} error={error_text}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
