# 故障排查

先查看 GitHub Actions 的失败步骤和日志，或查看 macOS 本地日志。不要把日志中的 Cookie、Token 或 Secret 发给别人。

## 网易云登录失效或出现 301

### macOS

如果你只使用 macOS 本地同步，不需要 GitHub CLI；在浏览器中重新登录或扫码即可。只有需要更新 GitHub Actions 的 `NETEASE_COOKIE` 时，才需要使用 GitHub CLI。

首次使用 GitHub CLI 时先登录一次：

```bash
gh auth login
```

然后运行 Cookie 更新脚本：

```bash
.venv/bin/python scripts/update_netease_cookie_secret.py \
  --repo 用户名/netease-to-spotify
```

后续更新不需要重复执行 `gh auth login`。

脚本会打开独立 Chromium。重新登录或扫码后，只有每日推荐接口验证成功才会更新 GitHub Secret。网络错误、其他 API 错误或扫码超时不会覆盖旧值。

### 其他平台

在已登录的网易云网页中，从开发者工具 **Network → Request Headers → Cookie** 复制完整 Cookie，并在自己 Fork 的 **Settings → Secrets and variables → Actions** 中更新 `NETEASE_COOKIE`。不要把 Cookie 写进仓库或 `.env`。

完成后重新运行 GitHub Actions。301 表示网易云接口拒绝当前登录会话，不一定是 Spotify 出错。

## Spotify 授权失败

### 本地授权失败

确认 Spotify App 的 Redirect URI 完全是：

```text
http://127.0.0.1:8888/callback
```

然后重新运行：

```bash
.venv/bin/python setup.py
```

确认 Client ID、Client Secret 属于同一个 Spotify App，并且本机 `.env` 权限为 `0600`。

### Actions 授权失败

检查自己的 Fork 是否包含以下四个 Spotify Secrets，名称必须完全一致：

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REFRESH_TOKEN
SPOTIFY_PLAYLIST_ID
```

不要把本机 `.env` 当作 GitHub Secrets；两者需要分别配置。

## GitHub Actions 运行失败

1. 打开 **Actions**，进入失败的运行。
2. 查看第一个失败步骤，不要只看最后一行。
3. 确认运行的是自己的 Fork 和 `main` 分支。
4. 检查 Secret 名称、Cookie 是否仍有效，以及是否有 GitHub Actions 权限。

先运行 **NetEase Spotify Match Dry Run**。它不会修改 Playlist，适合确认推荐和匹配是否正常。完成后可在该运行页面的 Artifacts 下载 `match-dry-run-report`，其中包含 `match_report.json` 详细报告。

## 为什么有些歌曲没有同步

项目会拒绝标题、艺人、专辑或版本证据不足的候选，例如 Live、Remix、Cover、Karaoke 或明显时长不符的版本。未匹配不一定表示 Spotify 没有这首歌，也可能是为了避免误匹配而主动跳过。

先查看 Dry Run 中的搜索和拒绝原因，不要直接降低匹配标准或手动加入未经确认的版本。

## 为什么 Playlist 没有更新

以下情况会保留现有 Playlist：

- 网易云 Cookie 失效、网络错误或推荐为空。
- Spotify 授权、Playlist 权限或 API 请求失败。
- 所有推荐歌曲都没有通过保守匹配。

确认正式 workflow 的 **Run sync** 步骤成功，并查看日志中的推荐和匹配数量。Dry Run 本身不会更新 Playlist。

## Mac 自动任务没有执行

先确认 LaunchAgent 是否加载：

```bash
launchctl print "gui/$(id -u)/com.swamass.netease-to-spotify"
```

再查看日志：

```bash
tail -f ~/Library/Logs/netease-to-spotify/sync.log \
  ~/Library/Logs/netease-to-spotify/sync.error.log
```

LaunchAgent 每 5 分钟检查一次，但不会主动唤醒睡眠中的 Mac。程序只在北京时间每天 06:10 之后首次执行；Mac 睡眠后当天恢复运行时仍可能补执行，当天已经尝试过或失败后不会自动重试。修复后可手动运行：

⚠️ 这是正式同步，会替换目标 Playlist 的全部原有歌曲，不是追加。

```bash
.venv/bin/python scripts/local_sync.py
```

如果服务没有加载，重新执行 `scripts/install_local_sync.sh`；如果虚拟环境或 Chromium 不存在，按 [Mac 使用指南](macos.md) 安装。
