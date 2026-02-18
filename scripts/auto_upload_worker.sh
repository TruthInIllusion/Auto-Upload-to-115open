#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f /etc/default/auto-upload-to-115open ]]; then
  set -a
  # shellcheck source=/etc/default/auto-upload-to-115open
  source /etc/default/auto-upload-to-115open
  set +a
fi

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck source=.env
  source "${PROJECT_ROOT}/.env"
  set +a
fi

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <task_file>" >&2
  exit 2
fi

TASK_FILE="$1"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON_BIN}" -m auto_upload_to_115open.worker --task-file "${TASK_FILE}"
