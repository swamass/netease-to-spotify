# Mac 使用指南

macOS 本地方案与 GitHub Actions 独立运行：本地方案使用 Mac 上的浏览器登录状态，GitHub Actions 使用你在仓库中配置的 Secrets。

## 本地同步

### 准备依赖

在项目根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r local-requirements.txt
.venv/bin/python -m playwright install chromium
```

本地 `.env` 需要四个 Spotify 变量：`SPOTIFY_CLIENT_ID`、`SPOTIFY_CLIENT_SECRET`、`SPOTIFY_REFRESH_TOKEN`、`SPOTIFY_PLAYLIST_ID`。授权方法见 [新手使用指南](getting-started.md)。

### 第一次运行

⚠️ 这是正式同步，会替换目标 Playlist 中的全部原有歌曲，不是追加。确认目标歌单可以被替换后再运行。

```bash
.venv/bin/python scripts/local_sync.py
```

脚本会打开独立的持久化 Chromium Profile：

```text
~/.local/share/netease-to-spotify-browser
```

请在网易云网页中登录或用 App 扫码。脚本读取浏览器 Cookie，验证每日推荐成功后才进入 Spotify 匹配；推荐失败或匹配数为零时不会修改 Playlist。

## 自动运行

可选安装仓库已有的 LaunchAgent：

```bash
scripts/install_local_sync.sh
launchctl print "gui/$(id -u)/com.swamass.netease-to-spotify"
```

任务每 5 分钟检查一次，但不会主动唤醒睡眠中的 Mac。程序按 `Asia/Shanghai` 判断时间，每天北京时间 06:10 后最多自动尝试一次；如果 Mac 当时睡眠，恢复运行后当天仍可能补执行。失败后当天不会自动重试。

卸载：

```bash
scripts/uninstall_local_sync.sh
```

日志位置：

```text
~/Library/Logs/netease-to-spotify/sync.log
~/Library/Logs/netease-to-spotify/sync.error.log
```

## 用 Mac 扫码更新 GitHub Cookie

此功能需要：

- Python 本地虚拟环境和 `local-requirements.txt`
- Playwright Chromium
- GitHub CLI
- 已完成一次 `gh auth login`

如果你使用 Fork，请先指定自己的仓库，避免误更新默认仓库：

```bash
.venv/bin/python scripts/update_netease_cookie_secret.py \
  --repo 用户名/netease-to-spotify
```

首次使用 GitHub CLI 时才需要先执行：

```bash
gh auth login
```

然后再次运行上面的更新命令。后续更新不需要重复 `gh auth login`。如果你确实使用原仓库，也可以省略 `--repo`：

```bash
.venv/bin/python scripts/update_netease_cookie_secret.py
```

首次运行会打开独立 Chromium。请在网易云网页中登录或使用 App 扫码；Cookie 验证成功后，脚本才会自动更新 GitHub Secret。

本地同步不需要 GitHub CLI；只有更新 GitHub Actions 的 Cookie 才需要它。更新 Cookie 不会修改 Spotify Playlist。

脚本行为：

1. Cookie 有效：验证每日推荐接口后直接更新 `NETEASE_COOKIE`。
2. 网易云明确返回业务码 `301`：清除失效的 `MUSIC_U` 和 `__csrf`，在同一 Profile 中重新扫码，再验证一次。
3. 新 Cookie 验证成功才更新 Secret；网络错误、其他 API 错误、扫码超时或 Cookie 不完整都不会覆盖旧值。
4. 最多重新扫码一次，不会运行 Spotify 同步，也不会修改 Playlist。

## 创建 Automator 双击入口（可选）

Automator 应用需要你自行创建；仓库没有提供现成安装包。

1. 打开 macOS **Automator**，选择 **应用程序**。
2. 搜索并加入 **运行 Shell 脚本**。
3. Shell 选择 `/bin/zsh`，输入类似以下内容；将路径改成你的实际项目路径：

```bash
cd ~/Documents/netease-to-spotify
.venv/bin/python scripts/update_netease_cookie_secret.py \
  --repo 用户名/netease-to-spotify
```

4. 保存为应用，例如“更新网易云 Cookie”。以后双击它即可打开浏览器并等待扫码。首次创建后建议先手动运行命令确认配置无误。

不要把 Cookie 或 Secret 写进 Automator 脚本。
