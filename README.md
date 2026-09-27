# Study Companion

一个面向网页学习场景的浏览器侧边栏：采集当前标签页音频，实时生成逐字稿，在同一个
Session 中连续问答，并把逐字稿与对话导出到本地。

它不绑定 YouTube 或任何单一网站。扩展只负责当前标签页音频采集和交互，本机 Python
服务负责 ASR、问答和持久化。

## 功能

- Chrome/Edge Manifest V3 侧边栏，用户手动授权并开始采集。
- 支持本地 FunASR 和阿里云 Qwen Audio Streaming 实时转写。
- 云端临时结果原位修订，只有确认后的句子写入 Session。
- 对标准 `<video>` / `<audio>` 跟踪暂停和继续，时间戳按有效播放时长推进。
- 逐字稿边生成边保存；意外关闭侧边栏或未点击“结束采集”时，已确认内容仍保留。
- 历史 Session 可继续采集、重命名和删除，也可随时新建 Session。
- 逐字稿与连续问答共用主内容区；模型回答使用 Markdown 安全渲染。
- 每次提问可单独决定是否携带逐字稿；上下文超限时自动用最近一半逐字稿重试一次。
- 支持 Markdown、TXT、JSON、SRT、VTT 导出。
- API Key 只保存在本机服务，不写入扩展存储、Session 或导出文件。

## 架构

```text
当前网页标签页
   │ tabCapture / Web Audio
   ▼
Chrome 侧边栏 ── PCM 16 kHz / WebSocket ──> 本机 FastAPI 服务
                                              ├─ FunASR（本地）
                                              ├─ Qwen ASR（云端）
                                              ├─ OpenAI 兼容对话接口
                                              └─ SQLite + Session 文件
```

更完整的数据流、权限边界和状态归属见 [架构说明](docs/ARCHITECTURE.md)。

## 快速开始

### 1. 准备环境

- Python 3.10 或更高版本
- Chrome/Edge 116 或更高版本
- Linux 或 WSL2；当前完整验证环境是 Windows 11 + WSL2 Ubuntu 22.04
- 本地 ASR 可选：NVIDIA GPU、可用 CUDA 驱动及足够的模型存储空间

扩展使用原生 JavaScript，不需要 Node.js 或 npm。

### 2. 安装本机服务

```bash
git clone https://github.com/OwenLittleWhite/web-study-companion.git
cd web-study-companion
bash scripts/bootstrap.sh
```

如果要使用本地 FunASR，再安装体积较大的本地识别依赖：

```bash
.venv/bin/python -m pip install -r server/requirements-local-asr.txt
```

只使用云端 ASR 时，在 `.env` 中设置 `FUNASR_PRELOAD=false`，可避免启动时加载本地模型。

### 3. 启动服务

```bash
bash scripts/start-server.sh
```

看到 `Application startup complete` 后，在另一个终端检查：

```bash
curl http://127.0.0.1:8765/health
```

服务以前台方式运行，按 `Ctrl+C` 停止。不要直接删除 `data/`，其中保存了全部 Session
和本机配置。

### 4. 加载浏览器扩展

1. 打开 `chrome://extensions` 或 `edge://extensions`。
2. 开启“开发者模式”。
3. 选择“加载已解压的扩展程序”，指向仓库中的 `extension/`。
4. 在目标网页点击工具栏里的 Study Companion 图标，完成当前标签页授权。
5. 在侧边栏配置本地/云端识别，然后手动点击“开始采集”。

Windows 浏览器加载 WSL 目录时，可使用：

```text
\\wsl.localhost\<发行版名称>\path\to\web-study-companion\extension
```

## 使用方式

工具栏点击只负责打开侧边栏并申请 Chrome 当前标签页权限，不会自动创建 Session 或开始录音。

1. 打开目标音视频网页并保持其为当前标签页。
2. 点击扩展图标授权当前标签页。
3. 在侧边栏选择 ASR 方式和参数。
4. 点击“开始采集”创建新 Session；加载历史记录后，按钮会变成“继续采集”。
5. 点击底部输入框进入问答视图，`Enter` 发送，`Shift+Enter` 换行。
6. 点击“结束采集”停止。采集期间已经确认的逐字稿会即时保存，不依赖这一步才落盘。

## 配置

首次执行 `bootstrap.sh` 会从 `.env.example` 创建本机 `.env`。不要提交真实密钥。

```dotenv
DASHSCOPE_API_KEY=
FUNASR_DEVICE=cuda:0
FUNASR_PRELOAD=true
COMPANION_HOST=127.0.0.1
COMPANION_PORT=8765
COMPANION_DATA_DIR=./data
```

阿里云 ASR 和对话模型也可在侧边栏中测试并保存。若两者都使用 DashScope，可以填写同一个
DashScope API Key；它们仍作为两项配置分别管理。完整字段、地域、模型和安全说明见
[配置说明](docs/CONFIGURATION.md)。

## 数据与隐私

默认数据目录：

```text
data/
├── companion.sqlite3
├── asr_config.json
├── llm_config.json
└── sessions/
    └── 页面标题_sessionid/
        ├── session.json
        ├── transcript.raw.jsonl
        ├── transcript.final.md
        └── conversation.json
```

- 原始音频默认不落盘。
- `.env`、`.venv/` 和整个 `data/` 已加入 `.gitignore`。
- 本机配置文件尽可能以 `0600` 权限写入，读取 API 不回显密钥。
- 选择云端 ASR 或云端对话模型时，相应音频或文本会发送给所选服务商。

## 开发与验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q server tests scripts
.venv/bin/python scripts/validate_extension.py
.venv/bin/python -m pip check
```

需要本地模型和已启动服务的集成验证：

```bash
.venv/bin/python scripts/verify_local_asr.py
.venv/bin/python scripts/verify_ws_pipeline.py
```

## 文档

- [安装与运行](docs/INSTALLATION.md)
- [前端扩展](docs/FRONTEND.md)
- [后端服务](docs/BACKEND.md)
- [配置说明](docs/CONFIGURATION.md)
- [架构与数据流](docs/ARCHITECTURE.md)
- [常见问题与排错](docs/TROUBLESHOOTING.md)
- [开发与贡献](CONTRIBUTING.md)
- [已验证环境与安装日志](docs/ENVIRONMENT.md)

## 已知边界

- DRM、企业策略或浏览器策略保护的页面可能拒绝标签页音频采集。
- 只采集当前标签页音频，不采集麦克风。
- 对标准 `<video>` / `<audio>` 可识别暂停；WebAudio、自绘播放器和部分跨域子框架可能只能
  使用音频流时钟，无法精确感知页面播放状态。
- 本地 FunASR 的效果和延迟依赖设备、模型与音频质量。当前 GPU 路径已验证，CPU 路径未做
  同等强度的性能验收。
- 浏览器商店发布、DRM 页面和所有第三方站点兼容性尚未覆盖；当前通过开发者模式加载扩展。
