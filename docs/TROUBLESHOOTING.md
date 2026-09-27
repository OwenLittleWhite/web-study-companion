# 常见问题与排错

## 侧边栏提示无法连接本机服务

先在 WSL/Linux 终端检查：

```bash
curl http://127.0.0.1:8765/health
```

若连接失败，在仓库根目录运行：

```bash
bash scripts/start-server.sh
```

保持该终端打开。若修改过 `COMPANION_PORT`，扩展中的固定地址和 `manifest.json` 权限也必须同步
修改；最简单的恢复方式是继续使用默认 `8765`。

## 服务启动很久，像是卡住

当 `FUNASR_PRELOAD=true` 时，服务会在启动阶段下载、加载并预热本地模型。观察终端日志和 GPU
占用，等待 `Application startup complete`。只使用云端识别时可设置：

```dotenv
FUNASR_PRELOAD=false
```

然后重启服务。

## 本地识别不可用

检查健康接口中的 `providers.local-funasr`，并确认安装了本地依赖：

```bash
.venv/bin/python -m pip install -r server/requirements-local-asr.txt
.venv/bin/python scripts/verify_local_asr.py
```

GPU 报错时检查 `FUNASR_DEVICE`、驱动可见性和 PyTorch 安装。若临时改用云端，把识别方式切到
“阿里云识别”，不需要删除本地环境。

## 云端 ASR 连接失败

- 确认 Key 属于所选地域可访问的 DashScope 服务；
- 北京与新加坡使用不同 WebSocket 端点，优先通过侧边栏地域选项切换；
- 确认模型是 UI 支持的 3.1 或 3.0 Streaming 模型；
- 使用“测试连接”，验证成功后再保存；
- 服务端读取配置时不会回显旧 Key，输入框留空表示保留已保存 Key。

## 点击工具栏后为什么没有自动开始

这是预期交互。工具栏点击用于获得 Chrome 对当前标签页的捕获授权并打开侧边栏；真正采集必须
在选好本地/云端和语言后，手动点击“开始采集”或“继续采集”。

## 新网页无法开始，提示需要重新授权

`tabCapture` 授权绑定当前标签页和页面导航。切换标签页、关闭标签页或跨域跳转后，重新点击一次
工具栏图标，再在侧边栏开始。

## 网页有声音但没有逐字稿

依次确认：

1. 本机 `/health` 正常；
2. 侧边栏显示正在采集；
3. 网页标签页本身确实在输出声音且未静音；
4. 所选 Provider 已就绪；
5. 扩展 Service Worker、offscreen 文档和后端终端没有错误。

DRM 或企业策略保护页面可能禁止捕获。项目不绕过 DRM。

## 暂停期间时间戳仍推进

标准 `<video>` / `<audio>` 会被监控，暂停时不应继续发送空白音频。WebAudio、自绘播放器、
跨域子框架或站点自定义媒体层可能无法暴露标准状态，此时会退回音频流时间。可以先在普通 HTML5
视频站点复现，以区分扩展缺陷和页面结构限制。

## 继续采集后时间从零开始

当前版本会把新片段追加到旧时间轴末尾。先确认后端和扩展都是同一最新版本，并在扩展管理页
重新加载扩展、重启后端。旧版本已经保存的明显时间回跳会在读取和导出时修复展示，但原始 JSONL
不会被静默改写。

## 关闭前没点“结束采集”，内容会丢吗

每个确认后的最终片段会立即写 SQLite 和 `transcript.raw.jsonl`，不依赖结束按钮。异常关闭时，
最后一段尚未被 ASR 确认为最终稿的临时文本可能丢失；已经确认的内容可从历史 Session 恢复。

## 删除或重命名 Session 报 409

正在采集的 Session 不能删除或重命名。先结束采集，再操作。若 UI 与实际状态不一致，检查后端
版本并刷新侧边栏；后端重启会清空实时活跃集合，但不会删除 Session 内容。

## 问答提示上下文过长

勾选逐字稿时，后端会选择相关片段；如果模型仍明确报告上下文超限，会自动用最近一半逐字稿
重试一次。仍失败时，可取消勾选逐字稿、缩短问题，或选择上下文窗口更大的模型。

## WSL 中的扩展目录选不到

在 Windows 文件选择器地址栏输入：

```text
\\wsl.localhost\<发行版名称>\完整\Linux\路径\web-study-companion\extension
```

也可以在 WSL 终端运行 `explorer.exe .` 打开当前目录，再选择 `extension/`。不要选择仓库根目录，
Chrome 需要直接看到 `manifest.json`。

## Session 数据在哪里

默认在仓库根目录 `data/`。如果设置了 `COMPANION_DATA_DIR`，以该路径为准。排错时不要公开粘贴
`asr_config.json`、`llm_config.json` 或 `.env`，这些文件可能包含真实 Key。
