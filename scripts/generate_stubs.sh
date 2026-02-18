#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GEN_DIR="${PROJECT_ROOT}/src/auto_upload_to_115open/generated"

mkdir -p "${GEN_DIR}"

python3 -m grpc_tools.protoc \
  -I"${PROJECT_ROOT}" \
  --python_out="${GEN_DIR}" \
  --grpc_python_out="${GEN_DIR}" \
  "${PROJECT_ROOT}/clouddrive.proto"

# grpc_tools generates absolute imports by default; patch to package-relative import.
if grep -q '^import clouddrive_pb2 as' "${GEN_DIR}/clouddrive_pb2_grpc.py"; then
  sed -i 's/^import clouddrive_pb2 as /from . import clouddrive_pb2 as /' "${GEN_DIR}/clouddrive_pb2_grpc.py"
fi

echo "generated: ${GEN_DIR}/clouddrive_pb2.py"
echo "generated: ${GEN_DIR}/clouddrive_pb2_grpc.py"
