# 配置说明

配置分为三类：后端环境变量、侧边栏中的云端 ASR 配置、侧边栏中的对话模型配置。

## 后端环境变量

后端启动时读取仓库根目录 `.env`。已有系统环境变量优先于 `.env` 中的同名值。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `COMPANION_HOST` | `127.0.0.1` | HTTP/WebSocket 监听地址；个人使用建议保持回环地址 |
| `COMPANION_PORT` | `8765` | 服务端口；修改后还需同步修改扩展代码和权限 |
| `COMPANION_DATA_DIR` | `./data` | SQLite、Session 和本机配置目录；相对路径基于仓库根目录 |
| `FUNASR_MODEL` | `paraformer-zh-streaming` | 本地 FunASR 模型名称或可解析路径 |
| `FUNASR_DEVICE` | `cuda:0` | FunASR 设备；CPU 可尝试 `cpu` |
| `FUNASR_PRELOAD` | `false` | 直接运行 Python 服务时是否加载并预热本地模型 |
| `DASHSCOPE_API_KEY` | 空 | Qwen ASR 和 Qwen 对话的首次默认 Key |
| `QWEN_ASR_WS_URL` | 北京地域 WebSocket 地址 | 未保存侧边栏 ASR 配置时的默认端点 |
| `QWEN_ASR_MODEL` | `qwen-audio-3.1-asr-flash-streaming` | 未保存配置时的默认流式 ASR 模型 |
| `QWEN_LLM_BASE_URL` | DashScope 兼容接口 | 未保存问答配置时的默认 Base URL |
| `QWEN_LLM_MODEL` | `qwen-plus` | 未保存问答配置时的默认模型 |

布尔值支持 `1/true/yes/on`（不区分大小写）表示真，其他值按假处理。

示例：仅使用云端服务，不加载本地模型。

```dotenv
DASHSCOPE_API_KEY=
QWEN_ASR_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference
QWEN_ASR_MODEL=qwen-audio-3.1-asr-flash-streaming
QWEN_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_LLM_MODEL=qwen-plus
COMPANION_HOST=127.0.0.1
COMPANION_PORT=8765
COMPANION_DATA_DIR=./data
FUNASR_MODEL=paraformer-zh-streaming
FUNASR_DEVICE=cuda:0
FUNASR_PRELOAD=false
```

两个启动脚本会覆盖 `.env` 中的该字段：`start-server.sh` 强制为 `false`，
`start-server-local-asr.sh` 强制为 `true`。这样脚本名称和实际资源占用始终一致。

## 本地 ASR

侧边栏选择“本地识别”后，Session 使用 `local-funasr` Provider。语言可选自动、中文或英文；
当前本地 Provider 使用流式 Paraformer，按 600 ms 音频块处理。

本地模式不会把音频发送到云端，但模型下载阶段可能访问模型仓库。原始音频默认不写入磁盘。

## 阿里云 Qwen ASR

侧边栏配置项：

- 地域：北京 `cn-beijing` 或新加坡 `ap-southeast-1`；
- 模型：`qwen-audio-3.1-asr-flash-streaming` 或
  `qwen-audio-3.0-asr-flash-streaming`；
- DashScope API Key；
- 专业词：最多 400 个字符；
- 是否携带页面标题和最近逐字稿作为识别上下文。

保存前会建立一次实时 ASR 连接验证。保存位置是 `data/asr_config.json`。后续读取配置时只返回
掩码，不返回 Key。

云端识别使用服务商返回的临时稿和最终稿：临时稿可被后续结果修订，只有 `sentence_end` 标记的
最终句进入 Session。识别上下文在每个最终句后用最近内容刷新，用于改善后续专有名词一致性；
它不能保证纠正已经归档的最终句。

## 对话模型

后端调用 OpenAI 兼容的 `/chat/completions` 接口。侧边栏配置项：

- 服务类型：`qwen`、`volcengine` 或 `custom`；
- Domain / Base URL：填写到版本层级，不要包含 `/chat/completions`；
- Model：服务商提供的模型标识；
- API Key。

保存前会发起一个最多 8 个输出 token 的连接测试。保存位置是 `data/llm_config.json`。

示例 Qwen 配置：

```text
Provider: qwen
Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
Model: qwen-plus
```

如果 ASR 和问答都使用同一个 DashScope 账号，可以使用同一个 Key；项目仍把 ASR 和问答配置
分别保存，便于以后单独更换。火山和自定义 Provider 只用于对话模型；当前 ASR Provider 没有
实现火山语音识别。

## 逐字稿上下文

每次发送问题前都可以独立勾选“携带逐字稿”：

- 勾选：发送当前 Session 的相关逐字稿、历史问答和本次问题；
- 不勾选：只发送历史问答和本次问题，系统提示模型不得声称看过原文；
- Session 尚无逐字稿时，勾选发送会被拒绝并提示取消勾选。

长逐字稿会先通过轻量检索选择相关段落和最近段落。若服务商仍明确返回上下文长度超限，后端
自动改用最近一半逐字稿重试一次，并把 `transcript_scope` 标记为 `recent_half`。其他错误不会
伪装成上下文超限，也不会无限重试。

## 密钥与文件安全

- `.env`、`data/asr_config.json`、`data/llm_config.json` 均被 Git 忽略；
- 配置 JSON 尽可能设置为当前用户可读写的 `0600`；
- 不要把 Key 写进 `extension/`、截图、Issue、日志或导出文件；
- 公开仓库前可运行 `git status --ignored` 和密钥扫描确认忽略规则；
- 如果曾经把真实 Key 提交到 Git，删除文件并不等于撤销泄漏，应立即到服务商后台轮换 Key。
