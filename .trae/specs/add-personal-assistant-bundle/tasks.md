# Tasks

> Task 1–8 相互独立可并行；Task 9 依赖 Task 1–8 的插件 id 落定；Task 10 依赖全部。

- [x] Task 1: 新增 file-write-tool 工具插件（backend_tool）
  - [x] 创建 `plugins/file-write-tool/plugin.json`（id/file/type/description/author/lifecycle.on_load，对齐 kb-retrieval-tool 结构）
  - [x] 创建 `plugins/file-write-tool/main.py`：继承 BaseToolPlugin，tool_name="file-write-tool:write_text"，经 ctx.fs.write_text 写入；缺参数→TOOL_EXEC_ERROR；PermissionError→FILE_PERMISSION_DENIED；成功返回写入路径
  - [x] 新增 `backend/tests/test_file_write_tool.py`：stub ctx/fs 覆盖 成功写入 / 路径穿越拒绝 / 缺参数 三种用例（5 用例）
- [x] Task 2: 新增 finance-ledger-tool 结构化账本工具（backend_tool）
  - [x] 创建 `plugins/finance-ledger-tool/plugin.json`（结构对齐 kb-retrieval-tool）
  - [x] 创建 `plugins/finance-ledger-tool/main.py`：tool_name="finance-ledger-tool:ledger"，action=add/query/stats；账本 `data/generated_docs/finance_ledger.json`（{"records":[...]}，经 ctx.fs 读写，文件不存在按空账本）；add 参数 amount(正数)/type(income|expense)/category/note/date(缺省今天)；query 按 month/category 过滤；stats 汇总总收入/总支出/净结余/支出分类排行（金额两位小数）；action 非法或参数缺失/金额非正数→TOOL_EXEC_ERROR；空账本 query/stats 返回 success 提示
  - [x] 新增 `backend/tests/test_finance_ledger_tool.py`：覆盖 记账+统计闭环 / 非法 action 与负数金额拒绝 / 空账本容错 / query 过滤 / 跨月不计入（7 用例）
- [x] Task 3: 新增 personal-life-agent 生活问答智能体
  - [x] `plugins/personal-life-agent/plugin.json`：priority=40，temperature=0.7，bind_ui_plugin_id=demo-ui-think-visualizer
  - [x] `plugins/personal-life-agent/main.py`：复用 demo-agent-plugin ReAct 图模式，日常生活助手人设 system_prompt
- [x] Task 4: 新增 personal-kb-review-agent 知识复盘智能体
  - [x] `plugins/personal-kb-review-agent/plugin.json`：dependencies=["kb-retrieval-tool"]，temperature=0.3
  - [x] `plugins/personal-kb-review-agent/main.py`：强制先检索后作答，标注来源，知识库为空提示上传
- [x] Task 5: 新增 personal-organize-agent 个人整理智能体
  - [x] `plugins/personal-organize-agent/plugin.json`：temperature=0.3
  - [x] `plugins/personal-organize-agent/main.py`：读 data/uploads → 结构化整理 → 保存 data/generated_docs
- [x] Task 6: 新增 personal-writing-agent 文档写作智能体
  - [x] `plugins/personal-writing-agent/plugin.json`：temperature=0.8
  - [x] `plugins/personal-writing-agent/main.py`：写作/润色/改写人设，成稿可保存
- [x] Task 7: 新增 personal-code-agent 代码辅助智能体
  - [x] `plugins/personal-code-agent/plugin.json`：temperature=0.3
  - [x] `plugins/personal-code-agent/main.py`：代码生成/解释/调试人设，可读 data/uploads 代码文件
- [x] Task 8: 新增 personal-finance-agent 智能记账理财分析智能体
  - [x] `plugins/personal-finance-agent/plugin.json`：dependencies=["finance-ledger-tool"]，temperature=0.3，bind_ui_plugin_id=demo-ui-think-visualizer
  - [x] `plugins/personal-finance-agent/main.py`：记账/查账/统计必须调用 finance-ledger-tool:ledger，分析基于真实统计数据，禁止编造账目
- [x] Task 9: 预置「个人全能助手」快照 + 文档表格更新
  - [x] 修改 `backend/nvwa_agent/core/snapshot.py` `ensure_preset_snapshots()`：新增第三个预置快照，保持 count>0 早退；显式清单内插件 enabled 强制置 true
  - [x] 修复 `apply_snapshot()` 激活顺序：backend_tools → ui_plugins → backend_agents（否则带依赖 Agent 被误标 fault）
  - [x] 修正 `plugins/demo-file-tool/main.py` 参数描述路径示例（data/uploads/...，原示例在白名单下必然越权）
  - [x] 更新 `dev-doc/NvwaAgent-插件开发指南.md` §7 示例插件一览表追加 8 行
- [x] Task 10: mock 模式端到端验证
  - [x] backend pytest 全量 120 passed（含新增 12 用例）
  - [x] 临时数据库 + mock 模式 TestClient 端到端：扫描识别 8 新插件（共 21）；预置快照 3 个；加载「个人全能助手」applied=18、demo-agent-plugin 全量覆盖禁用；任务链路 task:finish 持久化且 agent:think 命中 personal-code-agent；仅激活 personal-finance-agent 时意图必选该 agent；finance-ledger-tool 记账真实落盘 + stats 含 35.00；file-write-tool 真实落盘 + 越权拒绝

# Task Dependencies
- Task 1–8：可并行（插件目录相互独立）
- Task 9：依赖 Task 1–8（需要最终插件 id 清单）
- Task 10：依赖 Task 1–9
