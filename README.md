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

先登录 [网易云音乐网页版](https://music.163.com/)。以 Chrome 为例，打开开发者工具，进入 **Application → Storage → Cookies → https://music.163.com**，复制自己登录会话的完整 Cookie 内容；也可以在 **Network** 请求的 **Request Headers → Cookie** 中复制。

不要复制 `Cookie:` 这个字段名，只复制后面的完整内容，并填入 `NETEASE_COOKIE`。Cookie 是敏感信息，可能过期，不能提交到仓库。

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

### 6. 先运行 Dry Run

打开自己的仓库 **Actions → NetEase Spotify Match Dry Run → Run workflow**。运行完成后查看日志和 Artifacts。

Dry Run 只获取推荐、搜索和匹配，不会清空、添加或修改 Spotify Playlist。

### 7. 运行正式同步

确认 Dry Run 没有配置或认证错误后，打开 **Actions → Sync NetEase Daily Recommendations → Run workflow**。

正式同步会用当天成功匹配的歌曲替换目标 Playlist，建议为本项目创建独立 Playlist。之后 GitHub Actions 会按 workflow 的 schedule 自动运行，当前 cron `0 22 * * *` 对应北京时间次日约 06:00，实际可能有调度延迟。

## 匹配优化

**Latest**

- 改进跨语言艺人名识别
- 支持简繁体与部分中日汉字差异
- 减少同名歌曲与错误艺人误匹配
- 改进 Live / Remix / Acoustic / Cover 等版本识别
- 兼容不同平台的专辑名与时长差异
- 加入 MusicBrainz / ISRC 辅助验证

匹配策略保持保守：**无法可靠确认的歌曲会跳过，而不是强行匹配。**

## License

MIT License，详见 [LICENSE](LICENSE)。
