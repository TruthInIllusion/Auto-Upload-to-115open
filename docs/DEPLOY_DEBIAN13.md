# Debian 13 部署与运维手册

本文件是当前可直接执行的最新流程，适用于：

- `qBittorrent-nox` 运行用户：`seedbox`（可改）
- CloudDrive2 与本项目部署在同一台 Debian 13 服务器
- 上传目标目录：`/115open/自动上传`
- gRPC 建议地址：`127.0.0.1:19798` + `CD2_USE_TLS=0`

## 一次性部署命令

> 下面按块执行。先改变量，再执行。

### 1) 变量

```bash
export RUN_USER="seedbox"
export INSTALL_DIR="/opt/auto-upload-to-115open"
export REPO_URL="https://github.com/<你的用户名>/<你的仓库名>.git"

export CD2_ADDR="127.0.0.1:19798"
export CD2_USE_TLS="0"
export CD2_TOKEN="在这里填你的CloudDrive2_API_TOKEN"
export CD2_TARGET_ROOT="/115open/自动上传"
export CD2_DELAY_MINUTES="60"
export CD2_WATCH_DIRS="/mnt/seedbox/complete/"
export CD2_MAX_RETRIES="3"
export CD2_RETRY_BACKOFF="2.0"
```

### 2) 安装系统依赖

```bash
sudo apt update
sudo apt install -y git at python3 python3-venv
sudo systemctl enable --now atd
```

### 3) 检查 Python 版本（必须 >= 3.11）

```bash
python3 - <<'PY'
import sys
print("Python:", sys.version)
assert sys.version_info >= (3,11), "需要 Python >= 3.11"
print("版本检查通过")
PY
```

### 4) 拉取或更新项目代码

```bash
sudo install -d -m 0755 -o "$RUN_USER" -g "$RUN_USER" "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  sudo -u "$RUN_USER" -H git -C "$INSTALL_DIR" pull --ff-only
else
  sudo -u "$RUN_USER" -H git clone "$REPO_URL" "$INSTALL_DIR"
fi
```

### 5) 创建 venv、安装依赖、生成 gRPC stub

```bash
sudo -u "$RUN_USER" -H bash -lc "
set -euo pipefail
cd '$INSTALL_DIR'
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
./scripts/generate_stubs.sh
"
```

### 6) 写入配置文件

```bash
sudo tee /etc/default/auto-upload-to-115open >/dev/null <<EOF_CFG
CD2_ADDR=$CD2_ADDR
CD2_USE_TLS=$CD2_USE_TLS
CD2_TOKEN=$CD2_TOKEN
CD2_TARGET_ROOT=$CD2_TARGET_ROOT
CD2_DELAY_MINUTES=$CD2_DELAY_MINUTES
CD2_WATCH_DIRS=$CD2_WATCH_DIRS
CD2_MAX_RETRIES=$CD2_MAX_RETRIES
CD2_RETRY_BACKOFF=$CD2_RETRY_BACKOFF
CD2_QUEUE_DIR=/var/lib/auto_uploader/queue
CD2_STATE_DIR=/var/lib/auto_uploader/state
EOF_CFG

sudo chown root:"$RUN_USER" /etc/default/auto-upload-to-115open
sudo chmod 640 /etc/default/auto-upload-to-115open
```

### 7) 准备队列/状态目录权限

```bash
sudo install -d -m 0750 -o "$RUN_USER" -g "$RUN_USER" /var/lib/auto_uploader/queue
sudo install -d -m 0750 -o "$RUN_USER" -g "$RUN_USER" /var/lib/auto_uploader/state
```

### 8) 启用 linger（保证 user systemd 定时任务可靠）

```bash
sudo loginctl enable-linger "$RUN_USER"
RUN_UID="$(id -u "$RUN_USER")"
sudo systemctl start "user@${RUN_UID}.service"
sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/${RUN_UID}" systemctl --user status >/dev/null
echo "linger + user systemd ready"
```

### 9) qBittorrent WebUI 设置

`下载完成后运行外部程序` 填：

```bash
/opt/auto-upload-to-115open/scripts/auto_upload_enqueue.sh "%F"
```

## 首次验证（建议）

先临时改为 1 分钟，验证后改回 60。

```bash
sudo sed -i 's#^CD2_DELAY_MINUTES=.*#CD2_DELAY_MINUTES=1#' /etc/default/auto-upload-to-115open

RUN_UID="$(id -u "$RUN_USER")"
TEST_DIR="/mnt/seedbox/complete/cd2-test-$(date +%Y%m%d-%H%M%S)"
sudo -u "$RUN_USER" mkdir -p "$TEST_DIR"
sudo -u "$RUN_USER" bash -lc "echo 'hello cd2' > '$TEST_DIR/hello.txt'"

sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/${RUN_UID}" \
  "$INSTALL_DIR/scripts/auto_upload_enqueue.sh" "$TEST_DIR"
```

查看状态与日志：

```bash
LATEST_STATE="$(sudo ls -1t /var/lib/auto_uploader/state/*.json | head -n1)"
echo "$LATEST_STATE"
sudo cat "$LATEST_STATE"

sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/${RUN_UID}" \
  journalctl --user --since '20 min ago' --no-pager | \
  grep -Ei 'queued:|completed:|failed:|retry-scheduled|auto-upload-115open' || true
```

验证通过后改回生产延迟：

```bash
sudo sed -i 's#^CD2_DELAY_MINUTES=.*#CD2_DELAY_MINUTES=60#' /etc/default/auto-upload-to-115open
```

## 维护与更新

### 更新代码

```bash
sudo -u "$RUN_USER" -H git -C "$INSTALL_DIR" pull --ff-only
sudo -u "$RUN_USER" -H bash -lc "
set -euo pipefail
cd '$INSTALL_DIR'
source .venv/bin/activate
pip install -r requirements.txt
./scripts/generate_stubs.sh
"
```

### 修改监视目录

例如新增目录：

```bash
sudo sed -i 's#^CD2_WATCH_DIRS=.*#CD2_WATCH_DIRS=/mnt/seedbox/complete/:/mnt/seedbox/another/#' /etc/default/auto-upload-to-115open
```

### 健康检查

```bash
sudo RUN_USER="$RUN_USER" INSTALL_DIR="$INSTALL_DIR" "$INSTALL_DIR/scripts/health_check.sh"
```

## 重启后是否可用

在本手册流程完成后，重启服务器仍可用。重启后建议执行：

```bash
RUN_UID="$(id -u "$RUN_USER")"
sudo -u "$RUN_USER" XDG_RUNTIME_DIR="/run/user/${RUN_UID}" systemctl --user status >/dev/null && echo "user systemd OK"
sudo RUN_USER="$RUN_USER" INSTALL_DIR="$INSTALL_DIR" "$INSTALL_DIR/scripts/health_check.sh"
```
