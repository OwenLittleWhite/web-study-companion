# 安装与运行

本文用于从全新 clone 开始运行 Study Companion。项目由两部分组成：

- `extension/`：Chrome/Edge Manifest V3 扩展，无需构建。
- `server/`：运行在本机的 Python/FastAPI 服务，负责 ASR、问答和数据存储。

## 1. 环境要求

基础环境：

- Git
- Python 3.10+
- 能创建 Python `venv` 的 Linux/WSL 环境
- Chrome/Edge 116+

可选本地 ASR 环境：

- NVIDIA GPU 和可用的 WSL/Linux GPU 驱动
- 足够的磁盘空间存放 Python 依赖和 FunASR 模型缓存

已完整验证的机器环境是 Windows 11 + WSL2 Ubuntu 22.04 + NVIDIA GPU。核心后端依赖和云端
ASR 不要求安装本地 FunASR。本地 CPU 模式可通过 `FUNASR_DEVICE=cpu` 尝试，但当前没有做与
GPU 路径同等强度的延迟验收。

## 2. 获取代码

```bash
git clone https://github.com/OwenLittleWhite/web-study-companion.git
cd web-study-companion
```

## 3. 安装后端核心依赖

```bash
bash scripts/bootstrap.sh
```

该脚本会：

1. 创建 `.venv/`；
2. 安装 `server/requirements.txt`；
3. 在不存在时从 `.env.example` 复制出 `.env`。

它不会覆盖已有 `.env`，也不会自动安装体积较大的本地 ASR 依赖。

## 4. 选择 ASR 安装方式

### 方式 A：只用阿里云 Qwen ASR

编辑 `.env`：

```dotenv
FUNASR_PRELOAD=false
DASHSCOPE_API_KEY=
```

API Key 可留空，启动后在侧边栏的“阿里云识别”配置中填写并测试。配置会保存在本机
`data/asr_config.json`，不会进入扩展目录。

### 方式 B：安装本地 FunASR

```bash
.venv/bin/python -m pip install -r server/requirements-local-asr.txt
```

本地模型配置为：

```dotenv
FUNASR_MODEL=paraformer-zh-streaming
FUNASR_DEVICE=cuda:0
FUNASR_PRELOAD=true
```

首次启动需要下载模型并完成预热，耗时取决于网络、缓存和设备。等待服务终端出现
`Application startup complete` 后再开始采集。

## 5. 启动与停止后端

### 轻量启动：只启动服务

在仓库根目录运行：

```bash
bash scripts/start-server.sh
```

该脚本会显式设置 `FUNASR_PRELOAD=false`，不受 `.env` 中旧值影响，也不会在服务启动阶段加载
FunASR。HTTP API、Session、导出、云端 ASR 和问答仍然可用。如果随后选择本地 ASR，模型会在
第一次本地采集时才延迟加载，第一次等待时间会更长。

### 本地模式：启动服务并预加载模型

```bash
bash scripts/start-server-local-asr.sh
```

该脚本会显式设置 `FUNASR_PRELOAD=true`，在 HTTP 服务开始接受请求前加载并预热本地模型。它会
明显使用更多内存和 GPU 资源，只在确实需要本地识别时运行。

健康检查：

```bash
curl http://127.0.0.1:8765/health
```

返回结果中：

- `ok: true` 表示 HTTP 服务可用；
- `providers.local-funasr.ready` 表示本地依赖是否可见；
- `providers.qwen-cloud.ready` 表示云端 ASR 是否已有 Key。

两个脚本都在当前终端以前台方式运行，使用 `Ctrl+C` 安全停止。项目目前没有后台守护或系统服务
脚本。

## 6. 加载浏览器扩展

1. 打开 `chrome://extensions` 或 `edge://extensions`；
2. 开启“开发者模式”；
3. 点击“加载已解压的扩展程序”；
4. 选择仓库中的 `extension/` 目录；
5. 将扩展固定到工具栏，便于在目标标签页主动授权。

Windows 浏览器访问 WSL 文件时，目录形式通常为：

```text
\\wsl.localhost\<发行版名称>\home\<用户名>\...\web-study-companion\extension
```

修改扩展代码后，需要在扩展管理页点击“重新加载”。修改 Python 代码后，需要停止并重新启动
后端服务。

## 7. 首次使用

1. 打开一个有音频或视频的普通网页；
2. 点击扩展工具栏图标，打开侧边栏并授权当前标签页；
3. 配置识别方式；
4. 手动点击“开始采集”；
5. 播放网页媒体并观察逐字稿；
6. 点击“结束采集”，或加载历史 Session 后继续采集。

工具栏授权不会自动开始采集。切换到不同标签页或跨域导航后，需要重新点击工具栏图标授权。

## 8. 验证安装

不需要云端 Key 或模型下载的基础检查：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q server tests scripts
.venv/bin/python scripts/validate_extension.py
.venv/bin/python -m pip check
```

本地模型验证会实际加载模型并做一次转写：

```bash
.venv/bin/python scripts/verify_local_asr.py
```

服务启动后，可执行完整 WebSocket + ASR + Session 存档链路验证：

```bash
.venv/bin/python scripts/verify_ws_pipeline.py
```

机器级安装记录、当时执行过的命令和版本证据见 [ENVIRONMENT.md](ENVIRONMENT.md)。它是一个
已验证环境的审计日志，不代表所有系统都必须使用完全相同的驱动或缓存路径。
