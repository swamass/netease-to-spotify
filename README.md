# 网易云每日推荐 → Spotify

自动获取网易云音乐「每日推荐」，在 Spotify 中搜索并保守匹配，然后同步到指定 Spotify Playlist。项目通过 GitHub Actions 自动运行，不需要自己长期运行服务器。

```text
网易云每日推荐 → Spotify 搜索与匹配 → 自动同步到 Playlist
```

无法可靠确认的歌曲会跳过，而不是强行匹配。

## 使用方法

### 1. Fork 项目并 Clone

将项目 Fork 到自己的 GitHub。后续配置和运行都在自己的 Fork 中进行：

```bash
git clone https://github.com/你的用户名/netease-to-spotify.git
cd netease-to-spotify
```

需要 Git 和 Python 3.12+。可用以下命令检查 Python：

```bash
python --version
```

Windows 如果 `python` 不可用，可以将下面命令中的 `python` 替换为 `py`。没有 Git 时，请先从 [Git 官方下载页面](https://git-scm.com/downloads) 安装。

### 2. 创建 Spotify App

打开 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)，登录并点击 **Create app**。

在 App 的 **Settings** 中查看 **Client ID**，点击 **View client secret** 查看 **Client Secret**，并添加 Redirect URI：

```text
http://127.0.0.1:8888/callback
```

### 3. 获取 Refresh Token

在项目根目录运行：

```bash
python -m pip install -r requirements.txt
python setup.py
```

按提示输入 Spotify Playlist URL 或 ID，并完成 Spotify 授权。Setup 会显示需要保存的 `SPOTIFY_REFRESH_TOKEN`，不会自动上传或保存凭据。

### 4. 获取网易云 Cookie

Cookie 是网易云网页版的登录凭证。它可能过期，不能保证永久有效；**不要把 Cookie 发到聊天、Issue、截图或提交到代码仓库。**

以 Chrome 为例：

1. 打开 [网易云音乐网页版](https://music.163.com/) 并确认已经登录。
2. 打开开发者工具，切到 **Network（网络）**，选择 **Fetch/XHR**，然后刷新网页（Mac 按 `⌘R`）。
3. 在请求列表中点开一个发往 `music.163.com` 的请求；右侧选 **Headers（标头）**。
4. 在 **Request Headers（请求标头）** 中找到 `Cookie`，复制它后面的完整内容。不要复制字段名 `Cookie:`，也不要只复制某一个 Cookie 项。
5. 将这段内容作为 `NETEASE_COOKIE` 的值保存到自己 Fork 的 GitHub Actions Secret（见下一节）。

如果请求标头里没有 `Cookie`，先确认网页已登录，再刷新并查看新请求。不同请求显示的 Cookie 内容可能不同；请选网易云页面刚发出的请求，并复制其完整的 `Cookie` 请求标头。

### 5. 配置 GitHub Secrets

在自己的 Fork 中打开：**Settings → Secrets and variables → Actions → New repository secret**。

逐项填写下表的 **Name** 和对应的 **Secret / Value**：

| Name | Secret / Value |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify App 的 Client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify App 的 Client Secret |
| `SPOTIFY_REFRESH_TOKEN` | `setup.py` 获取的 Refresh Token |
| `SPOTIFY_PLAYLIST_ID` | 目标 Spotify Playlist ID |
| `NETEASE_COOKIE` | 自己网易云登录会话的完整 Cookie |

Secret 保存后 GitHub 不会再显示原值，这是正常的。以后 Cookie 更新时，修改已有的 `NETEASE_COOKIE` Secret 即可，不要改 Secret 名称。

### 6. 先运行 Dry Run

打开自己的仓库 **Actions → NetEase Spotify Match Dry Run → Run workflow**。运行完成后查看日志和 Artifacts。

Dry Run 只获取推荐、搜索和匹配，不会清空、添加或修改 Spotify Playlist。

### 7. 运行正式同步

确认 Dry Run 没有配置或认证错误后，打开 **Actions → Sync NetEase Daily Recommendations → Run workflow**。

正式同步会用当天成功匹配的歌曲替换目标 Playlist，建议为本项目创建独立 Playlist。之后 GitHub Actions 会按 workflow 的 schedule 自动运行，当前 cron `0 22 * * *` 对应北京时间次日约 06:00，实际可能有调度延迟。

### 本地自动同步（macOS）

这是与 GitHub Actions 分开的本地方案：它不会上传 Cookie、凭据或同步日志，也不会改变 GitHub Actions 的配置。它需要一台持续使用的 macOS 用户会话；LaunchAgent 每 5 分钟轮询一次，但每天只在北京时间 06:10 之后执行一次。

#### 首次设置

1. 在项目根目录创建 Python 3.12 虚拟环境并安装依赖：

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -r local-requirements.txt
   .venv/bin/python -m playwright install chromium
   ```

2. 运行 `.venv/bin/python setup.py` 完成 Spotify OAuth。按提示输入 Client ID、Client Secret、目标 Playlist URL 或 ID，并选择 Playlist 是否公开。成功后 OAuth 值会以 600 权限保存到 `~/.config/netease-to-spotify/.env`；不要把这个文件复制到仓库、提交到 Git 或发送给别人。确认其中还包含 `SPOTIFY_PLAYLIST_ID`，并检查权限：

   ```bash
   chmod 600 ~/.config/netease-to-spotify/.env
   ```

   本地运行需要这四个变量：`SPOTIFY_CLIENT_ID`、`SPOTIFY_CLIENT_SECRET`、`SPOTIFY_REFRESH_TOKEN`、`SPOTIFY_PLAYLIST_ID`。网易云 Cookie 不写入 `.env`，而是从独立的 Playwright 浏览器 Profile 读取。

3. 先手动运行一次：`.venv/bin/python scripts/local_sync.py`。第一次运行会打开独立浏览器 Profile，请手动登录网易云；密码不会被脚本读取或保存。成功后确认 Spotify Playlist 已更新。

#### 安装、验证和手动运行

安装 LaunchAgent：

```bash
scripts/install_local_sync.sh
launchctl print "gui/$(id -u)/com.swamass.netease-to-spotify"
```

`launchctl print` 能显示该服务即表示已加载。再次手动同步使用 `.venv/bin/python scripts/local_sync.py`；只想停止自动运行可执行 `scripts/uninstall_local_sync.sh`，不会删除浏览器 Profile、状态或日志。

任务每 5 分钟被 macOS 唤醒一次，但由 Python `zoneinfo` 按北京时间判断，只有每天 06:10 之后首次运行才会执行；每天最多执行一次。Mac 在计划时间睡眠时，醒来后会在当天 06:10 之后补执行。失败后当天不会自动重试，需查看日志、修复问题后手动运行；失败时会显示 macOS 通知。日志保存在 `~/Library/Logs/netease-to-spotify/sync.log` 和 `sync.error.log`，可用以下命令查看：

```bash
tail -f ~/Library/Logs/netease-to-spotify/sync.log \
  ~/Library/Logs/netease-to-spotify/sync.error.log
```

网易云返回 301、浏览器登录态失效或推荐为空时会停止，现有 Spotify Playlist 不会被清空。

#### 故障排查

- `Missing local environment values`：检查 `~/.config/netease-to-spotify/.env` 是否包含上面的四个变量，并确认权限为 600。
- `网易云浏览器会话未登录或已失效`：再次运行本地同步，在打开的独立浏览器中登录网易云；不要把 Cookie 复制到 `.env` 或日志。
- `launchctl print` 找不到服务：重新运行 `scripts/install_local_sync.sh`，并确认 `.venv/bin/python` 存在。
- Spotify Playlist 没有更新：先运行一次手动同步并查看两个本地日志文件；如果当天已经尝试过一次，LaunchAgent 不会自动重试，修复后请手动运行。

本地自动同步只适用于 macOS；GitHub Actions 仍按上文的 Secrets 和 workflow 运行，两者互不替代。

## Cookie 失效后如何恢复

如果 Actions 日志出现类似：

```text
NetEase API returned code 301: 获取用户信息失败
```

通常表示网易云接口没有接受当前登录会话。Cookie 可能已过期、失效，或复制时没有包含有效登录态；这不一定代表 Spotify 或歌曲搜索出了问题。

按下面步骤更新，不需要改代码：

1. 在网易云网页版重新登录。
2. 按上面「4. 获取网易云 Cookie」的步骤，在 Network 请求的 **Request Headers → Cookie** 中复制新的完整 Cookie。
3. 打开自己 Fork 的 **Settings → Secrets and variables → Actions**，在 Repository secrets 中找到 `NETEASE_COOKIE`，点 **Update**（如果没有这个 Secret，则点 **New repository secret**）。名称仍填写 `NETEASE_COOKIE`，值粘贴刚复制的 Cookie 并保存。
4. 打开 **Actions → Sync NetEase Daily Recommendations → Run workflow**，选 `main` 分支并启动一次正式同步。
5. 等待运行结束：绿色勾号表示 workflow 成功；再查看日志中的同步结果，确认歌曲已添加到目标 Spotify Playlist。若仍报 301，请重新登录后再复制一次，并确认复制的是完整的 `Cookie` 请求标头，而不是某一个单独 Cookie。

每个使用者都应在自己的 Fork 中保存自己的 Cookie。Cookie 需要在失效时手动更新；重新登录、更新 Secret 后再次运行 workflow 即可恢复。更新 Cookie 本身不会改动代码或 Playlist，只有运行正式同步时才会更新 Playlist。

## 匹配优化

**Latest**

- 优化 Spotify 搜索与候选筛选，改进多语言歌名/艺人及版本识别。
- 增加 MusicBrainz / ISRC 辅助核验；证据不足时仍跳过，不猜测。

匹配策略保持保守：**无法可靠确认的歌曲会跳过，而不是强行匹配。**

## License

MIT License，详见 [LICENSE](LICENSE)。
