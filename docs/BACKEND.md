# 后端服务说明

后端是只监听本机回环地址的 FastAPI 服务，负责转写适配、Session 生命周期、问答配置、持久化
和导出。入口为 `server/run.py`。

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `server/run.py` | 读取配置并启动 Uvicorn |
| `server/app/main.py` | HTTP/WebSocket 路由、服务生命周期和采集协调 |
| `server/app/config.py` | `.env` 和环境变量解析 |
| `server/app/store.py` | SQLite、Session 文件、时间轴恢复与导出 |
| `server/app/providers/` | 本地 FunASR 和 Qwen Streaming ASR 适配器 |
| `server/app/asr_config.py` | 云端 ASR 配置验证和本地持久化 |
| `server/app/llm.py` | 连续问答、逐字稿上下文和超限降级 |
| `server/app/llm_config.py` | OpenAI 兼容对话配置验证和本地持久化 |
| `server/app/retrieval.py` | 逐字稿上下文组装 |
| `server/app/models.py` | HTTP 请求模型和字段限制 |

## 启动

```bash
bash scripts/start-server.sh
```

这是轻量入口：脚本显式禁用启动时的本地模型预加载，进入 `server/` 后使用仓库自己的
`.venv/bin/python` 启动。默认监听 `127.0.0.1:8765`，不会暴露到局域网。

需要本地模型时运行：

```bash
bash scripts/start-server-local-asr.sh
```

本地入口显式启用预加载；已安装 FunASR 时，应用会在接受请求前加载并预热模型。这能减少第一段
音频的冷启动等待，但会增加服务启动时间和内存/GPU 占用。

## HTTP API

交互式 OpenAPI 文档在服务启动后可访问：

```text
http://127.0.0.1:8765/docs
```

主要接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务版本和 ASR Provider 就绪状态 |
| `POST` | `/api/sessions` | 创建 Session |
| `GET` | `/api/sessions` | 列出最近 Session |
| `GET` | `/api/sessions/{id}` | 读取 Session、逐字稿和问答 |
| `PATCH` | `/api/sessions/{id}` | 重命名 Session |
| `DELETE` | `/api/sessions/{id}` | 删除非采集中的 Session |
| `POST` | `/api/sessions/{id}/chat` | 在当前 Session 中连续问答 |
| `GET/PUT` | `/api/asr/config` | 读取公开字段或验证并保存 ASR 配置 |
| `POST` | `/api/asr/config/test` | 只测试 ASR 配置，不保存 |
| `GET/PUT` | `/api/llm/config` | 读取公开字段或验证并保存问答配置 |
| `POST` | `/api/llm/config/test` | 只测试问答配置，不保存 |
| `GET` | `/api/sessions/{id}/export?format=md` | 导出 `md/txt/json/srt/vtt` |

配置读取接口只返回 `has_api_key` 和掩码，不返回真实 Key。保存接口会先连接服务商验证，验证失败
时不替换原配置。

## WebSocket 转写协议

连接：

```text
ws://127.0.0.1:8765/ws/transcribe
```

第一个文本消息必须是 `start`：

```json
{
  "type": "start",
  "session_id": "existing-session-id",
  "provider": "local-funasr",
  "language": "auto",
  "page": {
    "title": "Page title"
  }
}
```

随后客户端发送 16 kHz、16-bit、小端、单声道 PCM 二进制帧。停止时发送：

```json
{"type": "stop"}
```

服务端事件包括 `provider.loading`、`provider.warming`、`provider.ready`、
`transcript.partial`、`transcript.final` 和 `capture.error`。最终稿在发送给浏览器前已经写入
存储；临时稿仅用于 UI 原位更新。

## 持久化策略

SQLite 是索引和查询的主要存储；每个 Session 同时维护独立可读文件，方便审计和恢复：

- `session.json`：Session 元数据；
- `transcript.raw.jsonl`：只追加的原始最终片段；
- `transcript.final.md`：整理后的逐字稿；
- `conversation.json`：连续问答。

数据模型仍保留旧版总结字段以兼容已有数据库，但当前 UI 不生成总结，也不要求每个 Session 存在
`summary.md`。

每个最终片段到达时立即写入，不需要等待“结束采集”。继续采集时，后端从现有有效时间轴末尾
计算偏移，新片段接在旧片段之后。读取和导出旧版本 Session 时会修复历史时间回跳的展示时间轴，
但不会改写 `transcript.raw.jsonl` 中的原始时间字段。

## 并发与状态

后端维护当前进程内正在采集的 Session id，用于阻止采集中重命名或删除。真正的 Session 内容
持久化在 `data/`，服务重启后仍存在；“是否正在采集”属于实时连接状态，不应跨服务重启恢复。

当前实现适合单机个人使用，不是多用户鉴权服务。不要把监听地址改成 `0.0.0.0` 后直接暴露到
公网；代码没有账号体系、访问令牌或租户隔离。
