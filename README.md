# R-Code

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python&logoColor=white) ![License](https://img.shields.io/badge/License-MIT-green.svg)

R-Code 是一个 Python code-agent runtime。它用薄主循环编排模型、工具、安全边界、上下文治理与恢复流程；具体能力通过 registry、hook 和 context preparer 接入，而不是堆进主循环。

## 能力概览

- 动态上下文：消息链、附件、工具结果预算、compaction 与分层 memory。
- 可控工具执行：descriptor、guard、deny-first permission、hook 和结果持久化。
- 会话恢复：JSONL transcript、trace、error log 与后台任务 artifacts。
- 验证闭环：文件修改后先验证，失败证据进入下一轮 repair context。
- 扩展集成：subagent、skill、MCP、task 与 background task。

### Memory

- Instruction memory：分层 `ONECODE.md` / rules，作为 system prompt 规则。
- Long-term memory：`.onecode/memory/` 的跨会话 topic；检索和注入前须通过 `is_injectable()`，stale topic 不注入。
- Session memory：`.onecode/sessions/<id>/session-memory.json` 是唯一事实源；`session-memory.md` 仅为渲染产物。工具事实、用户确认与 LLM extraction 经 `merge_state()` 合并，优先级为 user > tool > llm_extraction > speculation；stale 内容保留审计但不进入上下文。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --dev
cp .env.example .env
uv run python -m ui.cli.app
```

模型配置从 `.env` 读取；也可先启动 CLI 后用 `/connect` 配置。批处理示例：

```bash
echo "列出当前目录的文件" | uv run python -m ui.cli.app
```

## 开发

开始前阅读 [AGENTS.md](AGENTS.md)，再阅读 [architecture.md](architecture.md)、相关 `docs/design-docs/` 与活跃 ExecPlan。复杂改动应遵循 [PLANS.md](PLANS.md)。

```bash
uv run python -m pytest tests -q
uv run python -m pytest tests/test_import_boundaries.py -q
uv run python -m compileall core services infrastructure
```

## 文档

- [架构总览](architecture.md)
- [运行时与恢复](docs/design-docs/core-runtime-architecture.md)
- [上下文与 session memory](docs/design-docs/compaction-architecture.md)
- [长期、指令记忆](docs/design-docs/memory-architecture.md)
- [工具运行时](docs/design-docs/tool-runtime-architecture.md)
- [权限与沙箱](docs/design-docs/permission-architecture.md)
- [设计原则](docs/design-docs/core-beliefs.md)
- [ExecPlans](docs/exec-plans/active/)

## License

MIT
