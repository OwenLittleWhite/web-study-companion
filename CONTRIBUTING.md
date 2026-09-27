# 开发与贡献

感谢参与 Study Companion。提交变更前，请先确认它仍然遵守“当前标签页主动授权、本机保存密钥、
最终稿即时持久化”的边界。

## 本地开发

```bash
bash scripts/bootstrap.sh
bash scripts/start-server.sh
```

扩展无需构建，直接在 Chrome/Edge 开发者模式中加载 `extension/`。修改扩展文件后在扩展管理页
点击“重新加载”；修改后端文件后重启服务。

## 必跑检查

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q server tests scripts
.venv/bin/python scripts/validate_extension.py
.venv/bin/python -m pip check
```

涉及 ASR 或 WebSocket 链路时，在具备本地模型的环境中追加：

```bash
.venv/bin/python scripts/verify_local_asr.py
.venv/bin/python scripts/verify_ws_pipeline.py
```

手工浏览器检查至少覆盖：手动授权但不自动开始、新建 Session、历史 Session 续采、暂停/继续、
逐字稿自动滚动、逐字稿/问答切换、Markdown 回答、重命名、删除和五种导出格式。

## 安全要求

- 不提交 `.env`、`data/`、模型缓存、真实音视频或任何 API Key；
- 不把密钥移到前端或浏览器存储；
- 不把后端默认监听地址改成公网地址；
- 不在未经说明的情况下扩大扩展网页权限；
- 对来自网页、ASR 或模型的字符串按不可信输入处理。

提交前检查：

```bash
git status --short --ignored
git diff --check
git grep -n -I -E 'sk-[A-Za-z0-9_-]{16,}|Bearer[[:space:]]+[A-Za-z0-9._-]{16,}'
```

最后一条命令没有输出才是期望结果；它只能发现常见模式，不能代替人工检查。

## 文档同步

修改接口、环境变量、权限、数据格式或用户操作流程时，同一提交中更新相应文档：

- 安装/运行：`docs/INSTALLATION.md`
- 扩展行为：`docs/FRONTEND.md`
- API/存储：`docs/BACKEND.md`
- 配置：`docs/CONFIGURATION.md`
- 常见失败：`docs/TROUBLESHOOTING.md`
- 特定机器的真实安装记录：`docs/ENVIRONMENT.md`

`docs/ENVIRONMENT.md` 是可复现审计记录。新增记录应写明日期、操作系统、命令、结果和未验证边界，
不要把“计划执行”写成“已经通过”。
