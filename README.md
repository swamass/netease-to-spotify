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
