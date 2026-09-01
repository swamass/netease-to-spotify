# 网易云每日推荐 → Spotify

每天获取网易云音乐每日推荐，通过 Spotify Search 和保守 matcher 匹配后刷新到指定 Spotify Playlist。项目由 GitHub Actions 自动运行，不需要自己长期运行服务器。

```
网易云音乐每日推荐 → Spotify Search → 保守匹配 → Spotify Playlist
```

## 功能
- 每天自动同步网易云每日推荐。
- 每首歌曲最多进行两次 Spotify Search。
- 提供只读 Dry Run，正式同步前可检查结果。
- 匹配不可靠、配置缺失或 Spotify 限流时保留原 Playlist。

## 匹配策略
本项目优先保证匹配准确性，而不是追求 100% 匹配率。matcher 综合考虑歌曲标题、艺人、专辑、时长，以及 Live / Remix / Remaster 等版本信息。无法可靠确认时会跳过，而不是强制加入可能错误的版本。

## 使用前准备
- Python 3.12+
- 自己的 Spotify Developer App
- 一个可修改的 Spotify Playlist
- 已登录的网易云音乐账号

## 快速开始
### 1. Fork 仓库
Fork 本仓库，然后 clone 你自己的副本。

### 2. 创建 Spotify App
打开 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)，登录后点击 **Create app**。创建后进入该 App 的 **Settings**：
- **Client ID** 在 App 页面直接可见。
- 点击 **View client secret** 查看 Client Secret；不要公开或提交它。
- 在 **Redirect URIs** 添加：

```
http://127.0.0.1:8888/callback
```

### 3. 运行 Setup
```bash
python -m pip install -r requirements.txt
python setup.py
```
Setup 接收 Playlist URL / ID，生成 OAuth URL，验证 OAuth state 并获取 Refresh Token。不会保存凭据或自动上传 GitHub Secrets，Client Secret 会隐藏输入。

### 4. 获取网易云 Cookie
打开并登录 [网易云音乐](https://music.163.com/)。以 Chrome 为例：按 **F12** 打开开发者工具，进入 **Application → Storage → Cookies → https://music.163.com**，确认当前是自己的登录会话；也可在 **Network** 中打开网易云请求查看 **Request Headers** 的 `Cookie`。

复制完整的 Cookie header 内容（不要复制 `Cookie:` 这几个字），包括代码实际需要的 `__csrf` 字段，粘贴到 GitHub Secret `NETEASE_COOKIE`。不要把 Cookie 发给他人。Cookie 过期后需要重新获取。

### 5. 配置 GitHub Secrets
在你自己的 Fork 仓库中打开 **Settings → Secrets and variables → Actions → New repository secret**。每次填写：
- **Name**：下表中的变量名
- **Secret**：从 Setup 或自己的登录会话获得的对应值



| Secret | 用途 |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify App Client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify App Client Secret |
| `SPOTIFY_REFRESH_TOKEN` | Spotify OAuth Refresh Token |
| `SPOTIFY_PLAYLIST_ID` | 目标 Playlist |
| `NETEASE_COOKIE` | 网易云登录 Cookie |

### 6. 先运行 Dry Run
打开你自己的仓库 **Actions**，选择 **NetEase Spotify Match Dry Run**，点击 **Run workflow → Run workflow**。运行完成后打开该 run 查看日志和 **Artifacts**。有匹配统计且没有配置/认证错误即可继续；它不会清空、添加或修改 Playlist。

### 7. 运行正式同步
确认 Dry Run 后，打开 **Actions → Sync NetEase Daily Recommendations → Run workflow → Run workflow** 进行第一次正式运行。确认成功后，后续由 schedule 自动执行。正式同步会替换目标 Playlist 内容，建议使用独立 Playlist。

## Dry Run
Dry Run 是只读验证入口，会生成匹配日志和 `match_report.json` artifact，不会调用 Playlist 写入接口。

## 每日自动同步
正式 workflow 支持手动运行和定时运行：
```
0 22 * * *
```
GitHub Actions cron 使用 UTC，对应北京时间次日约 06:00；GitHub 调度可能有延迟。成功时会用当天匹配到的歌曲替换 Playlist；失败时保留原内容。

## 匹配原则
1. 用标题召回候选。
2. 用艺人确认身份。
3. 用专辑和时长辅助排序。
4. 检查是否存在不同录音版本。
5. 不确定就跳过。

## 已知限制
- Spotify Search 不一定返回目标录音。
- 不同地区版权限制可能导致歌曲不可用。
- 网易云和 Spotify 的 metadata 写法可能不同。
- 中文、日文、罗马字艺人或标题可能导致 unmatched。
- Live、Remix、Remaster 等版本可能被主动拒绝。
- Cookie 会过期；unmatched 不一定意味着程序出错。

## 安全说明
- 不要提交 `.env`、Spotify Client Secret、Refresh Token 或网易云 Cookie。
- 使用 GitHub Secrets 保存运行时凭据。
- 凭据意外公开后立即轮换。
- 不要在日志中输出 Token、Secret、Cookie 或 OAuth code。
- Fork 用户必须使用自己的凭据。

## 常见问题
**Missing required environment variable**：检查五个 GitHub Secrets 是否都已创建且非空。

**Spotify 401**：检查 Client ID、Client Secret、Refresh Token、Redirect URI 和 App 设置。

**No sufficiently reliable candidate**：matcher 无法可靠确认候选，不一定是程序错误。

**网易云认证失败**：Cookie 可能过期，请重新获取。

**Dry Run 成功但 Playlist 没变化**：这是正常的，Dry Run 不写 Playlist。

## 本地开发与测试
```bash
python -m pip install -r requirements.txt
PYTHONPATH=. python -m pytest
```

## License
本项目采用 MIT License，详见 [LICENSE](LICENSE)。