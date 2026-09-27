# 前端扩展说明

前端是无需打包的 Chrome/Edge Manifest V3 扩展，代码位于 `extension/`。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `manifest.json` | 扩展元数据、权限、侧边栏和后台 Service Worker 注册 |
| `background.js` | 工具栏授权、Session 创建、采集状态协调、标准媒体状态探测 |
| `offscreen.html` / `offscreen.js` | 持有标签页媒体流、Web Audio 转码、WebSocket 推流 |
| `sidepanel.html` / `sidepanel.css` | 自适应侧边栏布局和交互结构 |
| `sidepanel.js` | Session、配置、逐字稿、问答、导出等 UI 状态 |
| `markdown.js` | 模型回答的受控 Markdown 渲染与 HTML 转义 |

## 权限说明

扩展声明的主要权限：

- `activeTab`、`tabCapture`：仅在用户点击工具栏后访问当前标签页音频；
- `sidePanel`：显示主界面；
- `offscreen`：让采集在侧边栏重新渲染时仍由独立文档持有；
- `scripting`：观察普通页面中标准 `<video>` / `<audio>` 的播放状态；
- `storage`：保存界面偏好、当前采集引用和授权状态；
- `tabs`：读取当前标签页标题、URL 和生命周期。

`host_permissions` 只包含 `127.0.0.1:8765` 和 `localhost:8765`，没有申请 `<all_urls>`。
网页访问来自用户对当前标签页的临时授权。

## 采集生命周期

1. 用户点击扩展图标。
2. `background.js` 记录当前标签页授权并打开侧边栏，不创建 Session。
3. 用户在侧边栏选好 ASR 参数，点击“开始采集”或“继续采集”。
4. 后台调用 `chrome.tabCapture.getMediaStreamId()`，把 stream id 交给 offscreen 文档。
5. offscreen 文档创建音频图，保留网页声音，同时转成 16 kHz、16-bit、单声道 PCM。
6. PCM 通过 `ws://127.0.0.1:8765/ws/transcribe` 发送给本机服务。
7. 服务回传临时稿、最终稿和状态；侧边栏更新 UI，最终稿已经由后端落盘。
8. 用户停止、标签页关闭或连接异常时，采集状态被清理，Session 保留。

为避免重复启动，后台保存 `captureStarting` 锁；超过 30 秒的旧启动锁会自动清理。扩展还会核对
Chrome 实际捕获列表，避免 UI 把已经失效的流误判成正在采集。

## UI 状态

- 默认主区域显示逐字稿。
- 输入框始终可见；聚焦后自动切换到占满主区域的问答视图。
- 顶部“逐字稿 / 问答”可手动切换，同一时间只展开一个主内容区。
- 问答视图打开时，后台转写继续落盘；标签显示新增逐字稿数量。
- 逐字稿在用户停留于底部附近时自动跟随最新内容；切回逐字稿会定位到末尾。
- 历史 Session 加载后可继续采集，原问答和逐字稿不会清空。

## 浏览器中保存什么

`chrome.storage` 只保存扩展运行状态和非敏感偏好，例如 ASR 选择、语言、最近 Session id、当前
采集引用。API Key 不写入浏览器存储；密钥由本机后端保存。

Session 的逐字稿和问答也不以浏览器存储作为真实来源。侧边栏每次恢复时从本机服务读取完整
Session，所以清空扩展状态不会等于删除 Session 数据。

## 本地服务地址

当前扩展在 `background.js` 和 `sidepanel.js` 中使用固定地址：

```text
http://127.0.0.1:8765
ws://127.0.0.1:8765
```

如果修改 `COMPANION_PORT`，还必须同步修改这两个文件及 `manifest.json` 的
`host_permissions`，然后重新加载扩展。仅修改 `.env` 端口不会让扩展自动发现新地址。

## 开发调试

- 在 `chrome://extensions` 的扩展卡片中打开 Service Worker 控制台，查看授权和后台错误。
- 在侧边栏中使用开发者工具查看 UI 请求和渲染错误。
- offscreen 文档可从扩展的 Inspect views 中打开。
- 运行静态校验：

```bash
.venv/bin/python scripts/validate_extension.py
```

不要把 API Key 硬编码进任何 `extension/*.js` 或 `manifest.json` 文件。
