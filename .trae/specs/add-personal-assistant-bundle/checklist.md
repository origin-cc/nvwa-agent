# Checklist

## 插件实现
- [x] plugins/ 下新增 6 个 personal agent 插件，plugin.json 符合开发指南 §2 规范（id=目录名、name/version/type/description/author/priority/model_params/bind_ui_plugin_id/lifecycle 齐全）
- [x] 6 个 Agent main.py 均继承 BaseAgentPlugin、实现 build_graph（ReAct 单循环 think→tool_call→final），on_load 返回插件实例，单文件 <300 行（128–137 行）
- [x] 各 Agent system_prompt 差异化人设，description 面向意图识别可区分（含场景关键词）
- [x] personal-kb-review-agent 的 dependencies 声明 ["kb-retrieval-tool"]；快照加载时依赖工具先激活，未出现 fault
- [x] personal-finance-agent 的 dependencies 声明 ["finance-ledger-tool"]；记账/查账/统计仅经 finance-ledger-tool:ledger，分析必须基于工具返回数据
- [x] file-write-tool：tool_name="file-write-tool:write_text"，经 ctx.fs.write_text 写入；路径穿越返回 FILE_PERMISSION_DENIED；缺参数返回 TOOL_EXEC_ERROR；成功返回写入路径
- [x] finance-ledger-tool：action=add/query/stats 三动作；账本 data/generated_docs/finance_ledger.json（{"records":[...]}）；文件不存在按空账本；非法 action/负数金额/缺必填参数→TOOL_EXEC_ERROR；空账本 query/stats 返回 success 提示；stats 输出总收入/总支出/净结余/支出分类排行（两位小数）
- [x] 所有新插件自包含（无跨插件 Python import、无构建步骤），可直接拷贝部署

## 预置快照
- [x] ensure_preset_snapshots() 预置第三个快照「预置·个人全能助手」，启用清单 = 6 personal agents + file-write-tool + finance-ledger-tool + demo-file-tool + kb-retrieval-tool + 8 个 demo-ui-* 插件（e2e 验证 applied=18）
- [x] demo-agent-plugin 不在快照内（加载后按全量覆盖语义被禁用，e2e 验证）
- [x] AgentProfile 表已有记录时不重复初始化（count>0 早退逻辑未被破坏）
- [x] 显式清单型预置快照内插件 enabled 强制置 true（修复构建时全 false 导致加载后零激活）
- [x] apply_snapshot 激活顺序修复为 工具→UI→Agent（修复带依赖 Agent 被误标 fault）

## 验证
- [x] backend pytest 全量通过（120 passed），新增 test_file_write_tool.py 覆盖 成功写入 / 路径越权 / 缺参数（5 用例）
- [x] 新增 test_finance_ledger_tool.py 覆盖 记账+统计闭环 / 非法 action 与负数金额 / 空账本容错 / query 过滤 / 跨月（7 用例）
- [x] mock 模式端到端：插件扫描识别 8 个新插件（共 21）→ 预置快照 3 个 → 加载后全部激活 → 任务 task:finish 事件与最终答案持久化
- [x] file-write-tool 经真实 FileAccessor 落盘成功 + 越权路径 FILE_PERMISSION_DENIED 拒绝
- [x] finance-ledger-tool 经真实 FileAccessor 记账落盘（finance_ledger.json 35 元餐饮）+ stats 返回含 35.00
- [x] 仅激活 personal-finance-agent 时 mock 意图必选该 agent（agent:think 事件验证）

## 范围控制
- [x] 未修改核心运行时 / 调度器 / SDK / 前端基座代码（核心改动仅 snapshot.py 预置清单 + enabled 修正 + 激活顺序；另修正 demo-file-tool 两行路径描述示例）
- [x] dev-doc/NvwaAgent-插件开发指南.md §7 表格已追加 8 个新插件行
