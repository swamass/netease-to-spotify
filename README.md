# 网易云每日推荐 → Spotify

获取网易云每日推荐，经 Spotify 搜索、版本冲突检测和 MusicBrainz/ISRC 核验后更新指定 Playlist。证据不足时跳过歌曲，不强行匹配。
## 项目简介与特点
- 支持多语言标题/艺人名，以及 Live、Remix、Acoustic 等版本识别。
- 网易云使用 `NETEASE_COOKIE`；Spotify 使用 OAuth Refresh Token。
- 支持 GitHub Actions 云端同步，也支持 macOS 本地浏览器会话同步；两者独立。

## 快速开始
### 安装与 Spotify 授权
```bash
git clone https://github.com/你的用户名/netease-to-spotify.git
cd netease-to-spotify
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```
在 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) 创建 App，并添加 Redirect URI：

```text
http://127.0.0.1:8888/callback
```
运行本地授权工具，按提示输入 Client ID、Client Secret 和 Playlist URL/ID：

```bash
.venv/bin/python setup.py
```
`setup.py` 只将 OAuth 配置保存到本机 `~/.config/netease-to-spotify/.env`，不会配置 GitHub Actions。首次授权后，本地需要：
`SPOTIFY_CLIENT_ID`、`SPOTIFY_CLIENT_SECRET`、`SPOTIFY_REFRESH_TOKEN`、`SPOTIFY_PLAYLIST_ID`。
```bash
chmod 600 ~/.config/netease-to-spotify/.env
```
### GitHub Actions 云端同步

在自己 Fork 的 **Settings → Secrets and variables → Actions** 配置上述四个 Spotify 变量以及 `NETEASE_COOKIE`，然后从 **Actions → Sync NetEase Daily Recommendations → Run workflow** 手动运行。正式 workflow 也会按既有 schedule 运行；不要打印或提交任何 Secret、Cookie、Token。

## 网易云 Cookie 获取与更新
### macOS 浏览器 Profile
本地同步复用独立 Profile：`~/.local/share/netease-to-spotify-browser`。首次使用或登录失效时安装依赖和 Chromium：

```bash
.venv/bin/python -m pip install -r local-requirements.txt
.venv/bin/python -m playwright install chromium
```
脚本会打开该 Profile，请在网易云网页中手动登录/扫码。密码不会被读取或保存，Cookie 不写入仓库、`.env` 或日志。

### 更新 GitHub Secret
先登录 GitHub CLI，再运行：

```bash
gh auth login
.venv/bin/python scripts/update_netease_cookie_secret.py
```
脚本默认目标是 `swamass/netease-to-spotify`。其他 Fork 必须指定自己的仓库，避免误更新原仓库：

```bash
.venv/bin/python scripts/update_netease_cookie_secret.py \
  --repo 用户名/netease-to-spotify
```
流程：读取本地 Cookie 并调用每日推荐接口验证；有效则直接更新 Secret；明确认证失效（业务码 `301`）则清除失效登录 Cookie，在同一 Profile 中重新扫码，验证新 Cookie 成功后才更新。网络错误、其他 API 错误、Cookie 不完整或扫码超时会停止，不覆盖旧 Secret；最多重新登录一次。该脚本不运行 Spotify 同步。

首次运行更新脚本会打开独立 Chromium；请在网易云网页中登录或用 App 扫码，验证成功后脚本自动更新 GitHub Secret。

### Windows 等其他平台
在已登录网易云网页的开发者工具中，从 Network 请求的 **Request Headers → Cookie** 复制完整 Cookie，保存到自己 Fork 的 GitHub Actions Secret `NETEASE_COOKIE`。不要复制单个 Cookie，也不要把 Cookie 发到聊天、Issue、截图、日志或仓库。

## macOS 本地自动同步（可选）
完成 `.env` 和 Chromium 安装后，先手动运行：

```bash
.venv/bin/python scripts/local_sync.py
```
首次运行会打开浏览器；推荐获取失败、匹配数为零或认证异常时不会修改 Playlist。

安装/检查/卸载已有 LaunchAgent：

```bash
scripts/install_local_sync.sh
launchctl print "gui/$(id -u)/com.swamass.netease-to-spotify"
scripts/uninstall_local_sync.sh
```
任务每 5 分钟唤醒一次，由 Python `zoneinfo` 按 `Asia/Shanghai` 判断，仅在北京时间每天 06:10 之后首次执行；Mac 睡眠后当天醒来会补执行，同一天不会重复尝试。失败后当天不会自动重试。

日志：`~/Library/Logs/netease-to-spotify/sync.log` 和 `sync.error.log`。Automator 双击应用可以作为用户自行创建的快捷入口，但不是仓库提供的安装程序。

## 常见问题

- **301 / Cookie 失效**：macOS 用户运行 Cookie 更新脚本，重新扫码后自动验证并更新 GitHub Secret；其他平台需要手动更新 Cookie。完成后可以重新运行 GitHub Actions。
- **`Missing local environment values`**：检查 `.env` 的四个 Spotify 变量和 `0600` 权限；网易云 Cookie 不放入 `.env`。
- **Playlist 未更新**：查看本地或 Actions 日志。网易云失败、推荐为空、匹配为零、Spotify 认证失败或匹配异常时会保留现有 Playlist。
- **选择哪种方式**：GitHub Actions 不要求 Mac 开机但需要维护 Secrets；macOS 本地复用浏览器状态但需要 Mac 按计划运行。两者不共享 Profile 或配置。

## License

MIT License，详见 [LICENSE](LICENSE)。
