# auto-upload-to-115open

将 qBittorrent-nox 的“下载完成”事件转换为一个可审计、可延迟、可重试的上传任务，并通过 **CloudDrive2 官方 gRPC Remote Upload Protocol** 上传到 115 网盘（CloudDrive2 逻辑根路径：`/115open`）。

## 设计目标

- **不使用 FUSE 挂载**：避免权限继承 / setgid / FUSE 语义复杂与不稳定。
- **官方边界内实现**：仅使用仓库内 `clouddrive.proto` 定义的 gRPC API；不猜测 REST/隐藏接口。
- **可靠延迟**：使用 `systemd-run --on-active=...` 创建一次性任务，避免 `sleep` 堆积进程。
- **可配置触发目录**：仅当“完成后内容路径”匹配白名单目录（可多个）才触发上传。
- **幂等与可审计**：任务与状态落盘（默认 `/var/lib/cd2-uploader`），重复触发不重复上传。

## 运行环境

- Debian 13（服务器）
- qBittorrent-nox
- CloudDrive2（Web: 19798/19799）
- 目标云端目录：`/115open`

## 仓库内容

- `clouddrive.proto`：CloudDrive2 官方 gRPC API 定义
- `CloudDrive2 gRPC API 开发者指南.pdf`：官方 API 说明文档（存档）
- `src/auto_upload_to_115open/`：Python 实现（gRPC client + worker）
- `scripts/`：qBittorrent 触发脚本与 worker wrapper
