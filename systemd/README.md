# systemd 运行建议

本项目通过 `systemd-run --user --on-active=...` 创建一次性延迟任务。

## 1) 启用用户 linger（推荐）

如果 `qBittorrent-nox` 以普通用户（例如 `seedbox`）运行，建议为该用户启用 linger，避免退出登录后 user systemd 被清理：

```bash
sudo loginctl enable-linger seedbox
```

## 2) 确认 user systemd 可用

```bash
sudo -u seedbox systemctl --user status
```

## 3) 查看一次性任务

```bash
sudo -u seedbox systemctl --user list-units 'auto-upload-115open-*'
```

## 4) 查看执行日志

```bash
sudo -u seedbox journalctl --user -u 'auto-upload-115open-*' -f
```

如果 `systemd-run --user` 不可用，程序会自动回退到 `at` 调度。
