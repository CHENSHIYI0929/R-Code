
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

### 2026-08-24 — Repeat checkout attempt

- Removed the incomplete temporary clone and retried with `git clone --depth
  200`.
- The retry failed before checkout with `Error in the HTTP2 framing layer`.
- Status remains `checkout_failed`, not `invalid_case`: both failures occurred
  before repository content, base commit selection, dependency installation,
  or verifier execution. This is a GitHub transport blocker shared by any
  candidate cloned through the same path.

### 2026-08-24 — Click #2939 validation result

- `REPO_URL`: `https://github.com/pallets/click.git`
- Official PR: #2940; actual small fix commit:
  `93c6966eb3a575c2b600434d1cc9f4b3aee505ac`.
- `BASE_COMMIT`: `b63239d657aab7c4e04667a62e7177f617b37230`.
- Minimal fetch, parent-object checks, and detached base checkout succeeded.
  The selected fix patch only touches `CHANGES.rst`, `src/click/testing.py`,
  and `tests/test_chain.py`.
- Install command: `uv sync --dev` in an isolated workspace (Python 3.13.9,
  Click 8.2.1). Verifier: `uv run pytest tests/test_chain.py::test_pipeline -q`.
- Base result: **PASS** (`3 passed in 0.02s`), not the required FAIL.
- Status: `invalid_case` because the chosen repository test does not reproduce
  the issue at this base. The official patch was intentionally not applied:
  `base FAIL -> official patch PASS` cannot be established. No model run or
  smoke-manifest entry was created.

### 2026-08-24 — Revised verifier admission result

- The admission rule is `reliable verifier -> base FAIL -> official source fix
  PASS`. The official regression assertion from `tests/test_chain.py` was
  applied to the base without applying the source fix.
- Base result: `3 failed`, each exposing the reported `SystemExit(1)`.
- Applying only the official `src/click/testing.py` patch and re-running the
  identical verifier produced `3 passed`.
- Status: **admitted** as `click-2939`; it is recorded immediately in
  `benchmarks/real_repo/smoke_manifest.json`. The regression patch and source
  patch are evaluator-only validation material and must not be exposed to the
  agent.

### 2026-08-24 — Flask #1559 candidate fetch status

- Official metadata uniquely resolves fix commit
  `8bb34bd251f326e1b901c0219cbaf569d22c5711` and parent
  `7f3867491570746a4c14bdaa5bd59ec1b64cbfea`; the commit message explicitly
  fixes #1559 and changes only `flask/app.py` plus its regression test in
  `tests/test_basic.py`.
- Three minimal `depth=2` fetch attempts were made after removing the dead Git
  proxy: two HTTP/1.1 attempts returned `Empty reply from server`; a one-shot
  HTTP/2 attempt could not connect to GitHub port 443. No Git objects were
  received.
- Status: `checkout_failed`, not `invalid_case`. Commit identity is resolved,
  but base checkout, dependency installation, and `base FAIL -> official fix
  PASS` remain unverified. No model call or manifest entry was created.

### 2026-08-24 — Jinja #515 validation result

- Official fix commit: `8189d2164dd671c7607771cc132c684f512b8bee`;
  base parent: `f51862d6ca2bf32b315350ac61e4eb1e91ee6801`.
- Minimal fetch, object checks, and detached base checkout succeeded. The
  official source change is a one-line correction in `jinja2/utils.py`.
- Isolated environment: Python 3.9.25 and MarkupSafe 2.0.1. Python 3.13 and
  3.10 compatibility errors were treated as environment errors, not base
  failures.
- Behavioral oracle calls `unicode_urlencode('/', for_qs=True)` and requires
  `%2F`. Base returned `/` (FAIL); the identical oracle after applying only the
  official source fix returned `%2F` (PASS).
- Status: **admitted** as `jinja-515` and immediately recorded in
  `benchmarks/real_repo/smoke_manifest.json`. The oracle and gold metadata are
  evaluator-only and must not enter agent input.

### 2026-08-24 — Werkzeug #2467 validation result

- Official merged PR #2468 resolves to merge commit
  `76ccf1f107e0d34bbf88227fc30dfab42c080456`; first parent base is
  `7ae6bc12fa9b99c942f4f04022a175426a8414e9`.
- Minimal fetch and checkout succeeded. The official regression addition to
  `test_strict_slashes_leaves_dont_consume` fails on base with `NotFound`.
- Applying only the official routing source changes and re-running the same
  test passes (`1 passed`). Environment: Python 3.10.20, pytest 7.1.2, and the
  repository's minimal conftest dependencies.
- Status: **admitted** as `werkzeug-2467` and immediately recorded in the
  smoke manifest; evaluator test changes and gold metadata remain hidden.

### 2026-08-24 — Werkzeug #2471 validation result

- Official merged PR #2472 resolves to
  `cdee5ce61b47b3cdf5f1452a457badb18549f162`; base is
  `5c85706a35fa7122839fe2572747dccf32e9912d`.
- The official `test_path_weighting` regression test selected the wrong
  `complex` route on base (FAIL). Applying only the official source change in
  `routing/rules.py` made the identical test pass.
- Status: **admitted** as `werkzeug-2471`; environment and hidden-evaluator
  policy are identical to the adjacent Werkzeug case.

### 2026-08-24 — Werkzeug #2485 validation result

- Official PR #2497 resolves to
  `bebf46d336782e70510f00e3a08db1e1453ce68a`; base is
  `fe8a56e9e348e8ae97ce826368301becea8a3d74`.
- The official `test_proxy_wrapped` regression fails on base with
  `RuntimeError: object is not bound`. Applying only the official
  `src/werkzeug/local.py` fix makes the identical test pass.
- Status: **admitted** as `werkzeug-2485` and frozen in the manifest.

### 2026-08-24 — Werkzeug #2993 validation result

- Official PR #2997 resolves to
  `ba15683fb30b51187fa7efa9d212a030ad6ddb94`; base is
  `ea93b549a93f65b216070e72a26cf0cc31d1e9ad`.
- A behavioral oracle derived from the official regression requires an IPv6
  server host to be bracketed. Base returned `::1:8080` (FAIL); applying only
  the official `sansio/utils.py` source fix returned `[::1]:8080` (PASS).
- Status: **admitted** as `werkzeug-2993` and frozen in the manifest.

### 2026-08-24 — Werkzeug #2994 validation result

- Official PR #2995 resolves to
  `ea93b549a93f65b216070e72a26cf0cc31d1e9ad`; base is
  `1a1728ed88939ca68928dade168e1989be062c6f`.
- The behavioral oracle derived from the official regression shows base
  expanding `b"ab"` into integer values 97 and 98 (FAIL). Applying only the
  official datastructure source changes preserves the bytes value (PASS).
- Status: **admitted** as `werkzeug-2994` and frozen in the manifest.

### 2026-08-24 — Werkzeug #2985 validation result

- Official PR #2986 resolves to
  `64d27f79eb84880b33f4451e078dab0b49c4c2c2`; base is
  `d1f60d68ac9788aec05712aca29867abd00d5cc3`.
- The official-regression-derived oracle shows `str(EnvironHeaders(...))`
  returning only CRLF on base (FAIL). Applying only the official headers
  source fix renders both headers and the final CRLF (PASS).
- Status: **admitted** as `werkzeug-2985` and frozen in the manifest.

### 2026-08-24 — Werkzeug PR #2843 validation result

- Official merged PR/fix `f516c4005c7c4510b61ae07969450771b929809d`;
  base `4c09d1b3b08deb939803a4beb53483cbc54dfb8d`.
- The official-regression-derived oracle raises `TypeError` on base when a
  converter receives `None` (FAIL). Applying only the official source fix
  returns the requested default `-1` (PASS).
- Validation itself passed, but the candidate is **not admitted**: #2843 is a
  fix PR without a separate issue description, so using its body as agent input
  would violate the no-gold-leakage policy.

### 2026-08-24 — Werkzeug PR #2470 validation result

- The already fetched official merge commit
  `5c85706a35fa7122839fe2572747dccf32e9912d` has base
  `76ccf1f107e0d34bbf88227fc30dfab42c080456`.
- Its official regression test shows the base partially matching a UUID path
  as integer route value `2` (FAIL). Applying only the official one-file
  routing source fix selects the UUID route and passes.
- Validation itself passed, but the candidate is **not admitted**: #2470 is a
  fix PR without a separate issue description.

### 2026-08-24 — Strict-set audit

- Strictly admitted cases: `click-2939`, `jinja-515`, `werkzeug-2467`,
  `werkzeug-2471`, `werkzeug-2485`, `werkzeug-2993`, `werkzeug-2994`,
  `werkzeug-2985`, `werkzeug-2465`, and `werkzeug-2988` (10 total).
- Every admitted entry has a fixed official commit and checkoutable base plus an
  independently observed `base FAIL -> official source fix PASS` result.
- Flask #1559 and Werkzeug #2831/#2834 remain transport-blocked alternates.
  PR-only #2843/#2470 are excluded to preserve the issue-description-only
  agent-input rule.

### 2026-08-24 — Werkzeug #2465 validation result

- Official source commit
  `364d9c2a90f02815347c0a998cf0f31ebf6a3ee5`; base
  `fa76cbe1de42a89d3c7e59121341c6bd975b7007`.
- The documented public import `from werkzeug.routing import ValidationError`
  raises `ImportError` on base (FAIL). Applying the official one-line export
  makes the identical oracle pass.
- Status: **admitted** as `werkzeug-2465`; strict set is now 9 cases.

### 2026-08-24 — Werkzeug #2988 validation result

- Official PR #2990 resolves to
  `13170140d383404a2ee98dd2740d00061d3f5b10`; base is
  `f27e476144f973d2bc3df42cfd562be4c33bbcfe`.
- The issue's public callable example produces the expected mypy overload error
  on base. After applying only the official source patch, the identical oracle
  reports zero errors.
- Status: **admitted** as `werkzeug-2988`, completing the strict 10-case set.

### 2026-08-24 — Real-Repo-10 1x non-stream smoke result

- Formal transport configuration is `stream=false`. `stream=true` repeatedly
  hung in the provider SSE body-read phase and was excluded as a transport
  failure, not a model-capability result.
- The frozen 10-case set ran once through isolated base worktrees with the
  production runtime tool registration and evaluator-owned verifiers.
- Integrity: 10/10 records, verifier outputs, patches, traces, and transcripts
  were retained. Interrupted stream attempts are not included.
- Result: 0/10 task success. Failure distribution: four
  `wall_clock_budget_exceeded`, four `provider_timeout`, and two
  `model_call_budget_exceeded`.
- Mean (std): 4.9 (2.7) tool calls, 28,171.8 (26,670.3) tokens, and
  58,624.9 ms (17,227.4 ms) latency. Every evaluator correctly observed a
  still-failing base-derived workspace.
- Status: paused after 1x smoke by request; do not start 10x3. Full findings
  are in `docs/reports/2026-08-24-real-repo-10-smoke.md`.

形成可以直接用于简历和面试的真实代码仓库评测证据。
