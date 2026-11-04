# 新手使用指南

本指南面向第一次使用 GitHub 和终端的用户。推荐先配置 GitHub Actions，再运行只读 Dry Run，确认结果后才启动正式同步。

## 1. 准备账号和软件

你需要：

- 一个 GitHub 账号，用来保存自己的项目副本。
- 一个 Spotify 账号和一个准备接收歌曲的 Playlist。
- 建议新建一个专门接收每日推荐的 Spotify Playlist，避免覆盖其他歌单。
- 一个网易云音乐账号，并能在网页中登录或用 App 扫码。
- Git 和 Python 3.12。macOS 本地同步还需要 Chromium 和 GitHub CLI；只使用 GitHub Actions 时仍需要 Python 来运行授权工具。

“Fork”是把别人的 GitHub 项目复制到你自己的账号下；“Secret”是 GitHub 提供的加密配置项，程序可以读取但日志不会显示其值。

## 2. Fork 项目

1. 打开项目 GitHub 页面。
2. 点击右上角 **Fork**。
3. 选择你的账号作为 **Owner**，确认仓库名仍为 `netease-to-spotify`。
4. 打开 Fork 后，点击 **Code → HTTPS**，复制仓库地址。

在终端执行以下命令，把地址中的用户名换成你的 GitHub 用户名：

```bash
git clone https://github.com/你的用户名/netease-to-spotify.git
cd netease-to-spotify
```

完成后应看到项目文件夹，并能看到 `.github`、`src` 等目录。

## 3. 准备本地环境

这一步只用于运行 Spotify 授权工具。打开终端，进入项目目录：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果提示找不到 `python3.12`，先安装 Python 3.12，再重新执行。Windows 用户可将 `python3.12` 替换为已安装的 Python 命令，并使用对应的虚拟环境路径。

## 4. 创建 Spotify App

Spotify App 是允许本项目代表你访问 Spotify 的应用配置。

1. 打开 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) 并登录。
2. 点击 **Create app**。
3. 在 App Settings 中找到 **Redirect URIs**，添加：

   ```text
   http://127.0.0.1:8888/callback
   ```

4. 保存设置，并记下 **Client ID** 和 **Client Secret**。Client Secret 只应保存在本地或 GitHub Secret 中，不要发给任何人。

## 5. 完成 Spotify 授权

在项目根目录执行：

```bash
.venv/bin/python setup.py
```

按提示输入 Client ID、Client Secret、Playlist URL 或 Playlist ID，并在浏览器中同意授权。授权工具会在本机生成：

```text
~/.config/netease-to-spotify/.env
```

该文件只保存本地配置，不会自动填写 GitHub。确认文件包含以下四项，并限制权限：

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REFRESH_TOKEN
SPOTIFY_PLAYLIST_ID
```

```bash
chmod 600 ~/.config/netease-to-spotify/.env
```

## 6. 配置 GitHub Secrets

GitHub Actions 不会读取你 Mac 上的 `.env`，需要在自己的 Fork 中单独配置。

1. 打开 Fork 的 **Settings → Secrets and variables → Actions**。
2. 点击 **New repository secret**。
3. 依次创建以下五项，名称必须完全一致：

   ```text
   SPOTIFY_CLIENT_ID
   SPOTIFY_CLIENT_SECRET
   SPOTIFY_REFRESH_TOKEN
   SPOTIFY_PLAYLIST_ID
   NETEASE_COOKIE
   ```

4. 将对应值粘贴到 Value 中并保存。可以在本机复制 `.env` 中的 Spotify 值，但不要把这些值发到聊天、日志或 Issue。

## 7. 配置网易云登录

`NETEASE_COOKIE` 是网易云网页登录状态的 Cookie，不是网易云密码。

1. 在浏览器打开 [网易云音乐网页版](https://music.163.com/) 并登录。
2. 打开开发者工具，进入 **Network**，刷新页面。
3. 点击一个发往 `music.163.com` 的请求。
4. 在 **Request Headers** 找到完整的 `Cookie` 值并复制。
5. 把完整值填入你自己的 Fork 的 `NETEASE_COOKIE` Secret。

不要只复制 `MUSIC_U` 或 `__csrf`，也不要保存到代码仓库。Cookie 可能过期，更新方法见 [Mac 使用指南](macos.md)。

## 8. 第一次运行 Dry Run

Dry Run 是只读取推荐、搜索和匹配的检查，不会清空或修改 Spotify Playlist。

1. 打开自己 Fork 的 **Actions**。
2. 选择 **NetEase Spotify Match Dry Run**。
3. 点击 **Run workflow**，选择 `main`，再次点击运行。
4. 打开新运行，等待 **Run read-only matching** 完成。

绿色勾号表示流程成功。查看日志中的推荐数量、匹配数量和未匹配歌曲；如果 Cookie 或 Spotify 配置错误，先按 [故障排查指南](troubleshooting.md) 修复。

## 9. 启动正式同步

⚠️ 正式同步会替换目标 Playlist 中的全部原有歌曲，不是追加。例如当天推荐 30 首、成功匹配 22 首，同步后目标歌单只包含这 22 首。网易云推荐获取失败或匹配数为零时，会保留原有歌单。

确认 Dry Run 没有认证或配置错误后：

1. 打开 **Actions → Sync NetEase Daily Recommendations**。
2. 点击 **Run workflow**，选择 `main`。
3. 确认这是正式同步后点击运行。

正式同步只会在推荐获取成功且有有效匹配时更新 Playlist。工作流也会按既有 schedule 自动运行。

## 10. 确认同步成功

打开正式运行详情，确认 **Run sync** 步骤为绿色，并查看日志中的推荐和匹配数量。然后打开 Spotify 目标 Playlist，确认歌曲顺序和数量符合预期。

如果运行失败或匹配数为零，项目的保护逻辑会保留原 Playlist；不要仅因为日志显示部分匹配就重复启动正式同步。
