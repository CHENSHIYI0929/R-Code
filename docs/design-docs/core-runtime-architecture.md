# Core Runtime Architecture

本文描述 `core/` 的架构边界。`core/` 是 R-Code agent runtime 的编排层，只表达生命周期、状态和 transition，不承载具体工具、provider、安全策略、prompt 文本、上下文治理策略或 UI 行为。

## 文件职责

| 文件 | 职责 |
|:---|:---|
| `core/loop.py` | 薄主循环 `AgentLoop`：上下文重建 → 模型流式调用 → 工具执行 → finish gate → transition/completed |
| `core/context_engine.py` | 每轮模型调用前重建 `ContextSnapshot` 的边界层及三个可注入协议 |
| `core/runtime_state.py` | 单会话可变状态（usage、轮次、恢复标志、session id、metadata） |
| `core/transitions.py` | provider-neutral 的 `TransitionReason` 枚举 |
| `core/stream_events.py` | loop 对外输出的 `AgentEvent` 类型 |

## 接口设计

### AgentLoop

```python
async def stream(prompt, *, attachments=None) -> AsyncIterator[AgentEvent]
async def continue_stream() -> AsyncIterator[AgentEvent]
```

- `stream` 是普通用户交互入口：触发 `UserPromptSubmit` hook，追加 user message 与调用方预构建的 durable attachment，再进入 `_run_loop_async()`。
- `continue_stream` 用于子 agent / 恢复场景，从已 seed 到 `MessageStore` 的消息链继续，不重复追加用户 prompt。

构造依赖（除前 5 个外均可选）：`state`、`message_store`、`context_engine`、`model_client`、`tool_executor`、`trace_recorder`、`current_model_context`、`hooks`、`compaction_service`（`ReactiveCompactor`）、`session_memory_extractor`、`session_memory_updater`、`model_retry_runner`、`error_log_recorder`。

附件解析、文件读取、权限检查和投影不属于主循环：CLI 在调用前收集附件，`ContextEngine` 的 preparer 在模型调用前把 attachment role 投影成 provider-visible messages。

### ContextEngine

```python
async def build_for_model(state) -> ContextSnapshot
```

三个可注入协议：

- `ContextPreparer.prepare(messages, state)`：返回消息 iterable 或 `PreparedContext`，可同步或异步。是 compaction/记忆/附件的接入点。
- `PromptAssembler.assemble(state) -> str`。
- `ToolSchemaProvider.tool_schemas(state) -> Iterable[dict]`。

默认实现 `NoOpContextPreparer` / `StaticPromptAssembler` / `EmptyToolSchemaProvider` 用于测试与 subagent fork。CLI 装配会注入 attachment→memory→compaction 的 preparer 链、`DynamicPromptAssembler` 和 `ToolRegistry`。

### RuntimeState

稳定字段：`usage`、`turn_count`、`max_turns`（默认 20）、`has_attempted_reactive_compact`、`has_escalated_max_output_tokens`、`max_output_recovery_count`、`last_transition`、`session_id`、`metadata`。

方法：`add_usage(usage)`、`set_transition(transition)`、`start_new_session() -> str`（重置消息相关状态、usage、transition、metadata，但保留 `max_turns`）。

metadata 当前承载：`files_read`、`files_changed`、`disabled_tools`/`denied_tools`/`hidden_tools`、`read_only_agent`、`is_fork_child`、`memory_extraction_agent`/`allowed_memory_path`、`long_term_memory_extraction_agent`/`allowed_memory_dir`、`model_request_overrides`、`task_list_id`/`parent_task_list_id`、`mcp_server_instructions`、`workspace` 等。

### AgentEvent

`type` 取值：`interaction_started`、`assistant_delta`、`assistant_message_completed`、`tool_call_ready`、`tool_started`、`tool_progress`、`tool_result`、`transition`、`completed`、`error`。字段含 `text`、`result`、`transition`、`metadata`。当前 loop 不主动 yield `error`，未捕获异常向上抛出并由 CLI 记录到 error log。

## 核心数据流

```mermaid
sequenceDiagram
  participant Caller as CLI / SubagentRunner
  participant Loop as AgentLoop
  participant Engine as ContextEngine
  participant Retry as ModelRetryRunner
  participant Model as ModelClient
  participant Exec as ToolExecutor
  participant Store as MessageStore

  Caller->>Loop: stream(prompt, attachments)
  Loop->>Store: append_user + append_attachments
  loop 每轮
    Loop->>Loop: turn_count += 1 (超限→max_turns→return)
    Loop->>Engine: build_for_model(state)
    Engine-->>Loop: ContextSnapshot
    Loop->>Retry: stream(λ model.stream(snapshot))
    Retry->>Model: stream(snapshot)
    Model-->>Retry: ModelStreamEvent*
    Retry-->>Loop: 缓冲后的事件 (失败attempt丢弃)
    alt context_limit_exceeded 且首次
      Loop->>Loop: reactive compact → reactive_compact_retry → continue
    else output_interrupted
      Loop->>Loop: escalate / recovery → continue
    end
    Loop->>Store: append_assistant
    Loop->>Loop: AssistantMessageCompleted hook (session memory)
    alt 有实际 tool_calls
      Loop->>Exec: execute(tool_calls)
      Exec-->>Loop: ToolExecutionResult*
      Loop->>Store: append_tool_results (+followup)
      Loop->>Loop: set tool_use → continue
    else 无 tool_calls
      Loop->>Gate: FinishGate.evaluate（仅文件修改后验证）
      alt verification failed
        Gate-->>Loop: repair_feedback attachment
        Loop->>Store: append_attachments
        Loop->>Loop: verification_failed_retry → continue
      else verification passed / gate absent
        Loop->>Loop: TurnStopped hook → completed_verified/completed → return
      end
    end
  end
```

## 关键机制

### 续轮判定

主循环判断是否继续时只看 `message_completed.metadata["tool_calls"]` 中是否存在实际工具调用，不依赖 provider 私有 `stop_reason`。

### Transition

`TransitionReason`（StrEnum）：`tool_use`、`completed`、`completed_verified`、`verification_failed_retry`、`verification_blocked`、`repair_exhausted`、`max_turns`、`rate_limit_retry`、`reactive_compact_retry`、`max_output_tokens_escalate`、`max_output_tokens_recovery`、`stop_hook_continue`。

| Transition | 触发条件 | loop 行为 |
|:---|:---|:---|
| `max_turns` | `turn_count > max_turns` | 设置 transition 后 return |
| `rate_limit_retry` | `ModelRetryRunner` 重试前回调 | 重试同一轮 |
| `reactive_compact_retry` | `context_limit_exceeded` 且首次 | 触发 compact 后 `continue`，不 append assistant |
| `max_output_tokens_escalate` | 首次 `output_interrupted` | 设 `max_output_tokens=64000`，`continue`，不 append assistant |
| `max_output_tokens_recovery` | 再次 interrupted 且 recovery < 3 | append 截断 assistant + continuation prompt，`continue` |
| `tool_use` | 有实际 tool calls | append 结果后 `continue` |
| `completed` | 无 finish gate 的无 tool calls 自然结束 | return final text |
| `completed_verified` | 修改后的候选结束通过 `FinishGate` 验证 | return final text，并在 metadata 标记验证通过 |
| `verification_failed_retry` | 验证失败且未超过 repair budget | append durable `repair_feedback` 后 `continue` |
| `verification_blocked` | 修改后没有可运行的验证命令，或 verification outcome 是命令缺失、环境阻塞、timeout、permission denied | 停止，不把结果称作已验证 |
| `repair_exhausted` | 验证失败重复或 repair attempt 耗尽 | 停止并保留最后一次验证 artifact |

`stop_hook_continue` 已在枚举中定义，loop 当前未消费，是目标恢复能力。

### Verification-gated finish

`FinishGate` 是 `core/loop.py` 内的 provider-neutral protocol。它返回 `FinishDecision` 风格的 outcome：`pass`、`continue`、`blocked` 或 `exhausted`。core 只消费 outcome、可选 attachment 和人类可读 message；它不理解 pytest、shell 命令、traceback 或检索实现。CLI 注入 `services.repair.RepairLoopGate`：该服务仅在 `RuntimeState.metadata["files_changed"]` 非空时运行验证。失败输出经共享 `ToolResultStorage` 写入 session artifact，以 `FailureParser` 和 `RepositoryRetriever` 生成 bounded repair context；重复相同失败或达到最大 attempt 会停止，避免无限修复循环。

### 错误恢复分层

- HTTP/transport 把 429/5xx/网络错误标记为 `ProviderError(retryable=...)`。
- `ModelRetryRunner` 对 `retryable` 且非 `context_limit_exceeded` 的错误做指数退避，映射为 `rate_limit_retry`；耗尽后抛 `RetryExhaustedError`。
- `AgentLoop` 处理 `context_limit_exceeded`（reactive compact）和 `output_interrupted`（escalate / recovery）。
- 不可恢复错误经 `error_log_recorder` 记录后向上抛出。

详见 `model-provider-architecture.md`。

### Session memory 钩子

assistant 消息写入后，loop 触发 `AssistantMessageCompleted` hook 并优先调用 `session_memory_extractor`；仅在无 extractor 且本轮无 tool calls 时调用 `session_memory_updater`。详见 `compaction-architecture.md`。

## Core 不负责的内容

具体工具逻辑与工具名分支、provider wire protocol / HTTP / API key / 模型 catalog、路径规范化与 sandbox 分类、权限 UI、system prompt section 文本、上下文压缩与记忆策略、transcript / trace 文件格式、CLI slash command 与渲染。这些分别属于 `tools/`、`infrastructure/`、`services/guard`、`services/permissions`、`prompts/`、`services/context|compaction|memory|attachments`、`services/observability` 和 `ui/cli`。
