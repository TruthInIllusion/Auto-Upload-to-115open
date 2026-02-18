from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shlex
import subprocess

from auto_upload_to_115open.config import Settings


@dataclass(frozen=True)
class ScheduleResult:
    scheduler: str
    unit_name: str
    detail: str


class SchedulingError(RuntimeError):
    pass


def _sanitize_unit_part(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
        else:
            allowed.append("-")
    return "".join(allowed)


def schedule_worker(
    settings: Settings,
    task_file: Path,
    task_id: str,
    delay_seconds: int,
    reason: str,
) -> ScheduleResult:
    unit_suffix = _sanitize_unit_part(task_id[:16])
    reason_part = _sanitize_unit_part(reason)
    unit_name = f"auto-upload-115open-{reason_part}-{unit_suffix}"

    systemd_cmd = [
        "systemd-run",
        "--user",
        "--quiet",
        "--collect",
        "--unit",
        unit_name,
        "--on-active",
        f"{int(delay_seconds)}s",
        str(settings.worker_script),
        str(task_file),
    ]

    try:
        systemd = subprocess.run(systemd_cmd, capture_output=True, text=True)
    except OSError as exc:
        systemd = subprocess.CompletedProcess(
            args=systemd_cmd,
            returncode=127,
            stdout="",
            stderr=f"systemd-run unavailable: {exc}",
        )
    if systemd.returncode == 0:
        detail = systemd.stdout.strip() or systemd.stderr.strip() or "scheduled"
        return ScheduleResult(scheduler="systemd-run", unit_name=unit_name, detail=detail)

    at_cmd = ["at", "now", "+", str(max(1, math.ceil(delay_seconds / 60))), "minutes"]
    at_input = f"{shlex.quote(str(settings.worker_script))} {shlex.quote(str(task_file))}\n"
    try:
        at_res = subprocess.run(at_cmd, input=at_input, capture_output=True, text=True)
    except OSError as exc:
        at_res = subprocess.CompletedProcess(
            args=at_cmd,
            returncode=127,
            stdout="",
            stderr=f"at unavailable: {exc}",
        )
    if at_res.returncode == 0:
        detail = at_res.stdout.strip() or at_res.stderr.strip() or "scheduled"
        return ScheduleResult(scheduler="at", unit_name=unit_name, detail=detail)

    raise SchedulingError(
        "failed to schedule worker with systemd-run and at; "
        f"systemd-run exit={systemd.returncode}, stderr={systemd.stderr.strip()!r}; "
        f"at exit={at_res.returncode}, stderr={at_res.stderr.strip()!r}"
    )
