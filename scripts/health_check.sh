#!/usr/bin/env bash
set -euo pipefail

RUN_USER="${RUN_USER:-seedbox}"
INSTALL_DIR="${INSTALL_DIR:-/opt/auto-upload-to-115open}"
CONFIG_FILE="${CONFIG_FILE:-/etc/default/auto-upload-to-115open}"
QUEUE_DIR="${QUEUE_DIR:-/var/lib/auto_uploader/queue}"
STATE_DIR="${STATE_DIR:-/var/lib/auto_uploader/state}"

if ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "[FAIL] RUN_USER not found: $RUN_USER"
  exit 2
fi

RUN_UID="$(id -u "$RUN_USER")"
XDG_RUNTIME_DIR="/run/user/${RUN_UID}"
CURRENT_USER="$(id -un)"

run_as_user() {
  if [[ "$CURRENT_USER" == "$RUN_USER" ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$RUN_USER" "$@"
    return
  fi
  return 1
}

pass() { echo "[PASS] $*"; }
warn() { echo "[WARN] $*"; }
fail() { echo "[FAIL] $*"; }

FAIL_COUNT=0
WARN_COUNT=0

check_file_exists() {
  local f="$1"
  local title="$2"
  if [[ -e "$f" ]]; then
    pass "$title exists: $f"
  else
    fail "$title missing: $f"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

check_readable_by_run_user() {
  local f="$1"
  local title="$2"
  if run_as_user test -r "$f"; then
    pass "$title readable by $RUN_USER"
  else
    fail "$title NOT readable by $RUN_USER"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

check_dir_writable_by_run_user() {
  local d="$1"
  local title="$2"
  if run_as_user test -w "$d"; then
    pass "$title writable by $RUN_USER"
  else
    fail "$title NOT writable by $RUN_USER"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

check_file_exists "$INSTALL_DIR" "install dir"
check_file_exists "$INSTALL_DIR/scripts/auto_upload_enqueue.sh" "enqueue script"
check_file_exists "$INSTALL_DIR/scripts/auto_upload_worker.sh" "worker script"
check_file_exists "$INSTALL_DIR/scripts/generate_stubs.sh" "stub generator"
check_file_exists "$INSTALL_DIR/.venv/bin/python" "venv python"
check_file_exists "$INSTALL_DIR/src/auto_upload_to_115open/generated/clouddrive_pb2.py" "clouddrive_pb2.py"
check_file_exists "$INSTALL_DIR/src/auto_upload_to_115open/generated/clouddrive_pb2_grpc.py" "clouddrive_pb2_grpc.py"
check_file_exists "$CONFIG_FILE" "config file"

if [[ -f "$CONFIG_FILE" ]]; then
  check_readable_by_run_user "$CONFIG_FILE" "config file"
fi

if [[ -d "$QUEUE_DIR" ]]; then
  check_dir_writable_by_run_user "$QUEUE_DIR" "queue dir"
else
  fail "queue dir missing: $QUEUE_DIR"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

if [[ -d "$STATE_DIR" ]]; then
  check_dir_writable_by_run_user "$STATE_DIR" "state dir"
else
  fail "state dir missing: $STATE_DIR"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet atd; then
    pass "atd service is active"
  else
    warn "atd service is NOT active (systemd-run unavailable时将无法回退 at)"
    WARN_COUNT=$((WARN_COUNT + 1))
  fi
else
  warn "systemctl not found; skip atd and user systemd checks"
  WARN_COUNT=$((WARN_COUNT + 1))
fi

if command -v loginctl >/dev/null 2>&1; then
  if loginctl show-user "$RUN_USER" -p Linger --value | grep -qi '^yes$'; then
    pass "linger enabled for $RUN_USER"
  else
    warn "linger is NOT enabled for $RUN_USER"
    WARN_COUNT=$((WARN_COUNT + 1))
  fi
else
  warn "loginctl not found; skip linger check"
  WARN_COUNT=$((WARN_COUNT + 1))
fi

if command -v systemctl >/dev/null 2>&1; then
  if run_as_user env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" systemctl --user status >/dev/null 2>&1; then
    pass "user systemd is available"
  else
    fail "user systemd unavailable for $RUN_USER"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
fi

if [[ -f "$CONFIG_FILE" ]]; then
  set +u
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set -u

  if [[ -n "${CD2_ADDR:-}" ]]; then
    pass "CD2_ADDR set: ${CD2_ADDR}"
  else
    fail "CD2_ADDR is empty"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

  if [[ -n "${CD2_TOKEN:-}" ]]; then
    pass "CD2_TOKEN is set (hidden)"
  else
    fail "CD2_TOKEN is empty"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

  if [[ -n "${CD2_WATCH_DIRS:-}" ]]; then
    pass "CD2_WATCH_DIRS set: ${CD2_WATCH_DIRS}"
  else
    fail "CD2_WATCH_DIRS is empty"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

  if [[ -n "${CD2_TARGET_ROOT:-}" ]]; then
    pass "CD2_TARGET_ROOT set: ${CD2_TARGET_ROOT}"
  else
    fail "CD2_TARGET_ROOT is empty"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
fi

echo ""
echo "Summary: FAIL=${FAIL_COUNT}, WARN=${WARN_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi

exit 0
