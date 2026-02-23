# HANDOFF

## 项目名称

`auto-upload-to-115open`

## 项目目标（必须保持）

将 qBittorrent-nox 的“下载完成后内容路径”事件转换为可审计、可延迟、可重试的上传任务，并通过 CloudDrive2 官方 gRPC Remote Upload Protocol 上传到 115（CloudDrive2 逻辑路径 `/115open`）。

## 强约束（必须遵守）

- 仅使用 `clouddrive.proto` 中定义的官方 gRPC API。
- 上传必须使用 Remote Upload Protocol（`StartRemoteUpload` / `RemoteUploadChannel` / `RemoteReadData` / `RemoteHashProgress`）。
- 鉴权使用 gRPC metadata：`Authorization: Bearer <token>`。
- 禁止使用 CloudDrive2 FUSE 挂载语义。
- 延迟必须用 `systemd-run --on-active`（优先）或 `at`，禁止 `sleep`。

## 当前实现状态（已完成）

- `src/qbt_cd2_uploader/config.py`
  - 解析环境变量（`CD2_ADDR`、`CD2_USE_TLS`、`CD2_TOKEN`、`CD2_TARGET_ROOT`、`CD2_DELAY_MINUTES`、`CD2_WATCH_DIRS` 等）
  - 支持多目录白名单（逗号/冒号分隔）
- `src/qbt_cd2_uploader/path_rules.py`
  - 基于“完成后内容路径”判断是否命中白名单
  - 生成相对路径映射到远端 `/115open/...`
- `src/qbt_cd2_uploader/state_store.py`
  - 队列与状态目录落盘（pending/archive + state/items）
  - 幂等控制（同一路径 `scheduled/running/success` 不重复上传）
  - 稳定 `device_id` 持久化
- `src/qbt_cd2_uploader/grpc_client.py`
  - CloudDrive2 gRPC client
  - Remote Upload Protocol 上传流程
  - CreateFolder 确保远端父目录存在
- `src/qbt_cd2_uploader/worker.py`
  - 读取 task 执行上传
  - 失败落状态和错误信息
  - 有限重试（`CD2_MAX_RETRIES`）
- `src/qbt_cd2_uploader/cli.py`
  - `enqueue`
  - `run-task`
- `scripts/qbt_cd2_enqueue.sh`
  - 接收 qBittorrent 完成路径
  - 白名单判断后创建 task
  - 用 `systemd-run --on-active` 延迟调度（失败回退 `at`）
- `scripts/cd2_upload_worker.sh`
  - 调用 Python worker
- `scripts/generate_stubs.sh`
  - 生成 `clouddrive_pb2.py` / `clouddrive_pb2_grpc.py`
- `README.md`
  - 本地开发、部署、服务器配置、qBittorrent 配置、日志查看

## 当前已知现象（待排查重点）

现象：

- 多次测试下载中“有时能成功上传到 115”，但“绝大多数没有看到上传”
- 用户已确认完成路径位于指定白名单目录（目录命中不是主要问题）

高概率原因（按优先级）：

1. 幂等拦截：同一路径重复触发被 `scheduled/running/success` 状态拦截
2. 延迟期间路径被移动/清理：worker 执行时本地路径不存在
3. `systemd-run --user` 调度失败，且 `at` 回退不可用（未安装/`atd` 未运行）
4. 全局串行锁导致任务积压（看起来像没上传）
5. gRPC 调用失败，但未查看状态文件 `last_error` 或 `journalctl`

## 服务器环境（目标）

- Debian 13
- qBittorrent-nox
- CloudDrive2
- CloudDrive2 Web: `19798(http)` / `19799(https)`
- CloudDrive2 逻辑目标根路径：`/115open`

## 常用配置（通过 `/etc/default/cd2-uploader`）

```bash
CD2_ADDR=127.0.0.1:19799
CD2_USE_TLS=1
CD2_TOKEN=YOUR_API_TOKEN
CD2_TARGET_ROOT=/115open
CD2_DELAY_MINUTES=60
CD2_WATCH_DIRS=/mnt/seedbox/complete/:/mnt/seedbox/another/
CD2_MAX_RETRIES=3
CD2_QUEUE_DIR=/var/lib/cd2-uploader/queue
CD2_STATE_DIR=/var/lib/cd2-uploader/state
# qBittorrent 若为系统服务，可考虑：
# CD2_SYSTEMD_USER_MODE=0
```

## qBittorrent 外部程序配置（参考）

```bash
/opt/auto-upload-to-115open/scripts/qbt_cd2_enqueue.sh "%F"
```

## 首轮排查命令（建议按顺序）

### 1) 看队列是否积压

```bash
ls -lt /var/lib/cd2-uploader/queue/pending | head -50
ls -lt /var/lib/cd2-uploader/queue/archive | head -50
```

### 2) 看状态和错误信息（最关键）

```bash
rg -n '"status":|"completed_path":|"last_error":|"attempts":' /var/lib/cd2-uploader/state/items
```

重点关注：

- `status=success`（可能是幂等导致后续跳过）
- `status=failed` + `last_error`
- `completed path does not exist`
- `no regular files found`

### 3) 看 systemd 调度与 worker 日志（用户模式）

```bash
systemctl --user list-units 'cd2-upload-*' --all
journalctl --user -u 'cd2-upload-*' --since '2 hours ago' --no-pager
```

### 4) 如果 qBittorrent 是系统服务，检查是否该用系统模式

```bash
systemctl status qbittorrent-nox
```

若是系统服务，建议测试：

```bash
echo 'CD2_SYSTEMD_USER_MODE=0' | sudo tee -a /etc/default/cd2-uploader
```

### 5) 检查 `at` 回退链路是否可用（当 `systemd-run` 失败时）

```bash
command -v at
systemctl status atd
atq
```

### 6) 手动重放一次 enqueue（直接看脚本输出）

```bash
/opt/auto-upload-to-115open/scripts/qbt_cd2_enqueue.sh "/mnt/seedbox/complete/你的完成路径"
```

如果输出类似：

- `SKIPPED IDEMPOTENT_BLOCKED state=success`

说明是幂等拦截（符合设计）。

## 本地/跨电脑继续开发建议

- 以 GitLab 仓库代码为事实源（不要只依赖聊天记录）
- 将服务器排查结果（日志、状态文件片段）提交到 issue 或保存到 `debug/`（注意脱敏 token）
- 新电脑上的 Codex 先阅读：
  - `README.md`
  - `HANDOFF.md`
  - `src/qbt_cd2_uploader/*.py`
  - `scripts/*.sh`

## 下一步建议（面向后续 Codex）

1. 优先确认“没上传”是否实际是幂等跳过
2. 确认 `systemd-run --user` 是否可靠（linger/user bus）
3. 如需，增强日志：
   - enqueue 阶段记录调度成功/失败与 unit 名称
   - worker 阶段记录 task_id/path_key/remote path
4. 可选改进：
   - 增加 `inspect-state` CLI 子命令
   - 增加失败重试退避
   - 增加并发控制配置（当前全局串行）
