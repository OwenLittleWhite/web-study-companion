# Environment and Reproduction Journal

本文件记录“实际执行过什么”和“尚未验证什么”。以后任何 Agent 修改运行环境前，先读
`AGENTS.md` 和本文件；安装、升级或删除依赖后，在此追加命令、版本和验证结果。

## 部署边界

- 服务端、Python 虚拟环境、本地 ASR 和 Session 数据均在 **WSL 2 / Ubuntu-22.04** 中。
- Chrome/Edge 运行在 Windows，通过 `127.0.0.1:8765` 访问 WSL 服务。
- Windows 浏览器加载扩展时应选择：
  `\\wsl.localhost\Ubuntu-22.04\home\owen\code\study\projects\web-study-companion\extension`
- ASR API Key 可放在 WSL 项目根目录 `.env`，也可由本机设置接口写入权限为 `0600` 的
  `data/asr_config.json`；问答模型密钥同理可写入 `data/llm_config.json`。密钥绝不写入扩展源码、
  浏览器存储、Session、导出、日志或文档。

## 本机基线（2026-09-25 实测）

执行：

```bash
python3 --version
printenv WSL_DISTRO_NAME
nvidia-smi
df -h /home/owen/code/study/projects
free -h
```

结果：

- Ubuntu `22.04.5 LTS`，WSL 发行版名 `Ubuntu-22.04`，Python `3.10.12`。
- NVIDIA GeForce RTX 5060，显存 `8151 MiB`，Windows 驱动 `591.86`。
- `nvidia-smi` 报告 CUDA `13.1`；PyTorch 实际安装 CUDA 13.0 构建。
- WSL 可用内存约 `15 GiB`，Swap `4 GiB`。
- 安装后 WSL 文件系统剩余约 `631 GiB`。

这些值是机器状态快照，可能变化。修改 CUDA/PyTorch 前必须重新检查。

## 从零复现

### 1. 核心服务

```bash
cd /home/owen/code/study/projects/web-study-companion
bash scripts/bootstrap.sh
```

脚本会创建 `.venv`、升级 pip、安装 `server/requirements.txt`，并在缺失时从
`.env.example` 复制 `.env`。2026-09-25 实际执行成功，得到：

- pip `26.2.1`
- FastAPI `0.117.1`
- Uvicorn `0.36.0`
- HTTPX `0.28.1`
- websockets `15.0.1`

### 2. 本地 FunASR（大体积，可单独安装）

```bash
cd /home/owen/code/study/projects/web-study-companion
.venv/bin/python -m pip install -r server/requirements-local-asr.txt
```

2026-09-25 实际执行成功。下载期间出现过一次 PyPI TLS 重试，pip 自动恢复；最终
`.venv/bin/python -m pip check` 返回 `No broken requirements found.`。关键版本：

- `torch 2.14.0+cu130`
- `torchaudio 2.11.0+cu130`
- `funasr 1.4.16`
- `modelscope 1.40.1`
- `numpy 2.2.6`
- `soundfile 0.14.0`

依赖安装后的 `.venv` 约 `6.1 GiB`。首次模型验证还会下载约 `881 MB` 的
`paraformer-zh-streaming` 权重到 `~/.cache/modelscope`；模型缓存不属于项目文件。

### 3. CUDA 快速验证

2026-09-25 实际执行：

```bash
.venv/bin/python - <<'PY'
import torch
print(torch.__version__, torch.version.cuda)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))
print((torch.ones(4, device="cuda") * 7).sum().item())
PY
```

结果：`torch 2.14.0+cu130`、CUDA build `13.0`、`cuda_available=True`、GPU 为
`NVIDIA GeForce RTX 5060`、GPU 张量结果 `28.0`。这证明 PyTorch CUDA 基础路径可用，
但不能代替真实 ASR 验证。

### 4. 启动服务

```bash
cd /home/owen/code/study/projects/web-study-companion
```

轻量启动不加载本地模型：

```bash
bash scripts/start-server.sh
```

需要服务启动前加载并预热本地 FunASR 时，使用独立入口：

```bash
bash scripts/start-server-local-asr.sh
```

等待终端出现 `Application startup complete` 后再点击扩展工具栏图标。两个脚本会分别强制
`FUNASR_PRELOAD=false/true`，不依赖 `.env` 中可能遗留的旧值。

健康检查：

```bash
curl http://127.0.0.1:8765/health
```

2026-09-25 已实测服务能启动，健康检查、Session 创建/读取/列表和 Markdown 导出均成功。
未配置密钥时，健康检查会明确显示 `qwen-cloud.ready=false`，这不是服务故障。

## Qwen 云端配置

优先在扩展侧边栏选择“阿里云识别”并点击“配置”，保存前会先建立 WebSocket 验证。配置只写入
WSL 本机 `data/asr_config.json`，并且只对新建 Session 生效。也可以编辑本机 `.env` 作为默认值；
不要把实际密钥复制到文档或 Agent 对话：

```dotenv
DASHSCOPE_API_KEY=
QWEN_ASR_WS_URL=the-endpoint-shown-for-your-region
QWEN_ASR_MODEL=qwen-audio-3.1-asr-flash-streaming
QWEN_LLM_BASE_URL=the-compatible-mode-base-url-shown-for-your-region
QWEN_LLM_MODEL=qwen-plus
FUNASR_PRELOAD=false
```

在 2026-09-25 这次基线记录时，本机没有配置 `DASHSCOPE_API_KEY`，因此 Qwen 实时转写和真实
云端连续问答尚未发起请求。
问答模型也可以在扩展内配置兼容接口。密钥由用户配置后再验收，不能把“适配器代码存在”写成
“云端已验证”。

## Windows 浏览器安装

1. 保持 WSL 服务运行。
2. Windows Chrome 打开 `chrome://extensions`，Edge 打开 `edge://extensions`。
3. 开启“开发者模式”，选择“加载已解压的扩展程序”。
4. 选择
   `\\wsl.localhost\Ubuntu-22.04\home\owen\code\study\projects\web-study-companion\extension`。
5. 打开一个会播放声音的普通 HTTPS 页面并保持其为当前标签页。
6. 点击浏览器工具栏中的 Study Companion 图标，只打开侧边栏并授权当前标签页，不会自动创建
   Session 或开始转写。
7. 选择本地/阿里云识别、模型、语言及其他参数，再点击侧边栏“开始采集”。服务已在启动阶段预热
   本地模型；确认服务终端出现 `Application startup complete` 后再开始采集。

限制：浏览器内部页、部分 DRM/企业策略保护页面可能不允许标签页音频采集。当前版本只采集
用户主动开始的当前标签页，不采集麦克风，也不默认保存原始音频。

## 验证命令与状态

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q server tests scripts
.venv/bin/python scripts/validate_extension.py
.venv/bin/python scripts/verify_local_asr.py
.venv/bin/python scripts/verify_ws_pipeline.py  # 需先启动服务并完成上一条
```

2026-09-25 当前结果：

- 完成：14 个 Python 单元测试通过。
- 完成：Python `compileall` 通过。
- 完成：Manifest V3 和两个扩展 HTML 的静态校验通过。
- 完成：`pip check` 无损坏依赖。
- 完成：服务健康检查、Session 创建/读取/历史列表、导出 API 冒烟测试通过。
- 完成：首次 FunASR 模型下载（约 25 分钟，受当时网络速度影响）。
- 完成：真实 16 kHz 语音在 RTX 5060 上输出“欢迎大家来体验达摩院推出的语音识别模型”，
  验证脚本返回 `LOCAL_ASR_OK`。
- 完成：相同真实音频通过 `/ws/transcribe`、FunASR、SQLite 和 Session 文件存档整链路，
  输出相同文本并返回 `WS_PIPELINE_OK`。
- 完成：本地 Provider 在报告 ready 前执行独立 GPU 预热；缓存模型后的全新服务进程整链路
  冒烟测试耗时约 `33.5 s`，随后 600 ms 分块推理约为 `0.14–0.24 s/块`。
- 未验证：Windows Chrome/Edge 中实际加载扩展、标签页采音和 UI 操作。自动化浏览器工具因当前
  WSL 工作目录 URI 不受支持而未能启动，必须按上面的 Windows 手工步骤验收。
- 未验证：Qwen 云端 ASR及真实外部模型问答，因为本机没有 API Key。

系统 Node.js 是 `12.22.9`，无法解析扩展代码中的 optional chaining，因此没有把
`node --check` 结果当作扩展失败；Chrome 最低版本声明为 116，扩展静态校验已通过。若以后要用
Node 做 JS lint，应先在项目内引入受控的新版本工具链并记录安装过程。

## 执行日志

### 2026-09-28 — 拆分轻量服务与本地模型启动入口

- 现象：用户运行原 `scripts/start-server.sh` 后终端整体消失；重新检查时 8765 已无监听，WSL
  uptime 只有约 9 分钟，说明不只是 FastAPI 普通退出，WSL 实例在此前后发生了终止或重启。
- 可见证据：上一 WSL boot 没有正常关机尾迹，也没有留下 OOM kill 记录；结束前最后一条内核异常
  是 `misc dxg ... Ioctl failed: -75`，指向 WSL GPU 桥接。该证据不足以证明唯一根因，因此只记录为
  “本地模型/CUDA 初始化相关的高可能性”，不写成已确认 OOM。
- 根本交互问题：原默认 `FUNASR_PRELOAD=true`，而本机 `.env` 没有覆盖该字段，普通启动脚本会在
  HTTP 监听前直接加载 FunASR 和预热 GPU，用户无法从脚本名称判断资源开销。
- 修复：`scripts/start-server.sh` 现在强制 `FUNASR_PRELOAD=false`；新增
  `scripts/start-server-local-asr.sh`，仅该入口强制加载并预热本地模型；Python 配置和
  `.env.example` 的兜底默认也改为 `false`。
- 数据边界：检查时正式服务已经不在运行；本次没有删除或改写 `data/`、Session、密钥配置或模型
  缓存，也未安装、升级或删除依赖。

### 2026-09-27 — 扩展与服务 0.3.10 旧版续采时间轴兼容

- 复现：当前 Lecture 3 Session 在片段 `1499 → 1500` 处从 `58:01` 回跳到 `00:00.320`；这是扩展
  请求续采时正式服务仍为旧版造成的，后续 10 段均保存了从零开始的 Provider 原始时间。
- 修复：恢复和导出按数据库自增 ID 还原真实采集顺序；检测超过 5 秒的明显时间回跳后，以上一段
  `end_ms` 为后续旧版续采段添加展示偏移。若后续片段已经使用新版绝对时间，则自动退出兼容偏移，
  不重复累加。下一次续采的起点也改为规范化时间轴的最大 `end_ms`。
- 数据边界：SQLite 与 `transcript.raw.jsonl` 中的原始时间戳完全不改写；API 对被兼容的片段额外返回
  `stored_start_ms`、`stored_end_ms` 和 `timeline_repaired=true`。当前 Session 的片段 `1500` 从原始
  `320ms` 展示为 `58:14.510`，最终片段接到 `60:32.020`；SRT 导出同步使用连续时间轴。
- 验证：21 个 Python 单元测试、扩展静态校验、`compileall` 与 `pip check` 通过；正式 API 返回的
  10 个回跳片段全部带审计字段，SRT 尾部为 `01:00:08 → 01:00:32`，SQLite `integrity_check=ok`。
- 环境变更：未安装、升级或删除任何依赖。

### 2026-09-27 — 扩展 0.3.9 逐字稿自动跟随

- 复现：用户截图中黄色实时临时稿已出现在逐字稿底部，但容器滚动位置不会持续跟随内容增长；原实现
  只在最终片段同步写 DOM 后立即设置一次 `scrollTop`，没有覆盖临时稿更新，而且可能早于浏览器布局。
- 修复：所有滚动统一延迟到下一次 `requestAnimationFrame`；用 `MutationObserver` 覆盖最终句追加、
  同段文字增长和黄色临时稿更新，并在从问答切回逐字稿时再次定位末尾。滚动容器禁用浏览器锚点
  抵消，连续事件会合并为一帧，避免重复抖动。
- 验证：20 个 Python 单元测试、扩展静态校验、`compileall` 和 `pip check` 通过；Windows Chrome
  Headless + CDP 使用用户截图同宽的 `659×729` 视口，分别注入 100 段最终稿和两版黄色临时稿，
  两次均得到 `scrollTop == scrollHeight - clientHeight`，差值为 `0px`。
- 部署：确认正式库已无 `ended_at IS NULL` 的 Session 后，以 `SIGTERM` 正常停止旧服务并通过
  `scripts/start-server.sh` 启动后端 `0.3.7`；FunASR 重新加载、GPU 预热完成，`/health` 的本地与
  Qwen Provider 均 ready，SQLite `integrity_check=ok`。扩展 `0.3.9` 仍需用户在浏览器中重新加载。
- 环境变更：本次仅修改扩展静态文件、校验与文档，未安装、升级或删除任何依赖。

### 2026-09-27 — 扩展 0.3.8 暂停感知时间戳

- 复现：用户截图中前两段为 `00:04 / 00:38`，网页视频长时间暂停后，下一段跳到 `55:56`。本地
  FunASR 的时间来自已处理 PCM 样本数，Qwen 时间来自已发送音频流；原扩展在媒体暂停时仍持续发送
  空白 PCM，因此两条链路都会累计暂停时间。
- 修复：在用户已授予的当前标签页内，通过 `chrome.scripting.executeScript` 安装标准
  `<video>/<audio>` 播放状态监视器；暂停、缓冲、等待或拖动期间，Offscreen Document 保持连接但
  不发送 PCM，恢复播放后继续。界面显示“转写与时间戳已暂停”。停止采集时移除页面监视器。
- 权限：Manifest 增加 `scripting`，仍与现有 `activeTab` 临时授权配合；未增加 `<all_urls>` 或永久
  站点访问权限。无标准媒体元素、跨域子框架或 WebAudio 播放器回退到原音频时钟，不伪装为精确。
- 数据边界：只改善之后采集的片段；已有 `55:56` 等时间戳不自动修改，因为现有存档没有可靠的历史
  暂停区间，猜测回写会破坏 append-only 原稿证据。
- 环境变更：本次未安装、升级或删除任何依赖。正式采集仍在进行，因此未重新加载扩展或重启服务。

### 2026-09-27 — 扩展与服务 0.3.7 历史 Session 续采

- 续采：从历史列表加载 Session 后，主按钮显示“继续采集”；启动请求显式携带现有 Session ID，
  后端继续向原 Session 追加确认片段，保留已有逐字稿和连续问答。
- 时间轴：续采开始时读取旧稿最大 `end_ms` 作为偏移，新一轮 ASR 即使从 `0ms` 开始，也会接在旧稿
  末尾，不会因时间戳重置而插入旧内容中间。Qwen 启动上下文同时带入旧稿最近 8 段。
- 新建：顶部增加“＋新建”。它只清除当前 Session 选择和浏览器中的 `lastSessionId`，不删除或改写
  历史数据；随后“开始采集”才创建全新 Session。采集中禁用新建，防止串写。
- 验证：20 个 Python 单元测试、`compileall`、扩展静态校验与 `pip check` 全部通过；新增测试覆盖
  Session 结束后恢复为采集中状态、续采偏移和跨 Provider 追加顺序。隔离数据目录和 `8878` 端口的
  新服务 `/health` 返回 `0.3.7`，Session 创建和读取冒烟通过；测试数据位于系统临时目录，不接触正式库。
  Windows Chrome Headless + CDP 在 `300/380/648px` 下确认“＋新建”等关键控件均在视口内、无横向
  溢出，并执行状态函数确认加载历史后按钮显示“继续采集”且“＋新建”可用。
- 部署：实现时检测到正式采集仍在进行，因此先保留旧进程；确认所有 Session 都已结束后才正常停止
  旧服务并启动正式后端 `0.3.7`。扩展需重新加载到 `0.3.9` 后，续采、新建、暂停感知时间戳与自动
  滚动才会一起生效。
- 环境变更：本次未安装、升级或删除任何依赖。

### 2026-09-27 — 扩展 0.3.6 单内容区问答交互

- 交互：移除逐字稿/问答上下双框和各自放大、折叠按钮；默认只展示逐字稿。底部问答输入框始终
  可见，获得焦点后自动切换为占满主内容区的连续问答，也可通过顶部“逐字稿 / 问答”标签手动切换。
- 输入：`Enter` 发送、`Shift+Enter` 换行；增加 `isComposing` 与 `keyCode=229` 保护，避免中文输入法
  确认候选词时误发送。
- 后台转写：问答视图不会暂停音频采集或写盘；新确认片段继续写入当前 Session，并在逐字稿标签显示
  “新增 N 段”，切回逐字稿后清零。切换视图不会切换 Session 或改写历史数据。
- 空间：本地/云端、模型和语言配置收进顶部摘要弹层，主界面只保留摘要与开始/结束按钮；停止按钮
  改为“结束采集”，明确已确认逐字稿在采集过程中实时保存。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验与 `pip check` 全部通过；Windows Chrome
  Headless 配合 CDP 在 `300/380/648px` 三档视口检查，页面滚动宽度均等于视口宽度，关键按钮和
  输入框都在视口内；实际执行单内容区切换函数与配置弹层开关，互斥显示和 `300px` 弹层边界正确。
  安装态的工具栏授权、输入框焦点及键盘事件仍需用户重新加载扩展后实点验收。
- 环境变更：本次只修改浏览器扩展静态文件、校验脚本与文档，未安装、升级或删除任何依赖；后端
  数据结构和服务进程均未变更。

### 2026-09-27 — 扩展 0.3.5 手动开始采集

- 交互：工具栏点击只打开侧边栏并通过 `activeTab` 授权当前标签页，不再创建 Session 或自动转写；
  用户选择本地/阿里云、模型、语言及其他参数后，点击侧边栏“开始采集”才真正创建 Session。
- 权限边界：授权只保存在 `chrome.storage.session`，浏览器重启会清除；同一标签页同源页面可重复手动
  开始，切换标签页或跨站导航后需要重新点击工具栏授权。未增加全站永久访问权限。
- 状态：增加“已授权、等待手动开始”“正在启动”“授权失效”提示，并在启动阶段锁定参数控件，避免
  重复创建 Session。后端和 Session 数据格式没有变化。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验和 `pip check` 通过；静态回归确认工具栏
  处理函数不再调用 `startAuthorizedCapture`，侧边栏启动请求明确携带当前 Provider 和语言。本地服务
  `/health` 正常、SQLite `integrity_check=ok`。浏览器控制连接受当前 WSL 工作目录限制，安装态的
  “工具栏授权 → 手动开始”仍需用户重新加载扩展后实点验收，未把静态检查写成浏览器实测。
- 环境变更：本次未安装、升级或删除任何依赖。

### 2026-09-26 — 扩展 0.3.4 问答 Markdown 渲染

- 范围：仅对大模型 `assistant` 回答启用 Markdown；用户问题、逐字稿和其他状态文本仍按纯文本显示。
  新回答和从历史 Session 恢复的回答共用同一渲染路径。
- 能力：支持标题、段落、无序/有序/任务列表、引用、分隔线、粗体、斜体、删除线、行内代码、
  围栏代码块、表格和 `http/https/mailto` 链接。
- 安全：未引入远程 CDN 或新依赖；渲染器使用 `createElement`/`textContent` 构建 DOM，禁止用
  `innerHTML` 注入模型内容；链接协议仅允许 `http`、`https` 和 `mailto`，新窗口链接带
  `noopener noreferrer`。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验和 `pip check` 通过。Windows Chrome
  Headless 实际生成 1 个 H1、1 个 H2、2 个粗体、1 个任务复选框、1 张表格、1 个 Python 代码块和
  1 个安全链接；注入样例未产生 `script` 节点、未执行脚本，也未产生 `javascript:` 链接。
  `648px` 视口的页面滚动宽度与视口宽度一致，并已人工检查渲染截图。
- 环境变更：本次未安装、升级或删除任何依赖；正式后端仍为 `0.3.3`，此次只需重新加载未打包扩展。

### 2026-09-26 — 扩展 0.3.3 删除弹窗顶层与断点修正

- 根因复盘：通用 `.modal` 层级为 `100`，而 0.3.1 将删除确认层写成 `70`，因此确认弹窗会被
  历史 Session 窗口遮住；此前的自动化渲染直接手动展示了两个层，却没有断言删除层高于历史层，
  验收不完整。
- 修复：删除确认改为原生 `<dialog>.showModal()`，由浏览器顶层机制保证始终位于历史窗口之上；
  确认与取消按钮使用可收缩的等宽 Flex，禁止任一按钮撑开容器。
- 自适应：用户截图宽度为 `648px`，而 0.3.2 的两行断点为 `620px`，真实窗口刚好绕过断点。
  操作栏现在默认为 `2 × 2`，不再依赖窗口宽度猜测是否换行。
- 针对验收：19 个单元测试、`compileall`、扩展静态校验和 `pip check` 通过。在 Windows Chrome
  Headless 中保持历史窗口开启，再调用删除对话框；`300px` 和用户截图同宽的 `648px` 下，
  `deleteDialog.matches(':modal')=true`、历史窗口仍可见，确认/取消和四个操作入口的边界均在视口内，
  `documentElement.scrollWidth` 等于视口宽度。并人工检查了 `648px` 截图。
- 部署：已在无活动连接时停止 `0.3.2`，重新加载 FunASR 并启动正式 `0.3.3`。`/health`
  报告 `0.3.3` 且本地 Provider 就绪；SQLite 仍为 16 个 Session、130 个片段，`integrity_check=ok`。
- 环境变更：本次未安装、升级或删除任何依赖。

### 2026-09-26 — 扩展 0.3.2 窄宽度容器自适应加固

- 现场现象：用户的实际侧边栏中，云端识别、语言、结束按钮和第四个操作入口在右侧被裁切。
  这说明仅依赖 `460px` 视口断点不足以覆盖 Windows 缩放和侧边栏停靠组合。
- 修复：主配置容器改为单个可收缩网格轨道；所有直接网格子项、操作栏项和面板标题项允许
  `min-width: 0`；Provider 文字在极窄宽度下省略，不再撑开列宽。换行断点提前到 `620px`，
  `420px` 以下的模型、语言和启停控件改为单列。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验和 `pip check` 通过。使用
  Windows Chrome Headless + CDP 实测 `300/380/550/700px` 四档宽度：页面滚动宽度均等于视口宽度，
  所有待操作控件的右边界都位于视口内；`550px` 时设置与操作栏自动换为两行。
- 运行操作：用户明确要求后，向旧服务 PID `824061` 发送 `SIGINT`；端口在 1 秒内停止监听，
  进程在 14 秒内完成 GPU 资源退出。随后通过 `bash scripts/start-server.sh` 启动正式 `0.3.2`，
  FunASR 加载、GPU 预热和 `/health` 检查成功；删除路由对不存在的 Session 返回业务级 404
  `Session 不存在。`，证明新路由已生效。
- 数据核对：重启前 SQLite `integrity_check=ok`，有 16 个 Session、129 个片段；优雅停止期间最后一段
  正常落盘，重启后仍为 16 个 Session、130 个片段，最新 Session 已写入 `ended_at`，完整性仍为 `ok`。
- 环境变更：本次未安装、升级或删除任何依赖。

### 2026-09-26 — 扩展 0.3.1 Session 删除交互修复

- 现场证据：用户截图中删除请求在 `sidepanel.js` 抛出 `Not Found`；当时正式
  `127.0.0.1:8765/health` 仍报告 `0.1.0`，而已加载扩展使用了新版 `DELETE` 接口，因此是前后端
  版本不一致，不是 Session 数据损坏。
- 交互：删除确认从历史长列表底部改为居中的独立确认弹窗，会显示待删 Session 标题；
  无需滚到列表底部，可通过取消按钮、右上角、遮罩或 Escape 退出。
- 错误反馈：删除中和删除失败会在确认弹窗内直接显示；如果是旧服务返回 404，会明确提示
  “结束采集并重启服务”，不再只在开发者控制台出现未处理异常。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验和 `pip check` 通过。在隔离端口
  `8879` 和临时数据目录中实际创建、删除 Session，删除后列表为空。Windows Chrome Headless +
  CDP 实测 `300×560` 和 `520×860`：确认弹窗居中、按钮始终在视口内，页面无横向溢出。
- 运行边界：检查时最新 Session 仍为未结束状态，且浏览器与 `8765` 仍有 WebSocket 连接；
  本次未重启正式服务，也未修改或删除任何现有 Session。

### 2026-09-26 — 扩展 0.3.0 阿里云 Qwen 实时转写适配

- 环境变更：本次未安装、升级或删除任何依赖；继续使用已有 `websockets 15.0.1`。
- 交互：侧边栏增加本地/阿里云切换，可配置北京/新加坡地域、Qwen Audio 3.1/3.0
  Streaming、专业词和页面/最近逐字稿上下文。配置仅对新 Session 生效。
- 协议：实现 DashScope WebSocket `run-task`、二进制 PCM 流、`continue-task` 上下文更新和
  `finish-task`；前端会用新的 partial 候选覆盖旧候选，只将 final 文本追加到 Session。
- 密钥：设置读取接口不返回原值；空白保存会保留旧密钥；远程验证失败不覆盖原配置。
  持久化文件权限为 `0600`，扩展静态校验禁止把密钥写入 Chrome storage 或 JS 源码。
- 验证：19 个 Python 单元测试、`compileall`、扩展静态校验和 `pip check` 全部通过。本地假
  WebSocket 覆盖了授权头、模型、语言、专业词、初始上下文、动态上下文和 partial/final 修订语义。
- 隔离冒烟：用 `FUNASR_PRELOAD=false`、临时数据目录和 `127.0.0.1:8878` 启动 0.3.0；
  `/health` 和 `/api/asr/config` 均成功，未配密钥时连接测试正确返回 400。
  后续加入 Provider 就绪性前置校验：未保存 Key 时 Qwen Session 会在建档前被拒绝，不留空历史。
  正式 `8765` 服务和现有 Session 未被重启或修改。
- 布局验收：使用本机已有 Windows Chrome Headless + CDP 实测 `340×700` 和 `520×860`；
  两组视口的 `documentElement.scrollWidth` 都等于视口宽度，本地/云端切换、模型、语言、启停控件和
  ASR 设置弹窗均未越界。未安装新的浏览器测试依赖。
- 真实阿里云请求仍等用户提供测试 Key 后验收。
- 待验收：真实 Key 下的连接、中英文准确率/修订效果、计费数据和 Windows 已安装扩展的完整点击流程。

### 2026-09-26 — 侧边栏宽高自适应修复

- 原因：真实 Chrome 侧边栏在主窗口变窄或页面缩放后，可用 CSS 视口会小于桌面预览宽度；旧样式
  给 `body` 强制了 `340px` 最小宽度，四列操作栏和表单控件的固有宽度会把右侧内容裁掉。
- 修复：移除根节点强制最小宽度，所有主容器限制在当前视口内；`460px` 以下操作栏自动重排为
  `2 × 2`，`350px` 以下转写引擎、语言和启停按钮改为单列；短窗口会压缩页头、控件和输入区。
  Tooltip、下载菜单和弹窗宽度也限制在当前视口内。
- 自动化渲染：未安装任何新依赖。使用本机已有 Windows Chrome Headless、Codex 自带 Node.js 和
  Chrome DevTools Protocol，经 WSL 临时只读 HTTP 服务加载侧边栏；分别覆盖 `300×560`、
  `340×640`、`380×720`、`460×860`、`520×860`。五组视口的页面滚动宽度均等于视口宽度，
  转写选择器、启停按钮、四个操作入口及上下双框均没有横向越界；另人工查看了 `340×640` 与
  `520×860` 截图。
- 静态防回归：`scripts/validate_extension.py` 会检查窄屏断点存在，并禁止重新加入
  `body { min-width: 340px; }`。
- 边界：上述是实际浏览器渲染检查，但不是以 `chrome-extension://` 安装态完成的人工交互验收；
  仍需用户结束当前采集后重新加载扩展，再在原侧边栏尺寸和缩放比例下确认一次。

### 2026-09-26 — 扩展 0.2.0 双框问答与 Session 管理

- UI：移除总结入口；逐字稿和连续问答改为默认上下双框，支持分别放大、折叠和恢复双框；逐字稿
  改为连续段落显示，不再把每个短 ASR 片段渲染成独立行。
- Session：增加重命名和二次确认删除接口；重命名不移动数据目录，删除先把唯一 Session 目录移动
  到项目内临时回收路径，数据库事务成功后才清理，避免误删其他 Session。
- 问答：同一 Session 保存完整连续对话；每次请求必须显式携带 `include_transcript`；未勾选时不
  发送逐字稿。若模型明确报告上下文长度超限，只保留最近 50% 逐字稿重试一次，对话历史不裁剪，
  第二次失败则直接展示错误。
- 配置：增加全局对话模型 Provider、Domain/Base URL、API Key、Model 设置与连接测试；读取接口
  永不返回密钥，配置只写入权限为 `0600` 的 `data/llm_config.json`，保存前远端验证失败不会覆盖
  上一次配置。
- 数据迁移：现有 `messages` 表只增加逐条上下文授权和范围字段，不删除或重写已有逐字稿与问答。
- 验证：14 个 Python 单元测试、compileall、扩展静态校验和 pip check 通过；在隔离端口 `8877`
  与临时数据库完成健康检查、Session 创建/重命名/列表/删除/404 及 CORS `PATCH` 冒烟测试；侧边栏
  在 Playwright `380×860` 视口渲染后横向滚动宽度等于视口宽度。
- 迁移验证：使用 SQLite 在线备份复制当前正式库，在副本上完成 schema 迁移；迁移前后均为 12 个
  Session、41 个逐字稿片段、0 条问答，`include_transcript` 和 `transcript_scope` 字段添加成功，
  未修改正式库。
- 未接入：尝试使用当前 `paraformer-zh-streaming` 对完整音频窗口进行第二遍重解码，超过 60 秒仍
  未返回，已仅终止该测试进程。该路径不满足实时修订延迟要求，因此 0.2.0 不伪装为“可回改”；
  后续需引入独立的快速离线校正模型或云端支持 revision 的 ASR 协议后再实现。
- 未验证：真实外部模型连接与问答，因为未配置用户 API Key；Windows 已加载扩展的点击流程仍需
  用户重新加载 `0.2.0` 后验收。

### 2026-09-26 — 扩展 0.1.3 Session 逐字稿恢复修复

- 复现：恢复正在进行的 Session 后，逐字稿仍显示时间戳，但正文为空。
- 数据核验：SQLite `integrity_check` 为 `ok`；当前 Session 有 33 个片段、218 个字符，数据并未
  丢失。
- 根因：实时 WebSocket 片段使用 `text` 字段，而从 SQLite 恢复的片段使用 `final_text`；前端只
  读取 `text`，造成“假丢失”。
- 修复：服务端恢复接口统一补充 `text`；前端兼容 `text`、`final_text`、`raw_text`，缺字段时显示
  明确占位，不再生成只有时间戳的空行。
- 防回归：单元测试验证恢复片段同时包含 `text` 与 `final_text`；扩展静态校验验证兼容读取逻辑；
  `AGENTS.md` 增加实时/恢复字段契约和先核验存储再判断数据丢失的约束。
- 待用户侧：在 `chrome://extensions` 重新加载 `0.1.3` 后，确认当前 33 段逐字稿正文恢复显示。

### 2026-09-25 — 扩展 0.1.2 与本地模型启动保护

- 复现：浏览器停在“正在创建 Session 并申请当前标签页音频流”；SQLite 中出现两条无逐字稿的
  重复 Session，同时旧服务在 FunASR 加载/推理期间无法及时响应健康检查。
- 修复：本地 FunASR 改为服务启动阶段加载并预热；创建 Session 请求增加 5 秒超时；扩展增加
  30 秒防重复启动锁，并自动清理遗留锁。
- 恢复：旧服务对 `SIGINT`/`SIGTERM` 未退出，因此在确认监听端口已关闭后仅强制终止对应 PID；
  SQLite `integrity_check` 返回 `ok`，已有 11 条 Session 均保留，未删除用户数据。
- 完成：新服务成功完成本地模型加载和 GPU 预热后再监听 `127.0.0.1:8765`；扩展版本升级到
  `0.1.2`。
- 完成：扩展静态校验、8 个 Python 单测、compileall 和 pip check 通过。
- 待用户侧：在 `chrome://extensions` 重新加载扩展后，回到普通音视频网页单击工具栏图标验收。

### 2026-09-25 — 扩展 0.1.1 标签页授权修复

- 复现：侧边栏按钮调用后台 `tabCapture.getMediaStreamId()` 时，Chrome 返回
  `Extension has not been invoked for the current page`。
- 根因：Chrome 的标签页采集授权绑定浏览器工具栏 action 调用；侧边栏按钮本身不会得到这项
  per-tab 授权。
- 修复：浏览器工具栏图标的 `chrome.action.onClicked` 现在负责打开侧边栏、创建 Session、
  获取 stream ID 并自动开始采集；侧边栏不再直接申请标签页采音。
- 完成：扩展版本升级到 `0.1.1`；扩展静态校验、7 个 Python 单测、compileall 和 pip check 通过。
- 待用户侧：在 `chrome://extensions` 重新加载扩展后，使用 Windows Chrome 实际点击工具栏图标
  验证。当前自动化浏览器连接仍被 WSL 工作目录 URI 限制，未将静态验证写成浏览器实测。

### 2026-09-25 — 初始环境

- 已完成：本机/WSL/GPU/内存/磁盘检查。
- 已完成：创建 `.venv` 并安装核心服务依赖。
- 已完成：安装 CUDA 13.0 PyTorch、torchaudio、FunASR、ModelScope 和 NumPy。
- 已完成：PyTorch GPU 张量实测与 Python 包导入验证。
- 已完成：核心单测、扩展静态校验、服务及 REST API 冒烟测试。
- 已完成：初始化项目 Git 仓库；`.env`、`.venv`、`data` 均已确认被忽略。
- 已完成：本地 ASR 模型、GPU 预热和 WebSocket 音频整链路的真实样例实测。
- 待用户侧：Windows 浏览器真实采集，以及配置密钥后的 Qwen 云端验收。
- 清理：验收生成的临时 Session 数据已移出项目，首次正式启动会创建干净的 `data/`。
