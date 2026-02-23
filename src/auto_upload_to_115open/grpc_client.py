from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import grpc

from auto_upload_to_115open.config import Settings
from auto_upload_to_115open.path_rules import join_cloud_path

try:
    from auto_upload_to_115open.generated import clouddrive_pb2
    from auto_upload_to_115open.generated import clouddrive_pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "CloudDrive2 gRPC stubs are missing. Run scripts/generate_stubs.sh first."
    ) from exc


HASH_UNKNOWN = 0
HASH_MD5 = 1
HASH_SHA1 = 2
HASH_PIKPAK_SHA1 = 3

STATUS_CANCELLED = 2
STATUS_FINISH = 5
STATUS_SKIPPED = 6
STATUS_IGNORED = 8
STATUS_ERROR = 9
STATUS_FATAL_ERROR = 10


class RemoteUploadError(RuntimeError):
    pass


class CloudDriveRemoteUploader:
    def __init__(self, settings: Settings, device_id: str) -> None:
        self.settings = settings
        self.device_id = device_id
        self._metadata = (("authorization", f"Bearer {settings.cd2_token}"),)
        self._channel = self._build_channel()
        self._stub = clouddrive_pb2_grpc.CloudDriveFileSrvStub(self._channel)

    def close(self) -> None:
        self._channel.close()

    def upload_path(self, source_path: str, remote_target_path: str) -> int:
        source = Path(source_path).expanduser().resolve(strict=False)
        if not source.exists():
            raise RemoteUploadError(f"source path not found: {source}")

        if source.is_file():
            self._ensure_remote_dir(self._remote_parent(remote_target_path))
            self._upload_file(source, remote_target_path)
            return 1

        self._ensure_remote_dir(remote_target_path)
        upload_count = 0

        # Keep upload order deterministic to simplify debugging/replay.
        for local_file in self._iter_files(source):
            rel = local_file.relative_to(source).as_posix()
            remote_file_path = join_cloud_path(remote_target_path, rel)
            self._ensure_remote_dir(self._remote_parent(remote_file_path))
            self._upload_file(local_file, remote_file_path)
            upload_count += 1

        return upload_count

    def _iter_files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path

    def _upload_file(self, local_file: Path, remote_file_path: str) -> None:
        file_size = local_file.stat().st_size
        start_req = clouddrive_pb2.StartRemoteUploadRequest(
            file_path=remote_file_path,
            file_size=file_size,
            known_hashes={},
            client_can_calculate_hashes=True,
        )

        started = self._stub.StartRemoteUpload(start_req, metadata=self._metadata)
        upload_id = started.upload_id.strip()
        if not upload_id:
            raise RemoteUploadError(f"StartRemoteUpload returned empty upload_id for {local_file}")

        channel_req = clouddrive_pb2.RemoteUploadChannelRequest(device_id=self.device_id)
        stream = self._stub.RemoteUploadChannel(channel_req, metadata=self._metadata)

        try:
            with local_file.open("rb") as fp:
                for reply in stream:
                    if reply.upload_id != upload_id:
                        continue

                    req_type = reply.WhichOneof("request")
                    if req_type == "read_data":
                        self._handle_read_data(upload_id, reply.read_data, fp)
                        continue
                    if req_type == "hash_data":
                        self._handle_hash_data(upload_id, reply.hash_data, local_file, file_size)
                        continue
                    if req_type == "status_changed":
                        status = int(reply.status_changed.status)
                        if status in {STATUS_FINISH, STATUS_SKIPPED}:
                            return
                        if status in {STATUS_CANCELLED, STATUS_ERROR, STATUS_FATAL_ERROR, STATUS_IGNORED}:
                            err = reply.status_changed.error_message or f"upload failed with status={status}"
                            raise RemoteUploadError(err)
                        continue

                raise RemoteUploadError(f"upload stream ended before completion: {local_file}")
        finally:
            stream.cancel()

    def _handle_read_data(self, upload_id: str, request, fp) -> None:
        fp.seek(request.offset)
        remaining = int(request.length)
        current_offset = int(request.offset)
        chunk_size = 4 * 1024 * 1024

        if remaining == 0:
            payload = clouddrive_pb2.RemoteReadDataUpload(
                upload_id=upload_id,
                offset=current_offset,
                length=0,
                lazy_read=request.lazy_read,
                data=b"",
                is_last_chunk=True,
            )
            reply = self._stub.RemoteReadData(payload, metadata=self._metadata)
            if not reply.success:
                raise RemoteUploadError(reply.error_message or "RemoteReadData failed")
            return

        while remaining > 0:
            take = min(chunk_size, remaining)
            data = fp.read(take)
            if not data:
                raise RemoteUploadError(
                    f"local read underflow at offset={current_offset}, requested={take}"
                )

            is_last = len(data) >= remaining
            payload = clouddrive_pb2.RemoteReadDataUpload(
                upload_id=upload_id,
                offset=current_offset,
                length=len(data),
                lazy_read=request.lazy_read,
                data=data,
                is_last_chunk=is_last,
            )
            reply = self._stub.RemoteReadData(payload, metadata=self._metadata)
            if not reply.success:
                raise RemoteUploadError(reply.error_message or "RemoteReadData failed")

            remaining -= len(data)
            current_offset += len(data)

    def _handle_hash_data(self, upload_id: str, request, local_file: Path, total_bytes: int) -> None:
        hash_type = int(request.hash_type)
        block_size = int(request.block_size) if request.HasField("block_size") else 0

        if hash_type == HASH_MD5:
            digest = hashlib.md5()
        elif hash_type in {HASH_SHA1, HASH_PIKPAK_SHA1}:
            digest = hashlib.sha1()
        else:
            raise RemoteUploadError(f"unsupported hash_type requested by server: {hash_type}")

        chunk_size = 4 * 1024 * 1024
        bytes_hashed = 0
        block_hashes: list[str] = []
        block_buffer = bytearray()

        with local_file.open("rb") as fp:
            while True:
                chunk = fp.read(chunk_size)
                if not chunk:
                    break

                digest.update(chunk)
                bytes_hashed += len(chunk)

                if block_size > 0 and hash_type == HASH_MD5:
                    block_buffer.extend(chunk)
                    while len(block_buffer) >= block_size:
                        part = bytes(block_buffer[:block_size])
                        block_hashes.append(hashlib.md5(part).hexdigest())
                        del block_buffer[:block_size]

                progress = clouddrive_pb2.RemoteHashProgressUpload(
                    upload_id=upload_id,
                    bytes_hashed=bytes_hashed,
                    total_bytes=total_bytes,
                    hash_type=hash_type,
                )
                self._stub.RemoteHashProgress(progress, metadata=self._metadata)

        if block_size > 0 and hash_type == HASH_MD5 and block_buffer:
            block_hashes.append(hashlib.md5(bytes(block_buffer)).hexdigest())

        finished = clouddrive_pb2.RemoteHashProgressUpload(
            upload_id=upload_id,
            bytes_hashed=bytes_hashed,
            total_bytes=total_bytes,
            hash_type=hash_type,
            hash_value=digest.hexdigest(),
            block_hashes=block_hashes,
        )
        self._stub.RemoteHashProgress(finished, metadata=self._metadata)

    def _build_channel(self):
        if self.settings.cd2_use_tls:
            creds = grpc.ssl_channel_credentials()
            return grpc.secure_channel(self.settings.cd2_addr, creds)
        return grpc.insecure_channel(self.settings.cd2_addr)

    def _ensure_remote_dir(self, remote_dir: str) -> None:
        normalized = remote_dir.strip()
        if not normalized:
            normalized = "/"
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        normalized = normalized.rstrip("/") or "/"

        if normalized == "/":
            return

        parts = [p for p in normalized.split("/") if p]
        current = "/"
        for part in parts:
            req = clouddrive_pb2.CreateFolderRequest(parentPath=current, folderName=part)
            result = self._stub.CreateFolder(req, metadata=self._metadata)

            success = bool(result.result.success)
            if not success:
                error = (result.result.errorMessage or "").lower()
                if "exist" not in error and "already" not in error:
                    raise RemoteUploadError(
                        f"CreateFolder failed for parent={current}, name={part}: {result.result.errorMessage}"
                    )

            current = join_cloud_path(current, part)

    @staticmethod
    def _remote_parent(remote_file_path: str) -> str:
        normalized = remote_file_path.rstrip("/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized

        slash = normalized.rfind("/")
        if slash <= 0:
            return "/"
        return normalized[:slash]
