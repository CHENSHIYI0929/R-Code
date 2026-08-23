# R-Code Agent 项目紧急提升计划

## 目标定位

当前 R-Code 已经达到 Agent Runtime / Agent Infra 实习项目中上水平。

下一阶段重点不是继续堆功能，而是将：

> "实现了很多 Agent 模块"

提升为：

> "针对 Coding Agent 的关键问题提出机制改进，并通过实验验证有效"。

核心目标：

1.  补齐生产级可靠性问题；
2.  强化 Repair Loop 差异化；
3.  增加可量化 Evaluation；
4.  补足 JD 中 Agent Infra 常见能力。

------------------------------------------------------------------------

# Priority 0：必须优先完成（影响面试质量最大）

## P0 最小侵入实施决策（2026-08-23）

原计划严格标记为 P0 的只有 Benchmark；但它依赖验证结果可信、失败原因可
区分。因此实施时将 P0 收敛为三项，并按下面顺序交付。这样不改变
`core/loop.py` 的通用 `FinishGate` 边界，也不把 verification 伪装成模型可调用
tool。

1. **VerificationExecutor 与超时清理**：新增 `services/verification/`。它将旧的
   `.onecode/settings.json` 中 `verification.commands: [string]` 解析成 argv，拒绝
   shell 管道、重定向和命令替换，限定 cwd 为 workspace，并以独立进程组运行、
   超时后 terminate/kill/wait。`RepairLoopGate` 仅调用该接口、持久化报告和决定
   是否继续。对象形式 `{"argv": ["python", "-m", "pytest", "-q"]}` 为推荐新
   格式；旧字符串格式继续支持，所以现有项目不需要迁移。
2. **失败分类与稳定指纹**：保留既有粗粒度 `VerificationReport.status`
   (`passed`/`failed`/`blocked`) 以保持 UI、trace 和测试兼容；新增细粒度
   `outcome`（`passed`、`test_failed`、`command_missing`、`environment_blocked`、
   `timeout`、`permission_denied`）。只有 `test_failed` 才进入 parser/retriever 和
   再修；其他 outcome 终止为 blocked。指纹改由测试节点、异常类型、文件、行号和
   归一化消息组成，不能再直接 hash 全量 stdout。
3. **Repair Loop Benchmark 基座**：在 `benchmarks/repair_loop/` 建立版本化任务
   manifest、四种机制 profile（baseline、verification-only、parser、full）、JSONL
   run record 和汇总器。运行时通过 `RepairLoopPolicy` 注入 profile，不复制主循环。
   首版 runner 接受一个异步 case runner，允许真实 provider、回放模型或 CI harness
   共用相同的指标定义；任务工作区复制和 provider 驱动保持在 benchmark adapter，
   不进入 production runtime。

调用链为：

    AgentLoop -> FinishGate(RepairLoopGate) -> VerificationExecutor
       -> VerificationReport(outcome, artifact) -> FailureParser
       -> stable fingerprint -> RepositoryRetriever -> repair_feedback attachment
       -> AgentLoop 下一轮

核心兼容性风险及处理：旧字符串命令若依赖 `&&`、`|`、重定向等 shell 语法会被安全
拒绝并显示 `environment_blocked`，需要改为 argv 对象；这是显式的安全收紧，不会静默
改变命令语义。`status` 字段不改名；新消费者读取 `outcome`，旧消费者继续读取
`status`。Benchmark 不默认启用，也不会改变正常 CLI 的模型、工具或 MCP 装配。

建议测试覆盖：argv 与旧字符串兼容、shell 元字符拒绝、命令缺失、环境阻塞、超时后
进程组清理、同一失败在临时路径/时间戳变化下指纹不变、不同异常指纹不同、非测试
失败不会触发 retry，以及四个 benchmark profile 的指标汇总。

## 1. 建立 Repair Loop Benchmark（最高优先级）

### 当前问题

目前已有：

-   Verification Gate
-   Failure Parser
-   Retrieval
-   Repair Feedback

但是主要证明：

-   模块运行正确；
-   状态机正确。

缺少：

> Agent 是否真的因为这些机制变好了。

### 实施方案

设计固定任务集：

Baseline:

    原始 R-Code

实验：

    + Verification Gate

    + Failure Parser

    + Failure-aware Retrieval

指标：

    success rate
    resolved rate
    turns
    tool calls
    tokens
    latency
    verification attempts
    same failure repeats

建议任务类型：

-   Python Bug Fix
-   pytest failure repair
-   missing implementation
-   regression repair

### 目标

形成：

    问题
    ↓
    机制
    ↓
    实验
    ↓
    指标
    ↓
    分析

完整项目闭环。

------------------------------------------------------------------------

# Priority 1：修复 Repair Loop 架构问题

## 2. 抽象 VerificationExecutor

### 当前问题

普通代码执行：

    ToolExecutor
    → Guard
    → Permission
    → Hook
    → Handler

但 Verification 当前直接 subprocess。

风险：

-   两套执行入口；
-   安全策略不统一；
-   难以追踪。

### 修改方向

增加：

    services/verification/
        verification_executor.py

统一负责：

-   command validation
-   workspace boundary
-   timeout
-   process cleanup
-   result storage
-   trace

目标：

让 Verification 成为 Harness 内的一等能力。

------------------------------------------------------------------------

## 3. 完善 Verification Failure 分类

### 当前问题

Shell 返回：

    127

可能被误认为普通测试失败。

### 修改为：

    passed

    test_failed

    command_missing

    environment_blocked

    timeout

    permission_denied

意义：

避免 Agent 修改业务代码解决环境问题。

------------------------------------------------------------------------

## 4. 修复 Timeout 进程残留

### 当前问题

timeout 后：

-   subprocess 可能继续运行；
-   pytest 子进程可能残留。

### 修改：

timeout:

    terminate process group
    ↓
    kill if needed
    ↓
    await cleanup

记录：

    verification_timeout

------------------------------------------------------------------------

# Priority 2：提升 Failure-aware Repair 的技术含量

## 5. Stable Failure Fingerprint

### 当前问题

目前如果直接 hash raw output：

容易受到：

-   时间戳
-   临时路径
-   随机日志

影响。

### 修改：

建立：

    FailureEvidence
    ↓
    normalize
    ↓
    fingerprint

输入：

    test node id
    exception type
    file path
    line
    normalized message

输出：

    stable failure id

用于：

-   防止死循环；
-   判断是否真正进展。

------------------------------------------------------------------------

## 6. 打通 Symbol Retrieval

### 当前问题

已有：

    FailureEvidence.symbol
    RepositoryRetriever.symbol search

但是 Parser 没有真正产生 symbol。

### 修改：

从：

-   traceback frame
-   pytest location
-   AST definition

提取：

    class
    function
    method

形成：

    failed test
    ↓
    symbol
    ↓
    definition/reference
    ↓
    repair context

这会明显增强 Repo-level Coding Agent 属性。

------------------------------------------------------------------------

## 7. Retrieval 增加真正预算控制

### 当前：

主要：

    max snippets

不足。

### 增加：

    global token budget

    per-file budget

    snippet ranking

    deduplication

    retrieval reason

最终输出：

    Repair Attachment

    - failure evidence
    - relevant files
    - snippets
    - why selected

------------------------------------------------------------------------

# Priority 3：提升 Agent Infra 完整度

## 8. Workspace Verification State

### 当前问题

files_changed 是 session 级状态。

可能：

-   重复验证；
-   漏验证。

### 修改：

增加：

    workspace_revision

    verified_revision

    dirty_since_last_verified

逻辑：

    workspace changed
            |
            v
    verification required
            |
            v
    verified_revision update

------------------------------------------------------------------------

## 9. Progress Model

### 当前：

主要依赖：

    max_attempts
    same_failure_repeat

不足。

### 增加：

记录：

    test pass delta

    failure count delta

    code diff

    new files inspected

    new evidence

判断：

    progress

    stalled

    regression

避免无限修错。

------------------------------------------------------------------------

# Priority 4：补 JD 高频能力

## 10. Docker Sandbox

### 当前：

已有：

-   Guard
-   Permission

但不是完整隔离。

### 增强：

加入：

    Docker execution sandbox

    filesystem isolation

    resource limit

    network restriction

形成：

    Agent Runtime
    +
    Safe Code Execution

------------------------------------------------------------------------

## 11. vLLM 接入

目标：

补：

-   Model Serving
-   OpenAI-compatible API
-   latency benchmark

实践：

    Qwen
    ↓
    vLLM server
    ↓
    R-Code Provider

测试：

    TTFT
    tokens/s
    concurrency

------------------------------------------------------------------------

## 12. 服务化部署

如果投：

-   AI 应用开发
-   Agent 平台

建议补：

    FastAPI

    Session API

    SSE streaming

    Redis task queue

    Docker deployment

------------------------------------------------------------------------

# 不建议当前投入

## 1. 不建议继续增加 Agent 功能

例如：

-   更多 Skill
-   更多 Tool
-   更多 Agent 类型

原因：

当前功能已经足够丰富。

短板不是能力数量，而是：

    可靠性
    +
    评测
    +
    实验

------------------------------------------------------------------------

## 2. 不建议强行加入 RAG

Coding Agent 不需要为了匹配 JD 硬加：

-   Milvus
-   Embedding
-   Vector DB

更合理：

用 Text-to-SQL 项目证明 Retrieval 能力。

------------------------------------------------------------------------

# 最终面试版本目标

完成后项目故事：

    问题：
    Coding Agent 完成判断依赖模型自觉，失败恢复弱。

    方案：
    设计 Verification-gated Finish。

    进一步：
    利用 Failure Parser 和 Repository Retrieval
    构建 Failure-aware Repair Loop。

    工程保障：
    加入 Runtime、安全、Context、Memory、Trace。

    实验：
    Benchmark + Ablation 证明提升。

最终定位：

> 面向仓库级软件工程任务的可验证 Code Agent Runtime。

------------------------------------------------------------------------

## P0 实施状态（2026-08-23）

P0 三项的最小侵入版本已完成：`VerificationExecutor`、结构化 outcome 与稳定
fingerprint、以及 Repair Loop benchmark 的任务/profile/record/summary 基座。
`core/loop.py` 未增加 capability-specific 分支；`RepairLoopGate` 仍是唯一的
FinishGate 实现，新的执行与实验策略通过 services 依赖注入。

验证结果：

    python -m pytest tests/test_repair_services.py tests/test_repair_loop.py
    tests/test_verification_executor.py tests/test_repair_benchmark.py
    tests/test_attachment_projector.py tests/test_cli_resume.py
    tests/test_runtime_integration.py tests/test_import_boundaries.py -q

    33 passed

    python -m compileall core services benchmarks

    completed without syntax errors

全量 `python -m pytest tests -q` 在 collection 阶段因当前环境缺少
`tree_sitter_bash` 而中断（13 个 Bash/CLI 相关模块），尚未执行到本次新增测试。
这不是 Repair Loop 的回归；在完成 `uv sync --dev` 或安装该测试依赖后应重跑全量
套件。下一步应选择实际 provider 并实现 benchmark adapter：为每个 task/profile
复制干净工作区、运行模型并写入 JSONL `BenchmarkRun`，再以本基座生成 ablation
报告。
