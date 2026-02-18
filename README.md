# Auto upload to 115open (`auto-upload-to-115open`)

将 qBittorrent-nox 的“下载完成后内容路径”事件转换为可审计任务，按目录白名单触发并延迟执行，然后使用 **CloudDrive2 官方 gRPC Remote Upload Protocol** 上传到 115 网盘目录 `/115open`。

## 快速入口

- Debian 13 最新部署手册：`docs/DEPLOY_DEBIAN13.md`
- 一键健康检查脚本：`scripts/health_check.sh`

## 关键约束落实

- 仅使用 `clouddrive.proto` 定义的官方 gRPC API。
- 上传协议使用 `StartRemoteUpload + RemoteUploadChannel + RemoteReadData + RemoteHashProgress`。
- 鉴权通过 gRPC metadata：`Authorization: Bearer <token>`（gRPC 实际发送为小写 `authorization`）。
- 不使用 FUSE/挂载语义，worker 直接读取本地文件，通过 Remote Upload 推送给 CloudDrive2。
- 延迟调度优先 `systemd-run --user --on-active=...`，失败回退 `at`，**不使用 `sleep`**。

## 仓库结构

```text
.
├── clouddrive.proto
├── CloudDrive2 gRPC API 开发者指南.pdf
├── pyproject.toml
├── requirements.txt
├── scripts
│   ├── auto_upload_enqueue.sh
│   ├── auto_upload_worker.sh
│   ├── generate_stubs.sh
│   └── health_check.sh
├── docs
│   └── DEPLOY_DEBIAN13.md
├── src/auto_upload_to_115open
│   ├── config.py
│   ├── enqueue.py
│   ├── grpc_client.py
│   ├── models.py
│   ├── path_rules.py
│   ├── scheduler.py
│   ├── task_store.py
│   ├── worker.py
│   └── generated/
└── systemd/README.md
```

## 环境变量配置

必须项：

- `CD2_ADDR`：CloudDrive2 gRPC 地址，例如 `127.0.0.1:19799`（TLS）或 `127.0.0.1:19798`（非 TLS）
- `CD2_USE_TLS`：`1` 或 `0`
- `CD2_TOKEN`：CloudDrive2 API Token

常用项：

- `CD2_TARGET_ROOT`：默认 `/115open`
- `CD2_DELAY_MINUTES`：默认 `60`
- `CD2_WATCH_DIRS`：触发目录白名单，支持逗号或冒号分隔
  - 示例：`/mnt/seedbox/complete/:/mnt/seedbox/another/`
- `CD2_MAX_RETRIES`：默认 `3`（总尝试次数）
- `CD2_RETRY_BACKOFF`：默认 `2.0`（指数退避系数）
- `CD2_QUEUE_DIR`：默认 `/var/lib/auto_uploader/queue`
- `CD2_STATE_DIR`：默认 `/var/lib/auto_uploader/state`

说明：

- 仅当“完成后内容路径”命中 `CD2_WATCH_DIRS` 白名单才会入队。
- 默认白名单仅 `/mnt/seedbox/complete/`，例如 `/mnt/seedbox/flush/` 不会触发。
- `device_id` 会稳定保存在 `${CD2_STATE_DIR}/device_id`。

## 本地开发（VSCode + venv）

> 推荐 Python 3.11+

```bash
cd auto-upload-to-115open
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

生成 gRPC stub：

```bash
./scripts/generate_stubs.sh
```

会生成：

- `src/auto_upload_to_115open/generated/clouddrive_pb2.py`
- `src/auto_upload_to_115open/generated/clouddrive_pb2_grpc.py`

基础语法检查：

```bash
python -m compileall src
```

## 部署到 Debian 13 服务器

### 1) 上传代码

```bash
rsync -avz --delete ./ seedbox@server:/opt/auto-upload-to-115open/
```

### 2) 服务器创建 venv

```bash
ssh seedbox@server
cd /opt/auto-upload-to-115open
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/generate_stubs.sh
```

### 3) 配置环境变量（推荐）

创建 `/etc/default/auto-upload-to-115open`：

```bash
sudo tee /etc/default/auto-upload-to-115open >/dev/null <<'CFG'
CD2_ADDR=127.0.0.1:19799
CD2_USE_TLS=1
CD2_TOKEN=YOUR_TOKEN_HERE
CD2_TARGET_ROOT=/115open
CD2_DELAY_MINUTES=60
CD2_WATCH_DIRS=/mnt/seedbox/complete/:/mnt/seedbox/another/
CD2_MAX_RETRIES=3
CD2_RETRY_BACKOFF=2.0
CD2_QUEUE_DIR=/var/lib/auto_uploader/queue
CD2_STATE_DIR=/var/lib/auto_uploader/state
CFG
```

给 qBittorrent 运行用户授权目录：

```bash
sudo mkdir -p /var/lib/auto_uploader/queue /var/lib/auto_uploader/state
sudo chown -R seedbox:seedbox /var/lib/auto_uploader
```

### 4) systemd user 环境建议

见 `systemd/README.md`。

## qBittorrent-nox 配置

在 qBittorrent 设置中启用：

- `下载完成后运行外部程序`：

```bash
/opt/auto-upload-to-115open/scripts/auto_upload_enqueue.sh "%F"
```

其中 `%F` 是“完成后内容路径”（文件或目录）。

## 手动测试

模拟一次入队（仅命中白名单时才会真正入队）：

```bash
/opt/auto-upload-to-115open/scripts/auto_upload_enqueue.sh /mnt/seedbox/complete/test-data
```

查看队列与状态：

```bash
ls -lah /var/lib/auto_uploader/queue
ls -lah /var/lib/auto_uploader/state
cat /var/lib/auto_uploader/state/*.json
```

查看一次性延迟 unit：

```bash
systemctl --user list-units 'auto-upload-115open-*'
```

查看日志：

```bash
journalctl --user -u 'auto-upload-115open-*' -f
```

## 幂等与重试行为

- 同一 source path 的 `task_id = sha256(source_path)`，重复触发不会重复上传。
- 状态写入 `${CD2_STATE_DIR}/${task_id}.json`。
- 失败后按 `CD2_MAX_RETRIES` 限制重试，重试延迟按 `CD2_RETRY_BACKOFF` 指数退避。
- 达到最大重试后状态为 `failed`，保留错误信息用于排障。

## 开发注意事项

- 必须在虚拟环境（`venv`）中安装依赖和执行脚本，避免污染全局环境。
- 若你使用 `19799` 且为自签证书，可能需要确认服务器证书链；不方便处理证书时可改用 `19798 + CD2_USE_TLS=0`（仅限可信内网）。
