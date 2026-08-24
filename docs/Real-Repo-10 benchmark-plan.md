
请新增独立的 `Real-Repo-10` benchmark，用真实 GitHub issue 验证 R-Code 的端到端代码修复能力。不要修改生产 AgentLoop、Memory、Context、Repair、Recovery 逻辑，除非发现影响评测正确性的 bug。

目标链路：

`真实 GitHub issue`
→ `定位对应 fix PR / commit`
→ `取修复前 parent commit 作为 base_commit`
→ `验证 base_commit 上 issue 可复现`
→ `创建干净 workspace`
→ `仅把 issue description + repo workspace 交给 R-Code`
→ `R-Code 用自己的 Harness 自主定位与修改`
→ `运行固定 verifier`
→ `导出 git diff`
→ `保存 artifact`
→ `汇总 Real-Repo-10 report`

一、建立目录

新建：

`benchmarks/real_repo/`

建议包含：

`cases.json`
`case_builder.py`
`workspace.py`
`runner.py`
`verifier.py`
`report.py`
`types.py`

二、挑选 10 个真实 issue

优先条件：

* Python 项目；
* 开源 GitHub repo；
* issue 已有明确 merged fix PR；
* 修复范围较小到中等；
* 测试命令清晰；
* 本地依赖可安装；
* 不依赖大型数据库、GPU、浏览器、云服务；
* 避免只改文档、纯格式、版本号等无意义任务。

第一版优先从 Flask / Click 等轻量仓库选择。

每个 case 固定保存：

* `case_id`
* `repo`
* `issue_number`
* `issue_url`
* `problem_statement`
* `fix_pr`
* `fix_commit`
* `base_commit`
* `verifier_command`
* `category`
* `expected_scope`
* `environment_notes`

三、自动确定 base_commit

不要手写 base_commit。

对每个 issue：

1. 找到对应 merged fix PR；
2. 获取真正包含修复的 commit；
3. 将修复 commit 的 parent commit 作为 `base_commit`；
4. checkout base_commit；
5. 验证问题在 base_commit 上确实存在；
6. 应用官方 fix patch 后应能通过 verifier。

只有满足：

`base_commit → FAIL`
`official fix → PASS`

才允许纳入 Real-Repo-10。

否则标记为 `invalid_case`，不要强行纳入。

四、构建干净 workspace

每次 run：

* clone 或复用只读 repo cache；
* checkout 指定 `base_commit`；
* 创建独立工作副本；
* 清除未跟踪文件和历史修改；
* 不允许 repetition 之间共享修改后的 workspace；
* 保存：

  * repo URL
  * commit SHA
  * workspace fingerprint
  * Python version
  * dependency metadata

五、Agent 输入约束

Agent 只允许看到：

* issue 的原始 `problem_statement`
* 当前 repo workspace
* 正常 production system prompt
* production-aligned coding tools

不得提供：

* 目标文件路径
* gold patch
* fix PR 内容
* fix commit diff
* 人工定位提示
* verifier 预期答案
* “应该修改哪个函数”之类提示

六、使用 R-Code 自己的 Harness

必须走现有生产执行链：

`RealModelAdapter`
→ `AgentLoop`
→ `Context`
→ `Memory`
→ `Guard`
→ `glob / grep / read_file / edit_file / write_file`
→ `Repair / verifier`
→ `Trace / Transcript`

不要让 benchmark 自己直接修改代码。

七、预算

每个 case 固定 benchmark-only 预算：

* `max_model_calls`
* `max_tool_steps`
* `max_wall_clock`
* `provider_timeout`

预算参数写入 case/run artifact。

超限必须正常生成 BenchmarkRun，不得中断整个批次。

failure taxonomy 至少包括：

* `provider_timeout`
* `provider_error`
* `model_call_budget_exceeded`
* `tool_budget_exceeded`
* `wall_clock_budget_exceeded`
* `checkout_failed`
* `dependency_failed`
* `environment_blocked`
* `empty_patch`
* `verifier_failed`
* `regression_failed`
* `invalid_case`

八、Verifier

每个 case 使用固定 verifier command。

原则：

* verifier 在选 case 阶段先人工/自动验证过；
* 优先运行目标测试或最小相关测试集；
* 不默认跑整个大型 test suite；
* 必要时再补相关 regression tests；
* verifier 必须独立于 Agent 的 final answer；
* Agent 说“修好了”不能作为 success。

成功条件：

* patch 非空；
* verifier 返回 0；
* 目标 bug 被修复；
* 必要 regression tests 仍通过；
* 任务没有因 provider/environment/budget 异常终止。

九、导出 patch

Agent 完成后执行：

`git diff --no-ext-diff`

保存为：

`model_patch`

每条 run 保存：

* issue metadata
* base_commit
* model/config
* prompt
* transcript
* trace
* tool events
* model calls
* tool steps
* token usage
* latency
* git diff
* verifier command
* stdout/stderr
* exit code
* terminal outcome
* failure kind

十、先做 3-case environment smoke

不要直接跑 10 个正式任务。

先挑 3 个最轻的 case：

`3 cases × 1`

目标只验证：

* repo checkout
* dependency install
* Agent 自主导航
* edit
* verifier
* patch export
* artifact
* failure classification

若某个 case 环境无法稳定复现：

标记 `environment_blocked` 或 `invalid_case`，然后换一个候选 issue。

十一、固定 Real-Repo-10

3-case smoke 稳定后，筛选出最终 10 个 case。

一旦冻结，不再因为 Agent 做不出来而替换 case。

允许因为以下原因替换：

* base_commit 无法复现 bug；
* verifier 不可靠；
* 依赖无法稳定安装；
* issue 实际不是代码修复；
* 仓库环境不可重复。

禁止因为“模型失败”而换 case。

十二、第一轮正式验证

先跑：

`10 cases × 1`

目的：

* 确认 10 个任务都能完整进入 evaluator；
* 找出 environment/provider 类异常；
* 不作为最终稳定性结论。

记录：

* resolved
* failure kind
* tool steps
* model calls
* tokens
* latency
* verifier attempts

十三、正式重复实验

只有 10×1 流程稳定后，再跑：

`10 cases × 3`

固定：

* model
* provider
* stream mode
* temperature
* max tokens
* budgets
* base_commit
* verifier

不得在三次重复之间修改 prompt 或机制。

十四、最终统计

生成：

`benchmark-results/real-repo-10/report.json`
`docs/reports/YYYY-MM-DD-real-repo-10.md`

至少统计：

* resolved rate
* per-case success rate
* mean/std model calls
* mean/std tool steps
* mean/std tokens
* mean/std latency
* failure distribution
* environment failure rate
* provider failure rate
* navigation failure
* verifier failure

同时列出每个 case：

`repo / issue / base_commit / verifier / 3-run result`

十五、结果解释边界

Real-Repo-10 只用于证明：

`真实 issue → 自主定位 → 代码修改 → 验证`

不要用它单独证明：

* Memory 的因果收益
* Compaction 的因果收益
* Recovery 的因果收益

这些继续由现有 internal mechanism benchmark 支撑。

最终项目评测结构固定为：

`Internal synthetic benchmark`
→ 证明 Harness 机制

`Real-Repo-10`
→ 证明真实仓库端到端能力

两者成功率禁止合并。

十六、不要继续扩机制

执行 Real-Repo-10 过程中：

* provider failure → 分类并记录；
* environment failure → 分类并记录；
* model failure → 保留；
* 只有 benchmark 本身判定错误、artifact 丢失、verifier 错误时才修 benchmark；
* 不要为了提高通过率修改 production AgentLoop、Memory、Context、Repair、Recovery。

最终目标：

`10 个真实 GitHub issue + 固定 base_commit + 自主导航 + R-Code Harness + verifier + 3× 重复 + 完整 artifacts`

## Validation Log

### 2026-08-24 — Candidate discovery and first checkout attempt

- Candidate: `pallets/click` issue [#2939](https://github.com/pallets/click/issues/2939),
  linked merged PR [#2940](https://github.com/pallets/click/pull/2940).
- The issue supplies a small Python reproducer; the PR states that it fixes
  #2939, so it is eligible for local base/official-patch validation.
- A temporary clone to `/private/tmp/r-code-real-repo-click` failed before any
  checkout or test with `RPC failed; curl 18`, `early EOF`, and
  `invalid index-pack output`.
- Status: `checkout_failed` (transient candidate-validation infrastructure
  failure). No base commit, verifier result, or model run was recorded; the
  candidate is not yet `invalid_case` and must be retried or replaced only
  after a repeat checkout failure.

形成可以直接用于简历和面试的真实代码仓库评测证据。
