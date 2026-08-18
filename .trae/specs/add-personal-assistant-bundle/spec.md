# 个人全能助手插件组合 Spec

## Why
PRD §7.1 v0.1-alpha 验收要求「通过插件组合复现个人/工作助手示例效果」，当前仓库仅有单个示例 Agent（demo-agent-plugin）。需交付「个人全能助手」插件组合——6 个个人向 Agent 插件 + 2 个工具插件（文件写入、结构化账本） + 1 个预置快照，验证「一切皆插件、组合即场景」的架构能力，不引入任何硬编码业务模式。

## What Changes
- 新增 6 个 `backend_agent` 插件（`plugins/` 下各自独立目录，遵循插件开发指南 §3 代码契约）：
  - `personal-life-agent` 生活问答智能体（priority 40，通用兜底）
  - `personal-kb-review-agent` 知识复盘智能体（dependencies: `kb-retrieval-tool`）
  - `personal-organize-agent` 个人整理智能体
  - `personal-writing-agent` 文档写作智能体
  - `personal-code-agent` 代码辅助智能体
  - `personal-finance-agent` 智能记账理财分析智能体（dependencies: `finance-ledger-tool`）
- 新增 2 个 `backend_tool` 插件：
  - `file-write-tool`（经 `ctx.fs` 写入 `data/generated_docs` 白名单目录）
  - `finance-ledger-tool`（结构化账本工具：add 记账 / query 查询 / stats 统计）
- 修改 `backend/nvwa_agent/core/snapshot.py` 的 `ensure_preset_snapshots()`：新增第三个预置快照「预置·个人全能助手」
- 不新建 UI 插件：6 个 Agent 的 `bind_ui_plugin_id` 统一绑定现有 `demo-ui-think-visualizer`，在 `demo-ui-chat` 对话页直接使用
- 更新 `dev-doc/NvwaAgent-插件开发指南.md` §7 示例插件一览表（追加 8 行）

## Impact
- Affected code: `plugins/`（新增 8 个插件目录）、`backend/nvwa_agent/core/snapshot.py`（预置快照清单 + 预置 enabled 修正 + apply_snapshot 激活顺序修复）、`plugins/demo-file-tool/main.py`（仅参数描述路径示例修正 `data/uploads/...`）、`backend/tests/`（新增 2 个工具测试文件）、`dev-doc/NvwaAgent-插件开发指南.md`（示例表格）
- 不修改核心运行时、调度器、SDK、前端基座
- 无 BREAKING 变更：已有数据库预置快照早退逻辑保持不变（AgentProfile 表非空则不重复初始化）

## ADDED Requirements

### Requirement: 个人向 Agent 插件集（6 个）
系统 SHALL 提供 6 个独立自包含的 `backend_agent` 插件，均继承 `BaseAgentPlugin`、实现 `build_graph`（复用 demo-agent-plugin 的 ReAct 单循环模式：think→tool_call→final，工具调用协议为单独一行 `{"tool_call": {...}}` JSON），通过差异化 `system_prompt` 与 `description` 实现职责区分（description 参与意图识别）。

| 插件 id | 职责 | 工具引导 | model_params.temperature | priority |
| --- | --- | --- | --- | --- |
| personal-life-agent | 通用生活类问答 | 直接回答为主，涉及用户私有资料时可调用知识库检索 | 0.7 | 40 |
| personal-kb-review-agent | 知识库内容总结、复盘、问答 | 回答前必须先 `kb-retrieval-tool:search` 检索，基于检索原文作答，知识库为空时提示上传 | 0.3 | 50 |
| personal-organize-agent | 笔记、资料归纳整理 | 读取 uploads 资料（`demo-file-tool:read_text`，path 如 `data/uploads/xxx.txt`），整理结果保存至 `data/generated_docs`（`file-write-tool:write_text`） | 0.3 | 50 |
| personal-writing-agent | 文档生成、润色、改写 | 成稿经用户确认后可调用 `file-write-tool:write_text` 保存 | 0.8 | 50 |
| personal-code-agent | 代码生成、解释、调试辅助 | 需要查看用户上传的代码文件时调用 `demo-file-tool:read_text` | 0.3 | 50 |
| personal-finance-agent | 智能记账、消费统计、理财分析 | 记账/查询/统计必须调用 `finance-ledger-tool:ledger`（action=add/query/stats），基于统计结果输出消费结构分析与预算建议；绝不凭空编造账目数据 | 0.3 | 50 |

约束：
- 每个插件目录含 `plugin.json` + `main.py`，单文件 <300 行，`on_load` 返回插件实例
- `bind_ui_plugin_id` 统一为 `demo-ui-think-visualizer`
- 插件自包含可拷贝（不跨插件 import Python 代码），ReAct 图代码随插件目录复制

#### Scenario: 意图匹配（真实推理）
- **WHEN** 已激活 personal-writing-agent，用户提交「帮我写一封请假邮件」
- **THEN** 核心调度器意图识别选中 personal-writing-agent 执行，`task:start`→`agent:think`（流式）→`task:finish` 携带最终答案

#### Scenario: 意图选取（mock 模式）
- **WHEN** mock_mode_enabled=true 且多个 Agent 激活
- **THEN** 意图识别按 priority 取最大者（生活问答 40 不压过专业 Agent）；仅激活单个 Agent 时必选该 Agent，可用于逐个验证

#### Scenario: 知识复盘依赖校验
- **WHEN** kb-retrieval-tool 未加载/未激活时激活 personal-kb-review-agent
- **THEN** 依赖校验失败，插件拒绝激活进 fault（dependencies 语义）

#### Scenario: 记账理财链路
- **WHEN** 用户提交「记一笔：今天午饭花了 35 元」或「这个月消费分析一下」
- **THEN** personal-finance-agent 被选中，经 `finance-ledger-tool:ledger`（action=add / action=stats）完成记账或统计，`tool:call`/`tool:result` 事件推送，最终基于真实账本数据输出分析与建议

### Requirement: file-write-tool 文件写入工具
系统 SHALL 提供全局 `backend_tool` 插件 `file-write-tool`：
- `tool_name = "file-write-tool:write_text"`
- `parameters_schema`：`path`（相对仓库根，如 `data/generated_docs/x.md`，必填）、`content`（文本内容，必填）
- `execute` 经 `ctx.fs.write_text` 写入（白名单约束由 SDK 文件访问器保证）
- 成功返回写入文件相对路径；参数缺失返回 `TOOL_EXEC_ERROR`；路径穿越返回 `FILE_PERMISSION_DENIED`

#### Scenario: 正常写入
- **WHEN** args = `{"path": "data/generated_docs/note.md", "content": "..."}`
- **THEN** 文件写入 `data/generated_docs/note.md`，ToolResult.success 返回路径，`tool:result` 事件推送

> 路径约定：`ctx.fs` 相对路径基于仓库根解析，白名单默认为 `data/uploads`、`data/generated_docs`，故工具示例路径一律带 `data/` 前缀。

#### Scenario: 越权拒绝
- **WHEN** args.path = `../evil.txt` 或绝对路径穿越白名单
- **THEN** 返回 `ToolResult.failure("FILE_PERMISSION_DENIED", …)`，转 `tool:error` 事件

### Requirement: finance-ledger-tool 结构化账本工具
系统 SHALL 提供全局 `backend_tool` 插件 `finance-ledger-tool`：
- `tool_name = "finance-ledger-tool:ledger"`，单工具多动作（action 参数）：
  - `add`：追加一条记账记录，参数 `amount`（正数，必填）、`type`（`income`/`expense`，必填）、`category`（如 餐饮/交通/工资，必填）、`note`（备注，可选）、`date`（`YYYY-MM-DD`，缺省今天）
  - `query`：按 `month`（`YYYY-MM`，可选，缺省当月）与 `category`（可选）过滤返回记录列表
  - `stats`：按 `month`（可选）汇总——总收入、总支出、净结余、支出分类排行
- 账本持久化：JSON 文件 `data/generated_docs/finance_ledger.json`（`ctx.fs` 白名单目录内，格式 `{"records": [...]}`），读取失败/文件不存在按空账本处理，写入全量落盘
- 校验：action 非法或必填参数缺失/类型不符 → `TOOL_EXEC_ERROR`；金额非正数 → `TOOL_EXEC_ERROR`
- 并发安全依赖系统既有 FIFO 串行任务队列（单任务串行执行，无并发写风险）
- 返回结构：`add` 返回确认与记录内容；`query`/`stats` 返回可读文本摘要（含金额，保留两位小数）

#### Scenario: 记账与统计闭环
- **WHEN** action=add 记录「午餐 35 元 餐饮」，随后 action=stats 查询当月
- **THEN** 统计结果包含该笔支出（总支出含 35.00，餐饮分类计数正确），账本文件持久化

#### Scenario: 非法参数拒绝
- **WHEN** action=add 且 amount=-10，或 action=delete
- **THEN** 返回 `TOOL_EXEC_ERROR`，账本不被修改

#### Scenario: 空账本容错
- **WHEN** 账本文件不存在时执行 action=query/stats
- **THEN** 返回「账本为空」类提示，不报错（`ToolResult.success`）

### Requirement: 「个人全能助手」预置快照
`ensure_preset_snapshots()` SHALL 在原有 2 个预置快照基础上新增第三个「预置·个人全能助手」：
- 启用（enabled=true）：6 个 `personal-*-agent`（含 personal-finance-agent）、`file-write-tool`、`finance-ledger-tool`、`demo-file-tool`、`kb-retrieval-tool`、`demo-ui-chat`、`demo-ui-think-visualizer`、`demo-ui-plugins`、`demo-ui-config`、`demo-ui-kb`、`demo-ui-replay`、`demo-ui-snapshot`、`demo-ui-tools`
- 不含 `demo-agent-plugin`（快照加载后按全量覆盖语义禁用）

#### Scenario: 一键切换组合
- **WHEN** 用户在快照管理页加载「预置·个人全能助手」
- **THEN** 快照内插件全部激活、不在快照内的已激活插件全部禁用（PRD §3.5 全量覆盖），demo-ui-chat 正常对话并由个人向 Agent 处理任务

#### Scenario: 既有数据库兼容
- **WHEN** 服务启动时 AgentProfile 表已有记录
- **THEN** 不重复初始化预置快照（保持现有 count>0 早退逻辑）

### Requirement: mock 模式端到端可验证
所有新插件 SHALL 在 `mock_mode_enabled=true` 下完成端到端链路验证：扫描 → 加载快照激活 → 提交多类任务 → SSE 事件（task:start/agent:think/tool:call/tool:result/task:finish）→ 任务结果持久化 → 文件落盘（涉及写入工具时）。

## MODIFIED Requirements

### Requirement: 预置快照初始化（ensure_preset_snapshots）
原：首次启动预置 2 个快照（预置·纯对话模式 / 预置·知识库增强模式）。
改：首次启动预置 3 个快照，新增「预置·个人全能助手」（启用清单见上）；显式清单型预置快照内的插件 `enabled` 强制置 true（构建时全部插件未激活，采集值恒为 false，需显式置位才能实现"一键加载组合"）。
迁移：已有数据库不受影响；老库用户可手动导入同名快照 JSON 或删除快照记录后重启重建预置。

### Requirement: 快照应用顺序（apply_snapshot）
原：按 backend_agents → backend_tools → ui_plugins 顺序激活，Agent 声明 `dependencies=[工具id]` 时工具尚未激活，依赖校验失败将 Agent 误标 fault。
改：激活顺序固定为 backend_tools → ui_plugins → backend_agents（依赖方向：Agent 依赖工具），保证带依赖的 Agent 可被快照正确激活。

## REMOVED Requirements
无
